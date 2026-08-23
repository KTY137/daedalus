"""Trusted monotonic UTC observation clock for Attempt lifecycle records."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

from daedalus.schemas import _utc_timestamp

# How long :meth:`AttemptLifecycleClock.now` may wait for the Event-Store wall
# clock to reach a timestamp the strict-increase floors pushed into the future.
# One wall-clock tick is the realistic wait: CPython advertises 15.625 ms for
# ``GetSystemTimeAsFileTime`` on Windows, and this budget clears that with room
# to spare while still refusing to block on a genuinely anomalous ``minimum``.
_MAX_WALL_CLOCK_CATCHUP_SECONDS = 0.25


def _wall_clock_now() -> datetime:
    """Read the same wall clock the Event Store stamps its rows from.

    ``daedalus.spine.ledger._now_iso`` is ``datetime.now(timezone.utc)``.  The
    lifecycle clock must read that identical source, because the readers in
    ``attempt_spine_reader`` and ``attempt_ledger`` bind a trusted record time
    to its Event-Store transition with *zero* negative tolerance: a trusted time
    that lags the event is safe, one that leads it can fabricate order.
    """
    return datetime.now(timezone.utc)


class AttemptLifecycleClock:
    """Produce nondecreasing UTC timestamps without accepting caller time.

    Wall time is sampled once when the trusted kernel object is constructed and
    then advanced from ``time.monotonic_ns``.  A minimum persisted timestamp may
    be supplied after restart so a terminal observation cannot predate its
    start even if the host wall clock moved backwards.

    The monotonic projection is an *upper bound only*.  It bounds how far a
    forward wall-clock step may drag an observation, but it is never emitted on
    its own, because the two clocks do not share a resolution: on Windows
    CPython ``time.monotonic`` is ``GetTickCount64()`` with a 15.625 ms
    quantum, so an anchor taken just before a tick and a reading taken just
    after one overstate the elapsed interval by nearly a full quantum.  Emitting
    that projection let the trusted clock lead the Event-Store timestamp by up
    to ~15.6 ms and made the zero-tolerance readers reject sound lifecycles.

    Two rules keep the emitted value behind the Event Store:

    * clamp the projection to the Event-Store wall clock, so a coarse monotonic
      quantum can never be mistaken for elapsed time;
    * when the strict-increase floors push the value past that wall clock, wait
      (briefly, and bounded) for real time to reach it rather than emitting a
      timestamp the Event Store has not reached yet.

    The result is a clock whose every emitted timestamp has already been
    observed on the Event Store's own wall clock, so the readers keep their
    zero negative tolerance instead of trading it for a skew window.
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

    @staticmethod
    def _await_wall_clock(current: datetime) -> None:
        """Block until the Event-Store wall clock reaches ``current``.

        Bounded by :data:`_MAX_WALL_CLOCK_CATCHUP_SECONDS`.  Reaching that bound
        means the wall clock stepped backwards or a persisted ``minimum`` came
        from a host running ahead -- a real anomaly rather than a resolution
        artifact -- so the value is emitted and the zero-tolerance readers are
        left free to refuse it.
        """
        deadline_ns = time.monotonic_ns() + int(
            _MAX_WALL_CLOCK_CATCHUP_SECONDS * 1_000_000_000
        )
        while _wall_clock_now() < current:
            if time.monotonic_ns() >= deadline_ns:
                return
            time.sleep(0)

    def now(self, *, minimum: str | None = None) -> str:
        with self._lock:
            elapsed_ns = max(0, time.monotonic_ns() - self._monotonic_anchor_ns)
            current = self._wall_anchor + timedelta(microseconds=elapsed_ns // 1000)
            wall_now = _wall_clock_now()
            if wall_now < current:
                current = wall_now
            if minimum is not None:
                minimum_value = self._parse(minimum)
                if current <= minimum_value:
                    current = minimum_value + timedelta(microseconds=1)
            if current <= self._last:
                current = self._last + timedelta(microseconds=1)
            self._await_wall_clock(current)
            self._last = current
            return current.isoformat()


__all__ = ["AttemptLifecycleClock"]
