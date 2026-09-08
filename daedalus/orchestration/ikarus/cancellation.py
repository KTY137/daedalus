"""Per-stream cancellation signal and measured termination of an exact owned child.

The durable ConversationRequestManager owns request identity and cancellation
receipts. This module has no registry, scheduler, event store or effect authority.
"""
from __future__ import annotations

import math
import subprocess
import threading
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SubprocessStopReceipt:
    """Positive, local evidence for stopping one exact owned child process.

    ``process_exited`` is only true after ``poll``/``wait`` observed the child
    terminal.  The receipt intentionally does not infer anything about a remote
    service the child may have contacted before it exited.
    """

    request_id: str
    cancellation_requested: bool
    was_running: bool
    terminate_sent: bool
    kill_sent: bool
    process_exited: bool
    returncode: int | None

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "cancellation_requested": self.cancellation_requested,
            "was_running": self.was_running,
            "terminate_sent": self.terminate_sent,
            "kill_sent": self.kill_sent,
            "process_exited": self.process_exited,
            "returncode": self.returncode,
        }


class CancellationSignal:
    """Thread-safe stop signal passed directly to provider cancellation probes."""

    __slots__ = (
        "request_id",
        "_event",
        "_lock",
        "_subprocess_stop_receipt",
    )

    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._subprocess_stop_receipt: SubprocessStopReceipt | None = None

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


    def subprocess_stop_receipt(self) -> SubprocessStopReceipt | None:
        """Return local child-stop evidence observed for this exact request.

        The receipt is immutable.  Reading it under the signal lock gives the
        cancellation endpoint a coherent snapshot without introducing another
        registry or process table.
        """
        with self._lock:
            return self._subprocess_stop_receipt

    def _record_subprocess_stop_receipt(self, receipt: SubprocessStopReceipt) -> None:
        """Attach evidence emitted by ``terminate_owned_subprocess`` only.

        If a later observation proves terminal state, it may strengthen an
        earlier non-terminal receipt.  A weaker observation never overwrites
        positive ``process_exited`` evidence.
        """
        if type(receipt) is not SubprocessStopReceipt:
            raise TypeError("receipt must be an exact SubprocessStopReceipt")
        if receipt.request_id != self.request_id:
            raise ValueError("subprocess receipt request_id does not match signal")
        with self._lock:
            current = self._subprocess_stop_receipt
            if current is None or (not current.process_exited and receipt.process_exited):
                self._subprocess_stop_receipt = receipt


def terminate_owned_subprocess(
    signal: CancellationSignal,
    process: subprocess.Popen[Any],
    *,
    grace_s: float = 1.0,
) -> SubprocessStopReceipt:
    """Stop one exact child after cancellation and prove what actually happened.

    The helper is deliberately opt-in: it neither watches a global registry nor
    discovers processes.  A caller that owns both ``signal`` and ``process``
    invokes it after observing cancellation.  ``terminate`` gets one bounded
    grace window; if the child is still live, ``kill`` gets the same bounded
    observation window.  Expiry stays ``process_exited=False`` rather than being
    rounded up to success.

    Exact types are required at this trust boundary.  A duck-typed process can
    run arbitrary code from ``poll``/``terminate``/``wait`` before the caller has
    proved it is the child handle it created.
    """
    if type(signal) is not CancellationSignal:
        raise TypeError("signal must be an exact CancellationSignal")
    if type(process) is not subprocess.Popen:
        raise TypeError("process must be an exact subprocess.Popen")
    grace = float(grace_s)
    if not math.isfinite(grace) or grace < 0:
        raise ValueError("grace_s must be >= 0 and finite")

    def finish(receipt: SubprocessStopReceipt) -> SubprocessStopReceipt:
        # Only cancellation evidence belongs on a stop receipt.  A caller may
        # probe this helper before cancellation to prove it is a no-op; that
        # observation must never later masquerade as evidence for a stop.
        if receipt.cancellation_requested:
            signal._record_subprocess_stop_receipt(receipt)
        return receipt

    requested = signal.cancelled()
    running = process.poll() is None
    if not requested or not running:
        code = process.poll()
        return finish(SubprocessStopReceipt(
            request_id=signal.request_id,
            cancellation_requested=requested,
            was_running=running,
            terminate_sent=False,
            kill_sent=False,
            process_exited=code is not None,
            returncode=code,
        ))

    terminate_sent = False
    kill_sent = False
    try:
        process.terminate()
        terminate_sent = True
    except ProcessLookupError:
        # The child won the race and exited between poll() and terminate().
        pass

    try:
        returncode = process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        # Re-check before escalating: a child that became terminal at the
        # boundary must not receive an unnecessary kill.
        returncode = process.poll()
        if returncode is None:
            try:
                process.kill()
                kill_sent = True
            except ProcessLookupError:
                pass
            try:
                returncode = process.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                returncode = process.poll()

    return finish(SubprocessStopReceipt(
        request_id=signal.request_id,
        cancellation_requested=True,
        was_running=True,
        terminate_sent=terminate_sent,
        kill_sent=kill_sent,
        process_exited=returncode is not None,
        returncode=returncode,
    ))
