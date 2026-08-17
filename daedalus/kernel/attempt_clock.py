"""Trusted monotonic UTC observation clock for Attempt lifecycle records."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

from daedalus.schemas import _utc_timestamp


class AttemptLifecycleClock:
    """Produce nondecreasing UTC timestamps without accepting caller time.

    Wall time is sampled once when the trusted kernel object is constructed and
    then advanced from ``time.monotonic_ns``.  A minimum persisted timestamp may
    be supplied after restart so a terminal observation cannot predate its
    start even if the host wall clock moved backwards.

    The projection is additionally clamped to the live wall clock.  The
    canonical Event Store stamps its own rows from ``datetime.now`` while this
    clock advances a wall anchor that the host timer quantized when it was
    sampled, so the monotonic projection drifts *ahead* of the Event Store by
    up to one timer tick plus accumulated rate skew.  An observation ahead of
    the row that records it makes a lifecycle record time follow its own
    Event-Store transition, which the Attempt guards correctly refuse.  The
    clamp only ever moves an observation backwards toward the wall clock; the
    ``minimum`` and last-observation floors are applied afterwards, so the
    anti-rollback guarantee above still wins.
    """

    def __init__(self) -> None:
        self._wall_anchor = datetime.now(timezone.utc)
        self._monotonic_anchor_ns = time.monotonic_ns()
        self._last = self._wall_anchor - timedelta(microseconds=1)
        self._lock = threading.Lock()

    @staticmethod
    def _parse(value: str) -> datetime:
        normalized = _utc_timestamp(value, "minimum_timestamp")
        return datetime.fromisoformat(normalized.replace("Z", "+00:00"))

    def now(self, *, minimum: str | None = None) -> str:
        with self._lock:
            elapsed_ns = max(0, time.monotonic_ns() - self._monotonic_anchor_ns)
            current = self._wall_anchor + timedelta(microseconds=elapsed_ns // 1000)
            wall_now = datetime.now(timezone.utc)
            if wall_now < current:
                current = wall_now
            if minimum is not None:
                minimum_value = self._parse(minimum)
                if current <= minimum_value:
                    current = minimum_value + timedelta(microseconds=1)
            if current <= self._last:
                current = self._last + timedelta(microseconds=1)
            self._last = current
            return current.isoformat()


__all__ = ["AttemptLifecycleClock"]
