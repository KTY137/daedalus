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


ROOT = Path(__file__).resolve().parents[1]
OUTBOX = ROOT / "outbox"
INBOX = ROOT / "inbox"
ARCHIVE = ROOT / "runs" / "processed"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def enqueue(objective: str, repo_root: str, paths: list[str], model: str = "sonnet") -> Path:
    OUTBOX.mkdir(parents=True, exist_ok=True)
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in objective)[:48].strip("-")
    path = OUTBOX / f"{_stamp()}-{slug or 'task'}.json"
    payload = {
        "objective": objective,
        "repo_root": repo_root,
        "paths": paths,
        "model": model,
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
    return payload


def process_request(path: Path, default_repo_root: str | None = None) -> Path:
    INBOX.mkdir(parents=True, exist_ok=True)
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    payload = _read_request(path, default_repo_root)
    result_path = INBOX / f"{path.stem}.report.json"

    try:
        result = ask_claude(
            objective=payload["objective"],
            repo_root=payload["repo_root"],
            paths=payload["paths"],
            model=payload["model"],
            timeout_s=int(payload.get("timeout_s", 300)),
        )
        report = {
            "request": payload,
            "bridge_status": "done",
            "agent": result["agent"],
            "report": result["report"],
        }
    except Exception as exc:
        report = {
            "request": payload,
            "bridge_status": "failed",
            "error": str(exc),
        }

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
    watch_p.add_argument("--interval-s", type=float, default=2.0)

    enqueue_p = sub.add_parser("enqueue", help="Create a Claude request in outbox.")
    enqueue_p.add_argument("objective")
    enqueue_p.add_argument("--repo-root", required=True)
    enqueue_p.add_argument("--paths", nargs="*", default=[])
    enqueue_p.add_argument("--model", default="sonnet")

    once_p = sub.add_parser("once", help="Process current outbox requests once.")
    once_p.add_argument("--repo-root")

    args = parser.parse_args()
    if args.command == "watch":
        watch(args.repo_root, args.interval_s)
    elif args.command == "enqueue":
        print(enqueue(args.objective, args.repo_root, args.paths, args.model))
    elif args.command == "once":
        OUTBOX.mkdir(parents=True, exist_ok=True)
        for path in sorted(OUTBOX.glob("*.json")):
            print(process_request(path, args.repo_root))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
