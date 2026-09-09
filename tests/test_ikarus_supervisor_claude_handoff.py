"""Product-path regressions for TaskAttempt-owned Ikarus/Claude identity."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import daedalus.ikarus_claude_attempt_handoff as handoff  # noqa: E402
from daedalus.ikarus_supervisor import (  # noqa: E402
    MissionSupervisor,
    PlannedItem,
    RoleHarness,
    plan_mission,
)
from daedalus.schemas import ResourceBudget  # noqa: E402
from daedalus.spine.attempt import GateResult  # noqa: E402


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "target"
    repo.mkdir()

    def git(*args: str) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
        return proc.stdout.strip()

    git("init")
    git("config", "user.name", "t")
    git("config", "user.email", "t@example.invalid")
    (repo / "docs").mkdir()
    (repo / "docs" / "a.md").write_text("alpha\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "seed")
    return repo, git("rev-parse", "HEAD")


def _gate(_item: PlannedItem):
    def gate(_ctx):
        return GateResult(passed=True, name="unit-gate", command=())

    return gate


def _run(
    tmp_path: Path,
    monkeypatch,
    runner_factory,
) -> tuple[MissionSupervisor, dict]:
    repo, head = _repo(tmp_path)
    monkeypatch.setenv("DAEDALUS_WORKTREE_ROOT", str(tmp_path / "wt"))
    item = PlannedItem(
        objective="rewrite docs/a.md",
        role="coder",
        paths=("docs/a.md",),
    )
    session, mission = plan_mission(
        "TaskAttempt Claude handoff probe",
        repo_root=repo,
        items=(item,),
        base_revision=head,
        budget=ResourceBudget(max_wall_time_s=120),
        success_criteria=("docs/a.md is rewritten and gated",),
    )
    supervisor = MissionSupervisor(
        repo_root=repo,
        run_dir=tmp_path / "run",
        roles={
            "coder": RoleHarness(
                role="coder",
                runner_factory=runner_factory,
                gate_factory=_gate,
            )
        },
        gate_timeout_s=120,
    )
    return supervisor, supervisor.run(session, mission, (item,))


def _writer(item: PlannedItem):
    def runner(ctx):
        target = Path(ctx.worktree) / item.paths[0]
        target.write_text("written through guarded runner\n", encoding="utf-8")
        return {"wrote": item.paths[0]}

    return runner


def test_runner_context_is_authenticated_before_runner_factory(
    tmp_path: Path, monkeypatch
) -> None:
    events: list[str] = []
    real_guard = handoff.require_task_attempt_runner_context

    def guard(binding, context):
        events.append("guard")
        return real_guard(binding, context)

    def factory(item: PlannedItem):
        events.append("factory")
        return _writer(item)

    monkeypatch.setattr(handoff, "require_task_attempt_runner_context", guard)
    supervisor, final = _run(tmp_path, monkeypatch, factory)

    assert final["outcome"] == "landed"
    assert events == ["guard", "factory"]
    assert len(supervisor.results) == 1
    assert final["items"][0]["attempt_id"] == supervisor.results[0].branch


def test_runner_context_refusal_blocks_runner_factory(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[str] = []

    def refuse(_binding, _context):
        raise handoff.IkarusClaudeAttemptHandoffRefused("context substitution probe")

    def factory(item: PlannedItem):
        calls.append(item.objective)
        return _writer(item)

    monkeypatch.setattr(handoff, "require_task_attempt_runner_context", refuse)
    supervisor, final = _run(tmp_path, monkeypatch, factory)

    assert calls == []
    assert final["outcome"] == "bounced"
    assert final["items"][0]["status"] == "bounced"
    assert len(supervisor.results) == 1
    assert supervisor.results[0].state == "runner_failed"
    assert "context substitution probe" in (supervisor.results[0].error or "")


def test_terminal_binding_refusal_withholds_trusted_attempt_identity(
    tmp_path: Path, monkeypatch
) -> None:
    def refuse(_binding, _attempt):
        raise handoff.IkarusClaudeAttemptHandoffRefused("terminal substitution probe")

    monkeypatch.setattr(handoff, "require_task_attempt_terminal_contract", refuse)
    supervisor, final = _run(tmp_path, monkeypatch, _writer)

    # The candidate itself can be clean while the supervisor refuses to expose
    # it as trusted Ikarus terminal evidence.  Producer evidence remains
    # inspectable by digest, but no Attempt identity is promoted into Work Pulse.
    assert supervisor.results[0].ok is True
    assert final["outcome"] == "bounced"
    row = final["items"][0]
    assert row["status"] == "bounced"
    assert row["attempt_id"] is None
    assert row["attempt_receipt_sha256"]
    assert "terminal substitution probe" in (row["detail"] or "")
