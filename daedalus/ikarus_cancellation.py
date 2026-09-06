"""Transient cancellation ownership for one live Ikarus request.

This module owns exactly one small question: has a named, currently-active
Ikarus request been asked to stop?  It is intentionally *not* a policy engine,
ledger, execution layer, or durable store.  The HTTP surface, Ikarus router and
provider transports can all share the same signal without inventing separate
booleans or interpreting a dropped browser connection as proof of cancellation.

The registry is process-local because the work it controls is process-local.
Entries exist only while a request is active and must be released by the owner
in ``finally``.  Cancellation is idempotent and release is identity-safe: an
old request owner cannot accidentally delete a newer signal that reused the
same request id.

A stop request and a stopped request are deliberately different facts.  The
signal therefore also carries a terminal event which only the registry owner
sets while releasing the exact live signal.  ``cancel_and_wait`` can use that
event to produce bounded positive evidence that the request owner has actually
left its live scope; a timeout remains an explicit unproven outcome rather than
being rounded up to "stopped".
"""
from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass


# Browser-generated UUIDs fit this alphabet, but the contract deliberately does
# not require UUID semantics.  Treat the value as an opaque correlation id and
# bound it before it becomes a dictionary key or crosses logs/receipts.
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")


class CancellationRegistrationError(ValueError):
    """A cancellation id is malformed or already owned by a live request."""


@dataclass(frozen=True)
class CancelReceipt:
    """What one cancellation request actually changed."""

    request_id: str
    active: bool
    newly_cancelled: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "active": self.active,
            "newly_cancelled": self.newly_cancelled,
        }


@dataclass(frozen=True)
class StopReceipt:
    """Bounded evidence from requesting stop and observing the exact owner.

    ``request_finished`` means the exact signal that was active when cancellation
    was requested has subsequently been released by its owner.  It does *not*
    claim that a remote vendor stopped billing or that an OS process was killed;
    those stronger claims need provider/subprocess evidence at their own layer.
    """

    request_id: str
    active: bool
    newly_cancelled: bool
    request_finished: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "active": self.active,
            "newly_cancelled": self.newly_cancelled,
            "request_finished": self.request_finished,
        }


class CancellationSignal:
    """Thread-safe stop signal passed directly to provider cancellation probes."""

    __slots__ = ("request_id", "_event", "_finished", "_lock")

    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        self._event = threading.Event()
        self._finished = threading.Event()
        self._lock = threading.Lock()

    def cancelled(self) -> bool:
        """Return whether cancellation has been requested."""
        return self._event.is_set()

    def cancel(self) -> bool:
        """Request cancellation and return True only for the first transition."""
        # Event.set() is thread-safe, but is_set()+set is not one atomic
        # transition. The receipt's newly_cancelled bit is evidence, so exactly
        # one racing caller is allowed to observe that transition as new.
        with self._lock:
            if self._event.is_set():
                return False
            self._event.set()
            return True

    def finished(self) -> bool:
        """Whether the exact live owner has released this signal."""
        return self._finished.is_set()

    def wait_finished(self, timeout_s: float = 0.0) -> bool:
        """Wait at most ``timeout_s`` for owner release; never invent a deadline.

        The timeout belongs to the observer, not to the work.  Expiry only means
        terminal state was not proven inside that observation window; it does not
        cancel, kill, or otherwise alter the request.
        """
        timeout = float(timeout_s)
        if timeout < 0:
            raise ValueError("timeout_s must be >= 0")
        return self._finished.wait(timeout)

    def _mark_finished(self) -> None:
        """Registry-only terminal mark for the exact live owner."""
        self._finished.set()


class CancellationRegistry:
    """Identity-safe owner map for live Ikarus cancellation signals."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._signals: dict[str, CancellationSignal] = {}

    @staticmethod
    def validate_request_id(request_id: str) -> str:
        value = str(request_id or "")
        if not _REQUEST_ID_RE.fullmatch(value):
            raise CancellationRegistrationError(
                "request_id must be 8-128 characters of A-Z, a-z, 0-9, '.', '_', ':', or '-'"
            )
        return value

    def open(self, request_id: str) -> CancellationSignal:
        """Claim one id for one active request; duplicate live ownership refuses."""
        value = self.validate_request_id(request_id)
        with self._lock:
            if value in self._signals:
                raise CancellationRegistrationError(
                    f"request_id {value!r} already belongs to an active Ikarus request"
                )
            signal = CancellationSignal(value)
            self._signals[value] = signal
            return signal

    @contextmanager
    def claim(self, request_id: str) -> Iterator[CancellationSignal]:
        """Own one live signal and prove terminal release on every exit path.

        HTTP/runtime callers should prefer this over a hand-written open/finally
        pair.  It keeps the lifecycle rule executable: an exception, disconnect,
        or normal final cannot strand an id in the process-local registry.
        """
        signal = self.open(request_id)
        try:
            yield signal
        finally:
            self.release(signal)

    def cancel(self, request_id: str) -> CancelReceipt:
        """Request stop without guessing whether an unknown id ever existed."""
        value = self.validate_request_id(request_id)
        with self._lock:
            signal = self._signals.get(value)
            if signal is None:
                return CancelReceipt(value, active=False, newly_cancelled=False)
            return CancelReceipt(
                value,
                active=True,
                newly_cancelled=signal.cancel(),
            )

    def cancel_and_wait(self, request_id: str, *, timeout_s: float = 0.0) -> StopReceipt:
        """Request stop, then observe the *same* owner for bounded completion.

        The exact signal is captured while holding the registry lock, then the
        wait happens without that lock so the owner is free to release it.  This
        matters when a request id is later reused: terminal evidence can only be
        attributed to the signal that was live when this call requested stop,
        never to a newer owner with the same opaque id.
        """
        timeout = float(timeout_s)
        if timeout < 0:
            raise ValueError("timeout_s must be >= 0")
        value = self.validate_request_id(request_id)
        with self._lock:
            signal = self._signals.get(value)
            if signal is None:
                return StopReceipt(
                    value,
                    active=False,
                    newly_cancelled=False,
                    request_finished=False,
                )
            newly_cancelled = signal.cancel()
        return StopReceipt(
            value,
            active=True,
            newly_cancelled=newly_cancelled,
            request_finished=signal.wait_finished(timeout),
        )

    def release(self, signal: CancellationSignal) -> bool:
        """Release only if *signal* is still the exact owner of its id."""
        if type(signal) is not CancellationSignal:
            raise TypeError("signal must be an exact CancellationSignal")
        with self._lock:
            if self._signals.get(signal.request_id) is not signal:
                return False
            # Mark terminal before deleting the address. A cancel_and_wait caller
            # may already hold this exact signal after releasing the registry
            # lock; setting the event before removal gives it positive evidence
            # without retaining tombstones or confusing a later id reuse.
            signal._mark_finished()
            del self._signals[signal.request_id]
            return True

    def active_count(self) -> int:
        with self._lock:
            return len(self._signals)


_DEFAULT_REGISTRY = CancellationRegistry()


def default_registry() -> CancellationRegistry:
    """The one process-local registry shared by HTTP and live Ikarus requests."""
    return _DEFAULT_REGISTRY
