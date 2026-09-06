"""Tool discovery must be honest, and honest here means effect-free.

The load-bearing claim: asking for status never crosses a process boundary. A
status call that shells out to ``kicad-cli --version`` would be an unregistered
effect entrypoint, which this repository's review rules class as a
release-blocking defect. So the version stays empty and its provenance is
always stated.
"""
from __future__ import annotations

import pytest

from daedalus.pcb_design.toolchains import (
    TOOLS,
    all_tool_status,
    find_tool_path,
    get_tool,
    interpret_version_probe,
    tool_status,
)

TOOL_IDS = [tool.id for tool in TOOLS]


def test_the_registry_covers_the_tools_the_owner_named():
    assert {"kicad-cli", "pcbnew", "ngspice", "gerbv"} <= set(TOOL_IDS)


def test_ids_are_unique_and_lookup_is_exact():
    assert len(TOOL_IDS) == len(set(TOOL_IDS))
    assert get_tool("kicad-cli").command == "kicad-cli"
    with pytest.raises(KeyError):
        get_tool("kicad-cli-typo")


@pytest.mark.parametrize("tool_id", TOOL_IDS)
def test_status_never_reports_a_version_it_did_not_measure(tool_id):
    row = tool_status(tool_id)
    assert row["version"] == "", "status must not invent or probe a version"
    assert row["probe_status"] in {"not_run", "not_imported"}
    assert row["version_probe_returncode"] is None
    assert row["imported"] is False


@pytest.mark.parametrize("tool_id", TOOL_IDS)
def test_status_is_either_available_with_a_path_or_absent_with_a_reason(tool_id):
    row = tool_status(tool_id)
    if row["available"]:
        assert row["command_path"], "an available tool must say where it is"
        assert row["last_error"] == ""
    else:
        assert row["command_path"] == ""
        assert row["last_error"], "an absent tool must say why"


def test_status_never_starts_a_process(monkeypatch):
    """Fault injection: make every process start explode, then ask for status."""

    import os
    import subprocess

    def explode(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("tool discovery started a process")

    monkeypatch.setattr(subprocess, "Popen", explode)
    monkeypatch.setattr(subprocess, "run", explode)
    monkeypatch.setattr(subprocess, "check_output", explode)
    monkeypatch.setattr(os, "system", explode)
    monkeypatch.setattr(os, "popen", explode)

    rows = all_tool_status()
    assert len(rows) == len(TOOLS)


def test_python_modules_are_located_but_never_imported(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def guard(name, *args, **kwargs):
        if name.split(".")[0] in {"pcbnew", "kipy"}:  # pragma: no cover
            raise AssertionError(f"discovery imported {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guard)
    row = tool_status("pcbnew")
    assert row["kind"] == "python_module"
    assert row["imported"] is False
    assert row["probe_status"] == "not_imported"


def test_the_pcbnew_row_refuses_to_conclude_kicad_is_absent():
    row = tool_status("pcbnew")
    assert "not evidence that" in row["notes"] or "not evidence" in row["notes"]


def test_an_environment_override_wins_and_is_labelled(tmp_path, monkeypatch):
    fake = tmp_path / "kicad-cli"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("DAEDALUS_PCB_KICAD_CLI_COMMAND", str(fake))
    path, how = find_tool_path("kicad-cli")
    assert how == "env_override"
    assert path.endswith("kicad-cli")
    assert tool_status("kicad-cli")["available"] is True


def test_an_override_naming_a_missing_file_does_not_fall_through_to_path(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DAEDALUS_PCB_KICAD_CLI_COMMAND", str(tmp_path / "absent"))
    path, how = find_tool_path("kicad-cli")
    assert (path, how) == ("", "env_override_missing")
    row = tool_status("kicad-cli")
    assert row["available"] is False
    assert "environment override" in row["last_error"]


def test_a_kicad_install_series_is_not_reported_as_a_version(tmp_path, monkeypatch):
    binary = tmp_path / "Program Files" / "KiCad" / "9.0" / "bin" / "kicad-cli.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"")
    monkeypatch.setenv("DAEDALUS_PCB_KICAD_CLI_COMMAND", str(binary))
    row = tool_status("kicad-cli")
    assert row["install_series"] == "9.0"
    assert row["version"] == "", "an install directory name is not a running version"
    assert row["version_source"] == "install_path"


def test_a_module_row_has_no_command_globs_applied():
    assert find_tool_path("pcbnew") == ("", "")


# ---------------------------------------------------------------------------
# interpret_version_probe: pure interpretation of output obtained elsewhere
# ---------------------------------------------------------------------------


def test_a_clean_kicad_cli_banner_parses():
    result = interpret_version_probe("kicad-cli", returncode=0, stdout="9.0.1\n")
    assert result["version"] == "9.0.1"
    assert result["version_source"] == "probe"
    assert result["probe_status"] == "ok"
    assert result["last_error"] == ""


def test_a_nonzero_launcher_with_a_banner_stays_a_warning_not_a_success():
    result = interpret_version_probe("kicad-cli", returncode=1, stderr="8.0.7\n")
    assert result["version"] == "8.0.7"
    assert result["probe_status"] == "warning"
    assert "exited 1" in result["probe_warning"]


def test_a_failed_probe_reports_the_output_not_a_version():
    result = interpret_version_probe(
        "kicad-cli", returncode=127, stderr="command not found"
    )
    assert result["version"] == ""
    assert result["version_source"] == ""
    assert result["probe_status"] == "failed"
    assert result["last_error"] == "command not found"


def test_a_probe_that_never_started_is_distinguished_from_one_that_failed():
    result = interpret_version_probe("gerbv", returncode=None)
    assert result["probe_status"] == "failed"
    assert result["last_error"] == "probe did not start"


def test_ngspice_and_gerbv_banners_parse():
    ngspice = interpret_version_probe(
        "ngspice",
        returncode=0,
        stdout="******\n** ngspice-44 : Circuit level simulation program\n",
    )
    assert ngspice["version"] == "44"
    gerbv = interpret_version_probe(
        "gerbv", returncode=0, stdout="gerbv version 2.10.0\n"
    )
    assert gerbv["version"] == "2.10.0"


def test_interpret_version_probe_starts_no_process(monkeypatch):
    import subprocess

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("started a process")),
    )
    assert interpret_version_probe("kicad-cli", returncode=0, stdout="9.0.1")["version"]
