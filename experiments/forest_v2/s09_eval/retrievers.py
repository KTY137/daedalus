"""The baselines this slice ships itself.

Each one exists to remove a specific way of being fooled, which is the only
reason a baseline earns its runtime (plan section 10, Gate 3's baseline
list; section 13's "extra context explains the whole gain"):

``RandomUniform``     the floor.  Any score not clearly above this is noise.
``PathLexical``       matches the query against **path tokens only**.  If
                      this wins, the task is filename echo, not retrieval.
``Bm25``              classic BM25 over file content plus path tokens.
``Bm25ContentOnly``   the same, with path tokens removed from the document.
                      The gap to ``Bm25`` is how much of BM25's score was
                      the filename rather than the file.
``RecencyPrior``      ignores the query completely and ranks by how recently
                      a file was touched before the case revision.  If a
                      query-aware method cannot beat a query-blind one, the
                      query is not doing the work.

All of them are deterministic and pure stdlib.  None reads a byte past the
budget, and none can see the gold set -- it is not in their input.
"""
from __future__ import annotations

import hashlib
import math
import random
import subprocess
from collections import Counter
from pathlib import Path
from typing import Dict, List, Sequence

if __package__ in (None, ""):  # pragma: no cover - direct-script convenience
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from s09_eval.contract import Candidate, QueryView
    from s09_eval.tokens import TokenCache, path_tokens, word_tokens
else:
    from .contract import Candidate, QueryView
    from .tokens import TokenCache, path_tokens, word_tokens

BM25_K1 = 1.5
BM25_B = 0.75


class RandomUniform:
    """Shuffle the universe. The floor every other number is read against."""

    name = "random_uniform"

    def __init__(self, seed: str = "s09") -> None:
        self.seed = seed

    def rank(self, query: QueryView, universe: Sequence[Candidate]) -> List[str]:
        # Seeded per case so the floor is reproducible, not a lucky draw.
        digest = hashlib.sha256(f"{self.seed}:{query.case_id}".encode()).hexdigest()
        rng = random.Random(int(digest[:16], 16))
        paths = [c.path for c in universe]
        rng.shuffle(paths)
        return paths


class PathLexical:
    """Score a file by how much of the query appears in its path.

    Content-free on purpose: this is the "is the answer just written in the
    commit message" detector.
    """

    name = "path_lexical"

    def rank(self, query: QueryView, universe: Sequence[Candidate]) -> List[str]:
        q = set(word_tokens(query.text))
        if not q:
            return []
        scored = []
        for cand in universe:
            tokens = path_tokens(cand.path)
            overlap = len(q & tokens)
            if not overlap:
                continue
            # length-normalised so a deep path cannot win by having many tokens
            scored.append((overlap / math.sqrt(len(tokens)), cand.path))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [path for _, path in scored]


class Bm25:
    """BM25 over document tokens, with the usual k1/b."""

    name = "bm25"
    include_path_tokens = True

    def __init__(self, cache: TokenCache | None = None) -> None:
        self.cache = cache if cache is not None else TokenCache()

    def _document(self, cand: Candidate) -> Counter:
        counts = self.cache.counts(cand.blob, cand.text)
        if not self.include_path_tokens:
            return counts
        merged = Counter(counts)
        merged.update(word_tokens(cand.path))
        return merged

    def rank(self, query: QueryView, universe: Sequence[Candidate]) -> List[str]:
        q_terms = set(word_tokens(query.text))
        if not q_terms:
            return []

        docs: List[tuple[str, Counter, int]] = []
        df: Counter = Counter()
        total_len = 0
        for cand in universe:
            counts = self._document(cand)
            length = sum(counts.values())
            if not length:
                continue
            docs.append((cand.path, counts, length))
            total_len += length
            for term in q_terms:
                if term in counts:
                    df[term] += 1
        if not docs:
            return []

        n = len(docs)
        avgdl = total_len / n
        idf = {
            term: math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            for term in q_terms
            if df[term]
        }
        if not idf:
            return []

        scored = []
        for path, counts, length in docs:
            score = 0.0
            for term, weight in idf.items():
                tf = counts.get(term, 0)
                if not tf:
                    continue
                denom = tf + BM25_K1 * (1 - BM25_B + BM25_B * length / avgdl)
                score += weight * (tf * (BM25_K1 + 1)) / denom
            if score > 0:
                scored.append((score, path))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [path for _, path in scored]


class Bm25ContentOnly(Bm25):
    """BM25 with the path stripped out of the document.

    Its distance from :class:`Bm25` is the filename contribution, measured
    rather than argued about.
    """

    name = "bm25_content_only"
    include_path_tokens = False


class RecencyPrior:
    """Rank by how recently a file changed before the case revision.

    Query-blind by construction -- it never reads ``query.text``.  This is
    the control that keeps a query-aware method honest: churn is a strong,
    nearly free prior in most repositories, and a method that cannot beat it
    has not shown that it understands the request.

    Only history reachable from ``query.revision`` (the pre-image commit) is
    walked, so nothing after the case is visible.
    """

    name = "recency_prior"

    def __init__(self, repo: Path | str | None = None, window: int = 400) -> None:
        self.repo = Path(repo) if repo else Path(__file__).resolve().parents[3]
        self.window = window
        self._order_cache: Dict[str, Dict[str, int]] = {}

    def _recency(self, revision: str) -> Dict[str, int]:
        cached = self._order_cache.get(revision)
        if cached is not None:
            return cached
        proc = subprocess.run(
            [
                "git", "-C", str(self.repo), "log", "--no-merges",
                "--pretty=format:", "--name-only", f"-n{self.window}", revision,
            ],
            capture_output=True,
            check=False,
        )
        order: Dict[str, int] = {}
        if proc.returncode == 0:
            rank = 0
            for line in proc.stdout.decode("utf-8", "replace").splitlines():
                path = line.strip()
                if path and path not in order:
                    rank += 1
                    order[path] = rank
        self._order_cache[revision] = order
        return order

    def rank(self, query: QueryView, universe: Sequence[Candidate]) -> List[str]:
        if not query.revision:
            return []
        order = self._recency(query.revision)
        scored = [
            (order[c.path], c.path) for c in universe if c.path in order
        ]
        scored.sort()
        return [path for _, path in scored]


def default_suite(cache: TokenCache | None = None) -> List[object]:
    """The five baselines, sharing one token cache so costs are comparable."""
    shared = cache if cache is not None else TokenCache()
    bm25 = Bm25(shared)
    content_only = Bm25ContentOnly(shared)
    return [RandomUniform(), PathLexical(), bm25, content_only, RecencyPrior()]
