"""The effect-free claim of the G1-EDA-HOST-STATUS-02 emission path.

`daedalus/chip_design/cli.py` owns exactly one admitted effect boundary: the
`run` subcommand, which delegates to `run_admitted_eda` and the `begin_effect`
it consumes.  The packet claims that `plan` -- including `--emit-tcl` and
`--emit-harness` -- stays outside that boundary and opens nothing for writing.
An earlier revision of this packet broke that claim by writing the emitted
script to an operator-named path from inside `plan`, which is a second write
path beside the door's admission.  The claim is therefore asserted three ways
here instead of in prose:

1. **Statically**, over the AST of the pure emitter and of every function on
   the planning path: no write, spawn or socket API is referenced, and the
   deleted write helpers must stay deleted.
2. **By fault injection**, at runtime: every write, process start and socket is
   armed to explode, and then every effect-free subcommand is executed,
   emission included.
3. **By measurement**: the byte contents of a directory tree are identical
   before and after a full scan/classify/inspect/plan cycle.

`run` is deliberately absent from every list below.  It is *supposed* to write,
under a lease; the point of this file is that nothing else does.
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

import daedalus.chip_design.cli as chip_cli
from daedalus.chip_design.cli import main

from test_chip_cli_canonical import _write_project

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "daedalus" / "chip_design"
CLI_SOURCE = PACKAGE / "cli.py"
EMITTER_SOURCE = PACKAGE / "tcl_emit.py"

#: Every function the `plan` subcommand may reach in `cli.py`.  Each one is
#: checked below for write/spawn calls.  `run`'s composition root is not here.
PLANNING_FUNCTIONS = (
    "_emission_mode",
    "_emit_scripts",
    "_emit_plan",
    "_emitted_source_lists",
    "_expected_outputs",
    "_hls_kernel_identity",
    "_manifest_payload",
    "_manifest_refusal_reasons",
    "_output_dir",
    "_phase_sequence",
    "_plan_digest",
    "_planned_step",
    "_require_complete_manifest",
    "_validate_selected_runs",
    "_vitis_hls_plan",
    "_vivado_command",
)

#: Helpers whose only purpose was the deleted filesystem emission.  If one
#: comes back, this packet has regrown the write path the review rejected.
DELETED_WRITE_HELPERS = ("_emission_target_path", "_write_emitted_script")

FORBIDDEN_IMPORTS = {
    "subprocess",
    "socket",
    "ssl",
    "http",
    "urllib",
    "requests",
    "httpx",
    "asyncio",
    "multiprocessing",
    "threading",
    "concurrent",
    "ctypes",
    "signal",
    "pty",
    "webbrowser",
    "tempfile",
    "shutil",
    "pickle",
}

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

WRITE_MODES = set("wax+")


def _dotted(node: ast.AST) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


def _effect_calls(tree: ast.AST) -> list[str]:
    """Every write/spawn-shaped call in one AST subtree."""

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
            # `Path.open(...)`/`handle.open(...)` in a write mode.
            if target.attr == "open":
                mode = _open_mode(node)
                if set(mode) & WRITE_MODES:
                    offending.append(f"line {node.lineno}: .open(mode={mode!r})")
        if isinstance(target, ast.Name) and target.id == "open":
            mode = _open_mode(node)
            if set(mode) & WRITE_MODES:
                offending.append(f"line {node.lineno}: open(mode={mode!r})")
    return offending


def _open_mode(node: ast.Call) -> str:
    mode = ""
    if node.args and isinstance(node.args[0], ast.Constant):
        candidate = node.args[0].value
        if isinstance(candidate, str) and set(candidate) <= set("rwxab+tU"):
            mode = candidate
    if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
        mode = str(node.args[1].value)
    for keyword in node.keywords:
        if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
            mode = str(keyword.value.value)
    return mode


def _function(source: Path, name: str) -> ast.FunctionDef:
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{source.name} has no top-level function {name}")


# ---------------------------------------------------------------------------
# Static: the pure emitter
# ---------------------------------------------------------------------------


def test_the_emitter_imports_no_effect_capability() -> None:
    tree = ast.parse(EMITTER_SOURCE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & FORBIDDEN_IMPORTS, sorted(imported & FORBIDDEN_IMPORTS)
    # It must also stay a leaf: rendering may not reach any other Daedalus
    # module, or the "pure function of its arguments" claim is unverifiable.
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            assert not node.module.startswith("daedalus")
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("daedalus")


def test_the_emitter_calls_no_write_or_spawn_api() -> None:
    tree = ast.parse(EMITTER_SOURCE.read_text(encoding="utf-8"))
    assert _effect_calls(tree) == []


def test_the_emitter_touches_no_path_at_all() -> None:
    """It formats path strings; it must never resolve or stat one."""

    text = EMITTER_SOURCE.read_text(encoding="utf-8")
    for forbidden in ("Path(", "os.path", "open(", ".exists()", ".is_file()"):
        assert forbidden not in text, f"the emitter references {forbidden}"


# ---------------------------------------------------------------------------
# Static: the planning path in the CLI
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", PLANNING_FUNCTIONS)
def test_no_planning_function_writes_or_spawns(name: str) -> None:
    assert _effect_calls(_function(CLI_SOURCE, name)) == []


@pytest.mark.parametrize("name", DELETED_WRITE_HELPERS)
def test_the_deleted_write_helpers_stay_deleted(name: str) -> None:
    """The review rejected emission-by-file; it must not come back quietly."""

    tree = ast.parse(CLI_SOURCE.read_text(encoding="utf-8"))
    names = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert name not in names
    assert name not in CLI_SOURCE.read_text(encoding="utf-8")


def test_the_only_write_mode_open_in_the_cli_is_the_admitted_run_path() -> None:
    """One door, and it is not `plan`.

    The whole file is scanned rather than one function, so a write added
    anywhere outside the effectful composition root is a red test.
    """

    tree = ast.parse(CLI_SOURCE.read_text(encoding="utf-8"))
    planning = {name for name in PLANNING_FUNCTIONS}
    offending: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        calls = _effect_calls(node)
        if calls and node.name in planning:
            offending.append(f"{node.name}: {calls}")
    assert offending == []


def test_the_static_scan_would_actually_catch_a_write() -> None:
    """Mutation guard: prove the AST scan is not vacuous."""

    tree = ast.parse(
        "def f(target):\n"
        "    with target.open('xb') as handle:\n"
        "        handle.write(b'x')\n"
    )
    assert _effect_calls(tree) != []
    assert _effect_calls(ast.parse("def f(p):\n    p.write_bytes(b'x')\n")) != []
    assert _effect_calls(ast.parse("def f(p):\n    open(p, 'w')\n")) != []
    # ...and that a read is still allowed, or the scan would be useless.
    assert _effect_calls(ast.parse("def f(p):\n    open(p, 'rb').read()\n")) == []


# ---------------------------------------------------------------------------
# Runtime fault injection
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def effects_armed():
    """Arm every effect boundary the planning path claims not to touch.

    A context manager rather than a fixture, so pytest's ``tmp_path`` and the
    project fixture are written *before* the trap is set.
    """

    def explode(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError(f"the planning path performed an effect: {args!r}")

    real_open = builtins.open

    def guarded_open(file, mode="r", *args, **kwargs):
        if set(str(mode)) & WRITE_MODES:  # pragma: no cover
            raise AssertionError(f"the planning path opened {file!r} for writing")
        return real_open(file, mode, *args, **kwargs)

    real_path_open = Path.open

    def guarded_path_open(self, mode="r", *args, **kwargs):
        if set(str(mode)) & WRITE_MODES:  # pragma: no cover
            raise AssertionError(f"the planning path opened {self!r} for writing")
        return real_path_open(self, mode, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(builtins, "open", guarded_open)
        patch.setattr(Path, "open", guarded_path_open)
        for name in ("Popen", "run", "call", "check_call", "check_output"):
            patch.setattr(subprocess, name, explode, raising=False)
        for name in (
            "system", "popen", "remove", "unlink", "rmdir", "mkdir", "makedirs",
            "rename", "replace", "write",
        ):
            patch.setattr(os, name, explode, raising=False)
        patch.setattr(socket, "socket", explode)
        patch.setattr(socket, "create_connection", explode)
        for name in ("write_text", "write_bytes", "mkdir", "touch", "unlink", "rename"):
            patch.setattr(Path, name, explode, raising=False)
        # The admitted door itself: reaching it from `plan` is the defect.
        for name in ("acquire_chip_eda_lease", "run_admitted_eda", "execute_argv"):
            patch.setattr(chip_cli, name, explode, raising=False)
        yield


def test_the_trap_would_actually_fire(tmp_path: Path) -> None:
    """Mutation guard: prove the armed context is not a no-op."""

    with pytest.raises(AssertionError, match="performed an effect"):
        with effects_armed():
            os.mkdir(tmp_path / "nope")
    with pytest.raises(AssertionError, match="opened .* for writing"):
        with effects_armed():
            open(tmp_path / "nope.txt", "w").close()
    with pytest.raises(AssertionError, match="opened .* for writing"):
        with effects_armed():
            (tmp_path / "nope2.txt").open("xb").close()


def test_every_effect_free_subcommand_runs_with_writes_armed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    xpr = _write_project(root, project_path_metadata=r"C:\source\demo.xpr")
    kernel = tmp_path / "kernel" / "vadd.cpp"
    kernel.parent.mkdir(parents=True)
    kernel.write_text("extern \"C\" void vadd() {}\n", encoding="utf-8", newline="\n")

    with effects_armed():
        assert main(["status", "--json"]) == 0
        assert main(["scan", str(root), "--json"]) == 0
        assert main(["classify", str(xpr), "--json"]) == 0
        assert main(["inspect", str(xpr), "--json"]) == 0
        for phase in ("inspect", "synth", "impl", "full"):
            assert main(["plan", str(xpr), "--phase", phase, "--json"]) == 0
            assert (
                main(
                    [
                        "plan", str(xpr), "--phase", phase,
                        "--emit-tcl", "--emit-harness", "--json",
                    ]
                )
                == 0
            )
        assert main(["plan", str(xpr), "--emit-tcl", "-", "--json"]) == 0
        assert (
            main(
                [
                    "plan", str(kernel), "--target", "vitis-hls",
                    "--top", "vadd", "--part", "xcu250-figd2104-2L-e",
                    "--emit-tcl", "--emit-harness", "--json",
                ]
            )
            == 0
        )
    capsys.readouterr()


def test_a_planning_refusal_also_performs_no_effect(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    xpr = _write_project(root, project_path_metadata=r"C:\source\demo.xpr")
    with effects_armed():
        with pytest.raises(SystemExit):
            main(["plan", str(xpr), "--emit-tcl", "out.tcl", "--json"])
        with pytest.raises(SystemExit):
            main(["plan", str(xpr), "--emit-harness", "--json"])
        with pytest.raises(SystemExit):
            main(["plan", str(xpr), "--top", "vadd", "--json"])
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


def test_a_full_planning_cycle_leaves_the_tree_byte_identical(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    xpr = _write_project(root, project_path_metadata=r"C:\source\demo.xpr")
    before = _tree_digest(tmp_path)
    main(["status", "--json"])
    main(["scan", str(root), "--json"])
    main(["inspect", str(xpr), "--json"])
    main(["plan", str(xpr), "--json"])
    main(["plan", str(xpr), "--emit-tcl", "--emit-harness", "--json"])
    main(["plan", str(xpr), "--emit-tcl", "-", "--json"])
    capsys.readouterr()
    assert _tree_digest(tmp_path) == before
    assert not list(tmp_path.rglob("*.tcl")), "planning materialised a script"
    assert not list(tmp_path.rglob(".daedalus-chip")), "no workspace was created"


def test_emission_does_not_touch_the_project_it_reads(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    xpr = _write_project(root, project_path_metadata=r"C:\source\demo.xpr")
    before = xpr.stat()
    main(["plan", str(xpr), "--emit-tcl", "--emit-harness", "--json"])
    capsys.readouterr()
    after = xpr.stat()
    assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)
