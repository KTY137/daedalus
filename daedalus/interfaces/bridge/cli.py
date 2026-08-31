"""CLI parser, dispatch, and text projection for the File Bridge facade."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BridgeCliPorts:
    """Current facade bindings required by one CLI dispatch."""

    outbox: Path
    resolve_repo_root: Callable[..., str]
    watch: Callable[..., None]
    enqueue: Callable[..., Path]
    process_request: Callable[..., Path]
    handle_poison_request: Callable[[Path, BaseException], Path | None]
    bridge_status: Callable[[str | None], dict[str, Any]]
    print_status: Callable[[dict[str, Any]], None]
    mark_read: Callable[..., list[str]]
    watcher_ownership_busy: type[BaseException]
    watcher_not_running: type[BaseException]
    pending_exceptions: tuple[tuple[type[BaseException], str], ...]

    @property
    def pending_types(self) -> tuple[type[BaseException], ...]:
        return tuple(kind for kind, _label in self.pending_exceptions)

    def pending_label(self, exc: BaseException) -> str:
        return next(
            label
            for kind, label in self.pending_exceptions
            if isinstance(exc, kind)
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="File bridge between Codex and Claude."
    )
    sub = parser.add_subparsers(dest="command")

    watch_parser = sub.add_parser(
        "watch", help="Watch outbox and process Claude requests."
    )
    watch_parser.add_argument("--repo-root")
    watch_parser.add_argument("--project")
    watch_parser.add_argument("--interval-s", type=float, default=2.0)

    enqueue_parser = sub.add_parser(
        "enqueue", help="Create a task request in outbox."
    )
    enqueue_parser.add_argument("objective")
    enqueue_parser.add_argument("--repo-root")
    enqueue_parser.add_argument("--project")
    enqueue_parser.add_argument("--paths", nargs="*", default=[])
    enqueue_parser.add_argument("--model", default="sonnet")
    enqueue_parser.add_argument(
        "--lane",
        default="auto",
        choices=["auto", "claude", "local", "local_only", "codex"],
        help=(
            "auto/local run accepted assignments through the leased executor "
            "with no direct Claude fallback; local_only exposes only trusted "
            "local Ollama; claude/codex are refused until the queue caller "
            "holds broker authority"
        ),
    )
    enqueue_parser.add_argument(
        "--source",
        default="unknown",
        choices=["unknown", "codex", "claude", "user", "ikarus"],
        help="who queued the request",
    )
    enqueue_parser.add_argument(
        "--strategy",
        default="single",
        choices=["single", "spawn"],
        help=(
            "single routes one task; spawn is currently refused until a "
            "leased multi-task adapter exists"
        ),
    )
    enqueue_parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "queue even though no watcher is alive to run it "
            "(default: REFUSE, because such a task just sits)"
        ),
    )

    once_parser = sub.add_parser(
        "once", help="Process current outbox requests once."
    )
    once_parser.add_argument("--repo-root")
    once_parser.add_argument("--project")

    status_parser = sub.add_parser(
        "status",
        help="Queue depth, in-flight task, watcher liveness, UNREAD reports.",
    )
    status_parser.add_argument(
        "--project", help="filter queue/reports to one project"
    )
    status_parser.add_argument("--json", action="store_true")

    mark_parser = sub.add_parser(
        "mark-read",
        help="Acknowledge finished reports (drops markers in inbox/.seen/).",
    )
    mark_parser.add_argument(
        "names",
        nargs="*",
        help="report file names (with or without .report.json)",
    )
    mark_parser.add_argument(
        "--all", action="store_true", help="mark every unread report as read"
    )
    return parser


def print_status(status: dict[str, Any], *, stale_after_s: float) -> None:
    hb = status["watcher"]
    state = hb["state"]
    if state == "alive":
        watcher = f"alive (heartbeat {hb['age_s']}s ago, pid {hb.get('pid')})"
    elif state == "busy":
        current = hb.get("current") or {}
        watcher = (
            f"busy on {current.get('file', '?')} for {hb.get('busy_for_s')}s "
            f"(pid {hb.get('pid')})"
        )
    elif state == "wedged":
        current = hb.get("current") or {}
        watcher = (
            f"POSSIBLY WEDGED on {current.get('file', '?')} for "
            f"{hb.get('busy_for_s')}s -- investigate, then restart: "
            f"{hb['restart']}"
        )
    elif state == "stale":
        watcher = (
            f"STALE (last heartbeat {hb['age_s']}s ago > {stale_after_s:.0f}s) "
            f"-- restart: {hb['restart']}"
        )
    else:
        watcher = f"{hb.get('detail', 'unknown')} -- start: {hb['restart']}"
    print(f"Watcher : {watcher}")
    print(f"Queue   : {status['queue_depth']} queued")
    for item in status["queued"]:
        print(f"  {item['name']}  lane={item['lane']}")
    if status["in_flight"]:
        print(f"In-flight: {status['in_flight'].get('file', '?')}")
    print(
        f"Reports : {status['reports_total']} total, "
        f"{status['unread_count']} UNREAD"
    )
    for item in status["unread"]:
        print(
            f"  UNREAD {item['name']}  status={item['status']} "
            f"lane={item['lane']}"
        )
        if item["summary"]:
            print(f"         {item['summary']}")
    if status["unread_count"]:
        print(
            "Acknowledge: python -m daedalus.file_bridge mark-read --all "
            "(or name specific reports)"
        )
    if status.get("quarantined_count"):
        print(
            f"QUARANTINED: {status['quarantined_count']} request(s) the watcher "
            "could not process -- they are NOT queued and will not run"
        )
        for item in status["quarantined"]:
            print(
                f"  {item['name']}  {item['reason']}: {item['error'][:120]}"
            )
    print(f"Arrival log: {status['latest_log']}")


def dispatch(
    args: argparse.Namespace,
    *,
    parser: argparse.ArgumentParser,
    ports: BridgeCliPorts,
) -> None:
    """Dispatch an already-admitted command through current facade ports."""

    if args.command == "watch":
        try:
            ports.watch(
                ports.resolve_repo_root(args.repo_root, args.project),
                args.interval_s,
                project=args.project,
            )
        except ports.watcher_ownership_busy as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            raise SystemExit(2) from None
    elif args.command == "enqueue":
        try:
            print(
                ports.enqueue(
                    args.objective,
                    ports.resolve_repo_root(args.repo_root, args.project),
                    args.paths,
                    args.model,
                    args.lane,
                    args.project,
                    args.source,
                    args.strategy,
                    require_watcher=not args.force,
                )
            )
        except ports.watcher_not_running as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(2)
    elif args.command == "once":
        ports.outbox.mkdir(parents=True, exist_ok=True)
        repo_root = (
            ports.resolve_repo_root(args.repo_root, args.project)
            if args.repo_root or args.project
            else None
        )
        for path in sorted(ports.outbox.glob("*.json")):
            try:
                print(ports.process_request(path, repo_root))
            except ports.pending_types as exc:
                print(
                    f"{ports.pending_label(exc)} {path.name}: {exc}",
                    file=sys.stderr,
                )
            except Exception as exc:  # noqa: BLE001 - poison is quarantined
                ports.handle_poison_request(path, exc)
    elif args.command == "status":
        status = ports.bridge_status(args.project)
        if args.json:
            print(json.dumps(status, indent=2))
        else:
            ports.print_status(status)
    elif args.command == "mark-read":
        if not args.names and not args.all:
            print("nothing to do: pass report names or --all")
        else:
            marked = ports.mark_read(args.names, all_reports=args.all)
            print(f"marked {len(marked)} report(s) read")
            for name in marked:
                print(f"  {name}")
    else:
        parser.print_help()


__all__ = ["BridgeCliPorts", "build_parser", "dispatch", "print_status"]
