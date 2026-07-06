"""Build-session abstraction -- the coordination layer that turns ONE feature
objective into a multi-wave build plan the crew can execute.

Where :func:`daedalus.ikarus.Ikarus.spawn` plans a single objective across the
*local* bench, a **build session** is the frontier-first counterpart: it owns
one feature across several bounded **waves**, tracks who owns each subtask, and
routes implementation to a frontier builder (Claude) while sending only routine
work (docs/tests) to the local Ollama bench.

This module is deterministic and additive. It reuses the existing seams and
invents no new ones:

  * :func:`daedalus.decompose.decompose`  -- feature -> scoped subtasks.
  * :func:`daedalus.router.route_task`    -- subtask -> owning agent.
  * :func:`daedalus.categories.preset_for` -- owning agent -> {lane, tier}.
  * :class:`daedalus.ikarus.Ikarus`       -- wave sizing (``max_workers``) and
    the project's ``active_agents``.

**Frontier-first topology.** The category preset's ``lane`` decides the builder:
a local lane (``local`` / ``local_only``) keeps the subtask on the Ollama bench;
any other lane (``claude`` / ``auto``) escalates it to the frontier builder.
Routine categories go local by tagging their category ``lane`` as ``local``.

Nothing here writes to a repo, drives a provider, or bypasses a lane gate; a
build session is planning *state around* the harness, not a replacement for it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .categories import preset_for
from .decompose import decompose
from .ikarus import Ikarus
from .router import route_task

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
    tasks per wave, order preserved."""
    size = max(1, max_workers)
    waves: list[Wave] = []
    for i in range(0, len(tasks), size):
        waves.append(Wave(index=len(waves), tasks=tasks[i:i + size]))
    return waves


def plan_build(
    feature: str,
    repo_root: str,
    project: str | None = None,
    *,
    persist: bool = True,
    runs_dir: str | Path | None = None,
    update_architecture: bool = True,
) -> BuildSession:
    """Plan a multi-wave build for ``feature``.

    Decompose the feature, route each subtask to its owning agent, derive that
    agent's category preset (lane/tier), assign a frontier or local builder off
    the lane, and group the subtasks into bounded waves. Deterministic apart
    from :func:`decompose`'s optional local-model call (which has a deterministic
    fallback); no provider write happens here.
    """
    # Reuse Ikarus purely for its wave sizing + active_agents resolution: with
    # a project it loads the team's max_workers/active_agents; without one it
    # keeps the safe defaults. No spawning happens.
    foreman = Ikarus(project=project)
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
    )
    if persist:
        session.save(runs_dir, update_architecture=update_architecture)
    return session
