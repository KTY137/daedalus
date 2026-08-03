from __future__ import annotations

import inspect

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
