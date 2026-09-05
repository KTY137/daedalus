"""CLI contract: canonical JSON on stdout and exit codes that mean something.

``python -m daedalus.pcb_design`` is the whole product surface of this
experiment. It is not registered anywhere -- no effect-registry row, no HTTP
route, no desktop projection, no ``daedalus-chip`` subcommand -- and
``test_pcb_design_isolation.py`` proves that separately.
"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from fixtures.pcb_design import BOARD_TEXT, write_fixture

from daedalus.pcb_design.cli import EXIT_INCOMPLETE, EXIT_OK, EXIT_REFUSED, main


@pytest.fixture
def project(tmp_path):
    return write_fixture(tmp_path / "lane6")


def run(capsys, *argv):
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out


def run_json(capsys, *argv):
    code, out = run(capsys, *argv, "--json")
    assert "\n" not in out.strip(), "--json must emit exactly one canonical line"
    return code, json.loads(out)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def test_status_succeeds_and_lists_every_registered_tool(capsys):
    code, rows = run_json(capsys, "status")
    assert code == EXIT_OK
    assert {row["id"] for row in rows} >= {"kicad-cli", "pcbnew", "ngspice", "gerbv"}
    assert all(row["version"] == "" for row in rows)


def test_status_text_marks_an_install_series_as_not_a_version(capsys, tmp_path, monkeypatch):
    binary = tmp_path / "KiCad" / "8.0" / "bin" / "kicad-cli.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"")
    monkeypatch.setenv("DAEDALUS_PCB_KICAD_CLI_COMMAND", str(binary))
    code, out = run(capsys, "status")
    assert code == EXIT_OK
    assert "install series 8.0, not a probed version" in out


def test_status_text_says_absent_with_a_reason(capsys, monkeypatch):
    monkeypatch.setenv("DAEDALUS_PCB_KICAD_CLI_COMMAND", "/definitely/not/here")
    code, out = run(capsys, "status")
    assert code == EXIT_OK
    assert "ABSENT" in out


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------


def test_scan_binds_a_project_with_byte_identities(capsys, project, tmp_path):
    code, payload = run_json(capsys, "scan", str(tmp_path))
    assert code == EXIT_OK
    assert payload["project_count"] == 1
    entry = payload["projects"][0]
    assert entry["name"] == "lane6_fixture"
    assert entry["project_file"] == "lane6/lane6_fixture.kicad_pro"
    board = entry["boards"][0]
    assert board["sha256"] == payload["projects"][0]["boards"][0]["sha256"]
    assert board["hash_status"] == "sha256"
    assert board["size_bytes"] == project["board"].stat().st_size
    assert board["authoritative"] is True
    assert payload["unbound"] == []


def test_scan_reports_a_standalone_board_as_unbound_instead_of_guessing(
    capsys, tmp_path
):
    loose = tmp_path / "loose"
    loose.mkdir()
    (loose / "orphan.kicad_pcb").write_bytes(BOARD_TEXT.encode("utf-8"))
    code, payload = run_json(capsys, "scan", str(tmp_path))
    assert code == EXIT_OK
    assert payload["project_count"] == 0
    assert [row["path"] for row in payload["unbound"]] == ["loose/orphan.kicad_pcb"]


def test_scan_ignores_kicad_backup_directories(capsys, tmp_path, project):
    backups = tmp_path / "lane6" / "lane6_fixture-backups"
    backups.mkdir()
    (backups / "old.kicad_pcb").write_bytes(BOARD_TEXT.encode("utf-8"))
    _, payload = run_json(capsys, "scan", str(tmp_path))
    assert all("-backups" not in row["path"] for row in payload["unbound"])
    assert payload["artifact_count"] == 3


def test_scan_signals_truncation_with_a_nonzero_exit(capsys, project, tmp_path):
    code, payload = run_json(capsys, "scan", str(tmp_path), "--max-files", "1")
    assert code == EXIT_INCOMPLETE
    assert payload["truncated"] is True
    assert payload["artifact_count"] == 1


def test_scan_skips_hashing_beyond_the_byte_bound_instead_of_lying(
    capsys, project, tmp_path
):
    _, payload = run_json(capsys, "scan", str(tmp_path), "--max-hash-bytes", "10")
    rows = payload["projects"][0]["boards"] + payload["projects"][0]["schematics"]
    assert rows, "the fixture must still be discovered"
    for row in rows:
        assert row["sha256"] == ""
        assert row["hash_status"] == "skipped_too_large"
        assert row["size_bytes"] > 10


def test_scan_refuses_a_root_that_is_not_a_directory(project):
    with pytest.raises(SystemExit) as caught:
        main(["scan", str(project["board"])])
    assert caught.value.code == 2


# ---------------------------------------------------------------------------
# inspect
# ---------------------------------------------------------------------------


def test_inspect_a_board_succeeds_and_emits_canonical_json(capsys, project):
    code, report = run_json(capsys, "inspect", str(project["board"]))
    assert code == EXIT_OK
    assert report["schema"] == "daedalus.pcb_design/board-report/1"
    assert report["footprint_count"] == 2
    assert report["complete"] is True


def test_inspect_a_schematic_succeeds(capsys, project):
    code, report = run_json(capsys, "inspect", str(project["schematic"]))
    assert code == EXIT_OK
    assert report["schema"] == "daedalus.pcb_design/schematic-report/1"
    assert report["symbol_count"] == 2


def test_inspect_pretty_prints_by_default(capsys, project):
    code, out = run(capsys, "inspect", str(project["board"]))
    assert code == EXIT_OK
    assert "\n" in out
    assert json.loads(out)["report_sha256"]


def test_a_refusal_exits_three_and_prints_the_reason(capsys, tmp_path):
    target = tmp_path / "broken.kicad_pcb"
    target.write_bytes(b"(kicad_pcb (version 20240108)")
    code, payload = run_json(capsys, "inspect", str(target))
    assert code == EXIT_REFUSED
    assert payload["refused"] is True
    assert payload["reason"] == "malformed_sexpr"
    assert payload["detail"]


def test_an_unsupported_suffix_exits_three(capsys, project):
    code, payload = run_json(capsys, "inspect", str(project["project"]))
    assert code == EXIT_REFUSED
    assert payload["reason"] == "unsupported_suffix"


def test_a_force_parsed_unknown_version_exits_one(capsys, tmp_path):
    target = tmp_path / "future.kicad_pcb"
    target.write_bytes(BOARD_TEXT.replace("20240108", "20260101").encode("utf-8"))
    code, payload = run_json(
        capsys, "inspect", str(target), "--allow-unknown-version"
    )
    assert code == EXIT_INCOMPLETE
    assert payload["complete"] is False


def test_the_max_bytes_flag_is_enforced(capsys, project):
    code, payload = run_json(
        capsys, "inspect", str(project["board"]), "--max-bytes", "32"
    )
    assert code == EXIT_REFUSED
    assert payload["reason"] == "input_too_large"


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------


def test_plan_is_inadmissible_on_every_host_and_says_why(capsys):
    code, payload = run_json(capsys, "plan")
    assert code == EXIT_INCOMPLETE
    assert payload["admissible"] is False
    assert payload["effects_performed"] == []
    assert all(step["executed"] is False for step in payload["steps"])
    reasons = payload["inadmissible_reasons"]
    assert "governance:amendment_013_adopted" in reasons
    assert "governance:effect_lease" in reasons
    assert "governance:owner_approval" in reasons


def test_plan_names_the_argv_it_would_use_without_building_a_command_line(capsys):
    _, payload = run_json(capsys, "plan")
    erc = next(step for step in payload["steps"] if step["id"] == "erc")
    assert erc["argv_shape"][:3] == ["kicad-cli", "sch", "erc"]
    assert "--exit-code-violations" in erc["argv_shape"]
    assert any("<" in token and ">" in token for token in erc["argv_shape"]), (
        "placeholders must stay unsubstituted"
    )


def test_plan_separates_a_missing_binary_from_the_real_blocker(capsys, monkeypatch):
    monkeypatch.setenv("DAEDALUS_PCB_KICAD_CLI_COMMAND", "/definitely/not/here")
    _, payload = run_json(capsys, "plan", "--step", "erc")
    step = payload["steps"][0]
    assert step["status"] == "blocked_external"
    assert "kicad-cli:absent" in step["blocked_by"]
    assert "governance:effect_lease" in step["blocked_by"]
    assert payload["missing_tools"] == ["kicad-cli"]


def test_plan_can_be_restricted_and_rejects_unknown_steps(capsys):
    _, payload = run_json(capsys, "plan", "--step", "drc", "--step", "nonsense")
    assert [step["id"] for step in payload["steps"]] == ["drc"]
    assert payload["unknown_step_ids"] == ["nonsense"]
    assert "unknown_step:nonsense" in payload["inadmissible_reasons"]


def test_the_plan_shape_digest_ignores_host_measurements(capsys, monkeypatch):
    _, first = run_json(capsys, "plan")
    monkeypatch.setenv("DAEDALUS_PCB_KICAD_CLI_COMMAND", "/definitely/not/here")
    _, second = run_json(capsys, "plan")
    assert first["plan_shape_sha256"] == second["plan_shape_sha256"]


# ---------------------------------------------------------------------------
# module entrypoint
# ---------------------------------------------------------------------------


def test_the_module_entrypoint_runs_and_returns_the_documented_code(project):
    result = subprocess.run(
        [sys.executable, "-m", "daedalus.pcb_design", "inspect", str(project["board"]), "--json"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == EXIT_OK, result.stderr
    assert json.loads(result.stdout)["footprint_count"] == 2


def test_the_module_entrypoint_propagates_a_refusal_code(tmp_path):
    target = tmp_path / "broken.kicad_pcb"
    target.write_bytes(b"(((")
    result = subprocess.run(
        [sys.executable, "-m", "daedalus.pcb_design", "inspect", str(target), "--json"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == EXIT_REFUSED
    assert json.loads(result.stdout)["reason"] == "malformed_sexpr"


def test_an_unknown_subcommand_is_a_usage_error():
    with pytest.raises(SystemExit) as caught:
        main(["publish"])
    assert caught.value.code == 2
