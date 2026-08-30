from __future__ import annotations

import importlib.util
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from daedalus.kernel.effects import EffectExecutionRequest
from daedalus.runtimes.broker import (
    RuntimeProviderBindingMismatch,
)
from runtime_provider_test_double import (
    run_runtime_provider_test_double as run_runtime_provider,
)
from daedalus.runtimes.provider_observation import (
    ProviderObservationAuthority,
    ProviderObservationBindingLedger,
    issue_provider_observation_authority,
)


ROOT = Path(__file__).resolve().parents[2]
AUTHORITY_FIXTURE = ROOT / "tests/kernel/test_runtime_effect_replay_projection.py"
AUTHORITY_KEY_ID = "broker-boundary-authority-key"
AUTHORITY_KEY = b"broker-boundary-authority-key-material-at-least-32-bytes"
OBSERVATION_KEY_ID = "broker-boundary-observation-key"
OBSERVATION_KEY = b"broker-boundary-observation-key-material-at-least-32-bytes"
RECORD_KEY = b"broker-boundary-record-key-material-at-least-32-bytes"
OUTPUT_SHA = "d" * 64


def _load_fixture():
    name = "daedalus_test_runtime_provider_exact_boundary_fixture"
    spec = importlib.util.spec_from_file_location(name, AUTHORITY_FIXTURE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fixture = _load_fixture()


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


def _ledger(tmp_path: Path, name: str = "binding.sqlite3"):
    return ProviderObservationBindingLedger(
        tmp_path / name,
        authority_id="authority.runtime-provider-observation",
        authority_keyring={AUTHORITY_KEY_ID: AUTHORITY_KEY},
        observation_keyring={OBSERVATION_KEY_ID: OBSERVATION_KEY},
        record_secret=RECORD_KEY,
    )


def _subject(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    authorization, _record = fixture._authorization(tmp_path, monkeypatch)
    execution = fixture._execution()
    ledger = _ledger(tmp_path)
    authority = issue_provider_observation_authority(
        authority_id="authority.runtime-provider-observation",
        authority_key_id=AUTHORITY_KEY_ID,
        authority_secret=AUTHORITY_KEY,
        binding_id="broker-boundary-binding",
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
    _set_clocks(monkeypatch)
    return authorization, execution, authority, ledger


def _run(authorization, execution, authority, ledger, *, invoke):
    return run_runtime_provider(
        fixture._request().entrypoint_id,
        authorization=authorization,
        execution=execution,
        invoke=invoke,
        output_digests=lambda value: (OUTPUT_SHA,),
        observation_authority=authority,
        observation_binding_ledger=ledger,
    )


def test_missing_authority_or_ledger_refuses_before_grant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization, execution, authority, ledger = _subject(tmp_path, monkeypatch)
    called: list[str] = []
    with pytest.raises(RuntimeProviderBindingMismatch, match="ProviderObservationAuthority"):
        _run(
            authorization,
            execution,
            None,
            ledger,
            invoke=lambda: called.append("provider"),
        )
    with pytest.raises(RuntimeProviderBindingMismatch, match="ProviderObservationBindingLedger"):
        _run(
            authorization,
            execution,
            authority,
            None,
            invoke=lambda: called.append("provider"),
        )
    assert called == []
    assert authorization.effect_ledger.execution_state(execution.execution_id) is None


def test_exact_replay_refuses_a_fresh_substituted_binding_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization, execution, authority, ledger = _subject(tmp_path, monkeypatch)
    calls: list[str] = []
    first = _run(
        authorization,
        execution,
        authority,
        ledger,
        invoke=lambda: calls.append("provider") or "output",
    )
    assert first.executed is True
    substituted = _ledger(tmp_path, "substituted-binding.sqlite3")
    with pytest.raises(RuntimeProviderBindingMismatch, match="could not authenticate and bind"):
        _run(
            authorization,
            execution,
            authority,
            substituted,
            invoke=lambda: calls.append("duplicate") or "duplicate",
        )
    assert calls == ["provider"]
    assert substituted.load(execution.execution_id) is None


class _ExecutionSubclass(EffectExecutionRequest):
    pass


class _AuthoritySubclass(ProviderObservationAuthority):
    pass


class _LedgerSubclass(ProviderObservationBindingLedger):
    pass


def test_subclassed_execution_authority_and_ledger_are_not_exact_subjects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization, execution, authority, ledger = _subject(tmp_path, monkeypatch)
    execution_subclass = _ExecutionSubclass(**execution.to_dict())
    authority_subclass = _AuthoritySubclass(**authority.to_dict())
    ledger_subclass = _LedgerSubclass(
        tmp_path / "subclass-binding.sqlite3",
        authority_id="authority.runtime-provider-observation",
        authority_keyring={AUTHORITY_KEY_ID: AUTHORITY_KEY},
        observation_keyring={OBSERVATION_KEY_ID: OBSERVATION_KEY},
        record_secret=RECORD_KEY,
    )
    with pytest.raises(RuntimeProviderBindingMismatch, match="exact EffectExecutionRequest"):
        _run(
            authorization,
            execution_subclass,
            authority,
            ledger,
            invoke=lambda: "forbidden",
        )
    with pytest.raises(RuntimeProviderBindingMismatch, match="ProviderObservationAuthority"):
        _run(
            authorization,
            execution,
            authority_subclass,
            ledger,
            invoke=lambda: "forbidden",
        )
    with pytest.raises(RuntimeProviderBindingMismatch, match="ProviderObservationBindingLedger"):
        _run(
            authorization,
            execution,
            authority,
            ledger_subclass,
            invoke=lambda: "forbidden",
        )
    assert authorization.effect_ledger.execution_state(execution.execution_id) is None
