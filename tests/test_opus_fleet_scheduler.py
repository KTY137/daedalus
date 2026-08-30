# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from experiments.opus_fleet_watchdog import scheduler


def _paths(tmp_path: Path) -> scheduler.SchedulerPaths:
    repo = (tmp_path / "repo root").resolve()
    return scheduler.SchedulerPaths.validated(
        pythonw=(tmp_path / "Python Runtime" / "pythonw.exe").resolve(),
        watchdog=(repo / "tools" / "watchdog.py").resolve(),
        config=(repo / ".agentenv" / "opus fleet.json").resolve(),
        working_directory=repo,
    )


def _task_xml(
    paths: scheduler.SchedulerPaths,
    *,
    interval: str = "PT20M",
    duration: str = "P3650D",
) -> str:
    command = escape(str(paths.pythonw))
    arguments = escape(paths.action_arguments)
    working_directory = escape(str(paths.working_directory))
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <TimeTrigger>
      <Repetition>
        <Interval>{interval}</Interval>
        <Duration>{duration}</Duration>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>2026-08-25T12:00:00+02:00</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>example\\developer</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <Hidden>true</Hidden>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{command}</Command>
      <Arguments>{arguments}</Arguments>
      <WorkingDirectory>{working_directory}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>"""


def _status_json(
    paths: scheduler.SchedulerPaths, *, result: int = 0, xml: str | None = None
) -> str:
    return json.dumps(
        {
            "installed": True,
            "task_name": scheduler.TASK_FULL_NAME,
            "state": "Ready",
            "last_task_result": result,
            "last_run_time": "2026-08-25T12:00:00.0000000+02:00",
            "next_run_time": "2026-08-25T12:20:00.0000000+02:00",
            "xml": _task_xml(paths) if xml is None else xml,
        }
    )


def test_install_builder_keeps_dynamic_paths_out_of_powershell_source(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)

    invocation = scheduler.build_install(
        pythonw=paths.pythonw,
        watchdog=paths.watchdog,
        config=paths.config,
        working_directory=paths.working_directory,
    )

    assert invocation.argv[:7] == scheduler.POWERSHELL_ARGV_PREFIX
    assert invocation.argv[-1] == scheduler.INSTALL_SCRIPT
    assert invocation.environment == paths.environment()
    for dynamic_value in paths.environment().values():
        assert dynamic_value not in scheduler.INSTALL_SCRIPT
        assert dynamic_value not in "\0".join(invocation.argv)

    script = scheduler.INSTALL_SCRIPT
    assert "New-ScheduledTaskAction" in script
    assert "New-ScheduledTaskTrigger" in script
    assert "New-ScheduledTaskPrincipal" in script
    assert "New-ScheduledTaskSettingsSet" in script
    assert "Register-ScheduledTask" in script
    assert "schtasks" not in script.casefold()
    assert "'fleet'" in script
    assert "'--config'" in script
    assert "-RepetitionInterval (New-TimeSpan -Minutes 20)" in script
    assert "-RepetitionDuration (New-TimeSpan -Days 3650)" in script


def test_install_script_has_exact_reliability_and_principal_contract() -> None:
    script = scheduler.INSTALL_SCRIPT

    required_fragments = (
        "-LogonType Interactive",
        "-RunLevel Limited",
        "-MultipleInstances IgnoreNew",
        "-StartWhenAvailable",
        "-AllowStartIfOnBatteries",
        "-DontStopIfGoingOnBatteries",
        "-DontStopOnIdleEnd",
        "-RestartCount 0",
        "-Hidden",
        "-ExecutionTimeLimit (New-TimeSpan -Hours 2)",
        "-TaskName 'OpusFleet'",
        "-TaskPath '\\Daedalus\\'",
        "-Force",
    )
    for fragment in required_fragments:
        assert fragment in script


def test_paths_must_be_absolute_pythonw_and_canonical_watchdog(
    tmp_path: Path,
) -> None:
    repo = tmp_path.resolve()

    with pytest.raises(ValueError, match="pythonw must"):
        scheduler.SchedulerPaths.validated(
            pythonw=repo / "python.exe",
            watchdog=repo / "tools" / "watchdog.py",
            config=repo / "fleet.json",
            working_directory=repo,
        )

    with pytest.raises(ValueError, match="tools/watchdog.py"):
        scheduler.SchedulerPaths.validated(
            pythonw=repo / "pythonw.exe",
            watchdog=repo / "other.py",
            config=repo / "fleet.json",
            working_directory=repo,
        )

    with pytest.raises(ValueError, match="absolute"):
        scheduler.SchedulerPaths.validated(
            pythonw="pythonw.exe",
            watchdog=repo / "tools" / "watchdog.py",
            config=repo / "fleet.json",
            working_directory=repo,
        )


def test_uninstall_and_status_builders_use_only_scheduledtasks_cmdlets() -> None:
    uninstall = scheduler.build_uninstall()
    status = scheduler.build_status()

    assert uninstall.environment == {}
    assert "Unregister-ScheduledTask" in uninstall.argv[-1]
    assert "Get-ScheduledTask" in uninstall.argv[-1]
    assert "schtasks" not in uninstall.argv[-1].casefold()
    assert status.environment == {}
    assert "Get-ScheduledTaskInfo" in status.argv[-1]
    assert "Export-ScheduledTask" in status.argv[-1]
    assert "ConvertTo-Json" in status.argv[-1]


def test_export_parser_accepts_exact_task_contract(tmp_path: Path) -> None:
    paths = _paths(tmp_path)

    exported = scheduler.parse_exported_task_xml(_task_xml(paths))

    assert exported.command == str(paths.pythonw)
    assert exported.arguments == paths.action_arguments
    assert exported.working_directory == str(paths.working_directory)
    assert exported.repetition_interval == "PT20M"
    assert exported.repetition_duration == "P3650D"
    assert exported.logon_type == "InteractiveToken"
    assert exported.run_level == "LeastPrivilege"
    assert exported.multiple_instances_policy == "IgnoreNew"
    assert exported.start_when_available is True
    assert exported.disallow_start_if_on_batteries is False
    assert exported.stop_if_going_on_batteries is False
    assert exported.stop_on_idle_end is False
    assert exported.restart_count == 0
    assert exported.hidden is True
    assert exported.execution_time_limit == "PT2H"
    assert exported.contract_violations(paths) == ()


def test_zero_last_result_and_exact_export_are_healthy(tmp_path: Path) -> None:
    paths = _paths(tmp_path)

    status = scheduler.parse_status_output(
        _status_json(paths, result=0), expected_paths=paths
    )

    assert status.installed is True
    assert status.state == "Ready"
    assert status.last_task_result == 0
    assert status.degraded is False
    assert status.degraded_reasons == ()


def test_nonzero_last_task_result_is_always_degraded(tmp_path: Path) -> None:
    paths = _paths(tmp_path)

    status = scheduler.parse_status_output(
        _status_json(paths, result=0x8007042B), expected_paths=paths
    )

    assert status.installed is True
    assert status.last_task_result == 0x8007042B
    assert status.degraded is True
    assert "last_task_result:2147943467" in status.degraded_reasons


def test_export_contract_drift_is_degraded_even_after_success(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    drifted_xml = _task_xml(paths, interval="PT15M", duration="P1D")

    status = scheduler.parse_status_output(
        _status_json(paths, result=0, xml=drifted_xml), expected_paths=paths
    )

    assert status.degraded is True
    assert any("repetition_interval" in reason for reason in status.degraded_reasons)
    assert any("repetition_duration" in reason for reason in status.degraded_reasons)


def test_absent_task_is_reported_degraded() -> None:
    status = scheduler.parse_status_output(
        json.dumps({"installed": False, "task_name": scheduler.TASK_FULL_NAME})
    )

    assert status.installed is False
    assert status.degraded is True
    assert status.degraded_reasons == ("task_not_installed",)


def test_install_runner_contract_does_not_require_live_scheduler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    monkeypatch.setenv("SCHEDULER_TEST_SENTINEL", "retained")
    captured: dict[str, object] = {}

    def fake_runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["argv"] = argv
        captured.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    scheduler.install(
        pythonw=paths.pythonw,
        watchdog=paths.watchdog,
        config=paths.config,
        working_directory=paths.working_directory,
        runner=fake_runner,
    )

    assert captured["argv"] == list(scheduler.build_install(
        pythonw=paths.pythonw,
        watchdog=paths.watchdog,
        config=paths.config,
        working_directory=paths.working_directory,
    ).argv)
    environment = captured["env"]
    assert isinstance(environment, dict)
    assert environment["SCHEDULER_TEST_SENTINEL"] == "retained"
    for name, value in paths.environment().items():
        assert environment[name] == value
    assert captured["check"] is False
    assert captured["timeout"] == 60


def test_status_refuses_invalid_json_and_malformed_xml(tmp_path: Path) -> None:
    paths = _paths(tmp_path)

    with pytest.raises(ValueError, match="valid JSON"):
        scheduler.parse_status_output("not-json")

    status = scheduler.parse_status_output(
        _status_json(paths, result=0, xml="<Task>"), expected_paths=paths
    )
    assert status.degraded is True
    assert any(reason.startswith("task_export_invalid:") for reason in status.degraded_reasons)
