"""Crash journal and request-identity ownership for the file bridge.

The legacy :mod:`daedalus.file_bridge` module remains the registered effect
facade.  This module owns the deterministic identities and the small durable
journal behind that facade.  Paths, clocks, canonical hashing, and the atomic
publisher are explicit ports so importing the owner creates no second store or
effect entrypoint and the facade's compatibility seams stay live.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


CanonicalShaPort = Callable[[dict[str, Any]], str]
JournalPathPort = Callable[[str], Path]
NowPort = Callable[[], str]
RequestShaPort = Callable[[dict[str, Any]], str]
WriteJsonPort = Callable[[Path, dict[str, Any]], None]


def request_key(path: Path) -> str:
    """Return the filename-derived idempotency key of a queued request."""

    return path.stem


def request_sha256(
    payload: dict[str, Any],
    *,
    canonical_sha: CanonicalShaPort,
) -> str:
    """Return the canonical identity of a normalized request body."""

    return canonical_sha(payload)


def raw_request_sha256(path: Path) -> str:
    """Return byte identity when poison input cannot be normalized as JSON."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def report_request_binding(
    report: dict[str, Any],
    key: str,
    *,
    request_sha: RequestShaPort,
) -> str:
    """Return the request digest proven by a complete terminal report."""

    status = report.get("bridge_status")
    if not isinstance(status, str) or not status.strip():
        raise ValueError("existing report has no terminal bridge_status")
    report_key = report.get("request_file")
    if report_key is not None and report_key != key:
        raise ValueError(
            f"existing report is bound to request_file {report_key!r}, "
            f"not {key!r}"
        )

    explicit = report.get("request_sha256")
    if explicit is not None and (
        not isinstance(explicit, str)
        or not re.fullmatch(r"[0-9a-f]{64}", explicit)
    ):
        raise ValueError("existing report request_sha256 is malformed")
    embedded = report.get("request")
    embedded_sha256 = request_sha(embedded) if isinstance(embedded, dict) else None
    if (
        explicit is not None
        and embedded_sha256 is not None
        and explicit != embedded_sha256
    ):
        raise ValueError(
            "existing report request_sha256 contradicts its request body"
        )
    bound = explicit or embedded_sha256
    if bound is None:
        raise ValueError("existing report has no provable request identity")
    return bound


def effect_identity_for(
    key: str,
    entry: dict[str, Any],
    *,
    now: NowPort,
) -> dict[str, str]:
    """Return the deterministic Effect-Lease identity for one request key."""

    digest = hashlib.sha256(
        f"daedalus.file-bridge.effect:{key}".encode("utf-8")
    ).hexdigest()
    expected_attempt = f"file-bridge-{digest[:32]}"
    expected_lease = f"file-bridge-{digest[:32]}-lease"
    existing = entry.get("effect_identity")
    if existing is None:
        return {
            "attempt_id": expected_attempt,
            "lease_id": expected_lease,
            "issued_at": now(),
        }
    if not isinstance(existing, dict):
        raise ValueError("journal effect_identity must be an object")
    if (
        existing.get("attempt_id") != expected_attempt
        or existing.get("lease_id") != expected_lease
    ):
        raise ValueError(
            "journal effect_identity does not match the request filename key"
        )
    issued_text = existing.get("issued_at")
    if not isinstance(issued_text, str) or not issued_text.strip():
        raise ValueError("journal effect_identity issued_at is missing")
    try:
        issued = datetime.fromisoformat(issued_text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("journal effect_identity issued_at is malformed") from exc
    if issued.tzinfo is None:
        raise ValueError("journal effect_identity issued_at must include a timezone")
    canonical = issued.astimezone(timezone.utc).isoformat(timespec="microseconds")
    if issued_text != canonical:
        raise ValueError("journal effect_identity issued_at is not canonical UTC")
    return {
        "attempt_id": expected_attempt,
        "lease_id": expected_lease,
        "issued_at": issued_text,
    }


def journal_dir(archive: Path) -> Path:
    """Return the journal directory derived from the facade archive path."""

    return archive / ".journal"


def mission_projection_dir(key: str, *, journal: Path) -> Path:
    """Return a disposable mission projection path derived only from ``key``."""

    digest = hashlib.sha256(
        f"daedalus.file-bridge.mission-projection:{key}".encode("utf-8")
    ).hexdigest()
    return journal / "mission-supervisor" / digest


def journal_path(key: str, *, journal: Path) -> Path:
    return journal / f"{key}.json"


def request_lock_path(key: str, *, journal: Path) -> Path:
    """Return the cross-process claim path for a request identity."""

    return journal / f"{key}.process.lock"


def read_journal(key: str, *, path_for: JournalPathPort) -> dict[str, Any]:
    """Read one journal, treating missing or malformed state as empty."""

    try:
        entry = json.loads(path_for(key).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    return entry if isinstance(entry, dict) else {}


def crash_journal_state(detail: str, *, journal: Path) -> tuple[bool, str]:
    """Create and mechanically verify the durable journal precondition."""

    journal.mkdir(parents=True, exist_ok=True)
    allowed = journal.is_dir()
    evidence = f"journal={journal}; {detail}"
    if not allowed:
        evidence = "journal directory unavailable; " + evidence
    return allowed, evidence


def write_journal(
    key: str,
    entry: dict[str, Any],
    *,
    now: NowPort,
    path_for: JournalPathPort,
    write_json: WriteJsonPort,
) -> None:
    """Timestamp and atomically publish one journal entry through its ports."""

    entry["updated"] = now()
    write_json(path_for(key), entry)
