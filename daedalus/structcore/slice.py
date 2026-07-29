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

from . import markdown as markdown_mod
from .index import build_index, resolution_context
from .languages import doc_spec_for, spec_for
from .parse import extract_units
from .tokens import count_tokens


def estimate_tokens(text: str) -> int:
    """Token count for the distill ratio. Uses a real BPE tokenizer (tiktoken)
    when installed, else a ~4-chars/token heuristic — see ``tokens.count_tokens``.
    So the reduction % is tokenizer-exact when tiktoken is present, and still a
    meaningful ratio without it."""
    return count_tokens(text)


def _whole_repo_tokens(idx: dict) -> tuple[int, bool]:
    """The distill ratio's DENOMINATOR, plus whether it was actually measured.

    ``slice_tokens`` (the numerator) is tokenizer-exact whenever tiktoken is
    installed, but this used to be ``total_chars // 4`` unconditionally -- a real
    token count divided by a heuristic one, which makes the headline reduction %
    wrong by however far chars/4 misses on this corpus (it under-counts source
    code, so the published number was systematically flattering). ``total_tokens``
    is now carried through the index by the same tokenizer.

    The fallback survives for index dicts that predate the field: an older JSON
    dump, or the Rust engine (structcore-rs emits total_chars only). Degraded is
    allowed; degraded-and-silent is not, hence the returned flag, which callers
    surface as ``whole_repo_tokens_exact``.
    """
    tok = idx.get("total_tokens")
    if tok is not None:
        return max(1, int(tok)), True
    return max(1, idx.get("total_chars", 0) // 4), False


def _read(root: Path, rel: str) -> str:
    try:
        return (root / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _units_of(root: Path, rel: str, text: str | None = None):
    """Editable units of a file: code units, or -- for a document -- SECTIONS.

    A ``DocSection`` is field-compatible with a ``CodeUnit`` (module/name/line/
    end_line/loc/source/language), so a caller that already handles units needs
    no type switch. What a caller MUST NOT do is feed sections into the call-
    graph approximation: identifiers in prose are not calls, and
    ``semantic_slice`` keeps the two apart for that reason.
    """
    if text is None:
        text = _read(root, rel)
    if doc_spec_for(rel) is not None:
        return list(markdown_mod.parse_document(rel, text).sections)
    spec = spec_for(rel)
    return extract_units(rel, text, spec) if spec else []


def _skeleton(root: Path, rel: str) -> str:
    """Signature-level digest of a file: one line per unit (its first line).

    For a DOCUMENT the analogue is exact and is delegated to
    ``markdown.document_skeleton``: the heading tree is the signature set, the
    prose is the body, the body is dropped, and the drop is reported inline.
    That path also carries the hard invariant this function cannot state for
    code -- the result is never larger than the raw document.

    Routing documents here matters as much as what it produces. The old
    fallthrough (``spec_for`` returns None for .md, so zero units, so the
    ``len(out) == 1`` branch) emitted twelve raw lines of prose under a header
    reading ``(skeleton)`` -- presenting a document as though it had signatures,
    with no statement that the other 3,580 lines existed at all.
    """
    text = _read(root, rel)
    if doc_spec_for(rel) is not None:
        return markdown_mod.document_skeleton(rel, text).text
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
    include_focus: bool = True,
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

    WHAT THE REDUCTION % IS MEASURED AGAINST. ``reduction_pct`` is
    ``1 - slice_tokens / whole_repo_tokens``. Both sides are now counted by the
    SAME tokenizer (``tokens.count_tokens``: tiktoken cl100k_base when installed,
    chars/4 otherwise); the denominator used to be a bare ``total_chars // 4``
    regardless, so the ratio mixed a measured numerator with an estimated
    denominator. ``whole_repo_tokens_exact`` is False when that old estimate is
    still in play (an index dict lacking ``total_tokens`` -- an older JSON dump,
    or the Rust engine).

    ``whole_repo_tokens`` is the summed token count of the IN-CENTER source files
    -- exactly the file set ``index`` accumulates inside its metric-withholding
    guard, so .daedalusignore'd and out-of-scope files are excluded from the
    baseline just as they are from the slice.

    It is deliberately NOT identical to what ``eval/harness.py:_whole_repo_text``
    concatenates for the Tier-2 A/B, which differs in three ways: it prepends a
    ``# ===== rel =====`` header per file (so its total runs HIGHER), it truncates
    at a char cap (so on a large repo its total runs LOWER, and it reports
    ``b_truncated``), and it walks the filesystem with its own ignore-dir list
    rather than the index's scope, so the two can disagree about which files
    "the repo" contains. Treat ``reduction_pct`` as the index-scoped ratio and
    Tier-2's ``tokens_B`` as the as-fed-to-a-model count; they answer different
    questions and should not be expected to match.

    ``max_tokens`` (default ``None`` -> no cap, byte-identical to before) caps the
    assembled ``slice_text``. When exceeded the slice degrades by dropping WHOLE
    neighbour units (never truncating text), always keeping the FOCUS and the
    WITHHELD block and appending a visible ``# ===== CONTEXT TRIMMED ... =====``
    marker; ``trimmed_count`` reports how many neighbours were dropped.

    ``include_focus`` (default ``True`` -> byte-identical to before) controls only
    whether the FOCUS file's BODY is emitted into ``slice_text``. With ``False`` the
    body is replaced by a one-line header and ``included[0]`` is reported as
    ``mode="omitted"``; the focus source is still read and still drives symbol
    resolution (callees/callers). The offload rewrite path sets this: it already
    puts the file body in the prompt separately, so duplicating it via the FOCUS
    block would waste the window -- the slice then contributes only neighbour
    context. INVARIANT: the FOCUS GATE (the floor scan of the FULL focus text and
    its fail-closed refusal) runs FIRST and IDENTICALLY in both modes -- omitting
    the body never skips the gate, so a secret-bearing focus is refused either way.
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
        whole, whole_exact = _whole_repo_tokens(idx)
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
            "whole_repo_tokens_exact": whole_exact,
            # Which tokenizer produced the denominator. "chars/4 (heuristic)"
            # when tiktoken is absent -- so a consumer never reports a heuristic
            # count as "measured". None when the index predates the field.
            "whole_repo_tokenizer": idx.get("tokenizer"),
            "reduction_pct": round(100 * (1 - slice_tokens / whole), 1),
            "backend": idx["backend"],
            "slice_text": breadcrumb,
        }

    is_doc = doc_spec_for(rel) is not None
    focus_unit = None
    if symbol:
        # ``file.py::function`` and ``spec.md::Heading`` are the same request:
        # give me this one unit, not the whole file. For a document the anchor
        # slug is accepted as well as the literal heading text, because a link
        # written elsewhere in the repo spells it that way
        # (``[x](docs/spec.md#the-heading)``) and refusing the spelling the repo
        # itself uses would make the sharper target unreachable in practice.
        units = _units_of(root, rel, text)
        focus_unit = next((x for x in units if x.name == symbol), None)
        if focus_unit is None and is_doc:
            wanted = markdown_mod.slugify(symbol)
            focus_unit = next(
                (x for x in units if getattr(x, "anchor", "") == wanted), None)
        focus_src = focus_unit.source if focus_unit else text
    else:
        focus_src = text

    if include_focus:
        focus_inc = {"file": rel, "role": "focus", "mode": "full", "tokens": estimate_tokens(focus_src)}
        focus_block = f"# ===== FOCUS: {target} =====\n{focus_src}"
    else:
        # Body omitted -- the offload rewrite path already supplies it separately.
        # The FOCUS GATE above scanned the FULL focus text and would have returned
        # before reaching here; only the EMITTED text drops. focus_src is still read
        # and focus_unit still resolved the symbol's callees/callers. Provenance
        # must not claim mode "full"/full-body tokens for an omitted body.
        focus_block = f"# ===== FOCUS: {target} (body omitted -- supplied separately) ====="
        focus_inc = {"file": rel, "role": "focus", "mode": "omitted",
                     "tokens": estimate_tokens(focus_block)}
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

    # DOCUMENT LAYER, kept as its OWN neighbour class rather than merged into
    # dep_rels/caller_rels. Two reasons, both load-bearing:
    #
    #  * a link is not an import, and the roles must stay distinguishable in the
    #    ``included`` provenance -- a reader of the receipt has to be able to
    #    tell "the code this file needs" from "the prose that describes it";
    #  * the symbol path below feeds dep_rels/caller_rels into
    #    ``graph.callees``/``graph.callers``, which match IDENTIFIER TOKENS. Prose
    #    is full of words that look like identifiers, so a document merged into
    #    those sets would manufacture call edges out of English.
    #
    # Both maps are absent from an index built without documents, so this is
    # inert by construction on the default path.
    doc_edges = idx.get("document_links") or {}
    doc_rev = idx.get("document_links_reverse") or {}
    documents_out: set[str] = set()      # files THIS document links to
    documented_by: set[str] = set()      # documents that link to THIS file
    for r in doc_edges.get(rel, ()):
        if r != rel and r in modules:
            documents_out.add(r)
        elif r != rel:
            shell_stops += 1
    for src in doc_rev.get(rel, ()):
        if src != rel and src in modules:
            documented_by.add(src)
        elif src != rel:
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

    # ``not is_doc``: the symbol path is the CALL-GRAPH path, and a document has
    # no call graph. ``graph.callees`` resolves identifier TOKENS, and for a
    # document focus the resolver's same-file table is that document's own
    # headings -- so any prose word matching a heading title would be emitted as
    # a "callee", with its whole section body, under a label asserting a call
    # relation that does not exist. A document's real relations are its links,
    # and they are emitted below in their own section under their own name.
    if symbol and focus_unit is not None and not is_doc:
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

    # THE DOCUMENT RELATION LAYER, emitted on BOTH paths (symbol and module) and
    # for BOTH directions, because they answer two different questions that are
    # both wanted: distilling a spec should show the code it points at, and
    # distilling a source file should show the spec that describes it -- which is
    # the exact inverse of the defect this feature exists to fix.
    #
    # Same egress gate, same order (``_emit_ok`` BEFORE ``_skeleton``, so a file
    # that trips the floor is never read into the emitted text). Lowest keep rank
    # (0) so a token budget sheds prose before it sheds code.
    for role, rels in (("documents", sorted(documents_out)),
                       ("documented_by", sorted(documented_by))):
        kept_docs = [r for r in rels if _emit_ok(r, role)]
        if not kept_docs:
            continue
        label = ("DOCUMENTS (linked from this document)" if role == "documents"
                 else "DOCUMENTED BY (documents linking here)")
        section = f"\n# ===== {label}, skeleton ====="
        for r in kept_docs:
            sk = _skeleton(root, r)
            inc = {"file": r, "role": role, "mode": "skeleton",
                   "tokens": estimate_tokens(sk)}
            neighbors.append({"section": section, "text": sk,
                              "tokens": inc["tokens"], "keep": 0, "inc": inc})

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
    whole, whole_exact = _whole_repo_tokens(idx)
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
        # False => the index predates total_tokens, so the denominator fell back
        # to the chars/4 whole-repo estimate rather than the per-file token sum.
        # True only means "same tokenizer as the numerator", NOT "tiktoken-
        # measured" -- when tiktoken is absent both sides are chars/4 and the
        # ratio is consistent but the absolute count is a heuristic. Read
        # whole_repo_tokenizer for the honest label; a degraded tokenizer is
        # reported there, never silent.
        "whole_repo_tokens_exact": whole_exact,
        # Tokenizer behind whole_repo_tokens (see the focus-gate return above).
        "whole_repo_tokenizer": idx.get("tokenizer"),
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
    # Honest label: name the actual tokenizer instead of blanket "measured".
    # whole_repo_tokens_exact only says the denominator is the per-file token
    # sum (not the legacy chars/4 whole-repo fallback); it does NOT say a real
    # BPE tokenizer was used. tokenizer_name() already distinguishes the two.
    tk = res.get("whole_repo_tokenizer")
    if not res.get("whole_repo_tokens_exact"):
        denom = "ESTIMATED chars/4"
    elif tk and "heuristic" in tk:
        # tiktoken absent: per-file chars/4 sum. Consistent with the numerator,
        # but a heuristic -- do not call it "measured".
        denom = f"ESTIMATED {tk}"
    elif tk:
        denom = f"measured: {tk}"
    else:
        denom = "measured"
    print(f"  whole repo: {res['whole_repo_tokens']:>9} tokens  "
          f"(Repomix-style full concat; {denom})")
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
