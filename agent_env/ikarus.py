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

FREE_LANES = ("ollama", "deepseek")

# Default posture: local bench on, external bench dormant (no DeepSeek key).
DEFAULT_AVAILABILITY = {"claude_cli": True, "ollama": True, "deepseek": False}


@dataclass
class Assignment:
    objective: str
    paths: list[str]
    owner: str            # senior specialist who owns/reviews the domain
    lane: str             # ollama | deepseek | claude_cli (if bounced)
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
    _bench: cycle = field(default=None, repr=False)

    def __post_init__(self) -> None:
        # Extra pool workers Ikarus can spin up for fan-out beyond the role shadows.
        self._bench = cycle(roster("ollama"))
        if self.policy is None and self.project:
            from .projects import load_project
            from .sensitivity import load_policy
            self.policy = load_policy(load_project(self.project))

    def accept(self, tasks: list[dict]) -> list[Assignment]:
        """Clear each task. Only low-risk work that Adam would offload is taken;
        anything that routes back to Claude is bounced to Adam."""
        avail = self.availability or DEFAULT_AVAILABILITY
        out: list[Assignment] = []
        for t in tasks:
            objective = t["objective"]
            paths = t.get("paths", [])
            agent, decision = route_and_select(objective, paths, avail, self.policy)
            if decision.provider not in FREE_LANES:
                out.append(Assignment(objective, paths, agent["name"], decision.provider,
                                      "-", decision.mode, False,
                                      "belongs to the senior crew -> return to Adam"))
                continue
            out.append(Assignment(objective, paths, agent["name"], decision.provider,
                                  decision.persona, decision.mode, True, decision.reason))
        return out

    def plan(self, tasks: list[dict]) -> dict:
        """Dry run: who gets spawned, in how many bounded waves."""
        acc = self.accept(tasks)
        taken = [a for a in acc if a.accepted]
        waves = (len(taken) + self.max_workers - 1) // self.max_workers if taken else 0
        return {
            "assignments": acc,
            "spawned": len(taken),
            "bounced_to_adam": len(acc) - len(taken),
            "waves": waves,
        }

    def dispatch(self, repo_root: str, tasks: list[dict], dry_run: bool = True) -> list[dict]:
        """Run the accepted work. dry_run stops at the spawn plan; live actually
        invokes each bench worker through the provider seam."""
        avail = self.availability or DEFAULT_AVAILABILITY
        results: list[dict] = []
        for a in self.accept(tasks):
            if not a.accepted:
                results.append({"worker": a.worker, "status": "bounced", "reason": a.reason})
                continue
            if dry_run:
                results.append({"worker": a.worker, "lane": a.lane, "mode": a.mode,
                                "owner": a.owner, "objective": a.objective, "status": "planned"})
                continue
            # Live writes MUST go through the verify+rollback+fail-closed cascade
            # (Mary #2) -- never call the provider directly here.
            from .offload import offload
            res = offload(a.objective, repo_root, a.paths, live=True,
                          availability=avail, project=self.project)
            results.append({"worker": a.worker, "lane": a.lane,
                            "status": res.get("action"), "result": res})
        return results

    def spawn(self, objective: str, repo_root: str, dry_run: bool = True) -> dict:
        """One-shot entry: decompose a single objective into subtasks, then plan
        (dry_run) or dispatch (live) them across the bounded local bench.

        This is the dynamic counterpart to the hardcoded ``_demo_tasks`` flow --
        the subtasks come from :func:`agent_env.decompose.decompose` (local model
        with a deterministic per-path fallback), not a fixed list."""
        from .decompose import decompose
        subtasks = decompose(objective, repo_root)
        if dry_run:
            return self.plan(subtasks)
        return self.dispatch(repo_root, subtasks, dry_run=False)


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
