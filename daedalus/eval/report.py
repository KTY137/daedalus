"""report.py -- render eval results as an ASCII table (Windows cp1252 safe).

No unicode box-drawing, no fancy glyphs: only ``+ - |`` so it prints on a raw
Windows console. Framing is honest: this is a small private directional eval,
recall is necessary-not-sufficient, Tier 2 needs a runtime, and -- the point of
this module -- "hand_reachable" recall is partly self-graded and MUST NOT be
blended with independently-derived recall into one headline number.
"""
from __future__ import annotations

HEADER = "Daedalus distillation eval -- private directional eval, NOT SWE-bench."

# Plain-English disclaimer per provenance -- printed on every render that
# includes a "hand_reachable" bucket. This is the single most important line
# in this file: it is what stops the eval from overclaiming.
_PROVENANCE_NOTE = {
    "hand_reachable": (
        "PARTIALLY SELF-GRADED: a human picked these labels AND verified them "
        "reachable by running the same slicer being graded. Treat this recall "
        "as an upper bound / sanity check, NOT independent proof the slicer works."
    ),
    "independent_diff": (
        "INDEPENDENT: labels derived from what an on-disk diff literally "
        "changed -- no graph walk involved. This recall is not self-graded."
    ),
    "temporal_churn": (
        "INDEPENDENT: labels derived from git co-change (files that change "
        "together) -- no graph walk involved. This recall is not self-graded."
    ),
}


def _rule(widths: list[int]) -> str:
    return "+" + "+".join("-" * (w + 2) for w in widths) + "+"


def _row(cells: list[str], widths: list[int]) -> str:
    return "| " + " | ".join(c.ljust(w) for c, w in zip(cells, widths)) + " |"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(h) for h in headers]
    for r in rows:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], len(c))
    out = [_rule(widths), _row(headers, widths), _rule(widths)]
    out += [_row(r, widths) for r in rows]
    out.append(_rule(widths))
    return "\n".join(out)


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def _provenance_breakdown_lines(by_provenance: dict, recall_key: str = "mean_recall",
                                compression_key: str | None = "mean_compression") -> list[str]:
    """Shared renderer for the "PROVENANCE BREAKDOWN" block used by both Tier 1
    and the arms report. Always shows both tiers (even when empty) and always
    prints the honesty note -- this block is the deliverable of this sprint."""
    lines = [
        "PROVENANCE BREAKDOWN (never blended -- this is the honest number):",
    ]
    headers = ["PROVENANCE", "TIER", "N", "RECALL"]
    if compression_key:
        headers.append("COMPRESSION")
    rows = []
    for prov in sorted(by_provenance):
        note = _PROVENANCE_NOTE.get(prov, "")
        lines.append(f"  [{prov}] {note}")
        for tier in ("primary", "quarantine"):
            agg = by_provenance[prov][tier]
            if agg["n_tasks"] == 0:
                continue
            row = [prov, tier, str(agg["n_tasks"]), _pct(agg[recall_key])]
            if compression_key:
                row.append(_pct(agg[compression_key]))
            rows.append(row)
    if rows:
        lines.append("")
        lines.append(_table(headers, rows))
    lines.append("")
    lines.append("  NOTE: \"quarantine\" rows are excluded from every go/no-go "
                 "number above and reported here only for flywheel visibility.")
    return lines


def render_tier1(result: dict) -> str:
    headers = ["TASK", "PROJECT", "PROVENANCE", "TIER", "RECALL", "COMPRESS",
               "SLICE_TOK", "WHOLE_TOK", "MISSED"]
    rows = []
    # Errored rows carry no recall/compression/slice_tokens/... at all (see
    # harness._task_error_row) -- they get their own ERRORED section below,
    # not a row in this recall/compression table.
    for t in result["per_task"]:
        if "error" in t:
            continue
        rows.append([
            t["id"],
            t["project"],
            t["label_provenance"],
            t["label_tier"],
            _pct(t["recall"]),
            _pct(t["compression"]),
            f"{t['slice_tokens']:,}",
            f"{t['whole_repo_tokens']:,}",
            ",".join(t["missed"]) if t["missed"] else "-",
        ])
    lines = [
        HEADER,
        "",
        "TIER 1 -- deterministic slice recall + compression (no LLM).",
        f"tokenizer: {result['tokenizer']}",
        "  recall     = fraction of must-include symbols present in the slice",
        "               (necessary, not sufficient -- proves no load-bearing",
        "                context was dropped).",
        "  compression = 1 - slice_tokens / whole_repo_tokens.",
        "",
        _table(headers, rows),
        "",
        f"{result['n_tasks']} tasks total "
        f"({result['n_primary_tasks']} primary, {result['n_quarantine_tasks']} quarantine).",
        "",
    ]
    lines += _provenance_breakdown_lines(result["by_provenance"])
    # Healthy (non-errored) misses only -- an errored task has no "missed"
    # list at all (it never got as far as measuring recall); it is reported
    # below, in its own unmissable section, not folded in here as a miss.
    misses = [t for t in result["per_task"] if "error" not in t and t["missed"]]
    if misses:
        lines.append("")
        lines.append(f"SLICE-RECALL MISSES ({len(misses)}) "
                     "-- symbols the current slice dropped (feedback for structcore):")
        for t in misses:
            lines.append(f"  {t['id']} [{t['target']}] ({t['label_provenance']}/{t['label_tier']}): "
                         f"missing {', '.join(t['missed'])}")
    else:
        lines.append("")
        lines.append("SLICE-RECALL MISSES: none -- every labelled symbol was "
                     "reachable in its slice.")
    # ERRORED section -- a per-task resolution failure (bad repo label, or a
    # target no longer in the index -- e.g. a quarantined mint task whose file
    # moved) is EXCLUDED from every mean above but must never go unreported:
    # "a degraded measurement is reported, never silent." Absent entirely
    # (result.get, not result[...]) for any pre-existing caller that hand-built
    # a Tier-1 result dict without this key -- and always absent when there are
    # zero errored tasks, so this block adds NO lines to that report.
    errored = result.get("errored") or []
    if errored:
        lines.append("")
        lines.append(f"*** ERRORED TASKS ({len(errored)}) -- resolution failed, "
                     "EXCLUDED from every recall/compression figure above, "
                     "reported here so nothing goes silently missing: ***")
        for t in sorted(errored, key=lambda r: r["id"]):
            lines.append(f"  {t['id']} [{t.get('target')}] "
                         f"({t['label_provenance']}/{t['label_tier']}): {t['error']}")
    return "\n".join(lines)


def render_arms(result: dict) -> str:
    """A/B/C: distilled slice vs whole-repo concat vs BM25 retrieval. Model-free
    (recall via substring match, no LLM), so this runs offline every time."""
    headers = ["TASK", "PROVENANCE", "TIER", "R_A", "R_B", "R_C",
               "TOK_A", "TOK_B(true)", "TOK_C", "B_TRUNC@CAP", "C_TRUNC@BUDGET", "C>=A"]
    rows = []
    # Errored rows carry no recall_A/tokens_A/... at all (see harness._task_error_row)
    # -- they are reported in their own section below, not in this table.
    healthy = [t for t in result["per_task"] if "error" not in t]
    for t in healthy:
        rows.append([
            t["id"], t["label_provenance"], t["label_tier"],
            _pct(t["recall_A"]), _pct(t["recall_B"]), _pct(t["recall_C"]),
            f"{t['tokens_A']:,}", f"{t['tokens_B']:,}", f"{t['tokens_C']:,}",
            "yes" if t["b_truncated_at_cap"] else "no",
            "yes" if t["c_truncated_at_budget"] else "no",
            "YES" if t["c_beats_a"] else "no",
        ])
    lines = [
        "",
        "ARMS A/B/C -- distilled slice (A) vs whole-repo concat (B) vs BM25 "
        "retrieval (C). Deterministic, no LLM.",
        "  A = today's semantic_slice.",
        "  B = naive whole-repo concat. R_B/TOK_B are measured against the TRUE, "
        "FULL, UNTRUNCATED repo text -- beating a truncated B is not a win.",
        "      B_TRUNC@CAP = yes means: if this task ran Tier 2, B would be cut "
        "down to fit the model's context window -- a WEAKER baseline than the "
        "R_B/TOK_B shown here.",
        "  C = BM25 (k1=1.2, b=0.75) top-k retrieval, budgeted to the SAME token "
        "count as A. The 'dumb retrieval' baseline that matters commercially.",
        "",
        _table(headers, rows),
        "",
    ]
    lines += _provenance_breakdown_lines(
        result["by_provenance"], recall_key="mean_recall_A", compression_key=None)
    lines.append("")
    lines.append("A vs B vs C, mean recall / mean tokens, by provenance x tier "
                 "(quarantine excluded from any go/no-go read):")
    agg_headers = ["PROVENANCE", "TIER", "N", "R_A", "R_B", "R_C",
                   "TOK_A", "TOK_B", "TOK_C"]
    agg_rows = []
    for prov in sorted(result["by_provenance"]):
        for tier in ("primary", "quarantine"):
            agg = result["by_provenance"][prov][tier]
            if agg["n_tasks"] == 0:
                continue
            agg_rows.append([
                prov, tier, str(agg["n_tasks"]),
                _pct(agg["mean_recall_A"]), _pct(agg["mean_recall_B"]), _pct(agg["mean_recall_C"]),
                f"{agg['mean_tokens_A']:,.0f}", f"{agg['mean_tokens_B']:,.0f}", f"{agg['mean_tokens_C']:,.0f}",
            ])
    if agg_rows:
        lines.append("")
        lines.append(_table(agg_headers, agg_rows))

    # c_beats_a is tie-inclusive (recall_C >= recall_A, see harness.eval_task_arms)
    # so this block -- not the "no" cells under the C>=A column -- is where a
    # tie surfaces. A tie ("BM25 matches the product's recall at equal cost")
    # is the commercially damning case, not merely a strict loss for A.
    beats = [t for t in healthy if t["c_beats_a"]]
    lines.append("")
    if beats:
        lines.append(f"*** C (BM25) TIES OR BEATS A (semantic slice) on "
                     f"{len(beats)}/{len(healthy)} tasks -- reported loudly, "
                     "not smoothed over: ***")
        for t in beats:
            lines.append(f"  {t['id']}: recall_C={_pct(t['recall_C'])} >= "
                         f"recall_A={_pct(t['recall_A'])}  (tokens_C={t['tokens_C']:,}, "
                         f"tokens_A={t['tokens_A']:,})")
    else:
        lines.append("C never tied or beat A's recall on this task set.")

    trunc = [t for t in healthy if t["b_truncated_at_cap"]]
    if trunc:
        lines.append("")
        lines.append(f"B WOULD BE TRUNCATED for {len(trunc)}/{len(healthy)} tasks if run "
                     "through Tier 2 (context-window cap) -- the R_B/TOK_B columns above are "
                     "the TRUE untruncated baseline, not what a live LLM run would see:")
        for t in trunc:
            lines.append(f"  {t['id']}: true tokens_B={t['tokens_B']:,}  "
                         f"capped tokens_B={t['tokens_B_capped_at_default']:,}")

    # ERRORED section -- same rationale as render_tier1's: excluded from every
    # arm/aggregate above, never silently dropped. Absent when there are none.
    errored = result.get("errored") or []
    if errored:
        lines.append("")
        lines.append(f"*** ERRORED TASKS ({len(errored)}) -- resolution failed, "
                     "EXCLUDED from every arm/aggregate above, reported here so "
                     "nothing goes silently missing: ***")
        for t in sorted(errored, key=lambda r: r["id"]):
            lines.append(f"  {t['id']} [{t.get('target')}] "
                         f"({t['label_provenance']}/{t['label_tier']}): {t['error']}")
    return "\n".join(lines)


def render_tier2(result: dict) -> str:
    if result.get("skipped"):
        return "\n".join([
            "",
            "TIER 2 -- LLM task-success (distilled slice A vs whole-repo concat B).",
            f"  SKIPPED: {result['reason']}",
        ])

    headers = ["TASK", "PROJECT", "OK_A", "OK_B", "TOK_A", "TOK_B", "TOK_B(true)", "B_TRUNC"]
    rows = []
    for t in result["per_task"]:
        rows.append([
            t["id"],
            t["project"],
            "yes" if t["success_A"] else "no",
            "yes" if t["success_B"] else "no",
            f"{t['tokens_A']:,}",
            f"{t['tokens_B']:,}",
            f"{t.get('tokens_B_true', t['tokens_B']):,}",
            "yes" if t["b_truncated"] else "no",
        ])
    prov = result["provider"]
    tok_a, tok_b = result["tokens_A"], result["tokens_B"]
    ratio = f"{100 * tok_a / tok_b:.1f}%" if tok_b else "n/a"
    lines = [
        "",
        "TIER 2 -- LLM task-success (distilled slice A vs whole-repo concat B).",
        f"provider: {prov['kind']} model={prov['model']} host={prov['host']}",
        "  the win: A ~= B success at a fraction of B's tokens.",
        "  TOK_B is what was actually sent to the model (may be truncated to fit "
        "the context window); TOK_B(true) is the real, untruncated whole-repo size.",
        "",
        _table(headers, rows),
        "",
        f"AGGREGATE over {result['n_tasks']} tasks:  "
        f"success A = {result['success_A']}/{result['n_tasks']}   "
        f"success B = {result['success_B']}/{result['n_tasks']}",
        f"  tokens: A = {tok_a:,}   B (sent) = {tok_b:,}   B (true, untruncated) = "
        f"{result.get('tokens_B_true', tok_b):,}   (A is {ratio} of B-sent)",
    ]
    if result.get("b_truncated_any"):
        lines.append("  WARNING: B was TRUNCATED to fit the model's context window for "
                     "at least one task -- B (sent) above understates the real whole-repo "
                     "baseline; a truncated baseline is a WEAKER one, not a fair comparison.")
    errored = result.get("errored") or []
    if errored:
        lines.append("")
        lines.append(f"*** ERRORED TASKS ({len(errored)}) -- resolution failed before an LLM "
                     "call was made, SKIPPED (not counted in the aggregate above): ***")
        for t in sorted(errored, key=lambda r: r["id"]):
            lines.append(f"  {t['id']} [{t.get('target')}] "
                         f"({t['label_provenance']}/{t['label_tier']}): {t['error']}")
    return "\n".join(lines)


def render_gate(result: dict) -> str:
    """ADVISORY regression-ratchet report -- see harness.run_gate docstring.
    This never blocks anything by itself; it is a local developer command."""
    banner = "PASS" if result["passed"] else "FAIL"
    lines = [
        "",
        "GATE -- counterfactual per-task recall regression ratchet (ADVISORY ONLY, "
        "never wired to block autonomous actions).",
        f"baseline: {result['baseline_path']}",
        f"checked {result['n_checked']} primary-tier task(s) against the stored baseline.",
        "",
        f"RESULT: {banner}",
    ]
    if result["regressions"]:
        lines.append("")
        lines.append(f"REGRESSIONS ({len(result['regressions'])}) -- recall DECREASED vs baseline:")
        for r in result["regressions"]:
            lines.append(f"  {r['id']}: {_pct(r['baseline_recall'])} -> {_pct(r['current_recall'])} "
                         f"(delta {_pct(r['delta'])})  missed now: {', '.join(r['missed']) or '-'}")
    if result["improved"]:
        lines.append("")
        lines.append(f"IMPROVED ({len(result['improved'])}):")
        for r in result["improved"]:
            lines.append(f"  {r['id']}: {_pct(r['baseline_recall'])} -> {_pct(r['current_recall'])}")
    if result["new_tasks"]:
        lines.append("")
        lines.append(f"NEW (no baseline entry yet, not gated): {', '.join(result['new_tasks'])}")
    if result["missing_tasks"]:
        lines.append("")
        lines.append(f"IN BASELINE BUT NOT IN THIS RUN: {', '.join(result['missing_tasks'])}")
    # Errored tasks (result.get: absent for any hand-built pre-existing gate
    # result dict, and always absent -> no lines added when there are none).
    errored_primary = result.get("errored_primary") or []
    if errored_primary:
        lines.append("")
        lines.append(f"*** PRIMARY TASK(S) FAILED TO RESOLVE ({len(errored_primary)}) -- "
                     "this FAILS the gate (a broken primary corpus must scream): ***")
        for r in errored_primary:
            lines.append(f"  {r['id']} [{r.get('target')}]: {r['error']}")
    errored_quarantine = result.get("errored_quarantine") or []
    if errored_quarantine:
        lines.append("")
        lines.append(f"ERRORED QUARANTINE TASK(S) ({len(errored_quarantine)}) -- "
                     "reported only, does NOT fail the gate:")
        for r in errored_quarantine:
            lines.append(f"  {r['id']} [{r.get('target')}]: {r['error']}")
    if not result["regressions"] and not errored_primary:
        lines.append("")
        lines.append("No primary-tier task lost recall vs the stored baseline.")
    lines.append("")
    lines.append("Run 'python -m daedalus.eval --update-baseline' to intentionally "
                 "accept the current numbers as the new baseline (explicit only, never automatic).")
    return "\n".join(lines)


def render(tier1: dict, tier2: dict | None = None, arms: dict | None = None) -> str:
    out = render_tier1(tier1)
    if arms is not None:
        out += "\n" + render_arms(arms)
    if tier2 is not None:
        out += "\n" + render_tier2(tier2)
    return out
