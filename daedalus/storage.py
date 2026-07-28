"""Fail-closed storage capability check (the storage watermark).

A missing or too-full volume must surface as ``storage_unavailable`` --
never silently spill work onto another volume (HANDOFF.md section 1.4).
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

DEFAULT_MIN_FREE_GIB = 2.0
_GIB = 1024**3


class StorageUnavailable(RuntimeError):
    """Raised when a required volume is missing or below the free-space watermark."""


@dataclass(frozen=True)
class StorageStatus:
    path: str
    total_bytes: int
    free_bytes: int
    min_free_bytes: int
    state: str  # "ok" | "storage_unavailable"

    @property
    def ok(self) -> bool:
        return self.state == "ok"


def _min_free_bytes(min_free_gib: float | None) -> int:
    if min_free_gib is None:
        raw = os.environ.get("DAEDALUS_MIN_FREE_GIB", "")
        try:
            min_free_gib = float(raw) if raw else DEFAULT_MIN_FREE_GIB
        except ValueError:
            min_free_gib = DEFAULT_MIN_FREE_GIB
    return int(min_free_gib * _GIB)


def check_storage(path: str, min_free_gib: float | None = None) -> StorageStatus:
    min_free = _min_free_bytes(min_free_gib)
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return StorageStatus(
            path=str(path),
            total_bytes=0,
            free_bytes=0,
            min_free_bytes=min_free,
            state="storage_unavailable",
        )
    state = "ok" if usage.free >= min_free else "storage_unavailable"
    return StorageStatus(
        path=str(path),
        total_bytes=usage.total,
        free_bytes=usage.free,
        min_free_bytes=min_free,
        state=state,
    )


def require_storage(path: str, min_free_gib: float | None = None) -> StorageStatus:
    status = check_storage(path, min_free_gib=min_free_gib)
    if not status.ok:
        raise StorageUnavailable(
            f"storage_unavailable: {status.path} has {status.free_bytes} bytes free, "
            f"requires {status.min_free_bytes} bytes; refusing to fall back to another volume"
        )
    return status
