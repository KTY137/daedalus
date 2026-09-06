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
"""
from __future__ import annotations

import re
import threading
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


class CancellationSignal:
    """Thread-safe stop signal passed directly to provider cancellation probes."""

    __slots__ = ("request_id", "_event", "_lock")

    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        self._event = threading.Event()
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

    def release(self, signal: CancellationSignal) -> bool:
        """Release only if *signal* is still the exact owner of its id."""
        if type(signal) is not CancellationSignal:
            raise TypeError("signal must be an exact CancellationSignal")
        with self._lock:
            if self._signals.get(signal.request_id) is not signal:
                return False
            del self._signals[signal.request_id]
            return True

    def active_count(self) -> int:
        with self._lock:
            return len(self._signals)


_DEFAULT_REGISTRY = CancellationRegistry()


def default_registry() -> CancellationRegistry:
    """The one process-local registry shared by HTTP and live Ikarus requests."""
    return _DEFAULT_REGISTRY
