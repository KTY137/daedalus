# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The health module asks the egress policy before it opens a socket.

``daedalus/health.py`` sits under the ikarus door's declared
``network_egress``, and ``hand_state`` reaches whatever ``OLLAMA_HOST`` names.
Until 2026-08-22 it went straight to ``urlopen`` with no endpoint admission at
all: point ``OLLAMA_HOST`` at a tailnet box and the health probe connected to
it, while every other ollama lane in the same process -- ``ikarus_os``'s
``_egress_decision``, ``memory.embeddings`` -- refused that exact host. A
status probe that reaches hosts the write lane refuses is a hole shaped like a
diagnostic.

The claims pinned here:

1. a disallowed host is refused BEFORE connect -- zero socket connections, not
   "a connection that was then discarded";
2. the refusal degrades the status; it never raises, because this module is
   read-only status and no probe may become the reason a caller crashes;
3. the refusal is attributable -- host, lane and contract are readable in the
   detail, so an operator can fix it;
4. the decision is DELEGATED, not copied: ``hand_admission`` returns
   ``ollama_endpoint_admission``'s answer unchanged, so health and the write
   lane cannot drift into two opinions about one endpoint;
5. an allowed host still gets probed -- the guard refuses, it does not disable.
"""

from __future__ import annotations

import socket

import pytest

from daedalus import health
from daedalus.providers.ollama import REMOTE_CONSENT_VAR, ollama_endpoint_admission


DISALLOWED = "http://100.119.126.9:11434"
LOOPBACK = "http://127.0.0.1:11434"


@pytest.fixture()
def no_consent(monkeypatch: pytest.MonkeyPatch) -> None:
    """No operator consent for any endpoint, and OLLAMA_HOST unset by default."""
    monkeypatch.delenv(REMOTE_CONSENT_VAR, raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)


@pytest.fixture()
def count_connects(monkeypatch: pytest.MonkeyPatch) -> list:
    """Record every outbound connection attempt this process makes.

    Both ``socket.socket.connect`` and ``socket.create_connection`` are
    counted. urllib reaches the wire through ``create_connection``, but a
    future rewrite of ``_http_json`` onto a raw socket would slip past a probe
    that only watched the higher-level one -- and a leak this test cannot see
    is a test that certifies the leak.
    """
    seen: list = []
    real_connect = socket.socket.connect
    real_create = socket.create_connection

    def spy_connect(self, address, *args, **kwargs):
        seen.append(address)
        return real_connect(self, address, *args, **kwargs)

    def spy_create(address, *args, **kwargs):
        seen.append(address)
        return real_create(address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", spy_connect)
    monkeypatch.setattr(socket, "create_connection", spy_create)
    return seen


def test_a_disallowed_host_is_refused_before_any_connect(
    monkeypatch: pytest.MonkeyPatch, no_consent: None, count_connects: list
) -> None:
    """The load-bearing one: refused means no bytes left, not "we tried".

    MEASURED 2026-08-22 on this trunk: ``OLLAMA_HOST`` at the tailnet bench
    with no ``DAEDALUS_OLLAMA_REMOTE_OK`` -> ``state == 'degraded'`` and the
    connection spy records an empty list.

    GUARD DISABLED, RED CONFIRMED [MEASURED 2026-08-22]: removing the
    ``if not allowed`` branch from ``hand_state`` (so the probe calls
    ``_ollama_alive`` unconditionally, which is exactly what it did before this
    change) turns this red on BOTH assertions -- the state comes back
    ``unknown`` after a real timeout, and the spy records two entries for
    ('100.119.126.9', 11434), one per layer it watches. The connection
    assertion is the one that matters:
    a version of this fix that judged the host AFTER connecting would still
    return 'degraded' and would still be a leak.
    """
    monkeypatch.setenv("OLLAMA_HOST", DISALLOWED)

    state = health.hand_state(timeout_s=1.0)

    assert state.state == health.DEGRADED, (
        f"a refused endpoint reported {state.state!r}; the egress policy denies "
        "this host, so the probe cannot have concluded anything about the "
        "executor")
    assert count_connects == [], (
        f"the refused probe still opened {count_connects}. Admission must run "
        "before _ollama_alive: a check that connects first and judges after has "
        "already leaked the thing it refuses.")


def test_the_refusal_degrades_rather_than_raising(
    monkeypatch: pytest.MonkeyPatch, no_consent: None
) -> None:
    """Read-only status may not crash its caller.

    ``hand_state`` is called from ``_p_hand_executor`` and from anything asking
    "is the Hand there". A raise would make a misconfigured OLLAMA_HOST take
    down the whole health run, including the fifteen probes that have nothing
    to do with ollama -- the operator would lose every OTHER answer at the
    moment they most need them.
    """
    monkeypatch.setenv("OLLAMA_HOST", DISALLOWED)
    state = health.hand_state(timeout_s=1.0)  # must not raise
    assert state.host == DISALLOWED
    assert state.state != health.WORKING


def test_the_refusal_names_the_host_the_lane_and_the_contract(
    monkeypatch: pytest.MonkeyPatch, no_consent: None
) -> None:
    """A refusal nobody can attribute is a refusal nobody can fix.

    The deny detail carries the same four facts the embedding backend's deny
    receipt carries -- contract, host, lane, and that no connection was made --
    so the two refusals read alike to an operator who meets them in either
    order.
    """
    monkeypatch.setenv("OLLAMA_HOST", DISALLOWED)
    detail = health.hand_state(timeout_s=1.0).detail

    assert "provider.egress_policy" in detail, "the contract that refused is unnamed"
    assert DISALLOWED in detail, "the refused host is unreadable in the detail"
    assert "lane=untrusted" in detail, "the lane verdict is missing"
    assert "connected=false" in detail, (
        "the detail does not state that no connection was made -- the one fact "
        "distinguishing a pre-connect refusal from a post-connect one")


def test_health_delegates_the_decision_instead_of_copying_it(
    monkeypatch: pytest.MonkeyPatch, no_consent: None
) -> None:
    """One implementation of "may bytes reach this endpoint", not two.

    This repo's recurring disease is two predicates for one question, each
    drifting until the answers disagree. ``hand_admission`` must return
    ``ollama_endpoint_admission``'s tuple unchanged for every case, including
    the consent case, where a second copy would most plausibly diverge (a
    reimplementation that treated ``DAEDALUS_OLLAMA_REMOTE_OK`` as a boolean
    would admit EVERY remote host -- the exact trap that variable's
    host-not-flag design exists to prevent).
    """
    for host, consent in (
        (LOOPBACK, None),
        (DISALLOWED, None),
        (DISALLOWED, DISALLOWED),
        (DISALLOWED, "http://some-other-host:11434"),
        (DISALLOWED, "1"),
    ):
        if consent is None:
            monkeypatch.delenv(REMOTE_CONSENT_VAR, raising=False)
        else:
            monkeypatch.setenv(REMOTE_CONSENT_VAR, consent)
        monkeypatch.setenv("OLLAMA_HOST", host)

        assert health.hand_admission() == ollama_endpoint_admission(host), (
            f"health took its own view of {host!r} with consent {consent!r}")


def test_an_admitted_host_is_still_probed(
    monkeypatch: pytest.MonkeyPatch, no_consent: None, count_connects: list
) -> None:
    """The guard refuses; it does not quietly disable the probe.

    A "fix" that returned degraded for everything would pass all four tests
    above and would silently blind the health run. Loopback is admitted by
    ``lane_for_host`` with no consent variable at all, so the probe must reach
    ``_ollama_alive`` -- whose verdict (working / absent / unknown) depends on
    whether an ollama happens to be running here, and is deliberately not
    asserted. What IS asserted is that the attempt happened.
    """
    monkeypatch.setenv("OLLAMA_HOST", LOOPBACK)

    state = health.hand_state(timeout_s=1.0)

    assert state.state != health.DEGRADED, (
        "loopback was refused; the admission check is now denying hosts the "
        "policy admits")
    assert count_connects, (
        "an admitted host produced no connection attempt at all -- the probe "
        "was disabled rather than guarded")
