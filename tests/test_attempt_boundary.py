"""``python.attempt`` starts at the central boundary, and the receipt is the record.

The row was ``LOCAL_GUARDS`` with the note "direct Python callers do not yet
obtain a boundary receipt", so ``begin_effect`` REFUSED it and the canonical
``PolicyDecision`` on the attempt path was assembled from a hand-written list of
guard names. These tests pin the three things that changed: the row is central
and anchored, the boundary event happens before the first worktree write, and
``PolicyDecision.policy_sha256`` comes from the receipt rather than from a
second, independent read of the same registry.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

import daedalus.kairos.worktree as worktree_module
import daedalus.spine.attempt as attempt_module
import daedalus.spine.effect_boundary as boundary_module
from daedalus.spine.attempt import GateResult, RunnerContext, TaskSpec, run_attempt
from daedalus.spine.effect_boundary import (
    REGISTRY_BY_ID,
    EffectStartRefused,
    GuardAnchor,
    Wiring,
    registry_sha256,
)
from daedalus.spine.receipts import (
    ATTEMPT_ENTRYPOINT_ID,
    UNMETERED_SPEND_REASON,
    AttemptContractSet,
)

ROW = "python.attempt"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(tmp_path / "ks"))
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], check=True)
    (root / "a.txt").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "base"], check=True)
    return root


def _runner(ctx):
    (ctx.worktree / "a.txt").write_text("two\n", encoding="utf-8")
    return {"ok": True}


def _gate(ctx):
    return GateResult(passed=True, name="target-scope", output="ok", duration_s=0.25)


def _run(repo, tmp_path, **kw):
    task = TaskSpec(task_id="boundary-1", instruction="change a.txt",
                    target_paths=("a.txt",))
    body = dict(runner=_runner, gate=_gate, repo_root=str(repo),
                ledger_path=str(tmp_path / "spine.sqlite3"),
                artifact_dir=str(tmp_path / "art"))
    body.update(kw)
    return run_attempt(task, **body)


# --------------------------------------------------------------------------- #
# the registry row                                                             #
# --------------------------------------------------------------------------- #
def test_the_row_is_central_and_anchored():
    row = REGISTRY_BY_ID[ROW]
    assert row.wiring is Wiring.CENTRAL
    # The anchor names TaskAttempt.run, not the two-line run_attempt wrapper:
    # TaskAttempt(...).run() is a live call shape, and a boundary reachable
    # only through one constructor is not a boundary.
    assert GuardAnchor("daedalus.spine.attempt:TaskAttempt.run",
                       "begin_effect") in row.anchors
    assert set(row.guard_contracts) == {
        "spine.intent_ledger", "containment.worktree",
        "containment.attempt", "budget.process_guard",
    }


def test_the_declared_effects_still_match_what_the_path_does():
    """Worktree + artifact writes, the gate child, and the candidate branch ref.

    NETWORK_EGRESS and SPEND stay absent on purpose: the model call belongs to
    the injected runner, which crosses its own ``python.offload`` boundary under
    its own lease. Declaring them here would claim this row bounds a spend it
    neither meters nor limits."""
    effects = {e.value for e in REGISTRY_BY_ID[ROW].effects}
    assert effects == {"filesystem_write", "process_spawn", "repository_mutation"}


def test_begin_effect_no_longer_refuses_the_row():
    with pytest.raises(EffectStartRefused) as excinfo:
        boundary_module.begin_effect(ROW, REGISTRY_BY_ID[ROW].effects, ())
    # It refuses for a MISSING DECISION now, not for "not centrally wired" --
    # which is what it said before the row was upgraded.
    assert "missing guard decisions" in str(excinfo.value)
    assert "not central" not in str(excinfo.value)


# --------------------------------------------------------------------------- #
# ordering: the boundary comes before the first effect                         #
# --------------------------------------------------------------------------- #
def test_the_boundary_event_precedes_the_first_worktree_write(repo, tmp_path,
                                                              monkeypatch):
    trace: list[tuple[str, str]] = []
    real_begin = boundary_module.begin_effect
    real_create = worktree_module.GitWorktreeManager.create_worktree

    def traced_begin(entrypoint_id, effects, decisions, **kw):
        receipt = real_begin(entrypoint_id, effects, decisions, **kw)
        trace.append(("begin_effect", str(entrypoint_id)))
        return receipt

    def traced_create(self, *a, **kw):
        trace.append(("create_worktree", ""))
        return real_create(self, *a, **kw)

    monkeypatch.setattr(boundary_module, "begin_effect", traced_begin)
    monkeypatch.setattr(worktree_module.GitWorktreeManager, "create_worktree",
                        traced_create)

    result = _run(repo, tmp_path)
    assert result.state == "clean", result.error
    kinds = [row[0] for row in trace]
    assert ("begin_effect", ROW) in trace
    assert kinds.index("create_worktree") > trace.index(("begin_effect", ROW))


def test_a_refused_boundary_stops_the_attempt_before_any_effect(repo, tmp_path,
                                                                monkeypatch):
    created: list[int] = []
    real_create = worktree_module.GitWorktreeManager.create_worktree

    def counted(self, *a, **kw):
        created.append(1)
        return real_create(self, *a, **kw)

    def refuse(*a, **kw):
        raise EffectStartRefused("test refusal")

    monkeypatch.setattr(worktree_module.GitWorktreeManager, "create_worktree",
                        counted)
    monkeypatch.setattr(boundary_module, "begin_effect", refuse)

    result = _run(repo, tmp_path)
    # A refused start is a STATE, never an exception -- run_attempt still
    # promises to return.
    assert result.state == "worktree_failed"
    assert "effect boundary refused this attempt" in (result.error or "")
    assert created == []


# --------------------------------------------------------------------------- #
# the decisions are run, not asserted                                          #
# --------------------------------------------------------------------------- #
def test_a_runner_context_that_names_the_checkout_refuses_the_attempt(
        repo, tmp_path, monkeypatch):
    """Property 2 of this module's four ("the runner is never told where the
    repo is") was prose. Re-adding the field must refuse, not widen."""

    @dataclass(frozen=True)
    class LeakyContext(RunnerContext):
        repo_root: str = ""

    monkeypatch.setattr(attempt_module, "RunnerContext", LeakyContext)
    result = _run(repo, tmp_path)
    assert result.state == "worktree_failed"
    assert "containment.attempt" in (result.error or "")
    assert "repo_root" in (result.error or "")


def test_an_overlapping_isolation_root_refuses_the_attempt(repo, tmp_path,
                                                           monkeypatch):
    monkeypatch.setattr(
        worktree_module.GitWorktreeManager, "worktree_root",
        property(lambda self: Path(repo) / "inside"))
    result = _run(repo, tmp_path)
    assert result.state in {"worktree_failed", "storage_unavailable"}
    if result.state == "worktree_failed":
        assert "containment.worktree" in (result.error or "")


# --------------------------------------------------------------------------- #
# the receipt is the source of the canonical PolicyDecision                    #
# --------------------------------------------------------------------------- #
def test_policy_sha256_is_the_boundary_receipts_registry_sha(repo, tmp_path,
                                                             monkeypatch):
    seen: list = []
    real_begin = boundary_module.begin_effect

    def capture(entrypoint_id, effects, decisions, **kw):
        receipt = real_begin(entrypoint_id, effects, decisions, **kw)
        if str(entrypoint_id) == ROW:
            seen.append(receipt)
        return receipt

    monkeypatch.setattr(boundary_module, "begin_effect", capture)
    result = _run(repo, tmp_path)
    assert result.state == "clean", result.error

    contracts = AttemptContractSet.from_dict(result.contracts)
    assert len(seen) == 1
    assert contracts.policy.policy_sha256 == seen[0].registry_sha256
    assert contracts.policy.policy_sha256 == registry_sha256()
    # The receipt itself is tied into the record, so a reader can find the start.
    assert seen[0].receipt_sha256 in contracts.policy.provenance.input_digests


def test_the_receipts_own_guard_evidence_is_in_the_decision(repo, tmp_path):
    result = _run(repo, tmp_path)
    assert result.state == "clean", result.error
    reasons = AttemptContractSet.from_dict(result.contracts).policy.reasons
    assert any(r.startswith(f"effect boundary: begin_effect({ATTEMPT_ENTRYPOINT_ID})")
               for r in reasons)
    # Contract evidence the CONTRACT produced, not prose restating its name.
    assert any("primary_tree.overlap_reason" in r for r in reasons)
    assert any("install_process_guard active" in r for r in reasons)
    assert any("gate-0 durable spine writer open at" in r for r in reasons)
    # The locally-derived list survives as corroboration.
    assert "containment.attempt: declared target_paths bound the accepted patch" in reasons


def test_spend_stays_unmetered_and_says_so(repo, tmp_path):
    """MEASURED 2026-08-22: ``daedalus.offload``'s result dict carries no token
    or cost key (``action``, ``wrote``, ``verify``, ``report``, ``draft``,
    ``reachability``, ``model``, ``note``, ``rolled_back``, ``auto_mint``,
    ``latent_route``, ``slice_context``, ``mutation_blocked``,
    ``dirty_unreverted``, ``needs_stronger_lane``, and the two effect receipts),
    and no provider module accounts usage. So there is nothing to carry into
    ``AttemptReceipt.usage``, and zero must keep saying "nobody measured this"
    rather than "this cost nothing"."""
    result = _run(repo, tmp_path)
    contracts = AttemptContractSet.from_dict(result.contracts)
    assert UNMETERED_SPEND_REASON in contracts.policy.reasons
    assert contracts.receipt.usage.cost_microusd == 0
    # The one thing that IS measured on this path stays measured.
    assert contracts.receipt.usage.wall_time_ms == 250
