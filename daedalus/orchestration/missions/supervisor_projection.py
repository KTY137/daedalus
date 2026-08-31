"""Disposable MissionSupervisor projection for canonical wave execution.

The production executor remains :class:`WaveExecutor`.  These functions use
the existing ``MissionSupervisor`` object only as the owner of a run directory
and its existing chained ``StateLedger`` projection.  They never consult role
harnesses and never construct or start a ``TaskAttempt``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from daedalus.atomic import publish_bytes_once
from daedalus.build import BuildSession, BuildTask
from daedalus.build_exec import BuildRunReport, WaveResult
from daedalus.ikarus_supervisor import (
    MissionSupervisor,
    StateLedger,
    SupervisorRefused,
)
from daedalus.schemas import MissionContract


_PROJECTED_ITEM_STATES = frozenset(
    {"planned", "landed", "bounced", "skipped", "refused"}
)
_TERMINAL_OUTCOMES = frozenset({"landed", "bounced", "refused"})


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _snapshot(
    supervisor: MissionSupervisor,
    session: BuildSession,
    mission: MissionContract,
) -> tuple[Path, tuple[BuildTask, ...], MissionContract]:
    if type(supervisor) is not MissionSupervisor:
        raise SupervisorRefused(
            "supervisor projection requires an exact MissionSupervisor"
        )
    if type(session) is not BuildSession:
        raise SupervisorRefused(
            "supervisor projection requires an exact BuildSession"
        )
    if type(mission) is not MissionContract:
        raise SupervisorRefused(
            "supervisor projection requires an exact MissionContract"
        )

    session.bind_work_items()
    tasks = tuple(session.tasks())
    if not tasks or any(type(task) is not BuildTask for task in tasks):
        raise SupervisorRefused(
            "supervisor projection requires exact planned BuildTask records"
        )
    retained = MissionContract.from_dict(mission.to_dict())
    if retained.digest != mission.digest:
        raise SupervisorRefused(
            "mission changed while the supervisor projection snapshotted it"
        )
    if retained.mission_id != session.mission_id:
        raise SupervisorRefused(
            "supervisor projection mission does not match the BuildSession"
        )
    if retained.objective != session.feature:
        raise SupervisorRefused(
            "supervisor projection objective does not match the BuildSession"
        )
    if tuple(sorted(retained.work_item_ids)) != tuple(
        sorted(session.work_item_ids())
    ):
        raise SupervisorRefused(
            "supervisor projection work items do not match the MissionContract"
        )

    try:
        planned_root = Path(session.repo_root).resolve()
        supervisor_root = Path(supervisor.repo_root).resolve()
        run_dir = Path(supervisor.run_dir).resolve()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise SupervisorRefused(
            "supervisor projection paths could not be resolved"
        ) from exc
    if planned_root != supervisor_root:
        raise SupervisorRefused(
            "supervisor projection repository does not match the BuildSession"
        )
    return run_dir, tasks, retained


def _projection_identity(mission: MissionContract) -> dict[str, Any]:
    """Mission substance stable across a crash-created provenance clock."""

    body = mission.to_dict()
    provenance = dict(body["provenance"])
    provenance.pop("created_at")
    body["provenance"] = provenance
    return body


def _mission_file(run_dir: Path, mission: MissionContract) -> MissionContract:
    path = run_dir / "mission.json"
    body = json.dumps(
        mission.to_dict(), indent=1, sort_keys=True, ensure_ascii=False
    ) + "\n"
    created = publish_bytes_once(path, body.encode("utf-8"))
    if created:
        return mission
    try:
        retained = MissionContract.from_dict(
            json.loads(path.read_text(encoding="utf-8"))
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SupervisorRefused(
            "existing supervisor mission projection is malformed"
        ) from exc
    if (
        retained.digest != mission.digest
        and _projection_identity(retained) != _projection_identity(mission)
    ):
        raise SupervisorRefused(
            "supervisor projection directory belongs to another mission"
        )
    # The first immutable MissionContract remains the projection subject. A
    # crash-created run_mission call owns a fresh provenance timestamp, but no
    # other contract difference is tolerated or rewritten.
    return retained


def _planned_rows(tasks: tuple[BuildTask, ...]) -> list[dict[str, Any]]:
    return [
        {
            "work_item_id": task.work_item_id,
            "objective": task.objective,
            "role": task.agent,
            "runtime_id": task.builder,
            "runtime_binding_sha256": None,
            "paths": list(task.paths),
            "status": "planned",
            "attempt_id": None,
            "attempt_receipt_sha256": None,
            "evidence_packet_sha256": None,
            "detail": None,
        }
        for task in tasks
    ]


def _base(
    mission: MissionContract,
    rows: list[dict[str, Any]],
    *,
    outcome: str | None,
) -> dict[str, Any]:
    return {
        "mission_id": mission.mission_id,
        "mission_sha256": mission.digest,
        "objective": mission.objective,
        "source_revision": mission.source_revision,
        "items": rows,
        "outcome": outcome,
    }


def _require_same_chain(
    ledger: StateLedger, mission: MissionContract
) -> dict[str, Any] | None:
    previous = ledger.last_revision
    if previous is None:
        return None
    if (
        previous.get("mission_id") != mission.mission_id
        or previous.get("mission_sha256") != mission.digest
    ):
        raise SupervisorRefused(
            "supervisor projection ledger belongs to another mission"
        )
    return previous


def begin_supervisor_projection(
    supervisor: MissionSupervisor,
    session: BuildSession,
    mission: MissionContract,
) -> dict[str, Any]:
    """Retain the mission's planned projection before WaveExecutor runs."""

    run_dir, tasks, current = _snapshot(supervisor, session, mission)
    retained = _mission_file(run_dir, current)
    ledger = StateLedger(run_dir / "ledger", resume=True)
    previous = _require_same_chain(ledger, retained)
    # A terminal projection never regresses to "planned" on crash replay.  It
    # does not skip execution: only the canonical effect ledger may do that.
    if previous is not None and previous.get("outcome") in _TERMINAL_OUTCOMES:
        return previous
    return ledger.publish_if_changed(
        _base(retained, _planned_rows(tasks), outcome=None)
    )


def _result_rows(
    tasks: tuple[BuildTask, ...],
    report: BuildRunReport,
) -> list[dict[str, Any]]:
    observed: dict[str, Mapping[str, Any]] = {}
    for wave in report.waves:
        if type(wave) is not WaveResult:
            raise SupervisorRefused(
                "supervisor projection requires exact WaveResult records"
            )
        if wave.mission_id != report.mission_id:
            raise SupervisorRefused(
                "wave/report mission identity differs in supervisor projection"
            )
        for result in wave.results:
            if not isinstance(result, Mapping):
                raise SupervisorRefused(
                    "wave result is not an object in supervisor projection"
                )
            stamp = result.get("work_item")
            if not isinstance(stamp, Mapping):
                raise SupervisorRefused(
                    "wave result lacks its canonical work-item stamp"
                )
            if stamp.get("mission_id") != report.mission_id:
                raise SupervisorRefused(
                    "wave result work-item stamp names another mission"
                )
            work_item_id = str(stamp.get("work_item_id") or "")
            if not work_item_id or work_item_id in observed:
                raise SupervisorRefused(
                    "wave result work-item identity is absent or duplicated"
                )
            observed[work_item_id] = result

    rows = _planned_rows(tasks)
    for row, task in zip(rows, tasks):
        result = observed.get(task.work_item_id)
        status = str(task.status or "planned")
        if status not in _PROJECTED_ITEM_STATES:
            status = "bounced" if result is not None else "planned"
        row["status"] = status
        if result is None:
            if status == "planned" and report.dry_run:
                row["detail"] = "dry-run plan; no external effect started"
            continue
        nested = result.get("result")
        nested = nested if isinstance(nested, Mapping) else {}
        detail = (
            result.get("reason")
            or result.get("error")
            or nested.get("note")
            or nested.get("error")
            or result.get("status")
        )
        row["detail"] = None if detail is None else str(detail)[:1000]
    return rows


def finish_supervisor_projection(
    supervisor: MissionSupervisor,
    session: BuildSession,
    mission: MissionContract,
    report: BuildRunReport,
) -> dict[str, Any]:
    """Project one returned canonical report without gaining execution power."""

    if type(report) is not BuildRunReport:
        raise SupervisorRefused(
            "supervisor projection requires an exact BuildRunReport"
        )
    if report.mission_id != mission.mission_id:
        raise SupervisorRefused(
            "supervisor projection report names another mission"
        )
    if report.feature != session.feature or Path(report.repo_root).resolve() != Path(
        session.repo_root
    ).resolve():
        raise SupervisorRefused(
            "supervisor projection report does not describe the BuildSession"
        )

    begin_supervisor_projection(supervisor, session, mission)
    run_dir, tasks, current = _snapshot(supervisor, session, mission)
    retained = _mission_file(run_dir, current)
    ledger = StateLedger(run_dir / "ledger", resume=True)
    previous = _require_same_chain(ledger, retained)
    if previous is not None and previous.get("outcome") in _TERMINAL_OUTCOMES:
        return previous
    rows = _result_rows(tasks, report)
    statuses = tuple(str(row["status"]) for row in rows)
    if report.dry_run:
        outcome = None
    elif statuses and all(status == "landed" for status in statuses):
        outcome = "landed"
    elif any(status in {"bounced", "refused"} for status in statuses):
        outcome = "bounced"
    else:
        outcome = None
    return ledger.publish_if_changed(_base(retained, rows, outcome=outcome))


__all__ = ["begin_supervisor_projection", "finish_supervisor_projection"]
