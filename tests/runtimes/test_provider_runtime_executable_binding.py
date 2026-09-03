from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from daedalus.kernel.runtime_effects import RuntimeBoundEffectAuthorization
from daedalus.runtimes.provider.executable_object_registry import (
    ProviderExecutableObjectRegistry,
)
from daedalus.runtimes.provider.executable_pre_admission import (
    ProviderExecutablePreAdmissionReceipt,
)
from daedalus.runtimes.provider.observation import (
    ProviderObservationAuthority,
    ProviderObservationBindingLedger,
    issue_provider_observation_authority,
)
from daedalus.runtimes.provider.runtime_executable_binding import (
    ProviderRuntimeExecutableBindingMismatch,
    ProviderRuntimeExecutableBindingReceipt,
    ProviderRuntimeExecutableBindingShapeError,
    bind_provider_runtime_executable,
)
from daedalus.spine.envelope import canonical_sha


ROOT = Path(__file__).resolve().parents[2]
AUTHORITY_FIXTURE = ROOT / "tests/kernel/test_runtime_effect_replay_projection.py"
AUTHORITY_KEY_ID = "ikarus-binding-authority-key"
AUTHORITY_KEY = b"ikarus-binding-authority-key-material-at-least-32-bytes"
OBSERVATION_KEY_ID = "ikarus-binding-observation-key"
OBSERVATION_KEY = b"ikarus-binding-observation-key-material-at-least-32-bytes"
RECORD_KEY = b"ikarus-binding-record-key-material-at-least-32-bytes"
PROVIDER_ID = "provider.external-runtime-fixture"


def _sha(label: str) -> str:
    return canonical_sha({"label": label})


def _load_authority_fixture():
    name = "daedalus_test_ikarus_provider_runtime_binding_fixture"
    spec = importlib.util.spec_from_file_location(name, AUTHORITY_FIXTURE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fixture = _load_authority_fixture()


def _write_adapter(
    root: Path,
    *,
    module_name: str = "daedalus.providers.ikarus_binding_fixture_adapter",
):
    source = (
        "CALLS = []\n"
        "\n"
        "def helper():\n"
        "    return 'ok'\n"
        "\n"
        "def other_helper():\n"
        "    return 'substituted'\n"
        "\n"
        "def invoke():\n"
        "    return helper()\n"
        "\n"
        "def output_digests(value):\n"
        "    return ('a' * 64,)\n"
    )
    relative = Path(*module_name.split(".")).with_suffix(".py")
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8", newline="\n")
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module, path, hashlib.sha256(path.read_bytes()).hexdigest()


def _pre_admission(
    authorization,
    execution,
    *,
    module_name: str,
    source_sha256: str,
    provider_id: str = PROVIDER_ID,
) -> ProviderExecutablePreAdmissionReceipt:
    return ProviderExecutablePreAdmissionReceipt(
        source_revision=authorization.capability.source_revision,
        resolution_sha256=_sha("resolution"),
        verification_sha256=_sha("verification"),
        structure_sha256=_sha("structure"),
        completed_retention_sha256=_sha("retention"),
        retention_effect_terminal_sha256=_sha("retention-terminal"),
        repository_head_sha256=_sha("repository-head"),
        provider_id=provider_id,
        adapter_id="adapter-ikarus-binding-fixture",
        implementation_id="implementation-ikarus-binding-fixture-v1",
        entrypoint_id=authorization.request.entrypoint_id,
        runtime_id=authorization.capability.runtime_id,
        execution_id=execution.execution_id,
        idempotency_key=execution.idempotency_key,
        invocation_authority_sha256=_sha("invocation-authority"),
        invocation_contract_sha256=_sha("invocation-contract"),
        invocation_subject_sha256=_sha("invocation-subject"),
        invocation_identity_projection_sha256=_sha("identity-projection"),
        identity_registry_sha256=_sha("identity-registry"),
        identity_descriptor_sha256=_sha("identity-descriptor"),
        target_authority_sha256=_sha("target-authority"),
        target_projection_sha256=_sha("target-projection"),
        target_manifest_sha256=_sha("target-manifest"),
        target_descriptor_sha256=_sha("target-descriptor"),
        adapter_artifact_sha256=_sha("adapter-artifact"),
        adapter_config_sha256=_sha("adapter-config"),
        lease_sha256=authorization.capability.lease.digest,
        invoke_target=f"{module_name}:invoke",
        invoke_source_sha256=source_sha256,
        output_digests_target=f"{module_name}:output_digests",
        output_digests_source_sha256=source_sha256,
    )


def _subject(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    authorization, _record = fixture._authorization(tmp_path, monkeypatch)
    execution = fixture._execution()
    authority = issue_provider_observation_authority(
        authority_id="authority.ikarus-provider-binding",
        authority_key_id=AUTHORITY_KEY_ID,
        authority_secret=AUTHORITY_KEY,
        binding_id="ikarus-provider-binding",
        provider_id=PROVIDER_ID,
        observation_keyring={OBSERVATION_KEY_ID: OBSERVATION_KEY},
        entrypoint_id=authorization.request.entrypoint_id,
        runtime_id=authorization.capability.runtime_id,
        execution=execution,
        lease_sha256=authorization.capability.lease.digest,
        source_revision=authorization.capability.source_revision,
        issued_at=fixture.NOW - timedelta(minutes=1),
        expires_at=fixture.NOW + timedelta(hours=1),
    )
    ledger = ProviderObservationBindingLedger(
        tmp_path / "provider-binding.sqlite3",
        authority_id="authority.ikarus-provider-binding",
        authority_keyring={AUTHORITY_KEY_ID: AUTHORITY_KEY},
        observation_keyring={OBSERVATION_KEY_ID: OBSERVATION_KEY},
        record_secret=RECORD_KEY,
    )
    module, path, source_sha = _write_adapter(tmp_path)
    pre_admission = _pre_admission(
        authorization,
        execution,
        module_name=module.__name__,
        source_sha256=source_sha,
    )
    registry = ProviderExecutableObjectRegistry(tmp_path)
    registry.register(
        pre_admission,
        invoke=module.invoke,
        output_digests=module.output_digests,
    )
    return (
        authorization,
        execution,
        authority,
        ledger,
        registry,
        pre_admission,
        module,
        path,
    )


def _bind(
    authorization,
    execution,
    authority,
    ledger,
    registry,
    pre_admission,
):
    return bind_provider_runtime_executable(
        authorization.request.entrypoint_id,
        authorization=authorization,
        execution=execution,
        observation_authority=authority,
        observation_binding_ledger=ledger,
        executable_registry=registry,
        pre_admission=pre_admission,
        at=fixture.NOW,
    )


def test_binding_authenticates_provider_and_executable_without_starting_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject(tmp_path, monkeypatch)
    authorization, execution, authority, ledger, registry, pre_admission, module, _ = subject

    receipt = _bind(
        authorization,
        execution,
        authority,
        ledger,
        registry,
        pre_admission,
    )

    assert module.CALLS == []
    assert authorization.effect_ledger.execution_state(execution.execution_id) is None
    assert ledger.load(execution.execution_id) is None
    assert receipt.provider_id == authority.provider_id
    assert receipt.pre_admission_sha256 == pre_admission.digest
    assert (
        receipt.dependency_manifest_sha256
        == registry.verify_registered(pre_admission).dependency_manifest_sha256
    )
    payload = receipt.to_dict()
    assert payload["observation_authority_authenticated_before_effect"] is True
    assert payload["registered_executable_objects_reverified"] is True
    assert payload["pre_effect_subject_verified"] is True
    assert payload["effect_lease_granted"] is False
    assert payload["effect_started"] is False
    assert payload["provider_start_persisted"] is False
    assert payload["provider_code_executed"] is False
    assert payload["provider_execution_allowed"] is False
    assert payload["callback_seam_removed"] is False
    assert ProviderRuntimeExecutableBindingReceipt.from_dict(payload) == receipt


def test_provider_a_authority_plus_provider_b_executable_refuses_before_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject(tmp_path, monkeypatch)
    authorization, execution, authority, ledger, _registry, pre_admission, module, _ = subject
    foreign = dataclasses.replace(pre_admission, provider_id="provider.foreign-runtime")
    foreign_registry = ProviderExecutableObjectRegistry(tmp_path)
    foreign_registry.register(
        foreign,
        invoke=module.invoke,
        output_digests=module.output_digests,
    )

    with pytest.raises(
        ProviderRuntimeExecutableBindingMismatch,
        match="provider observation subject mismatch: provider_id",
    ):
        _bind(
            authorization,
            execution,
            authority,
            ledger,
            foreign_registry,
            foreign,
        )

    assert module.CALLS == []
    assert authorization.effect_ledger.execution_state(execution.execution_id) is None
    assert ledger.load(execution.execution_id) is None


def test_bad_observation_signature_refuses_before_registry_or_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject(tmp_path, monkeypatch)
    authorization, execution, authority, ledger, registry, pre_admission, module, _ = subject
    forged = dataclasses.replace(authority, signature_sha256="f" * 64)

    with pytest.raises(
        ProviderRuntimeExecutableBindingMismatch,
        match="did not authenticate pre-effect",
    ):
        _bind(
            authorization,
            execution,
            forged,
            ledger,
            registry,
            pre_admission,
        )

    assert module.CALLS == []
    assert authorization.effect_ledger.execution_state(execution.execution_id) is None
    assert ledger.load(execution.execution_id) is None


def test_repository_mutation_after_admission_refuses_before_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject(tmp_path, monkeypatch)
    authorization, execution, authority, ledger, registry, pre_admission, module, path = subject
    path.write_text(
        path.read_text(encoding="utf-8") + "\nMUTATED = True\n",
        encoding="utf-8",
        newline="\n",
    )

    with pytest.raises(
        ProviderRuntimeExecutableBindingMismatch,
        match="did not reverify pre-effect",
    ):
        _bind(
            authorization,
            execution,
            authority,
            ledger,
            registry,
            pre_admission,
        )

    assert module.CALLS == []
    assert authorization.effect_ledger.execution_state(execution.execution_id) is None
    assert ledger.load(execution.execution_id) is None


def test_ambient_helper_rebinding_after_admission_refuses_before_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject(tmp_path, monkeypatch)
    authorization, execution, authority, ledger, registry, pre_admission, module, _ = subject
    module.helper = module.other_helper

    with pytest.raises(
        ProviderRuntimeExecutableBindingMismatch,
        match="did not reverify pre-effect",
    ):
        _bind(
            authorization,
            execution,
            authority,
            ledger,
            registry,
            pre_admission,
        )

    assert module.CALLS == []
    assert authorization.effect_ledger.execution_state(execution.execution_id) is None
    assert ledger.load(execution.execution_id) is None


def test_exact_boundary_types_refuse_subclass_smuggling_before_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject(tmp_path, monkeypatch)
    authorization, execution, authority, ledger, registry, pre_admission, module, _ = subject

    class AuthorizationSubclass(RuntimeBoundEffectAuthorization):
        pass

    subclassed = AuthorizationSubclass(
        capability=authorization.capability,
        request=authorization.request,
        policy_decision=authorization.policy_decision,
        effect_ledger=authorization.effect_ledger,
        runtime_trust_ledger=authorization.runtime_trust_ledger,
        lease_keyring=authorization.lease_keyring,
        runtime_authority_keyring=authorization.runtime_authority_keyring,
        guard_decisions=authorization.guard_decisions,
        current_kill_switch_generation=authorization.current_kill_switch_generation,
        registry=authorization.registry,
    )
    with pytest.raises(
        ProviderRuntimeExecutableBindingShapeError,
        match="authorization must be exact",
    ):
        _bind(
            subclassed,
            execution,
            authority,
            ledger,
            registry,
            pre_admission,
        )

    assert module.CALLS == []
    assert authorization.effect_ledger.execution_state(execution.execution_id) is None


def test_binding_receipt_refuses_authority_escalation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject(tmp_path, monkeypatch)
    authorization, execution, authority, ledger, registry, pre_admission, _module, _ = subject
    receipt = _bind(
        authorization,
        execution,
        authority,
        ledger,
        registry,
        pre_admission,
    )
    payload = receipt.to_dict()
    payload["provider_execution_allowed"] = True

    with pytest.raises(
        ProviderRuntimeExecutableBindingShapeError,
        match="escalated claim: provider_execution_allowed",
    ):
        ProviderRuntimeExecutableBindingReceipt.from_dict(payload)


def test_subclassed_pre_admission_is_not_accepted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject(tmp_path, monkeypatch)
    authorization, execution, authority, ledger, registry, pre_admission, module, _ = subject

    class PreAdmissionSubclass(ProviderExecutablePreAdmissionReceipt):
        pass

    subclassed = PreAdmissionSubclass(**dataclasses.asdict(pre_admission))
    with pytest.raises(
        ProviderRuntimeExecutableBindingShapeError,
        match="pre_admission must be exact",
    ):
        _bind(
            authorization,
            execution,
            authority,
            ledger,
            registry,
            subclassed,
        )

    assert module.CALLS == []
    assert authorization.effect_ledger.execution_state(execution.execution_id) is None
