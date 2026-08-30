# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import inspect
import time
from datetime import datetime, timedelta, timezone

from daedalus.kernel.attempt_clock import AttemptLifecycleClock
from daedalus.kernel.attempt_contracts import (
    AttemptStartRecord,
    AttemptTerminalReceipt,
)
from daedalus.kernel.attempt_ledger import AttemptLedger


def test_clock_has_monotonic_and_persisted_minimum_floors() -> None:
    source = inspect.getsource(AttemptLifecycleClock.now)
    assert "time.monotonic_ns" in source
    assert "if current <= minimum_value" in source
    assert "if current <= self._last" in source
    assert "self._last + timedelta(microseconds=1)" in source
    # The wall-clock clamp must stay, and must stay ahead of both floors so it
    # can never undo the anti-rollback guarantees they provide.
    assert "if wall_now < current" in source
    assert source.index("if wall_now < current") < source.index(
        "if current <= minimum_value"
    )


_ONE_HOUR_NS = 3_600_000_000_000


def test_observation_never_runs_ahead_of_the_event_store_wall_clock(
    monkeypatch,
) -> None:
    """A lifecycle time may never follow the Event-Store row that records it.

    The Event Store stamps ``created_ts``/``ts`` from ``datetime.now``.  When
    the monotonic projection outran that clock, ``AttemptLedger.begin`` failed
    closed on its own trusted start time.
    """
    clock = AttemptLifecycleClock()
    ahead = time.monotonic_ns() + _ONE_HOUR_NS
    monkeypatch.setattr(time, "monotonic_ns", lambda: ahead)

    before = datetime.now(timezone.utc)
    observed = datetime.fromisoformat(clock.now())
    after = datetime.now(timezone.utc)

    assert observed <= after, "observation followed the Event-Store wall clock"
    assert observed >= before


def test_clamped_observations_are_still_strictly_nondecreasing(monkeypatch) -> None:
    clock = AttemptLifecycleClock()
    frozen = time.monotonic_ns() + _ONE_HOUR_NS
    monkeypatch.setattr(time, "monotonic_ns", lambda: frozen)

    stamps = [clock.now() for _ in range(50)]

    assert stamps == sorted(stamps)
    assert len(set(stamps)) == 50


def test_persisted_minimum_still_outranks_the_wall_clock_clamp() -> None:
    """Clamping must not reopen the backwards-wall-clock hole it sits next to."""
    clock = AttemptLifecycleClock()
    future = datetime.now(timezone.utc) + timedelta(hours=1)

    observed = datetime.fromisoformat(clock.now(minimum=future.isoformat()))

    assert observed > future


def test_contract_provenance_time_is_exactly_the_trusted_lifecycle_time() -> None:
    start = inspect.getsource(AttemptStartRecord.__post_init__)
    terminal = inspect.getsource(AttemptTerminalReceipt.__post_init__)
    assert "self.provenance.created_at != started_at" in start
    assert "start provenance time must equal trusted start time" in start
    assert "self.provenance.created_at != completed_at" in terminal
    assert "terminal provenance time must equal trusted completion time" in terminal


def test_event_store_times_bound_the_embedded_trusted_times() -> None:
    start = inspect.getsource(AttemptLedger._decode_start_intent)
    terminal = inspect.getsource(AttemptLedger._decode_terminal_result)
    assert "intent.created_ts" in start
    assert "follows its Event-Store start event" in start
    assert "intent.resolved_ts" in terminal
    assert "follows its Event-Store terminal event" in terminal


def test_legacy_time_arguments_are_explicitly_discarded() -> None:
    begin = inspect.getsource(AttemptLedger.begin)
    complete = inspect.getsource(AttemptLedger.complete)
    assert "del started_at" in begin
    assert "del completed_at" in complete
    assert "trusted_started_at = self._clock.now()" in begin
    assert "self._clock.now(minimum=start.started_at)" in complete
