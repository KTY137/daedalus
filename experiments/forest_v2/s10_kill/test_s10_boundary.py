"""The isolation claims of this slice, enforced instead of asserted in prose.

The shared forest_v2 README makes three promises about experiment code: it
imports no production package, no production package imports it, and it
adds no effectful entrypoint under ``experiments/`` (an unscanned effectful
directory is exactly the blind spot the Gate-0 boundary work closed).

A promise in a docstring decays.  These checks read the slice's own source
with the stdlib AST and fail when it stops being true.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import List

PACKAGE = Path(__file__).resolve().parent
MODULES = sorted(p for p in PACKAGE.glob("*.py"))
NON_TEST_MODULES = [p for p in MODULES if not p.name.startswith("test_")]

#: Import roots this slice may not touch: the kernel, its harness siblings,
#: and anything that reaches the outside world.
FORBIDDEN_ROOTS = {
    "daedalus",
    "tools",
    "runs",
    "subprocess",
    "socket",
    "urllib",
    "http",
    "requests",
    "shutil",
    "ftplib",
    "smtplib",
    "asyncio",
    "multiprocessing",
}

#: Attribute calls that mutate the filesystem.  Matched by name alone, so
#: this is deliberately over-strict: ``str.replace`` trips the same wire as
#: ``Path.replace``.  That is the intended trade -- an allowlist of "safe"
#: call sites is exactly the thing that erodes until the check means
#: nothing, and the slice loses nothing by phrasing itself differently.
WRITE_METHODS = {
    "write_text", "write_bytes", "mkdir", "touch", "unlink", "rmdir",
    "rename", "replace", "symlink_to", "chmod", "remove", "makedirs",
    "rmtree", "copy", "copyfile", "move",
}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _import_roots(tree: ast.Module) -> List[str]:
    roots: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative: inside this package by construction
                continue
            if node.module:
                roots.append(node.module.split(".")[0])
    return roots


def test_the_slice_has_modules_to_check():
    assert NON_TEST_MODULES, "no source found; the checks below would pass vacuously"


def test_no_module_imports_the_kernel_or_reaches_outside():
    offenders = []
    for path in MODULES:
        for root in _import_roots(_tree(path)):
            if root in FORBIDDEN_ROOTS:
                offenders.append(f"{path.name} imports {root}")
    assert offenders == [], f"isolation broken: {offenders}"


def test_every_import_is_standard_library():
    """No third-party dependency may creep into a slice meant to be re-run later."""
    allowed = set(sys.stdlib_module_names) | {"pytest"}
    strays = []
    for path in MODULES:
        for root in _import_roots(_tree(path)):
            if root not in allowed:
                strays.append(f"{path.name}: {root}")
    assert strays == [], f"non-stdlib imports: {strays}"


def test_the_evaluator_writes_nothing():
    """Read-only in fact, not only in the docstring."""
    offenders = []
    for path in NON_TEST_MODULES:
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in WRITE_METHODS:
                offenders.append(f"{path.name}: .{func.attr}()")
            if isinstance(func, ast.Name) and func.id == "open":
                mode = ""
                if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                    mode = str(node.args[1].value)
                for kw in node.keywords:
                    if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                        mode = str(kw.value.value)
                if any(ch in mode for ch in "wax+"):
                    offenders.append(f"{path.name}: open(mode={mode!r})")
    assert offenders == [], f"this slice must not write: {offenders}"


def test_nothing_in_the_package_defines_an_effectful_entrypoint():
    """The only ``main`` is the printing CLI; nothing else claims an entrypoint."""
    mains = []
    for path in NON_TEST_MODULES:
        for node in _tree(path).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main":
                mains.append(path.name)
    assert mains == ["cli.py"], f"unexpected entrypoints: {mains}"
