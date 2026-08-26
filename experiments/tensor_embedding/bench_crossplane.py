"""Cross-plane retrieval benchmark: does the Twin beat what people do today?

The question is not "can this be used" but "does it beat the normal process".
The normal process for "which code does this document describe?" is: read the
prose, guess identifiers, grep. So the baselines are grep and BM25, not a
strawman.

GROUND TRUTH: human-authored markdown links from a documentation page to a
source file. Not name equality -- that trap was already sprung once. The
extractor's ``documents`` edges are BUILT from backtick-span == symbol-name, so
any lexical method scores 100% on them by construction and the comparison says
nothing. A markdown link is an independent, deliberate statement by an author.

QUERY: the page's prose with the link targets, their basenames and every
backticked span REMOVED. What is left is domain language -- what an engineer
actually has when they ask the question.

METHODS
  exact_token   the file whose stem appears literally in the query
  bm25          BM25 over the source files, identifiers split on case and _
  doc_neighbour the deterministic brief: files linked by pages that this page
                links to (structure, no learning)
  tensor        embedding retrieval over the Twin with THIS link held out

Run:  python experiments/tensor_embedding/bench_crossplane.py <repo-root> <tag>
"""

from __future__ import annotations

import collections
import json
import math
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
OUT = REPO / "runs" / "tensor_embedding_v3"
SKIP = {".git", "node_modules", "venv-tensor", ".venv", "venv", "__pycache__",
        "site-packages", "reference", "lab_assets", ".mypy_cache", ".pytest_cache"}

MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
MD_CODE = re.compile(r"`[^`]*`")
TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]+")


def usable(path: pathlib.Path) -> bool:
    return not any(part in SKIP for part in path.parts)


def split_identifier(word: str) -> list[str]:
    parts = re.split(r"[_\W]+", word)
    out = []
    for part in parts:
        out.extend(re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z]+|[a-z]+|\d+", part) or [part])
    return [p.lower() for p in out if p]


def tokenise(text: str) -> list[str]:
    out = []
    for word in TOKEN.findall(text):
        out.extend(split_identifier(word))
    return out


def collect(root: pathlib.Path):
    """Source files, and (query, target) pairs taken from markdown links."""
    sources = {}
    for path in root.rglob("*.py"):
        if not usable(path) or path.stat().st_size > 300_000:
            continue
        rel = path.relative_to(root).as_posix()
        sources[rel] = path.read_text(encoding="utf-8", errors="replace")

    pairs = []
    for path in root.rglob("*.md"):
        if not usable(path) or path.stat().st_size > 300_000:
            continue
        page = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        targets = []
        for _, href in MD_LINK.findall(text):
            if href.startswith(("http", "#", "mailto")):
                continue
            try:
                resolved = (path.parent / href.split("#")[0]).resolve().relative_to(root).as_posix()
            except ValueError:
                continue
            if resolved in sources:
                targets.append(resolved)
        if not targets:
            continue

        # Scrub: every backticked span, every link, every basename of a target.
        prose = MD_CODE.sub(" ", text)
        prose = MD_LINK.sub(lambda m: " " + m.group(1) + " ", prose)
        for target in set(targets):
            stem = pathlib.Path(target).stem
            prose = re.sub(re.escape(stem), " ", prose, flags=re.IGNORECASE)
            for piece in split_identifier(stem):
                prose = re.sub(rf"\b{re.escape(piece)}\b", " ", prose, flags=re.IGNORECASE)
        for target in set(targets):
            pairs.append({"page": page, "target": target, "query": " ".join(tokenise(prose)[:400])})
    return sources, pairs


class BM25:
    def __init__(self, docs: dict[str, str], k1: float = 1.5, b: float = 0.75):
        self.ids = sorted(docs)
        self.tf = []
        self.df = collections.Counter()
        lengths = []
        for key in self.ids:
            counts = collections.Counter(tokenise(docs[key]))
            self.tf.append(counts)
            lengths.append(sum(counts.values()) or 1)
            for term in counts:
                self.df[term] += 1
        self.len = lengths
        self.avg = sum(lengths) / len(lengths)
        self.n = len(self.ids)
        self.k1, self.b = k1, b

    def rank(self, query: list[str]) -> list[str]:
        scores = [0.0] * self.n
        for term in set(query):
            if term not in self.df:
                continue
            idf = math.log(1 + (self.n - self.df[term] + 0.5) / (self.df[term] + 0.5))
            for i, counts in enumerate(self.tf):
                freq = counts.get(term)
                if not freq:
                    continue
                denom = freq + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg)
                scores[i] += idf * freq * (self.k1 + 1) / denom
        return [self.ids[i] for i in sorted(range(self.n), key=lambda i: -scores[i])]


def exact_token_rank(query: list[str], sources) -> list[str]:
    """What grep gives you: files whose stem tokens appear in the query."""
    qset = set(query)
    scored = []
    for rel in sources:
        stem_tokens = set(split_identifier(pathlib.Path(rel).stem))
        scored.append((len(stem_tokens & qset), rel))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [rel for _, rel in scored]


def doc_neighbour_rank(pair, pairs, sources) -> list[str]:
    """The deterministic brief: what do sibling pages of this page link to?"""
    page = pair["page"]
    siblings = collections.Counter()
    for other in pairs:
        if other["page"] == page:
            continue
        siblings[other["target"]] += 1
    ordered = [rel for rel, _ in siblings.most_common()]
    rest = [rel for rel in sorted(sources) if rel not in siblings]
    return ordered + rest


def recall_at(ranking: list[str], target: str, ks=(1, 5, 10, 25)) -> dict:
    try:
        rank = ranking.index(target)
    except ValueError:
        rank = len(ranking)
    return {k: int(rank < k) for k in ks}


def main() -> int:
    root = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else REPO
    tag = sys.argv[2] if len(sys.argv) > 2 else "self"
    sources, pairs = collect(root)
    if not pairs:
        print("no (query, target) pairs found -- no markdown links into source files")
        return 1

    bm25 = BM25(sources)
    ks = (1, 5, 10, 25)
    totals = {m: {k: 0 for k in ks} for m in ("exact_token", "bm25", "doc_neighbour")}
    for pair in pairs:
        query = pair["query"].split()
        for method, ranking in (
            ("exact_token", exact_token_rank(query, sources)),
            ("bm25", bm25.rank(query)),
            ("doc_neighbour", doc_neighbour_rank(pair, pairs, sources)),
        ):
            hit = recall_at(ranking, pair["target"], ks)
            for k in ks:
                totals[method][k] += hit[k]

    n = len(pairs)
    payload = {
        "benchmark": "crossplane-doc-to-code",
        "root": str(root),
        "tag": tag,
        "queries": n,
        "candidate_files": len(sources),
        "chance_recall@10": round(10 / len(sources), 5),
        "ground_truth": "human-authored markdown links (NOT name equality)",
        "query_scrubbing": "backticked spans, link targets, target basenames and their word pieces removed",
        "results": {m: {f"@{k}": round(v[k] / n, 4) for k in ks} for m, v in totals.items()},
    }
    print(f"queries={n}  candidate source files={len(sources)}  "
          f"chance@10={payload['chance_recall@10']:.5f}")
    for method, row in payload["results"].items():
        print(f"  {method:14s} " + "  ".join(f"R@{k}={row[f'@{k}']:.3f}" for k in ks))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"bench_{tag}.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"wrote {OUT / f'bench_{tag}.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
