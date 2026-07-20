"""slice — "Distill this": a semantic slice of a target, vs whole-repo concat.

The wedge. Repomix/Gitingest hand an agent the WHOLE repo as concatenated text.
``semantic_slice`` instead hands it exactly the relevant neighborhood:

  * the FOCUS (a file, or a single symbol) in full;
  * its DEPENDENCIES (what it imports) as signature skeletons — orientation,
    not full bodies;
  * its CALLERS (who imports it) as skeletons;
  * everything else omitted.

and reports the token reduction vs the naive whole-repo dump. This is v1
(module-neighborhood, powered by the derived import graph); symbol-level
precision arrives with ``graph.py`` (SCIP / stack-graphs).

Honest bar: the whole point is that this beats concatenation on tokens *and*
keeps enough context to act. The token win is measured here; the downstream
task-success half belongs to the eval harness (Movement III).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .index import build_index, resolution_context
from .languages import spec_for
from .parse import extract_units
from .tokens import count_tokens


def estimate_tokens(text: str) -> int:
    """Token count for the distill ratio. Uses a real BPE tokenizer (tiktoken)
    when installed, else a ~4-chars/token heuristic — see ``tokens.count_tokens``.
    So the reduction % is tokenizer-exact when tiktoken is present, and still a
    meaningful ratio without it."""
    return count_tokens(text)


def _read(root: Path, rel: str) -> str:
    try:
        return (root / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _units_of(root: Path, rel: str):
    text = _read(root, rel)
    spec = spec_for(rel)
    return extract_units(rel, text, spec) if spec else []


def _skeleton(root: Path, rel: str) -> str:
    """Signature-level digest of a file: one line per unit (its first line)."""
    text = _read(root, rel)
    spec = spec_for(rel)
    units = extract_units(rel, text, spec) if spec else []
    out = [f"# {rel}  (skeleton)"]
    for u in units:
        first = next((ln.strip() for ln in u.source.splitlines() if ln.strip()), u.name)
        out.append(f"    {first[:120]}   # :{u.line} ({u.loc} loc)")
    if len(out) == 1:  # nothing extractable -> a few head lines for orientation
        head = [ln for ln in text.splitlines() if ln.strip()][:12]
        out += [f"    {ln[:120]}" for ln in head]
    return "\n".join(out)


def _reverse_edges(idx: dict) -> dict:
    """Callers map: rel -> the rels that import it.

    ``build_index`` ships this precomputed as ``import_edges_reverse`` because
    it is index-invariant and this function is on the per-target path: the eval
    harness and the web API both call ``semantic_slice`` in a loop against ONE
    shared index, so inverting the forward map here would repeat the same O(E)
    work per call. The fallback below exists only for an index dict that
    predates the key (an older JSON dump); it iterates ``sorted()`` so the
    appended caller lists come out in the same order as the precomputed ones.
    """
    rev = idx.get("import_edges_reverse")
    if rev is not None:
        return rev
    edges = idx.get("import_edges") or {}
    out: dict[str, list[str]] = {}
    for src in sorted(edges):
        for tgt in edges[src]:
            out.setdefault(tgt, []).append(src)
    return out


def semantic_slice(root, target: str, idx: dict | None = None) -> dict:
    root = Path(root).resolve()
    idx = idx or build_index(root)
    modules = idx["modules"]

    symbol = None
    rel = target.replace("\\", "/")
    if "::" in rel:
        rel, symbol = rel.split("::", 1)
    if rel not in modules:
        cands = [m for m in modules if m.endswith(rel)]
        if not cands:
            raise ValueError(f"target not found in index: {rel}")
        rel = cands[0]

    text = _read(root, rel)
    spec = spec_for(rel)
    focus_unit = None
    if symbol:
        units = extract_units(rel, text, spec) if spec else []
        focus_unit = next((x for x in units if x.name == symbol), None)
        focus_src = focus_unit.source if focus_unit else text
    else:
        focus_src = text

    included = [{"file": rel, "role": "focus", "mode": "full", "tokens": estimate_tokens(focus_src)}]
    parts = [f"# ===== FOCUS: {target} =====\n{focus_src}"]

    # NEIGHBORHOOD EXPANSION, keyed rel->rel for EVERY language.
    #
    # This used to run off ``dependencies``, whose Python keys are DOTTED module
    # names while every other language keys by rel path. The lookup was built
    # python-only, so for a .c/.cpp/.qml/.ts target it produced nothing and the
    # slice silently degraded to the focus file alone -- a distiller that did
    # not distil outside Python, while ``import_edges`` held the correct edges
    # the whole time. ``import_edges`` carries the identical Python edges
    # (verified: zero diff in dep_rels/caller_rels over this repo's 113 python
    # files) plus the ones that were being dropped.
    #
    # ``r in modules`` IS THE SCOPE BOUNDARY, and it is load-bearing.
    # ``import_edges`` is deliberately shell-INCLUSIVE: index.py resolves
    # imports OUTSIDE the metric guard so that an edge pointing into vendored
    # code still resolves to a real file instead of reading as "external".
    # ``modules[rel]``, by contrast, is assigned only INSIDE that guard -- so
    # membership in ``modules`` is exactly "is in the declared center". Walking
    # these edges without this test would expand the slice straight into
    # vendored trees, which is the fan-out the center feature exists to stop.
    # This also keeps every downstream ``_units_of``/``_skeleton`` call scoped:
    # they re-read off disk and know nothing of the index, so the filtering has
    # to happen here, before a rel reaches them.
    edges = idx.get("import_edges") or {}
    rev_edges = _reverse_edges(idx)
    dep_rels: set[str] = set()
    caller_rels: set[str] = set()
    shell_stops = 0
    for r in edges.get(rel, ()):
        if r == rel:
            continue
        if r in modules:
            dep_rels.add(r)
        else:
            shell_stops += 1  # named as an edge, not expanded through
    for src in rev_edges.get(rel, ()):
        if src == rel:
            continue
        if src in modules:
            caller_rels.add(src)
        else:
            shell_stops += 1

    if symbol and focus_unit is not None:
        # symbol-level: include exactly the callees (full) + callers (signature)
        # of THIS symbol, from the module neighborhood — sharper than whole files.
        from . import graph

        dep_units, caller_units = [], []
        for r in sorted(dep_rels):
            dep_units += _units_of(root, r)
        for r in sorted(caller_rels):
            caller_units += _units_of(root, r)
        # Move-4: import/scope-aware resolution (from the derived index) drops
        # false edges to same-named units in unrelated modules; None -> the pure
        # name-match fallback, so this is safe when the root wasn't indexed here.
        resolver = resolution_context(root, key=idx.get("scope_key"))
        callee_hits = graph.callees(focus_unit, dep_units, resolver)
        caller_hits = graph.callers(focus_unit, caller_units, resolver)

        # THE SCOPE BOUNDARY, RE-ASSERTED ON THE SYMBOL PATH.
        #
        # ``dep_rels``/``caller_rels`` above are gated on ``r in modules``, but
        # the resolver does not go through them: ``SymbolResolver.resolve``
        # reads ``defs_by_file`` directly, so a name that binds to a SHELL unit
        # returns that unit and its full body lands in the CALLEES block --
        # straight past the gate that exists to stop exactly this. Keying the
        # resolver cache by scope fixes the cause; this fixes the CLASS, so no
        # future resolver provenance (a stale cache, a hand-built resolver, a
        # caller that omits scope_key) can reopen it. Cheap and total.
        #
        # Rejections are COUNTED into the same shell_boundary_stops the module
        # path reports -- a body withheld here is a real edge stopping at the
        # boundary, and dropping it silently would leave the slice looking as
        # though the neighborhood simply ended.
        def _in_center(hits):
            kept = [u for u in hits if u.module in modules]
            return kept, len(hits) - len(kept)

        callee_hits, n_callee_shell = _in_center(callee_hits)
        caller_hits, n_caller_shell = _in_center(caller_hits)
        shell_stops += n_callee_shell + n_caller_shell
        if callee_hits:
            parts.append("\n# ===== CALLEES (symbol-level, approximate) =====")
            for cu in callee_hits:
                block = f"# {cu.module}:{cu.line}\n{cu.source}"
                parts.append(block)
                included.append({"file": cu.module, "role": "callee", "mode": "full", "tokens": estimate_tokens(block)})
        if caller_hits:
            parts.append("\n# ===== CALLERS (symbol-level, approximate) =====")
            for cu in caller_hits:
                first = next((ln.strip() for ln in cu.source.splitlines() if ln.strip()), cu.name)
                line = f"    {first[:120]}   # {cu.module}:{cu.line}"
                parts.append(line)
                included.append({"file": cu.module, "role": "caller", "mode": "signature", "tokens": estimate_tokens(line)})
    else:
        for role, rels in (("dependency", sorted(dep_rels)), ("caller", sorted(caller_rels))):
            if not rels:
                continue
            parts.append(f"\n# ===== {role.upper()}S (skeleton) =====")
            for r in rels:
                sk = _skeleton(root, r)
                parts.append(sk)
                included.append({"file": r, "role": role, "mode": "skeleton", "tokens": estimate_tokens(sk)})

    slice_text = "\n".join(parts)
    slice_tokens = estimate_tokens(slice_text)
    whole = max(1, idx.get("total_chars", 0) // 4)
    return {
        "target": target,
        "focus_file": rel,
        "focus_symbol": symbol,
        "included": included,
        "n_included": len(included),
        # Edges that pointed OUT of the declared center and were therefore not
        # expanded through. Reported rather than dropped in silence: a slice
        # that stops at the shell boundary and a slice with no neighbors at all
        # look identical from the outside, and only one of them is complete.
        "shell_boundary_stops": shell_stops,
        "slice_tokens": slice_tokens,
        "whole_repo_tokens": whole,
        "reduction_pct": round(100 * (1 - slice_tokens / whole), 1),
        "backend": idx["backend"],
        "slice_text": slice_text,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="daedalus.structcore.slice",
        description="Distill this: semantic slice of a target vs whole-repo concat.")
    ap.add_argument("repo", help="repo root")
    ap.add_argument("target", help="path/to/file.ext  or  path/to/file.ext::symbol")
    ap.add_argument("--out", default=None, help="write the slice text to this file")
    ap.add_argument("--json", default=None, help="write the full result (incl. slice) to JSON")
    args = ap.parse_args(argv)

    res = semantic_slice(args.repo, args.target)
    print(f"\nDISTILL  '{res['target']}'  ->  focus {res['focus_file']}")
    print(f"backend: tree-sitter={'on' if res['backend']['tree_sitter'] else 'off'}")
    print(f"included {res['n_included']} files:")
    for i in res["included"][:25]:
        print(f"  {i['role']:11} {i['mode']:8} {i['tokens']:>7} tok  {i['file']}")
    print(f"\n  slice:      {res['slice_tokens']:>9} tokens")
    print(f"  whole repo: {res['whole_repo_tokens']:>9} tokens  (Repomix-style full concat)")
    print(f"  REDUCTION:  {res['reduction_pct']}%")
    if args.out:
        Path(args.out).write_text(res["slice_text"], encoding="utf-8")
        print(f"  wrote slice -> {args.out}")
    if args.json:
        Path(args.json).write_text(json.dumps(res, indent=1), encoding="utf-8")
        print(f"  wrote json  -> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
