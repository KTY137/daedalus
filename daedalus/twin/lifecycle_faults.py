"""Process-safe Project Twin lifecycle writes and bounded fault recovery.

This module layers an operating-system advisory lock over the canonical
``AtomicProjectTwinLifecycleStore``.  The underlying store remains the sole
serialization and lifecycle authority; this wrapper only closes the lost-update
window between loading the current head and atomically replacing the lifecycle
file.

On platforms without ``fcntl`` the wrapper refuses rather than claiming
cross-process safety it cannot provide.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from daedalus.kernel.artifacts import ArtifactRef

from .genesis import ProjectTwinContractError, ProjectTwinManifest
from .lifecycle import AtomicProjectTwinLifecycleStore

try:  # pragma: no cover - availability is asserted by the supported CI platform
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


class LockedProjectTwinLifecycleStore(AtomicProjectTwinLifecycleStore):
    """Serialize lifecycle compare-and-swap operations across processes.

    The lock is repository-specific, so unrelated repositories can progress in
    parallel.  It is held across load, expected-head comparison, transition
    verification, temporary-file persistence, atomic replacement, directory
    fsync, and final return.
    """

    def _lock_path(self, repository_id: str) -> Path:
        return self.root / f".{self._repository_key(repository_id)}.lock"

    @contextmanager
    def _exclusive_repository_lock(self, repository_id: str) -> Iterator[None]:
        if fcntl is None:
            raise ProjectTwinContractError(
                "cross-process Project Twin lifecycle locking is unavailable"
            )
        lock_path = self._lock_path(repository_id)
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def append(
        self,
        manifest: ProjectTwinManifest,
        *,
        expected_head_sha256: str | None,
    ) -> ArtifactRef:
        with self._exclusive_repository_lock(manifest.repository_id):
            return super().append(
                manifest,
                expected_head_sha256=expected_head_sha256,
            )


__all__ = ["LockedProjectTwinLifecycleStore"]
