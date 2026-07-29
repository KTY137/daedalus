"""Focused proof for the curated picker -> attempt path.

No model or network is used. The one end-to-end attempt uses a temporary git
repository and injected runner/gate so target-scope refusal is measured at the
same choke point as a live attempt.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import daedalus.spine.attempt as attempt_mod
import daedalus.spine.picker as picker
from daedalus.spine.bootstrap import refresh_sources
from daedalus.spine.attempt import (
    STATE_CLEAN,
    STATE_GATES_FAILED,
    GateResult,
    RunnerContext,
    TaskAttempt,
    TaskSpec,
)
from daedalus.spine.ledger import SpineLedger


BASE = "a" * 40
OBSERVED = "b" * 40
TARGET = "design/visual-lab/src/main.tsx"
GATE_ARGV = [
    "cmd.exe", "/d", "/s", "/c",
    "npm.cmd --prefix design/visual-lab run build",
]


def _config(repo: Path, *, work_queue=True, write_allow=(TARGET,),
            picker_sources=True, spine=None) -> dict:
    payload = {
        "policy": {"write_allow": list(write_allow)},
        "work_queue": (
            {"enabled": True, "path": ".agentenv/work-queue.json"}
            if work_queue else {"enabled": False}),
    }
    if picker_sources:
        payload["picker_sources"] = {
            "map": "disabled",
            "inventory": "disabled",
            "eval_baseline": "disabled",
            "eval_gate": "disabled",
            "hotspots": "disabled",
        }
    if spine is not None:
        payload["spine"] = spine
    folder = repo / ".agentenv"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "agentenv.json").write_text(
        json.dumps(payload), encoding="utf-8")
    return payload


def _queue(repo: Path, *, target=TARGET, cwd=".", argv=GATE_ARGV,
           instruction="Edit only the declared target.", priority=7,
           base=BASE) -> bytes:
    payload = {
        "schema": picker.WORK_QUEUE_SCHEMA,
        "repo_state": {
            "head": base,
            "meaning": "candidate_base_revision",
        },
        "tasks": [{
            "id": "curated-bootstrap",
            "state": "ready",
            "instruction": instruction,
            "authority_refs": [
                "operator-authorization:test",
                ".agentenv/agentenv.json",
            ],
            "target_paths": [target],
            "priority": priority,
            "gate": {
                "argv": list(argv),
                "cwd": cwd,
                "timeout_s": 180,
            },
        }],
    }
    raw = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
    path = repo / ".agentenv" / "work-queue.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


def _fake_head(repo: Path, sha=OBSERVED) -> None:
    branch = repo / ".git" / "refs" / "heads"
    branch.mkdir(parents=True, exist_ok=True)
    (repo / ".git" / "HEAD").write_text(
        "ref: refs/heads/main\n", encoding="utf-8")
    (branch / "main").write_text(sha + "\n", encoding="utf-8")


def _git_repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init"], cwd=path, check=True,
                   capture_output=True)
    subprocess.run(["git", "config", "user.name", "Queue Test"], cwd=path,
                   check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "queue@example.invalid"],
                   cwd=path, check=True, capture_output=True)
    target = path / TARGET
    target.parent.mkdir(parents=True)
    target.write_text("old\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True,
                   capture_output=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=path, check=True,
                   capture_output=True)
    return path


def test_work_queue_source_states_are_distinct_and_path_is_confined(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    _config(repo, work_queue=False)
    data, source = picker.load_work_queue(repo)
    assert data is None
    assert source["state"] == "disabled"
    assert "error" not in source

    _config(repo)
    data, source = picker.load_work_queue(repo)
    assert data is None
    assert source["state"] == "absent"
    assert source["error"]

    cfg_path = repo / ".agentenv" / "agentenv.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["work_queue"]["path"] = "../outside.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    data, source = picker.load_work_queue(repo)
    assert data is None
    assert source["state"] == "invalid"
    assert "escapes repo root" in source["error"]

    cfg["work_queue"]["path"] = ".agentenv/work-queue.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    (repo / ".agentenv" / "work-queue.json").write_text(
        "{broken", encoding="utf-8")
    data, source = picker.load_work_queue(repo)
    assert data is None
    assert source["state"] == "invalid"

    raw = _queue(repo)
    data, source = picker.load_work_queue(repo)
    assert data is not None
    assert source["state"] == "valid"
    assert source["path"] == str(
        (repo / ".agentenv" / "work-queue.json").resolve())
    assert source["sha256"] == hashlib.sha256(raw).hexdigest()
    assert source["byte_length"] == len(raw)


def test_work_queue_path_cannot_escape_through_a_symlink(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _config(repo)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "queue.json").write_text("{}", encoding="utf-8")
    link = repo / ".agentenv" / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")
    cfg_path = repo / ".agentenv" / "agentenv.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["work_queue"]["path"] = ".agentenv/linked/queue.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    data, source = picker.load_work_queue(repo)

    assert data is None
    assert source["state"] == "invalid"
    assert "escapes repo root" in source["error"]


def test_disabled_map_source_is_not_refreshed_into_the_primary_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _config(repo)
    calls = []

    reports = refresh_sources(
        repo,
        runner=lambda argv, root: calls.append((argv, root)))

    assert calls == []
    assert len(reports) == 1
    assert reports[0].name == "map"
    assert reports[0].attempted is False
    assert reports[0].succeeded is True
    assert "disabled by repo-local" in reports[0].detail
    assert not (repo / "docs" / "architecture-state.json").exists()


def test_queue_candidate_binds_bytes_base_scope_gate_and_observed_head(
        tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _config(repo)
    raw = _queue(repo)
    _fake_head(repo)

    monkeypatch.setattr(
        picker, "_run_eval_gate",
        lambda: pytest.fail("disabled eval gate was executed"))
    monkeypatch.setattr(
        picker, "_load_index",
        lambda root: pytest.fail("disabled hotspots were executed"))
    queue = picker.build_queue(
        repo, limit=None, use_attempt_memory=False,
        include_eval=True, include_hotspots=True)

    assert [c.task_id for c in queue.candidates] == ["curated-bootstrap"]
    assert queue.sources["work_queue"]["state"] == "valid"
    assert queue.sources["map"]["state"] == "disabled"
    assert queue.sources["inventory"]["state"] == "disabled"
    assert queue.sources["eval_baseline"]["state"] == "disabled"
    assert queue.sources["eval_gate"]["state"] == "disabled"
    assert queue.sources["hotspots"]["state"] == "disabled"
    candidate = queue.top
    assert candidate is not None
    assert candidate.source == "work_queue"
    assert candidate.base_revision == BASE
    assert candidate.target_paths == (TARGET,)
    assert candidate.gate_argv == tuple(GATE_ARGV)
    assert candidate.gate_cwd == "."
    assert candidate.gate_timeout_s == 180
    assert candidate.evidence["queue_sha256"] == hashlib.sha256(raw).hexdigest()
    assert candidate.evidence["queue_path"] == str(
        (repo / ".agentenv" / "work-queue.json").resolve())
    assert candidate.evidence["candidate_base_revision"] == BASE
    # Self-reference is explicit: the queue is READ at OBSERVED, while its
    # candidate is intentionally attempted from the earlier BASE.
    assert candidate.evidence["picker_observed_head"] == OBSERVED

    spec = candidate.to_task_spec()
    assert spec.base_revision == BASE
    assert spec.target_paths == (TARGET,)
    assert spec.gate_argv == tuple(GATE_ARGV)
    assert spec.gate_cwd == "."
    assert spec.gate_timeout_s == 180
    assert spec.metadata["picker_evidence"]["queue_sha256"] == (
        hashlib.sha256(raw).hexdigest())
    assert spec.body()["gate"]["argv"] == GATE_ARGV
    assert spec.body()["target_paths"] == [TARGET]


@pytest.mark.parametrize(
    "mutate,error_fragment",
    [
        (lambda q: q.update(schema="other"), "schema must be"),
        (lambda q: q["repo_state"].update(head="abc"), "full 40- or 64-hex"),
        (lambda q: q["tasks"][0]["target_paths"].__setitem__(
            0, "../escape.tsx"), "must not contain"),
        (lambda q: q["tasks"][0]["gate"].update(cwd="design/visual-lab"),
         "gate.cwd must be '.'"),
        (lambda q: q["tasks"][0]["gate"].update(argv="npm test"),
         "gate.argv must be"),
    ],
)
def test_invalid_queue_never_admits_a_partial_candidate(
        tmp_path, mutate, error_fragment):
    repo = tmp_path / "repo"
    repo.mkdir()
    _config(repo)
    _queue(repo)
    path = repo / ".agentenv" / "work-queue.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")

    queue = picker.build_queue(
        repo, limit=None, use_attempt_memory=False)

    assert queue.top is None
    assert queue.sources["work_queue"]["state"] == "invalid"
    assert error_fragment in queue.sources["work_queue"]["error"]
    assert "work_queue" in queue.degraded_sources


def test_policy_feasibility_suppresses_task_before_ranking(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _config(repo, write_allow=("design/visual-lab/src/App.tsx",))
    _queue(repo)

    queue = picker.build_queue(
        repo, limit=None, use_attempt_memory=False)

    assert queue.top is None
    source = queue.sources["work_queue"]
    assert source["state"] == "valid"
    assert source["policy_blocked"] == 1
    assert source["suppressed"] is True
    assert "work_queue" in queue.degraded_sources
    assert any("write policy blocks" in note for note in queue.notes)


def test_external_repo_uses_one_repo_bound_ledger_for_read_and_write(tmp_path,
                                                                    monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _config(repo)
    _queue(repo, instruction="same instruction")
    default_path, error = picker.resolve_spine_db_path(repo)
    assert error is None
    assert default_path == (
        repo / "runs" / "spine" / "spine.sqlite3").resolve()

    cold = picker.build_queue(repo, limit=None, use_attempt_memory=False)
    candidate = cold.top
    assert candidate is not None
    ledger = SpineLedger(default_path)
    try:
        intent = ledger.record_intent(
            picker.ATTEMPT_INTENT_KIND,
            candidate.to_task_spec().body(),
            effect_key="queue-memory-proof")
        ledger.mark_completed(
            intent.id, effect_id="c" * 64,
            result={"state": "no_change"})
    finally:
        ledger.close()

    warm = picker.build_queue(repo, limit=None)
    assert warm.sources["attempt_memory"]["path"] == str(default_path)
    assert warm.top.evidence["prior_attempts"] == 1
    assert warm.top.evidence["prior_attempts_same_definition"] == 1
    assert warm.top.evidence["last_attempt_outcome"] == "no_change"

    _queue(repo, instruction="same instruction", base="d" * 40)
    revised = picker.build_queue(repo, limit=None)
    assert revised.top.evidence["prior_attempts"] == 1
    assert revised.top.evidence["prior_attempts_same_definition"] == 0
    assert "different task definition" in revised.top.evidence["memory"]

    captured = {}
    monkeypatch.setattr(
        attempt_mod, "offload_runner",
        lambda **kw: ("runner", kw))

    def fake_run(spec, **kwargs):
        captured["spec"] = spec
        captured["kwargs"] = kwargs
        return SimpleNamespace(state="no_change")

    monkeypatch.setattr(attempt_mod, "run_attempt", fake_run)
    args = SimpleNamespace(
        repo_root=str(repo), live=True, artifact_dir=None,
        keep_worktree=False)
    picker._default_attempt(candidate, args)
    assert captured["kwargs"]["ledger_path"] == default_path
    assert captured["spec"].target_paths == (TARGET,)
    assert captured["spec"].gate_argv == tuple(GATE_ARGV)

    cfg = json.loads(
        (repo / ".agentenv" / "agentenv.json").read_text(encoding="utf-8"))
    cfg["spine"] = {"ledger_path": "../outside.sqlite3"}
    path, error = picker.resolve_spine_db_path(
        repo, project_config=cfg)
    assert path is None
    assert "escapes repo root" in error


def test_legacy_taskspec_body_and_digest_shape_are_unchanged():
    spec = TaskSpec(task_id="legacy", instruction="do work")
    assert spec.body() == {
        "task_id": "legacy",
        "instruction": "do work",
        "base_revision": None,
        "gate_paths": [],
        "metadata": {},
    }
    assert "target_paths" not in spec.body()
    assert "gate" not in spec.body()


def test_offload_runner_forwards_declared_paths_and_cannot_be_widened(
        tmp_path, monkeypatch):
    captured = {}

    def fake_offload(objective, repo_root, **kwargs):
        captured.update(
            objective=objective, repo_root=repo_root, kwargs=kwargs)
        return {"action": "plan"}

    monkeypatch.setattr("daedalus.offload.offload", fake_offload)
    task = TaskSpec(
        task_id="scoped", instruction="edit it",
        target_paths=(TARGET,))
    ctx = RunnerContext(
        worktree=tmp_path, branch="b", base_revision=BASE, task=task,
        is_cancelled=lambda: False)

    runner = attempt_mod.offload_runner(
        live=True, paths=["design/visual-lab/src/App.tsx"])
    runner(ctx)

    assert captured["repo_root"] == str(tmp_path)
    assert captured["kwargs"]["paths"] == [TARGET]
    assert captured["kwargs"]["live"] is True


def test_taskspec_command_gate_is_the_attempt_default(monkeypatch, tmp_path):
    captured = {}

    def fake_command_gate(argv, **kwargs):
        captured["argv"] = tuple(argv)
        captured["kwargs"] = kwargs
        return lambda ctx: GateResult(
            passed=True, name="fake", output="passed")

    monkeypatch.setattr(attempt_mod, "command_gate", fake_command_gate)
    TaskAttempt(
        TaskSpec(
            task_id="gate-proof",
            instruction="edit",
            gate_argv=tuple(GATE_ARGV),
            gate_cwd=".",
            gate_timeout_s=180),
        runner=lambda ctx: None,
        repo_root=tmp_path,
        worktree_manager=object())

    assert captured["argv"] == tuple(GATE_ARGV)
    assert captured["kwargs"]["timeout_s"] == 180
    assert captured["kwargs"]["name"] == "queue-command"


def test_artifact_outside_target_scope_is_refused_before_gate(
        tmp_path, monkeypatch):
    repo = _git_repo(tmp_path / "repo")
    monkeypatch.setenv(
        "DAEDALUS_WORKTREE_ROOT", str(tmp_path / "worktrees"))
    ledger = SpineLedger(tmp_path / "ledger" / "spine.sqlite3")
    gate_calls = []

    def runner(ctx):
        (ctx.worktree / TARGET).write_text("new\n", encoding="utf-8")
        extra = ctx.worktree / "design/visual-lab/src/App.tsx"
        extra.write_text("escaped\n", encoding="utf-8")

    def gate(ctx):
        gate_calls.append(ctx)
        return GateResult(passed=True, name="must-not-run", output="pass")

    try:
        result = TaskAttempt(
            TaskSpec(
                task_id="scope-proof",
                instruction="edit only main",
                target_paths=(TARGET,)),
            runner=runner,
            gate=gate,
            repo_root=repo,
            ledger=ledger).run()
    finally:
        ledger.close()

    assert result.state == STATE_GATES_FAILED
    assert result.gates.name == "target-scope"
    assert "App.tsx" in result.gates.output
    assert gate_calls == []
    assert result.artifact.changed_paths == (
        "design/visual-lab/src/App.tsx", TARGET)
    assert subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, check=True,
        capture_output=True, text=True).stdout == ""


def test_in_scope_artifact_reaches_the_gate(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path / "repo")
    monkeypatch.setenv(
        "DAEDALUS_WORKTREE_ROOT", str(tmp_path / "worktrees"))
    ledger = SpineLedger(tmp_path / "ledger" / "spine.sqlite3")
    gate_calls = []

    def runner(ctx):
        (ctx.worktree / TARGET).write_text("new\n", encoding="utf-8")

    def gate(ctx):
        gate_calls.append(ctx)
        return GateResult(passed=True, name="proof", output="1 passed")

    try:
        result = TaskAttempt(
            TaskSpec(
                task_id="scope-proof",
                instruction="edit only main",
                target_paths=(TARGET,)),
            runner=runner,
            gate=gate,
            repo_root=repo,
            ledger=ledger).run()
    finally:
        ledger.close()

    assert result.state == STATE_CLEAN
    assert len(gate_calls) == 1


def test_green_gate_cannot_rewrite_the_tree_after_artifact_capture(
        tmp_path, monkeypatch):
    repo = _git_repo(tmp_path / "repo")
    monkeypatch.setenv(
        "DAEDALUS_WORKTREE_ROOT", str(tmp_path / "worktrees"))
    ledger = SpineLedger(tmp_path / "ledger" / "spine.sqlite3")

    def runner(ctx):
        (ctx.worktree / TARGET).write_text("candidate\n", encoding="utf-8")

    def mutating_green_gate(ctx):
        # Simulate a formatter/build script that changes a tracked candidate
        # after the artifact was staged, then exits green.
        (ctx.worktree / TARGET).write_text("post-gate\n", encoding="utf-8")
        return GateResult(
            passed=True, name="mutating-green", returncode=0,
            output="build passed")

    try:
        result = TaskAttempt(
            TaskSpec(
                task_id="binding-proof",
                instruction="edit only main",
                target_paths=(TARGET,)),
            runner=runner,
            gate=mutating_green_gate,
            repo_root=repo,
            ledger=ledger).run()
    finally:
        ledger.close()

    assert result.state == STATE_GATES_FAILED
    assert result.gates.passed is False
    assert result.gates.returncode == 0
    assert "post-gate artifact binding failed" in result.gates.output
    assert "Refusing the green verdict" in result.gates.output


def test_post_gate_binding_error_fails_closed_and_resolves_intent(
        tmp_path, monkeypatch):
    repo = _git_repo(tmp_path / "repo")
    monkeypatch.setenv(
        "DAEDALUS_WORKTREE_ROOT", str(tmp_path / "worktrees"))
    ledger = SpineLedger(tmp_path / "ledger" / "spine.sqlite3")

    def runner(ctx):
        (ctx.worktree / TARGET).write_text("candidate\n", encoding="utf-8")

    monkeypatch.setattr(
        TaskAttempt, "_post_gate_artifact_stable",
        lambda self, worktree, artifact: (_ for _ in ()).throw(
            OSError("verification unavailable")))
    try:
        result = TaskAttempt(
            TaskSpec(
                task_id="binding-error-proof",
                instruction="edit only main",
                target_paths=(TARGET,)),
            runner=runner,
            gate=lambda ctx: GateResult(
                passed=True, name="green", returncode=0, output="passed"),
            repo_root=repo,
            ledger=ledger).run()
        assert result.state == STATE_GATES_FAILED
        assert "could not be verified" in result.gates.output
        assert ledger.open_intents() == []
    finally:
        ledger.close()
