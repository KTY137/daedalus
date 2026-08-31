"""Claimed request dispatch behind the File Bridge effect facade.

The registered ``file_bridge.process`` effect start remains in
``daedalus.file_bridge.process_request``.  This owner acquires the canonical
per-request OS claim and resolves the crash race where another consumer has
already archived the source while the loser waited.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, ContextManager


CompletedReportPort = Callable[[Path], dict[str, Any] | None]
KeyPort = Callable[[Path], str]
LockPort = Callable[[Path, str], ContextManager[Any]]
ProcessClaimedPort = Callable[..., Path]
RequestLockPathPort = Callable[[str], Path]


def claim_and_dispatch_request(
    path: Path,
    default_repo_root: str | None,
    *,
    inbox: Path,
    key_for: KeyPort,
    lock_path_for: RequestLockPathPort,
    lock: LockPort,
    completed_report: CompletedReportPort,
    process_claimed: ProcessClaimedPort,
) -> Path:
    """Process one request under its filename-derived cross-process claim."""

    key = key_for(path)
    label = f"file-bridge request {key!r}"
    with lock(lock_path_for(key), label):
        if not path.exists():
            result_path = inbox / f"{key}.report.json"
            if completed_report(result_path) is not None:
                return result_path
            raise FileNotFoundError(path)
        return process_claimed(path, default_repo_root, key=key)
