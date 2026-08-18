"""EXPERIMENT s07: a pure-stdlib BM25 baseline over the repository's files.

Frame (same as the rest of ``experiments/forest_v2``): read-only, stdlib only,
no imports of repository code, no network, no subprocess, no writes.  Nothing
in the production tree may import this module.

WHY THIS EXISTS
---------------
The master plan names BM25 twice: as a required Gate-3 baseline (§10) and as a
kill criterion (§13 — "the full representation does not beat code-only or BM25
retrieval").  A kill criterion that has no implementation cannot fire.  This
module is that implementation: the cheapest honest retrieval baseline, frozen
before any graph-conditioned retriever exists, so the later comparison cannot
grade its own homework.

WHAT IT IS
----------
Textbook Okapi BM25 with

* an identifier-aware tokenizer (snake_case and camelCase are split, and the
  whole identifier is kept as well, so both ``iron_plan_guard`` and ``guard``
  retrieve the same file);
* Lucene's non-negative idf ``ln(1 + (N - df + 0.5) / (df + 0.5))``;
* the standard length normalisation ``k1``/``b`` (defaults 1.2 / 0.75);
* an optional path-token boost: the repo-relative path is tokenised and added
  ``path_weight`` times to the document (default 3).  ``path_weight=0`` gives
  content-only BM25, which is what an ablation should compare against.

WHAT IT IS NOT
--------------
Not a production index (rebuilt from scratch each run, held in RAM, no
incremental update, no stemming, no stopword list, no phrase or field query
syntax).  Query terms are deduplicated, so query-term frequency is ignored —
irrelevant for the short queries the harness issues, wrong for long ones.

s09 CONTRACT
------------
Python::

    import sys
    sys.path.insert(0, str(root / "experiments/forest_v2/s07_bm25"))
    from bm25_index import BM25Index, IndexConfig

    index = BM25Index.build(root)                  # or IndexConfig(...)
    hits = index.search("budget ceiling ledger", k=10)
    ranked_paths = [hit.path for hit in hits]      # repo-relative POSIX

Process boundary (language agnostic)::

    python experiments/forest_v2/s07_bm25/bm25_index.py --root . --k 10 "query"

prints one JSON object with ``"schema": "forest-v2-s07-bm25/1"``.  Both forms
return the same ranking.  Ties break on path ascending, so the ranking is
deterministic for a fixed tree.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import time
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Mapping, Sequence

SCHEMA = "forest-v2-s07-bm25/1"

DEFAULT_EXTENSIONS: tuple[str, ...] = (
    ".py",
    ".pyi",
    ".md",
    ".txt",
    ".rst",
    ".json",
    ".jsonl",
    ".toml",
    ".cfg",
    ".ini",
    ".yaml",
    ".yml",
    ".ps1",
    ".sh",
    ".rs",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".html",
    ".css",
    ".sql",
)

# Same tree without the machine-written artifact dumps (.json/.jsonl).  Offered
# as a preset, not as the default: dropping the data files by default would
# quietly pick a friendlier corpus for the baseline.  A harness that wants
# code+prose only must say so, and say so in its report.
CODE_DOC_EXTENSIONS: tuple[str, ...] = tuple(
    ext for ext in DEFAULT_EXTENSIONS if ext not in {".json", ".jsonl"}
)

DEFAULT_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".idea",
        ".vscode",
        ".obsidian",
        "node_modules",
        ".venv",
        "venv",
        "env",
        "site-packages",
        "target",
        "dist",
        "build",
        ".next",
        ".turbo",
        "coverage",
        "htmlcov",
    }
)

_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
_CAMEL_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+")
_HAS_LETTER_RE = re.compile(r"[A-Za-z]")


@lru_cache(maxsize=None)
def _expand(raw: str, min_token_len: int) -> tuple[str, ...]:
    """Tokens produced by one raw word.  Memoised: source vocabulary repeats hard."""
    out: list[str] = []
    whole = raw.replace("_", "").lower()
    if len(whole) >= min_token_len and _HAS_LETTER_RE.search(whole):
        out.append(whole)
    if "_" in raw or whole != raw:
        parts: list[str] = []
        for chunk in raw.split("_"):
            if chunk:
                parts.extend(_CAMEL_RE.findall(chunk))
        if len(parts) > 1:
            for part in parts:
                low = part.lower()
                if len(low) >= min_token_len and _HAS_LETTER_RE.search(low):
                    out.append(low)
    return tuple(out)


def tokenize(text: str, *, min_token_len: int = 2) -> list[str]:
    """Identifier-aware tokenizer.

    ``BM25Index.build`` -> ``bm25index``, ``bm``, ``25``, ``index``, ``build``.
    The full identifier and its parts are both emitted, so exact-name queries
    and natural-language queries hit the same documents.  Tokens without a
    letter are dropped (line numbers and hashes are noise, not vocabulary).

    The ``whole != raw`` guard is a pure fast path: an all-lowercase word with
    no underscore camel-splits to itself, so the split is skipped, not changed.
    ``token_counts`` must stay equivalent to ``Counter(tokenize(...))`` — a
    test pins that.
    """
    out: list[str] = []
    for raw in _WORD_RE.findall(text):
        out.extend(_expand(raw, min_token_len))
    return out


def token_counts(text: str, *, min_token_len: int = 2) -> Counter:
    """Term frequencies for ``text``; equivalent to ``Counter(tokenize(text))``.

    Collapses in-file word repetition before expansion, which is where the
    indexing time actually goes on a source tree.
    """
    counts: Counter = Counter()
    for raw, occurrences in Counter(_WORD_RE.findall(text)).items():
        for token in _expand(raw, min_token_len):
            counts[token] += occurrences
    return counts


@dataclass(frozen=True)
class IndexConfig:
    """Frozen knobs.  Defaults are the textbook ones; deviations are explicit."""

    k1: float = 1.2
    b: float = 0.75
    path_weight: int = 3
    min_token_len: int = 2
    max_file_bytes: int = 512 * 1024
    max_files: int | None = None
    extensions: tuple[str, ...] = DEFAULT_EXTENSIONS
    skip_dirs: frozenset[str] = DEFAULT_SKIP_DIRS


@dataclass(frozen=True)
class SearchHit:
    rank: int
    path: str
    score: float
    matched_terms: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "rank": self.rank,
            "path": self.path,
            "score": round(self.score, 6),
            "matched_terms": list(self.matched_terms),
        }


@dataclass
class BuildReport:
    """RAW counters from the last build.  Never smoothed, never estimated."""

    files_seen: int = 0
    files_indexed: int = 0
    files_skipped_extension: int = 0
    files_skipped_size: int = 0
    files_skipped_binary: int = 0
    files_skipped_unreadable: int = 0
    bytes_indexed: int = 0
    build_seconds: float = 0.0

    def as_dict(self) -> dict:
        data = dict(self.__dict__)
        data["build_seconds"] = round(self.build_seconds, 3)
        return data


class BM25Index:
    """In-memory BM25 index.  Build once, query many times."""

    def __init__(self, config: IndexConfig | None = None) -> None:
        self.config = config or IndexConfig()
        self.paths: list[str] = []
        self.doc_len: list[int] = []
        self.postings: dict[str, dict[int, int]] = {}
        self.report = BuildReport()
        self._idf_cache: dict[str, float] = {}

    # ---- construction -------------------------------------------------

    @classmethod
    def build(cls, root: str | os.PathLike[str], config: IndexConfig | None = None) -> "BM25Index":
        """Index every eligible file under ``root`` (deterministic walk order)."""
        index = cls(config)
        started = time.perf_counter()
        for path in index._walk(Path(root)):
            index._ingest_file(Path(root), path)
        index.report.build_seconds = time.perf_counter() - started
        return index

    @classmethod
    def from_documents(
        cls,
        documents: Mapping[str, str],
        config: IndexConfig | None = None,
    ) -> "BM25Index":
        """Index an in-memory corpus (``path -> text``).  Used by the tests."""
        index = cls(config)
        started = time.perf_counter()
        for path in sorted(documents):
            index._add(path, documents[path])
            index.report.files_seen += 1
            index.report.files_indexed += 1
            index.report.bytes_indexed += len(documents[path].encode("utf-8"))
        index.report.build_seconds = time.perf_counter() - started
        return index

    def _walk(self, root: Path) -> Iterable[Path]:
        skip = self.config.skip_dirs
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in skip)
            for name in sorted(filenames):
                yield Path(dirpath) / name

    def _ingest_file(self, root: Path, path: Path) -> None:
        report = self.report
        report.files_seen += 1
        if self.config.max_files is not None and report.files_indexed >= self.config.max_files:
            return
        if path.suffix.lower() not in self.config.extensions:
            report.files_skipped_extension += 1
            return
        try:
            size = path.stat().st_size
        except OSError:
            report.files_skipped_unreadable += 1
            return
        if size > self.config.max_file_bytes:
            report.files_skipped_size += 1
            return
        try:
            raw = path.read_bytes()
        except OSError:
            report.files_skipped_unreadable += 1
            return
        if b"\x00" in raw:
            report.files_skipped_binary += 1
            return
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:  # pragma: no cover - defensive
            rel = path.as_posix()
        self._add(rel, raw.decode("utf-8", errors="replace"))
        report.files_indexed += 1
        report.bytes_indexed += len(raw)

    def _add(self, rel_path: str, text: str) -> None:
        cfg = self.config
        counts = token_counts(text, min_token_len=cfg.min_token_len)
        if cfg.path_weight > 0:
            for term, freq in token_counts(rel_path, min_token_len=cfg.min_token_len).items():
                counts[term] += freq * cfg.path_weight
        doc_id = len(self.paths)
        self.paths.append(rel_path)
        self.doc_len.append(sum(counts.values()))
        postings = self.postings
        for term, freq in counts.items():
            entry = postings.get(term)
            if entry is None:
                postings[term] = {doc_id: freq}
            else:
                entry[doc_id] = freq
        self._idf_cache.clear()

    # ---- scoring ------------------------------------------------------

    @property
    def num_documents(self) -> int:
        return len(self.paths)

    @property
    def avg_doc_len(self) -> float:
        if not self.doc_len:
            return 0.0
        return sum(self.doc_len) / len(self.doc_len)

    def idf(self, term: str) -> float:
        """Lucene's non-negative BM25 idf."""
        cached = self._idf_cache.get(term)
        if cached is not None:
            return cached
        n = self.num_documents
        df = len(self.postings.get(term, ()))
        value = math.log(1.0 + (n - df + 0.5) / (df + 0.5)) if n else 0.0
        self._idf_cache[term] = value
        return value

    def search(self, query: str, k: int = 10) -> list[SearchHit]:
        """Rank documents for ``query``.  Highest score first, path ascending on ties."""
        cfg = self.config
        terms = sorted(set(tokenize(query, min_token_len=cfg.min_token_len)))
        if not terms or not self.paths:
            return []
        avgdl = self.avg_doc_len or 1.0
        scores: dict[int, float] = {}
        matched: dict[int, list[str]] = {}
        for term in terms:
            postings = self.postings.get(term)
            if not postings:
                continue
            idf = self.idf(term)
            if idf <= 0.0:
                continue
            for doc_id, tf in postings.items():
                norm = 1.0 - cfg.b + cfg.b * (self.doc_len[doc_id] / avgdl)
                contribution = idf * (tf * (cfg.k1 + 1.0)) / (tf + cfg.k1 * norm)
                scores[doc_id] = scores.get(doc_id, 0.0) + contribution
                matched.setdefault(doc_id, []).append(term)
        ordered = sorted(scores.items(), key=lambda item: (-item[1], self.paths[item[0]]))
        hits: list[SearchHit] = []
        for rank, (doc_id, score) in enumerate(ordered[: max(k, 0)], start=1):
            hits.append(
                SearchHit(
                    rank=rank,
                    path=self.paths[doc_id],
                    score=score,
                    matched_terms=tuple(sorted(matched[doc_id])),
                )
            )
        return hits

    def rank_of(self, query: str, path: str, limit: int = 1000) -> int | None:
        """1-based rank of ``path`` for ``query`` within ``limit``; ``None`` if absent."""
        for hit in self.search(query, k=limit):
            if hit.path == path:
                return hit.rank
        return None

    # ---- reporting ----------------------------------------------------

    def stats(self) -> dict:
        return {
            "documents": self.num_documents,
            "terms": len(self.postings),
            "tokens": sum(self.doc_len),
            "avg_doc_len": round(self.avg_doc_len, 2),
            "config": {
                "k1": self.config.k1,
                "b": self.config.b,
                "path_weight": self.config.path_weight,
                "min_token_len": self.config.min_token_len,
                "max_file_bytes": self.config.max_file_bytes,
            },
            "build": self.report.as_dict(),
        }


def search_repository(
    root: str | os.PathLike[str],
    queries: Sequence[str],
    k: int = 10,
    config: IndexConfig | None = None,
) -> dict:
    """One-shot convenience wrapper returning the s09 JSON contract."""
    index = BM25Index.build(root, config)
    return {
        "schema": SCHEMA,
        "read_only": True,
        "root": str(Path(root).resolve()),
        "k": k,
        "index": index.stats(),
        "results": [
            {"query": query, "hits": [hit.as_dict() for hit in index.search(query, k=k)]}
            for query in queries
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BM25 baseline over repository files")
    parser.add_argument("query", nargs="*", help="one or more queries")
    parser.add_argument("--root", default=None, help="repository root (default: repo of this file)")
    parser.add_argument("--k", type=int, default=10, help="hits per query (default 10)")
    parser.add_argument("--path-weight", type=int, default=IndexConfig.path_weight)
    parser.add_argument("--k1", type=float, default=IndexConfig.k1)
    parser.add_argument("--b", type=float, default=IndexConfig.b)
    args = parser.parse_args(argv)

    root = Path(args.root) if args.root else Path(__file__).resolve().parents[3]
    config = IndexConfig(k1=args.k1, b=args.b, path_weight=args.path_weight)
    if not args.query:
        index = BM25Index.build(root, config)
        print(json.dumps({"schema": SCHEMA, "index": index.stats()}, indent=2, sort_keys=True))
        return 0
    payload = search_repository(root, args.query, k=args.k, config=config)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
