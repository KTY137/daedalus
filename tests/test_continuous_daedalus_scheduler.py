from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "continuous_daedalus.ps1"


def _text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _section(text: str, start: str, end: str) -> str:
    _, marker, remainder = text.partition(start)
    assert marker, f"missing section start: {start}"
    body, marker, _ = remainder.partition(end)
    assert marker, f"missing section end: {end}"
    return body


def test_scheduled_action_uses_only_the_bounded_canonical_loop() -> None:
    text = _text()
    builder = _section(
        text,
        "function New-LoopArgumentString",
        "function Invoke-DaedalusModule",
    )

    assert "'daedalus.loop'" in builder
    for flag in (
        "--repo-root",
        "--max-iterations",
        "--max-wall-clock-s",
        "--max-spend-usd",
        "--max-attempts-per-candidate",
        "--queue-limit",
        "--json",
        "--arm",
    ):
        assert flag in builder

    # A scheduled run may use the normal non-forcing arm operation. It must
    # never override a prior human stop or acquire merge/promotion authority.
    lowered = builder.lower()
    assert "--force" not in lowered
    assert "promote" not in lowered
    assert "merge" not in lowered
    assert "git push" not in lowered


def test_default_run_is_small_and_finitely_bounded() -> None:
    text = _text()
    defaults = {
        "IntervalMinutes": "60",
        "MaxIterations": "3",
        "MaxWallClockSeconds": "1500",
        "MaxSpendUsd": "1.00",
        "MaxAttemptsPerCandidate": "1",
        "QueueLimit": "25",
    }
    for name, value in defaults.items():
        pattern = rf"\[(?:int|double)\]\${name}\s*=\s*{re.escape(value)}"
        assert re.search(pattern, text), f"default {name}={value} is not pinned"

    assert "New-TimeSpan -Days 7300" in text
    assert "($MaxWallClockSeconds + 300)" in text


def test_task_is_limited_interactive_and_non_overlapping() -> None:
    text = _text()
    assert "-MultipleInstances IgnoreNew" in text
    assert "-RunLevel Limited" in text
    assert "-LogonType Interactive" in text
    assert "-StartWhenAvailable" in text
    assert "-ExecutionTimeLimit" in text
    assert "-RunLevel Highest" not in text
    assert "-UserId 'SYSTEM'" not in text
    assert "-MultipleInstances Parallel" not in text


def test_install_refuses_rid500_before_arming_or_task_writes() -> None:
    text = _text()
    install = _section(text, "    'Install' {", "    'Uninstall' {")

    assert "Assert-SupportedTaskPrincipal" in text
    assert "AccountAdministratorSid" in text
    assert "RID 500" in text
    assert "RunLevel=Limited" in text
    assert "0x80070005" in text
    assert "No kill-switch or Task Scheduler state was changed" in text
    assert install.index("Assert-SupportedTaskPrincipal") < install.index("$armArgs")
    assert install.index("Assert-SupportedTaskPrincipal") < install.index(
        "Register-ScheduledTask"
    )
    assert install.index("$task = New-ScheduledTask") < install.index("$armArgs")
    assert install.index("$armArgs") < install.index("Register-ScheduledTask")

    # UAC cannot repair the semantic defect: Windows ignores Limited for the
    # built-in Administrator. The script must refuse, not self-elevate.
    assert "-Verb RunAs" not in text


def test_registration_failure_is_fail_closed() -> None:
    install = _section(_text(), "    'Install' {", "    'Uninstall' {")
    registration = _section(
        install,
        "        try {\n            Register-ScheduledTask",
        "        Write-Host \"Installed $FullTaskName\"",
    )

    assert "continuous task registration failed" in registration
    assert "daedalus.spine.killswitch', 'stop'" in registration
    assert "the loop was left" in registration
    assert "STOPPED" in registration


def test_native_subprocess_wrapper_returns_only_the_integer_exit_code() -> None:
    text = _text()
    wrapper = _section(
        text,
        "function Invoke-DaedalusModule",
        "function Get-TaskOrNull",
    )
    assert "$output = & $PythonPath @Arguments 2>&1" in wrapper
    assert "$exitCode = $LASTEXITCODE" in wrapper
    assert "Write-Host $line" in wrapper
    assert "return [int]$exitCode" in wrapper

    # Partial WhatIf semantics would be dangerous here: an earlier version
    # could arm the kill switch while only simulating task registration.
    assert "SupportsShouldProcess" not in text
    assert "$PSCmdlet.ShouldProcess" not in text


def test_human_stop_is_sticky_and_uninstall_stops_before_exit() -> None:
    text = _text()
    assert "daedalus.spine.killswitch', 'stop'" in text
    assert "Stop-ScheduledTask" in text
    assert "Unregister-ScheduledTask" in text
    assert "A sticky human stop remains authoritative" in text

    # Force-rearming exists only as an explicit operator switch. The scheduled
    # argument builder above is separately proven not to contain --force.
    assert "[switch]$ForceRearm" in text
    assert "if ($ForceRearm)" in text
    assert "$armArgs += '--force'" in text


def test_scheduler_does_not_contain_repository_mutation_commands() -> None:
    lowered = _text().lower()
    forbidden = (
        "git merge",
        "git push",
        "git reset --hard",
        "promote_candidates",
        "ownerapproval",
        "promotionreceipt",
        "--no-verify",
    )
    for token in forbidden:
        assert token not in lowered


def test_operator_docs_name_the_supported_windows_principal() -> None:
    docs = (ROOT / "docs" / "CONTINUOUS_DAEDALUS.md").read_text(
        encoding="utf-8"
    )
    assert "built-in Windows `Administrator` account (RID 500)" in docs
    assert "Windows ignores `RunLevel=Limited`" in docs
    assert "before arming the kill switch" in docs
    assert "`Status` and" in docs and "`Stop` remain ordinary-shell" in docs
