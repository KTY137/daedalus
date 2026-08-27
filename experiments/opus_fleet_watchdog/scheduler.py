"""Windows Task Scheduler adapter for the advisory Opus fleet experiment.

This module owns only the operating-system wake-up.  The scheduled action
re-enters the already registered ``tools/watchdog.py`` effect boundary; it does
not run a model or mutate a repository itself.  Command construction and task
XML inspection are pure so the contract can be tested without registering a
task on the host.

Iron Plan: EXPERIMENT (Gate 0, isolated read-only advisory workload).
"""

from __future__ import annotations

import json
import os
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence


TASK_PATH = "\\Daedalus\\"
TASK_NAME = "OpusFleet"
TASK_FULL_NAME = f"{TASK_PATH}{TASK_NAME}"

INTERVAL_MINUTES = 20
REPETITION_DURATION_DAYS = 3650
EXECUTION_LIMIT_HOURS = 2

ENV_PYTHONW = "DAEDALUS_OPUS_FLEET_PYTHONW"
ENV_WATCHDOG = "DAEDALUS_OPUS_FLEET_WATCHDOG"
ENV_CONFIG = "DAEDALUS_OPUS_FLEET_CONFIG"
ENV_WORKING_DIRECTORY = "DAEDALUS_OPUS_FLEET_WORKING_DIRECTORY"

POWERSHELL_ARGV_PREFIX = (
    "powershell.exe",
    "-NoLogo",
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy",
    "Bypass",
    "-Command",
)


# Deliberately static: caller-controlled values are read from the child
# process's environment and never interpolated into PowerShell source.
INSTALL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

function Read-RequiredProcessEnvironment([string] $Name) {
    $value = [Environment]::GetEnvironmentVariable($Name, 'Process')
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "Missing required process environment variable: $Name"
    }
    if (-not [IO.Path]::IsPathRooted($value)) {
        throw "Process environment variable must contain an absolute path: $Name"
    }
    if ($value.Contains('"')) {
        throw "Double quotes are not valid in a scheduled-task path: $Name"
    }
    return [IO.Path]::GetFullPath($value)
}

function Quote-TaskArgument([string] $Value) {
    return '"' + $Value + '"'
}

$pythonw = Read-RequiredProcessEnvironment 'DAEDALUS_OPUS_FLEET_PYTHONW'
$watchdog = Read-RequiredProcessEnvironment 'DAEDALUS_OPUS_FLEET_WATCHDOG'
$config = Read-RequiredProcessEnvironment 'DAEDALUS_OPUS_FLEET_CONFIG'
$workingDirectory = Read-RequiredProcessEnvironment 'DAEDALUS_OPUS_FLEET_WORKING_DIRECTORY'

$actionArguments = @(
    (Quote-TaskArgument $watchdog),
    'fleet',
    '--config',
    (Quote-TaskArgument $config)
) -join ' '

$action = New-ScheduledTaskAction `
    -Execute $pythonw `
    -Argument $actionArguments `
    -WorkingDirectory $workingDirectory

$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 20) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$principal = New-ScheduledTaskPrincipal `
    -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -DontStopOnIdleEnd `
    -RestartCount 0 `
    -Hidden `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

$task = New-ScheduledTask `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description 'Daedalus read-only advisory fleet wake-up (20 minute cadence)'

Register-ScheduledTask `
    -TaskName 'OpusFleet' `
    -TaskPath '\Daedalus\' `
    -InputObject $task `
    -Force | Out-Null
""".strip()


UNINSTALL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$task = Get-ScheduledTask -TaskName 'OpusFleet' -TaskPath '\Daedalus\' -ErrorAction SilentlyContinue
if ($null -ne $task) {
    Unregister-ScheduledTask -TaskName 'OpusFleet' -TaskPath '\Daedalus\' -Confirm:$false
}
""".strip()


STATUS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$task = Get-ScheduledTask -TaskName 'OpusFleet' -TaskPath '\Daedalus\' -ErrorAction SilentlyContinue
if ($null -eq $task) {
    [PSCustomObject]@{
        installed = $false
        task_name = '\Daedalus\OpusFleet'
    } | ConvertTo-Json -Compress
    exit 0
}

$info = Get-ScheduledTaskInfo -TaskName 'OpusFleet' -TaskPath '\Daedalus\'
$xml = Export-ScheduledTask -TaskName 'OpusFleet' -TaskPath '\Daedalus\'
[PSCustomObject]@{
    installed = $true
    task_name = '\Daedalus\OpusFleet'
    state = [string] $task.State
    last_task_result = [long] $info.LastTaskResult
    last_run_time = $info.LastRunTime.ToString('o')
    next_run_time = $info.NextRunTime.ToString('o')
    xml = $xml
} | ConvertTo-Json -Compress -Depth 3
""".strip()


@dataclass(frozen=True)
class SchedulerPaths:
    """Absolute paths frozen into the task action at installation time."""

    pythonw: Path
    watchdog: Path
    config: Path
    working_directory: Path

    @classmethod
    def validated(
        cls,
        *,
        pythonw: str | os.PathLike[str],
        watchdog: str | os.PathLike[str],
        config: str | os.PathLike[str],
        working_directory: str | os.PathLike[str],
    ) -> "SchedulerPaths":
        values = {
            "pythonw": _absolute_path(pythonw, "pythonw"),
            "watchdog": _absolute_path(watchdog, "watchdog"),
            "config": _absolute_path(config, "config"),
            "working_directory": _absolute_path(
                working_directory, "working_directory"
            ),
        }
        pythonw_path = values["pythonw"]
        if pythonw_path.name.casefold() not in {"pythonw", "pythonw.exe"}:
            raise ValueError("pythonw must name pythonw or pythonw.exe")

        watchdog_path = values["watchdog"]
        expected_watchdog = values["working_directory"] / "tools" / "watchdog.py"
        if watchdog_path != expected_watchdog:
            raise ValueError(
                "watchdog must be the absolute <working_directory>/tools/watchdog.py path"
            )
        return cls(**values)

    def environment(self) -> dict[str, str]:
        return {
            ENV_PYTHONW: str(self.pythonw),
            ENV_WATCHDOG: str(self.watchdog),
            ENV_CONFIG: str(self.config),
            ENV_WORKING_DIRECTORY: str(self.working_directory),
        }

    @property
    def action_arguments(self) -> str:
        return f'"{self.watchdog}" fleet --config "{self.config}"'


@dataclass(frozen=True)
class PowerShellInvocation:
    """A process invocation whose environment contains only public path data."""

    argv: tuple[str, ...]
    environment: Mapping[str, str]


@dataclass(frozen=True)
class TaskExport:
    """Security- and reliability-relevant fields from exported task XML."""

    command: str | None
    arguments: str | None
    working_directory: str | None
    repetition_interval: str | None
    repetition_duration: str | None
    logon_type: str | None
    run_level: str | None
    multiple_instances_policy: str | None
    start_when_available: bool | None
    disallow_start_if_on_batteries: bool | None
    stop_if_going_on_batteries: bool | None
    stop_on_idle_end: bool | None
    restart_count: int
    hidden: bool | None
    execution_time_limit: str | None

    def contract_violations(
        self, expected_paths: SchedulerPaths | None = None
    ) -> tuple[str, ...]:
        violations: list[str] = []

        expected_values: tuple[tuple[str, object, object], ...] = (
            ("repetition_interval", self.repetition_interval, "PT20M"),
            ("repetition_duration", self.repetition_duration, "P3650D"),
            ("logon_type", self.logon_type, "InteractiveToken"),
            ("run_level", self.run_level, "LeastPrivilege"),
            ("multiple_instances_policy", self.multiple_instances_policy, "IgnoreNew"),
            ("start_when_available", self.start_when_available, True),
            (
                "disallow_start_if_on_batteries",
                self.disallow_start_if_on_batteries,
                False,
            ),
            (
                "stop_if_going_on_batteries",
                self.stop_if_going_on_batteries,
                False,
            ),
            ("stop_on_idle_end", self.stop_on_idle_end, False),
            ("restart_count", self.restart_count, 0),
            ("hidden", self.hidden, True),
            ("execution_time_limit", self.execution_time_limit, "PT2H"),
        )
        for name, actual, expected in expected_values:
            if actual != expected:
                violations.append(f"{name}: expected {expected!r}, got {actual!r}")

        for name, value in (
            ("command", self.command),
            ("working_directory", self.working_directory),
        ):
            if not value or not Path(value).is_absolute():
                violations.append(f"{name}: expected an absolute path, got {value!r}")

        if expected_paths is not None:
            path_expectations = (
                ("command", self.command, str(expected_paths.pythonw)),
                (
                    "working_directory",
                    self.working_directory,
                    str(expected_paths.working_directory),
                ),
                ("arguments", self.arguments, expected_paths.action_arguments),
            )
            for name, actual, expected in path_expectations:
                if actual != expected:
                    violations.append(
                        f"{name}: expected {expected!r}, got {actual!r}"
                    )

        return tuple(violations)


@dataclass(frozen=True)
class SchedulerStatus:
    installed: bool
    state: str | None
    last_task_result: int | None
    last_run_time: str | None
    next_run_time: str | None
    exported_task: TaskExport | None
    degraded_reasons: tuple[str, ...]

    @property
    def degraded(self) -> bool:
        return bool(self.degraded_reasons)


class SchedulerCommandError(RuntimeError):
    """PowerShell could not complete a scheduler operation."""


def _absolute_path(value: str | os.PathLike[str], label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{label} must be an absolute path")
    if '"' in str(path):
        raise ValueError(f'{label} cannot contain a double quote (\")')
    return path.resolve(strict=False)


def build_install(
    *,
    pythonw: str | os.PathLike[str],
    watchdog: str | os.PathLike[str],
    config: str | os.PathLike[str],
    working_directory: str | os.PathLike[str],
) -> PowerShellInvocation:
    """Build (but do not execute) the idempotent task registration call."""

    paths = SchedulerPaths.validated(
        pythonw=pythonw,
        watchdog=watchdog,
        config=config,
        working_directory=working_directory,
    )
    return PowerShellInvocation(
        argv=(*POWERSHELL_ARGV_PREFIX, INSTALL_SCRIPT),
        environment=paths.environment(),
    )


def build_uninstall() -> PowerShellInvocation:
    """Build (but do not execute) the idempotent task removal call."""

    return PowerShellInvocation(
        argv=(*POWERSHELL_ARGV_PREFIX, UNINSTALL_SCRIPT),
        environment={},
    )


def build_status() -> PowerShellInvocation:
    """Build (but do not execute) the task status/export call."""

    return PowerShellInvocation(
        argv=(*POWERSHELL_ARGV_PREFIX, STATUS_SCRIPT),
        environment={},
    )


def install(
    *,
    pythonw: str | os.PathLike[str],
    watchdog: str | os.PathLike[str],
    config: str | os.PathLike[str],
    working_directory: str | os.PathLike[str],
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    """Register or replace the single per-user advisory fleet task."""

    invocation = build_install(
        pythonw=pythonw,
        watchdog=watchdog,
        config=config,
        working_directory=working_directory,
    )
    _run_checked(invocation, runner=runner)


def uninstall(
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    """Remove the advisory fleet task if it exists."""

    _run_checked(build_uninstall(), runner=runner)


def status(
    *,
    expected_paths: SchedulerPaths | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> SchedulerStatus:
    """Return current task health and exported-contract drift."""

    completed = _run_checked(build_status(), runner=runner)
    return parse_status_output(completed.stdout, expected_paths=expected_paths)


def _run_checked(
    invocation: PowerShellInvocation,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(invocation.environment)
    completed = runner(
        list(invocation.argv),
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown PowerShell error").strip()
        raise SchedulerCommandError(detail)
    return completed


def parse_status_output(
    output: str, *, expected_paths: SchedulerPaths | None = None
) -> SchedulerStatus:
    """Parse the JSON emitted by :data:`STATUS_SCRIPT` and grade health."""

    try:
        payload = json.loads(output)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("scheduler status output is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("scheduler status output must be a JSON object")

    installed = bool(payload.get("installed", False))
    if not installed:
        return SchedulerStatus(
            installed=False,
            state=None,
            last_task_result=None,
            last_run_time=None,
            next_run_time=None,
            exported_task=None,
            degraded_reasons=("task_not_installed",),
        )

    reasons: list[str] = []
    try:
        last_task_result = int(payload["last_task_result"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("installed task status lacks an integer LastTaskResult") from exc
    if last_task_result != 0:
        reasons.append(f"last_task_result:{last_task_result}")

    xml = payload.get("xml")
    exported_task: TaskExport | None = None
    if not isinstance(xml, str) or not xml.strip():
        reasons.append("task_export_missing")
    else:
        try:
            exported_task = parse_exported_task_xml(xml)
        except ValueError as exc:
            reasons.append(f"task_export_invalid:{exc}")
        else:
            reasons.extend(exported_task.contract_violations(expected_paths))

    return SchedulerStatus(
        installed=True,
        state=_optional_string(payload.get("state")),
        last_task_result=last_task_result,
        last_run_time=_optional_string(payload.get("last_run_time")),
        next_run_time=_optional_string(payload.get("next_run_time")),
        exported_task=exported_task,
        degraded_reasons=tuple(reasons),
    )


def parse_exported_task_xml(xml: str) -> TaskExport:
    """Extract the task contract from Windows Task Scheduler XML."""

    try:
        root = ET.fromstring(xml)
    except (TypeError, ET.ParseError) as exc:
        raise ValueError("malformed scheduled-task XML") from exc

    namespace = ""
    if root.tag.startswith("{"):
        namespace = root.tag[1:].split("}", 1)[0]
    prefix = f"{{{namespace}}}" if namespace else ""

    def text_at(*parts: str) -> str | None:
        node = root.find("./" + "/".join(prefix + part for part in parts))
        if node is None or node.text is None:
            return None
        value = node.text.strip()
        return value or None

    restart_count_text = text_at("Settings", "RestartOnFailure", "Count")
    try:
        restart_count = int(restart_count_text) if restart_count_text else 0
    except ValueError:
        restart_count = -1

    return TaskExport(
        command=text_at("Actions", "Exec", "Command"),
        arguments=text_at("Actions", "Exec", "Arguments"),
        working_directory=text_at("Actions", "Exec", "WorkingDirectory"),
        repetition_interval=text_at(
            "Triggers", "TimeTrigger", "Repetition", "Interval"
        ),
        repetition_duration=text_at(
            "Triggers", "TimeTrigger", "Repetition", "Duration"
        ),
        logon_type=text_at("Principals", "Principal", "LogonType"),
        run_level=text_at("Principals", "Principal", "RunLevel"),
        multiple_instances_policy=text_at("Settings", "MultipleInstancesPolicy"),
        start_when_available=_xml_bool(text_at("Settings", "StartWhenAvailable")),
        disallow_start_if_on_batteries=_xml_bool(
            text_at("Settings", "DisallowStartIfOnBatteries")
        ),
        stop_if_going_on_batteries=_xml_bool(
            text_at("Settings", "StopIfGoingOnBatteries")
        ),
        stop_on_idle_end=_xml_bool(
            text_at("Settings", "IdleSettings", "StopOnIdleEnd")
        ),
        restart_count=restart_count,
        hidden=_xml_bool(text_at("Settings", "Hidden")),
        execution_time_limit=text_at("Settings", "ExecutionTimeLimit"),
    )


def _xml_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    return None


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


__all__: Sequence[str] = (
    "ENV_CONFIG",
    "ENV_PYTHONW",
    "ENV_WATCHDOG",
    "ENV_WORKING_DIRECTORY",
    "EXECUTION_LIMIT_HOURS",
    "INSTALL_SCRIPT",
    "INTERVAL_MINUTES",
    "PowerShellInvocation",
    "REPETITION_DURATION_DAYS",
    "STATUS_SCRIPT",
    "SchedulerCommandError",
    "SchedulerPaths",
    "SchedulerStatus",
    "TASK_FULL_NAME",
    "TASK_NAME",
    "TASK_PATH",
    "TaskExport",
    "UNINSTALL_SCRIPT",
    "build_install",
    "build_status",
    "build_uninstall",
    "install",
    "parse_exported_task_xml",
    "parse_status_output",
    "status",
    "uninstall",
)
