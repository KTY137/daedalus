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


def test_generic_scheduled_action_still_uses_the_bounded_canonical_loop() -> None:
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
    lowered = builder.lower()
    assert "--force" not in lowered
    assert "git push" not in lowered
    assert "promote_candidates" not in lowered


def test_campaign_action_uses_only_the_small_guard_and_same_scheduler() -> None:
    text = _text()
    builder = _section(
        text,
        "function New-LoopArgumentString",
        "function Invoke-DaedalusModule",
    )
    assert "tools\\gardener_campaign.py" in builder
    assert "'run'" in builder
    assert "'--campaign'" in builder
    assert "'--repo-root'" in builder
    assert "Register-ScheduledTask" not in builder
    assert "New-ScheduledTask" not in builder

    # Python does not own another scheduler. Task registration remains here.
    guard = (ROOT / "tools" / "gardener_campaign.py").read_text(encoding="utf-8")
    for forbidden in ("Register-ScheduledTask", "New-ScheduledTask", "schtasks.exe"):
        assert forbidden not in guard


def test_default_generic_run_remains_small_and_finitely_bounded() -> None:
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
    assert "$executionLimit = $MaxWallClockSeconds + 300" in text


def test_task_is_limited_interactive_non_overlapping_and_user_named() -> None:
    text = _text()
    assert "$TaskPath = '\\Daedalus\\'" in text
    assert "$TaskName = $ScheduledTaskName" in text
    assert "ValidatePattern('^[A-Za-z0-9._-]{1,100}$')" in text
    assert "-MultipleInstances IgnoreNew" in text
    assert "-RunLevel Limited" in text
    assert "-LogonType Interactive" in text
    assert "-StartWhenAvailable" in text
    assert "-ExecutionTimeLimit" in text
    assert "-RunLevel Highest" not in text
    assert "-UserId 'SYSTEM'" not in text
    assert "-MultipleInstances Parallel" not in text


def test_campaign_file_is_confined_and_validated_before_registration() -> None:
    text = _text()
    resolver = _section(text, "function Resolve-Campaign", "function Quote-TaskArgument")
    assert "[System.IO.Path]::IsPathRooted" in resolver
    assert "Join-Path $Root $candidate" in resolver
    assert "CampaignFile must remain inside RepoRoot" in resolver
    assert "daedalus-gardener-campaign/1" in resolver
    assert "Europe/Berlin" in resolver
    assert "work_until_date_exclusive" in resolver
    assert "final_report_date" in resolver
    assert "interval is outside 15..1440" in resolver
    assert "wall-clock bound is outside 60..7200" in resolver

    install = _section(text, "    'Install' {", "    'Uninstall' {")
    guard_position = install.index("$guardExit")
    arm_position = install.index("$armArgs")
    register_position = install.index("Register-ScheduledTask")
    assert guard_position < arm_position < register_position
    assert "Campaign guard refused installation" in install


def test_campaign_cutoff_is_berlin_midnight_with_distinct_final_trigger() -> None:
    text = _text()
    converter = _section(
        text,
        "function Convert-BerlinDateToLocalTime",
        "function Resolve-Campaign",
    )
    assert "W. Europe Standard Time" in text
    assert "ConvertTimeToUtc" in converter
    assert "ToLocalTime" in converter

    install = _section(text, "    'Install' {", "    'Uninstall' {")
    assert "$ResolvedCampaign.CutoffLocal -le (Get-Date)" in install
    assert "$final = New-ScheduledTaskTrigger -Once -At $ResolvedCampaign.CutoffLocal" in install
    assert "$triggers = @($repeat, $final)" in install
    assert "Campaign cutoff:" in install
    assert "00:00 Europe/Berlin" in install


def test_campaign_run_once_and_status_enter_through_guard() -> None:
    text = _text()
    status = _section(text, "    'Status' {", "    'RunOnce' {")
    run_once = _section(text, "    'RunOnce' {", "    'Start' {")
    for body in (status, run_once):
        assert "tools\\gardener_campaign.py" in body
        assert "--campaign" in body
        assert "--repo-root" in body
    assert "'status'" in status
    assert "'run'" in run_once


def test_native_subprocess_wrapper_returns_only_integer_exit_code() -> None:
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
    assert "SupportsShouldProcess" not in text
    assert "$PSCmdlet.ShouldProcess" not in text


def test_human_stop_is_sticky_and_uninstall_stops_before_exit() -> None:
    text = _text()
    assert "daedalus.spine.killswitch', 'stop'" in text
    assert "Stop-ScheduledTask" in text
    assert "Unregister-ScheduledTask" in text
    assert "A sticky human stop remains authoritative" in text
    assert "[switch]$ForceRearm" in text
    assert "if ($ForceRearm)" in text
    assert "$armArgs += '--force'" in text

    builder = _section(
        text,
        "function New-LoopArgumentString",
        "function Invoke-DaedalusModule",
    )
    assert "--force" not in builder


def test_scheduler_does_not_contain_repository_mutation_or_promotion_commands() -> None:
    lowered = _text().lower()
    for token in (
        "git merge",
        "git push",
        "git reset --hard",
        "promote_candidates",
        "ownerapproval",
        "promotionreceipt",
        "--no-verify",
    ):
        assert token not in lowered
