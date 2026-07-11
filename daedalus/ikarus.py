"""Ikarus -- foreman of the contractor bench.

Adam owns trust, safety, and the senior Claude crew. He hands Ikarus only the
work he has already cleared as low-risk and offloadable. Ikarus then:

  * dynamically spawns local workers from a bounded pool (the Mexican/Italian
    Ollama bench; the Chinese DeepSeek bench stays dormant without a key),
  * briefs each with a scoped task + the owning specialist's domain,
  * enforces their *reduced rights* (the Ollama write-guard already refuses
    device/vendor/secret/high-risk paths),
  * returns a consolidated report for Adam / the owning specialist to review.

The myth is the mandate: Ikarus must not fly too high. He never talks to the
user, never decides trust, and bounces anything that belongs to the senior crew
back to Adam (defense in depth -- he re-checks the routing himself).
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from itertools import cycle

from .provider_router import route_and_select
from .providers import get_provider
from .providers.personas import roster
from .sensitivity import Policy

# Lanes Ikarus may dispatch (everything that is not the senior Claude lane).
# "Free" means free of CLAUDE tokens: ollama is truly free/local; deepseek and
# codex_cli are external and spend their own (cheap/subscription) budget.
FREE_LANES = ("ollama", "deepseek", "codex_cli")

# Default posture: local bench on, external benches dormant (no DeepSeek key,
# Codex only when the CLI is detected by doctor at dispatch time).
DEFAULT_AVAILABILITY = {"claude_cli": True, "ollama": True, "deepseek": False,
                        "codex_cli": False}


def _paths_overlap(assignments: list) -> bool:
    """True if any two write-mode assignments declare a shared path -- then they
    cannot run concurrently (real edit conflict). Advisory tasks write nothing,
    so they never conflict."""
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
class Ikarus:
    max_workers: int = 3                       # bounded concurrency on the local box
    availability: dict | None = None
    policy: Policy | None = None
    project: str | None = None                 # loads the safety policy for live writes
    active_agents: list[str] | None = None
    _bench: cycle = field(default=None, repr=False)

    def __post_init__(self) -> None:
        # Extra pool workers Ikarus can spin up for fan-out beyond the role shadows.
        self._bench = cycle(roster("ollama"))
        if self.policy is None and self.project:
            from .projects import load_project
            from .sensitivity import load_policy
            project_data = load_project(self.project)
            self.policy = load_policy(project_data)
            team = project_data.get("team") or {}
            try:
                configured_workers = int(team.get("max_workers", self.max_workers))
            except (TypeError, ValueError):
                configured_workers = self.max_workers
            self.max_workers = max(1, configured_workers)
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

        ``parallel=True`` enables it SAFELY: it runs accepted tasks in a bounded
        thread pool (``max_workers``) with ``isolate_paths=True`` so each task
        attributes only its OWN declared paths -- and it first REFUSES to
        parallelize any batch whose write-tasks share a path (a real conflict:
        two agents editing one file). Overlapping batches fall back to
        sequential with a note. Ollama on one GPU serializes generation anyway,
        so the win is overlapped verify/test, not 6x model throughput."""
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
            from .offload import offload
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
        # Parallel only when safe: write-tasks must have pairwise-disjoint paths.
        can_parallel = parallel and not _paths_overlap(live_tasks)

        if parallel and not can_parallel and live_tasks:
            # honest: we were asked for parallel but a path conflict forces order
            results.append({"status": "note", "objective": "parallel disabled",
                            "reason": "accepted write-tasks share a path -> ran sequentially to avoid clobber"})

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
            results.append(bp if bp is not None else _run_one(a, isolate=parallel))
        return results

    def spawn(self, objective: str, repo_root: str, dry_run: bool = True) -> dict:
        """One-shot entry: decompose a single objective into subtasks, then plan
        (dry_run) or dispatch (live) them across the bounded local bench.

        This is the dynamic counterpart to the hardcoded ``_demo_tasks`` flow --
        the subtasks come from :func:`daedalus.decompose.decompose` (local model
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
        from . import agents_registry as reg
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
    from .benchmark import TASKS
    return [{"objective": t.objective, "paths": t.paths} for t in TASKS]


def main() -> None:
    parser = argparse.ArgumentParser(description="Ikarus -- foreman of the contractor bench.")
    parser.add_argument("--max-workers", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    ikarus = Ikarus(max_workers=args.max_workers)
    plan = ikarus.plan(_demo_tasks())

    if args.json:
        print(json.dumps({
            "spawned": plan["spawned"], "bounced_to_adam": plan["bounced_to_adam"],
            "waves": plan["waves"],
            "assignments": [vars(a) for a in plan["assignments"]],
        }, indent=2))
        return

    print("IKARUS spawn plan  (local bench on, DeepSeek dormant)\n")
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
