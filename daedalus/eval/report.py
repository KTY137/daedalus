"""report.py -- render eval results as an ASCII table (Windows cp1252 safe).

No unicode box-drawing, no fancy glyphs: only ``+ - |`` so it prints on a raw
Windows console. Framing is honest: this is a small private directional eval,
recall is necessary-not-sufficient, and Tier 2 needs a runtime.
"""
from __future__ import annotations

HEADER = "Daedalus distillation eval -- private directional eval, NOT SWE-bench."


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


def render_tier1(result: dict) -> str:
    headers = ["TASK", "PROJECT", "RECALL", "COMPRESS", "SLICE_TOK", "WHOLE_TOK", "MISSED"]
    rows = []
    for t in result["per_task"]:
        rows.append([
            t["id"],
            t["project"],
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
        f"AGGREGATE over {result['n_tasks']} tasks:  "
        f"mean recall = {_pct(result['mean_recall'])}   "
        f"mean compression = {_pct(result['mean_compression'])}",
    ]
    misses = [t for t in result["per_task"] if t["missed"]]
    if misses:
        lines.append("")
        lines.append(f"SLICE-RECALL MISSES ({result['n_slice_recall_misses']}) "
                     "-- symbols the current slice dropped (feedback for structcore):")
        for t in misses:
            lines.append(f"  {t['id']} [{t['target']}]: missing {', '.join(t['missed'])}")
    else:
        lines.append("")
        lines.append("SLICE-RECALL MISSES: none -- every labelled symbol was "
                     "reachable in its slice.")
    return "\n".join(lines)


def render_tier2(result: dict) -> str:
    if result.get("skipped"):
        return "\n".join([
            "",
            "TIER 2 -- LLM task-success (distilled slice A vs whole-repo concat B).",
            f"  SKIPPED: {result['reason']}",
        ])

    headers = ["TASK", "PROJECT", "OK_A", "OK_B", "TOK_A", "TOK_B"]
    rows = []
    for t in result["per_task"]:
        rows.append([
            t["id"],
            t["project"],
            "yes" if t["success_A"] else "no",
            "yes" if t["success_B"] else "no",
            f"{t['tokens_A']:,}",
            f"{t['tokens_B']:,}",
        ])
    prov = result["provider"]
    tok_a, tok_b = result["tokens_A"], result["tokens_B"]
    ratio = f"{100 * tok_a / tok_b:.1f}%" if tok_b else "n/a"
    lines = [
        "",
        "TIER 2 -- LLM task-success (distilled slice A vs whole-repo concat B).",
        f"provider: {prov['kind']} model={prov['model']} host={prov['host']}",
        "  the win: A ~= B success at a fraction of B's tokens.",
        "",
        _table(headers, rows),
        "",
        f"AGGREGATE over {result['n_tasks']} tasks:  "
        f"success A = {result['success_A']}/{result['n_tasks']}   "
        f"success B = {result['success_B']}/{result['n_tasks']}",
        f"  tokens: A = {tok_a:,}   B = {tok_b:,}   (A is {ratio} of B)",
    ]
    return "\n".join(lines)


def render(tier1: dict, tier2: dict | None = None) -> str:
    out = render_tier1(tier1)
    if tier2 is not None:
        out += "\n" + render_tier2(tier2)
    return out
