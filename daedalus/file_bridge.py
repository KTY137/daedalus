from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .memory import record_from_bridge_report
from .projects import resolve_repo_root


ROOT = Path(__file__).resolve().parents[1]
OUTBOX = ROOT / "outbox"
INBOX = ROOT / "inbox"
ARCHIVE = ROOT / "runs" / "processed"
# Watcher liveness marker (see heartbeat_status): written by the watch loop,
# read by `daedalus doctor` and `file_bridge status`.
HEARTBEAT_PATH = ROOT / "runs" / "bridge_heartbeat.json"

# Heartbeat policy: an idle watcher beats every poll (throttled to
# IDLE_BEAT_EVERY_S); a beat older than STALE_AFTER_S with no in-flight task
# means the watcher is dead. While a task is in flight the beat carries
# `current` and is allowed to age up to BUSY_BUDGET_S (codex real-task budget
# is 8-20 min, provider timeout 1500 s -- a 2 min rule would false-alarm).
IDLE_BEAT_EVERY_S = 15.0
STALE_AFTER_S = 120.0
BUSY_BUDGET_S = 1800.0

# Codex-lane protocol lesson (2026-07-11, cost ~2 h): objectives longer than
# this without a CODEX_QUEUE.md reference smell like an inline task brief and
# get a (non-blocking) warning from enqueue().
CODEX_INLINE_BRIEF_CHARS = 200


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _seen_dir() -> Path:
    """Read-state ledger: one marker file per acknowledged report.

    Derived from INBOX at call time so tests that patch INBOX get a matching
    ledger for free."""
    return INBOX / ".seen"


def _latest_log() -> Path:
    """Single well-known append-only file -- one line per finished report --
    so an orchestrator can file-watch exactly one path instead of polling."""
    return INBOX / "LATEST.log"


def codex_inline_brief_warning(objective: str, lane: str) -> str | None:
    """Return a warning string when a codex-lane objective smells like an
    inline task brief, else None. Never blocks the enqueue."""
    if lane != "codex":
        return None
    if len(objective) <= CODEX_INLINE_BRIEF_CHARS:
        return None
    if "codex_queue" in objective.lower().replace(" ", "_"):
        return None
    return (
        f"codex-lane objective is {len(objective)} chars with no CODEX_QUEUE.md "
        "reference -- inline briefs bounce on this lane (protocol lesson "
        "2026-07-11). Put the full brief in docs/CODEX_QUEUE.md in the target "
        'repo and enqueue a short pointer instead, e.g. '
        '"Execute task C9 from docs/CODEX_QUEUE.md".'
    )


def enqueue(objective: str, repo_root: str, paths: list[str], model: str = "sonnet",
            lane: str = "auto", project: str | None = None,
            source: str = "unknown", strategy: str = "single",
            category: str | None = None) -> Path:
    """Drop one task request into the outbox for the watcher to dispatch.

    CODEX-LANE PROTOCOL (learned 2026-07-11, cost ~2 h of bounced tasks):
    the codex lane executes best from a *queue-file task*, not an inline
    brief. The working pattern is: write the full brief as a task entry in
    ``docs/CODEX_QUEUE.md`` inside the target repo, then enqueue a short
    objective that names it ("Execute task C9 from docs/CODEX_QUEUE.md").
    Long inline objectives on ``--lane codex`` bounce or underperform;
    :func:`codex_inline_brief_warning` prints a stderr warning (non-blocking)
    when an objective smells like an inline brief (> ~200 chars, no
    CODEX_QUEUE reference).
    """
    warning = codex_inline_brief_warning(objective, lane)
    if warning:
        print(f"WARNING: {warning}", file=sys.stderr)
    OUTBOX.mkdir(parents=True, exist_ok=True)
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in objective)[:48].strip("-")
    # A UNIQUE name, not a probably-unique one.
    #
    # This was `f"{_stamp()}-{slug}.json"`, and `_stamp()` has SECOND
    # resolution: two enqueues of the same objective inside one second produced
    # the same path and the second silently overwrote the first. A task queue
    # that drops a task under load, with no error and nothing in any log --
    # found by the acceptance run, which queued two requests and got one report.
    # Timestamps are for humans reading the directory; uniqueness has to come
    # from somewhere that cannot collide.
    base = f"{_stamp()}-{slug or 'task'}"
    path = OUTBOX / f"{base}.json"
    if path.exists():
        suffix = 1
        while (OUTBOX / f"{base}-{suffix}.json").exists():
            suffix += 1
        path = OUTBOX / f"{base}-{suffix}.json"
    payload = {
        "objective": objective,
        "repo_root": repo_root,
        "paths": paths,
        "model": model,
        "source": source,
        # Ikarus strategy:
        #   single -> route this one task through Ikarus
        #   spawn  -> let Ikarus decompose the objective and dispatch the bench
        "strategy": strategy,
        # Which lane the watcher may dispatch to:
        #   auto       -> route; run on the free bench when eligible, else Claude
        #   local      -> same as auto (prefer the bench), else fall back to Claude
        #   local_only -> local bench only; never fall back to Claude
        #   claude     -> always the trusted Claude lane
        #   codex      -> always the Codex CLI (external, egress-gated; no fallback)
        "lane": lane,
    }
    if project:
        payload["project"] = project
    if category:
        # Additive metadata only -- the role-category tag of the routed/owning
        # agent, carried through for the UI/bus/reports. Never consulted by
        # the lane gate in core.process_bridge_payload.
        payload["category"] = category
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
    payload.setdefault("lane", "local_only")  # fail-closed: an unlabeled file (hand-dropped/legacy) never spends unattended
    payload.setdefault("source", "unknown")
    payload.setdefault("strategy", "single")
    return payload


def _note_report_arrival(result_path: Path, report: dict[str, Any]) -> None:
    """Append one line per finished report to inbox/LATEST.log (best-effort).

    Exactly one well-known path an orchestrator can watch or tail instead of
    remembering to poll the whole inbox. New reports are unread by definition
    (no .seen marker) until `file_bridge mark-read` acknowledges them."""
    lane = report.get("lane") or (report.get("request") or {}).get("lane") or "?"
    line = (f"{_now_iso()} {result_path.name} "
            f"status={report.get('bridge_status', '?')} lane={lane}\n")
    try:
        with _latest_log().open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass  # signal channel only -- never fail the report write over it


def process_request(path: Path, default_repo_root: str | None = None) -> Path:
    INBOX.mkdir(parents=True, exist_ok=True)
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    payload = _read_request(path, default_repo_root)
    result_path = INBOX / f"{path.stem}.report.json"

    from .core import process_bridge_payload
    report = process_bridge_payload(payload)

    result_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _note_report_arrival(result_path, report)
    record_from_bridge_report(report)
    shutil.move(str(path), str(ARCHIVE / path.name))
    return result_path


# -- watcher heartbeat ------------------------------------------------------

_last_idle_beat = 0.0


def write_heartbeat(project: str | None = None, repo_root: str | None = None,
                    interval_s: float | None = None,
                    current: dict[str, Any] | None = None,
                    force: bool = False) -> None:
    """Best-effort liveness marker written by the watch loop.

    Idle beats are throttled to one per IDLE_BEAT_EVERY_S; task start/finish
    beats (``force=True``) always land. Written via temp-file + os.replace so
    a concurrent doctor read never sees a half-written file. Never raises."""
    global _last_idle_beat
    now = time.time()
    if not force and current is None and now - _last_idle_beat < IDLE_BEAT_EVERY_S:
        return
    payload = {
        "ts": _now_iso(),
        "epoch": now,
        "pid": os.getpid(),
        "project": project,
        "repo_root": repo_root,
        "interval_s": interval_s,
        "current": current,
    }
    try:
        HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = HEARTBEAT_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, HEARTBEAT_PATH)
        if current is None:
            _last_idle_beat = now
    except OSError:
        pass  # liveness signal only -- never let it kill or slow the watcher


def restart_hint(hb: dict[str, Any] | None = None) -> str:
    """The exact one-liner to (re)start the watcher, from heartbeat context."""
    hb = hb or {}
    if hb.get("project"):
        return f"python -m daedalus.file_bridge watch --project {hb['project']}"
    if hb.get("repo_root"):
        return f'python -m daedalus.file_bridge watch --repo-root "{hb["repo_root"]}"'
    return "python -m daedalus.file_bridge watch --project <project>"


def heartbeat_status(now: float | None = None) -> dict[str, Any]:
    """Classify the watcher heartbeat. States:

    * ``none``   -- no heartbeat file: watcher not running, or it predates the
                    heartbeat feature (cross-check: `daedalus watcher status`).
    * ``alive``  -- idle beat fresher than STALE_AFTER_S.
    * ``busy``   -- a task is in flight, within BUSY_BUDGET_S.
    * ``wedged`` -- a task has been in flight longer than BUSY_BUDGET_S.
    * ``stale``  -- idle beat older than STALE_AFTER_S: watcher is dead.
    """
    now = time.time() if now is None else now
    try:
        hb = json.loads(HEARTBEAT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {"state": "none", "restart": restart_hint(),
                "detail": "no heartbeat recorded (watcher not running, or "
                          "started before the heartbeat feature landed)"}
    age = max(0.0, now - float(hb.get("epoch") or 0.0))
    out = {
        "age_s": round(age, 1),
        "pid": hb.get("pid"),
        "project": hb.get("project"),
        "repo_root": hb.get("repo_root"),
        "current": hb.get("current"),
        "restart": restart_hint(hb),
    }
    current = hb.get("current")
    if current:
        busy_for = max(0.0, now - float(current.get("started_epoch") or 0.0))
        out["busy_for_s"] = round(busy_for, 1)
        out["state"] = "busy" if busy_for <= BUSY_BUDGET_S else "wedged"
        return out
    out["state"] = "alive" if age <= STALE_AFTER_S else "stale"
    return out


# -- report read-state + status ---------------------------------------------

def unread_reports() -> list[Path]:
    """Reports in the inbox with no .seen marker, oldest first."""
    if not INBOX.exists():
        return []
    seen = _seen_dir()
    return [p for p in sorted(INBOX.glob("*.report.json"))
            if not (seen / p.name).exists()]


def mark_read(names: list[str] | None = None, all_reports: bool = False) -> list[str]:
    """Acknowledge reports by dropping a marker per report into inbox/.seen/.
    Returns the report names actually marked."""
    targets: list[Path] = []
    if all_reports:
        targets = unread_reports()
    else:
        for name in names or []:
            path = INBOX / name
            if not path.exists() and not name.endswith(".report.json"):
                path = INBOX / f"{name}.report.json"
            if path.exists():
                targets.append(path)
    marked = []
    if targets:
        _seen_dir().mkdir(parents=True, exist_ok=True)
    for path in targets:
        try:
            (_seen_dir() / path.name).touch()
            marked.append(path.name)
        except OSError:
            pass
    return marked


def _report_brief(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        payload = {}
    request = payload.get("request") or {}
    summary = ((payload.get("report") or {}).get("summary")
               or payload.get("error") or "")
    return {
        "name": path.name,
        "status": payload.get("bridge_status") or "?",
        "lane": payload.get("lane") or request.get("lane") or "?",
        "project": request.get("project") or "",
        "summary": " ".join(str(summary).split())[:160],  # one line for the console
    }


def bridge_status(project: str | None = None) -> dict[str, Any]:
    """One-call answer to: is anything queued, is anything running, and are
    there finished reports I have not read yet?"""
    queued = []
    for path in sorted(OUTBOX.glob("*.json")) if OUTBOX.exists() else []:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            payload = {}
        if project and payload.get("project") not in (project, None, ""):
            continue
        queued.append({"name": path.name, "lane": payload.get("lane") or "?",
                       "project": payload.get("project") or ""})
    unread = []
    for path in unread_reports():
        brief = _report_brief(path)
        if project and brief["project"] not in (project, ""):
            continue
        unread.append(brief)
    hb = heartbeat_status()
    in_flight = hb.get("current") if hb.get("state") in ("busy", "wedged") else None
    return {
        "project": project,
        "watcher": hb,
        "queued": queued,
        "queue_depth": len(queued),
        "in_flight": in_flight,
        "unread": unread,
        "unread_count": len(unread),
        "reports_total": len(list(INBOX.glob("*.report.json"))) if INBOX.exists() else 0,
        "latest_log": str(_latest_log()),
    }


def stream_state(project: str | None = None) -> dict[str, Any]:
    """Compact, CHEAP snapshot for the SSE live stream. Reads ONLY the file bus
    (outbox/inbox/heartbeat) — no git, PowerShell or Ollama — so it can be polled
    once a second to drive the cockpit's live badges without the heavy dashboard.
    """
    st = bridge_status(project)
    newest = None
    if INBOX.exists():
        reports = sorted(INBOX.glob("*.report.json"), key=lambda p: p.stat().st_mtime)
        if reports:
            newest = _report_brief(reports[-1])
    return {
        "queue_depth": st["queue_depth"],
        "in_flight": bool(st["in_flight"]),
        "unread_count": st["unread_count"],
        "watcher_state": (st["watcher"] or {}).get("state"),
        "reports_total": st["reports_total"],
        "latest_report": newest,
    }


def _print_status(status: dict[str, Any]) -> None:
    hb = status["watcher"]
    state = hb["state"]
    if state == "alive":
        watcher = f"alive (heartbeat {hb['age_s']}s ago, pid {hb.get('pid')})"
    elif state == "busy":
        cur = hb.get("current") or {}
        watcher = f"busy on {cur.get('file', '?')} for {hb.get('busy_for_s')}s (pid {hb.get('pid')})"
    elif state == "wedged":
        cur = hb.get("current") or {}
        watcher = (f"POSSIBLY WEDGED on {cur.get('file', '?')} for {hb.get('busy_for_s')}s "
                   f"-- investigate, then restart: {hb['restart']}")
    elif state == "stale":
        watcher = (f"STALE (last heartbeat {hb['age_s']}s ago > {STALE_AFTER_S:.0f}s) "
                   f"-- restart: {hb['restart']}")
    else:
        watcher = f"{hb.get('detail', 'unknown')} -- start: {hb['restart']}"
    print(f"Watcher : {watcher}")
    print(f"Queue   : {status['queue_depth']} queued")
    for item in status["queued"]:
        print(f"  {item['name']}  lane={item['lane']}")
    if status["in_flight"]:
        print(f"In-flight: {status['in_flight'].get('file', '?')}")
    print(f"Reports : {status['reports_total']} total, {status['unread_count']} UNREAD")
    for item in status["unread"]:
        print(f"  UNREAD {item['name']}  status={item['status']} lane={item['lane']}")
        if item["summary"]:
            print(f"         {item['summary']}")
    if status["unread_count"]:
        print("Acknowledge: python -m daedalus.file_bridge mark-read --all "
              "(or name specific reports)")
    print(f"Arrival log: {status['latest_log']}")


def watch(default_repo_root: str | None, interval_s: float,
          project: str | None = None) -> None:
    OUTBOX.mkdir(parents=True, exist_ok=True)
    INBOX.mkdir(parents=True, exist_ok=True)
    print("AGENT_BRIDGE_START", flush=True)
    print(f"Watching {OUTBOX}", flush=True)
    print("AGENT_BRIDGE_READY", flush=True)

    def _beat(current: dict[str, Any] | None = None, force: bool = False) -> None:
        write_heartbeat(project=project, repo_root=default_repo_root,
                        interval_s=interval_s, current=current, force=force)

    while True:
        _beat()
        for path in sorted(OUTBOX.glob("*.json")):
            print(f"Processing {path.name}", flush=True)
            _beat(current={"file": path.name, "started_epoch": time.time(),
                           "started_ts": _now_iso()}, force=True)
            try:
                result = process_request(path, default_repo_root)
                print(f"Wrote {result}", flush=True)
            except Exception as exc:
                # A poison request must not kill the watcher (or crash-loop it
                # on restart): report the failure and archive the request.
                print(f"FAILED {path.name}: {exc}", flush=True)
                try:
                    report = {"request_file": path.name, "bridge_status": "failed",
                              "error": str(exc)}
                    result_path = INBOX / f"{path.stem}.report.json"
                    result_path.write_text(json.dumps(report, indent=2),
                                           encoding="utf-8")
                    _note_report_arrival(result_path, report)
                    shutil.move(str(path), str(ARCHIVE / path.name))
                except OSError:
                    pass  # locked/half-written file: retry next poll
            _beat(force=True)
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
    enqueue_p.add_argument("--lane", default="auto",
                           choices=["auto", "claude", "local", "local_only", "codex"],
                           help="auto/local prefer the free bench; local_only never calls Claude; "
                                "claude forces the trusted lane; codex forces the external "
                                "Codex CLI (egress-gated, no fallback)")
    enqueue_p.add_argument("--source", default="unknown",
                           choices=["unknown", "codex", "claude", "user", "ikarus"],
                           help="who queued the request")
    enqueue_p.add_argument("--strategy", default="single", choices=["single", "spawn"],
                           help="single routes one task; spawn lets Ikarus decompose and fan out")

    once_p = sub.add_parser("once", help="Process current outbox requests once.")
    once_p.add_argument("--repo-root")
    once_p.add_argument("--project")

    status_p = sub.add_parser(
        "status", help="Queue depth, in-flight task, watcher liveness, UNREAD reports.")
    status_p.add_argument("--project", help="filter queue/reports to one project")
    status_p.add_argument("--json", action="store_true")

    mark_p = sub.add_parser(
        "mark-read", help="Acknowledge finished reports (drops markers in inbox/.seen/).")
    mark_p.add_argument("names", nargs="*", help="report file names (with or without .report.json)")
    mark_p.add_argument("--all", action="store_true", help="mark every unread report as read")

    args = parser.parse_args()
    if args.command == "watch":
        watch(resolve_repo_root(args.repo_root, args.project), args.interval_s,
              project=args.project)
    elif args.command == "enqueue":
        print(enqueue(args.objective, resolve_repo_root(args.repo_root, args.project),
                      args.paths, args.model, args.lane, args.project,
                      args.source, args.strategy))
    elif args.command == "once":
        OUTBOX.mkdir(parents=True, exist_ok=True)
        repo_root = resolve_repo_root(args.repo_root, args.project) if (args.repo_root or args.project) else None
        for path in sorted(OUTBOX.glob("*.json")):
            print(process_request(path, repo_root))
    elif args.command == "status":
        status = bridge_status(args.project)
        if args.json:
            print(json.dumps(status, indent=2))
        else:
            _print_status(status)
    elif args.command == "mark-read":
        if not args.names and not args.all:
            print("nothing to do: pass report names or --all")
        else:
            marked = mark_read(args.names, all_reports=args.all)
            print(f"marked {len(marked)} report(s) read")
            for name in marked:
                print(f"  {name}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
