from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

import daedalus.runtimes.provider_executable_structure as subject
from daedalus.gates.python_target_structure import resolve_python_target_structure
from daedalus.runtimes.provider_executable_structure import (
    ProviderExecutableStructureBindingError,
)
from daedalus.runtimes.provider_executable_targets import (
    ProviderExecutableTargetProjection,
)


SOURCE = b'''def invoke():\n    return "ok"\n\ndef output_digests(value):\n    return ("0" * 64,)\n'''


def _fixture(tmp_path: Path) -> tuple[Path, ProviderExecutableTargetProjection]:
    package = tmp_path / "daedalus"
    package.mkdir()
    (package / "demo_provider.py").write_bytes(SOURCE)
    digest = hashlib.sha256(SOURCE).hexdigest()
    projection = ProviderExecutableTargetProjection(
        provider_id="provider_a",
        adapter_id="adapter_a",
        implementation_id="implementation_a",
        entrypoint_id="runtime_provider",
        runtime_id="runtime_a",
        source_revision="a" * 40,
        identity_sha256="1" * 64,
        identity_registry_sha256="2" * 64,
        identity_descriptor_sha256="3" * 64,
        target_manifest_sha256="4" * 64,
        target_descriptor_sha256="5" * 64,
        adapter_artifact_sha256="6" * 64,
        adapter_config_sha256="7" * 64,
        invoke_target="daedalus.demo_provider:invoke",
        invoke_source_sha256=digest,
        output_digests_target="daedalus.demo_provider:output_digests",
        output_digests_source_sha256=digest,
    )
    return tmp_path, projection


def test_resolver_cannot_substitute_invoke_structure_for_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, projection = _fixture(tmp_path)
    invoke = resolve_python_target_structure(
        root,
        projection.invoke_target,
        expected_source_sha256=projection.invoke_source_sha256,
    )

    def substituted(*args, **kwargs):
        return invoke

    monkeypatch.setattr(subject, "resolve_python_target_structure", substituted)

    with pytest.raises(ProviderExecutableStructureBindingError):
        subject.verify_provider_executable_structure(root, projection)


def test_resolver_cannot_detach_invoke_source_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, projection = _fixture(tmp_path)
    real_invoke = resolve_python_target_structure(
        root,
        projection.invoke_target,
        expected_source_sha256=projection.invoke_source_sha256,
    )
    real_output = resolve_python_target_structure(
        root,
        projection.output_digests_target,
        expected_source_sha256=projection.output_digests_source_sha256,
    )
    detached_invoke = replace(real_invoke, source_sha256="f" * 64)
    calls = iter((detached_invoke, real_output))

    monkeypatch.setattr(
        subject,
        "resolve_python_target_structure",
        lambda *args, **kwargs: next(calls),
    )

    with pytest.raises(ProviderExecutableStructureBindingError):
        subject.verify_provider_executable_structure(root, projection)
