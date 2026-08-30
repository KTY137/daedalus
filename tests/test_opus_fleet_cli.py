# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "watchdog_fleet_cli", ROOT / "tools" / "watchdog.py"
)
assert SPEC and SPEC.loader
wd = importlib.util.module_from_spec(SPEC)
sys.modules["watchdog_fleet_cli"] = wd  # dataclasses under `from __future__ import annotations` need the module registered
SPEC.loader.exec_module(wd)


def test_fleet_config_path_defaults_to_repo_and_rejects_bad_option(tmp_path: Path) -> None:
    assert wd.fleet_config_path(tmp_path, ["fleet"]) == (
        tmp_path / wd.FLEET_CONFIG_REL
    ).resolve()
    assert wd.fleet_config_path(
        tmp_path, ["fleet", "--config", "campaign.json"]
    ) == (tmp_path / "campaign.json").resolve()

    with pytest.raises(ValueError, match="requires a value"):
        wd.fleet_config_path(tmp_path, ["fleet", "--config"])
    with pytest.raises(ValueError, match="only once"):
        wd.fleet_config_path(
            tmp_path,
            ["fleet", "--config", "a.json", "--config", "b.json"],
        )


def test_live_fleet_injects_the_real_session_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import experiments.opus_fleet_watchdog as package
    from experiments.opus_fleet_watchdog import session_probe as probe_module

    sentinel = lambda: {"ok": True, "active_sessions": 0, "sources": []}
    captured: dict[str, object] = {}

    def fake_run(config: Path, *, session_probe):
        captured["config"] = config
        captured["probe"] = session_probe
        return {"status": "waiting", "reason": "active_sessions_present"}

    monkeypatch.setattr(probe_module, "fleet_session_probe", sentinel)
    monkeypatch.setattr(package, "run_campaign", fake_run)
    config = tmp_path / "fleet.json"

    assert wd.fleet_command(tmp_path, "fleet", config=config) == 0
    assert captured == {"config": config, "probe": sentinel}
    assert json.loads(capsys.readouterr().out)["status"] == "waiting"


@pytest.mark.parametrize(
    "result,expected",
    [
        ({"status": "complete", "reason": ""}, 0),
        ({"status": "degraded", "reason": "provider_failed"}, 1),
        (
            {"status": "waiting", "reason": "session_probe_error:timeout"},
            3,
        ),
    ],
)
def test_fleet_exit_code_preserves_expected_idle_and_failure_states(
    result: dict,
    expected: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import experiments.opus_fleet_watchdog as package

    monkeypatch.setattr(package, "run_campaign", lambda *_a, **_kw: result)
    assert wd.fleet_command(tmp_path, "fleet", config=tmp_path / "x.json") == expected
    capsys.readouterr()


def test_fleet_dry_run_never_dispatches_or_checks_sessions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import experiments.opus_fleet_watchdog as package

    plan = {"campaign_id": "dry", "plan_digest": "abc", "slots": []}
    monkeypatch.setattr(package, "dry_plan", lambda *_a, **_kw: plan)
    monkeypatch.setattr(
        package,
        "run_campaign",
        lambda *_a, **_kw: pytest.fail("dry fleet dispatched"),
    )

    assert wd.fleet_command(
        tmp_path, "fleet", config=tmp_path / "x.json", dry=True
    ) == 0
    assert json.loads(capsys.readouterr().out) == plan


def test_dry_install_and_uninstall_do_not_mutate_task_scheduler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import experiments.opus_fleet_watchdog as package
    from experiments.opus_fleet_watchdog import scheduler

    root = (tmp_path / "repo").resolve()
    config = root / ".claude" / "watchdog" / "fleet.json"
    pythonw = (tmp_path / "runtime" / "pythonw.exe").resolve()
    monkeypatch.setattr(wd, "_pythonw", lambda: str(pythonw))
    monkeypatch.setattr(package, "dry_plan", lambda *_a, **_kw: {"plan_digest": "abc"})
    monkeypatch.setattr(
        scheduler, "install", lambda **_kw: pytest.fail("dry install mutated task")
    )
    monkeypatch.setattr(
        scheduler, "uninstall", lambda **_kw: pytest.fail("dry uninstall mutated task")
    )

    assert wd.fleet_command(root, "fleet-install", config=config, dry=True) == 0
    install = json.loads(capsys.readouterr().out)
    assert install["action"] == "would_install"
    assert install["task"] == scheduler.TASK_FULL_NAME
    assert " fleet --config " in install["arguments"]

    monkeypatch.setattr(
        wd,
        "_fleet_scheduler_paths",
        lambda *_a, **_kw: pytest.fail("uninstall does not need runtime paths"),
    )
    assert wd.fleet_command(root, "fleet-uninstall", config=config, dry=True) == 0
    uninstall = json.loads(capsys.readouterr().out)
    assert uninstall["action"] == "would_uninstall"

