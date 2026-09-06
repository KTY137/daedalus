"""G1-EDA-HOST-STATUS-02: deterministic Vivado/Vitis-HLS Tcl emission.

Every test here is effect-free with respect to vendor tools.  No test needs
AMD Vivado, Vitis HLS, XSCT or Quartus.  Two tests start a plain ``tclsh`` and
skip when no Tcl shell is installed; one starts this CLI itself to measure a
real stdout redirect, because an in-process capture cannot see the platform
text layer.  A green harness result proves the emitted text is parseable Tcl
whose command words resolve; it is never evidence that a vendor tool accepts
the script.

The emission contract these tests pin is *inline*: ``plan`` writes no file.
An earlier revision wrote the emitted script to an operator-named path, which
put a write outside this CLI's one admitted effect anchor; see
``tests/test_chip_design_isolation.py`` for the guard that keeps it out.
"""
from __future__ import annotations

import base64
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import daedalus.chip_design.cli as chip_cli
from daedalus.chip_design.tcl_emit import (
    PARSE_HARNESS_TARGET,
    TCL_BUILTINS,
    TCL_EMIT_SCHEMA,
    TCL_SYNTAX_CHECKER,
    VITIS_HLS_COMMANDS,
    VITIS_HLS_TARGET,
    VIVADO_COMMANDS,
    VIVADO_SCOPES,
    VIVADO_TARGET,
    TclEmitError,
    emitted_command_words,
    emitted_defined_procs,
    expected_emitted_outputs,
    render_parse_harness,
    render_vitis_hls_flow,
    render_vivado_project_flow,
    tcl_completeness,
    tcl_info_complete,
)
from daedalus.chip_design.toolchains import all_tool_status, tool_status

from test_chip_cli_canonical import _write_project


# ---------------------------------------------------------------------------
# Ground truth for the pure-Python Tcl completeness scan.
#
# Every expected value below was measured with the Tcl shell installed on the
# development host (``tclsh`` 8.6.12 from Git for Windows) by feeding the exact
# bytes to ``info complete``.  The table is the contract: if the scanner ever
# disagrees with real Tcl on one of these, the scanner is wrong.
# ---------------------------------------------------------------------------
BS = "\\"
TCL_COMPLETE_CORPUS: tuple[tuple[str, str, bool], ...] = (
    ("simple", "set a 1\n", True),
    ("open_brace", "if {1} {\n", False),
    ("balanced", "if {1} {\n  set a 2\n}\n", True),
    ("open_bracket", "set a [expr 1+1\n", False),
    ("closed_bracket", "set a [expr {1+1}]\n", True),
    ("open_quote", 'puts "hello\n', False),
    ("closed_quote", 'puts "hello"\n', True),
    ("comment_open_brace", "# {\n", True),
    ("comment_open_brace_then_cmd", "# {\nset a 1\n", True),
    ("midword_brace", "set a b{\n", True),
    ("stray_close_brace", "set a }\n", True),
    ("trailing_backslash", "set a " + BS, True),
    ("backslash_newline", "set a " + BS + "\n1\n", True),
    ("brace_in_quote", 'puts "{"\n', True),
    ("bracket_in_quote", 'puts "[expr 1\n', False),
    ("bracket_in_quote_closed", 'puts "[expr 1]"\n', True),
    ("quote_in_brace", 'set a {"}\n', True),
    ("escaped_brace", "set a " + BS + "{\n", True),
    ("escaped_brace_in_brace", "set a {" + BS + "}}\n", True),
    ("hash_not_command_pos", "set a # {\n", False),
    ("comment_in_bracket", "set a [# {\n", False),
    ("semicolon_then_hash", "set a 1; # {\n", True),
    ("nested_braces", "proc p {} {\n  if {1} {\n  }\n}\n", True),
    ("empty", "", True),
    ("only_newlines", "\n\n", True),
    ("brace_after_word_chars", "puts a{b}\n", True),
    ("unbalanced_in_brace_comment", "proc p {} {\n# }\n", True),
    ("backslash_before_quote", 'puts "a' + BS + '"b"\n', True),
    ("open_bracket_in_brace", "set a {[}\n", True),
    ("close_bracket_toplevel", "set a ]\n", True),
    ("quote_midword", 'set a b"c\n', True),
    ("brace_in_comment_bracket", "# [\n", True),
    ("newline_in_quote", 'puts "a\nb"\n', True),
    ("double_backslash_eof", "set a " + BS + BS, True),
    ("bracket_then_brace", "set a [list {\n", False),
)

VIVADO_KWARGS = dict(
    project_file="C:/pinned/demo.xpr",
    project_root="C:/pinned",
    output_dir="C:/pinned/.daedalus-chip/plans/emitted/full",
    part="xc7a35ticsg324-1L",
    board_part="",
    top="top",
    synth_run="synth_1",
    impl_run="impl_1",
    jobs=1,
    design_sources=["demo.srcs/sources_1/new/top.sv"],
    constraint_sources=["demo.srcs/constrs_1/new/pins.xdc"],
    project_sha256="1" * 64,
    manifest_sha256="2" * 64,
    source_identity_sha256="3" * 64,
    plan_sha256="4" * 64,
    trusted_tcl_sha256="5" * 64,
)

HLS_KWARGS = dict(
    kernel_file="C:/pinned/kernel/vadd.cpp",
    kernel_sha256="6" * 64,
    top="vadd",
    part="xcu250-figd2104-2L-e",
    solution="solution1",
    clock_period="10",
    project_dir="C:/pinned/.daedalus-chip/plans/hls/vadd/hls_project",
    output_dir="C:/pinned/.daedalus-chip/plans/hls/vadd/reports",
    plan_sha256="7" * 64,
)

# Canonical identity of every emitted artifact, measured once and pinned so a
# rendering change cannot land silently.  (sha256, byte_length, line_count)
VIVADO_PINS: dict[str, tuple[str, int, int]] = {
    "inspect": ("f3d74f5d4e156c7fbe39f92c7fcba7ba30068ffa056a2385923342ec0e1afbcd", 3935, 102),
    "synth": ("8a2515620bcdd13ec05df2806c14133c97a013e90f4b9b8e3dcb120d5a1fb995", 4652, 119),
    "impl": ("a21d01e02b37962cb4ce87e3c08e110e9074d723f53f6e8387a8ed1e99280cc0", 5599, 141),
    "full": ("99e3fc661fcd90b4f51578af81078f84ec8b149ae025333e291673c19305d964", 5599, 141),
}
HLS_PIN = ("80ef3c3ceae3247cb861f07a3b42a2c168fbb5ceedfeb457735d4118f41cd4ed", 2835, 72)
HARNESS_PIN = ("6c3ea9ac5b99166f05049473d195251e3e61015fa53cbeb24ce8f73a1956d222", 11781, 238)

KERNEL_SOURCE = (
    "// Trivial Vitis HLS kernel fixture; no vendor header is required to\n"
    "// emit or review a csynth script for it.\n"
    "extern \"C\" void vadd(const int *a, const int *b, int *c, int n) {\n"
    "  for (int i = 0; i < n; ++i) {\n"
    "    c[i] = a[i] + b[i];\n"
    "  }\n"
    "}\n"
)


def _write_kernel(root: Path) -> Path:
    kernel = root / "kernel" / "vadd.cpp"
    kernel.parent.mkdir(parents=True, exist_ok=True)
    kernel.write_text(KERNEL_SOURCE, encoding="utf-8", newline="\n")
    return kernel


def _forbid_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("effect-free emission path reached admission or execution")

    monkeypatch.setattr(chip_cli, "acquire_chip_eda_lease", forbidden)
    monkeypatch.setattr(chip_cli, "run_admitted_eda", forbidden)
    monkeypatch.setattr(chip_cli, "execute_argv", forbidden)


def _json_stdout(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    captured = capsys.readouterr()
    assert captured.err == ""
    return json.loads(captured.out)


# ---------------------------------------------------------------------------
# Tcl completeness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,source,expected", TCL_COMPLETE_CORPUS)
def test_completeness_matches_measured_tclsh(name: str, source: str, expected: bool) -> None:
    assert tcl_info_complete(source) is expected, name


def test_completeness_names_the_open_construct() -> None:
    result = tcl_completeness("set a {1\n")
    assert result.complete is False
    assert result.open_construct == "brace"
    assert result.open_offset == 6
    payload = result.to_dict()
    assert payload["checker"] == TCL_SYNTAX_CHECKER
    assert payload["executed"] is False
    assert payload["vendor_acceptance_claimed"] is False


def test_completeness_refuses_a_non_string() -> None:
    with pytest.raises(TclEmitError):
        tcl_info_complete(b"set a 1\n")  # type: ignore[arg-type]


@pytest.mark.skipif(shutil.which("tclsh") is None, reason="no Tcl shell on this host")
def test_completeness_agrees_with_the_installed_tclsh(tmp_path: Path) -> None:
    """Re-derive the pinned corpus from whatever tclsh this host actually has."""

    probe = tmp_path / "probe.tcl"
    probe.write_text(
        "set channel [open [lindex $argv 0] r]\n"
        "fconfigure $channel -translation binary\n"
        "set body [read $channel]\n"
        "close $channel\n"
        "puts [info complete $body]\n",
        encoding="utf-8",
        newline="\n",
    )
    for index, (name, source, _expected) in enumerate(TCL_COMPLETE_CORPUS):
        case = tmp_path / f"case_{index}.txt"
        case.write_bytes(source.encode("utf-8"))
        result = subprocess.run(
            ["tclsh", str(probe), str(case)],
            capture_output=True,
            text=True,
            check=True,
        )
        measured = result.stdout.strip() == "1"
        assert measured is tcl_info_complete(source), name


# ---------------------------------------------------------------------------
# Deterministic rendering
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scope", VIVADO_SCOPES)
def test_vivado_script_identity_is_pinned(scope: str) -> None:
    script = render_vivado_project_flow(scope=scope, **VIVADO_KWARGS)
    sha256, byte_length, line_count = VIVADO_PINS[scope]
    assert (script.sha256, script.byte_length, script.line_count) == (
        sha256,
        byte_length,
        line_count,
    )
    assert script.target == VIVADO_TARGET
    assert script.scope == scope
    assert script.syntax_check.complete is True


def test_vitis_hls_script_identity_is_pinned() -> None:
    script = render_vitis_hls_flow(**HLS_KWARGS)
    assert (script.sha256, script.byte_length, script.line_count) == HLS_PIN
    assert script.target == VITIS_HLS_TARGET
    assert script.scope == "csynth"
    assert script.syntax_check.complete is True


def test_parse_harness_identity_is_pinned() -> None:
    script = render_vivado_project_flow(scope="full", **VIVADO_KWARGS)
    harness = render_parse_harness(script)
    assert (harness.sha256, harness.byte_length, harness.line_count) == HARNESS_PIN
    assert harness.target == PARSE_HARNESS_TARGET
    assert harness.syntax_check.complete is True
    assert script.sha256 in harness.text
    # The subject travels inside the harness, so the harness reads no file and
    # cannot be aimed at bytes the emitter never saw.
    assert base64.b64encode(script.data).decode("ascii")[:76] in harness.text
    assert "open $daedalus_script" not in harness.text
    assert "daedalus_real_open $daedalus_script" not in harness.text


def test_rendering_is_byte_stable_across_calls() -> None:
    first = render_vivado_project_flow(scope="full", **VIVADO_KWARGS)
    second = render_vivado_project_flow(scope="full", **VIVADO_KWARGS)
    assert first.data == second.data
    hls_first = render_vitis_hls_flow(**HLS_KWARGS)
    hls_second = render_vitis_hls_flow(**HLS_KWARGS)
    assert hls_first.data == hls_second.data
    assert first.text.endswith("\n") and hls_first.text.endswith("\n")
    assert "\r" not in first.text and "\r" not in hls_first.text


@pytest.mark.parametrize("scope", VIVADO_SCOPES)
def test_vivado_script_binds_every_inspected_identity(scope: str) -> None:
    script = render_vivado_project_flow(scope=scope, **VIVADO_KWARGS)
    for name in (
        "project_sha256",
        "manifest_sha256",
        "source_identity_sha256",
        "plan_sha256",
        "trusted_tcl_sha256",
    ):
        assert f"#   {name}:" in script.text
    for digest in ("1" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64):
        assert digest in script.text
    assert "xc7a35ticsg324-1L" in script.text
    assert "demo.srcs/sources_1/new/top.sv" in script.text
    assert "demo.srcs/constrs_1/new/pins.xdc" in script.text
    assert dict(script.bound_identities)["plan_sha256"] == "4" * 64


def test_scope_narrows_the_emitted_flow() -> None:
    inspect = render_vivado_project_flow(scope="inspect", **VIVADO_KWARGS).text
    synth = render_vivado_project_flow(scope="synth", **VIVADO_KWARGS).text
    full = render_vivado_project_flow(scope="full", **VIVADO_KWARGS).text
    assert "launch_runs" not in inspect
    assert "launch_runs $daedalus_synth_run" in synth
    assert "write_bitstream" not in synth
    assert "write_bitstream -force" in full
    assert "report_route_status" in full
    assert expected_emitted_outputs("inspect") == ("inspect_summary.txt",)
    assert "design.bit" in expected_emitted_outputs("full")
    assert "design.bit" not in expected_emitted_outputs("synth")


@pytest.mark.parametrize(
    "script_factory,declared",
    (
        (lambda: render_vivado_project_flow(scope="full", **VIVADO_KWARGS), VIVADO_COMMANDS),
        (lambda: render_vitis_hls_flow(**HLS_KWARGS), VITIS_HLS_COMMANDS),
    ),
)
def test_emitted_scripts_use_only_declared_commands(script_factory, declared) -> None:
    script = script_factory()
    allowed = set(declared) | TCL_BUILTINS | set(emitted_defined_procs(script.text))
    undeclared = sorted(set(emitted_command_words(script.text)) - allowed)
    assert undeclared == []
    missing = sorted(name for name in declared if name not in script.text)
    assert missing == [], "a declared vendor command is never emitted"
    assert set(script.commands) == set(declared)


def test_declaring_no_new_authority() -> None:
    script = render_vivado_project_flow(scope="full", **VIVADO_KWARGS)
    payload = script.to_dict()
    assert payload["schema"] == TCL_EMIT_SCHEMA
    assert payload["syntax_check"]["executed"] is False
    assert payload["syntax_check"]["vendor_acceptance_claimed"] is False
    assert "Daedalus emitted this text and did not run it" in script.text
    assert "neither a build result nor a promotion" in script.text


# ---------------------------------------------------------------------------
# Rendering refusals
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "override",
    (
        {"top": "top}\nexec evil"},
        {"top": "top; exec evil"},
        {"part": "xc7$evil"},
        {"project_file": "C:/pinned/[exec evil].xpr"},
        {"project_root": "C:/pin{ned"},
        {"output_dir": 'C:/pin"ned'},
        {"synth_run": "synth_1 ; exec evil"},
        {"impl_run": "impl_1]"},
        {"board_part": "board part with spaces"},
        {"jobs": 0},
        {"jobs": 65},
        {"jobs": True},
        {"design_sources": []},
        {"design_sources": ["../escape/top.sv"]},
        {"design_sources": ["/absolute/top.sv"]},
        {"design_sources": ["a.sv", "a.sv"]},
        {"project_sha256": "not-a-digest"},
        {"plan_sha256": "A" * 64},
    ),
)
def test_vivado_rendering_refuses_unsafe_values(override: dict) -> None:
    kwargs = {**VIVADO_KWARGS, **override}
    with pytest.raises(TclEmitError):
        render_vivado_project_flow(scope="full", **kwargs)


def test_vivado_rendering_refuses_an_unknown_scope() -> None:
    with pytest.raises(TclEmitError):
        render_vivado_project_flow(scope="bitstream", **VIVADO_KWARGS)


@pytest.mark.parametrize(
    "override",
    (
        {"kernel_file": "C:/pinned/kernel/vadd.sv"},
        {"kernel_file": "C:/pinned/kernel/vadd"},
        {"top": "1vadd"},
        {"clock_period": "10ns"},
        {"clock_period": "-1"},
        {"solution": "solution 1"},
        {"kernel_sha256": "6" * 63},
    ),
)
def test_vitis_hls_rendering_refuses_unsafe_values(override: dict) -> None:
    with pytest.raises(TclEmitError):
        render_vitis_hls_flow(**{**HLS_KWARGS, **override})


def test_parse_harness_refuses_to_wrap_itself() -> None:
    script = render_vivado_project_flow(scope="full", **VIVADO_KWARGS)
    harness = render_parse_harness(script)
    with pytest.raises(TclEmitError):
        render_parse_harness(harness)


# ---------------------------------------------------------------------------
# Contained tclsh dry parse (skipped without a Tcl shell; never needs Vivado)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("tclsh") is None, reason="no Tcl shell on this host")
@pytest.mark.parametrize(
    "script_factory",
    (
        lambda: render_vivado_project_flow(scope="full", **VIVADO_KWARGS),
        lambda: render_vitis_hls_flow(**HLS_KWARGS),
    ),
)
def test_parse_harness_runs_green_under_tclsh(tmp_path: Path, script_factory) -> None:
    script = script_factory()
    harness = render_parse_harness(script)
    harness_path = tmp_path / "emitted.harness.tcl"
    harness_path.write_bytes(harness.data)
    before = sorted(item.name for item in tmp_path.iterdir())
    result = subprocess.run(
        ["tclsh", str(harness_path)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    rows = dict(
        line.split(" ", 1)[1].split("=", 1)
        for line in result.stdout.splitlines()
        if line.startswith("DAEDALUS_TCL_PARSE ")
    )
    assert rows["complete"] == "1"
    assert rows["tcl_error"] == ""
    assert rows["intercepted_exit"] == "0"
    assert int(rows["stub_calls"]) > 0
    assert rows["vendor_acceptance_claimed"] == "0"
    assert rows["sha256_expected"] == script.sha256
    # base64 round-trip: tclsh decoded exactly the bytes the emitter produced.
    assert int(rows["embedded_bytes"]) == script.byte_length
    # The harness stubs every effectful surface, so the dry parse must not have
    # created the project, output or report directories the script names.
    assert sorted(item.name for item in tmp_path.iterdir()) == before


# ---------------------------------------------------------------------------
# CLI: status
# ---------------------------------------------------------------------------


def test_status_reports_the_vitis_family_honestly() -> None:
    rows = {row["id"]: row for row in all_tool_status()}
    for tool_id, command in (
        ("vitis", "vitis"),
        ("vitis_hls", "vitis_hls"),
        ("vpp", "v++"),
        ("xsct", "xsct"),
    ):
        row = rows[tool_id]
        assert row["command"] == command
        assert row["proprietary"] is True
        # Discovery never runs a probe, so an absent tool has no invented
        # version, path or return code.
        assert row["probe_status"] == "not_run"
        assert row["version"] == ""
        if not row["available"]:
            assert row["command_path"] == ""
            assert row["last_error"] == f"{command} not found"


def test_vitis_hls_discovery_honours_an_explicit_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launcher = tmp_path / "vitis_hls.bat"
    launcher.write_text("@echo off\n", encoding="utf-8")
    monkeypatch.setenv("DAEDALUS_VITIS_HLS_COMMAND", str(launcher))
    row = tool_status("vitis_hls")
    assert row["available"] is True
    assert Path(str(row["command_path"])) == launcher.resolve()
    assert row["probe_status"] == "not_run"


# ---------------------------------------------------------------------------
# CLI: plan --emit-tcl for the Vivado target
# ---------------------------------------------------------------------------


def test_plan_without_emission_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _forbid_effects(monkeypatch)
    root = tmp_path / "project"
    root.mkdir()
    xpr = _write_project(root, project_path_metadata=r"C:\source\demo.xpr")
    assert chip_cli.main(["plan", str(xpr), "--phase", "synth", "--json"]) == 0
    payload = _json_stdout(capsys)
    assert payload["schema"] == chip_cli.PLAN_SCHEMA
    assert not [key for key in payload if key.startswith("emitted_")]

def test_plan_emit_tcl_puts_a_bound_script_in_the_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _forbid_effects(monkeypatch)
    root = tmp_path / "project"
    root.mkdir()
    xpr = _write_project(root, project_path_metadata=r"C:\source\demo.xpr")
    assert (
        chip_cli.main(
            [
                "plan",
                str(xpr),
                "--phase",
                "full",
                "--emit-tcl",
                "--emit-harness",
                "--json",
            ]
        )
        == 0
    )
    payload = _json_stdout(capsys)
    emitted = payload["emitted_tcl"]
    harness = payload["emitted_harness"]
    assert emitted["schema"] == TCL_EMIT_SCHEMA
    assert emitted["target"] == VIVADO_TARGET
    assert emitted["scope"] == "full"
    assert emitted["syntax_check"]["complete"] is True
    assert emitted["syntax_check"]["vendor_acceptance_claimed"] is False
    assert emitted["syntax_check"]["executed"] is False
    assert "design.bit" in emitted["expected_outputs"]
    assert harness["subject_sha256"] == emitted["sha256"]
    assert harness["runner"] == "tclsh"
    # No path and no write: the script itself is the payload row.
    assert "path" not in emitted and "written" not in emitted
    assert "path" not in harness and "written" not in harness

    text = emitted["text"]
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == emitted["sha256"]
    assert len(text.encode("utf-8")) == emitted["byte_length"]
    assert emitted["bound_identities"]["manifest_sha256"] == payload["manifest_sha256"]
    assert (
        emitted["bound_identities"]["source_identity_sha256"]
        == payload["source_identity_sha256"]
    )
    assert emitted["bound_identities"]["project_sha256"] in text
    assert emitted["bound_identities"]["plan_sha256"] in text
    assert "xc7a35ticsg324-1L" in text
    assert "demo.srcs/sources_1/new/top.sv" in text
    assert "demo.srcs/constrs_1/new/pins.xdc" in text
    assert tcl_info_complete(text) is True
    assert tcl_info_complete(harness["text"]) is True
    # Emission must leave the inspected project and the whole tree alone.
    assert sorted(item.name for item in root.iterdir()) == ["demo.srcs", "demo.xpr"]
    assert sorted(item.name for item in tmp_path.iterdir()) == ["project"]


def test_plan_emit_tcl_is_deterministic_across_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _forbid_effects(monkeypatch)
    root = tmp_path / "project"
    root.mkdir()
    xpr = _write_project(root, project_path_metadata=r"C:\source\demo.xpr")
    argv = ["plan", str(xpr), "--emit-tcl", "--emit-harness", "--json"]
    assert chip_cli.main(argv) == 0
    first = _json_stdout(capsys)
    assert chip_cli.main(argv) == 0
    assert _json_stdout(capsys) == first


def test_plan_emit_tcl_dash_streams_only_the_script_to_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--emit-tcl -` exists so an operator can `> file` without a CLI write."""

    _forbid_effects(monkeypatch)
    root = tmp_path / "project"
    root.mkdir()
    xpr = _write_project(root, project_path_metadata=r"C:\source\demo.xpr")
    assert chip_cli.main(["plan", str(xpr), "--emit-tcl", "-", "--json"]) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.err)
    assert captured.out == payload["emitted_tcl"]["text"]
    assert (
        hashlib.sha256(captured.out.encode("utf-8")).hexdigest()
        == payload["emitted_tcl"]["sha256"]
    )
    assert tcl_info_complete(captured.out) is True
    assert sorted(item.name for item in tmp_path.iterdir()) == ["project"]


def test_a_redirected_script_still_hashes_to_its_recorded_digest(
    tmp_path: Path,
) -> None:
    """The whole point of `-` is `> file`, so measure a real redirect.

    An in-process capture cannot see the platform text layer: on Windows a
    text-mode stdout turns every LF into CRLF, and the saved script then no
    longer hashes to the sha256 its own payload records. This test spawns the
    CLI and redirects for real. It needs no vendor tool.
    """

    root = tmp_path / "project"
    root.mkdir()
    xpr = _write_project(root, project_path_metadata=r"C:\source\demo.xpr")
    saved = tmp_path / "flow.tcl"
    plan = tmp_path / "plan.json"
    with saved.open("wb") as out, plan.open("wb") as err:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "daedalus.chip_design",
                "plan",
                str(xpr),
                "--emit-tcl",
                "-",
                "--json",
            ],
            stdout=out,
            stderr=err,
        )
    assert result.returncode == 0, plan.read_text(encoding="utf-8")
    payload = json.loads(plan.read_text(encoding="utf-8"))
    data = saved.read_bytes()
    assert hashlib.sha256(data).hexdigest() == payload["emitted_tcl"]["sha256"]
    assert len(data) == payload["emitted_tcl"]["byte_length"]
    assert b"\r" not in data, "the text layer translated the emitted script"
    assert data.decode("utf-8") == payload["emitted_tcl"]["text"]


def test_plan_emit_harness_dash_streams_the_harness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _forbid_effects(monkeypatch)
    root = tmp_path / "project"
    root.mkdir()
    xpr = _write_project(root, project_path_metadata=r"C:\source\demo.xpr")
    assert (
        chip_cli.main(
            ["plan", str(xpr), "--emit-tcl", "--emit-harness", "-", "--json"]
        )
        == 0
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.err)
    assert captured.out == payload["emitted_harness"]["text"]


def test_plan_refuses_two_streams_on_one_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _forbid_effects(monkeypatch)
    root = tmp_path / "project"
    root.mkdir()
    xpr = _write_project(root, project_path_metadata=r"C:\source\demo.xpr")
    with pytest.raises(SystemExit):
        chip_cli.main(
            ["plan", str(xpr), "--emit-tcl", "-", "--emit-harness", "-", "--json"]
        )
    assert "only one of --emit-tcl and --emit-harness" in capsys.readouterr().err


@pytest.mark.parametrize("value", ("flow.tcl", "out/flow.tcl", "..", "/dev/null"))
def test_plan_emit_tcl_refuses_an_output_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    value: str,
) -> None:
    """Planning writes no file, so a path argument is a refusal, not a target."""

    _forbid_effects(monkeypatch)
    root = tmp_path / "project"
    root.mkdir()
    xpr = _write_project(root, project_path_metadata=r"C:\source\demo.xpr")
    with pytest.raises(SystemExit):
        chip_cli.main(["plan", str(xpr), "--emit-tcl", value, "--json"])
    assert "does not take an output path" in capsys.readouterr().err
    assert not list(tmp_path.rglob("*.tcl"))


def test_plan_emit_harness_requires_emit_tcl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _forbid_effects(monkeypatch)
    root = tmp_path / "project"
    root.mkdir()
    xpr = _write_project(root, project_path_metadata=r"C:\source\demo.xpr")
    with pytest.raises(SystemExit):
        chip_cli.main(["plan", str(xpr), "--emit-harness", "--json"])
    assert "--emit-harness requires --emit-tcl" in capsys.readouterr().err


def test_plan_refuses_hls_flags_on_the_vivado_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_effects(monkeypatch)
    root = tmp_path / "project"
    root.mkdir()
    xpr = _write_project(root, project_path_metadata=r"C:\source\demo.xpr")
    with pytest.raises(SystemExit):
        chip_cli.main(["plan", str(xpr), "--top", "vadd", "--json"])


# ---------------------------------------------------------------------------
# CLI: plan --target vitis-hls
# ---------------------------------------------------------------------------


def test_plan_vitis_hls_emits_a_bound_csynth_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _forbid_effects(monkeypatch)
    kernel = _write_kernel(tmp_path)
    assert (
        chip_cli.main(
            [
                "plan",
                str(kernel),
                "--target",
                VITIS_HLS_TARGET,
                "--top",
                "vadd",
                "--part",
                "xcu250-figd2104-2L-e",
                "--emit-tcl",
                "--json",
            ]
        )
        == 0
    )
    payload = _json_stdout(capsys)
    assert payload["schema"] == chip_cli.HLS_PLAN_SCHEMA
    assert payload["target"] == VITIS_HLS_TARGET
    assert payload["scope"] == "csynth"
    assert payload["top"] == "vadd"
    assert payload["promotion"] is False
    assert payload["security_boundary_claimed"] is False
    # No admitted Vitis HLS runner exists; the plan says so instead of implying
    # that `daedalus-chip run` could execute it, and the invocation stays a
    # template because no file was written for an argv to point at.
    assert payload["live_runner_available"] is False
    assert payload["invocation_template"] == [
        "vitis_hls",
        "-f",
        "<script the operator saved>",
    ]
    assert "argv" not in payload
    emitted = payload["emitted_tcl"]
    assert emitted["target"] == VITIS_HLS_TARGET
    assert "path" not in emitted and "written" not in emitted
    assert emitted["sha256"] == payload["emitted_tcl_sha256"]
    text = emitted["text"]
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == emitted["sha256"]
    assert payload["kernel_sha256"] in text
    assert emitted["bound_identities"]["plan_sha256"] in text
    assert "csynth_design" in text
    assert "xcu250-figd2104-2L-e" in text
    assert tcl_info_complete(text) is True
    # The kernel and the tree around it are untouched.
    assert kernel.read_text(encoding="utf-8") == KERNEL_SOURCE
    assert sorted(item.name for item in tmp_path.iterdir()) == ["kernel"]


def test_plan_vitis_hls_is_deterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _forbid_effects(monkeypatch)
    kernel = _write_kernel(tmp_path)
    argv = [
        "plan",
        str(kernel),
        "--target",
        VITIS_HLS_TARGET,
        "--top",
        "vadd",
        "--part",
        "xcu250-figd2104-2L-e",
        "--json",
    ]
    assert chip_cli.main(argv) == 0
    first = _json_stdout(capsys)
    assert chip_cli.main(argv) == 0
    second = _json_stdout(capsys)
    assert first == second
    assert "emitted_tcl" not in first


@pytest.mark.parametrize(
    "extra",
    (
        [],
        ["--top", "vadd"],
        ["--part", "xcu250-figd2104-2L-e"],
        ["--top", "vadd", "--part", "xcu250-figd2104-2L-e", "--phase", "synth"],
        ["--top", "vadd", "--part", "xcu250-figd2104-2L-e", "--jobs", "4"],
        ["--top", "vadd", "--part", "xcu250-figd2104-2L-e", "--vivado", "vivado"],
        ["--top", "1vadd", "--part", "xcu250-figd2104-2L-e"],
    ),
)
def test_plan_vitis_hls_refuses_incomplete_or_foreign_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: list[str]
) -> None:
    _forbid_effects(monkeypatch)
    kernel = _write_kernel(tmp_path)
    with pytest.raises(SystemExit):
        chip_cli.main(
            ["plan", str(kernel), "--target", VITIS_HLS_TARGET, *extra, "--json"]
        )


def test_plan_vitis_hls_refuses_a_non_cpp_kernel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_effects(monkeypatch)
    kernel = tmp_path / "vadd.sv"
    kernel.write_text("module vadd; endmodule\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        chip_cli.main(
            [
                "plan",
                str(kernel),
                "--target",
                VITIS_HLS_TARGET,
                "--top",
                "vadd",
                "--part",
                "xcu250-figd2104-2L-e",
                "--json",
            ]
        )
