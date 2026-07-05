from __future__ import annotations

import argparse
import json
from pathlib import Path

from .file_bridge import enqueue
from .fallback import DEFAULT_POLICY
from .memory import MemoryEvent, append_event
from .projects import load_project, resolve_repo_root
from .router import route_task
from .status import collect_status
from .token_policy import MAX_TODO_CHARS, trim_paths, trim_text


def _infer_paths(text: str, repo_root: str) -> list[str]:
    root = Path(repo_root)
    paths: list[str] = []
    for token in text.replace("`", " ").replace(",", " ").split():
        token = token.strip("\"'()[]")
        looks_like_path = "/" in token or "\\" in token or "." in Path(token).name
        if not looks_like_path:
            continue
        candidate = Path(token)
        if not candidate.is_absolute():
            candidate = root / candidate
        try:
            if candidate.exists():
                paths.append(str(candidate))
        except OSError:
            continue
    return list(dict.fromkeys(paths))


def prepare_task(
    message: str,
    repo_root: str | None = None,
    project: str | None = None,
    paths: list[str] | None = None,
    ask_claude: bool = True,
    lane: str = "auto",
) -> dict:
    root = resolve_repo_root(repo_root, project)
    project_data = load_project(project) if project else {}
    paths = trim_paths(paths or _infer_paths(message, root))
    agent = route_task(message, paths)
    status = collect_status(root)

    memory_record = append_event(
        MemoryEvent(
            kind="user_task",
            source="codex",
            repo_root=root,
            status="open",
            summary=trim_text(message, 600),
            todos=[f"Handle user task: {trim_text(message, MAX_TODO_CHARS)}"],
            paths=paths,
            payload={
                "agent": agent["name"],
                "git_status": status["git_status"],
                "fallback_policy": DEFAULT_POLICY,
            },
        )
    )

    queued_path = None
    if ask_claude:
        queued_path = str(
            enqueue(
                objective=f"Second opinion for task: {message}",
                repo_root=root,
                paths=paths,
                model=project_data.get("claude_model", "sonnet"),
                lane=lane,
            )
        )

    return {
        "repo_root": root,
        "agent": agent["name"],
        "paths": paths,
        "queued_claude_request": queued_path,
        "memory_event": memory_record,
        "status": status,
        "fallback_policy": DEFAULT_POLICY,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a user task for Codex/Claude collaboration.")
    parser.add_argument("message")
    parser.add_argument("--repo-root")
    parser.add_argument("--project")
    parser.add_argument("--paths", nargs="*", default=[])
    parser.add_argument("--no-claude", action="store_true")
    parser.add_argument("--lane", default="auto", choices=["auto", "claude", "local"],
                        help="how the watcher may execute the queued task")
    args = parser.parse_args()
    result = prepare_task(
        message=args.message,
        repo_root=args.repo_root,
        project=args.project,
        paths=args.paths,
        ask_claude=not args.no_claude,
        lane=args.lane,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
