"""A module that computes the repository root from ``__file__`` must count.

WHY THIS EXISTS. ``Path(__file__).resolve().parents[1]`` is correct for exactly
one location -- a module sitting directly under ``daedalus/`` -- and silently
wrong everywhere else. It does not raise, does not warn, and does not fail at
import: it just hands back a directory one level too shallow, and the failure
surfaces later as an empty registry, a missing catalogue, or a file the caller
swears it wrote.

Measured on 2026-09-02, during G1-FLAT-04: relocating eleven modules one level
deeper left six such derivations behind. Nothing caught them at the moment of
the move. ``daedalus.foundation.projects`` reported ``Known projects: none``
against a populated registry, and the failure landed eleven test files away
from the edit that caused it. A seventh had been wrong since G1-FLAT-01 nine
commits earlier -- ``gui_catalogue``'s legacy catalogue fallback pointed at
``daedalus/catalogue/gui``, a directory that has never existed -- and was
invisible because the packaged-resource path is tried first.

THE RULE. If a module N components below the repository root writes
``Path(__file__).resolve().parents[K]``, then ``K`` must be ``N - 1`` for that
expression to BE the repository root. This test does not assume every such
expression means the repository root; it checks the ones bound to a name that
says so, which is the form that has actually gone wrong here.

WHAT IT DELIBERATELY DOES NOT DO. It does not forbid the idiom, and it does not
require a shared constant. A leaf module that computes its own root has one
honest dependency; a module that imports a root constant has one more import
and the same failure mode if that constant is wrong. The defect was never the
idiom, it was that nothing counted.
"""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: Names whose value is asserted to be the repository root. A name outside this
#: set may legitimately point anywhere -- a package directory, a data folder --
#: and this contract says nothing about it.
ROOT_NAMES = frozenset({"ROOT", "REPO", "REPO_ROOT", "HARNESS_ROOT", "PROJECT_ROOT"})


def _tracked_python_files() -> tuple[str, ...]:
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--", "daedalus"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        timeout=30,
    )
    return tuple(
        sorted(
            raw.decode("utf-8")
            for raw in completed.stdout.split(b"\0")
            if raw.endswith(b".py")
        )
    )


def _parents_index(node: ast.AST) -> int | None:
    """``Path(__file__).resolve().parents[K]`` -> K, else None.

    ``.resolve()`` is optional and ``.parent.parent`` chains are counted too,
    because both forms appear in this tree and both encode the same hop count.
    """
    if isinstance(node, ast.Subscript):
        value = node.value
        if (
            isinstance(value, ast.Attribute)
            and value.attr == "parents"
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, int)
            and _is_file_path(value.value)
        ):
            return node.slice.value
        return None
    hops = 0
    cursor = node
    while isinstance(cursor, ast.Attribute) and cursor.attr == "parent":
        hops += 1
        cursor = cursor.value
    if hops and _is_file_path(cursor):
        return hops - 1
    return None


def _is_file_path(node: ast.AST) -> bool:
    """``Path(__file__)`` with any number of no-argument calls chained on."""
    while isinstance(node, ast.Call) and not node.args and not node.keywords:
        if not isinstance(node.func, ast.Attribute):
            return False
        node = node.func.value
    if not isinstance(node, ast.Call) or len(node.args) != 1:
        return False
    func = node.func
    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
    argument = node.args[0]
    return name == "Path" and isinstance(argument, ast.Name) and argument.id == "__file__"


def _root_derivations(source: str) -> list[tuple[str, int, int]]:
    """(name, lineno, parents-index) for every assignment naming the root."""
    out: list[tuple[str, int, int]] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value: ast.AST | None = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
            value = node.value
        else:
            continue
        if value is None:
            continue
        # the derivation may be the whole value or the left half of a `/ "x"`
        candidates = [value]
        cursor = value
        while isinstance(cursor, ast.BinOp) and isinstance(cursor.op, ast.Div):
            cursor = cursor.left
            candidates.append(cursor)
        for name in targets:
            if name not in ROOT_NAMES:
                continue
            for candidate in candidates:
                index = _parents_index(candidate)
                if index is not None:
                    out.append((name, node.lineno, index))
                    break
    return out


def test_every_repository_root_derivation_counts_its_own_depth() -> None:
    wrong: list[str] = []
    checked = 0
    for relative in _tracked_python_files():
        source = (ROOT / relative).read_text(encoding="utf-8", errors="replace")
        if "__file__" not in source:
            continue
        for name, lineno, index in _root_derivations(source):
            checked += 1
            expected = len(Path(relative).parts) - 1
            if index != expected:
                wrong.append(
                    f"{relative}:{lineno}: {name} = parents[{index}], "
                    f"but this file is {len(Path(relative).parts)} components "
                    f"below the repository, so the root is parents[{expected}]"
                )
    assert wrong == [], "\n".join(wrong)
    # A checker that finds nothing because it matched nothing is not a clean
    # tree, it is a broken instrument. Measured at 6 on 2026-09-02; the floor
    # is what keeps a future refactor of the matcher from going quiet.
    assert checked >= 5, f"only {checked} root derivations matched; the matcher drifted"


def test_the_matcher_sees_both_spellings_and_rejects_a_wrong_count() -> None:
    good = "ROOT = Path(__file__).resolve().parents[2]\n"
    assert _root_derivations(good) == [("ROOT", 1, 2)]

    chained = "REPO = Path(__file__).resolve().parent.parent.parent\n"
    assert _root_derivations(chained) == [("REPO", 1, 2)]

    joined = 'HARNESS_ROOT = Path(__file__).resolve().parents[3] / "runs"\n'
    assert _root_derivations(joined) == [("HARNESS_ROOT", 1, 3)]

    unnamed = "elsewhere = Path(__file__).resolve().parents[9]\n"
    assert _root_derivations(unnamed) == []

    not_a_file = "ROOT = Path(other).resolve().parents[1]\n"
    assert _root_derivations(not_a_file) == []
