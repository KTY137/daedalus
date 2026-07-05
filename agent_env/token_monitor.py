from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .memory import MEMORY_DIR, MemoryEvent, append_event, refresh_todo_snapshot
from .projects import resolve_repo_root


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


def read_usage_samples(repo_root: str | None = None, max_files: int = 20) -> list[UsageSample]:
    samples: list[UsageSample] = []
    for path in _iter_project_logs(repo_root)[:max_files]:
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor local Claude usage logs and checkpoint TODOs.")
    parser.add_argument("--repo-root")
    parser.add_argument("--project")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval-s", type=float, default=30.0)
    parser.add_argument("--fresh-threshold", type=int, default=50000)
    parser.add_argument("--cached-threshold", type=int, default=120000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    repo_root = resolve_repo_root(args.repo_root, args.project)
    if args.watch:
        watch(repo_root, args.interval_s, args.fresh_threshold, args.cached_threshold)
        return
    status = checkpoint_if_needed(repo_root, args.fresh_threshold, args.cached_threshold)
    if args.json:
        print(json.dumps(status, indent=2))
    else:
        print(status["reason"])


if __name__ == "__main__":
    main()
