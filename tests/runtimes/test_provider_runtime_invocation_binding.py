from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from daedalus.runtimes.provider.executable_object_registry import (
    ProviderExecutableObjectRegistry,
)
from daedalus.runtimes.provider.executable_pre_admission import (
    ProviderExecutablePreAdmissionReceipt,
)
from daedalus.runtimes.provider.invocation import ProviderInvocationSubject
from daedalus.runtimes.provider.invocation_abi import issue_provider_invocation_abi_contract
from daedalus.runtimes.provider.invocation_authority import (
    issue_provider_invocation_observation_authority,
)
from daedalus.runtimes.provider.invocation_payload import build_provider_invocation_payload
from daedalus.runtimes.provider.observation import (
    ProviderObservationBindingLedger,
    issue_provider_observation_authority,
)
from daedalus.runtimes.provider.runtime_executable_binding import (
    ProviderRuntimeExecutableBindingReceipt,
)
from daedalus.runtimes.provider.runtime_invocation_binding import (
    ProviderRuntimeInvocationBindingMismatch,
    ProviderRuntimeInvocationBindingShapeError,
    bind_provider_runtime_invocation,
)
from daedalus.spine.envelope import canonical_sha


ROOT = Path(__file__).resolve().parents[2]
AUTHORITY_FIXTURE = ROOT / "tests/kernel/test_runtime_effect_replay_projection.py"
AUTHORITY_ID = "authority.ikarus-runtime-invocation-binding"
AUTHORITY_KEY_ID = "ikarus-runtime-invocation-authority-key"
AUTHORITY_KEY = b"ikarus-runtime-invocation-authority-key-material-32-bytes"
OBSERVATION_KEY_ID = "ikarus-runtime-invocation-observation-key"
OBSERVATION_KEY = b"ikarus-runtime-invocation-observation-key-material-32-bytes"
RECORD_KEY = b"ikarus-runtime-invocation-record-key-material-at-least-32-bytes"
PROVIDER_ID = "provider.external-runtime-fixture"
ADAPTER_ID = "adapter-ikarus-runtime-fixture"
IMPLEMENTATION_ID = "implementation-ikarus-runtime-fixture-v1"
PAYLOAD_SCHEMA_ID = "ikarus-runtime-fixture-one-shot-v1"
INVOCATION_CONTRACT_ID = "provider-invocation-contract"


def _sha(label: str) -> str:
    return canonical_sha({"label": label})


def _load_authority_fixture():
    name = "daedalus_test_ikarus_runtime_invocation_binding_fixture"
    spec = importlib.util.spec_from_file_location(name, AUTHORITY_FIXTURE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fixture = _load_authority_fixture()


def _write_adapter(root: Path):
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


def _invocation_subject(authorization, execution) -> ProviderInvocationSubject:
    return ProviderInvocationSubject(
        provider_id=PROVIDER_ID,
        adapter_id=ADAPTER_ID,
        adapter_artifact_sha256=_sha("adapter-artifact"),
        adapter_config_sha256=_sha("adapter-config"),
        entrypoint_id=authorization.request.entrypoint_id,
        runtime_id=authorization.capability.runtime_id,
        execution_id=execution.execution_id,
        idempotency_key=execution.idempotency_key,
        execution_request_sha256=execution.digest,
        lease_sha256=authorization.capability.lease.digest,
        source_revision=authorization.capability.source_revision,
    )


def _pre_admission(authority, *, module_name: str, source_sha256: str, provider_id=PROVIDER_ID):
    subject = authority.invocation_subject
    return ProviderExecutablePreAdmissionReceipt(
        source_revision=subject.source_revision,
        resolution_sha256=_sha("resolution"),
        verification_sha256=_sha("verification"),
        structure_sha256=_sha("structure"),
        completed_retention_sha256=_sha("retention"),
        retention_effect_terminal_sha256=_sha("retention-terminal"),
        repository_head_sha256=_sha("repository-head"),
        provider_id=provider_id,
        adapter_id=subject.adapter_id,
        implementation_id=IMPLEMENTATION_ID,
        entrypoint_id=subject.entrypoint_id,
        runtime_id=subject.runtime_id,
        execution_id=subject.execution_id,
        idempotency_key=subject.idempotency_key,
        invocation_authority_sha256=authority.digest,
        invocation_contract_sha256=authority.invocation_contract_sha256,
        invocation_subject_sha256=subject.digest,
        invocation_identity_projection_sha256=_sha("identity-projection"),
        identity_registry_sha256=authority.invocation_registry_sha256,
        identity_descriptor_sha256=_sha("identity-descriptor"),
        target_authority_sha256=_sha("target-authority"),
        target_projection_sha256=_sha("target-projection"),
        target_manifest_sha256=_sha("target-manifest"),
        target_descriptor_sha256=_sha("target-descriptor"),
        adapter_artifact_sha256=subject.adapter_artifact_sha256,
        adapter_config_sha256=subject.adapter_config_sha256,
        lease_sha256=subject.lease_sha256,
        invoke_target=f"{module_name}:invoke",
        invoke_source_sha256=source_sha256,
        output_digests_target=f"{module_name}:output_digests",
        output_digests_source_sha256=source_sha256,
    )


def _bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    authorization, _record = fixture._authorization(tmp_path, monkeypatch)
    execution = fixture._execution()
    subject = _invocation_subject(authorization, execution)
    observation = issue_provider_observation_authority(
        authority_id=AUTHORITY_ID,
        authority_key_id=AUTHORITY_KEY_ID,
        authority_secret=AUTHORITY_KEY,
        binding_id="ikarus-runtime-invocation-binding",
        provider_id=subject.provider_id,
        observation_keyring={OBSERVATION_KEY_ID: OBSERVATION_KEY},
        entrypoint_id=subject.entrypoint_id,
        runtime_id=subject.runtime_id,
        execution=execution,
        lease_sha256=subject.lease_sha256,
        source_revision=subject.source_revision,
        issued_at=fixture.NOW - timedelta(minutes=1),
        expires_at=fixture.NOW + timedelta(hours=1),
    )
    authority = issue_provider_invocation_observation_authority(
        observation_authority=observation,
        invocation_subject=subject,
        invocation_contract_id=INVOCATION_CONTRACT_ID,
        invocation_registry_sha256=_sha("invocation-registry"),
        authority_secret=AUTHORITY_KEY,
    )
    payload = build_provider_invocation_payload(
        subject,
        payload_schema_id=PAYLOAD_SCHEMA_ID,
        body={
            "objective": "prove exact provider binding",
            "workspace": "/tmp/ikarus-runtime-fixture",
            "paths": ["src", "tests"],
            "model": "fixture-model",
            "timeout_seconds": 120,
        },
    )
    ledger = ProviderObservationBindingLedger(
        tmp_path / "provider-runtime-invocation-binding.sqlite3",
        authority_id=AUTHORITY_ID,
        authority_keyring={AUTHORITY_KEY_ID: AUTHORITY_KEY},
        observation_keyring={OBSERVATION_KEY_ID: OBSERVATION_KEY},
        record_secret=RECORD_KEY,
    )
    module, path, source_sha = _write_adapter(tmp_path)
    pre_admission = _pre_admission(
        authority,
        module_name=module.__name__,
        source_sha256=source_sha,
    )
    registry = ProviderExecutableObjectRegistry(tmp_path)
    executable_admission = registry.register(
        pre_admission,
        invoke=module.invoke,
        output_digests=module.output_digests,
    )
    abi = issue_provider_invocation_abi_contract(
        authority,
        payload,
        pre_admission,
        dependency_manifest_sha256=(
            executable_admission.dependency_manifest_sha256
        ),
        authority_id=AUTHORITY_ID,
        authority_keyring={AUTHORITY_KEY_ID: AUTHORITY_KEY},
        observation_keyring={OBSERVATION_KEY_ID: OBSERVATION_KEY},
        execution=execution,
        at=fixture.NOW,
    )
    return [
        authorization,
        execution,
        authority,
        payload,
        abi,
        ledger,
        registry,
        pre_admission,
        module,
        path,
        executable_admission,
    ]


def _bind(bundle):
    authorization, execution, authority, payload, abi, ledger, registry, pre_admission = bundle[:8]
    return bind_provider_runtime_invocation(
        authorization.request.entrypoint_id,
        authorization=authorization,
        execution=execution,
        invocation_authority=authority,
        invocation_payload=payload,
        invocation_abi=abi,
        observation_binding_ledger=ledger,
        executable_registry=registry,
        pre_admission=pre_admission,
        at=fixture.NOW,
    )


def test_runtime_invocation_binding_authenticates_conjunction_without_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle(tmp_path, monkeypatch)
    authorization, execution, authority, payload, abi, ledger, _, pre_admission = bundle[:8]

    receipt = _bind(bundle)

    assert type(receipt) is ProviderRuntimeExecutableBindingReceipt
    assert authorization.effect_ledger.execution_state(execution.execution_id) is None
    assert ledger.load(execution.execution_id) is None
    assert receipt.provider_id == authority.invocation_subject.provider_id
    assert receipt.adapter_id == authority.invocation_subject.adapter_id
    assert receipt.pre_admission_sha256 == pre_admission.digest
    assert (
        receipt.dependency_manifest_sha256
        == bundle[10].dependency_manifest_sha256
        == abi.dependency_manifest_sha256
    )
    assert abi.invocation_payload_sha256 == payload.digest
    rendered = receipt.to_dict()
    assert rendered["pre_effect_subject_verified"] is True
    assert rendered["effect_started"] is False
    assert rendered["provider_code_executed"] is False
    assert rendered["provider_execution_allowed"] is False
    assert rendered["callback_seam_removed"] is False


def test_ledger_owned_abi_verification_returns_no_key_material(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle(tmp_path, monkeypatch)
    _, execution, authority, payload, abi, ledger, _, pre_admission = bundle[:8]

    result = ledger.verify_invocation_abi_contract(
        abi,
        authority,
        payload,
        pre_admission,
        execution=execution,
        at=fixture.NOW,
    )

    assert result is None
    assert ledger.load(execution.execution_id) is None


def test_runtime_invocation_binding_requires_exact_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle(tmp_path, monkeypatch)
    bundle[5] = object()

    with pytest.raises(
        ProviderRuntimeInvocationBindingShapeError,
        match="must be exact ProviderObservationBindingLedger",
    ):
        _bind(bundle)


def test_semantic_payload_substitution_refuses_before_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle(tmp_path, monkeypatch)
    authorization, execution, authority = bundle[:3]
    bundle[3] = build_provider_invocation_payload(
        authority.invocation_subject,
        payload_schema_id=PAYLOAD_SCHEMA_ID,
        body={"objective": "different objective"},
    )

    with pytest.raises(
        ProviderRuntimeInvocationBindingMismatch,
        match="invocation ABI did not authenticate pre-effect",
    ):
        _bind(bundle)
    assert authorization.effect_ledger.execution_state(execution.execution_id) is None


def test_provider_a_authority_plus_provider_b_pre_admission_refuses_before_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle(tmp_path, monkeypatch)
    authorization, execution = bundle[:2]
    pre_admission = bundle[7]
    module = bundle[8]
    foreign = dataclasses.replace(pre_admission, provider_id="provider.foreign-runtime")
    foreign_registry = ProviderExecutableObjectRegistry(tmp_path)
    foreign_registry.register(
        foreign,
        invoke=module.invoke,
        output_digests=module.output_digests,
    )
    bundle[6] = foreign_registry
    bundle[7] = foreign

    with pytest.raises(
        ProviderRuntimeInvocationBindingMismatch,
        match="invocation ABI did not authenticate pre-effect",
    ):
        _bind(bundle)
    assert authorization.effect_ledger.execution_state(execution.execution_id) is None


def test_forged_abi_signature_refuses_before_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle(tmp_path, monkeypatch)
    authorization, execution = bundle[:2]
    bundle[4] = dataclasses.replace(bundle[4], signature_sha256="f" * 64)

    with pytest.raises(
        ProviderRuntimeInvocationBindingMismatch,
        match="invocation ABI did not authenticate pre-effect",
    ):
        _bind(bundle)
    assert authorization.effect_ledger.execution_state(execution.execution_id) is None


def test_signed_dependency_manifest_substitution_refuses_before_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle(tmp_path, monkeypatch)
    authorization, execution, authority, payload, _abi, _ledger, _, pre_admission = (
        bundle[:8]
    )
    bundle[4] = issue_provider_invocation_abi_contract(
        authority,
        payload,
        pre_admission,
        dependency_manifest_sha256=_sha("foreign-dependency-manifest"),
        authority_id=AUTHORITY_ID,
        authority_keyring={AUTHORITY_KEY_ID: AUTHORITY_KEY},
        observation_keyring={OBSERVATION_KEY_ID: OBSERVATION_KEY},
        execution=execution,
        at=fixture.NOW,
    )

    with pytest.raises(
        ProviderRuntimeInvocationBindingMismatch,
        match="authenticated invocation/executable subject mismatch: "
        "dependency_manifest_sha256",
    ):
        _bind(bundle)
    assert authorization.effect_ledger.execution_state(execution.execution_id) is None


def test_exact_ledger_instance_shadow_cannot_bypass_forged_abi_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle(tmp_path, monkeypatch)
    authorization, execution = bundle[:2]
    ledger = bundle[5]
    assert type(ledger) is ProviderObservationBindingLedger
    bundle[4] = dataclasses.replace(bundle[4], signature_sha256="0" * 64)
    ledger.__dict__["verify_invocation_abi_contract"] = (
        lambda *args, **kwargs: None
    )

    with pytest.raises(
        ProviderRuntimeInvocationBindingMismatch,
        match="invocation ABI did not authenticate pre-effect",
    ):
        _bind(bundle)
    assert authorization.effect_ledger.execution_state(execution.execution_id) is None
    assert ledger.load(execution.execution_id) is None


def test_repository_source_mutation_after_admission_refuses_before_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle(tmp_path, monkeypatch)
    authorization, execution = bundle[:2]
    path = bundle[9]
    path.write_text(
        path.read_text(encoding="utf-8") + "\nMUTATED = True\n",
        encoding="utf-8",
        newline="\n",
    )

    with pytest.raises(
        ProviderRuntimeInvocationBindingMismatch,
        match="executable subject did not authenticate pre-effect",
    ):
        _bind(bundle)
    assert authorization.effect_ledger.execution_state(execution.execution_id) is None


def test_d4_broker_executes_only_registered_payload_operation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from daedalus.runtimes.broker import run_runtime_provider

    bundle = _bundle(tmp_path, monkeypatch)
    authorization, execution, authority, payload, abi, ledger, registry, pre_admission = (
        bundle[:8]
    )
    monkeypatch.setattr("daedalus.runtimes.broker._utc_now", lambda: fixture.NOW)
    monkeypatch.setattr("daedalus.kernel.runtime_effects._utc_now", lambda: fixture.NOW)
    monkeypatch.setattr("daedalus.kernel.effects._utc_now", lambda: fixture.NOW)

    result = run_runtime_provider(
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

    assert result.executed is True
    assert result.value == {
        "result": "ok",
        "objective": "prove exact provider binding",
    }
    assert result.terminal_receipt is not None
    assert result.terminal_receipt.output_digests == ("a" * 64,)
    assert authorization.effect_ledger.execution_state(execution.execution_id) == "COMPLETED"
    assert ledger.load(execution.execution_id) is not None


def test_d4_exact_replay_does_not_reverify_or_execute_registered_objects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from daedalus.runtimes.broker import run_runtime_provider

    bundle = _bundle(tmp_path, monkeypatch)
    authorization, execution, authority, payload, abi, ledger, registry, pre_admission = (
        bundle[:8]
    )
    source_path = bundle[9]
    monkeypatch.setattr("daedalus.runtimes.broker._utc_now", lambda: fixture.NOW)
    monkeypatch.setattr("daedalus.kernel.runtime_effects._utc_now", lambda: fixture.NOW)
    monkeypatch.setattr("daedalus.kernel.effects._utc_now", lambda: fixture.NOW)
    kwargs = dict(
        authorization=authorization,
        execution=execution,
        invocation_authority=authority,
        invocation_payload=payload,
        invocation_abi=abi,
        observation_binding_ledger=ledger,
        executable_registry=registry,
        pre_admission=pre_admission,
    )
    first = run_runtime_provider(authorization.request.entrypoint_id, **kwargs)
    assert first.executed is True

    source_path.write_text(
        source_path.read_text(encoding="utf-8") + "\nMUTATED_AFTER_COMPLETION = True\n",
        encoding="utf-8",
        newline="\n",
    )
    replay = run_runtime_provider(authorization.request.entrypoint_id, **kwargs)

    assert replay.executed is False
    assert replay.start_receipt == first.start_receipt
    assert replay.terminal_receipt is None


def test_d4_production_signature_contains_no_loose_callback() -> None:
    import inspect

    from daedalus.runtimes.broker import run_runtime_provider

    parameters = inspect.signature(run_runtime_provider).parameters
    assert "invoke" not in parameters
    assert "output_digests" not in parameters
    assert {
        "invocation_authority",
        "invocation_payload",
        "invocation_abi",
        "executable_registry",
        "pre_admission",
    } <= set(parameters)


def test_d4_payload_substitution_refuses_before_effect_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from daedalus.runtimes.broker import RuntimeProviderBindingMismatch, run_runtime_provider

    bundle = _bundle(tmp_path, monkeypatch)
    authorization, execution, authority, _payload, abi, ledger, registry, pre_admission = (
        bundle[:8]
    )
    substituted = build_provider_invocation_payload(
        authority.invocation_subject,
        payload_schema_id=PAYLOAD_SCHEMA_ID,
        body={"objective": "substituted after ABI issuance"},
    )
    monkeypatch.setattr("daedalus.runtimes.broker._utc_now", lambda: fixture.NOW)
    with pytest.raises(RuntimeProviderBindingMismatch):
        run_runtime_provider(
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


def test_d4_fixed_output_evidence_failure_stays_started_for_reconciliation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from daedalus.runtimes.broker import (
        RuntimeProviderReconciliationRequired,
        run_runtime_provider,
    )

    bundle = _bundle(tmp_path, monkeypatch)
    authorization, execution, authority, payload, _abi, ledger, registry, pre_admission = (
        bundle[:8]
    )
    body = payload.to_dict()["body"]
    body["fail_output"] = True
    failing_payload = build_provider_invocation_payload(
        authority.invocation_subject,
        payload_schema_id=PAYLOAD_SCHEMA_ID,
        body=body,
    )
    failing_abi = issue_provider_invocation_abi_contract(
        authority,
        failing_payload,
        pre_admission,
        dependency_manifest_sha256=(
            registry.verify_registered(pre_admission).dependency_manifest_sha256
        ),
        authority_id=AUTHORITY_ID,
        authority_keyring={AUTHORITY_KEY_ID: AUTHORITY_KEY},
        observation_keyring={OBSERVATION_KEY_ID: OBSERVATION_KEY},
        execution=execution,
        at=fixture.NOW,
    )
    monkeypatch.setattr("daedalus.runtimes.broker._utc_now", lambda: fixture.NOW)
    monkeypatch.setattr("daedalus.kernel.runtime_effects._utc_now", lambda: fixture.NOW)
    monkeypatch.setattr("daedalus.kernel.effects._utc_now", lambda: fixture.NOW)
    with pytest.raises(RuntimeProviderReconciliationRequired):
        run_runtime_provider(
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
