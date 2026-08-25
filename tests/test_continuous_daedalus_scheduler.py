from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "continuous_daedalus.ps1"


def _text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _section(text: str, start: str, end: str) -> str:
    before, marker, remainder = text.partition(start)
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
        pattern = rf"\[[^\]]+\]\s*\r?\n\s*\[[^\]]+\]\s*\r?\n\s*\[(?:int|double)\]\${name}\s*=\s*{re.escape(value)}"
        if name in {"IntervalMinutes", "MaxIterations", "MaxWallClockSeconds", "QueueLimit"}:
            assert re.search(pattern, text), f"default {name}={value} is not pinned"
        else:
            assert f"]${name} = {value}" in text

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
