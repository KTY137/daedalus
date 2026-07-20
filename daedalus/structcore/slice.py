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


def _assemble_slice(focus_block: str, neighbors: list[dict],
                    withheld_lines: list[str], trimmed_marker: str | None) -> str:
    """Join FOCUS + kept neighbour units (each under its section header, in
    emission order) + the WITHHELD block + an optional TRIMMED marker.

    A section header is emitted once, and only for a section that still has a
    kept unit -- so dropping every unit of a section drops its header too. With
    the full neighbour list and no marker this reproduces the old flat join
    byte-for-byte (the un-budgeted path is unchanged)."""
    out = [focus_block]
    last_section = None
    for n in neighbors:
        if n["section"] != last_section:
            out.append(n["section"])
            last_section = n["section"]
        out.append(n["text"])
    out.extend(withheld_lines)
    if trimmed_marker:
        out.append(trimmed_marker)
    return "\n".join(out)


def _fit_budget(focus_block: str, neighbors: list[dict],
                withheld_lines: list[str], budget: int) -> tuple[list[dict], int]:
    """Degrade an over-budget slice by dropping WHOLE neighbour units -- never
    string-truncating -- until it fits ``budget`` tokens. FOCUS and the WITHHELD
    block are always kept (a tail truncation would silently delete the
    anti-hallucination breadcrumb, the exact failure the gate prevents).

    Lowest keep-priority goes first (callers/signatures before dependency and
    callee bodies); within a tier the later-emitted unit goes first, so the
    earliest / most-relevant neighbour survives longest. The TRIMMED marker's own
    cost is counted each pass so the kept set fits WITH the marker present.
    Returns (kept_in_emission_order, dropped_count)."""
    kept = list(neighbors)
    dropped = 0
    while kept:
        marker = (f"\n# ===== CONTEXT TRIMMED: dropped {dropped} of "
                  f"{len(neighbors)} neighbors to fit budget =====") if dropped else None
        if estimate_tokens(_assemble_slice(focus_block, kept, withheld_lines, marker)) <= budget:
            break
        victim = min(range(len(kept)), key=lambda i: (kept[i]["keep"], -i))
        kept.pop(victim)
        dropped += 1
    return kept, dropped


def semantic_slice(
    root,
    target: str,
    idx: dict | None = None,
    lane: str = "trusted",
    policy=None,
    max_tokens: int | None = None,
) -> dict:
    """Assemble a semantic slice of ``target``.

    ``lane`` selects the egress gate applied to every file that contributes text
    to ``slice_text`` (see ``sensitivity.slice_egress_rule``):

      * ``"trusted"`` (default) -- Claude, local Ollama, the eval harness, the
        local web distill view. The unconditional SECRET FLOOR still runs (a
        private key never enters a slice, even locally); the default-deny
        allow-list does NOT, so ordinary source is never withheld here. This is
        what keeps eval recall at 100%.
      * ``"untrusted"`` -- a genuinely untrusted external provider (DeepSeek).
        Floor + the existing default-deny allow-list both apply.

    Withholding is REPORTED, never silent: the result gains a sorted ``withheld``
    block (path, role, rule) AND an inline ``# ===== WITHHELD ... =====``
    breadcrumb in ``slice_text`` so the consuming model sees the gap rather than
    hallucinating the missing callee. If the FOCUS file itself is denied the
    slice fails closed -- no neighbour slice is returned in its place.

    ``max_tokens`` (default ``None`` -> no cap, byte-identical to before) caps the
    assembled ``slice_text``. When exceeded the slice degrades by dropping WHOLE
    neighbour units (never truncating text), always keeping the FOCUS and the
    WITHHELD block and appending a visible ``# ===== CONTEXT TRIMMED ... =====``
    marker; ``trimmed_count`` reports how many neighbours were dropped.
    """
    from ..sensitivity import slice_egress_rule

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

    # FOCUS GATE -- fail closed. The floor scans the FULL focus file (not just
    # the requested symbol): a file that carries a secret anywhere is refused as
    # a distill target rather than returning a slice of its neighbours dressed
    # up as the requested slice.
    focus_rule = slice_egress_rule(rel, text, lane=lane, policy=policy)
    if focus_rule:
        breadcrumb = (
            f"# ===== WITHHELD: {rel} ({focus_rule}) =====\n"
            f"# focus file withheld by the egress gate (lane={lane}); "
            f"slice refused (fail-closed)."
        )
        whole = max(1, idx.get("total_chars", 0) // 4)
        slice_tokens = estimate_tokens(breadcrumb)
        return {
            "target": target,
            "focus_file": rel,
            "focus_symbol": symbol,
            "included": [],
            "n_included": 0,
            "shell_boundary_stops": 0,
            "withheld": [{"file": rel, "role": "focus", "rule": focus_rule}],
            "withheld_count": 1,
            "slice_tokens": slice_tokens,
            "whole_repo_tokens": whole,
            "reduction_pct": round(100 * (1 - slice_tokens / whole), 1),
            "backend": idx["backend"],
            "slice_text": breadcrumb,
        }

    spec = spec_for(rel)
    focus_unit = None
    if symbol:
        units = extract_units(rel, text, spec) if spec else []
        focus_unit = next((x for x in units if x.name == symbol), None)
        focus_src = focus_unit.source if focus_unit else text
    else:
        focus_src = text

    focus_inc = {"file": rel, "role": "focus", "mode": "full", "tokens": estimate_tokens(focus_src)}
    focus_block = f"# ===== FOCUS: {target} =====\n{focus_src}"
    # Neighbour units, collected in emission order and kept SEPARATE from the
    # FOCUS so an optional token budget can degrade by dropping whole units (see
    # _fit_budget). ``keep`` is the drop priority: dependency/callee bodies (2)
    # outrank caller signatures (1), so callers are shed first.
    neighbors: list[dict] = []

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

    # NEIGHBOUR EGRESS GATE. Applied at the EMISSION point of every file whose
    # text would enter slice_text -- skeletons on the module path, and the actual
    # callee/caller UNITS on the symbol path. It must be the emission point, not
    # just the rel sets: the symbol resolver reads the index-wide ``defs_by_file``
    # directly (same mechanism the shell-boundary re-assertion below guards), so a
    # secret-bearing callee body can arrive from the resolver even after its rel
    # was dropped from ``dep_rels``. Gating each emitted unit's module closes that.
    #
    # Floor (secret-only) applies in every lane; the default-deny allow-list only
    # in an untrusted lane. Per file, so the deny_content first-match-break cannot
    # poison a whole slice and every hit is attributable to one path. Reported,
    # never silent: withheld -> a sorted block + an inline breadcrumb.
    _gate_cache: dict[str, str | None] = {}
    withheld_map: dict[str, tuple[str, str]] = {}  # rel -> (role, rule)

    def _rule_for(rel: str) -> str | None:
        if rel not in _gate_cache:
            _gate_cache[rel] = slice_egress_rule(
                rel, _read(root, rel), lane=lane, policy=policy)
        return _gate_cache[rel]

    def _emit_ok(rel: str, role: str) -> bool:
        rule = _rule_for(rel)
        if rule:
            # First role to withhold a rel names it; identical file+rule either way.
            withheld_map.setdefault(rel, (role, rule))
            return False
        return True

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
        # EGRESS GATE at emission: a callee body / caller signature is withheld
        # if its file trips the gate, even when it reached here via the resolver.
        callee_hits = [u for u in callee_hits if _emit_ok(u.module, "callee")]
        caller_hits = [u for u in caller_hits if _emit_ok(u.module, "caller")]
        callee_section = "\n# ===== CALLEES (symbol-level, approximate) ====="
        for cu in callee_hits:
            block = f"# {cu.module}:{cu.line}\n{cu.source}"
            inc = {"file": cu.module, "role": "callee", "mode": "full", "tokens": estimate_tokens(block)}
            neighbors.append({"section": callee_section, "text": block,
                              "tokens": inc["tokens"], "keep": 2, "inc": inc})
        caller_section = "\n# ===== CALLERS (symbol-level, approximate) ====="
        for cu in caller_hits:
            first = next((ln.strip() for ln in cu.source.splitlines() if ln.strip()), cu.name)
            line = f"    {first[:120]}   # {cu.module}:{cu.line}"
            inc = {"file": cu.module, "role": "caller", "mode": "signature", "tokens": estimate_tokens(line)}
            neighbors.append({"section": caller_section, "text": line,
                              "tokens": inc["tokens"], "keep": 1, "inc": inc})
    else:
        for role, rels in (("dependency", sorted(dep_rels)), ("caller", sorted(caller_rels))):
            kept = [r for r in rels if _emit_ok(r, role)]
            if not kept:
                continue
            section = f"\n# ===== {role.upper()}S (skeleton) ====="
            keep_rank = 2 if role == "dependency" else 1
            for r in kept:
                sk = _skeleton(root, r)
                inc = {"file": r, "role": role, "mode": "skeleton", "tokens": estimate_tokens(sk)}
                neighbors.append({"section": section, "text": sk,
                                  "tokens": inc["tokens"], "keep": keep_rank, "inc": inc})

    # sorted() for determinism: the withheld block and its breadcrumbs are order-
    # independent of dict insertion / set iteration.
    withheld = sorted(
        ({"file": rel, "role": role, "rule": rule}
         for rel, (role, rule) in withheld_map.items()),
        key=lambda w: (w["file"], w["role"]),
    )
    # Fail-loud breadcrumb IN the slice text (matching the spirit of
    # shell_boundary_stops, but inline so the model sees it): a withheld
    # neighbour leaves a marked gap, never an unmarked one it might hallucinate
    # across. ``withheld`` is already sorted() for determinism. This block is kept
    # LAST and is NEVER dropped by the budget -- degrade sheds neighbours, not the
    # gate's own report.
    withheld_lines: list[str] = []
    if withheld:
        withheld_lines.append("\n# ===== WITHHELD (egress gate) =====")
        for w in withheld:
            withheld_lines.append(f"# {w['file']}  ({w['rule']})  [{w['role']}]")

    # Assemble. With max_tokens=None this is byte-identical to the old flat join;
    # over budget it drops WHOLE neighbour units (never truncates) and appends a
    # visible TRIMMED marker, keeping FOCUS + WITHHELD.
    kept = neighbors
    trimmed_count = 0
    slice_text = _assemble_slice(focus_block, kept, withheld_lines, None)
    if max_tokens is not None and neighbors and estimate_tokens(slice_text) > max_tokens:
        kept, trimmed_count = _fit_budget(focus_block, neighbors, withheld_lines, max_tokens)
        marker = (f"\n# ===== CONTEXT TRIMMED: dropped {trimmed_count} of "
                  f"{len(neighbors)} neighbors to fit budget =====")
        slice_text = _assemble_slice(focus_block, kept, withheld_lines, marker)

    included = [focus_inc] + [n["inc"] for n in kept]
    slice_tokens = estimate_tokens(slice_text)
    whole = max(1, idx.get("total_chars", 0) // 4)
    return {
        "target": target,
        "focus_file": rel,
        "focus_symbol": symbol,
        "included": included,
        "n_included": len(included),
        "trimmed_count": trimmed_count,
        # Edges that pointed OUT of the declared center and were therefore not
        # expanded through. Reported rather than dropped in silence: a slice
        # that stops at the shell boundary and a slice with no neighbors at all
        # look identical from the outside, and only one of them is complete.
        "shell_boundary_stops": shell_stops,
        # Files that carried secret markers / non-allow-listed egress and were
        # therefore withheld from the slice. sorted(); each entry names the rule
        # that fired. Empty list on a clean slice.
        "withheld": withheld,
        "withheld_count": len(withheld),
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
