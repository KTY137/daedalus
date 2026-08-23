"""The terminal trust fence must release its SQLite authority read-only.

After the effect completes, the broker re-reads the runtime trust record under
``BEGIN IMMEDIATE`` so quarantine and record rotation are serialized out while
``COMPLETED`` is made durable.  That transaction exists only to hold the lock:
it must end in ``ROLLBACK``.  A ``COMMIT`` there would make fence-local reads
durable and hand a read-only verification path a write it never earned.

The fence connection is observed, not altered: the trust ledger also serves
``require_active``, which legitimately commits its own read transaction, so a
ledger-wide COMMIT refusal would break a correct path instead of measuring this
one.  The fence connection is identified by its caller, and its statements are
asserted positively -- a test that only checked "no COMMIT" would also pass on a
fence that never ran at all.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from daedalus.kernel.runtime_effects import RuntimeBoundEffectAuthorization
from daedalus.runtimes.broker import run_runtime_provider
from daedalus.runtimes.provider_observation import (
    ProviderObservationBindingLedger,
    issue_provider_observation_authority,
)

ROOT = Path(__file__).resolve().parents[2]
AUTHORITY_FIXTURE = ROOT / "tests/kernel/test_runtime_effect_replay_projection.py"
AUTHORITY_KEY_ID = "release-fence-authority-key"
AUTHORITY_KEY = b"release-fence-authority-key-material-at-least-32-bytes"
OBSERVATION_KEY_ID = "release-fence-observation-key"
OBSERVATION_KEY = b"release-fence-observation-key-material-at-least-32-bytes"
RECORD_KEY = b"release-fence-record-key-material-at-least-32-bytes"
OUTPUT_SHA = "a" * 64


def _load_authority_fixture():
    name = "daedalus_test_runtime_terminal_fence_release_fixture"
    spec = importlib.util.spec_from_file_location(name, AUTHORITY_FIXTURE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fixture = _load_authority_fixture()


FENCE_FRAME = "_finish_completed_under_runtime_fence"


class _RecordingConnection:
    """Pure observer over one trust-ledger connection.

    It records statements and forwards everything unchanged, so the path under
    test behaves exactly as it does in production.  ``sqlite3`` connections
    also commit implicitly when used as a context manager, which no ``execute``
    would reveal, so an implicit commit is recorded separately instead of being
    allowed to hide.
    """

    def __init__(self, connection, *, fence: bool) -> None:
        self._connection = connection
        self.fence = fence
        self.statements: list[str] = []
        self.context_committed = False

    def execute(self, statement: str, parameters=()):
        self.statements.append(" ".join(statement.split()).upper())
        return self._connection.execute(statement, parameters)

    def __enter__(self):
        self._connection.__enter__()
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is None and self._connection.in_transaction:
            self.context_committed = True
        return self._connection.__exit__(exc_type, exc, traceback)

    def __getattr__(self, name: str):
        return getattr(self._connection, name)


def _opened_by_terminal_fence() -> bool:
    """Report whether the terminal fence is the caller opening this connection.

    The trust ledger serves several paths and ``require_active`` legitimately
    commits its own read transaction, so the fence connection has to be
    identified by its caller rather than by refusing COMMIT ledger-wide.
    """

    frame = sys._getframe(1)
    while frame is not None:
        if frame.f_code.co_name == FENCE_FRAME:
            return True
        frame = frame.f_back
    return False


def _watch_trust_connections(ledger) -> list[_RecordingConnection]:
    """Wrap every connection the broker opens on the real trust ledger.

    The ledger instance is test-local, so the wrapper is installed directly on
    it rather than on the class; nothing outside this test can observe it.
    """

    opened: list[_RecordingConnection] = []
    original = ledger._connect

    def connect():
        proxy = _RecordingConnection(original(), fence=_opened_by_terminal_fence())
        opened.append(proxy)
        return proxy

    ledger._connect = connect
    return opened


def _set_clocks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "daedalus.kernel.runtime_effects._utc_now",
        lambda: fixture.NOW,
    )
    monkeypatch.setattr(
        "daedalus.kernel.effects._utc_now",
        lambda: fixture.NOW + timedelta(seconds=3),
    )
    monkeypatch.setattr(
        "daedalus.runtimes.broker._utc_now",
        lambda: fixture.NOW + timedelta(seconds=2),
    )


def _authority_bundle(tmp_path: Path, authorization, execution):
    ledger = ProviderObservationBindingLedger(
        tmp_path / "release-fence-provider-observation.sqlite3",
        authority_id="authority.runtime-provider-observation",
        authority_keyring={AUTHORITY_KEY_ID: AUTHORITY_KEY},
        observation_keyring={OBSERVATION_KEY_ID: OBSERVATION_KEY},
        record_secret=RECORD_KEY,
    )
    authority = issue_provider_observation_authority(
        authority_id="authority.runtime-provider-observation",
        authority_key_id=AUTHORITY_KEY_ID,
        authority_secret=AUTHORITY_KEY,
        binding_id="release-fence-exact-provider-binding",
        provider_id="provider.external-runtime-fixture",
        observation_keyring={OBSERVATION_KEY_ID: OBSERVATION_KEY},
        entrypoint_id=fixture._request().entrypoint_id,
        runtime_id=authorization.capability.runtime_id,
        execution=execution,
        lease_sha256=authorization.capability.lease.digest,
        source_revision=authorization.capability.source_revision,
        issued_at=fixture.NOW - timedelta(minutes=1),
        expires_at=fixture.NOW + timedelta(hours=1),
    )
    return authority, ledger


def _trace_terminals(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every terminal outcome without altering terminal behaviour."""

    original = RuntimeBoundEffectAuthorization.finish_effect
    outcomes: list[str] = []

    def traced(self, start_receipt, *, outcome, output_digests=(), detail_sha256=None):
        outcomes.append(outcome)
        return original(
            self,
            start_receipt,
            outcome=outcome,
            output_digests=output_digests,
            detail_sha256=detail_sha256,
        )

    monkeypatch.setattr(RuntimeBoundEffectAuthorization, "finish_effect", traced)
    return outcomes


def test_read_only_trust_fence_does_not_commit_after_effect_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization, _record = fixture._authorization(tmp_path, monkeypatch)
    execution = fixture._execution()
    authority, binding_ledger = _authority_bundle(
        tmp_path,
        authorization,
        execution,
    )
    _set_clocks(monkeypatch)
    terminals = _trace_terminals(monkeypatch)
    opened = _watch_trust_connections(authorization.runtime_trust_ledger)

    result = run_runtime_provider(
        fixture._request().entrypoint_id,
        authorization=authorization,
        execution=execution,
        invoke=lambda: {"answer": 42},
        output_digests=lambda value: (OUTPUT_SHA,),
        observation_authority=authority,
        observation_binding_ledger=binding_ledger,
    )

    assert result.executed is True
    assert result.value == {"answer": 42}
    assert result.terminal_receipt is not None
    assert result.terminal_receipt.outcome == "COMPLETED"
    assert result.terminal_receipt.output_digests == (OUTPUT_SHA,)
    assert terminals == ["completed"]

    # The fence actually opened its serialized transaction, so "no COMMIT"
    # below cannot pass vacuously on a fence that never ran.
    fenced = [connection for connection in opened if connection.fence]
    assert fenced, "the terminal fence never opened a trust-ledger connection"
    assert all("BEGIN IMMEDIATE" in c.statements for c in fenced)

    # Every serialized fence transaction released read-only: an explicit
    # ROLLBACK, no explicit COMMIT, and no implicit context-manager commit.
    for connection in fenced:
        assert "COMMIT" not in connection.statements
        assert "ROLLBACK" in connection.statements
        assert connection.context_committed is False
