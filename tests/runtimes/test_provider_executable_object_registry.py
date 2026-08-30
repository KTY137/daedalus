from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

from daedalus.runtimes.provider_executable_object_registry import (
    ProviderExecutableObjectAdmissionReceipt,
    ProviderExecutableObjectRegistry,
    ProviderExecutableObjectRegistryBindingError,
    ProviderExecutableObjectRegistryShapeError,
)
from daedalus.runtimes.provider_executable_pre_admission import (
    ProviderExecutablePreAdmissionReceipt,
)
from daedalus.spine.envelope import canonical_sha


REVISION = "a" * 40


def _sha(label: str) -> str:
    return canonical_sha({"label": label})


def _write_adapter(
    root: Path,
    *,
    module_name: str = "daedalus.providers.fixture_adapter",
    source: str | None = None,
):
    if source is None:
        source = (
            "CALLS = []\n"
            "\n"
            "def invoke():\n"
            "    CALLS.append('invoke')\n"
            "    return 'ok'\n"
            "\n"
            "def output_digests(value):\n"
            "    CALLS.append('output')\n"
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
    *,
    module_name: str,
    source_sha256: str,
) -> ProviderExecutablePreAdmissionReceipt:
    values = {
        "source_revision": REVISION,
        "resolution_sha256": _sha("resolution"),
        "verification_sha256": _sha("verification"),
        "structure_sha256": _sha("structure"),
        "completed_retention_sha256": _sha("retention"),
        "retention_effect_terminal_sha256": _sha("retention-terminal"),
        "repository_head_sha256": _sha("repository-head"),
        "provider_id": "provider-fixture",
        "adapter_id": "adapter-fixture",
        "implementation_id": "implementation-fixture-v1",
        "entrypoint_id": "ikarus-one-shot",
        "runtime_id": "runtime-fixture",
        "execution_id": "execution-1",
        "idempotency_key": "idempotency-1",
        "invocation_authority_sha256": _sha("invocation-authority"),
        "invocation_contract_sha256": _sha("invocation-contract"),
        "invocation_subject_sha256": _sha("invocation-subject"),
        "invocation_identity_projection_sha256": _sha("identity-projection"),
        "identity_registry_sha256": _sha("identity-registry"),
        "identity_descriptor_sha256": _sha("identity-descriptor"),
        "target_authority_sha256": _sha("target-authority"),
        "target_projection_sha256": _sha("target-projection"),
        "target_manifest_sha256": _sha("target-manifest"),
        "target_descriptor_sha256": _sha("target-descriptor"),
        "adapter_artifact_sha256": _sha("adapter-artifact"),
        "adapter_config_sha256": _sha("adapter-config"),
        "lease_sha256": _sha("lease"),
        "invoke_target": f"{module_name}:invoke",
        "invoke_source_sha256": source_sha256,
        "output_digests_target": f"{module_name}:output_digests",
        "output_digests_source_sha256": source_sha256,
    }
    return ProviderExecutablePreAdmissionReceipt(**values)


def test_registry_proves_loaded_objects_without_executing_them(tmp_path: Path) -> None:
    module, _path, source_sha = _write_adapter(tmp_path)
    subject = _pre_admission(
        module_name=module.__name__,
        source_sha256=source_sha,
    )
    registry = ProviderExecutableObjectRegistry(tmp_path)

    admission = registry.register(
        subject,
        invoke=module.invoke,
        output_digests=module.output_digests,
    )

    assert module.CALLS == []
    assert admission.pre_admission_sha256 == subject.digest
    payload = admission.to_dict()
    assert payload["repository_source_bytes_verified"] is True
    assert payload["loaded_object_targets_verified"] is True
    assert payload["loaded_object_bytecode_verified"] is True
    assert payload["provider_code_executed"] is False
    assert payload["provider_execution_allowed"] is False
    assert payload["effect_start_authorized"] is False
    assert payload["callback_seam_removed"] is False
    assert ProviderExecutableObjectAdmissionReceipt.from_dict(payload) == admission
    assert registry.verify_registered(subject) == admission
    assert module.CALLS == []


def test_registry_refuses_provider_object_substitution_before_execution(
    tmp_path: Path,
) -> None:
    first, _first_path, source_sha = _write_adapter(tmp_path)
    second, _second_path, _second_sha = _write_adapter(
        tmp_path,
        module_name="daedalus.providers.other_fixture_adapter",
    )
    subject = _pre_admission(
        module_name=first.__name__,
        source_sha256=source_sha,
    )
    registry = ProviderExecutableObjectRegistry(tmp_path)

    with pytest.raises(
        ProviderExecutableObjectRegistryBindingError,
        match="invoke function target differs",
    ):
        registry.register(
            subject,
            invoke=second.invoke,
            output_digests=first.output_digests,
        )

    assert first.CALLS == []
    assert second.CALLS == []


def test_registry_refuses_repository_source_mutation_after_registration(
    tmp_path: Path,
) -> None:
    module, path, source_sha = _write_adapter(tmp_path)
    subject = _pre_admission(
        module_name=module.__name__,
        source_sha256=source_sha,
    )
    registry = ProviderExecutableObjectRegistry(tmp_path)
    registry.register(
        subject,
        invoke=module.invoke,
        output_digests=module.output_digests,
    )

    path.write_text(
        path.read_text(encoding="utf-8") + "\nMUTATED = True\n",
        encoding="utf-8",
        newline="\n",
    )

    with pytest.raises(
        ProviderExecutableObjectRegistryBindingError,
        match="repository source digest differs",
    ):
        registry.verify_registered(subject)
    assert module.CALLS == []


def test_registry_refuses_loaded_bytecode_substitution(
    tmp_path: Path,
) -> None:
    module, path, source_sha = _write_adapter(tmp_path)
    subject = _pre_admission(
        module_name=module.__name__,
        source_sha256=source_sha,
    )
    registry = ProviderExecutableObjectRegistry(tmp_path)
    registry.register(
        subject,
        invoke=module.invoke,
        output_digests=module.output_digests,
    )

    namespace: dict[str, object] = {}
    exec(
        compile(
            "def invoke():\n    return 'substituted'\n",
            str(path),
            "exec",
        ),
        namespace,
    )
    replacement = namespace["invoke"]
    assert callable(replacement)
    module.invoke.__code__ = replacement.__code__  # type: ignore[attr-defined]

    with pytest.raises(
        ProviderExecutableObjectRegistryBindingError,
        match="loaded bytecode differs",
    ):
        registry.verify_registered(subject)
    assert module.CALLS == []


def test_registry_refuses_contradictory_hashes_for_one_source_file(
    tmp_path: Path,
) -> None:
    module, _path, source_sha = _write_adapter(tmp_path)
    subject = _pre_admission(
        module_name=module.__name__,
        source_sha256=source_sha,
    )
    subject = dataclasses.replace(
        subject,
        output_digests_source_sha256=_sha("contradictory-source"),
    )
    registry = ProviderExecutableObjectRegistry(tmp_path)

    with pytest.raises(
        ProviderExecutableObjectRegistryBindingError,
        match="contradictory authenticated digests",
    ):
        registry.register(
            subject,
            invoke=module.invoke,
            output_digests=module.output_digests,
        )
    assert module.CALLS == []


def test_registry_refuses_function_defaults_even_when_source_matches(
    tmp_path: Path,
) -> None:
    source = (
        "def invoke(value='ambient'):\n"
        "    return value\n"
        "\n"
        "def output_digests(value):\n"
        "    return ('a' * 64,)\n"
    )
    module, _path, source_sha = _write_adapter(tmp_path, source=source)
    subject = _pre_admission(
        module_name=module.__name__,
        source_sha256=source_sha,
    )
    registry = ProviderExecutableObjectRegistry(tmp_path)

    with pytest.raises(
        ProviderExecutableObjectRegistryBindingError,
        match="positional defaults are not admissible",
    ):
        registry.register(
            subject,
            invoke=module.invoke,
            output_digests=module.output_digests,
        )


def test_registry_refuses_reregistration_with_different_function_objects(
    tmp_path: Path,
) -> None:
    module, path, source_sha = _write_adapter(tmp_path)
    subject = _pre_admission(
        module_name=module.__name__,
        source_sha256=source_sha,
    )
    registry = ProviderExecutableObjectRegistry(tmp_path)
    admission = registry.register(
        subject,
        invoke=module.invoke,
        output_digests=module.output_digests,
    )

    spec = importlib.util.spec_from_file_location(module.__name__, path)
    assert spec is not None and spec.loader is not None
    replacement_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(replacement_module)

    with pytest.raises(
        ProviderExecutableObjectRegistryBindingError,
        match="already bound to different executable objects",
    ):
        registry.register(
            subject,
            invoke=replacement_module.invoke,
            output_digests=replacement_module.output_digests,
        )
    assert admission == registry.verify_registered(subject)


def test_admission_deserialization_refuses_authority_escalation(
    tmp_path: Path,
) -> None:
    module, _path, source_sha = _write_adapter(tmp_path)
    subject = _pre_admission(
        module_name=module.__name__,
        source_sha256=source_sha,
    )
    admission = ProviderExecutableObjectRegistry(tmp_path).register(
        subject,
        invoke=module.invoke,
        output_digests=module.output_digests,
    )
    payload = admission.to_dict()
    payload["provider_execution_allowed"] = True

    with pytest.raises(
        ProviderExecutableObjectRegistryShapeError,
        match="escalated claim: provider_execution_allowed",
    ):
        ProviderExecutableObjectAdmissionReceipt.from_dict(payload)


def test_registry_refuses_subclassed_pre_admission(tmp_path: Path) -> None:
    module, _path, source_sha = _write_adapter(tmp_path)
    subject = _pre_admission(
        module_name=module.__name__,
        source_sha256=source_sha,
    )

    class SubclassedPreAdmission(ProviderExecutablePreAdmissionReceipt):
        pass

    subclassed = SubclassedPreAdmission(**dataclasses.asdict(subject))
    with pytest.raises(
        ProviderExecutableObjectRegistryShapeError,
        match="pre_admission must be exact",
    ):
        ProviderExecutableObjectRegistry(tmp_path).register(
            subclassed,
            invoke=module.invoke,
            output_digests=module.output_digests,
        )
