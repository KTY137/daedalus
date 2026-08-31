"""One internal entry point for an admitted build mission.

This module deliberately defines no Mission, WorkItem, Effect, Attempt,
Evidence or scheduler type. It snapshots the existing ``BuildSession`` view
into the canonical ``MissionContract`` and hands execution to the existing
``WaveExecutor``. The executor remains the sole owner of scheduling, Effect
Leases, Attempt lifecycles and Evidence production.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from daedalus.build import BuildSession
from daedalus.build_exec import BuildRunReport, EffectBounds, WaveExecutor
from daedalus.schemas import MissionContract, ResourceBudget
from daedalus.spine.receipts import mission_contract_for_build_session


def _created_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mission_budget(executor: WaveExecutor) -> ResourceBudget:
    """Mirror the configured fallbacks used by the existing lease issuer."""

    bounds = executor.effect_bounds
    spend = None if bounds is None else bounds.max_spend_usd
    timeout = None if bounds is None else bounds.timeout_s
    max_cost_microusd = (
        0 if spend is None else max(0, int(round(float(spend) * 1_000_000)))
    )
    max_wall_time_s = (
        3600 if not timeout else max(1, int(round(float(timeout))))
    )
    return ResourceBudget(
        max_cost_microusd=max_cost_microusd,
        max_wall_time_s=max_wall_time_s,
    )


def _validate_effect_binding(
    executor: WaveExecutor,
    session: BuildSession,
    source_revision: str,
    trace_id: str | None,
) -> None:
    bounds = executor.effect_bounds
    if bounds is None:
        return
    if type(bounds) is not EffectBounds:
        raise TypeError("executor.effect_bounds must be an exact EffectBounds")
    if bounds.mission_id != session.mission_id:
        raise ValueError(
            "executor EffectBounds mission_id does not match the BuildSession"
        )
    if bounds.source_revision != source_revision:
        raise ValueError(
            "executor EffectBounds source_revision does not match the mission"
        )
    if trace_id is not None and bounds.trace_id not in (None, trace_id):
        raise ValueError("executor EffectBounds trace_id does not match the mission")


def run_mission(
    session: BuildSession,
    *,
    source_revision: str,
    executor: WaveExecutor,
    success_criteria: Sequence[str] | None = None,
    trace_id: str | None = None,
    repo_root: str | Path | None = None,
    dry_run: bool = True,
    parallel_advisory: bool = True,
    resume: bool = True,
    stop_on_bounce: bool = False,
    checkpoint_every_wave: bool = False,
    runs_dir: str | Path | None = None,
    update_architecture: bool = True,
    persist_session: bool = True,
) -> tuple[MissionContract, BuildRunReport]:
    """Compile and execute one existing ``BuildSession`` as one mission.

    No callback or scheduler is accepted here. The exact existing
    ``WaveExecutor`` is the only execution port, so callers cannot replace the
    canonical Effect/Attempt/Evidence chain with a parallel implementation.
    """

    if type(session) is not BuildSession:
        raise TypeError("run_mission requires an exact BuildSession")
    if type(executor) is not WaveExecutor:
        raise TypeError("run_mission requires an exact WaveExecutor")

    # Re-derive the settled WorkItem identities before constructing a Mission.
    # A changed objective/path/owner is refused here, before the executor can
    # classify or dispatch any wave.
    session.bind_work_items()
    _validate_effect_binding(executor, session, source_revision, trace_id)

    bounds = executor.effect_bounds
    mission_trace = trace_id
    if mission_trace is None and bounds is not None:
        mission_trace = bounds.trace_id
    mission = mission_contract_for_build_session(
        session,
        source_revision=source_revision,
        created_at=_created_at(),
        budget=_mission_budget(executor),
        success_criteria=success_criteria,
        trace_id=mission_trace,
        execution_limit_policy=executor.limit_policy,
    )

    report = executor.run(
        session,
        repo_root=str(repo_root) if repo_root is not None else None,
        dry_run=dry_run,
        parallel_advisory=parallel_advisory,
        resume=resume,
        stop_on_bounce=stop_on_bounce,
        checkpoint_every_wave=checkpoint_every_wave,
        runs_dir=runs_dir,
        update_architecture=update_architecture,
        persist_session=persist_session,
    )
    if type(report) is not BuildRunReport:
        raise TypeError("WaveExecutor returned a non-canonical BuildRunReport")
    if report.mission_id != mission.mission_id:
        raise ValueError("BuildRunReport mission_id does not match MissionContract")
    return mission, report
