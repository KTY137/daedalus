from __future__ import annotations

import hashlib
import json
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

import daedalus.chip_design.cli as chip_cli
import daedalus.chip_design.executor as executor_module
from daedalus.chip_design.manifest import (
    MANIFEST_SCHEMA,
    build_vivado_project_manifest,
)
from daedalus.chip_design.vivado_tcl import trusted_vivado_tcl
from daedalus.kernel.offload_lease import write_evidence_root
from daedalus.storage import ArtifactStore


REVISION = "a" * 40
PART = "xc7a35ticsg324-1L"
PLAN_SCHEMA = "daedalus-chip-vivado-plan/1"


def _write_project(
    root: Path,
    *,
    project_path_metadata: str,
    rtl: str = "module top; endmodule\n",
) -> Path:
    source = root / "demo.srcs" / "sources_1" / "new" / "top.sv"
    constraints = root / "demo.srcs" / "constrs_1" / "new" / "pins.xdc"
    source.parent.mkdir(parents=True, exist_ok=True)
    constraints.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(rtl, encoding="utf-8")
    constraints.write_text(
        "set_property PACKAGE_PIN A1 [get_ports clk]\n",
        encoding="utf-8",
    )
    xpr = root / "demo.xpr"
    xpr.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<Project Product="Vivado" Version="7" Minor="64" Path="{escape(project_path_metadata)}">
  <Configuration>
    <Option Name="Part" Val="{PART}"/>
  </Configuration>
  <FileSets>
    <FileSet Name="sources_1" Type="DesignSrcs">
      <File Path="$PSRCDIR/sources_1/new/top.sv">
        <FileInfo><Attr Name="UsedIn" Val="synthesis"/></FileInfo>
      </File>
      <Config><Option Name="TopModule" Val="top"/></Config>
    </FileSet>
    <FileSet Name="constrs_1" Type="Constrs">
      <File Path="$PSRCDIR/constrs_1/new/pins.xdc">
        <FileInfo><Attr Name="UsedIn" Val="implementation"/></FileInfo>
      </File>
    </FileSet>
  </FileSets>
  <Runs>
    <Run Id="synth_1" Type="Ft3:Synth" SrcSet="sources_1" ConstrsSet="constrs_1" Part="{PART}" Dir="$PRUNDIR/synth_1"/>
    <Run Id="impl_1" Type="Ft2:EntireDesign" SrcSet="sources_1" ConstrsSet="constrs_1" SynthRun="synth_1" Part="{PART}" Dir="$PRUNDIR/impl_1"/>
  </Runs>
</Project>
""",
        encoding="utf-8",
    )
    return xpr


def _project_pair(tmp_path: Path, *, same_identity: bool = True) -> tuple[Path, Path]:
    source_root = tmp_path / "authoritative-source"
    workspace_root = tmp_path / "isolated-workspace"
    source_root.mkdir()
    workspace_root.mkdir()
    source = _write_project(
        source_root,
        project_path_metadata=r"C:\authoritative\demo.xpr",
    )
    workspace = _write_project(
        workspace_root,
        project_path_metadata=r"D:\isolated\demo.xpr",
        rtl=(
            "module top; wire identity_changed; endmodule\n"
            if not same_identity
            else "module top; endmodule\n"
        ),
    )
    return source, workspace


def _tree_snapshot(root: Path) -> tuple[tuple[str, str], ...]:
    rows: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            rows.append((relative, "directory"))
        elif path.is_file():
            rows.append((relative, hashlib.sha256(path.read_bytes()).hexdigest()))
        else:
            rows.append((relative, "other"))
    return tuple(rows)


def _forbid_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("effect-free CLI path reached live admission or execution")

    monkeypatch.setattr(chip_cli, "acquire_chip_eda_lease", forbidden)
    monkeypatch.setattr(chip_cli, "run_admitted_eda", forbidden)
    monkeypatch.setattr(chip_cli, "execute_argv", forbidden)


def _json_stdout(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    captured = capsys.readouterr()
    assert captured.err == ""
    return json.loads(captured.out)


def _run_args(
    source_xpr: Path,
    workspace_xpr: Path,
    authority_root: Path,
    *,
    confirm: bool = True,
) -> list[str]:
    _write_authority_head(authority_root)
    args = [
        "run",
        str(source_xpr),
        "--workspace-project",
        str(workspace_xpr),
        "--phase",
        "synth",
        "--authority-root",
        str(authority_root),
        "--source-revision",
        REVISION,
        "--attempt-id",
        "test-attempt",
        "--writable-path",
        ".",
        "--json",
    ]
    if confirm:
        args.append("--confirm-project-writes")
    return args


def _write_authority_head(authority_root: Path, revision: str = REVISION) -> None:
    git_dir = authority_root / ".git"
    git_dir.mkdir(exist_ok=True)
    (git_dir / "HEAD").write_bytes((revision + "\n").encode("ascii"))


def _write_chip_policy(authority_root: Path, *, write_allow=(".",)) -> Path:
    policy = authority_root / ".agentenv" / "chip-eda-policy.json"
    policy.parent.mkdir(parents=True, exist_ok=True)
    policy.write_text(
        json.dumps({"policy": {"write_allow": list(write_allow)}}),
        encoding="utf-8",
    )
    return policy


def test_live_run_requires_an_explicit_stable_attempt_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source, workspace = _project_pair(tmp_path)
    authority = tmp_path / "authority"
    authority.mkdir()
    arguments = _run_args(source, workspace, authority)
    attempt_index = arguments.index("--attempt-id")
    del arguments[attempt_index : attempt_index + 2]
    _forbid_effects(monkeypatch)

    with pytest.raises(SystemExit) as caught:
        chip_cli.main(arguments)

    assert caught.value.code == 2
    assert "--attempt-id" in capsys.readouterr().err


def test_inspect_xpr_is_effect_free_and_returns_the_authoritative_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    xpr = _write_project(root, project_path_metadata=r"C:\source\demo.xpr")
    expected = build_vivado_project_manifest(xpr)
    before = _tree_snapshot(root)
    _forbid_effects(monkeypatch)

    assert chip_cli.main(["inspect", str(xpr), "--json"]) == 0

    payload = _json_stdout(capsys)
    assert payload["schema"] == MANIFEST_SCHEMA
    assert payload["sha256"] == expected.sha256
    assert payload["source_identity_sha256"] == expected.source_identity_sha256
    assert payload["project"]["path"] == "demo.xpr"
    assert _tree_snapshot(root) == before


@pytest.mark.parametrize("phase", ["inspect", "synth", "impl"])
def test_plan_xpr_is_effect_free_and_binds_manifest_tcl_and_discrete_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    phase: str,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    xpr = _write_project(root, project_path_metadata=r"C:\source\demo.xpr")
    manifest = build_vivado_project_manifest(xpr)
    trusted = trusted_vivado_tcl()
    before = _tree_snapshot(root)
    _forbid_effects(monkeypatch)

    assert chip_cli.main(["plan", str(xpr), "--phase", phase, "--json"]) == 0

    payload = _json_stdout(capsys)
    assert payload["schema"] == PLAN_SCHEMA
    assert payload["phase"] == phase
    assert payload["manifest_sha256"] == manifest.sha256
    assert payload["source_identity_sha256"] == manifest.source_identity_sha256
    assert payload["trusted_tcl_sha256"] == trusted.sha256
    assert payload["security_boundary_claimed"] is False
    argv = payload["argv"]
    assert argv[0] == "vivado"
    assert argv[argv.index("-source") + 1] == trusted.path
    assert str(xpr.resolve()) in argv
    assert _tree_snapshot(root) == before


@pytest.mark.parametrize("command", ["tcl", "lint"])
def test_raw_live_commands_are_disabled_before_lease_or_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    authority = tmp_path / "authority"
    source_root = tmp_path / "source"
    workspace = tmp_path / "workspace"
    for root in (authority, source_root, workspace):
        root.mkdir()
    script = workspace / "raw.tcl"
    rtl = workspace / "top.sv"
    script.write_text("puts forbidden\n", encoding="utf-8")
    rtl.write_text("module top; endmodule\n", encoding="utf-8")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("raw --live reached lease acquisition or process spawn")

    monkeypatch.setattr(chip_cli, "acquire_chip_eda_lease", forbidden)
    monkeypatch.setattr(chip_cli, "run_admitted_eda", forbidden)
    common = [
        "--repo-root",
        str(workspace),
        "--live",
        "--authority-root",
        str(authority),
        "--project-root",
        str(source_root),
        "--source-revision",
        REVISION,
        "--writable-path",
        ".",
    ]
    argv = (
        ["tcl", "vivado", str(script), *common]
        if command == "tcl"
        else ["lint", str(rtl), *common]
    )

    with pytest.raises(SystemExit) as caught:
        chip_cli.main(argv)

    assert caught.value.code == 2
    error = capsys.readouterr().err.lower()
    assert "live" in error
    assert "run" in error


def test_run_requires_explicit_confirmation_before_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source, workspace = _project_pair(tmp_path)
    authority = tmp_path / "authority"
    authority.mkdir()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("unconfirmed project writes reached admission or spawn")

    monkeypatch.setattr(chip_cli, "acquire_chip_eda_lease", forbidden)
    monkeypatch.setattr(chip_cli, "run_admitted_eda", forbidden)

    with pytest.raises(SystemExit) as caught:
        chip_cli.main(_run_args(source, workspace, authority, confirm=False))

    assert caught.value.code == 2
    assert "confirm-project-writes" in capsys.readouterr().err.lower()


def test_run_refuses_non_disjoint_source_and_workspace_before_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    source = _write_project(
        source_root,
        project_path_metadata=r"C:\source\demo.xpr",
    )
    authority = tmp_path / "authority"
    authority.mkdir()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("overlapping project roots reached admission or spawn")

    monkeypatch.setattr(chip_cli, "acquire_chip_eda_lease", forbidden)
    monkeypatch.setattr(chip_cli, "run_admitted_eda", forbidden)

    with pytest.raises(SystemExit) as caught:
        chip_cli.main(_run_args(source, source, authority))

    assert caught.value.code == 2
    assert "disjoint" in capsys.readouterr().err.lower()


def test_run_refuses_source_revision_that_does_not_match_authority_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source, workspace = _project_pair(tmp_path)
    authority = tmp_path / "authority"
    authority.mkdir()
    arguments = _run_args(source, workspace, authority)
    revision_index = arguments.index("--source-revision") + 1
    arguments[revision_index] = "b" * 40
    _forbid_effects(monkeypatch)

    with pytest.raises(SystemExit) as caught:
        chip_cli.main(arguments)

    assert caught.value.code == 2
    assert "repository head differs" in capsys.readouterr().err.lower()


def test_run_refuses_workspace_with_different_source_identity_before_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source, workspace = _project_pair(tmp_path, same_identity=False)
    authority = tmp_path / "authority"
    authority.mkdir()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("source-identity mismatch reached admission or spawn")

    monkeypatch.setattr(chip_cli, "acquire_chip_eda_lease", forbidden)
    monkeypatch.setattr(chip_cli, "run_admitted_eda", forbidden)

    with pytest.raises(SystemExit) as caught:
        chip_cli.main(_run_args(source, workspace, authority))

    assert caught.value.code == 2
    error = capsys.readouterr().err.lower()
    assert "source" in error
    assert "identity" in error


def test_flow_summary_requires_exact_phase_identity_and_vivado_version(
    tmp_path: Path,
) -> None:
    root = tmp_path / "summary-project"
    root.mkdir()
    project = _write_project(root, project_path_metadata=r"C:\source\demo.xpr")
    summary = root / "inspect_summary.txt"
    valid = {
        "schema": "daedalus-vivado-flow-summary/1",
        "phase": "inspect",
        "tool": "Vivado v2025.1.1",
        "project": str(project.resolve()),
        "part": PART,
        "board_part": "",
        "top": "top",
        "synth_run": "synth_1",
        "impl_run": "impl_1",
        "synth_status": "Not started",
        "synth_progress": "0%",
        "impl_status": "Not started",
        "impl_progress": "0%",
        "ip_count": "0",
        "locked_ip_count": "0",
    }

    def parse(values: dict[str, str]) -> dict[str, object]:
        summary.write_text(
            "".join(f"{key}={value}\n" for key, value in values.items()),
            encoding="utf-8",
        )
        return chip_cli._read_summary(
            summary,
            phase="inspect",
            project_file=project,
            part=PART,
            board_part="",
            top="top",
            synth_run="synth_1",
            impl_run="impl_1",
            jobs=1,
        )

    assert parse(valid)["identity"]["status"] == "parsed"
    for change in (
        {"schema": "untrusted-summary/1"},
        {"phase": "impl"},
        {"tool": "unknown tool"},
        {"project": str(root / "different.xpr")},
    ):
        result = parse({**valid, **change})
        assert result["identity"]["status"] == "unparseable"
        assert len(result["identity"]["sha256"]) == 64

    incomplete = dict(valid)
    incomplete.pop("ip_count")
    assert parse(incomplete)["identity"]["status"] == "unparseable"


def test_stopped_kill_switch_refuses_identical_disjoint_projects_before_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source, workspace = _project_pair(tmp_path, same_identity=True)
    source_manifest = build_vivado_project_manifest(source)
    workspace_manifest = build_vivado_project_manifest(workspace)
    assert source.parent.resolve() != workspace.parent.resolve()
    assert source_manifest.source_identity_sha256 == (
        workspace_manifest.source_identity_sha256
    )

    authority = tmp_path / "authority"
    authority.mkdir()
    permit = tmp_path / "operator-control" / "killswitch"
    permit.parent.mkdir()
    permit.write_text("STOP\n", encoding="ascii")
    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(permit))
    admission_seen = False
    real_acquire = chip_cli.acquire_chip_eda_lease

    def traced_acquire(*args, **kwargs):
        nonlocal admission_seen
        admission_seen = True
        return real_acquire(*args, **kwargs)

    def forbidden_spawn(*_args, **_kwargs):
        raise AssertionError("STOPPED kill switch reached EDA process spawn")

    monkeypatch.setattr(chip_cli, "acquire_chip_eda_lease", traced_acquire)
    monkeypatch.setattr(chip_cli, "run_admitted_eda", forbidden_spawn)

    with pytest.raises(SystemExit) as caught:
        chip_cli.main(_run_args(source, workspace, authority))

    assert caught.value.code == 2
    assert admission_seen is True
    assert "kill switch" in capsys.readouterr().err.lower()
    assert not (permit.parent / "effect-leases.sqlite3").exists()


@pytest.mark.parametrize(
    ("policy_allow", "expected"),
    ((None, "policy"), (("reports/",), "provider.write_policy")),
)
def test_run_refuses_missing_or_denied_operator_write_policy_before_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    policy_allow: tuple[str, ...] | None,
    expected: str,
) -> None:
    source, workspace = _project_pair(tmp_path, same_identity=True)
    authority = tmp_path / "authority"
    authority.mkdir()
    if policy_allow is not None:
        _write_chip_policy(authority, write_allow=policy_allow)
    permit = tmp_path / "operator-control" / "killswitch"
    permit.parent.mkdir()
    permit.write_text("RUN\n", encoding="ascii")
    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(permit))
    vendor = tmp_path / "vendor" / "Vivado" / "bin" / "vivado.bat"
    vendor.parent.mkdir(parents=True)
    vendor.write_text("@echo off\n", encoding="ascii")
    monkeypatch.setattr(
        chip_cli,
        "find_trusted_vendor_tool_path",
        lambda _tool: str(vendor),
    )

    def forbidden_spawn(*_args, **_kwargs):
        raise AssertionError("denied write policy reached EDA process spawn")

    monkeypatch.setattr(chip_cli, "run_admitted_eda", forbidden_spawn)

    with pytest.raises(SystemExit) as caught:
        chip_cli.main(_run_args(source, workspace, authority))

    assert caught.value.code == 2
    assert expected in capsys.readouterr().err.lower()


def test_run_refuses_a_vivado_launcher_from_project_content_before_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source, workspace = _project_pair(tmp_path, same_identity=True)
    authority = tmp_path / "authority"
    authority.mkdir()
    hostile = source.parent / "vivado.bat"
    hostile.write_text("echo hostile\n", encoding="ascii")
    monkeypatch.setattr(
        chip_cli,
        "find_trusted_vendor_tool_path",
        lambda _tool: str(hostile),
    )
    _forbid_effects(monkeypatch)

    with pytest.raises(SystemExit) as caught:
        chip_cli.main(_run_args(source, workspace, authority))

    assert caught.value.code == 2
    assert "source or workspace" in capsys.readouterr().err.lower()


class _SuccessfulInspectProcess:
    """Small ManagedProcess double; it never executes project content."""

    constructions = 0

    def __init__(self, argv, *, stdout, stderr, **_kwargs) -> None:
        type(self).constructions += 1
        values = list(argv)
        tclargs = values.index("-tclargs")
        phase = values[tclargs + 1]
        output = Path(values[tclargs + 4])
        assert phase == "inspect"
        output.mkdir(parents=True)
        (output / "inspect_summary.txt").write_text(
            "schema=daedalus-vivado-flow-summary/1\n"
            "phase=inspect\n"
            "tool=Vivado v2025.1.1\n"
            f"project={values[tclargs + 3]}\n"
            f"part={values[tclargs + 5]}\n"
            f"board_part={values[tclargs + 6]}\n"
            f"top={values[tclargs + 7]}\n"
            f"synth_run={values[tclargs + 8]}\n"
            f"impl_run={values[tclargs + 9]}\n"
            "synth_status=Not started\n"
            "synth_progress=0%\n"
            "impl_status=Not started\n"
            "impl_progress=0%\n"
            "ip_count=0\n"
            "locked_ip_count=0\n",
            encoding="utf-8",
        )
        stdout.write(b"DAEDALUS_VIVADO_RESULT phase=inspect status=complete\n")
        stderr.write(b"")

    @property
    def returncode(self) -> int:
        return 0

    def poll(self) -> int:
        return 0

    def cancel(self):
        raise AssertionError("completed inspect process was cancelled")

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        return None


def test_admitted_inspect_composes_real_lease_artifact_and_evidence_contracts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source, workspace = _project_pair(tmp_path, same_identity=True)
    authority = tmp_path / "authority"
    authority.mkdir()
    _write_authority_head(authority)
    _write_chip_policy(authority)
    permit = tmp_path / "operator-control" / "killswitch"
    permit.parent.mkdir()
    permit.write_text("RUN\n", encoding="ascii")
    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(permit))
    vendor = tmp_path / "vendor" / "Vivado" / "bin" / "vivado.bat"
    vendor.parent.mkdir(parents=True)
    vendor.write_text("@echo off\n", encoding="ascii")
    monkeypatch.setattr(
        chip_cli,
        "find_trusted_vendor_tool_path",
        lambda _tool: str(vendor),
    )
    monkeypatch.setattr(
        executor_module,
        "is_trusted_vendor_tool_path",
        lambda _tool, _path: True,
    )
    monkeypatch.setattr(
        executor_module.shutil,
        "which",
        lambda _command, **_kwargs: str(vendor),
    )
    monkeypatch.setattr(executor_module, "ManagedProcess", _SuccessfulInspectProcess)
    _SuccessfulInspectProcess.constructions = 0

    argv = [
        "run",
        str(source),
        "--workspace-project",
        str(workspace),
        "--phase",
        "inspect",
        "--authority-root",
        str(authority),
        "--source-revision",
        REVISION,
        "--attempt-id",
        "canonical-inspect",
        "--writable-path",
        ".",
        "--confirm-project-writes",
        "--json",
    ]
    result = chip_cli.main(argv)

    assert result == 0
    payload = _json_stdout(capsys)
    assert payload["status"] == "complete"
    assert payload["signoff"] is False
    step = payload["steps"][0]
    assert step["status"] == "ok"
    assert step["process_spawned"] is True
    assert step["verdict"] == "inconclusive"
    assert step["evaluation_status"] == "inconclusive"
    assert step["metrics"]["artifact_binding"]["status"] == "passed"
    assert step["metrics"]["messages"]["status"] == "unparseable"
    assert len(step["metrics"]["execution_plan_sha256"]) == 64
    assert step["receipt_locator"].startswith("artifact-locator:sha256:")
    assert step["evidence_locator"].startswith("artifact-locator:sha256:")
    assert _SuccessfulInspectProcess.constructions == 1

    store = ArtifactStore(write_evidence_root(authority, REVISION) / "artifacts")
    evidence_locator = store.load_locator(step["evidence_locator"].rsplit(":", 1)[-1])
    evidence = json.loads(store.get_bytes(evidence_locator.artifact_sha256))
    assert evidence["contract_type"] == "daedalus.evidence"
    assert evidence["evaluation_status"] == "inconclusive"

    # A process restart with the same phase attempt cannot mint a fresh lease
    # or silently execute again. The deterministic lease identity reaches the
    # canonical ledger replay refusal before another ManagedProcess exists.
    assert chip_cli.main(argv) == 1
    replay = _json_stdout(capsys)
    assert replay["status"] == "error"
    assert "EffectLeaseReplay" in replay["error"]
    assert _SuccessfulInspectProcess.constructions == 1
