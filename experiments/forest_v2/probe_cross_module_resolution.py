"""EXPERIMENT probe: what does import-binding resolution add over same-module?

Read-only continuation of ``probe_call_resolution.py`` under the same frozen
frame (stdlib AST only, no imports of repository code, no writes, no network,
no subprocess; one JSON object on stdout).  It measures three mechanically
checkable claims BEFORE Gate 2 builds a real resolver:

1. **Cross-module attribution.**  With per-file import bindings (``import x``,
   ``import x as y``, ``from x import f``, relative forms) a call site whose
   name resolves through a binding is *attributed*: either verified against
   the repo's own module symbol tables (``cross_module_repo``) or attributed
   to an external module without verification (``cross_module_external`` —
   enough for sink matching, not for existence proofs).  The counting rule is
   the baseline probe's: a site the generous same-module rule already claims
   stays in ``same_module_resolvable``; the new buckets only split the
   baseline's ``cross_module_or_dynamic``.
2. **Subclass evasion detectability.**  Every class base is resolved through
   the same bindings; a base attributed to an external sink module (the
   ``room_server`` case: ``ThreadingHTTPServer`` from ``http.server``) is
   mechanically visible instead of a hand-registered review finding.
3. **Registry-dispatch detectability.**  A local decorator whose body appends
   into a module-level registry (the ``system_check`` case: ``@check`` into
   ``CHECKS``) is detected structurally: the registered functions are known
   even though their call site is a subscript expression.

The ``guarded_call`` invisibility class is expected to STAY invisible (its
sink crosses an interpreter boundary, not an import); the probe reports what
it finds there so the negative result is retained, not assumed.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

PACKAGES = ("daedalus", "tools", "runs")

ACCEPTANCE_FILES = (
    "tools/guarded_call.py",
    "tools/system_check.py",
    "runs/council/room_server.py",
)


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _module_name(root: Path, path: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _collect_symbols(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _bindings(tree: ast.Module, module: str) -> dict[str, str]:
    """Local name -> dotted target ('pkg.mod' for modules, 'pkg.mod.sym' for symbols)."""
    package_parts = module.split(".")[:-1]
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                target = alias.name if alias.asname else alias.name.split(".")[0]
                out[local] = target
        elif isinstance(node, ast.ImportFrom):
            if node.module is None and node.level == 0:
                continue
            if node.level:
                base_parts = package_parts[: len(package_parts) - (node.level - 1)]
                base = ".".join(base_parts + ([node.module] if node.module else []))
            else:
                base = node.module or ""
            if not base:
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                out[alias.asname or alias.name] = f"{base}.{alias.name}"
    return out


def _registry_decorators(tree: ast.Module) -> dict[str, str]:
    """Decorator name -> registry name, for local decorators that append/assign into
    a module-level registry."""
    module_level = {
        target.id
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        if isinstance(target, ast.Name)
    }
    found: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            name = _call_name(inner.func)
            head, _, tail = name.partition(".")
            if tail in {"append", "add", "setdefault", "update"} and head in module_level:
                found[node.name] = head
    return found


def probe(root: Path) -> dict:
    files: list[tuple[str, Path, ast.Module]] = []
    module_symbols: dict[str, set[str]] = {}
    for package in PACKAGES:
        directory = root / package
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (OSError, UnicodeError, SyntaxError):
                continue
            module = _module_name(root, path)
            files.append((module, path, tree))
            module_symbols[module] = _collect_symbols(tree)

    totals = {
        "call_sites": 0,
        "unresolvable_shape": 0,
        "same_module_resolvable": 0,
        "cross_module_repo": 0,
        "cross_module_external": 0,
        "still_unattributed": 0,
        "classes": 0,
        "classes_with_external_base": 0,
        "classes_with_repo_base": 0,
        "registry_decorators": 0,
        "registry_registered_functions": 0,
    }
    acceptance: dict[str, dict] = {}

    for module, path, tree in files:
        rel = path.relative_to(root).as_posix()
        local_functions: set[str] = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                local_functions.add(node.name)
            elif isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        local_functions.add(child.name)
        bindings = _bindings(tree, module)
        registries = _registry_decorators(tree)
        registered = 0
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    name = _call_name(
                        decorator.func if isinstance(decorator, ast.Call) else decorator
                    )
                    if name in registries:
                        registered += 1
        totals["registry_decorators"] += len(registries)
        totals["registry_registered_functions"] += registered

        file_report = {
            "cross_module_repo_targets": [],
            "external_bases": [],
            "registries": registries,
            "registered_functions": registered,
        }

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                totals["classes"] += 1
                for base in node.bases:
                    base_name = _call_name(base)
                    if not base_name:
                        continue
                    head, _, rest = base_name.partition(".")
                    target = bindings.get(head)
                    if target is None:
                        continue
                    dotted = f"{target}.{rest}" if rest else target
                    owner = dotted.rsplit(".", 1)[0] if "." in dotted else dotted
                    if owner in module_symbols or dotted in module_symbols:
                        totals["classes_with_repo_base"] += 1
                    else:
                        totals["classes_with_external_base"] += 1
                        file_report["external_bases"].append(
                            {"class": node.name, "base": dotted}
                        )
            if not isinstance(node, ast.Call):
                continue
            totals["call_sites"] += 1
            name = _call_name(node.func)
            if not name:
                totals["unresolvable_shape"] += 1
                continue
            if name.split(".")[-1] in local_functions:
                totals["same_module_resolvable"] += 1
                continue
            head, _, rest = name.partition(".")
            target = bindings.get(head)
            if target is None:
                totals["still_unattributed"] += 1
                continue
            dotted = f"{target}.{rest}" if rest else target
            owner, _, symbol = dotted.rpartition(".")
            if owner in module_symbols and symbol in module_symbols[owner]:
                totals["cross_module_repo"] += 1
                if rel in ACCEPTANCE_FILES:
                    file_report["cross_module_repo_targets"].append(dotted)
            elif dotted in module_symbols:
                totals["cross_module_repo"] += 1
            else:
                totals["cross_module_external"] += 1
        if rel in ACCEPTANCE_FILES:
            acceptance[rel] = file_report

    calls = totals["call_sites"] or 1
    attributed = (
        totals["same_module_resolvable"]
        + totals["cross_module_repo"]
        + totals["cross_module_external"]
    )
    return {
        "schema": "forest-v2-cross-module-resolution-probe/1",
        "read_only": True,
        "totals": totals,
        "attributed_pct": round(100.0 * attributed / calls, 1),
        "cross_module_repo_pct": round(100.0 * totals["cross_module_repo"] / calls, 1),
        "still_unattributed_pct": round(
            100.0
            * (totals["still_unattributed"] + totals["unresolvable_shape"])
            / calls,
            1,
        ),
        "acceptance_sites": acceptance,
    }


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
    print(json.dumps(probe(root), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
