from __future__ import annotations

import ast
import inspect
from pathlib import Path

import daedalus.runtimes.provider_invocation_authority as authority_module


SOURCE_PATH = Path(inspect.getsourcefile(authority_module) or "")
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


def test_composite_authority_module_is_nonexecuting() -> None:
    forbidden_imports = {
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
    assert "Callable" not in SOURCE
    assert "invoke(" not in SOURCE
    assert "run_runtime_provider" not in SOURCE
    assert "begin_effect" not in SOURCE
    assert "sqlite3" not in SOURCE
    assert "OwnerApproval" not in SOURCE
    assert "PromotionReceipt" not in SOURCE


def test_exact_nested_types_and_shared_subject_checks_are_constructor_invariants() -> None:
    cls = _definition("ProviderInvocationObservationAuthority")
    constructor = next(
        node
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == "__post_init__"
    )
    source = ast.get_source_segment(SOURCE, constructor) or ""
    assert "type(self.observation_authority) is not ProviderObservationAuthority" in source
    assert "type(self.invocation_subject) is not ProviderInvocationSubject" in source
    assert "_subject_mismatches" in _calls(constructor)

    matcher = _definition("_subject_mismatches")
    matcher_source = ast.get_source_segment(SOURCE, matcher) or ""
    for field in (
        "provider_id",
        "entrypoint_id",
        "runtime_id",
        "execution_id",
        "idempotency_key",
        "execution_request_sha256",
        "lease_sha256",
        "source_revision",
    ):
        assert field in matcher_source


def test_signature_covers_nested_authorities_and_registry_contract() -> None:
    cls = _definition("ProviderInvocationObservationAuthority")
    to_dict = next(
        node
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == "to_dict"
    )
    to_dict_source = ast.get_source_segment(SOURCE, to_dict) or ""
    assert "observation_authority.to_dict" in to_dict_source
    assert "invocation_subject.to_dict" in to_dict_source
    assert "invocation_contract_id" in to_dict_source
    assert "invocation_registry_sha256" in to_dict_source

    signing = next(
        node
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == "signing_digest"
    )
    signing_source = ast.get_source_segment(SOURCE, signing) or ""
    assert "self.to_dict" in signing_source
    assert 'body["signature_sha256"] = "0" * 64' in signing_source
    assert "canonical_sha" in _calls(signing)

    contract = next(
        node
        for node in cls.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "invocation_contract_sha256"
    )
    contract_source = ast.get_source_segment(SOURCE, contract) or ""
    assert "invocation_subject.digest" in contract_source
    assert "invocation_registry_sha256" in contract_source
    assert "invocation_contract_id" in contract_source


def test_verification_authenticates_nested_observation_before_composite_signature() -> None:
    verifier = _definition("verify_provider_invocation_observation_authority")
    calls = [
        node
        for node in ast.walk(verifier)
        if isinstance(node, ast.Call)
    ]
    nested_line = min(
        node.lineno
        for node in calls
        if _call_name(node) == "verify_provider_observation_authority"
    )
    signature_line = min(
        node.lineno
        for node in calls
        if _call_name(node) == "_signature"
    )
    compare_line = min(
        node.lineno
        for node in calls
        if _call_name(node) == "hmac.compare_digest"
    )
    assert nested_line < signature_line < compare_line

    verifier_source = ast.get_source_segment(SOURCE, verifier) or ""
    assert "_normalize_keyring" in _calls(verifier)
    assert "authority.invocation_subject" in verifier_source
    assert "authority.invocation_contract_id" in verifier_source
    assert "authority.invocation_registry_sha256" in verifier_source
    assert "type(authority) is not ProviderInvocationObservationAuthority" in verifier_source


def test_deserialization_has_exact_outer_and_nested_shapes() -> None:
    cls = _definition("ProviderInvocationObservationAuthority")
    from_dict = next(
        node
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == "from_dict"
    )
    source = ast.get_source_segment(SOURCE, from_dict) or ""
    assert "set(payload) != expected" in source
    assert "ProviderObservationAuthority.from_dict" in source
    assert "ProviderInvocationSubject.from_dict" in source
    assert "isinstance(observation, Mapping)" in source
    assert "isinstance(invocation, Mapping)" in source


def test_public_exports_do_not_expose_signing_or_secret_helpers() -> None:
    exported = set(authority_module.__all__)
    assert "_signature" not in exported
    assert "_secret_bytes" not in exported
    assert "_normalize_keyring" not in exported
    assert exported == {
        "ProviderInvocationAuthorityBindingError",
        "ProviderInvocationAuthorityError",
        "ProviderInvocationAuthoritySignatureError",
        "ProviderInvocationObservationAuthority",
        "issue_provider_invocation_observation_authority",
        "verify_provider_invocation_observation_authority",
    }
