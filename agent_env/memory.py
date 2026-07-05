from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MEMORY_DIR = ROOT / "memory"
EVENTS_PATH = MEMORY_DIR / "events.local.jsonl"
TODO_PATH = MEMORY_DIR / "todos.local.md"


@dataclass
class MemoryEvent:
    kind: str
    summary: str
    source: str = "manual"
    repo_root: str | None = None
    task_id: str | None = None
    status: str | None = None
    todos: list[str] | None = None
    paths: list[str] | None = None
    payload: dict[str, Any] | None = None

    def to_record(self) -> dict[str, Any]:
        return {
            "time": datetime.now(timezone.utc).isoformat(),
            "kind": self.kind,
            "source": self.source,
            "repo_root": self.repo_root,
            "task_id": self.task_id,
            "status": self.status,
            "summary": self.summary,
            "todos": self.todos or [],
            "paths": self.paths or [],
            "payload": self.payload or {},
        }


def append_event(event: MemoryEvent) -> dict[str, Any]:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    record = event.to_record()
    with EVENTS_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    refresh_todo_snapshot()
    return record


def load_events() -> list[dict[str, Any]]:
    if not EVENTS_PATH.exists():
        return []
    events = []
    for line in EVENTS_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def refresh_todo_snapshot() -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    events = load_events()
    open_items: dict[str, dict[str, Any]] = {}
    completed: list[dict[str, Any]] = []

    for event in events:
        status = event.get("status")
        for todo in event.get("todos", []):
            key = todo.strip().lower()
            if not key:
                continue
            item = {
                "time": event.get("time", ""),
                "source": event.get("source", ""),
                "summary": event.get("summary", ""),
                "todo": todo,
                "paths": event.get("paths", []),
            }
            if status == "done":
                completed.append(item)
                open_items.pop(key, None)
            else:
                open_items[key] = item

    lines = [
        "# Local Agent Memory",
        "",
        "This file is generated from `memory/events.local.jsonl` and is ignored by Git.",
        "Use it to recover TODOs after token limits, crashes, or interrupted agent runs.",
        "",
        "## Open TODOs",
        "",
    ]
    current_open = list(open_items.values())
    if not current_open:
        lines.append("- None")
    else:
        for item in current_open[-100:]:
            path_text = ", ".join(item["paths"]) if item["paths"] else "no paths"
            lines.append(f"- [{item['source']}] {item['todo']} ({path_text})")
            lines.append(f"  - Context: {item['summary']}")

    lines.extend(["", "## Recent Done Items", ""])
    if not completed:
        lines.append("- None")
    else:
        for item in completed[-30:]:
            lines.append(f"- [{item['source']}] {item['todo']}")

    TODO_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def record_from_bridge_report(report: dict[str, Any]) -> dict[str, Any]:
    request = report.get("request", {})
    inner = report.get("report", {})
    status = inner.get("status") or report.get("bridge_status")
    summary = inner.get("summary") or report.get("error") or "Bridge report"
    todos = inner.get("todos") or []
    if report.get("bridge_status") == "failed" and not todos:
        todos = ["Inspect failed bridge report and retry if needed."]
    return append_event(
        MemoryEvent(
            kind="bridge_report",
            source=f"claude:{report.get('agent', 'unknown')}",
            repo_root=request.get("repo_root"),
            status=status,
            summary=summary,
            todos=todos,
            paths=request.get("paths", []),
            payload=report,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Local append-only memory for agent handoffs.")
    sub = parser.add_subparsers(dest="command")

    add_p = sub.add_parser("add", help="Append a manual memory event.")
    add_p.add_argument("summary")
    add_p.add_argument("--todo", action="append", default=[])
    add_p.add_argument("--repo-root")
    add_p.add_argument("--path", action="append", default=[])
    add_p.add_argument("--status", default="open")
    add_p.add_argument("--source", default="manual")

    sub.add_parser("snapshot", help="Regenerate the Markdown TODO snapshot.")

    done_p = sub.add_parser("done", help="Mark a TODO string as done.")
    done_p.add_argument("todo")
    done_p.add_argument("--summary", default="Marked TODO done")
    done_p.add_argument("--repo-root")
    done_p.add_argument("--source", default="manual")

    args = parser.parse_args()
    if args.command == "add":
        record = append_event(
            MemoryEvent(
                kind="manual",
                source=args.source,
                repo_root=args.repo_root,
                status=args.status,
                summary=args.summary,
                todos=args.todo,
                paths=args.path,
            )
        )
        print(json.dumps(record, indent=2))
    elif args.command == "snapshot":
        refresh_todo_snapshot()
        print(TODO_PATH)
    elif args.command == "done":
        record = append_event(
            MemoryEvent(
                kind="manual",
                source=args.source,
                repo_root=args.repo_root,
                status="done",
                summary=args.summary,
                todos=[args.todo],
            )
        )
        print(json.dumps(record, indent=2))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
