# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from .router import ROOT, route_task
from .schemas import AgentTask, RunState


RUN_DIR = ROOT / "runs"


def create_run(objective: str, paths: list[str], repo_root: str,
               engine: str = "stdlib") -> dict:
    """Compose one pruned run brief and write it to ``runs/<run_id>.json``.

    ``engine`` selects who COMPOSES the brief, never who writes it. The write
    below is the only effect either engine produces, which is what keeps the
    optional graph an adapter rather than a second control plane
    (plan §13). ``"stdlib"`` is the default and needs no dependency;
    ``"langgraph"`` routes composition through ``daedalus.langgraph_adapter``
    and raises ``LangGraphUnavailable`` if the extra is not installed --
    deliberately, rather than degrading silently to the other engine, so that
    "which engine produced this brief?" always has an answer.
    """
    run_id = uuid4().hex[:12]
    if engine == "langgraph":
        from .langgraph_adapter import run_brief

        payload = run_brief(objective, paths, repo_root, run_id)
        return _write_brief(run_id, payload)
    if engine != "stdlib":
        raise ValueError(f"unknown engine {engine!r}: expected 'stdlib' or 'langgraph'")

    agent = route_task(objective, paths)
    task = AgentTask(
        task_id=run_id,
        agent=agent["name"],
        repo_root=repo_root,
        objective=objective,
        paths=paths,
        context={
            "must_read": agent.get("must_read", []),
            "model_tier": agent.get("model_tier", "sonnet"),
            "call_name": agent.get("call_name", agent["name"]),
        },
        constraints=[
            "Do not read or pass full chat history.",
            "Read only files needed for this task.",
            "Return agent_report_v1 JSON only.",
            "No agent-to-agent chat; report to orchestrator only.",
        ],
    )
    state = RunState(
        run_id=run_id,
        objective=objective,
        repo_root=repo_root,
        active_agent=agent["name"],
        paths=paths,
    )
    state.add_event("task_created", task.brief())
    payload = {"state": state.to_dict(), "task": task.brief()}
    return _write_brief(run_id, payload)


def _write_brief(run_id: str, payload: dict) -> dict:
    """The single writer. Both engines land here and nowhere else."""
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    path = RUN_DIR / f"{run_id}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"path": str(path), "payload": payload}


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a pruned agent run brief.")
    parser.add_argument("objective")
    parser.add_argument("--paths", nargs="*", default=[])
    parser.add_argument("--repo-root", default=str(Path.cwd()))
    parser.add_argument("--engine", default="stdlib", choices=("stdlib", "langgraph"),
                        help="who composes the brief; the writer is the same either way")
    args = parser.parse_args()
    from daedalus.budget import process_guard_boundary_decision
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "cli.runbook",
        REGISTRY_BY_ID["cli.runbook"].effects,
        (process_guard_boundary_decision(),),
    )
    result = create_run(args.objective, args.paths, args.repo_root, engine=args.engine)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
