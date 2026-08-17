"""EXPERIMENT probe: how large is the cross-module call-resolution gap?

Read-only. Parses the production packages with the stdlib AST (no imports of
repository code, no writes, no network, no subprocess) and measures, per
package, how many call sites a same-module fixed point can resolve versus how
many need the function/method resolution that Forest v2 proposes.

Motivation: the Gate-0 effect boundary resolves calls to a same-module fixed
point by design, and its inventory measured three concrete invisibility
classes caused by exactly this limit (cross-module-only sinks, dispatch
tables, subclass evasion).  Before Gate 2 invests in full function/method
resolution, this probe puts a number on the gap so the later experiment has a
baseline that was measured before the implementation existed.

Output: one JSON object on stdout.  Nothing else.  A ``main`` that only
prints is read-only and is deliberately not an effect entrypoint.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

PACKAGES = ("daedalus", "tools", "runs")


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def probe(root: Path) -> dict:
    per_package: dict[str, dict[str, int]] = {}
    for package in PACKAGES:
        directory = root / package
        if not directory.is_dir():
            continue
        stats = {
            "files": 0,
            "unparseable": 0,
            "functions": 0,
            "methods": 0,
            "call_sites": 0,
            "unresolvable_shape": 0,
            "same_module_resolvable": 0,
            "cross_module_or_dynamic": 0,
        }
        for path in sorted(directory.rglob("*.py")):
            stats["files"] += 1
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (OSError, UnicodeError, SyntaxError):
                stats["unparseable"] += 1
                continue
            local_functions: set[str] = set()
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    local_functions.add(node.name)
                    stats["functions"] += 1
                elif isinstance(node, ast.ClassDef):
                    for child in node.body:
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            local_functions.add(child.name)
                            stats["methods"] += 1
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                stats["call_sites"] += 1
                name = _call_name(node.func)
                if not name:
                    stats["unresolvable_shape"] += 1
                elif name.split(".")[-1] in local_functions:
                    stats["same_module_resolvable"] += 1
                else:
                    stats["cross_module_or_dynamic"] += 1
        per_package[package] = stats

    totals = {
        key: sum(stats[key] for stats in per_package.values())
        for key in next(iter(per_package.values()))
    }
    calls = totals["call_sites"] or 1
    return {
        "schema": "forest-v2-call-resolution-probe/1",
        "read_only": True,
        "packages": per_package,
        "totals": totals,
        "same_module_resolvable_pct": round(
            100.0 * totals["same_module_resolvable"] / calls, 1
        ),
        "gap_pct": round(
            100.0
            * (totals["cross_module_or_dynamic"] + totals["unresolvable_shape"])
            / calls,
            1,
        ),
    }


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
    print(json.dumps(probe(root), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
