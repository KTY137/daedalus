"""Build-session abstraction -- the coordination layer that turns ONE feature
objective into a multi-wave build plan the crew can execute.

Where :func:`daedalus.kairos.scheduler.Ikarus.spawn` plans a single objective across the
*local* bench, a **build session** is the frontier-first counterpart: it owns
one feature across several bounded **waves**, tracks who owns each subtask, and
routes implementation to a frontier builder (Claude) while sending only routine
work (docs/tests) to the local Ollama bench.

This module is deterministic and additive. It reuses the existing seams and
invents no new ones:

  * :func:`daedalus.kairos.decompose.decompose`  -- feature -> scoped subtasks.
  * :func:`daedalus.router.route_task`    -- subtask -> owning agent.
  * :func:`daedalus.categories.preset_for` -- owning agent -> {lane, tier}.
  * :class:`daedalus.kairos.scheduler.Ikarus`       -- wave sizing (``max_workers``) and
    the project's ``active_agents``.

**Frontier-first topology.** The category preset's ``lane`` decides the builder:
a local lane (``local`` / ``local_only``) keeps the subtask on the Ollama bench;
any other lane (``claude`` / ``auto``) escalates it to the frontier builder.
Routine categories go local by tagging their category ``lane`` as ``local``.

Nothing here writes to a repo, drives a provider, or bypasses a lane gate; a
build session is planning *state around* the harness, not a replacement for it.

Execution is a separate concern, deliberately: see :mod:`daedalus.build_exec`
for the wave executor that takes a saved :class:`BuildSession` and actually
runs its waves through :class:`daedalus.kairos.scheduler.KairosScheduler`,
collecting results back onto each :class:`BuildTask`.

**These nouns are views of the canonical chain, not rivals to it.** Master
plan §7 fixes one chain -- ``MissionContract -> WorkItems -> Attempts ->
Artifacts -> EvidencePacket`` -- and this module's three nouns bind onto it:

  * :class:`BuildSession` is ONE ``MissionContract`` run (``mission_id``);
  * :class:`Wave` is an ordered batch of WorkItems (``index`` carries the
    order the mission's sorted ``work_item_ids`` tuple cannot);
  * :class:`BuildTask` is ONE WorkItem (``work_item_id``, derived by
    :func:`daedalus.schemas.derive_work_item_id`);
  * a dispatched task is an Attempt, and the existing ``AttemptContract``
    already carries ``mission_id`` + ``task_id`` -- nothing new is minted here.

No ``WorkItem`` class was added: ``MissionContract.work_item_ids`` already IS
that layer, so a second dataclass would have been a second contract for the
thing the mission already names (Invariant 1). The mission itself is compiled
by :func:`daedalus.spine.receipts.mission_contract_for_build_session`, which
lives in the spine because a mission needs a policy digest and a budget, and
those are not planning state. The reconciliation, including what is deferred
to :mod:`daedalus.build_exec` and :mod:`daedalus.loop`, is written down in
``docs/design/BUILD_VOCABULARY_RECONCILIATION_2026-08-22.md``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .categories import preset_for
from .kairos.decompose import decompose
from .kairos.scheduler import KairosScheduler
from .router import route_task
from .schemas import derive_work_item_id, work_item_identity_sha256

ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "runs" / "build"

# Which builder runs a subtask, driven off the category preset's lane.
FRONTIER_BUILDER = "claude"       # frontier lane -- the senior builder crew
LOCAL_BUILDER = "ollama"          # the cheap local bench
LOCAL_LANES = ("local", "local_only")


def _slug(text: str) -> str:
    """Filesystem-safe slug, mirroring ``file_bridge.enqueue``'s convention."""
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in text)[:48].strip("-") or "build"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


#: The provenance key every per-task dispatch result is stamped with. Namespaced
#: (one key, a mapping under it) exactly like ``build_exec``'s ``effect_lease``
#: stamp, so binding a result to its mission can never collide with a key
#: ``KairosScheduler.dispatch`` already produces.
WORK_ITEM_KEY = "work_item"


def mission_id_for_session(slug: str, created: str = "") -> str:
    """The mission id a :class:`BuildSession` gets when its caller names none.

    ``mission-<slug>[-<created>]``, reusing the ``mission-`` prefix
    :func:`daedalus.spine.receipts.mission_contract_for_candidate` already
    mints, so the build path does not invent a THIRD spelling of "mission"
    beside the picker's and the loop's.

    Deterministic given the session, which is what a work item id needs. It is
    not globally unique: two builds of the same feature started in the same
    second collide. A caller that cares supplies ``mission_id`` explicitly --
    ``daedalus.loop`` has a ``run_id`` and should pass it, so the wave lease's
    ``EffectBounds.mission_id`` and the session's mission are ONE string (that
    one-line hunk is deferred to the loop's owner; see the reconciliation doc).

    SANITISED, not validated. ``schemas._identifier`` refuses a mission id with
    a stray character, and this function runs inside ``BuildSession``'s
    constructor -- so raising here would mean an unusual feature name could
    abort a build before it planned anything. A slug is a display convenience;
    it is not allowed to be the reason a build does not happen. Anything
    outside the identifier grammar is folded to ``-`` exactly as
    ``spine.receipts._identifier_fragment`` folds a candidate's task id.
    """
    fragment = "".join(
        ch if (ch.isalnum() or ch in "._:/-") else "-" for ch in str(slug or "")
    ).strip("-") or "build"
    tail = "".join(
        ch if (ch.isalnum() or ch in "._:/-") else "-" for ch in str(created or "")
    ).strip("-")
    return f"mission-{fragment}{'-' + tail if tail else ''}"[:200]


class WorkItemIdentityError(RuntimeError):
    """A bound work item's substance changed under its id.

    Raised by :meth:`BuildSession.bind_work_items` when a re-plan would derive a
    different id for a task that already carries one. It is an error rather
    than a re-stamp because the id is what a receipt, a wave lease and an
    ``AttemptContract`` all name: silently re-deriving it would leave those
    records pointing at a work item whose objective, owner or paths are no
    longer what they were, and silently KEEPING it -- which is what the code
    did -- leaves the plan and the id describing two different jobs. Neither is
    a state a caller can fix without being told.
    """


def assign_builder(lane: str) -> tuple[str, bool]:
    """Map a category preset ``lane`` to ``(builder, frontier)``.

    Frontier-first: only the explicitly-local lanes stay on the bench; every
    other lane (``claude``/``auto``) escalates to the frontier builder."""
    if lane in LOCAL_LANES:
        return LOCAL_BUILDER, False
    return FRONTIER_BUILDER, True


@dataclass
class BuildTask:
    """One routed subtask within a wave, with its owner + category assignment."""
    objective: str
    agent: str                 # owning specialist (from router.route_task)
    category: str              # category id tagged on the owning agent
    lane: str                  # suggested lane (from categories.preset_for)
    tier: str                  # suggested model tier (from categories.preset_for)
    builder: str               # frontier builder (claude) | local bench (ollama)
    frontier: bool             # True -> frontier lane; False -> local bench
    paths: list[str] = field(default_factory=list)
    status: str = "planned"    # planned | dispatched | landed | bounced
    # The raw per-task result dict from the last KairosScheduler.dispatch()
    # call that touched this task (worker/lane/mode/status/wrote/reason -- see
    # dispatch()'s docstring in daedalus/kairos/scheduler.py for the shape).
    # `status` above intentionally stays a coarse 4-word lifecycle; nothing
    # more specific ("escalated_after_verify_fail" vs "escalate_to_claude" vs
    # a bench bounce) is lost -- it rides here instead. Populated only by
    # daedalus.build_exec.WaveExecutor; empty for a plan that never ran.
    last_result: dict[str, Any] = field(default_factory=dict)
    # ---- CANONICAL IDENTITY (plan §7) ------------------------------------- #
    # This task's WorkItem id and the mission it serves. Appended at the END of
    # the dataclass on purpose: every live construction site uses keywords, but
    # inserting a field earlier would still silently re-bind any positional
    # caller that appears later. Empty until the owning BuildSession binds them
    # (BuildSession.__post_init__), which is also what makes a hand-built
    # BuildTask usable in a test without knowing about missions.
    mission_id: str = ""
    work_item_id: str = ""
    #: The FULL digest of the substance this task's id was derived from, frozen
    #: at bind time. The id carries only twelve characters of it, which is
    #: enough for two plans to be distinct and not enough for a mismatch report
    #: to say what moved. Appended last, for the same positional-safety reason
    #: as the two ids above.
    work_item_identity_sha256: str = ""

    def work_item_stamp(self) -> dict[str, Any]:
        """This task's canonical identity, as a receipt-shaped mapping."""
        return {"mission_id": self.mission_id, "work_item_id": self.work_item_id}

    def mark(self, status: str, last_result: dict[str, Any] | None = None) -> None:
        """Advance this task's lifecycle in place. ``status`` should be one of
        planned|dispatched|landed|bounced. Pass the raw dispatch result dict
        as ``last_result`` to keep the full-fidelity detail alongside the
        coarse status -- never called with a mismatched pair by
        :mod:`daedalus.build_exec`, but nothing here enforces that; it is a
        plain setter, not a state machine.

        IT STAMPS THE RESULT IN PLACE, and that is load-bearing rather than
        tidy. ``build_exec`` puts the SAME dict object into ``WaveResult.results``
        that it hands here, so stamping it is what makes a wave receipt name the
        mission its rows belong to (Invariant 7) without editing the executor.
        The same file already mutates these dicts in place for
        ``result["effect_lease"]``, so this is that file's own idiom, not a new
        one. Stamping is skipped for an unbound task rather than writing empty
        ids, so an unstamped row reads as "this session bound nothing" instead
        of as a mission whose id happens to be the empty string.

        WHAT THIS DOES NOT REACH: rows that never pass through ``mark`` with a
        result -- a dry-run wave (which ``continue``s before the call) and the
        two refusal branches (which call ``mark("bounced")`` with no dict, over
        a separately built ``refused`` list). Those need the deferred
        ``build_exec`` hunk; see the reconciliation doc.
        """
        self.status = status
        if last_result is not None:
            self.last_result = last_result
        if isinstance(last_result, dict) and self.mission_id and self.work_item_id:
            last_result[WORK_ITEM_KEY] = self.work_item_stamp()

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "agent": self.agent,
            "category": self.category,
            "lane": self.lane,
            "tier": self.tier,
            "builder": self.builder,
            "frontier": self.frontier,
            "paths": list(self.paths),
            "status": self.status,
            "last_result": dict(self.last_result),
            "mission_id": self.mission_id,
            "work_item_id": self.work_item_id,
            "work_item_identity_sha256": self.work_item_identity_sha256,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BuildTask":
        return cls(
            objective=d["objective"],
            agent=d["agent"],
            category=d.get("category", ""),
            lane=d.get("lane", "auto"),
            tier=d.get("tier", "sonnet"),
            builder=d.get("builder", FRONTIER_BUILDER),
            frontier=bool(d.get("frontier", True)),
            paths=list(d.get("paths", [])),
            status=d.get("status", "planned"),
            last_result=dict(d.get("last_result", {})),
            # A snapshot written before the binding existed reloads with empty
            # ids and is re-bound by BuildSession.__post_init__ -- which will
            # derive the SAME ids, because the derivation is a function of the
            # plan, not of when it ran.
            mission_id=str(d.get("mission_id", "") or ""),
            work_item_id=str(d.get("work_item_id", "") or ""),
            work_item_identity_sha256=str(
                d.get("work_item_identity_sha256", "") or ""),
        )


@dataclass
class Wave:
    """A bounded batch of subtasks that may run concurrently."""
    index: int
    tasks: list[BuildTask] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"index": self.index, "tasks": [t.to_dict() for t in self.tasks]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Wave":
        return cls(index=int(d["index"]),
                   tasks=[BuildTask.from_dict(t) for t in d.get("tasks", [])])


@dataclass
class BuildSession:
    """One feature tracked across waves -- the unit of a coordinated build."""
    feature: str
    repo_root: str
    project: str | None
    waves: list[Wave] = field(default_factory=list)
    slug: str = ""
    created: str = ""
    max_workers: int = 3
    snapshot_path: str | None = None
    #: The ONE ``MissionContract`` this session runs (plan §7). Appended last
    #: for the same positional-safety reason as ``BuildTask.mission_id``.
    mission_id: str = ""

    def __post_init__(self) -> None:
        """Bind this session to one mission and every task to one work item.

        In ``__post_init__`` rather than in :func:`plan_build` because
        ``BuildSession`` is constructed DIRECTLY as well -- ``daedalus.loop``'s
        ``_session_for`` wraps one picker candidate as a one-task session, and
        that path drives the real builds. Binding at construction means the
        loop's sessions are canonical without the loop lane editing a line.

        Idempotent for an UNCHANGED plan: re-deriving a settled id yields the
        same string, so a reloaded snapshot keeps the ids it was persisted with.
        A plan whose substance moved under a bound id raises instead -- see
        :meth:`bind_work_items`.
        """
        self.bind_work_items()

    def bind_work_items(self) -> None:
        """Stamp the mission id and one deterministic work item id per task.

        The ordinal is the session-FLAT task index in wave order, so it is
        unique across the whole session (a per-wave index would collide between
        waves, and ``MissionContract.work_item_ids`` rejects duplicates). The
        hashed identity is the task's substance -- objective, owner, declared
        paths -- so the id is bound to what was planned, not merely to where it
        sat in the list.

        IT RE-DERIVES EVERY TIME, and that is the fix rather than a cost. This
        method used to write an id only into a task that had none, which made
        it silently correct for the reload case it was written for and silently
        WRONG for the case that actually happens: a session whose tasks are
        re-planned, re-ordered, re-scoped or re-routed in place, and then bound
        again. Every such task kept the id derived from the plan it no longer
        is, so the mission's ``work_item_ids``, the wave lease and the
        ``AttemptContract`` all named a work item whose objective, owner or
        declared paths had moved -- provenance (Invariant 7) reading exactly
        backwards, and undetectable from the records themselves because the id
        is a hash of a body nobody kept.

        Now the body IS kept (``work_item_identity_sha256``), so a re-bind can
        tell the two cases apart: an unchanged plan re-derives the same digest
        and nothing happens, and a changed one raises
        :class:`WorkItemIdentityError` naming both digests. A caller that
        deliberately re-plans clears the ids first; a caller that did not mean
        to gets told which task moved instead of a receipt that quietly lies.
        """
        if not self.mission_id:
            self.mission_id = mission_id_for_session(self.slug, self.created)
        for ordinal, task in enumerate(self.tasks()):
            if task.mission_id and task.mission_id != self.mission_id:
                raise WorkItemIdentityError(
                    f"build task {ordinal} is bound to mission "
                    f"{task.mission_id!r} but this session is "
                    f"{self.mission_id!r}; a task cannot serve two missions"
                )
            task.mission_id = self.mission_id
            identity = (task.objective, task.agent, *sorted(task.paths))
            digest = work_item_identity_sha256(
                self.mission_id, ordinal=ordinal, identity=identity)
            work_item_id = derive_work_item_id(
                self.mission_id, ordinal=ordinal, identity=identity)
            if task.work_item_id and task.work_item_id != work_item_id:
                raise WorkItemIdentityError(
                    f"build task {ordinal} ({task.objective!r}) is already bound "
                    f"to work item {task.work_item_id!r}, but its substance now "
                    f"derives {work_item_id!r}: the plan changed under a settled "
                    f"id (identity {task.work_item_identity_sha256 or 'unrecorded'}"
                    f" -> {digest}). Clear work_item_id to re-plan deliberately."
                )
            if (task.work_item_identity_sha256
                    and task.work_item_identity_sha256 != digest):
                raise WorkItemIdentityError(
                    f"build task {ordinal} ({task.objective!r}) keeps work item "
                    f"{task.work_item_id!r} while its recorded identity "
                    f"{task.work_item_identity_sha256} no longer matches the "
                    f"planned substance {digest}"
                )
            task.work_item_id = work_item_id
            task.work_item_identity_sha256 = digest

    def work_item_ids(self) -> tuple[str, ...]:
        """This session's work items, in plan order.

        The mission's own tuple is sorted and de-duplicated by the contract;
        this is the ordered view, which is what a wave needs and what the
        mission deliberately does not carry.
        """
        return tuple(t.work_item_id for t in self.tasks())

    def tasks(self) -> list[BuildTask]:
        return [t for w in self.waves for t in w.tasks]

    def summary(self) -> dict[str, int]:
        all_tasks = self.tasks()
        frontier = sum(1 for t in all_tasks if t.frontier)
        return {
            "subtasks": len(all_tasks),
            "waves": len(self.waves),
            "frontier": frontier,
            "local": len(all_tasks) - frontier,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "repo_root": self.repo_root,
            "project": self.project,
            "slug": self.slug,
            "created": self.created,
            "max_workers": self.max_workers,
            "mission_id": self.mission_id,
            "summary": self.summary(),
            "waves": [w.to_dict() for w in self.waves],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BuildSession":
        return cls(
            feature=d["feature"],
            repo_root=d["repo_root"],
            project=d.get("project"),
            waves=[Wave.from_dict(w) for w in d.get("waves", [])],
            slug=d.get("slug", ""),
            created=d.get("created", ""),
            max_workers=int(d.get("max_workers", 3)),
            snapshot_path=d.get("snapshot_path"),
            mission_id=str(d.get("mission_id", "") or ""),
        )

    def save(self, runs_dir: str | Path | None = None, *, update_architecture: bool = True) -> Path:
        """Persist a session snapshot under ``runs/build/<slug>-<ts>.json``.

        After a build session lands, the bookkeeper refreshes the living
        ``docs/architecture.html`` artifact (+ a history snapshot if the
        architecture changed). Best-effort: a bookkeeping hiccup never fails a
        build. Pass ``update_architecture=False`` to skip (e.g. in unit tests)."""
        directory = Path(runs_dir) if runs_dir is not None else RUN_DIR
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.slug}-{_stamp()}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        self.snapshot_path = str(path)
        if update_architecture:
            try:
                from .bookkeeper import update as _bk_update
                _bk_update(note=f"after build: {self.feature[:60]}")
            except Exception:
                pass  # never let bookkeeping break a build session
        return path


def load_session(path: str | Path) -> BuildSession:
    """Reload a persisted session snapshot (round-trips :meth:`BuildSession.save`)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    session = BuildSession.from_dict(data)
    session.snapshot_path = str(path)
    return session


def _chunk_waves(tasks: list[BuildTask], max_workers: int) -> list[Wave]:
    """Bounded wave sizing, mirroring ``Ikarus.plan``: at most ``max_workers``
    tasks per wave, order preserved.

    NOTE what this does NOT do: nothing here checks that tasks landing in the
    same wave target disjoint paths -- see :func:`wave_path_conflicts` for a
    read-only diagnostic over the result. Harmless today (advisory-only
    concurrent execution touches no files); see that function's docstring for
    why it stops mattering less, not more, once concurrent writes exist.
    """
    size = max(1, max_workers)
    waves: list[Wave] = []
    for i in range(0, len(tasks), size):
        waves.append(Wave(index=len(waves), tasks=tasks[i:i + size]))
    return waves


def wave_path_conflicts(wave: Wave) -> list[dict[str, Any]]:
    """Diagnostic ONLY -- pairs of tasks within one wave whose declared
    ``paths`` overlap. Mirrors the caveat already on
    ``daedalus.kairos.scheduler._paths_overlap``: an agentic worker is not
    bound by the paths string it was handed, so disjoint declared paths are
    not proof two tasks stay out of each other's way, and an overlap here is
    not proof they collide -- this is a planning-time smell, nothing load-
    bearing.

    Harmless for advisory (read-only) work, which is the only thing this
    session's waves run concurrently today (see ``daedalus.build_exec``).
    It would matter more, not less, for writes: two tasks in the SAME wave
    both declaring the same path is exactly the shared-file clobber
    ``KairosScheduler.dispatch`` refuses to risk even for merely CONCURRENT
    writes in general (see its ``can_parallel`` comment) -- and per-task
    worktree isolation (``KairosScheduler.gate_concurrent_writes``) fixes the
    ROLLBACK-clobber hazard by giving each write its own checkout, but does
    not by itself make two tasks editing the same file semantically
    compatible; that is what ``promote_candidates``'s cumulative re-gating
    and re-attempt-on-stale-base logic is for. Returns one entry per repeat
    sighting of a path (first owner only), not every pairwise combination.
    """
    conflicts: list[dict[str, Any]] = []
    first_owner: dict[str, int] = {}
    for i, task in enumerate(wave.tasks):
        for p in task.paths:
            key = str(p).replace("\\", "/")
            if key in first_owner:
                j = first_owner[key]
                conflicts.append({
                    "path": key,
                    "task_indices": [j, i],
                    "objectives": [wave.tasks[j].objective, task.objective],
                })
            else:
                first_owner[key] = i
    return conflicts


def plan_build(
    feature: str,
    repo_root: str,
    project: str | None = None,
    *,
    persist: bool = True,
    runs_dir: str | Path | None = None,
    update_architecture: bool = True,
    mission_id: str | None = None,
) -> BuildSession:
    """Plan a multi-wave build for ``feature``.

    Decompose the feature, route each subtask to its owning agent, derive that
    agent's category preset (lane/tier), assign a frontier or local builder off
    the lane, and group the subtasks into bounded waves. Deterministic apart
    from :func:`decompose`'s optional local-model call (which has a deterministic
    fallback); no provider write happens here.

    ``mission_id`` names the ONE mission this session runs. Omitted, it is
    derived by :func:`mission_id_for_session`; a caller that already owns a run
    identity (the loop's ``run_id``) should pass it, so the wave lease and the
    session cannot name two different missions for one build.
    """
    # Reuse Ikarus purely for its wave sizing + active_agents resolution: with
    # a project it loads the team's max_workers/active_agents; without one it
    # keeps the safe defaults. No spawning happens.
    foreman = KairosScheduler(project=project)
    max_workers = foreman.max_workers
    active_agents = foreman.active_agents

    subtasks = decompose(feature, repo_root)

    build_tasks: list[BuildTask] = []
    for sub in subtasks:
        objective = sub["objective"]
        paths = list(sub.get("paths", []))
        agent = route_task(objective, paths, repo_root=repo_root, active_agents=active_agents)
        category = agent.get("category", "") or ""
        preset = preset_for(agent, repo_root)
        lane, tier = preset["lane"], preset["tier"]
        builder, frontier = assign_builder(lane)
        build_tasks.append(BuildTask(
            objective=objective,
            agent=agent.get("name", "unknown"),
            category=category,
            lane=lane,
            tier=tier,
            builder=builder,
            frontier=frontier,
            paths=paths,
        ))

    session = BuildSession(
        feature=feature,
        repo_root=repo_root,
        project=project,
        waves=_chunk_waves(build_tasks, max_workers),
        slug=_slug(feature),
        created=_stamp(),
        max_workers=max_workers,
        mission_id=mission_id or "",
    )
    if persist:
        session.save(runs_dir, update_architecture=update_architecture)
    return session
