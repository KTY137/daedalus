from __future__ import annotations

import ast
import dataclasses
import inspect

import daedalus.runtimes.provider.invocation_identity as identity


def test_identity_projection_module_has_no_execution_or_effect_authority() -> None:
    source = inspect.getsource(identity)
    tree = ast.parse(source)
    forbidden_import_roots = {
        "asyncio",
        "httpx",
        "importlib",
        "requests",
        "socket",
        "sqlite3",
        "subprocess",
        "tempfile",
        "urllib",
    }
    imported: set[str] = set()
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called.add(node.func.attr)
    assert imported.isdisjoint(forbidden_import_roots)
    assert {
        "exec",
        "eval",
        "compile",
        "open",
        "system",
        "popen",
        "run",
        "Popen",
        "grant",
        "begin_effect",
        "finish_effect",
    }.isdisjoint(called)
    assert "Callable" not in source
    assert "invoke(" not in source
    assert "output_digests" not in source


def test_projection_permanently_denies_effect_and_provider_execution() -> None:
    source = inspect.getsource(
        identity.ProviderInvocationIdentityProjection.to_dict
    )
    assert '"runtime_effect_authorized": False' in source
    assert '"provider_execution_allowed": False' in source

    fields = {
        field.name
        for field in dataclasses.fields(
            identity.ProviderInvocationIdentityProjection
        )
    }
    assert "runtime_effect_authorized" not in fields
    assert "provider_execution_allowed" not in fields


def test_authentication_precedes_registry_resolution() -> None:
    source = inspect.getsource(identity.project_provider_invocation_identity)
    authenticate = source.index(
        "verify_provider_invocation_observation_authority("
    )
    revision_check = source.index(
        "registry.source_revision != subject.source_revision"
    )
    resolve = source.index("registry.resolve(subject)")
    assert authenticate < revision_check < resolve


def test_expected_contract_and_live_registry_digest_are_not_authority_derived() -> None:
    source = inspect.getsource(identity.project_provider_invocation_identity)
    assert (
        "invocation_contract_id=PROVIDER_INVOCATION_CONTRACT_ID"
        in source
    )
    assert "invocation_registry_sha256=registry.digest" in source
    assert (
        "invocation_contract_id=authority.invocation_contract_id"
        not in source
    )
    assert (
        "invocation_registry_sha256=authority.invocation_registry_sha256"
        not in source
    )


def test_projection_binds_every_identity_and_evidence_dimension() -> None:
    source = inspect.getsource(identity.project_provider_invocation_identity)
    for binding in (
        "provider_id=descriptor.provider_id",
        "adapter_id=descriptor.adapter_id",
        "implementation_id=descriptor.implementation_id",
        "entrypoint_id=descriptor.entrypoint_id",
        "runtime_id=descriptor.runtime_id",
        "execution_id=subject.execution_id",
        "idempotency_key=subject.idempotency_key",
        "source_revision=subject.source_revision",
        "authority_sha256=authority.digest",
        "observation_authority_sha256=authority.observation_authority.digest",
        "invocation_contract_sha256=authority.invocation_contract_sha256",
        "invocation_subject_sha256=subject.digest",
        "registry_sha256=registry.digest",
        "descriptor_sha256=descriptor.digest",
        "execution_request_sha256=execution.digest",
        "lease_sha256=subject.lease_sha256",
        "adapter_artifact_sha256=descriptor.adapter_artifact_sha256",
        "adapter_config_sha256=descriptor.adapter_config_sha256",
    ):
        assert binding in source


def test_module_claims_no_gate_promotion_or_trust_completion() -> None:
    source = inspect.getsource(identity).lower()
    forbidden_claims = (
        "closed = true",
        '"closed": true',
        "trusted = true",
        '"trusted": true',
        "ownerapproval(",
        "promotionreceipt(",
        "merge_pull_request",
    )
    assert all(claim not in source for claim in forbidden_claims)
