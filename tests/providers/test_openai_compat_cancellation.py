"""G1-KERNEL-02 -- an in-flight provider call must be interruptible.

Measured 2026-09-05 (docs/work-packets/G1-IKARUS-26_COMPUTER_LOOP_LIVE.md):
under the owner's ``unbounded_execution`` policy the computer loop passes
``timeout_s=None`` down to ``_openai_compat._post``, which passes it straight
to ``urlopen``. That is the correct answer to "how long may this run" -- a
disabled cap is never a magic number -- but it left the kill switch with
nothing to interrupt, so a stop was only noticed at the next checkpoint
BETWEEN calls.

Every test here runs against a local ``http.server`` on 127.0.0.1 that answers
slowly or not at all. None of them assert a duration as a performance number:
the discriminating claim is always "seconds, not the server's delay", and the
margins are wide because the box is shared.

The control test is :func:`test_the_same_call_without_a_probe_is_not_interruptible`.
Without it the rest would pass against a transport that was never blocked in
the first place -- which is exactly how the pre-existing cancellation test in
tests/test_ikarus_computer_loop.py passes today.
"""

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from daedalus.providers._openai_compat import (
    DEFAULT_CANCEL_POLL_S,
    ProviderCancelled,
    ProviderHTTPError,
    chat_completion,
    chat_raw,
)

REPLY = {"choices": [{"message": {"content": "the answer", "role": "assistant"}}]}

# Long enough that "the server answered" and "the probe fired" can never be
# confused, short enough that a hung test dies with the session. Every test
# releases the server in teardown, so no test actually waits this long.
FOREVER_S = 60.0

# Loose on purpose. Under the ten-agent load this box carries, a tight bound
# would measure the scheduler, not the mechanism.
PROMPT_S = 5.0


@contextmanager
def slow_server(*, delay_s: float, mode: str = "before_headers", status: int = 200,
                body: bytes | None = None):
    """A loopback endpoint that stalls.

    ``before_headers`` is the measured production shape: a non-streaming
    completion sends nothing at all -- not even a status line -- until
    generation has finished, so the caller is parked inside ``urlopen``.
    ``headers_then_silence`` is the other half: headers arrive, then the body
    stalls, so the caller is parked inside ``resp.read()``.
    """
    payload = json.dumps(REPLY).encode("utf-8") if body is None else body
    state: dict[str, object] = {
        "requests": 0, "payloads": [], "release": threading.Event(),
    }

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self) -> None:  # noqa: N802 - stdlib naming
            state["requests"] = int(state["requests"]) + 1        # type: ignore[arg-type]
            length = int(self.headers.get("Content-Length") or 0)
            state["payloads"].append(self.rfile.read(length))      # type: ignore[union-attr]
            try:
                if mode == "headers_then_silence":
                    self._head(len(payload))
                    self.wfile.flush()
                    state["release"].wait(delay_s)                 # type: ignore[union-attr]
                    self.wfile.write(payload)
                else:
                    state["release"].wait(delay_s)                 # type: ignore[union-attr]
                    self._head(len(payload))
                    self.wfile.write(payload)
            except OSError:
                pass  # an abandoned client is the point of several tests

        def _head(self, length: int) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(length))
            self.end_headers()

        def log_message(self, *args: object) -> None:
            pass

    class Server(ThreadingHTTPServer):
        daemon_threads = True

        def handle_error(self, *args: object) -> None:
            pass  # a client that walked away is not a test failure

    server = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    state["base_url"] = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield state
    finally:
        state["release"].set()                                     # type: ignore[union-attr]
        server.shutdown()
        server.server_close()


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer proxy in the environment would make 127.0.0.1 unreachable and
    turn every test below green for the wrong reason."""
    for name in ("no_proxy", "NO_PROXY"):
        monkeypatch.setenv(name, "*")
    for name in ("http_proxy", "HTTP_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(name, raising=False)


def _never() -> bool:
    return False


class _FlipAfter:
    """A probe that becomes True once, at a known moment."""

    def __init__(self, after_s: float) -> None:
        self.after_s = after_s
        self.started = time.monotonic()
        self.flipped_at: float | None = None

    def __call__(self) -> bool:
        if time.monotonic() - self.started < self.after_s:
            return False
        if self.flipped_at is None:
            self.flipped_at = time.monotonic()
        return True


# ---------------------------------------------------------------------------
# (d) an answered call is unchanged
# ---------------------------------------------------------------------------

def test_a_completed_reply_is_identical_with_and_without_a_probe():
    with slow_server(delay_s=0.05) as state:
        blocking = chat_completion(
            base_url=str(state["base_url"]), model="m", system="s", user="u",
            timeout_s=None, force_json=False)
        probed = chat_completion(
            base_url=str(state["base_url"]), model="m", system="s", user="u",
            timeout_s=None, force_json=False, cancelled=_never)
    assert blocking == "the answer"
    assert probed == blocking


def test_chat_raw_also_carries_the_probe_without_changing_its_result():
    with slow_server(delay_s=0.05) as state:
        blocking = chat_raw(
            base_url=str(state["base_url"]), model="m",
            messages=[{"role": "user", "content": "u"}], timeout_s=None)
        probed = chat_raw(
            base_url=str(state["base_url"]), model="m",
            messages=[{"role": "user", "content": "u"}], timeout_s=None,
            cancelled=_never)
    assert blocking == REPLY["choices"][0]["message"]
    assert probed == blocking


def test_the_request_body_is_unchanged_by_the_probe():
    with slow_server(delay_s=0.05) as state:
        for probe in (None, _never):
            chat_completion(
                base_url=str(state["base_url"]), model="m", system="s", user="u",
                timeout_s=None, force_json=False, cancelled=probe)
        sent = [json.loads(p.decode("utf-8")) for p in state["payloads"]]  # type: ignore[union-attr]
    assert sent[0] == sent[1]


# ---------------------------------------------------------------------------
# (a) + the control: without a probe the call still waits, indefinitely
# ---------------------------------------------------------------------------

def test_the_poll_interval_is_not_a_deadline():
    """A probe that never fires must not shorten anything. The server takes ~1.5 s
    -- about thirty poll intervals -- and the call still returns its reply."""
    with slow_server(delay_s=1.5) as state:
        started = time.monotonic()
        got = chat_completion(
            base_url=str(state["base_url"]), model="m", system="s", user="u",
            timeout_s=None, force_json=False, cancelled=_never, poll_interval_s=0.05)
        waited = time.monotonic() - started
    assert got == "the answer"
    assert waited >= 1.4, f"the call did not actually wait ({waited:.2f}s)"


def test_the_same_call_without_a_probe_is_not_interruptible():
    """The thermometer for every cancellation test below.

    Same server, same ``timeout_s=None``, no probe: the call is still parked
    after seconds. If this ever passes trivially -- because the server answers,
    or because something else ends the call -- then the cancellation tests
    prove nothing either.
    """
    with slow_server(delay_s=FOREVER_S) as state:
        done = threading.Event()

        def _call() -> None:
            try:
                chat_completion(
                    base_url=str(state["base_url"]), model="m", system="s",
                    user="u", timeout_s=None, force_json=False)
            except Exception:  # noqa: BLE001 - only "did it return" matters
                pass
            finally:
                done.set()

        threading.Thread(target=_call, daemon=True).start()
        assert not done.wait(3.0), "the un-probed call ended on its own"


# ---------------------------------------------------------------------------
# (b) the probe ends an in-flight call
# ---------------------------------------------------------------------------

def test_an_in_flight_call_ends_when_the_probe_flips():
    with slow_server(delay_s=FOREVER_S) as state:
        # Built AFTER the server is up: a probe whose clock started before a
        # slow fixture would already be True at the pre-flight check, and the
        # test would pass without ever reaching an in-flight call. The message
        # assertion below pins which of the two refusals actually fired.
        probe = _FlipAfter(1.0)
        started = time.monotonic()
        with pytest.raises(ProviderCancelled) as caught:
            chat_completion(
                base_url=str(state["base_url"]), model="m", system="s", user="u",
                timeout_s=None, force_json=False, cancelled=probe,
                poll_interval_s=0.05)
        raised_at = time.monotonic()
    assert probe.flipped_at is not None
    assert "in flight" in str(caught.value)
    # The claim is "seconds after the flip", not "the server's delay".
    assert raised_at - probe.flipped_at <= PROMPT_S
    assert raised_at - started < FOREVER_S / 2


def test_a_call_parked_on_the_body_is_cancellable_too():
    """Headers arrive, then the peer goes quiet -- the other half of the hang."""
    with slow_server(delay_s=FOREVER_S, mode="headers_then_silence") as state:
        probe = _FlipAfter(0.5)
        started = time.monotonic()
        with pytest.raises(ProviderCancelled) as caught:
            chat_completion(
                base_url=str(state["base_url"]), model="m", system="s", user="u",
                timeout_s=None, force_json=False, cancelled=probe,
                poll_interval_s=0.05)
        raised_at = time.monotonic()
    assert probe.flipped_at is not None
    assert "in flight" in str(caught.value)
    assert raised_at - probe.flipped_at <= PROMPT_S
    assert raised_at - started < FOREVER_S / 2


def test_a_call_already_cancelled_never_opens_a_connection():
    """A cancelled mission must not pay for one more worst-case reservation."""
    with slow_server(delay_s=0.05) as state:
        with pytest.raises(ProviderCancelled) as caught:
            chat_completion(
                base_url=str(state["base_url"]), model="m", system="s", user="u",
                timeout_s=None, force_json=False, cancelled=lambda: True)
        assert state["requests"] == 0
    assert "opened a connection" in str(caught.value)


def test_a_cancellation_is_not_a_provider_http_error():
    """A caller catching ProviderHTTPError means "the vendor failed". The kill
    switch working is not that, and must not be reported as it."""
    with slow_server(delay_s=FOREVER_S) as state:
        probe = _FlipAfter(0.3)
        with pytest.raises(ProviderCancelled) as caught:
            chat_completion(
                base_url=str(state["base_url"]), model="m", system="s", user="u",
                timeout_s=None, force_json=False, cancelled=probe,
                poll_interval_s=0.05)
    assert "in flight" in str(caught.value)
    assert not isinstance(caught.value, ProviderHTTPError)


def test_a_non_positive_poll_interval_is_refused():
    """Zero would busy-spin the probe; negative is meaningless. Neither is a way
    to express "no cap" -- that is what a False probe already means."""
    with slow_server(delay_s=0.05) as state:
        for bad in (0, -1.0):
            with pytest.raises(ValueError):
                chat_completion(
                    base_url=str(state["base_url"]), model="m", system="s",
                    user="u", timeout_s=None, force_json=False,
                    cancelled=_never, poll_interval_s=bad)


def test_the_default_poll_interval_is_a_small_positive_number():
    assert 0 < DEFAULT_CANCEL_POLL_S <= 1.0


# ---------------------------------------------------------------------------
# (c) existing failure semantics are untouched
# ---------------------------------------------------------------------------

def _failure(base_url: str, *, timeout_s, cancelled):
    try:
        chat_completion(base_url=base_url, model="m", system="s", user="u",
                        timeout_s=timeout_s, force_json=False, cancelled=cancelled)
    except BaseException as exc:  # noqa: BLE001 - the class IS the assertion
        return type(exc), str(exc)
    return None, None


def test_a_timeout_behaves_the_same_with_and_without_a_probe():
    """``timeout_s`` keeps meaning exactly what it meant. The probe neither
    shortens it nor rescues the call from it."""
    with slow_server(delay_s=FOREVER_S) as state:
        blocking = _failure(str(state["base_url"]), timeout_s=0.5, cancelled=None)
        probed = _failure(str(state["base_url"]), timeout_s=0.5, cancelled=_never)
    assert blocking[0] is not None, "the deadline did not fire at all"
    assert probed[0] is blocking[0]
    assert not issubclass(blocking[0], ProviderCancelled)


def test_an_http_error_is_reported_identically_with_and_without_a_probe():
    with slow_server(delay_s=0.0, status=500, body=b"upstream exploded") as state:
        blocking = _failure(str(state["base_url"]), timeout_s=None, cancelled=None)
        probed = _failure(str(state["base_url"]), timeout_s=None, cancelled=_never)
    assert blocking[0] is ProviderHTTPError
    assert probed == blocking


def test_an_unreachable_host_is_reported_identically_with_and_without_a_probe():
    with slow_server(delay_s=0.0) as state:
        dead = str(state["base_url"])
    # the server is closed here: the port is refused, not slow
    blocking = _failure(dead, timeout_s=None, cancelled=None)
    probed = _failure(dead, timeout_s=None, cancelled=_never)
    assert blocking[0] is ProviderHTTPError
    assert probed[0] is blocking[0]


# ---------------------------------------------------------------------------
# the ledger: a cancellable call is reserved exactly as often as a blocking one
# ---------------------------------------------------------------------------

class _FakeReservation:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    def settle(self, *args: object, **kwargs: object) -> None:
        self.log.append("settle")


@contextmanager
def counting_guard():
    """The real budget interposer with a fake ledger behind it."""
    from daedalus.runtimes.execution import budget_process

    reserved: list[str] = []
    settled: list[str] = []

    def _reserve(vendor, *args, **kwargs):
        reserved.append(vendor)
        return _FakeReservation(settled)

    uninstall = budget_process.install_process_guard(
        url_classifier=lambda url: ("remote_inference", str(url)),
        reserve_call=_reserve,
    )
    try:
        yield reserved, settled
    finally:
        uninstall()


def test_a_cancellable_call_is_reserved_exactly_once():
    """The interposer wraps ``urllib.request.urlopen`` as a module global, so a
    worker thread is still guarded -- and must not be guarded twice."""
    with slow_server(delay_s=0.05) as state:
        with counting_guard() as (reserved, settled):
            chat_completion(
                base_url=str(state["base_url"]), model="m", system="s", user="u",
                timeout_s=None, force_json=False)
            after_blocking = list(reserved)
            chat_completion(
                base_url=str(state["base_url"]), model="m", system="s", user="u",
                timeout_s=None, force_json=False, cancelled=_never)
            after_probed = list(reserved)
    assert len(after_blocking) == 1, after_blocking
    assert len(after_probed) == 2, after_probed
    assert settled == ["settle", "settle"]


def test_a_call_inside_an_explicit_reservation_is_not_reserved_twice():
    """``budget_process`` suppresses the interposer with a ``threading.local()``
    depth, so a naive worker thread would look unreserved and book the same
    call a second time. The worker inherits the mark instead."""
    from daedalus.budget import _enter_explicit, _exit_explicit

    with slow_server(delay_s=0.05) as state:
        with counting_guard() as (reserved, _settled):
            _enter_explicit()
            try:
                chat_completion(
                    base_url=str(state["base_url"]), model="m", system="s",
                    user="u", timeout_s=None, force_json=False, cancelled=_never)
            finally:
                _exit_explicit()
    assert reserved == [], f"the same call was reserved again: {reserved}"
