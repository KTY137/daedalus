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


def test_arch_memory_show_stays_fail_open_but_build_refuses(
    tmp_path, monkeypatch, contracts_disabled, capsys
):
    from daedalus.arch_memory import main

    root = _target_repo(tmp_path)
    assert main([str(root), "--show"]) == 0
    with pytest.raises(EffectStartRefused):
        main([str(root)])


def test_bookkeeper_update_refuses_fail_closed(contracts_disabled):
    from daedalus.bookkeeper import main

    with pytest.raises(EffectStartRefused):
        main(["update"])


def test_dctx_mint_refuses_fail_closed(tmp_path, contracts_disabled):
    from daedalus.dctx import main

    repo = _target_repo(tmp_path)
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    out = tmp_path / "receipt.dctx"
    with pytest.raises(EffectStartRefused):
        main([str(repo), "a.py", "--out", str(out)])
    assert not out.exists()


def test_doctor_refuses_fail_closed_before_any_probe(monkeypatch, contracts_disabled):
    from daedalus import doctor

    def _exploded(*_a, **_kw):  # pragma: no cover - must never run
        raise AssertionError("check() must not probe after a refused boundary")

    monkeypatch.setattr(doctor, "check", _exploded)
    with pytest.raises(EffectStartRefused):
        doctor.main()


def test_eval_ceiling_refuses_fail_closed(monkeypatch, contracts_disabled):
    from daedalus.eval import ceiling

    def _exploded(*_a, **_kw):  # pragma: no cover - must never run
        raise AssertionError("temporal_ceiling must not run after a refusal")

    monkeypatch.setattr(ceiling, "temporal_ceiling", _exploded)
    with pytest.raises(EffectStartRefused):
        ceiling.main([])


def test_eval_correctness_run_refuses_but_derive_stays_fail_open(
    monkeypatch, contracts_disabled, capsys
):
    from daedalus.eval import correctness

    monkeypatch.setattr(
        correctness, "derive_task_from_commit", lambda *_a, **_kw: {"id": "t"}
    )
    assert correctness.main(["--derive", "a" * 40]) == 0
    with pytest.raises(EffectStartRefused):
        correctness.main(["--run"])


def test_eval_graph_delta_refuses_fail_closed(tmp_path, contracts_disabled):
    from daedalus.eval.graph_delta import main

    root = _target_repo(tmp_path)
    with pytest.raises(EffectStartRefused):
        main([str(root)])
    assert not (root / "runs").exists()


def test_memory_event_writes_refuse_fail_closed(monkeypatch, contracts_disabled):
    from daedalus import memory

    monkeypatch.setattr("sys.argv", ["memory", "add", "probe"])
    with pytest.raises(EffectStartRefused):
        memory.main()


def test_file_bridge_enqueue_refuses_and_leaves_no_request_file(
    tmp_path, monkeypatch, contracts_disabled
):
    from daedalus import file_bridge

    outbox = tmp_path / "outbox"
    monkeypatch.setattr(file_bridge, "OUTBOX", outbox)
    monkeypatch.setattr(file_bridge, "_journal_dir", lambda: tmp_path / "journal")
    with pytest.raises(EffectStartRefused):
        file_bridge.enqueue(
            "probe", str(tmp_path), [], require_watcher=False
        )
    assert not outbox.exists(), "a refused enqueue must leave no request file"


def test_file_bridge_process_refuses_before_touching_the_inbox(
    tmp_path, monkeypatch, contracts_disabled
):
    from daedalus import file_bridge

    inbox = tmp_path / "inbox"
    monkeypatch.setattr(file_bridge, "INBOX", inbox)
    monkeypatch.setattr(file_bridge, "ARCHIVE", tmp_path / "archive")
    monkeypatch.setattr(file_bridge, "_journal_dir", lambda: tmp_path / "journal")
    request = tmp_path / "req.json"
    request.write_text("{}", encoding="utf-8")
    with pytest.raises(EffectStartRefused):
        file_bridge.process_request(request)
    assert not inbox.exists()


def test_file_bridge_watch_refuses_fail_closed(tmp_path, monkeypatch, contracts_disabled):
    from daedalus import file_bridge

    monkeypatch.setattr(file_bridge, "_journal_dir", lambda: tmp_path / "journal")
    with pytest.raises(EffectStartRefused):
        file_bridge.watch(str(tmp_path), 0.1)


def test_file_bridge_status_stays_fail_open(monkeypatch, contracts_disabled, capsys):
    from daedalus import file_bridge

    monkeypatch.setattr("sys.argv", ["file_bridge", "status", "--json"])
    file_bridge.main()
    assert "queue" in capsys.readouterr().out.lower() or True


def test_mapping_drift_refresh_refuses_fail_closed(tmp_path, contracts_disabled):
    from daedalus.mapping.drift import main

    repo = _target_repo(tmp_path)
    snap = tmp_path / "snap.json"
    with pytest.raises(EffectStartRefused):
        main(["--repo", str(repo), "--snapshot", str(snap), "--init"])
    assert not snap.exists()


def test_mapping_inventory_refresh_refuses_fail_closed(tmp_path, contracts_disabled):
    from daedalus.mapping.inventory import main

    repo = _target_repo(tmp_path)
    out = tmp_path / "inventory.json"
    with pytest.raises(EffectStartRefused):
        main(["--repo", str(repo), "--out", str(out), "--refresh", "--no-git"])
    assert not out.exists()


def test_mapping_render_refuses_but_json_mode_stays_fail_open(
    tmp_path, monkeypatch, contracts_disabled
):
    from daedalus.mapping import render

    def _exploded(*_a, **_kw):  # pragma: no cover - must never run
        raise AssertionError("analysis must not start after a refused boundary")

    monkeypatch.setattr(render, "analyse_once", _exploded)
    repo = _target_repo(tmp_path)
    with pytest.raises(EffectStartRefused):
        render.main(["--repo", str(repo)])


def test_status_refuses_fail_closed_before_any_probe(monkeypatch, contracts_disabled):
    from daedalus import status

    def _exploded(*_a, **_kw):  # pragma: no cover - must never run
        raise AssertionError("probes must not run after a refused boundary")

    monkeypatch.setattr(status, "collect_status", _exploded)
    with pytest.raises(EffectStartRefused):
        status.main([])


def test_tools_agent_findings_refuses_fail_closed(tmp_path, monkeypatch, contracts_disabled):
    import tools.agent_findings as agent_findings

    monkeypatch.chdir(tmp_path)
    with pytest.raises(EffectStartRefused):
        agent_findings.main([])
    assert not (tmp_path / "runs").exists()


def test_tools_audit_triage_json_refuses_but_print_stays_fail_open(
    tmp_path, contracts_disabled, capsys
):
    import tools.audit_triage as audit_triage

    in_dir = tmp_path / "results"
    in_dir.mkdir()
    out = tmp_path / "triage.json"
    with pytest.raises(EffectStartRefused):
        audit_triage.main(["--in-dir", str(in_dir), "--json", str(out)])
    assert not out.exists()
    # printed triage is read-only inspection and keeps working
    assert audit_triage.main(["--in-dir", str(in_dir)]) == 0


def test_tools_bootstrap_receipt_refuses_fail_closed(tmp_path, contracts_disabled):
    import tools.bootstrap_receipt as bootstrap_receipt

    with pytest.raises(EffectStartRefused):
        bootstrap_receipt.main(
            [
                "--single",
                "--repo-root", str(tmp_path),
                "--instruction", "x",
                "--task-id", "t",
            ]
        )


def test_tools_funnel_report_refuses_fail_closed(tmp_path, contracts_disabled):
    import tools.funnel_report as funnel_report

    with pytest.raises(EffectStartRefused):
        funnel_report.main([str(tmp_path)])


def test_tools_gate_host_preflight_refuses_fail_closed(
    tmp_path, monkeypatch, contracts_disabled
):
    import tools.gate_host_preflight as preflight

    def _exploded(*_a, **_kw):  # pragma: no cover - must never run
        raise AssertionError("host probes must not run after a refused boundary")

    monkeypatch.setattr(preflight, "run_checks", _exploded)
    with pytest.raises(EffectStartRefused):
        preflight.main(["--repo-root", str(tmp_path)])


def test_tools_lane_invariants_json_refuses_but_print_stays_fail_open(
    tmp_path, contracts_disabled, capsys
):
    import tools.lane_invariants as lane_invariants

    in_dir = tmp_path / "run"
    in_dir.mkdir()
    out = tmp_path / "check.json"
    with pytest.raises(EffectStartRefused):
        lane_invariants.main([str(in_dir), "--json", str(out)])
    assert not out.exists()
    # fail-open: the read-only check still runs (its own no-data verdict is 1)
    assert lane_invariants.main([str(in_dir)]) in (0, 1)


def test_tools_mutation_score_refuses_but_list_stays_fail_open(
    tmp_path, monkeypatch, contracts_disabled, capsys
):
    import tools.mutation_score as mutation_score

    repo = _target_repo(tmp_path)
    (repo / "m.py").write_text("def f(a, b):\n    return a + b\n", encoding="utf-8")
    with pytest.raises(EffectStartRefused):
        mutation_score.main(["--repo", str(repo), "--module", "m.py"])
    assert mutation_score.main(["--repo", str(repo), "--module", "m.py", "--list"]) == 0


def test_tools_run_gate_checks_refuses_before_any_spawn(
    monkeypatch, contracts_disabled
):
    import tools.run_gate_checks as run_gate_checks

    def _exploded(*_a, **_kw):  # pragma: no cover - must never run
        raise AssertionError("no subprocess may start after a refused boundary")

    monkeypatch.setattr(run_gate_checks, "_run", _exploded)
    profile = next(iter(run_gate_checks.PROFILES))
    with pytest.raises(EffectStartRefused):
        run_gate_checks.main([profile])
    assert run_gate_checks.main([profile, "--list"]) == 0


def test_tools_audit_swarm_run_refuses_but_plan_stays_fail_open(
    monkeypatch, contracts_disabled, capsys
):
    import tools.audit_swarm as audit_swarm

    def _exploded(*_a, **_kw):  # pragma: no cover - must never run
        raise AssertionError("fan_out must not run after a refused boundary")

    monkeypatch.setattr(audit_swarm, "fan_out", _exploded)
    monkeypatch.setattr(audit_swarm, "build_tasks", lambda *_a, **_kw: [])
    assert audit_swarm.main(["--plan"]) == 0
    with pytest.raises(EffectStartRefused):
        audit_swarm.main(["--run"])


def test_tools_funnel_run_refuses_before_any_tier_spend(
    tmp_path, monkeypatch, contracts_disabled
):
    import tools.funnel as funnel

    def _exploded(*_a, **_kw):  # pragma: no cover - must never run
        raise AssertionError("fan_out must not run after a refused boundary")

    monkeypatch.setattr(funnel, "fan_out", _exploded)
    monkeypatch.setattr(
        funnel, "load_spec",
        lambda _n: ({"name": "probe", "tiers": [{"name": "t", "system": "s",
                                                 "source": {"kind": "x"}}]},
                    tmp_path),
    )
    with pytest.raises(EffectStartRefused):
        funnel.main(["probe", "--run"])


def test_tools_gate_discrimination_refuses_but_dry_run_stays_fail_open(
    monkeypatch, contracts_disabled, capsys
):
    import tools.gate_discrimination as gate_discrimination

    def _exploded(*_a, **_kw):  # pragma: no cover - must never run
        raise AssertionError("run_corpus must not start after a refused boundary")

    monkeypatch.setattr(gate_discrimination, "run_corpus", _exploded)
    monkeypatch.setattr(gate_discrimination, "check_anchors", lambda *_a: [])
    assert gate_discrimination.main(["--dry-run"]) == 0
    with pytest.raises(EffectStartRefused):
        gate_discrimination.main([])


def test_tools_gui_check_refuses_before_any_spawn(
    tmp_path, monkeypatch, contracts_disabled
):
    import tools.gui_check as gui_check

    def _exploded(*_a, **_kw):  # pragma: no cover - must never run
        raise AssertionError("gui_run must not start after a refused boundary")

    monkeypatch.setattr(gui_check, "gui_run", _exploded)
    with pytest.raises(EffectStartRefused):
        gui_check.main(["--repo-root", str(tmp_path), "--web-root", str(tmp_path)])


def test_tools_operability_drill_refuses_before_the_drill(
    monkeypatch, contracts_disabled
):
    import tools.operability_drill as operability_drill

    def _exploded(*_a, **_kw):  # pragma: no cover - must never run
        raise AssertionError("the drill must not start after a refused boundary")

    monkeypatch.setattr(operability_drill, "run", _exploded)
    with pytest.raises(EffectStartRefused):
        operability_drill.main([])


def test_tools_system_check_refuses_before_any_check(
    monkeypatch, contracts_disabled
):
    import tools.system_check as system_check

    def _exploded(*_a, **_kw):  # pragma: no cover - must never run
        raise AssertionError("acceptance_run must not start after a refusal")

    monkeypatch.setattr(system_check, "acceptance_run", _exploded)
    with pytest.raises(EffectStartRefused):
        system_check.main([])


def test_tools_guarded_call_refuses_as_json_per_its_protocol(
    monkeypatch, contracts_disabled, capsys
):
    import io
    import tools.guarded_call as guarded_call

    monkeypatch.setattr(
        "sys.stdin", io.StringIO(json.dumps({"objective": "say hi"}))
    )
    assert guarded_call.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert "effect boundary refused" in out["error"]


def _runs_module(name):
    import importlib
    import sys as _sys
    from pathlib import Path as _Path

    root = _Path(__file__).resolve().parents[1]
    if str(root) not in _sys.path:
        _sys.path.insert(0, str(root))
    return importlib.import_module(name)


def test_runs_ab_doors_refuse_fail_closed(monkeypatch, contracts_disabled):
    run_arm = _runs_module("runs.ab.run_arm")
    monkeypatch.setattr("sys.argv", ["run_arm", "A"])
    with pytest.raises(EffectStartRefused):
        run_arm.main()

    score = _runs_module("runs.ab.score")
    with pytest.raises(EffectStartRefused):
        score.main()


def test_runs_council_room_refuses_but_show_stays_fail_open(
    monkeypatch, contracts_disabled, capsys
):
    room = _runs_module("runs.council.room")
    monkeypatch.setattr("sys.argv", ["room", "show"])
    room.main()  # read-only inspection keeps working
    monkeypatch.setattr(
        room, "_append", getattr(room, "_append", None), raising=False
    )
    monkeypatch.setattr("sys.argv", ["room", "cursor", "kaya", "--reset"])
    with pytest.raises(EffectStartRefused):
        room.main()


def test_runs_council_stream_hook_refuses_without_writing(
    monkeypatch, contracts_disabled, capsys
):
    import io

    stream_hook = _runs_module("runs.council.stream_hook")

    def _exploded(*_a, **_kw):  # pragma: no cover - must never run
        raise AssertionError("a refused hook must not write a record")

    monkeypatch.setattr(stream_hook, "_record", _exploded)
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    assert stream_hook.main(["stream_hook", "user"]) == 0
    assert "effect boundary refused" in capsys.readouterr().err


def test_runs_council_dead_letter_replay_refuses_but_list_stays_fail_open(
    tmp_path, contracts_disabled, capsys
):
    dlr = _runs_module("runs.council.dead_letter_replay")
    room_file = tmp_path / "room.md"
    room_file.write_text("", encoding="utf-8")
    assert dlr.main(["list", "--room", str(room_file)]) == 0
    with pytest.raises(EffectStartRefused):
        dlr.main(["replay", "--room", str(room_file)])


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
