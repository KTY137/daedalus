"""`daedalus tokens` -- what the session has burned, and nothing else.

This is OBSERVABILITY, not enforcement, and the distinction is load-bearing.
The spend ceiling lives in :mod:`daedalus.budget` and is enforced at the
syscall boundary; the intent record lives in :mod:`daedalus.spine.ledger`.
This module READS both and decides nothing about either. Concretely:

* :func:`should_checkpoint` -- the only function here that returns a decision
  -- takes exactly one argument, the token summary derived from the local
  Claude logs. Neither :func:`_budget_view` nor :func:`_spine_view` feeds it,
  and they are assembled in :func:`main` AFTER the decision is made, so no
  future edit can make a spend number change a checkpoint verdict without
  changing that signature in the diff. A test pins it.
* nothing here reserves, settles, or rolls the budget ledger, and the spine is
  opened ``read_only=True`` so SQLite itself refuses a write.

What it DOES write, and the only thing it writes, is its own report:
``memory/token_status.local.json`` plus the memory journal/TODO snapshot under
``memory/``. Two lock/sidecar files are touched by the READS -- the budget
lock beside the ledger and the WAL sidecars beside the spine database -- and
both are declared on the ``cli.token_monitor`` registry row for that reason.
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .limit_policy import ExecutionLimitPolicy, load_from_env
from .memory import MEMORY_DIR, MemoryEvent, append_event, refresh_todo_snapshot
from .foundation.projects import ROOT as REPO_ROOT, resolve_repo_root


CLAUDE_HOME = Path.home() / ".claude"
STATUS_PATH = MEMORY_DIR / "token_status.local.json"


@dataclass
class UsageSample:
    path: str
    timestamp: str
    session_id: str | None
    model: str | None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    api_error_status: int | None = None
    error: str | None = None
    text: str | None = None

    @property
    def fresh_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_creation_input_tokens


def _iter_project_logs(repo_root: str | None = None) -> list[Path]:
    project_dir = CLAUDE_HOME / "projects"
    if not project_dir.exists():
        return []
    logs = sorted(project_dir.glob("**/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not repo_root:
        return logs
    repo_norm = repo_root.lower().replace("\\", "/")
    filtered: list[Path] = []
    for path in logs:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if repo_norm in text.lower().replace("\\", "/"):
            filtered.append(path)
    return filtered


def _usage_from_message(obj: dict[str, Any]) -> dict[str, Any] | None:
    message = obj.get("message")
    if not isinstance(message, dict):
        return None
    usage = message.get("usage")
    if isinstance(usage, dict):
        return usage
    return None


def _sample_from_obj(path: Path, obj: dict[str, Any]) -> UsageSample | None:
    usage = _usage_from_message(obj)
    is_error = obj.get("isApiErrorMessage") or obj.get("apiErrorStatus")
    if not usage and not is_error:
        return None

    usage = usage or {}
    content = obj.get("message", {}).get("content", [])
    text = None
    if isinstance(content, list) and content and isinstance(content[0], dict):
        text = content[0].get("text")

    return UsageSample(
        path=str(path),
        timestamp=str(obj.get("timestamp", "")),
        session_id=obj.get("sessionId"),
        model=obj.get("message", {}).get("model"),
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
        cache_creation_input_tokens=int(usage.get("cache_creation_input_tokens") or 0),
        cache_read_input_tokens=int(usage.get("cache_read_input_tokens") or 0),
        api_error_status=obj.get("apiErrorStatus"),
        error=obj.get("error"),
        text=text,
    )


def read_usage_samples(
    repo_root: str | None = None,
    max_files: int = 20,
    *,
    limit_policy: ExecutionLimitPolicy | None = None,
) -> list[UsageSample]:
    policy = limit_policy or load_from_env()
    paths = _iter_project_logs(repo_root)
    if policy.enforces("work_scope"):
        paths = paths[:max_files]
    samples: list[UsageSample] = []
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            sample = _sample_from_obj(path, obj)
            if sample:
                samples.append(sample)
    return samples


def summarize_usage(samples: list[UsageSample]) -> dict[str, Any]:
    total_fresh = sum(s.fresh_tokens for s in samples)
    total_cached = sum(s.cache_read_input_tokens for s in samples)
    total_output = sum(s.output_tokens for s in samples)
    max_cached = max((s.cache_read_input_tokens for s in samples), default=0)
    rate_limits = [s for s in samples if s.api_error_status == 429 or s.error == "rate_limit"]
    latest = max((s.timestamp for s in samples), default="")
    return {
        "samples": len(samples),
        "latest": latest,
        "total_fresh_tokens": total_fresh,
        "total_cached_read_tokens": total_cached,
        "total_output_tokens": total_output,
        "max_cached_read_tokens": max_cached,
        "rate_limit_events": len(rate_limits),
        "latest_rate_limit": rate_limits[-1].text if rate_limits else None,
    }


def should_checkpoint(summary: dict[str, Any], fresh_threshold: int, cached_threshold: int) -> tuple[bool, str]:
    if summary["rate_limit_events"] > 0:
        return True, "Claude rate/session limit event detected."
    if summary["total_fresh_tokens"] >= fresh_threshold:
        return True, f"Fresh token usage crossed threshold ({summary['total_fresh_tokens']} >= {fresh_threshold})."
    if summary["max_cached_read_tokens"] >= cached_threshold:
        return True, f"Large cached context detected ({summary['max_cached_read_tokens']} >= {cached_threshold})."
    return False, "Token usage below checkpoint thresholds."


def checkpoint_if_needed(
    repo_root: str,
    fresh_threshold: int = 50000,
    cached_threshold: int = 120000,
) -> dict[str, Any]:
    samples = read_usage_samples(repo_root)
    summary = summarize_usage(samples)
    triggered, reason = should_checkpoint(summary, fresh_threshold, cached_threshold)
    trigger_key = f"{reason}|{summary.get('latest')}|{summary.get('rate_limit_events')}"
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    previous: dict[str, Any] = {}
    if STATUS_PATH.exists():
        try:
            previous = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = {}
    status = {"triggered": triggered, "reason": reason, "trigger_key": trigger_key, "summary": summary}
    STATUS_PATH.write_text(json.dumps(status, indent=2), encoding="utf-8")

    if triggered and previous.get("trigger_key") != trigger_key:
        append_event(
            MemoryEvent(
                kind="token_checkpoint",
                source="token-monitor",
                repo_root=repo_root,
                status="open",
                summary=reason,
                todos=["Review memory/todos.local.md before continuing after token pressure."],
                payload=status,
            )
        )
    else:
        refresh_todo_snapshot()
    return status


def watch(repo_root: str, interval_s: float, fresh_threshold: int, cached_threshold: int) -> None:
    print("TOKEN_MONITOR_START", flush=True)
    print(f"Watching Claude logs for {repo_root}", flush=True)
    print("TOKEN_MONITOR_READY", flush=True)
    last_reason = None
    while True:
        status = checkpoint_if_needed(repo_root, fresh_threshold, cached_threshold)
        reason = status["reason"]
        if status["triggered"] and reason != last_reason:
            print(f"TOKEN_CHECKPOINT {reason}", flush=True)
            last_reason = reason
        time.sleep(interval_s)


# --------------------------------------------------------------------------
# the two READ-ONLY views
#
# Both are deliberately total: an unavailable ledger degrades to a named reason
# rather than an exception, because read-only inspection fails OPEN (the plan's
# Gate-0 exit condition says protected effects fail closed, inspection does
# not). `daedalus tokens` refusing to tell you your token count because another
# lane happens to hold the budget lock would be a monitor that is useless
# exactly when the machine is busy -- which is the only time you ask it.
# --------------------------------------------------------------------------

#: Short on purpose. The canonical timeout is 30s, correct for a writer that
#: must not race; a reader that blocks half a minute behind a spending lane is
#: worse than a reader that says "busy". Nothing downstream branches on it.
BUDGET_READ_LOCK_TIMEOUT_S = 2.0


def _budget_view(lock_timeout_s: float = BUDGET_READ_LOCK_TIMEOUT_S) -> dict[str, Any]:
    """The canonical spend ledger's current state, as an observation.

    Goes through :class:`daedalus.budget.Ledger` rather than parsing
    ``ledger.json`` here: a second reader of the money file is a second answer
    to "what has been spent", and the one that disagrees is always the copy.
    ``state()`` is the ledger's own read path -- it takes the cross-process
    lock so the read cannot straddle a write, and mutates nothing.
    """
    from .budget import BudgetError, Ledger

    try:
        state = Ledger(lock_timeout_s=lock_timeout_s).state()
    except BudgetError as exc:
        return {"available": False, "reason": str(exc)}
    except OSError as exc:  # unreadable path, permissions, full disk
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
    return {"available": True, **state.as_dict()}


def _render_budget_view(budget: dict[str, Any]) -> str:
    if not budget.get("available"):
        return f"budget: unavailable -- {budget['reason']}"
    period_limit = (
        f"${budget['ceiling_usd']:.2f} ceiling"
        if budget["period_ceiling_enabled"]
        else "uncapped period USD ceiling"
    )
    call_limit = (
        f"{budget['calls']} of {budget['max_calls']} calls"
        if budget["billable_call_ceiling_enabled"]
        else f"{budget['calls']} calls recorded; call ceiling disabled"
    )
    return (
        f"budget: ${budget['spent_usd']:.4f} spent + "
        f"${budget['reserved_usd']:.4f} reserved of {period_limit} "
        f"({call_limit}, period {budget['period_key']})"
    )


def _spine_view(recent: int = 3) -> dict[str, Any]:
    """How much work is in flight on the intent spine, as an observation.

    Opened ``read_only=True``: SQLite refuses any write at the engine, so this
    cannot become a writer by accident. The existence check comes first because
    the read-only open of a MISSING database is an error, and a monitor must
    not be the thing that brings a spine database into existence.
    """
    from .spine.ledger import SpineLedger, default_db_path

    path = default_db_path()
    if not path.exists():
        return {"available": False, "reason": f"no spine ledger at {path}"}
    try:
        ledger = SpineLedger(path, read_only=True)
    except Exception as exc:  # sqlite3.Error, OSError -- all mean "cannot look"
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
    try:
        open_intents = ledger.open_intents()
        latest = ledger.recent_intents(limit=recent)
        return {
            "available": True,
            "path": str(path),
            "open_intents": len(open_intents),
            "recent": [
                {"id": i.id, "kind": i.kind, "state": i.state, "ts": i.created_ts}
                for i in latest
            ],
        }
    except Exception as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
    finally:
        ledger.close()


def main(argv: Sequence[str] | None = None) -> int:
    # THE BOUNDARY COMES FIRST -- before argument parsing, exactly as
    # daedalus/loop.py does it (72b5af82) and for the same reason. This module
    # has two doors: `daedalus tokens`, which reaches main() through cli.main's
    # guarded dispatch, and `python -m daedalus.token_monitor`, which does not.
    # Putting begin_effect at the top of main() means both doors pass it, so
    # adding the subcommand did not open a second, softer way in -- and no
    # branch below can reach the status write without having passed it.
    #
    # process_guard_boundary_decision installs the process-wide spend net
    # itself and returns the GuardDecision naming what is interposed, so the
    # receipt cannot cite a guard that never ran. begin_effect performs no
    # effect -- it authorises one -- and refuses the start unless the
    # cli.token_monitor row, the declared effects and that decision agree. The
    # registry anchor pins this call, so deleting it is a conformance failure
    # rather than a silent regression.
    from .budget import process_guard_boundary_decision
    from .spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "cli.token_monitor",
        REGISTRY_BY_ID["cli.token_monitor"].effects,
        (process_guard_boundary_decision(),),
    )

    parser = argparse.ArgumentParser(
        prog="daedalus tokens",
        description="Report local Claude token usage alongside the spend "
                    "ledger and the intent spine, and checkpoint the TODO "
                    "snapshot under token pressure. It READS the ledger and "
                    "the spine and decides nothing about either.",
    )
    parser.add_argument("--repo-root")
    parser.add_argument("--project")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval-s", type=float, default=30.0)
    parser.add_argument("--fresh-threshold", type=int, default=50000)
    parser.add_argument("--cached-threshold", type=int, default=120000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    # A verb invoked with no argument still has to answer. This module used
    # to be started only by a hook that always passed --repo-root, so
    # "neither flag" was a ValueError; as a console verb the obvious default
    # is THIS repository. Resolved from the package location and never from
    # cwd, so `daedalus tokens` means the same thing from any directory --
    # the same rule `daedalus drill` applies to its script path.
    if not args.repo_root and not args.project:
        args.repo_root = str(REPO_ROOT)
    repo_root = resolve_repo_root(args.repo_root, args.project)

    if args.watch:
        watch(repo_root, args.interval_s, args.fresh_threshold, args.cached_threshold)
        return 0

    status = checkpoint_if_needed(repo_root, args.fresh_threshold, args.cached_threshold)
    # Assembled AFTER the verdict exists, and merged into the REPORT rather
    # than into `status`: the persisted checkpoint record stays byte-for-byte
    # what it was before this verb existed, and the spend numbers are visibly
    # downstream of the decision instead of an input to it.
    report = {**status, "budget": _budget_view(), "spine": _spine_view()}
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(report["reason"])
        budget = report["budget"]
        print(_render_budget_view(budget))
        spine = report["spine"]
        if spine.get("available"):
            print(f"spine: {spine['open_intents']} intent(s) in flight")
        else:
            print(f"spine: unavailable -- {spine['reason']}")
    return 0


if __name__ == "__main__":
    # Safe BECAUSE main() starts at the canonical effect boundary: this tail is
    # a plain call into a guarded entrypoint, not a bypass of one. Same shape
    # as daedalus/loop.py's tail, deliberately.
    raise SystemExit(main())
