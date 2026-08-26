"""The Ikarus supervisor: one mission, one shared state ledger, role attempts.

WHAT THIS IS. The reusable half of what ``daedalus/ignition/gate1.py`` proved
as a fixture: intent -> ``MissionContract`` -> ordered work items -> attempts,
driven by a supervisor that keeps a SHARED STATE LEDGER — the coordination
object Agentic-J (arXiv 2606.02080, §3.1) puts at the centre of its system and
the master plan §7 already prescribes as artifact-first coordination
(``ProductSpec -> … -> MissionContract -> WorkItems -> Attempts -> Artifacts``).
Work packet: ``docs/work-packets/G1-IKARUS-01-supervisor-slice.md``.

WHAT THE LEDGER IS, PRECISELY — because "ledger" is a loaded word in this
tree.  It is NOT a second event store (invariant 1 has exactly one spine, and
review rule one calls a second one release-blocking).  It is a PROJECTION:
every state change writes one immutable, content-addressed revision file, and
each revision names ``previous_ledger_sha256``, so the chain is append-only
and tamper-evident without ever being authoritative.  The truth stays where it
already lives — the ``MissionContract``, the ``AttemptReceipt``s and the spine
ledger the attempts already write.  Deleting the whole ledger directory loses
a convenient view and no fact.

WHAT THE SUPERVISOR IS NOT, in v1, on purpose:

* not an LLM.  Planning is caller-declared work items, the same reviewable-
  draft posture ``ikarus_chat`` v1 took.  A model may PROPOSE plans later; the
  contract layer here does not change when it does.
* not a chat.  It accepts no transcript and stores none — the ledger carries
  the objective string and typed status, nothing conversational (plan §7:
  "Chat is an interface, not orchestration state").
* not a door.  There is no CLI tail and no module-level effect; every write
  lands under the caller-supplied run directory, and the attempts themselves
  go through ``TaskAttempt`` — the same guarded path everything else uses.
  Wiring a provider-backed role arrives with caller-injection half two, not
  here.

ROLES.  Agentic-J gives each subagent a targeted toolset; here a role is a
:class:`RoleHarness` — a runner factory and a gate factory keyed by name.  The
supervisor refuses a plan naming a role it was not given BEFORE any attempt
starts, because "the registry did not know it" must never be discovered
halfway through a half-executed mission.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .build import BuildSession, BuildTask, Wave
from .schemas import MissionContract, ResourceBudget
from .spine.attempt import GateResult, TaskAttempt, TaskSpec
from .spine.receipts import mission_contract_for_build_session

LEDGER_SCHEMA = "daedalus-ikarus-state-ledger/1"

#: Terminal work-item states the ledger may carry.  A coarse lifecycle on
#: purpose, mirroring ``BuildTask.status`` — anything finer rides on the
#: attempt result, which the revision references by digest instead of copying.
_ITEM_STATES = ("planned", "dispatched", "landed", "bounced", "skipped", "refused")


class SupervisorRefused(RuntimeError):
    """The mission cannot start (or continue) and the reason is named."""


class StateLedgerBroken(RuntimeError):
    """The revision chain on disk does not verify."""


@dataclass(frozen=True)
class RoleHarness:
    """What one role is allowed to bring to an attempt.

    ``runner_factory(item)`` returns the ``runner(ctx)`` callable and
    ``gate_factory(item)`` the ``gate(ctx)`` callable that
    :class:`TaskAttempt` consumes.  Factories rather than callables so a role
    can specialise per work item (Agentic-J's coder consults per-plugin
    skills; ours consults the item) without the supervisor knowing how.
    """

    role: str
    runner_factory: Callable[["PlannedItem"], Callable[[Any], dict]]
    gate_factory: Callable[["PlannedItem"], Callable[[Any], GateResult]]


@dataclass(frozen=True)
class PlannedItem:
    """One caller-declared work item: what, where, and which role does it."""

    objective: str
    role: str
    paths: tuple[str, ...]
    gate_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not str(self.objective).strip():
            raise ValueError("a planned item needs a non-empty objective")
        if not str(self.role).strip():
            raise ValueError("a planned item needs a role")
        if not self.paths:
            raise ValueError("a planned item must declare its target paths")
        object.__setattr__(self, "paths", tuple(str(p) for p in self.paths))
        object.__setattr__(self, "gate_paths", tuple(str(p) for p in self.gate_paths))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical(body: Mapping[str, Any]) -> str:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# --------------------------------------------------------------------------- #
# the state ledger                                                             #
# --------------------------------------------------------------------------- #
class StateLedger:
    """Immutable, chained revisions of one mission's coordination state.

    Every :meth:`publish` writes ``<dir>/<seq:04d>-<digest12>.json`` holding
    the FULL state at that moment plus ``previous_ledger_sha256`` — full
    snapshots, not deltas, so a reader needs one file to know where the
    mission stands and the chain only to know nobody rewrote history.
    ``revision_sha256`` is over the body with the digest field removed, the
    same recipe every receipt in this tree uses.
    """

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._sequence = 0
        self._previous = ""

    def publish(self, state: Mapping[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "schema": LEDGER_SCHEMA,
            "sequence": self._sequence,
            "previous_ledger_sha256": self._previous,
            "published_at": _utc_now(),
            **{k: v for k, v in state.items()},
        }
        digest = hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()
        body["revision_sha256"] = digest
        path = self.directory / f"{self._sequence:04d}-{digest[:12]}.json"
        # ``x`` so a sequence collision (two supervisors on one directory) is
        # a loud error instead of one silently absorbing the other's history.
        with path.open("x", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(body, indent=1, sort_keys=True, ensure_ascii=False))
            fh.write("\n")
        self._sequence += 1
        self._previous = digest
        return body


def verify_state_ledger(directory: str | Path) -> tuple[dict[str, Any], ...]:
    """Re-derive every digest and re-walk the chain; return the revisions.

    Raises :class:`StateLedgerBroken` on a tampered body, a broken link, a
    gap, or an empty directory — an empty ledger is "could not verify", never
    "verified, nothing there".
    """

    directory = Path(directory)
    paths = sorted(directory.glob("[0-9][0-9][0-9][0-9]-*.json"))
    if not paths:
        raise StateLedgerBroken(f"no ledger revisions under {directory}")
    revisions: list[dict[str, Any]] = []
    previous = ""
    for expected_seq, path in enumerate(paths):
        body = json.loads(path.read_text(encoding="utf-8"))
        claimed = str(body.get("revision_sha256", ""))
        subject = {k: v for k, v in body.items() if k != "revision_sha256"}
        derived = hashlib.sha256(_canonical(subject).encode("utf-8")).hexdigest()
        if derived != claimed:
            raise StateLedgerBroken(f"{path.name}: body does not match its digest")
        if int(body.get("sequence", -1)) != expected_seq:
            raise StateLedgerBroken(
                f"{path.name}: sequence {body.get('sequence')} where "
                f"{expected_seq} was expected — a revision is missing or reordered"
            )
        if str(body.get("previous_ledger_sha256", "")) != previous:
            raise StateLedgerBroken(f"{path.name}: chain link does not match")
        previous = claimed
        revisions.append(body)
    return tuple(revisions)


# --------------------------------------------------------------------------- #
# planning: caller intent -> canonical mission                                 #
# --------------------------------------------------------------------------- #
def plan_mission(
    objective: str,
    *,
    repo_root: str | Path,
    items: Sequence[PlannedItem],
    base_revision: str,
    budget: ResourceBudget,
    success_criteria: Sequence[str],
    project: str = "ikarus-supervisor",
    trace_id: str | None = None,
) -> tuple[BuildSession, MissionContract]:
    """Compile intent into the one session/mission pair the kernel accepts.

    Nothing here is invented: ``BuildSession.__post_init__`` binds the
    deterministic ``mission_id`` and one ``work_item_id`` per task (same plan,
    same ids — that is what makes reruns comparable), and
    ``mission_contract_for_build_session`` binds the effect-registry policy
    digest, so the mission and its attempts name ONE policy.  ``created=""``
    for the reason the ignition slice documents: an id that moves with the
    clock cannot be replayed.
    """

    if not items:
        raise SupervisorRefused("a mission with no work items is not a mission")
    # THE SLUG IS A FUNCTION OF THE PLAN, and this line exists because the
    # first acceptance run proved the obvious default wrong: a static slug
    # plus ``created=""`` means EVERY supervisor mission is
    # ``mission-ikarus-supervisor`` — two unrelated plans sharing one mission
    # identity, which is exactly the collision ``mission_id_for_session``'s
    # own docstring warns about ("a caller that cares supplies mission_id").
    # A timestamp would fix uniqueness and break replay; a content digest
    # gives both: same plan -> same id, different plan -> different id.
    plan_digest = hashlib.sha256(
        _canonical({
            "objective": objective,
            "items": [
                {"objective": i.objective, "role": i.role, "paths": list(i.paths)}
                for i in items
            ],
        }).encode("utf-8")
    ).hexdigest()
    tasks = [
        BuildTask(
            objective=item.objective,
            agent="daedalus.ikarus_supervisor",
            category="renovation",
            lane="deterministic",
            tier="none",
            builder=f"role:{item.role}",
            frontier=False,
            paths=list(item.paths),
        )
        for item in items
    ]
    session = BuildSession(
        feature=objective,
        repo_root=str(Path(repo_root).resolve()),
        project=project,
        waves=[Wave(index=0, tasks=tasks)],
        slug=f"ikarus-{plan_digest[:12]}",
        created="",
        max_workers=1,
    )
    mission = mission_contract_for_build_session(
        session,
        source_revision=base_revision,
        created_at=_utc_now(),
        budget=budget,
        success_criteria=tuple(success_criteria),
        trace_id=trace_id or session.mission_id,
    )
    return session, mission


# --------------------------------------------------------------------------- #
# the supervisor                                                               #
# --------------------------------------------------------------------------- #
@dataclass
class MissionSupervisor:
    """Drive one planned mission through role attempts, ledger revision by
    ledger revision.

    ``roles`` is the complete harness registry this mission may use.  It is
    checked against the WHOLE plan before the first dispatch: a plan that
    names an unknown role is refused with nothing run, because half a mission
    executed under a misspelt role name is the expensive way to find a typo.
    """

    repo_root: Path
    run_dir: Path
    roles: Mapping[str, RoleHarness]
    gate_timeout_s: float = 300.0
    fail_fast: bool = True
    #: Populated by :meth:`run`.
    results: list[Any] = field(default_factory=list)

    def run(
        self,
        session: BuildSession,
        mission: MissionContract,
        items: Sequence[PlannedItem],
    ) -> dict[str, Any]:
        tasks = session.waves[0].tasks
        if len(tasks) != len(items):
            raise SupervisorRefused(
                f"plan drift: session carries {len(tasks)} tasks for "
                f"{len(items)} planned items"
            )

        # REFUSE THE WHOLE PLAN FIRST.  One pass over every role name before
        # any attempt exists; the refusal lands in the ledger so a reader of
        # the run directory sees WHY nothing ran.
        ledger = StateLedger(self.run_dir / "ledger")
        unknown = sorted(
            {item.role for item in items} - set(self.roles.keys())
        )
        rows = [
            {
                "work_item_id": task.work_item_id,
                "objective": item.objective,
                "role": item.role,
                "paths": list(item.paths),
                "status": "planned",
                "attempt_id": None,
                "attempt_receipt_sha256": None,
                "evidence_packet_sha256": None,
                "detail": None,
            }
            for task, item in zip(tasks, items)
        ]
        base = {
            "mission_id": mission.mission_id,
            "mission_sha256": mission.digest,
            "objective": mission.objective,
            "source_revision": mission.source_revision,
            "items": rows,
            "outcome": None,
        }
        # The mission contract itself is retained beside the ledger — the
        # ledger references it by digest and never restates it.
        contract_path = self.run_dir / "mission.json"
        if not contract_path.exists():
            contract_path.write_text(
                json.dumps(mission.to_dict(), indent=1, sort_keys=True),
                encoding="utf-8",
                newline="\n",
            )
        ledger.publish(base)

        if unknown:
            for row in rows:
                if row["role"] in unknown:
                    row["status"] = "refused"
                    row["detail"] = f"role {row['role']!r} is not in the harness registry"
                else:
                    row["status"] = "skipped"
                    row["detail"] = "mission refused before dispatch"
            base["outcome"] = "refused"
            ledger.publish(base)
            raise SupervisorRefused(
                "the plan names roles this supervisor was not given: "
                + ", ".join(unknown)
            )

        outcome = "landed"
        for index, (task, item) in enumerate(zip(tasks, items)):
            if outcome != "landed" and self.fail_fast:
                task.status = "planned"
                rows[index]["status"] = "skipped"
                rows[index]["detail"] = "fail-fast: an earlier work item bounced"
                ledger.publish(base)
                continue
            harness = self.roles[item.role]
            rows[index]["status"] = task.status = "dispatched"
            ledger.publish(base)

            spec = TaskSpec(
                task_id=task.work_item_id,
                instruction=item.objective,
                target_paths=item.paths,
                gate_paths=item.gate_paths,
                gate_timeout_s=float(self.gate_timeout_s),
                metadata={
                    "mission_id": mission.mission_id,
                    "work_item_id": task.work_item_id,
                    "role": item.role,
                    "operator": "daedalus.ikarus_supervisor",
                },
            )
            attempt = TaskAttempt(
                spec,
                runner=harness.runner_factory(item),
                gate=harness.gate_factory(item),
                repo_root=self.repo_root,
                ledger_path=self.run_dir / "spine.sqlite3",
                artifact_dir=self.run_dir / "artifacts",
                mission_id=mission.mission_id,
                budget=ResourceBudget(max_wall_time_s=int(self.gate_timeout_s) * 2),
            )
            result = attempt.run()
            self.results.append(result)
            task.mark("landed" if result.ok else "bounced", dict(result.to_dict()))
            rows[index]["status"] = task.status
            rows[index]["attempt_id"] = result.branch
            # Digests, never copies: the ledger row points at the canonical
            # records by hash, exactly the posture the ignition receipt takes.
            contracts = result.contract_set()
            rows[index]["attempt_receipt_sha256"] = getattr(
                getattr(contracts, "receipt", None), "digest", None
            )
            rows[index]["evidence_packet_sha256"] = getattr(
                getattr(contracts, "evidence", None), "digest", None
            )
            if not result.ok:
                rows[index]["detail"] = f"state={result.state} error={result.error}"
                outcome = "bounced"
            ledger.publish(base)

        base["outcome"] = outcome
        final = ledger.publish(base)
        return final


__all__ = [
    "LEDGER_SCHEMA",
    "MissionSupervisor",
    "PlannedItem",
    "RoleHarness",
    "StateLedger",
    "StateLedgerBroken",
    "SupervisorRefused",
    "plan_mission",
    "verify_state_ledger",
]
