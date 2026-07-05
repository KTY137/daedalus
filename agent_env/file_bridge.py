from __future__ import annotations

import argparse
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .claude_bridge import ask_claude
from .memory import record_from_bridge_report
from .projects import resolve_repo_root


ROOT = Path(__file__).resolve().parents[1]
OUTBOX = ROOT / "outbox"
INBOX = ROOT / "inbox"
ARCHIVE = ROOT / "runs" / "processed"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def enqueue(objective: str, repo_root: str, paths: list[str], model: str = "sonnet",
            lane: str = "auto") -> Path:
    OUTBOX.mkdir(parents=True, exist_ok=True)
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in objective)[:48].strip("-")
    path = OUTBOX / f"{_stamp()}-{slug or 'task'}.json"
    payload = {
        "objective": objective,
        "repo_root": repo_root,
        "paths": paths,
        "model": model,
        # Which lane the watcher may dispatch to:
        #   auto  -> route; run on the free bench when eligible, else Claude
        #   local -> same as auto (prefer the bench), else fall back to Claude
        #   claude-> always the trusted Claude lane (original behaviour)
        "lane": lane,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _read_request(path: Path, default_repo_root: str | None) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "objective" not in payload:
        raise ValueError("request needs an objective")
    if "repo_root" not in payload:
        if not default_repo_root:
            raise ValueError("request needs repo_root or bridge needs --repo-root")
        payload["repo_root"] = default_repo_root
    payload.setdefault("paths", [])
    payload.setdefault("model", "sonnet")
    payload.setdefault("lane", "auto")
    return payload


def _availability_from_doctor() -> dict[str, bool]:
    """Reachability snapshot in the shape provider_router/offload expect."""
    from .doctor import check
    ready = check()
    return {
        "claude_cli": bool(ready.get("claude_cli")),
        "ollama": bool(ready.get("can_offload_local")),
        "deepseek": bool(ready.get("deepseek_key")),
    }


def _try_offload(payload: dict[str, Any]) -> dict[str, Any] | None:
    """For lane in ('auto','local'): route the task; if it lands on an available
    FREE lane, run it through the verified offload cascade and return a bridge
    report. Return ``None`` to fall through to the Claude lane (not eligible, the
    bench is down, or routing failed) -- Claude stays the backstop."""
    from .ikarus import FREE_LANES
    from .provider_router import route_and_select
    try:
        availability = _availability_from_doctor()
        _, decision = route_and_select(payload["objective"], payload["paths"], availability)
    except Exception:
        return None  # can't route -> let the Claude lane handle it
    if decision.provider not in FREE_LANES or not availability.get(decision.provider, False):
        return None

    from .offload import offload
    try:
        result = offload(
            payload["objective"], payload["repo_root"], payload["paths"],
            live=True, availability=availability, project=payload.get("project"),
        )
    except Exception as exc:
        return {
            "request": payload,
            "bridge_status": "failed",
            "lane": "local",
            "error": str(exc),
        }
    return {
        "request": payload,
        "bridge_status": "done",
        "lane": "local",
        "agent": result.get("owner"),
        "result": result,
    }


def _ask_claude_report(payload: dict[str, Any]) -> dict[str, Any]:
    """The original trusted-lane path: hand the task to Claude and wrap it."""
    try:
        result = ask_claude(
            objective=payload["objective"],
            repo_root=payload["repo_root"],
            paths=payload["paths"],
            model=payload["model"],
            timeout_s=int(payload.get("timeout_s", 300)),
        )
        return {
            "request": payload,
            "bridge_status": "done",
            "lane": "claude",
            "agent": result["agent"],
            "report": result["report"],
        }
    except Exception as exc:
        return {
            "request": payload,
            "bridge_status": "failed",
            "lane": "claude",
            "error": str(exc),
        }


def process_request(path: Path, default_repo_root: str | None = None) -> Path:
    INBOX.mkdir(parents=True, exist_ok=True)
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    payload = _read_request(path, default_repo_root)
    result_path = INBOX / f"{path.stem}.report.json"

    lane = payload.get("lane", "auto")
    report = None
    if lane in ("auto", "local"):
        report = _try_offload(payload)   # None -> not eligible, fall through
    if report is None:
        report = _ask_claude_report(payload)  # lane=="claude" or fell through

    result_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    record_from_bridge_report(report)
    shutil.move(str(path), str(ARCHIVE / path.name))
    return result_path


def watch(default_repo_root: str | None, interval_s: float) -> None:
    OUTBOX.mkdir(parents=True, exist_ok=True)
    INBOX.mkdir(parents=True, exist_ok=True)
    print("AGENT_BRIDGE_START", flush=True)
    print(f"Watching {OUTBOX}", flush=True)
    print("AGENT_BRIDGE_READY", flush=True)

    while True:
        for path in sorted(OUTBOX.glob("*.json")):
            print(f"Processing {path.name}", flush=True)
            result = process_request(path, default_repo_root)
            print(f"Wrote {result}", flush=True)
        time.sleep(interval_s)


def main() -> None:
    parser = argparse.ArgumentParser(description="File bridge between Codex and Claude.")
    sub = parser.add_subparsers(dest="command")

    watch_p = sub.add_parser("watch", help="Watch outbox and process Claude requests.")
    watch_p.add_argument("--repo-root")
    watch_p.add_argument("--project")
    watch_p.add_argument("--interval-s", type=float, default=2.0)

    enqueue_p = sub.add_parser("enqueue", help="Create a Claude request in outbox.")
    enqueue_p.add_argument("objective")
    enqueue_p.add_argument("--repo-root")
    enqueue_p.add_argument("--project")
    enqueue_p.add_argument("--paths", nargs="*", default=[])
    enqueue_p.add_argument("--model", default="sonnet")
    enqueue_p.add_argument("--lane", default="auto", choices=["auto", "claude", "local"],
                           help="auto/local run on the free bench when eligible; claude forces the trusted lane")

    once_p = sub.add_parser("once", help="Process current outbox requests once.")
    once_p.add_argument("--repo-root")
    once_p.add_argument("--project")

    args = parser.parse_args()
    if args.command == "watch":
        watch(resolve_repo_root(args.repo_root, args.project), args.interval_s)
    elif args.command == "enqueue":
        print(enqueue(args.objective, resolve_repo_root(args.repo_root, args.project),
                      args.paths, args.model, args.lane))
    elif args.command == "once":
        OUTBOX.mkdir(parents=True, exist_ok=True)
        repo_root = resolve_repo_root(args.repo_root, args.project) if (args.repo_root or args.project) else None
        for path in sorted(OUTBOX.glob("*.json")):
            print(process_request(path, repo_root))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
