from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import daedalus.chip_design.execution_plan as execution_plan_module
import daedalus.chip_design.toolchains as toolchains_module
from daedalus.chip_design.execution_plan import (
    EDA_EXECUTION_PLAN_SCHEMA,
    EdaExecutionPlan,
    environment_sha256,
    sanitized_eda_environment,
    trusted_windows_command_interpreter,
)


def test_sanitized_environment_is_allowlisted_secret_free_and_workspace_temp(
    tmp_path: Path,
) -> None:
    work = tmp_path / "workspace"
    work.mkdir()
    host = {
        "PATH": r"C:\Windows\System32",
        "SystemRoot": r"C:\Windows",
        "LM_LICENSE_FILE": "27000@license.example",
        "HTTPS_PROXY": "http://proxy.example",
        "GITHUB_TOKEN": "secret",
        "AWS_SECRET_ACCESS_KEY": "secret",
    }

    environment = sanitized_eda_environment(work, host_environment=host)

    assert environment["PATH"] == host["PATH"]
    assert environment["SYSTEMROOT"] == host["SystemRoot"]
    assert environment["TEMP"] == str(work.resolve())
    assert environment["TMP"] == str(work.resolve())
    assert not {
        "LM_LICENSE_FILE",
        "HTTPS_PROXY",
        "GITHUB_TOKEN",
        "AWS_SECRET_ACCESS_KEY",
    } & set(environment)
    assert len(environment_sha256(environment)) == 64


def test_sanitized_profile_is_unique_per_bound_output_directory(
    tmp_path: Path,
) -> None:
    work = tmp_path / "workspace"
    work.mkdir()
    first = sanitized_eda_environment(
        work,
        workspace_manifest_sha256="a" * 64,
        output_dir=work / "out" / "attempt-1",
    )
    repeated = sanitized_eda_environment(
        work,
        workspace_manifest_sha256="a" * 64,
        output_dir=work / "out" / "attempt-1",
    )
    second = sanitized_eda_environment(
        work,
        workspace_manifest_sha256="a" * 64,
        output_dir=work / "out" / "attempt-2",
    )

    assert first == repeated
    assert first["USERPROFILE"] != second["USERPROFILE"]
    assert Path(first["USERPROFILE"]).is_relative_to(work)


@pytest.mark.skipif(os.name != "nt", reason="Windows command interpreter contract")
def test_sanitized_environment_ignores_ambient_windows_shell_roots(
    tmp_path: Path,
) -> None:
    work = tmp_path / "workspace"
    work.mkdir()
    interpreter_path, interpreter_sha256 = trusted_windows_command_interpreter()

    environment = sanitized_eda_environment(
        work,
        host_environment={
            "SYSTEMROOT": str(work / "attacker-root"),
            "WINDIR": str(work / "attacker-windir"),
            "COMSPEC": str(work / "cmd.exe"),
            "PATH": str(work),
        },
    )

    assert environment["COMSPEC"] == interpreter_path
    assert environment["PATH"] == str(Path(interpreter_path).parent)
    assert environment["SYSTEMROOT"] == str(Path(interpreter_path).parent.parent)
    assert len(interpreter_sha256) == 64


@pytest.mark.skipif(os.name != "nt", reason="Windows command interpreter contract")
def test_command_interpreter_refuses_a_linked_system_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        execution_plan_module,
        "_has_linklike_component",
        lambda _path: True,
    )

    with pytest.raises(ValueError, match="linked component"):
        trusted_windows_command_interpreter()


@pytest.mark.parametrize(
    "module",
    (execution_plan_module, toolchains_module),
)
def test_windows_reparse_fallback_covers_python_without_path_is_junction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    module: object,
) -> None:
    candidate = tmp_path / "ordinary-looking-component"
    candidate.mkdir()
    monkeypatch.setattr(
        module,
        "os",
        SimpleNamespace(
            name="nt",
            lstat=lambda _path: SimpleNamespace(st_file_attributes=0x400),
        ),
    )

    assert module._is_linklike(candidate) is True


def test_execution_plan_binds_every_concrete_process_input(tmp_path: Path) -> None:
    work = tmp_path / "workspace"
    store = tmp_path / "authority" / "artifacts"
    work.mkdir()
    environment = sanitized_eda_environment(work, host_environment={"PATH": "vendor"})
    command_interpreter_path, command_interpreter_sha256 = (
        trusted_windows_command_interpreter()
    )
    plan = EdaExecutionPlan.build(
        phase="synth",
        argv=("vivado.bat", "-mode", "batch"),
        source_root=work,
        source_project=work / "demo.xpr",
        cwd=work,
        artifact_paths=("out/timing.rpt", "out/design.dcp"),
        artifact_store_root=store,
        timeout_s=60,
        environment=environment,
        source_manifest_sha256="1" * 64,
        workspace_manifest_sha256="2" * 64,
        source_identity_sha256="3" * 64,
        trusted_tcl_sha256="4" * 64,
        launcher_sha256="5" * 64,
        command_interpreter_path=command_interpreter_path,
        command_interpreter_sha256=command_interpreter_sha256,
    )

    assert plan.schema == EDA_EXECUTION_PLAN_SCHEMA
    assert plan.artifact_paths == ("out/design.dcp", "out/timing.rpt")
    assert plan.environment_keys == tuple(sorted(environment))
    assert len(plan.digest) == 64

    changed = EdaExecutionPlan.build(
        phase="synth",
        argv=("vivado.bat", "-mode", "batch", "-nojournal"),
        source_root=work,
        source_project=work / "demo.xpr",
        cwd=work,
        artifact_paths=plan.artifact_paths,
        artifact_store_root=store,
        timeout_s=60,
        environment=environment,
        source_manifest_sha256="1" * 64,
        workspace_manifest_sha256="2" * 64,
        source_identity_sha256="3" * 64,
        trusted_tcl_sha256="4" * 64,
        launcher_sha256="5" * 64,
        command_interpreter_path=command_interpreter_path,
        command_interpreter_sha256=command_interpreter_sha256,
    )
    assert changed.digest != plan.digest


@pytest.mark.parametrize("path", ("../escape.rpt", "/absolute.rpt"))
def test_execution_plan_refuses_artifact_escape(tmp_path: Path, path: str) -> None:
    with pytest.raises(ValueError, match="relative"):
        EdaExecutionPlan.build(
            phase="inspect",
            argv=("vivado",),
            source_root=tmp_path,
            source_project=tmp_path / "demo.xpr",
            cwd=tmp_path,
            artifact_paths=(path,),
            artifact_store_root=tmp_path / "cas",
            timeout_s=1,
            environment={},
            source_manifest_sha256="1" * 64,
            workspace_manifest_sha256="2" * 64,
            source_identity_sha256="3" * 64,
            trusted_tcl_sha256="4" * 64,
            launcher_sha256="5" * 64,
        )
