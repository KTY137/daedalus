from __future__ import annotations

import hashlib
import importlib.util
import inspect
import sys
from pathlib import Path

import pytest

import daedalus.claude_bridge as claude_bridge
import daedalus.providers.claude_cli as claude_provider
import daedalus.runtimes.broker as lifecycle
from daedalus.providers.claude_cli import ClaudeProviderAuthorizationRequired
from daedalus.runtimes.provider_invocation_abi import (
    issue_provider_invocation_abi_contract,
)
from daedalus.runtimes.provider_invocation_payload import (
    build_provider_invocation_payload,
)
from daedalus.runtimes.sealed_broker import run_sealed_runtime_provider


ROOT = Path(__file__).resolve().parents[2]
BINDING_TEST = ROOT / "tests/runtimes/test_provider_runtime_invocation_binding.py"


def _load_binding_fixture_module():
    name = "daedalus_test_sealed_runtime_binding_fixture"
    spec = importlib.util.spec_from_file_location(name, BINDING_TEST)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


binding = _load_binding_fixture_module()


def _write_sealed_adapter(root: Path):
    module_name = "daedalus.providers.ikarus_runtime_invocation_fixture_adapter"
    source = (
        "def helper():\n"
        "    return 'ok'\n"
        "\n"
        "def invoke(payload):\n"
        "    return {'result': helper(), 'objective': payload['objective']}\n"
        "\n"
        "def output_digests(value, payload):\n"
        "    if payload.get('fail_output'):\n"
        "        raise RuntimeError('fixed evidence failure')\n"
        "    return ('a' * 64,)\n"
    )
    path = root / Path(*module_name.split(".")).with_suffix(".py")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8", newline="\n")
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module, path, hashlib.sha256(path.read_bytes()).hexdigest()


def _bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(binding, "_write_adapter", _write_sealed_adapter)
    return binding._bundle(tmp_path, monkeypatch)


def _set_clocks(monkeypatch: pytest.MonkeyPatch) -> None:
    now = binding.fixture.NOW
    monkeypatch.setattr(lifecycle, "_utc_now", lambda: now)
    monkeypatch.setattr("daedalus.kernel.runtime_effects._utc_now", lambda: now)
    monkeypatch.setattr("daedalus.kernel.effects._utc_now", lambda: now)


def _run(bundle):
    authorization, execution, authority, payload, abi, ledger, registry, pre_admission = (
        bundle[:8]
    )
    return run_sealed_runtime_provider(
        authorization.request.entrypoint_id,
        authorization=authorization,
        execution=execution,
        invocation_authority=authority,
        invocation_payload=payload,
        invocation_abi=abi,
        observation_binding_ledger=ledger,
        executable_registry=registry,
        pre_admission=pre_admission,
    )


def test_sealed_provider_executes_only_registered_payload_operation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle(tmp_path, monkeypatch)
    authorization, execution = bundle[:2]
    ledger = bundle[5]
    _set_clocks(monkeypatch)

    result = _run(bundle)

    assert result.executed is True
    assert result.value == {
        "result": "ok",
        "objective": "prove exact provider binding",
    }
    assert result.terminal_receipt is not None
    assert result.terminal_receipt.output_digests == ("a" * 64,)
    assert authorization.effect_ledger.execution_state(execution.execution_id) == "COMPLETED"
    assert ledger.load(execution.execution_id) is not None


def test_sealed_provider_exact_replay_is_inert_after_source_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle(tmp_path, monkeypatch)
    source_path = bundle[9]
    _set_clocks(monkeypatch)
    first = _run(bundle)
    assert first.executed is True

    source_path.write_text(
        source_path.read_text(encoding="utf-8") + "\nMUTATED_AFTER_COMPLETION = True\n",
        encoding="utf-8",
        newline="\n",
    )
    replay = _run(bundle)

    assert replay.executed is False
    assert replay.start_receipt == first.start_receipt
    assert replay.terminal_receipt is None


def test_sealed_provider_signature_accepts_no_caller_selected_callbacks() -> None:
    parameters = inspect.signature(run_sealed_runtime_provider).parameters
    assert "invoke" not in parameters
    assert "output_digests" not in parameters
    assert "observation_authority" not in parameters
    assert {
        "invocation_authority",
        "invocation_payload",
        "invocation_abi",
        "observation_binding_ledger",
        "executable_registry",
        "pre_admission",
    } <= set(parameters)


def test_sealed_payload_substitution_refuses_before_effect_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle(tmp_path, monkeypatch)
    authorization, execution, authority, _payload, abi, ledger, registry, pre_admission = (
        bundle[:8]
    )
    substituted = build_provider_invocation_payload(
        authority.invocation_subject,
        payload_schema_id=binding.PAYLOAD_SCHEMA_ID,
        body={"objective": "substituted after ABI issuance"},
    )
    _set_clocks(monkeypatch)

    with pytest.raises(lifecycle.RuntimeProviderBindingMismatch):
        run_sealed_runtime_provider(
            authorization.request.entrypoint_id,
            authorization=authorization,
            execution=execution,
            invocation_authority=authority,
            invocation_payload=substituted,
            invocation_abi=abi,
            observation_binding_ledger=ledger,
            executable_registry=registry,
            pre_admission=pre_admission,
        )

    assert authorization.effect_ledger.execution_state(execution.execution_id) is None


def test_sealed_output_evidence_failure_stays_started_for_reconciliation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle(tmp_path, monkeypatch)
    authorization, execution, authority, payload, _abi, ledger, registry, pre_admission = (
        bundle[:8]
    )
    body = payload.to_dict()["body"]
    body["fail_output"] = True
    failing_payload = build_provider_invocation_payload(
        authority.invocation_subject,
        payload_schema_id=binding.PAYLOAD_SCHEMA_ID,
        body=body,
    )
    failing_abi = issue_provider_invocation_abi_contract(
        authority,
        failing_payload,
        pre_admission,
        dependency_manifest_sha256=(
            registry.verify_registered(pre_admission).dependency_manifest_sha256
        ),
        authority_id=binding.AUTHORITY_ID,
        authority_keyring={binding.AUTHORITY_KEY_ID: binding.AUTHORITY_KEY},
        observation_keyring={
            binding.OBSERVATION_KEY_ID: binding.OBSERVATION_KEY,
        },
        execution=execution,
        at=binding.fixture.NOW,
    )
    _set_clocks(monkeypatch)

    with pytest.raises(lifecycle.RuntimeProviderReconciliationRequired):
        run_sealed_runtime_provider(
            authorization.request.entrypoint_id,
            authorization=authorization,
            execution=execution,
            invocation_authority=authority,
            invocation_payload=failing_payload,
            invocation_abi=failing_abi,
            observation_binding_ledger=ledger,
            executable_registry=registry,
            pre_admission=pre_admission,
        )

    assert authorization.effect_ledger.execution_state(execution.execution_id) == "STARTED"


def test_claude_provider_accepts_a_complete_sealed_transition_bundle() -> None:
    marker = object()
    assert (
        claude_provider._runtime_binding_mode(
            invocation_authority=marker,
            invocation_payload=marker,
            invocation_abi=marker,
            executable_registry=marker,
            pre_admission=marker,
            observation_authority=None,
            observation_binding_ledger=marker,
        )
        == "sealed"
    )


def test_claude_provider_refuses_partial_or_mixed_sealed_authority() -> None:
    marker = object()
    with pytest.raises(ClaudeProviderAuthorizationRequired, match="complete bundle"):
        claude_provider._runtime_binding_mode(
            invocation_authority=marker,
            invocation_payload=None,
            invocation_abi=marker,
            executable_registry=marker,
            pre_admission=marker,
            observation_authority=None,
            observation_binding_ledger=marker,
        )

    with pytest.raises(ClaudeProviderAuthorizationRequired, match="must not mix"):
        claude_provider._runtime_binding_mode(
            invocation_authority=marker,
            invocation_payload=marker,
            invocation_abi=marker,
            executable_registry=marker,
            pre_admission=marker,
            observation_authority=marker,
            observation_binding_ledger=marker,
        )


def test_public_ask_claude_surface_no_longer_exposes_legacy_observation_authority() -> None:
    parameters = inspect.signature(claude_bridge.ask_claude).parameters
    assert "observation_authority" not in parameters
    assert {
        "invocation_authority",
        "invocation_payload",
        "invocation_abi",
        "observation_binding_ledger",
        "executable_registry",
        "pre_admission",
    } <= set(parameters)


def test_claude_provider_has_a_callback_free_sealed_callsite() -> None:
    source = inspect.getsource(claude_provider.ClaudeCLIProvider.run)
    assert "run_sealed_runtime_provider(" in source
    sealed_tail = source.split("run_sealed_runtime_provider(", 1)[1].split(")", 1)[0]
    assert "invoke=" not in sealed_tail
    assert "output_digests=" not in sealed_tail
