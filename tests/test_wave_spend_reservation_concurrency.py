# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The lease's concurrency ceiling, issued at a number that can actually bind.

FINDING F9 (measured 2026-08-22, agent_env_g0 HEAD 898ac110).
``build_exec._acquire_wave_lease`` passed ``positions=len(wave.tasks)``, and
``positions`` IS the lease's ``max_concurrency``
(``kernel/offload_lease.py:853``). So the ceiling equalled the number of
executions the wave derives, and the effect ledger's check
(``kernel/effects.py:761`` -> ``EffectLeaseConcurrencyError``) could never
fire: a wave can never start more executions than it has tasks. A bound that
is always slack is not a bound.

The real bounds live in the scheduler that will run the wave:
``ThreadPoolExecutor(max_workers=self.max_workers)`` for advisory parallel
dispatch (``kairos/scheduler.py:289``) and
``min(max_parallel_writes, max_workers)`` for the gated write path
(``kairos/scheduler.py:348``). Sequential dispatch runs one at a time.
``WaveExecutor._wave_concurrency`` issues that number instead.
"""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from daedalus.build import BuildTask, Wave
from daedalus.build_exec import EffectBounds, WaveExecutor
from daedalus.kairos.scheduler import Assignment, KairosScheduler
from daedalus.kernel.effects import EffectLeaseConcurrencyError
from daedalus.kernel.offload_lease import (
    acquire_wave_offload_lease, control_root,
)
from daedalus.spine.killswitch import KillSwitch

REPO_ROOT = str(Path(__file__).resolve().parents[1])
REVISION = "b" * 40


@pytest.fixture
def switch(tmp_path, monkeypatch):
    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(tmp_path / "killswitch"))
    sw = KillSwitch(repo_root=REPO_ROOT)
    sw.arm(note="test")
    assert control_root(REPO_ROOT) == tmp_path
    return sw


def _assignment(mode: str = "advisory") -> Assignment:
    return Assignment(objective="review the docref", paths=["docs/x.md"],
                      owner="Clio", lane="ollama", worker="Lucia", mode=mode,
                      accepted=True, reason="test routing")


def _wave(n: int) -> Wave:
    return Wave(index=0, tasks=[
        BuildTask(objective=f"task {i}", agent="Clio", category="docs",
                  lane="ollama", tier="cheap", builder="ollama",
                  frontier=False, paths=[f"docs/x{i}.md"])
        for i in range(n)])


def _scheduler(workers: int = 3, writes: int = 2) -> KairosScheduler:
    s = KairosScheduler(availability={"ollama": True})
    s.max_workers = workers
    s.max_parallel_writes = writes
    return s


# --------------------------------------------------------------------------- #
# what number is issued                                                        #
# --------------------------------------------------------------------------- #
def test_sequential_wave_leases_one_execution_at_a_time():
    got = WaveExecutor._wave_concurrency(_scheduler(), _wave(4),
                                         gated=False, parallel=False)
    assert got == 1


def test_parallel_advisory_wave_leases_the_worker_bound():
    # 4 tasks, 3 workers: dispatch's pool runs 3 at once, so 3 is the ceiling.
    assert WaveExecutor._wave_concurrency(
        _scheduler(workers=3), _wave(4), gated=False, parallel=True) == 3
    # ...and never more than the wave can possibly start.
    assert WaveExecutor._wave_concurrency(
        _scheduler(workers=8), _wave(2), gated=False, parallel=True) == 2


def test_gated_write_wave_leases_the_write_bound():
    # gate_concurrent_writes fans out over min(max_parallel_writes, max_workers).
    assert WaveExecutor._wave_concurrency(
        _scheduler(workers=5, writes=2), _wave(4), gated=True, parallel=False) == 2
    assert WaveExecutor._wave_concurrency(
        _scheduler(workers=1, writes=4), _wave(4), gated=True, parallel=False) == 1


def test_the_wave_lease_is_issued_at_that_number_not_at_the_task_count(switch):
    """The defect, at the seam where it lived: a 3-task sequential wave used to
    lease 3-way concurrency."""
    calls: list[dict] = []
    real = acquire_wave_offload_lease

    def _counting(*args, **kwargs):
        calls.append(dict(kwargs))
        return real(*args, **kwargs)

    executor = WaveExecutor(
        availability={"ollama": True},
        effect_bounds=EffectBounds(
            mission_id="concurrency-test", source_revision=REVISION,
            max_spend_usd=0.25, timeout_s=900.0, switch=switch))
    wave = _wave(3)
    assignments = [_assignment() for _ in range(3)]
    with mock.patch("daedalus.kernel.offload_lease."
                    "acquire_wave_offload_lease", side_effect=_counting):
        lease = executor._acquire_wave_lease(
            _scheduler(), wave, assignments, REPO_ROOT,
            task_dicts=[{"objective": t.objective, "paths": list(t.paths)}
                        for t in wave.tasks],
            attempt_id="w0-test", gated=False, has_writes=False,
            parallel=False)
    assert calls[0]["positions"] == 1
    assert lease.lease.effect_scope.max_concurrency == 1
    # The receipt publishes the bound an operator can check against the pool.
    assert lease.receipt()["max_concurrency"] == 1


# --------------------------------------------------------------------------- #
# and the ledger enforces it                                                   #
# --------------------------------------------------------------------------- #
def test_a_wave_with_more_tasks_than_the_bound_is_refused_by_the_ledger(switch):
    """Three tasks, a bound of one: the SECOND concurrent start is refused by
    the effect ledger, which is the component that enforces the ceiling."""
    wave = _wave(3)
    bound = WaveExecutor._wave_concurrency(_scheduler(), wave,
                                           gated=False, parallel=False)
    lease = acquire_wave_offload_lease(
        REPO_ROOT, source_revision=REVISION, mission_id="concurrency-test",
        attempt_id="w0-bound", positions=bound, writable_paths=("docs/x.md",),
        lanes=("ollama",), max_spend_usd=0.25, timeout_s=900,
        containment_evidence="advisory wave", switch=switch)
    auth = lease.authorization
    first = auth.begin_effect(lease.execution_for(0))
    assert first.execute is True
    with pytest.raises(EffectLeaseConcurrencyError):
        auth.begin_effect(lease.execution_for(1))
    # THE NEGATIVE CONTROL, and it is the finding itself: issued at the task
    # count -- what this executor passed until 2026-08-22 -- the same two
    # starts are both permitted, so the ceiling never fires.
    slack = acquire_wave_offload_lease(
        REPO_ROOT, source_revision=REVISION, mission_id="concurrency-test",
        attempt_id="w0-slack", positions=len(wave.tasks),
        writable_paths=("docs/x.md",), lanes=("ollama",), max_spend_usd=0.25,
        timeout_s=900, containment_evidence="advisory wave", switch=switch)
    slack_auth = slack.authorization
    assert slack_auth.begin_effect(slack.execution_for(0)).execute
    assert slack_auth.begin_effect(slack.execution_for(1)).execute
