from __future__ import annotations

import ast
import inspect
from pathlib import Path

import daedalus.runtimes.provider_invocation_resolution as resolution_module


SOURCE_PATH = Path(inspect.getsourcefile(resolution_module) or "")
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


def test_resolution_module_has_no_execution_persistence_or_promotion_authority() -> None:
    forbidden_imports = {
        "subprocess",
        "socket",
        "requests",
        "urllib",
        "httpx",
        "aiohttp",
        "importlib",
        "ctypes",
        "sqlite3",
        "os",
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
    assert "Callable" not in SOURCE
    assert "invoke(" not in SOURCE
    assert "exec(" not in SOURCE
    assert "eval(" not in SOURCE
    assert "begin_effect" not in SOURCE
    assert "OwnerApproval" not in SOURCE
    assert "PromotionReceipt" not in SOURCE


def test_resolution_verifies_manifest_digest_before_signed_authority_and_resolution() -> None:
    resolver = _definition("resolve_provider_invocation_authority")
    source = ast.get_source_segment(SOURCE, resolver) or ""
    assert "type(authority) is not ProviderInvocationObservationAuthority" in source
    assert "type(manifest) is not ProviderInvocationRegistryManifest" in source
    assert "type(execution) is not EffectExecutionRequest" in source
    assert "manifest.source_revision != expected_revision" in source
    assert "authority.invocation_registry_sha256 != manifest.digest" in source

    calls = [node for node in ast.walk(resolver) if isinstance(node, ast.Call)]
    verify_line = min(
        node.lineno
        for node in calls
        if _call_name(node)
        == "verify_provider_invocation_observation_authority"
    )
    resolve_line = min(
        node.lineno
        for node in calls
        if _call_name(node) == "manifest.resolve"
    )
    receipt_line = min(
        node.lineno for node in calls if _call_name(node) == "_receipt_for"
    )
    assert verify_line < resolve_line < receipt_line


def test_receipt_binds_all_runtime_registry_and_effect_subject_digests() -> None:
    receipt_for = _definition("_receipt_for")
    source = ast.get_source_segment(SOURCE, receipt_for) or ""
    for field in (
        "manifest.registry_id",
        "manifest.digest",
        "manifest.source_revision",
        "authority.digest",
        "authority.observation_authority.digest",
        "authority.invocation_contract_id",
        "authority.invocation_contract_sha256",
        "subject.digest",
        "descriptor.digest",
        "descriptor.provider_id",
        "descriptor.adapter_id",
        "descriptor.implementation_id",
        "descriptor.adapter_artifact_sha256",
        "descriptor.adapter_config_sha256",
        "descriptor.entrypoint_id",
        "descriptor.runtime_id",
        "subject.execution_id",
        "subject.idempotency_key",
        "subject.execution_request_sha256",
        "subject.lease_sha256",
    ):
        assert field in source
    assert "canonical_sha" in _calls(receipt_for)


def test_receipt_constructor_recomputes_digest_and_parser_is_exact() -> None:
    cls = _definition("ProviderInvocationResolutionReceipt")
    constructor = next(
        node
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == "__post_init__"
    )
    source = ast.get_source_segment(SOURCE, constructor) or ""
    assert "canonical_sha" in _calls(constructor)
    assert "self.unsigned_dict" in _calls(constructor)
    assert "self.receipt_sha256 != expected" in source

    parser = next(
        node
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == "from_dict"
    )
    parser_source = ast.get_source_segment(SOURCE, parser) or ""
    assert "set(payload) != expected" in parser_source
    assert "descriptor_sha256" in parser_source
    assert "implementation_id" in parser_source
    assert "observation_authority_sha256" in parser_source


def test_receipt_reverification_derives_descriptor_instead_of_accepting_one() -> None:
    verifier = _definition("verify_provider_invocation_resolution_receipt")
    source = ast.get_source_segment(SOURCE, verifier) or ""
    arguments = [argument.arg for argument in verifier.args.args]
    keyword_only = [argument.arg for argument in verifier.args.kwonlyargs]
    assert "descriptor" not in arguments + keyword_only
    assert "authority.invocation_registry_sha256 != manifest.digest" in source
    assert "manifest.resolve" in _calls(verifier)
    assert "_receipt_for" in _calls(verifier)
    assert "receipt != expected" in source


def test_resolution_time_is_timezone_aware_and_canonical() -> None:
    canonical = _definition("_canonical_at")
    source = ast.get_source_segment(SOURCE, canonical) or ""
    assert "isinstance(value, datetime)" in source
    assert "value.tzinfo is None" in source
    assert "value.utcoffset() is None" in source
    assert "value.astimezone" in _calls(canonical)
    assert "_utc_timestamp" in _calls(canonical)


def test_public_surface_is_receipt_and_read_only_resolution_only() -> None:
    assert set(resolution_module.__all__) == {
        "ProviderInvocationResolutionAuthenticationError",
        "ProviderInvocationResolutionBindingError",
        "ProviderInvocationResolutionError",
        "ProviderInvocationResolutionReceipt",
        "resolve_provider_invocation_authority",
        "verify_provider_invocation_resolution_receipt",
    }
