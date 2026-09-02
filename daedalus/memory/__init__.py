from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:  # pragma: no cover - import cost stays off the append path
    from .embeddings import AgentEvent


# ``memory.py`` became a package so vector-index helpers can live beside it.
# Operational state must remain in the repository-level ``memory/`` directory;
# using parents[1] here silently redirected state into ``daedalus/memory/``.
ROOT = Path(__file__).resolve().parents[2]
MEMORY_DIR = ROOT / "memory"
EVENTS_PATH = MEMORY_DIR / "events.local.jsonl"
TODO_PATH = MEMORY_DIR / "todos.local.md"
VECTOR_DB_PATH = MEMORY_DIR / "vectors.db"

logger = logging.getLogger(__name__)


@dataclass
class MemoryEvent:
    kind: str
    summary: str
    source: str = "manual"
    repo_root: str | None = None
    project: str | None = None
    trust: str | None = None
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
            "project": self.project,
            "trust": self.trust,
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
    # MEASURED 2026-09-02: the previous buffered ``open("a")`` write lost 4 of
    # 120 records under six concurrent appenders -- silently, because
    # overwritten bytes leave no malformed line for any reader to count. This
    # is the AUTHORITATIVE journal every projection derives from, so it appends
    # through the locked single-write path in ``journal_io``.
    #
    # A lock timeout RAISES rather than degrading to the old write: OSError was
    # always possible here (full disk, permissions), so raising is inside this
    # function's existing contract, and losing an authoritative event without
    # saying so is the worse outcome by a wide margin.
    from ..journal_io import append_lines

    append_lines(EVENTS_PATH, [json.dumps(record, ensure_ascii=False)])
    refresh_todo_snapshot()

    # Opt-in: forward to the vector store for embedding-based search.
    # Set DAEDALUS_VECTOR_INDEX=1 to enable. Requires Ollama running locally.
    if os.environ.get("DAEDALUS_VECTOR_INDEX", "").strip() in ("1", "true", "yes"):
        _try_vector_index(record)

    return record


def projection_event_from_record(record: Mapping[str, Any]) -> "AgentEvent":
    """Derive the projection input for one journal record.

    This is the single definition of "what a memory event embeds as", shared by
    the synchronous bridge below and by
    :mod:`daedalus.memory.projection_worker`.  It has to be shared: the index is
    content-addressed on a hash of exactly these fields, so two writers that
    derive an event differently would write two rows for one journal line
    instead of one, and neither would be able to tell the other's work had
    already been done.
    """

    from .embeddings import AgentEvent

    paths = [str(path) for path in (record.get("paths") or []) if str(path).strip()]
    content = str(record.get("summary", ""))
    if paths:
        # Keep explicit path evidence in both the human-readable projection
        # input and structured metadata.  The context compiler may map a
        # latent memory hit back into the Forest only when such evidence is
        # present; semantic similarity alone must never invent a file.
        content += "\n\nPaths:\n" + "\n".join(paths)
    return AgentEvent(
        event_id=f"{record.get('time', '')}_{record.get('kind', '')}",
        event_type=record.get("kind", "memory"),
        content=content,
        timestamp=record.get("time", ""),
        metadata={
            "source": record.get("source", ""),
            "task_id": record.get("task_id", ""),
            "repo_root": record.get("repo_root"),
            "project": record.get("project"),
            "trust": record.get("trust"),
            "status": record.get("status"),
            "paths": paths,
        },
    )


def _try_vector_index(record: dict[str, Any]) -> None:
    """Best-effort forwarding to EventVectorStore. Never raises.

    This bridge does NOT record a journal watermark -- it sees one record at a
    time and has no idea where that record sits in the journal file.  Indexes it
    builds alone therefore report ``freshness == "unanchored"``.  Run
    ``python -m daedalus.memory.projection_worker`` to anchor them; it costs no
    embedding calls for entries the bridge already projected.
    """
    store = None
    try:
        from .embeddings import EventVectorStore
        store = EventVectorStore(VECTOR_DB_PATH)
        report = store.ingest_events_report(
            [projection_event_from_record(record)],
            model_revision=(
                os.environ.get("OLLAMA_EMBED_MODEL_REVISION", "").strip() or None
            ),
        )
        if not report.status.available:
            logger.warning(
                "Vector indexing skipped (%s): %s",
                report.status.code,
                report.status.message,
            )
    except Exception as exc:
        # Indexing is explicitly secondary to the append-only operational log.
        # Keep the main path alive, but leave evidence for operators debugging
        # an enabled index instead of swallowing every failure invisibly.
        logger.warning("Vector indexing skipped: %s", exc)
    finally:
        if store is not None:
            store.close()


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
    observed = report.get("actual_providers")
    providers = [
        str(provider).strip() for provider in observed
        if str(provider or "").strip()
    ] if isinstance(observed, list) else []
    # The requested lane and historical ``agent`` label are routing metadata,
    # not proof that Claude (or any provider) ran.  Memory provenance must use
    # the same explicit execution evidence as the task/conversation surfaces.
    provider_source = "+".join(dict.fromkeys(providers)) or "none"
    return append_event(
        MemoryEvent(
            kind="bridge_report",
            source=f"file_bridge:{provider_source}",
            repo_root=request.get("repo_root"),
            project=request.get("project"),
            trust=inner.get("trust") or request.get("trust"),
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
    add_p.add_argument("--project")
    add_p.add_argument("--trust")
    add_p.add_argument("--path", action="append", default=[])
    add_p.add_argument("--status", default="open")
    add_p.add_argument("--source", default="manual")

    sub.add_parser("snapshot", help="Regenerate the Markdown TODO snapshot.")

    done_p = sub.add_parser("done", help="Mark a TODO string as done.")
    done_p.add_argument("todo")
    done_p.add_argument("--summary", default="Marked TODO done")
    done_p.add_argument("--repo-root")
    done_p.add_argument("--project")
    done_p.add_argument("--trust")
    done_p.add_argument("--source", default="manual")

    args = parser.parse_args()
    if args.command in ("add", "snapshot", "done"):
        # Help output stays fail-open; every event/snapshot write starts
        # at the central boundary.
        from daedalus.budget import process_guard_boundary_decision
        from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

        begin_effect(
            "cli.memory",
            REGISTRY_BY_ID["cli.memory"].effects,
            (process_guard_boundary_decision(),),
        )
    if args.command == "add":
        record = append_event(
            MemoryEvent(
                kind="manual",
                source=args.source,
                repo_root=args.repo_root,
                project=args.project,
                trust=args.trust,
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
                project=args.project,
                trust=args.trust,
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
