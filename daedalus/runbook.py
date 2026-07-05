from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from .router import ROOT, route_task
from .schemas import AgentTask, RunState


RUN_DIR = ROOT / "runs"


def create_run(objective: str, paths: list[str], repo_root: str) -> dict:
    agent = route_task(objective, paths)
    run_id = uuid4().hex[:12]
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

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    path = RUN_DIR / f"{run_id}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"path": str(path), "payload": payload}


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a pruned agent run brief.")
    parser.add_argument("objective")
    parser.add_argument("--paths", nargs="*", default=[])
    parser.add_argument("--repo-root", default=str(Path.cwd()))
    args = parser.parse_args()
    result = create_run(args.objective, args.paths, args.repo_root)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
