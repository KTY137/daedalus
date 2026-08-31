"""Queue-document ownership behind the registered File Bridge facade.

Consumer-liveness admission and the registered effect start remain in
``daedalus.file_bridge.enqueue``.  This module owns only deterministic request
normalization, collision-free naming, and atomic queue publication.  Every
ambient authority (path, clock, randomness, trace stamping, and publisher) is
an explicit port supplied by the facade.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable


ClockPort = Callable[[], str]
TraceStampPort = Callable[..., dict[str, Any]]
UniqueHexPort = Callable[[], str]
WriteTextPort = Callable[[Path, str], None]


def codex_inline_brief_warning(
    objective: str,
    lane: str,
    *,
    character_limit: int,
) -> str | None:
    """Return the retained, non-blocking Codex queue-file protocol warning."""

    if lane != "codex":
        return None
    if len(objective) <= character_limit:
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


def publish_request(
    *,
    outbox: Path,
    objective: str,
    repo_root: str,
    paths: list[str],
    model: str,
    lane: str,
    project: str | None,
    source: str,
    strategy: str,
    category: str | None,
    trace_id: str | None,
    clock: ClockPort,
    unique_hex: UniqueHexPort,
    stamp_trace: TraceStampPort,
    write_text: WriteTextPort,
) -> Path:
    """Atomically publish one complete, collision-free request document."""

    outbox.mkdir(parents=True, exist_ok=True)
    slug = "".join(
        character.lower() if character.isalnum() else "-"
        for character in objective
    )[:48].strip("-")
    base = f"{clock()}-{slug or 'task'}-{unique_hex()[:8]}"
    path = outbox / f"{base}.json"
    payload: dict[str, Any] = {
        "objective": objective,
        "repo_root": repo_root,
        "paths": paths,
        "model": model,
        "source": source,
        "strategy": strategy,
        "lane": lane,
    }
    if project:
        payload["project"] = project
    if category:
        payload["category"] = category
    payload = stamp_trace(payload, trace_id=trace_id)
    write_text(path, json.dumps(payload, indent=2))
    return path


def read_request(path: Path, default_repo_root: str | None) -> dict[str, Any]:
    """Read and fail-closed normalize one queued request document."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if "objective" not in payload:
        raise ValueError("request needs an objective")
    if "repo_root" not in payload:
        if not default_repo_root:
            raise ValueError("request needs repo_root or bridge needs --repo-root")
        payload["repo_root"] = default_repo_root
    payload.setdefault("paths", [])
    payload.setdefault("model", "sonnet")
    payload.setdefault("lane", "local_only")
    payload.setdefault("source", "unknown")
    payload.setdefault("strategy", "single")
    return payload
