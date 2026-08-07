from __future__ import annotations

import ast
import inspect
from pathlib import Path

import daedalus.runtimes.provider_observation_store_contract as contract_module


SOURCE_PATH = Path(inspect.getsourcefile(contract_module) or "")
SOURCE = SOURCE_PATH.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _definition(name: str):
    matches = [
        node
        for node in ast.walk(TREE)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.name == name
    ]
    assert len(matches) == 1, name
    return matches[0]


def _call_name(call: ast.Call) -> str:
    parts: list[str] = []
    node: ast.AST = call.func
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _calls(node: ast.AST) -> tuple[str, ...]:
    return tuple(
        _call_name(item)
        for item in ast.walk(node)
        if isinstance(item, ast.Call)
    )


def test_contract_module_has_no_store_effect_or_promotion_authority() -> None:
    forbidden_imports = {
        "sqlite3",
        "os",
        "subprocess",
        "socket",
        "requests",
        "urllib",
        "httpx",
        "aiohttp",
        "importlib",
        "ctypes",
    }
    imports = {
        alias.name
        for node in TREE.body
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_from = {
        node.module or ""
        for node in TREE.body
        if isinstance(node, ast.ImportFrom)
    }
    assert not (imports | imported_from) & forbidden_imports
    assert "sqlite3.connect" not in SOURCE
    assert "initialize_provider_observation_binding_store" not in SOURCE
    assert "bind_start(" not in SOURCE
    assert "begin_effect(" not in SOURCE
    assert "EffectLeaseLedger" not in SOURCE
    assert "OwnerApproval" not in SOURCE
    assert "PromotionReceipt" not in SOURCE


def test_operation_to_entrypoint_mapping_is_closed_and_exact() -> None:
    assert contract_module._ENTRYPOINT_BY_OPERATION == {
        "initialize-store": "provider.observation-store.initialize",
        "bind-provider-start": "provider.observation-store.bind-start",
    }

    subject = _definition("ProviderObservationStoreOperationSubject")
    constructor = next(
        node
        for node in subject.body
        if isinstance(node, ast.FunctionDef) and node.name == "__post_init__"
    )
    source = ast.get_source_segment(SOURCE, constructor) or ""
    assert "self.operation not in _ENTRYPOINT_BY_OPERATION" in source
    assert "self.entrypoint_id != expected_entrypoint" in source


def test_store_write_subject_binds_exact_local_effect_lease_and_revision() -> None:
    validator = _definition("_validate_store_write_subjects")
    source = ast.get_source_segment(SOURCE, validator) or ""
    assert "type(target) is not ProviderObservationStoreTarget" in source
    assert "type(execution) is not EffectExecutionRequest" in source
    assert "type(effect_lease) is not EffectLease" in source
    for field in (
        "effect_lease.entrypoint_id",
        "effect_lease.requested_effects",
        "execution.requested_effects",
        "effect_lease.provenance.source_revision",
        "target.source_revision",
        "execution.kill_switch_generation",
        "effect_lease.kill_switch_generation",
        "effect_lease.runtime_id",
        "effect_lease.runtime_manifest_sha256",
        "effect_lease.runtime_conformance_sha256",
        "execution.writable_paths",
        "execution.egress_endpoints",
        "execution.tools",
        "execution.secret_refs",
        "execution.max_cost_microusd",
    ):
        assert field in source


def test_bind_operation_requires_complete_provider_authority_and_start_receipt() -> None:
    builder = _definition("build_provider_observation_store_operation_subject")
    source = ast.get_source_segment(SOURCE, builder) or ""
    assert "type(provider_observation_authority) is not ProviderObservationAuthority" in source
    assert "type(provider_start_receipt) is not LeasedEffectStartReceipt" in source
    assert "provider_observation_authority.source_revision != target.source_revision" in source
    assert "_validate_start_receipt" in _calls(builder)
    assert "provider_observation_authority.digest" in source
    assert "provider_start_receipt.receipt_sha256" in source
    assert "_sha256" in _calls(builder)

    receipt_validator = _definition("_validate_start_receipt")
    receipt_source = ast.get_source_segment(SOURCE, receipt_validator) or ""
    assert "canonical_sha" in _calls(receipt_validator)
    for field in (
        "lease_sha256",
        "execution_id",
        "idempotency_key",
        "execution_request_sha256",
        "boundary_receipt_sha256",
        "started_at",
    ):
        assert field in receipt_source
    assert "receipt.receipt_sha256 != canonical_sha(expected_body)" in receipt_source


def test_authority_signature_covers_complete_subject_and_short_ttl() -> None:
    authority = _definition("ProviderObservationStoreOperationAuthority")
    to_dict = next(
        node
        for node in authority.body
        if isinstance(node, ast.FunctionDef) and node.name == "to_dict"
    )
    source = ast.get_source_segment(SOURCE, to_dict) or ""
    assert "self.subject.to_dict" in source
    assert "nonce" in source
    assert "issued_at" in source
    assert "expires_at" in source

    signing = next(
        node
        for node in authority.body
        if isinstance(node, ast.FunctionDef) and node.name == "signing_digest"
    )
    signing_source = ast.get_source_segment(SOURCE, signing) or ""
    assert "self.to_dict" in _calls(signing)
    assert 'body["signature_sha256"] = "0" * 64' in signing_source
    assert "canonical_sha" in _calls(signing)

    constructor = next(
        node
        for node in authority.body
        if isinstance(node, ast.FunctionDef) and node.name == "__post_init__"
    )
    constructor_source = ast.get_source_segment(SOURCE, constructor) or ""
    assert "expires <= issued" in constructor_source
    assert "expires - issued > _MAX_AUTHORITY_TTL" in constructor_source


def test_verifier_authenticates_before_time_and_subject_comparison() -> None:
    verifier = _definition("verify_provider_observation_store_operation_authority")
    calls = [node for node in ast.walk(verifier) if isinstance(node, ast.Call)]
    signature_line = min(
        node.lineno for node in calls if _call_name(node) == "_signature"
    )
    compare_line = min(
        node.lineno
        for node in calls
        if _call_name(node) == "hmac.compare_digest"
    )
    utc_line = min(
        node.lineno for node in calls if _call_name(node) == "_as_utc"
    )
    assert signature_line < compare_line < utc_line

    source = ast.get_source_segment(SOURCE, verifier) or ""
    assert "type(authority) is not ProviderObservationStoreOperationAuthority" in source
    assert "type(expected_subject) is not ProviderObservationStoreOperationSubject" in source
    assert "_normalized_keyring" in _calls(verifier)
    assert "authority.authority_id" in source
    assert "authority.subject" in source
    assert "instant < issued or instant >= expires" in source


def test_guard_decision_is_emitted_only_after_exact_verification() -> None:
    authorizer = _definition("authorize_provider_observation_store_operation")
    calls = [node for node in ast.walk(authorizer) if isinstance(node, ast.Call)]
    verify_line = min(
        node.lineno
        for node in calls
        if _call_name(node)
        == "verify_provider_observation_store_operation_authority"
    )
    decision_line = min(
        node.lineno for node in calls if _call_name(node) == "GuardDecision"
    )
    assert verify_line < decision_line
    source = ast.get_source_segment(SOURCE, authorizer) or ""
    assert "contract=STORE_GUARD_CONTRACT" in source
    assert "allowed=True" in source
    assert "authority.digest" in source
    assert "expected_subject.digest" in source


def test_public_surface_exposes_no_secret_or_signature_helper() -> None:
    exported = set(contract_module.__all__)
    assert "_signature" not in exported
    assert "_secret_bytes" not in exported
    assert "_normalized_keyring" not in exported
    assert "_validate_start_receipt" not in exported
    assert "_validate_store_write_subjects" not in exported
    assert exported == {
        "BIND_PROVIDER_START",
        "INITIALIZE_STORE",
        "STORE_GUARD_CONTRACT",
        "ProviderObservationStoreContractBindingError",
        "ProviderObservationStoreContractError",
        "ProviderObservationStoreContractExpired",
        "ProviderObservationStoreContractSignatureError",
        "ProviderObservationStoreOperationAuthority",
        "ProviderObservationStoreOperationSubject",
        "authorize_provider_observation_store_operation",
        "build_provider_observation_store_operation_subject",
        "issue_provider_observation_store_operation_authority",
        "verify_provider_observation_store_operation_authority",
    }
