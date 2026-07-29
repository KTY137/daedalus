"""Kairos -- bounded scheduler for the contractor bench.

Adam owns trust, safety, and the senior Claude crew. He hands Ikarus only the
work he has already cleared as low-risk and offloadable. Ikarus then:

  * dynamically spawns local workers from a bounded pool (the Mexican/Italian
    Ollama bench; the Chinese DeepSeek bench stays dormant without a key),
  * briefs each with a scoped task + the owning specialist's domain,
  * enforces their *reduced rights* (the Ollama write-guard already refuses
    device/vendor/secret/high-risk paths),
  * returns a consolidated report for Adam / the owning specialist to review.

Kairos never talks to the user, never decides trust, and bounces anything that
belongs to the senior crew back to the trusted orchestration layer.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from itertools import cycle
from typing import Any

from ..provider_router import route_and_select
from ..providers import get_provider
from ..providers.personas import roster
from ..sensitivity import Policy

# Lanes Ikarus may dispatch (everything that is not the senior Claude lane).
# "Free" means free of CLAUDE tokens: ollama is truly free/local; deepseek and
# codex_cli are external and spend their own (cheap/subscription) budget.
FREE_LANES = ("ollama", "deepseek", "codex_cli")

# Default posture: local bench on, external benches dormant (no DeepSeek key,
# Codex only when the CLI is detected by doctor at dispatch time).
DEFAULT_AVAILABILITY = {"claude_cli": True, "ollama": True, "deepseek": False,
                        "codex_cli": False}


def _paths_overlap(assignments: list) -> bool:
    """Diagnostic overlap among declared write hints.

    This is not a proof of write isolation: an agent may touch an undeclared
    path.  Production write concurrency therefore remains disabled until each
    task owns a separate Forge workcell/worktree.
    """
    seen: set[str] = set()
    for a in assignments:
        if getattr(a, "mode", "") != "write":
            continue
        for p in (a.paths or []):
            key = str(p).replace("\\", "/")
            if key in seen:
                return True
            seen.add(key)
    return False


@dataclass
class Assignment:
    objective: str
    paths: list[str]
    owner: str            # senior specialist who owns/reviews the domain
    lane: str             # ollama | deepseek | codex_cli | claude_cli (if bounced)
    worker: str           # bench persona doing the work ("-" if bounced)
    mode: str             # write | advisory
    accepted: bool
    reason: str


@dataclass
class KairosScheduler:
    max_workers: int = 3                       # bounded concurrency on the local box
    availability: dict | None = None
    policy: Policy | None = None
    project: str | None = None                 # loads the safety policy for live writes
    active_agents: list[str] | None = None
    # Concurrency cap SPECIFICALLY for gate_concurrent_writes (see that
    # method and daedalus/kairos/gated_writes.py), independent of
    # max_workers. Deliberately conservative and separately configurable:
    # every concurrent write-mode offload() triggers a FULL structcore
    # re-index (offload.py's post-write blast-radius fence, cached_index(...,
    # refresh=True)), and that cache's single-flight lock is keyed by
    # RESOLVED ROOT (structcore/index.py::cached_index) -- so N worktrees, N
    # distinct roots, N UNSHARED full re-index builds competing for CPU/RAM
    # at once. NOT MEASURED on this box for N>1 -- the default stays low
    # until someone measures the real cost and raises it deliberately.
    max_parallel_writes: int = 2
    _bench: cycle = field(default=None, repr=False)

    def __post_init__(self) -> None:
        # Extra pool workers Ikarus can spin up for fan-out beyond the role shadows.
        self._bench = cycle(roster("ollama"))
        if self.policy is None and self.project:
            from ..projects import load_project
            from ..sensitivity import load_policy
            project_data = load_project(self.project)
            self.policy = load_policy(project_data)
            team = project_data.get("team") or {}
            try:
                configured_workers = int(team.get("max_workers", self.max_workers))
            except (TypeError, ValueError):
                configured_workers = self.max_workers
            self.max_workers = max(1, configured_workers)
            try:
                configured_writes = int(team.get("max_parallel_writes", self.max_parallel_writes))
            except (TypeError, ValueError):
                configured_writes = self.max_parallel_writes
            self.max_parallel_writes = max(1, configured_writes)
            active = team.get("active_agents")
            if isinstance(active, list):
                self.active_agents = [str(a) for a in active if str(a).strip()]

    def accept(self, tasks: list[dict], repo_root: str | None = None) -> list[Assignment]:
        """Clear each task. Only low-risk work that Adam would offload is taken;
        anything that routes back to Claude is bounced to Adam.

        ``repo_root`` makes the target repo's own ``.agentenv/agents/`` roster
        visible to routing (without it only global agents route)."""
        avail = self.availability or DEFAULT_AVAILABILITY
        out: list[Assignment] = []
        for t in tasks:
            objective = t["objective"]
            paths = t.get("paths", [])
            agent, decision = route_and_select(
                objective, paths, avail, self.policy, self.active_agents,
                repo_root=repo_root,
            )
            if decision.provider not in FREE_LANES:
                out.append(Assignment(objective, paths, agent["name"], decision.provider,
                                      "-", decision.mode, False,
                                      "belongs to the senior crew -> return to Adam"))
                continue
            out.append(Assignment(objective, paths, agent["name"], decision.provider,
                                  decision.persona, decision.mode, True, decision.reason))
        return out

    def plan(self, tasks: list[dict], repo_root: str | None = None) -> dict:
        """Dry run: who gets spawned, in how many bounded waves."""
        acc = self.accept(tasks, repo_root=repo_root)
        taken = [a for a in acc if a.accepted]
        waves = (len(taken) + self.max_workers - 1) // self.max_workers if taken else 0
        return {
            "assignments": acc,
            "spawned": len(taken),
            "bounced_to_adam": len(acc) - len(taken),
            "waves": waves,
        }

    def dispatch(self, repo_root: str, tasks: list[dict], dry_run: bool = True,
                 parallel: bool = False) -> list[dict]:
        """Run the accepted work. dry_run stops at the spawn plan; live actually
        invokes each bench worker through the provider seam.

        Sequential by default (``parallel=False``): each live write is verified
        by diffing a WHOLE-repo content-hash snapshot around that one run
        (offload._repo_snapshot), which catches even writes outside --paths --
        but two such runs on one repo concurrently would cross-attribute
        disk_changed. So real concurrency requires per-task isolation.

        ``parallel=True`` currently overlaps advisory-only work.  Declared path
        disjointness is not a security boundary: a writable agent can touch an
        undeclared repository path, while ``isolate_paths=True`` would observe
        only its hints and misattribute the result.  Writable concurrency stays
        sequential with whole-repository snapshots until Forge gives every
        attempt its own workcell/worktree."""
        avail = self.availability or DEFAULT_AVAILABILITY
        accepted = self.accept(tasks, repo_root=repo_root)
        results: list[dict] = []

        def _bounced_or_planned(a: "Assignment") -> dict | None:
            if not a.accepted:
                return {"worker": a.worker, "lane": a.lane, "mode": a.mode,
                        "owner": a.owner, "objective": a.objective,
                        "paths": a.paths, "status": "bounced", "reason": a.reason}
            if dry_run:
                return {"worker": a.worker, "lane": a.lane, "mode": a.mode,
                        "owner": a.owner, "objective": a.objective,
                        "paths": a.paths, "status": "planned"}
            return None

        def _run_one(a: "Assignment", isolate: bool) -> dict:
            from ..offload import offload
            res = offload(a.objective, repo_root, a.paths, live=True,
                          availability=avail, project=self.project,
                          isolate_paths=isolate)
            return {"worker": a.worker, "lane": a.lane, "mode": a.mode,
                    "owner": a.owner, "objective": a.objective, "paths": a.paths,
                    "status": res.get("action"),
                    # ground truth: files REALLY changed on disk ([] for advisory
                    # drafts) -- render write claims from this, never from action.
                    "wrote": res.get("wrote", []), "result": res}

        live_tasks = [a for a in accepted if a.accepted and not dry_run]
        # Only read-only/advisory attempts may share a checkout concurrently.
        # Pairwise-disjoint declared strings are not evidence that agentic
        # writers stay within those strings.
        has_writes = any(a.mode == "write" for a in live_tasks)
        # Writes may go parallel ONLY when each one gets its own worktree. The
        # hazard this closes is not misattribution -- it is destruction: every
        # offload() gets a fresh provider whose rollback snapshot is per-call
        # while the FILES are shared, so if task A's verify fails after task B
        # landed a verified write to the same file, A's rollback writes its own
        # stale pre-run bytes over B's finished work, with no error raised.
        # Separate checkouts remove that by construction rather than by
        # convention: `isolate_paths` and disjoint declared paths never could,
        # because an agentic writer is not bound by the strings it was handed.
        #
        # STILL sequential here, but the reason changed: the isolation now
        # EXISTS -- see gate_concurrent_writes() below, which runs each write
        # through daedalus.spine.attempt.TaskAttempt (its own worktree, its
        # own hardened patch capture) fanned out concurrently, and
        # daedalus.kairos.gated_writes.promote_candidates(), which lands
        # gated candidates one at a time behind a cross-process lock with
        # cumulative re-gating. What THAT path returns is not what this one
        # returns, though: a gated PatchArtifact the primary checkout never
        # saw, not a live write already sitting in repo_root's working tree.
        # dispatch() keeps its existing auto-land contract for a single write
        # (offload() has always auto-landed a sequential one), and does not
        # silently switch write-mode dispatch to the gated-candidate shape --
        # that is a product decision (does concurrent dispatch keep
        # auto-landing, or become review-then-promote like the rest of the
        # spine?) for whoever owns that contract to make, not something to
        # decide by which code path happened to run. Call
        # gate_concurrent_writes()/promote_candidates() explicitly when that
        # decision says to.
        can_parallel = parallel and not has_writes

        if parallel and not can_parallel and live_tasks:
            results.append({"status": "note", "objective": "parallel disabled",
                            "reason": (
                                "writable attempts ran sequentially with whole-repo "
                                "change attribution; see gate_concurrent_writes() for "
                                "isolated, concurrent write gating (returns gated "
                                "candidates, not live writes -- promotion is a "
                                "separate, explicit step)"
                            )})

        if can_parallel and len(live_tasks) > 1:
            from concurrent.futures import ThreadPoolExecutor
            done: dict[int, dict] = {}
            pending = [a for a in accepted if (_bounced_or_planned(a) is None)]
            with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
                futs = {pool.submit(_run_one, a, True): i for i, a in enumerate(pending)}
                for f in futs:
                    done[futs[f]] = f.result()
            # preserve input order in the output
            live_iter = iter(done[i] for i in range(len(pending)))
            for a in accepted:
                bp = _bounced_or_planned(a)
                results.append(bp if bp is not None else next(live_iter))
            return results

        # sequential (default, or forced by a path conflict)
        for a in accepted:
            bp = _bounced_or_planned(a)
            results.append(bp if bp is not None else _run_one(a, isolate=False))
        return results

    def gate_concurrent_writes(self, repo_root: str, tasks: list[dict],
                               ledger_path=None, cancel: Any = None) -> list:
        """Safe concurrent WRITE dispatch: PHASE 1 only (gating, not landing).

        Every write task in ``tasks`` runs CONCURRENTLY, each through
        :class:`daedalus.spine.attempt.TaskAttempt` in its own worktree
        (``offload()`` as the runner -- its verify+rollback cascade stays the
        authority for per-task correctness; see
        ``daedalus.kairos.gated_writes._relay_gate``). Returns one
        :class:`daedalus.kairos.gated_writes.GatedCandidate` per accepted
        write task: a gate verdict plus a ``PatchArtifact`` when clean. The
        primary checkout at ``repo_root`` is NEVER touched by this call --
        that is ``TaskAttempt``'s own structural guarantee (see
        ``tests/test_spine_attempt.py::test_happy_path_artifact_and_primary_untouched``).

        Advisory-only tasks are bounced (this method only accepts write-mode
        work; use :meth:`plan`/:meth:`accept` for the routing verdict on the
        rest of a mixed task list, or :meth:`dispatch` to actually run them).

        ``cancel``, when given, is forwarded unchanged to
        :func:`daedalus.kairos.gated_writes.gate_candidates` -- added here so
        this wrapper does not silently strip a capability that module already
        supports; see that function's own docstring for exactly what it
        covers (every ``TaskAttempt`` in this batch) and does not (the
        cumulative re-gate inside ``promote_candidates``, a separate, filed
        follow-up, not this method's concern since it never promotes).

        Landing a candidate this returns into ``repo_root`` is a SEPARATE,
        explicit act -- see :func:`daedalus.kairos.gated_writes.promote_candidates`
        and the comment on ``can_parallel`` in :meth:`dispatch` for why this
        method does not do that itself.
        """
        from .gated_writes import gate_candidates
        avail = self.availability or DEFAULT_AVAILABILITY
        accepted = self.accept(tasks, repo_root=repo_root)
        writes = [a for a in accepted if a.accepted and a.mode == "write"]
        if not writes:
            return []
        return gate_candidates(
            repo_root, writes, project=self.project, availability=avail,
            max_workers=min(self.max_parallel_writes, self.max_workers),
            ledger_path=ledger_path, cancel=cancel)

    def spawn(self, objective: str, repo_root: str, dry_run: bool = True) -> dict:
        """One-shot entry: decompose a single objective into subtasks, then plan
        (dry_run) or dispatch (live) them across the bounded local bench.

        This is the dynamic counterpart to the hardcoded ``_demo_tasks`` flow --
        the subtasks come from :func:`daedalus.kairos.decompose.decompose` (local model
        with a deterministic per-path fallback), not a fixed list."""
        from .decompose import decompose
        subtasks = decompose(objective, repo_root)
        if dry_run:
            return self.plan(subtasks, repo_root=repo_root)
        return self.dispatch(repo_root, subtasks, dry_run=False)


    def configure(self, spec: dict, repo_root: str | None = None, *, overwrite: bool = False) -> dict:
        """Dynamic agent configurator: mint or reshape an agent-role definition
        at runtime. Ikarus owns the crew roster, so creating/editing roles is
        his job -- routing (``router.load_agents``) picks up the change with no
        restart. Returns a summary; raises ValueError on an invalid spec."""
        from .. import agents_registry as reg
        name = spec.get("name")
        if name and reg.get_role(name, repo_root) is not None:
            patch = {k: v for k, v in spec.items() if k != "name"}
            path = reg.update_role(name, patch, repo_root)
            action = "updated"
        else:
            path = reg.create_role(spec, repo_root, overwrite=overwrite)
            action = "created"
        return {"orchestrator": "ikarus", "action": action, "role": name,
                "path": str(path), "config": reg.get_role(name, repo_root)}


def _demo_tasks() -> list[dict]:
    from ..benchmark import TASKS
    return [{"objective": t.objective, "paths": t.paths} for t in TASKS]


def main() -> None:
    parser = argparse.ArgumentParser(description="Kairos -- bounded contractor-bench scheduler.")
    parser.add_argument("--max-workers", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    ikarus = KairosScheduler(max_workers=args.max_workers)
    plan = ikarus.plan(_demo_tasks())

    if args.json:
        print(json.dumps({
            "spawned": plan["spawned"], "bounced_to_adam": plan["bounced_to_adam"],
            "waves": plan["waves"],
            "assignments": [vars(a) for a in plan["assignments"]],
        }, indent=2))
        return

    print("KAIROS spawn plan  (local bench on, DeepSeek dormant)\n")
    print(f"{'objective':<34}{'owner':<18}{'lane/worker':<22}{'mode':<9}{'status'}")
    print("-" * 96)
    for a in plan["assignments"]:
        lane_worker = f"{a.lane}/{a.worker}" if a.accepted else "-> Adam"
        status = "spawn" if a.accepted else "bounce"
        print(f"{a.objective[:33]:<34}{a.owner:<18}{lane_worker:<22}{a.mode:<9}{status}")
    print("-" * 96)
    print(f"spawned {plan['spawned']} local worker(s) across {plan['waves']} wave(s) "
          f"(<= {args.max_workers}/wave); bounced {plan['bounced_to_adam']} back to Adam.")


if __name__ == "__main__":
    main()
