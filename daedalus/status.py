from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from .file_bridge import INBOX, OUTBOX
from .memory import TODO_PATH, load_events
from .projects import resolve_repo_root


ROOT = Path(__file__).resolve().parents[1]


def _git(repo_root: str, args: list[str]) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        return completed.stderr.strip()
    return completed.stdout.strip()


def _count_open_todos(events: list[dict[str, Any]]) -> int:
    open_keys: set[str] = set()
    done_keys: set[str] = set()
    for event in events:
        status = event.get("status")
        for todo in event.get("todos", []):
            key = todo.strip().lower()
            if not key:
                continue
            if status == "done":
                done_keys.add(key)
            else:
                open_keys.add(key)
    return len(open_keys - done_keys)


def collect_status(repo_root: str) -> dict[str, Any]:
    events = load_events()
    return {
        "repo_root": repo_root,
        "git_branch": _git(repo_root, ["branch", "--show-current"]),
        "git_status": _git(repo_root, ["status", "--short"]),
        "outbox_count": len(list(OUTBOX.glob("*.json"))) if OUTBOX.exists() else 0,
        "inbox_count": len(list(INBOX.glob("*.report.json"))) if INBOX.exists() else 0,
        "memory_events": len(events),
        "open_todos": _count_open_todos(events),
        "todo_snapshot": str(TODO_PATH),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Show local agent bridge status.")
    parser.add_argument("--repo-root")
    parser.add_argument("--project")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    repo_root = resolve_repo_root(args.repo_root, args.project)
    status = collect_status(repo_root)
    if args.json:
        print(json.dumps(status, indent=2))
        return
    print(f"Repo: {status['repo_root']}")
    print(f"Branch: {status['git_branch']}")
    print(f"Outbox: {status['outbox_count']} pending")
    print(f"Inbox: {status['inbox_count']} reports")
    print(f"Memory: {status['memory_events']} events, {status['open_todos']} open TODOs")
    print(f"TODO snapshot: {status['todo_snapshot']}")
    if status["git_status"]:
        print("\nGit status:")
        print(status["git_status"])


if __name__ == "__main__":
    main()
