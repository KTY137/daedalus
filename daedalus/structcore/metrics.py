# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Per-file health metrics — the 'code health' signal, comment-aware per language.

Stdlib-only baseline (LOC, function count, comment density, guard/over-defensive
density, long-function flag). If ``lizard`` is installed, real cyclomatic
complexity (avg/max) is added for the languages lizard supports.
"""
from __future__ import annotations

import io
import re
import tokenize
from functools import lru_cache

from .languages import LanguageSpec
from .parse import CodeUnit

_LONG_FN = 60


@lru_cache(maxsize=1)
def lizard_available() -> bool:
    try:
        import lizard  # noqa: F401

        return True
    except Exception:
        return False


def file_metrics(module: str, text: str, spec: LanguageSpec,
                 units: list[CodeUnit]) -> dict:
    lines = text.splitlines()
    loc = len(lines)
    comment_lines = _count_comments(text, spec)
    guard = _count_guards(text, spec)
    long_fns = [{"name": u.name, "line": u.line, "loc": u.loc}
                for u in units if u.loc > _LONG_FN]

    metrics = {
        "language": spec.name,
        "loc": loc,
        "n_functions": len(units),
        "comment_density": round(comment_lines / max(loc, 1), 3),
        "guard_density": round(guard / max(loc, 1), 3),
        "guard_count": guard,
        "long_functions": long_fns,
    }
    cc = _lizard_cc(module, text) if lizard_available() else None
    if cc:
        metrics.update(cc)
    return metrics


def _count_comments(text: str, spec: LanguageSpec) -> int:
    if spec.name == "python":
        n = 0
        try:
            for tok in tokenize.generate_tokens(io.StringIO(text).readline):
                if tok.type == tokenize.COMMENT:
                    n += 1
        except (tokenize.TokenError, IndentationError):
            pass
        return n
    n = 0
    in_block = False
    block = spec.block_comment[0] if spec.block_comment else None
    for raw in text.splitlines():
        line = raw.strip()
        if in_block:
            n += 1
            if block and block[1] in line:
                in_block = False
            continue
        if block and block[0] in line and block[1] not in line:
            in_block = True
            n += 1
            continue
        if any(line.startswith(m) for m in spec.line_comment) or (block and block[0] in line):
            n += 1
    return n


def _count_guards(text: str, spec: LanguageSpec) -> int:
    n = 0
    for kw in spec.guard_keywords:
        if kw.isalpha():
            n += len(re.findall(rf"\b{re.escape(kw)}\b", text))
        else:
            n += text.count(kw)
    return n


def _lizard_cc(module: str, text: str) -> dict | None:
    import lizard

    ext = "." + module.rsplit(".", 1)[-1] if "." in module else ".txt"
    try:
        analysis = lizard.analyze_file.analyze_source_code(module, text)
    except Exception:
        return None
    ccs = [f.cyclomatic_complexity for f in analysis.function_list]
    if not ccs:
        return None
    return {"cc_avg": round(sum(ccs) / len(ccs), 1), "cc_max": max(ccs)}
