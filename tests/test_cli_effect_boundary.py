"""Gate-0 central-boundary probes for the wired cli.* family.

Each wired CLI main must refuse fail-closed -- no output artifact, no state
write -- when the central boundary cannot accept the start, and must run on
the valid chain with the real budget.process_guard decision.  Deleting the
begin_effect call in any wired main turns its refusal probe red, so these
are also the family's mutation probes.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from daedalus.spine import effect_boundary
from daedalus.spine.effect_boundary import EffectStartRefused


@pytest.fixture
def contracts_disabled(monkeypatch):
    monkeypatch.setattr(
        effect_boundary,
        "GUARD_CONTRACT_IMPLEMENTED",
        {name: False for name in effect_boundary.GUARD_CONTRACT_IMPLEMENTED},
    )


def _target_repo(tmp_path: Path) -> Path:
    root = tmp_path / "target"
    root.mkdir()
    return root


def test_enforce_refuses_fail_closed_without_the_contract(
    tmp_path, monkeypatch, contracts_disabled
):
    from daedalus.enforce import main

    root = _target_repo(tmp_path)
    monkeypatch.setattr("sys.argv", ["enforce", "--repo-root", str(root)])
    with pytest.raises(EffectStartRefused):
        main()
    assert not (root / "AGENTS.md").exists(), (
        "a refused start must not have written harness instructions"
    )


def test_enforce_runs_on_the_valid_chain(tmp_path, monkeypatch, capsys):
    from daedalus.enforce import main

    root = _target_repo(tmp_path)
    monkeypatch.setattr("sys.argv", ["enforce", "--repo-root", str(root)])
    main()
    out = json.loads(capsys.readouterr().out)
    assert out["enforced"] is True
    assert (root / "AGENTS.md").exists()


def test_gui_lint_refuses_fail_closed_without_the_contract(
    tmp_path, monkeypatch, contracts_disabled
):
    from daedalus.gui.lint import main

    capture = tmp_path / "capture.json"
    capture.write_text(json.dumps({"page": "x", "issues": []}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(EffectStartRefused):
        main([str(capture)])
    assert not (tmp_path / "runs" / "gui" / "report.json").exists()


def test_runbook_refuses_fail_closed_without_the_contract(
    tmp_path, monkeypatch, contracts_disabled
):
    from daedalus import runbook

    monkeypatch.setattr(runbook, "RUN_DIR", tmp_path / "runs")
    monkeypatch.setattr(
        "sys.argv", ["runbook", "objective", "--repo-root", str(tmp_path)]
    )
    with pytest.raises(EffectStartRefused):
        runbook.main()
    assert not (tmp_path / "runs").exists()


def test_selftest_refuses_fail_closed_before_any_live_round_trip(
    monkeypatch, contracts_disabled
):
    from daedalus import selftest

    def _exploded(*_a, **_kw):  # pragma: no cover - must never run
        raise AssertionError("run() must not start after a refused boundary")

    monkeypatch.setattr(selftest, "run", _exploded)
    with pytest.raises(EffectStartRefused):
        selftest.main([])


def test_shift_status_stays_fail_open_read_only(contracts_disabled, capsys):
    from daedalus.shift import main

    assert main(["status"]) == 0
    assert capsys.readouterr().out.strip(), "status inspection must keep working"


def test_shift_state_writes_refuse_fail_closed(contracts_disabled):
    from daedalus.shift import main

    with pytest.raises(EffectStartRefused):
        main(["note", "probe"])


def test_structcore_json_write_refuses_but_summary_stays_fail_open(
    tmp_path, monkeypatch, contracts_disabled, capsys
):
    from daedalus.structcore.__main__ import main

    repo = _target_repo(tmp_path)
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    out = tmp_path / "index.json"
    with pytest.raises(EffectStartRefused):
        main([str(repo), "--json", str(out)])
    assert not out.exists()
    # read-only inspection path unaffected by the disabled contract
    assert main([str(repo)]) == 0


def test_structcore_slice_write_refuses_fail_closed(
    tmp_path, contracts_disabled
):
    from daedalus.structcore.slice import main

    repo = _target_repo(tmp_path)
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    out = tmp_path / "slice.txt"
    with pytest.raises(EffectStartRefused):
        main([str(repo), "a.py", "--out", str(out)])
    assert not out.exists()


def test_token_monitor_refuses_fail_closed_without_the_contract(
    tmp_path, monkeypatch, contracts_disabled
):
    from daedalus.token_monitor import main

    root = _target_repo(tmp_path)
    monkeypatch.setattr(
        "sys.argv", ["token_monitor", "--repo-root", str(root)]
    )
    with pytest.raises(EffectStartRefused):
        main()


def test_the_valid_chain_mints_a_real_process_guard_decision(tmp_path, monkeypatch):
    """The family decision is the executed contract, not an assertion."""
    import daedalus.budget as budget
    from daedalus.enforce import main

    root = _target_repo(tmp_path)
    monkeypatch.setattr("sys.argv", ["enforce", "--repo-root", str(root)])
    try:
        main()
        import subprocess

        assert getattr(subprocess.run, "__daedalus_budget__", False), (
            "the spend net must actually be installed by the boundary decision"
        )
    finally:
        budget.uninstall_process_guard()
    assert (root / "AGENTS.md").exists()
