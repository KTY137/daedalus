"""The isolation claim of the G1-HW-01 experiment, made falsifiable.

The packet asserts that ``daedalus/pcb_design/`` is effect-free and wired into
nothing. That is exactly the kind of claim this repository's review rules call
unverifiable when it appears only in prose, so it is asserted three ways here:

1. **Statically**, over the package's own AST: no process, socket or write API
   is referenced, and no absolute ``daedalus.*`` import exists.
2. **By fault injection**, at runtime: every process start, socket and write
   is armed to explode, and then every CLI subcommand is executed.
3. **By measurement**: the byte contents of a directory tree are identical
   before and after a full scan/inspect/plan cycle.

A fourth test guards the *wiring* claim: no other surface in the tree mentions
this package, so it cannot be reached through a product path.
"""
from __future__ import annotations

import ast
import builtins
import contextlib
import hashlib
import os
import socket
import subprocess
from pathlib import Path

import pytest

from fixtures.pcb_design import write_fixture

from daedalus.pcb_design.cli import main

PACKAGE = Path(__file__).resolve().parents[1] / "daedalus" / "pcb_design"
REPO = Path(__file__).resolve().parents[1]

MODULES = sorted(PACKAGE.glob("*.py"))

# Modules whose mere import would give this package an effect capability.
FORBIDDEN_IMPORTS = {
    "subprocess",
    "socket",
    "ssl",
    "http",
    "urllib",
    "requests",
    "httpx",
    "ftplib",
    "smtplib",
    "telnetlib",
    "asyncio",
    "multiprocessing",
    "threading",
    "concurrent",
    "ctypes",
    "signal",
    "pty",
    "webbrowser",
    "tempfile",
    "pickle",
    "pcbnew",
    "kipy",
}

# Method names that mean an effect no matter what they are called on.
FORBIDDEN_ATTRIBUTES = {
    "system",
    "popen",
    "spawnl",
    "spawnv",
    "execv",
    "execvp",
    "fork",
    "unlink",
    "rmdir",
    "removedirs",
    "makedirs",
    "mkdir",
    "renames",
    "chmod",
    "chown",
    "touch",
    "write_text",
    "write_bytes",
    "writelines",
    "rmtree",
    "copyfile",
    "copytree",
    "symlink_to",
    "hardlink_to",
}

# Names that are ambiguous on their own -- ``str.replace`` and ``list.remove``
# are not effects -- so they are only forbidden on a known effect receiver. A
# coarser check would have to be silenced with an exemption, and an exemption
# is exactly how a guard stops guarding.
FORBIDDEN_QUALIFIED = {
    "os.remove",
    "os.rename",
    "os.replace",
    "os.truncate",
    "os.link",
    "os.symlink",
    "os.utime",
    "os.write",
    "shutil.move",
    "shutil.copy",
    "shutil.copy2",
    "Path.replace",
    "Path.rename",
}


def _dotted(node: ast.AST) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


def test_the_package_has_modules_to_check():
    assert len(MODULES) >= 6, "the static checks below must not silently pass on nothing"


@pytest.mark.parametrize("module", MODULES, ids=lambda p: p.name)
def test_no_module_imports_an_effect_capability(module):
    tree = ast.parse(module.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    offending = sorted(imported & FORBIDDEN_IMPORTS)
    assert not offending, f"{module.name} imports {offending}"


@pytest.mark.parametrize("module", MODULES, ids=lambda p: p.name)
def test_no_module_calls_a_write_or_spawn_api(module):
    tree = ast.parse(module.read_text(encoding="utf-8"))
    offending: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if isinstance(target, ast.Attribute):
            if target.attr in FORBIDDEN_ATTRIBUTES:
                offending.append(f"line {node.lineno}: .{target.attr}()")
            dotted = _dotted(target)
            if dotted in FORBIDDEN_QUALIFIED:
                offending.append(f"line {node.lineno}: {dotted}()")
        if isinstance(target, ast.Name) and target.id == "open":
            mode = ""
            if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                mode = str(node.args[1].value)
            for keyword in node.keywords:
                if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
                    mode = str(keyword.value.value)
            if set(mode) & set("wax+"):
                offending.append(f"line {node.lineno}: open(mode={mode!r})")
    assert not offending, f"{module.name}: {offending}"


@pytest.mark.parametrize("module", MODULES, ids=lambda p: p.name)
def test_the_package_imports_nothing_else_from_daedalus(module):
    """No product wiring in either direction: the package is a leaf."""

    tree = ast.parse(module.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            assert not node.module.startswith("daedalus"), (
                f"{module.name} reaches into {node.module}; the experiment must "
                "stay a leaf package"
            )
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("daedalus"), (
                    f"{module.name} imports {alias.name}"
                )


def test_no_product_surface_references_this_package():
    """The experiment must be unreachable from any wired surface."""

    searched = [
        *(REPO / "daedalus").rglob("*.py"),
        *(REPO / "tools").rglob("*.py"),
        *(REPO / "configs").rglob("*.json"),
        REPO / "pyproject.toml",
    ]
    allowed_prefixes = (
        (REPO / "daedalus" / "pcb_design").as_posix(),
    )
    offending = []
    for path in searched:
        if not path.is_file():
            continue
        if path.as_posix().startswith(allowed_prefixes):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:  # pragma: no cover
            continue
        if "pcb_design" in text:
            offending.append(path.relative_to(REPO).as_posix())
    assert not offending, (
        "these wired surfaces reference the experiment: " + ", ".join(offending)
    )


def test_the_package_declares_no_console_script():
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert "daedalus-pcb" not in text
    assert "pcb_design" not in text


# ---------------------------------------------------------------------------
# Runtime fault injection
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def effects_armed():
    """Arm every effect boundary this package claims not to touch.

    This is a context manager rather than a fixture on purpose: pytest's own
    ``tmp_path`` and the fixture writer must run *before* the trap is set, or
    the test harness trips its own wire.
    """

    def explode(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError(f"the package performed an effect: {args!r}")

    real_open = builtins.open

    def guarded_open(file, mode="r", *args, **kwargs):
        if set(str(mode)) & set("wax+"):  # pragma: no cover
            raise AssertionError(f"the package opened {file!r} for writing")
        return real_open(file, mode, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(builtins, "open", guarded_open)
        for name in ("Popen", "run", "call", "check_call", "check_output"):
            patch.setattr(subprocess, name, explode, raising=False)
        for name in (
            "system", "popen", "remove", "unlink", "rmdir", "mkdir", "makedirs",
            "rename", "replace",
        ):
            patch.setattr(os, name, explode, raising=False)
        patch.setattr(socket, "socket", explode)
        patch.setattr(socket, "create_connection", explode)
        for name in ("write_text", "write_bytes", "mkdir", "touch", "unlink", "rename"):
            patch.setattr(Path, name, explode, raising=False)
        yield


def test_every_subcommand_runs_with_all_effect_boundaries_armed(tmp_path, capsys):
    project = write_fixture(tmp_path / "lane6")
    with effects_armed():
        assert main(["status", "--json"]) == 0
        assert main(["scan", str(tmp_path), "--json"]) == 0
        assert main(["inspect", str(project["board"]), "--json"]) == 0
        assert main(["inspect", str(project["schematic"]), "--json"]) == 0
        assert main(["plan", "--json"]) == 1
    assert capsys.readouterr().out.count("\n") == 5


def test_the_trap_would_actually_fire(tmp_path):
    """Mutation guard: prove the armed context is not a no-op."""

    with pytest.raises(AssertionError, match="performed an effect"):
        with effects_armed():
            os.mkdir(tmp_path / "nope")
    with pytest.raises(AssertionError, match="opened .* for writing"):
        with effects_armed():
            open(tmp_path / "nope.txt", "w").close()


def test_a_refusal_path_also_performs_no_effect(tmp_path, capsys):
    target = tmp_path / "broken.kicad_pcb"
    target.write_bytes(b"(kicad_pcb")
    with effects_armed():
        assert main(["inspect", str(target), "--json"]) == 3
    capsys.readouterr()


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"/" if path.is_dir() else path.read_bytes())
    return digest.hexdigest()


def test_a_full_cycle_leaves_the_tree_byte_identical(tmp_path, capsys):
    project = write_fixture(tmp_path / "lane6")
    before = _tree_digest(tmp_path)
    main(["scan", str(tmp_path), "--json"])
    main(["inspect", str(project["board"]), "--json"])
    main(["inspect", str(project["schematic"]), "--json"])
    main(["plan", "--json"])
    main(["status", "--json"])
    capsys.readouterr()
    assert _tree_digest(tmp_path) == before
    assert not list(tmp_path.rglob(".daedalus*")), "no state directory was created"


def test_inspection_does_not_touch_the_file_it_reads(tmp_path, capsys):
    project = write_fixture(tmp_path / "lane6")
    board = project["board"]
    before = board.stat()
    main(["inspect", str(board), "--json"])
    capsys.readouterr()
    after = board.stat()
    assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)
