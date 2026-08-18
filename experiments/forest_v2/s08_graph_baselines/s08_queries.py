"""EXPERIMENT s08 — a mechanically derived query set with one gold document each.

No human labels exist for this tree, so the queries are derived from it by
rules that are stated up front.  Every family has a *known* bias; the bias is
named here so the numbers are read correctly rather than believed:

* ``symbol`` — the query is a uniquely-defined function/class name, split into
  words.  Gold = its defining code file.  **Bias: maximally favourable to
  lexical matching**, because the gold document literally contains the query
  string.  It is the easy end of the scale, kept as a sanity floor.
* ``docstring`` — the first sentence of that symbol's docstring, with the
  symbol's own tokens REMOVED.  Gold = the defining code file.  Bias: still
  drawn from the gold file's text, but the strongest lexical bridge is cut, so
  the graph has room to matter.
* ``knowledge_ref`` — a prose line from a Markdown file that mentions a
  uniquely-defined code symbol in backticks, with that symbol removed.  Gold =
  the defining CODE file.  This is the only genuinely cross-plane family: the
  query comes from the knowledge plane, the answer lives in the code plane.
  It is the family where "four independent indices" must show its routing
  failure — or not, in which case the kill criterion says so.

Sampling is deterministic (fixed seed, sorted candidate order); re-running the
self-test on the same revision reproduces the same query set exactly.
"""
from __future__ import annotations

import random
import re
from collections import defaultdict

from s08_api import Query
from s08_corpus import Corpus, split_identifier, tokenize

QUERY_SEED = 20260818
MAX_PER_FAMILY = 200
MIN_QUERY_TOKENS = 3
MIN_SYMBOL_LEN = 6

_BACKTICK = re.compile(r"`([A-Za-z_][A-Za-z0-9_.]{3,})`")


def _unique_symbols(corpus: Corpus) -> dict[str, str]:
    """Symbol name -> module, only for names defined in exactly one module.

    Ambiguous names (``main``, ``run``, ``__init__``-ish helpers) are dropped:
    a query with two possible right answers cannot score a retriever fairly.
    """
    owners: dict[str, set[str]] = defaultdict(set)
    for module, facts in corpus.modules.items():
        for symbol in facts.symbols:
            leaf = symbol.split(".")[-1]
            if leaf.startswith("_") or len(leaf) < MIN_SYMBOL_LEN:
                continue
            owners[leaf].add(module)
    return {name: next(iter(mods)) for name, mods in owners.items() if len(mods) == 1}


def _strip_tokens(text: str, drop: set[str]) -> str:
    kept = [tok for tok in tokenize(text) if tok not in drop]
    return " ".join(kept)


def build_queries(corpus: Corpus, max_per_family: int = MAX_PER_FAMILY) -> list[Query]:
    rng = random.Random(QUERY_SEED)
    unique = _unique_symbols(corpus)
    queries: list[Query] = []

    # --- family: symbol
    symbol_pool = sorted(unique.items())
    rng.shuffle(symbol_pool)
    for name, module in symbol_pool[:max_per_family]:
        gold = corpus.doc_id_by_module.get(module)
        if gold is None:
            continue
        text = " ".join(split_identifier(name)) or name
        queries.append(Query(qid=f"symbol:{module}:{name}", family="symbol", text=text, gold_doc_id=gold))

    # --- family: docstring (symbol tokens removed)
    doc_pool: list[tuple[str, str, str]] = []  # (module, symbol, sentence)
    for module in sorted(corpus.modules):
        for symbol, sentence in corpus.modules[module].docstrings:
            leaf = symbol.split(".")[-1]
            if unique.get(leaf) != module:
                continue
            doc_pool.append((module, leaf, sentence))
    rng.shuffle(doc_pool)
    taken = 0
    for module, symbol, sentence in doc_pool:
        if taken >= max_per_family:
            break
        gold = corpus.doc_id_by_module.get(module)
        if gold is None:
            continue
        drop = set(split_identifier(symbol)) | {symbol.lower()}
        text = _strip_tokens(sentence, drop)
        if len(text.split()) < MIN_QUERY_TOKENS:
            continue
        queries.append(Query(qid=f"docstring:{module}:{symbol}", family="docstring", text=text, gold_doc_id=gold))
        taken += 1

    # --- family: knowledge_ref (markdown prose -> code file)
    ref_pool: list[tuple[str, str, str, str]] = []  # (locator, symbol, module, line)
    for doc in sorted(corpus.by_plane.get("knowledge", []), key=lambda d: d.doc_id):
        for line in doc.text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("|", ">", "```", "#")):
                continue
            for match in _BACKTICK.finditer(stripped):
                leaf = match.group(1).split(".")[-1]
                module = unique.get(leaf)
                if module is None:
                    continue
                ref_pool.append((doc.locator, leaf, module, stripped))
    rng.shuffle(ref_pool)
    seen_pairs: set[tuple[str, str]] = set()
    taken = 0
    for locator, symbol, module, line in ref_pool:
        if taken >= max_per_family:
            break
        key = (module, symbol)
        if key in seen_pairs:
            continue
        gold = corpus.doc_id_by_module.get(module)
        if gold is None:
            continue
        drop = set(split_identifier(symbol)) | {symbol.lower()}
        text = _strip_tokens(line, drop)
        if len(text.split()) < MIN_QUERY_TOKENS:
            continue
        seen_pairs.add(key)
        queries.append(
            Query(qid=f"knowledge_ref:{locator}:{symbol}", family="knowledge_ref", text=text, gold_doc_id=gold)
        )
        taken += 1

    return queries


# --------------------------------------------------------------- non-code gold
#
# The three families above ALL have a code document as their gold label.  That
# makes the plan's kill criterion "four independent indices perform equivalently
# to cross-plane fusion" undecidable on this query set: a method that spends any
# slot on a non-code plane can only lose, and a code-only index cannot be beaten
# by anything.  These two families put the answer somewhere other than the code
# plane, so plane routing has something to get right or wrong.
#
# They are an ADDITION, never a modification: ``build_queries`` still returns
# exactly the frozen 600, and the extended set is reported beside it, not
# instead of it.

NONCODE_QUERY_SEED = 20260819
MAX_MENTIONS_PER_TARGET = 4

_PATHISH = re.compile(r"[A-Za-z0-9_./\\-]+\.(?:json|csv|toml|yaml|yml|md)\b", re.IGNORECASE)
_DATA_SUFFIXES = (".json", ".csv", ".toml", ".yaml", ".yml")


def _locator_lookup(corpus: Corpus, plane: str) -> tuple[dict[str, str], dict[str, str]]:
    """(exact locator -> doc_id, unique basename -> doc_id) for one plane."""
    from pathlib import PurePosixPath

    by_locator: dict[str, str] = {}
    basenames: dict[str, list[str]] = defaultdict(list)
    for doc in corpus.by_plane.get(plane, []):
        by_locator[doc.locator] = doc.doc_id
        basenames[PurePosixPath(doc.locator).name].append(doc.doc_id)
    unique = {name: ids[0] for name, ids in basenames.items() if len(ids) == 1}
    return by_locator, unique


def build_non_code_queries(corpus: Corpus, max_per_family: int = MAX_PER_FAMILY) -> list[Query]:
    """Two families whose gold document is NOT a code document.

    * ``doc_ref`` — a prose line in one Markdown file that names another
      Markdown file; gold = the named **knowledge** document.  The mention's own
      tokens are stripped, exactly as in ``knowledge_ref``, so the query has to
      be matched by the surrounding prose rather than by the path.
    * ``data_ref`` — the same derivation, but the named file is a schema-shaped
      artifact; gold = the named **data** document.

    Both are capped at ``MAX_MENTIONS_PER_TARGET`` per gold document so one
    much-referenced file cannot supply a whole family, and both are sampled
    with their own generator, leaving the frozen families' stream untouched.
    """
    from pathlib import PurePosixPath

    rng = random.Random(NONCODE_QUERY_SEED)
    know_by_locator, know_unique = _locator_lookup(corpus, "knowledge")
    data_by_locator, data_unique = _locator_lookup(corpus, "data")

    pools: dict[str, list[tuple[str, str, str, str]]] = {"doc_ref": [], "data_ref": []}
    for source in sorted(corpus.by_plane.get("knowledge", []), key=lambda d: d.doc_id):
        for line in source.text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("|", ">", "```", "#")):
                continue
            for match in _PATHISH.finditer(stripped):
                raw = match.group(0).replace("\\", "/").lstrip("./")
                base = PurePosixPath(raw).name
                lowered = raw.lower()
                if lowered.endswith(".md"):
                    family = "doc_ref"
                    target = know_by_locator.get(raw) or know_unique.get(base)
                elif lowered.endswith(_DATA_SUFFIXES):
                    family = "data_ref"
                    target = data_by_locator.get(raw) or data_unique.get(base)
                else:
                    continue
                if target is None or target == source.doc_id:
                    continue
                pools[family].append((source.locator, raw, target, stripped))

    queries: list[Query] = []
    for family in ("doc_ref", "data_ref"):
        pool = pools[family]
        rng.shuffle(pool)
        per_target: dict[str, int] = defaultdict(int)
        seen: set[tuple[str, str]] = set()
        taken = 0
        for source_locator, raw, target, line in pool:
            if taken >= max_per_family:
                break
            if per_target[target] >= MAX_MENTIONS_PER_TARGET:
                continue
            key = (source_locator, target)
            if key in seen:
                continue
            text = _strip_tokens(line, set(tokenize(raw)))
            if len(text.split()) < MIN_QUERY_TOKENS:
                continue
            seen.add(key)
            per_target[target] += 1
            taken += 1
            queries.append(
                Query(
                    qid=f"{family}:{source_locator}:{raw}",
                    family=family,
                    text=text,
                    gold_doc_id=target,
                )
            )
    return queries


def build_extended_queries(corpus: Corpus, max_per_family: int = MAX_PER_FAMILY) -> list[Query]:
    """The frozen 600 plus the non-code families, in that order."""
    return build_queries(corpus, max_per_family) + build_non_code_queries(corpus, max_per_family)


def gold_plane_mix(queries: list[Query]) -> dict[str, int]:
    """How many gold labels sit in each plane — the number that decides decidability."""
    mix: dict[str, int] = defaultdict(int)
    for query in queries:
        mix[query.gold_doc_id.split(":", 1)[0]] += 1
    return dict(sorted(mix.items()))


def by_family(queries: list[Query]) -> dict[str, list[Query]]:
    out: dict[str, list[Query]] = defaultdict(list)
    for query in queries:
        out[query.family].append(query)
    return dict(out)


def leakage_note(corpus: Corpus, queries: list[Query]) -> dict[str, object]:
    """How much of each query's text is literally inside its own gold document?

    Reported, not hidden: if a family's overlap is ~1.0 the family measures
    string matching, and any retriever difference on it is close to noise.
    """
    per_family: dict[str, list[float]] = defaultdict(list)
    for query in queries:
        gold = corpus.docs.get(query.gold_doc_id)
        if gold is None:
            continue
        q_tokens = set(tokenize(query.text))
        if not q_tokens:
            continue
        gold_tokens = set(gold.tokens)
        per_family[query.family].append(len(q_tokens & gold_tokens) / len(q_tokens))
    return {
        family: {
            "n": len(vals),
            "mean_query_token_overlap_with_gold": round(sum(vals) / len(vals), 4) if vals else 0.0,
        }
        for family, vals in sorted(per_family.items())
    }


__all__ = [
    "build_queries",
    "build_non_code_queries",
    "build_extended_queries",
    "by_family",
    "gold_plane_mix",
    "leakage_note",
]
