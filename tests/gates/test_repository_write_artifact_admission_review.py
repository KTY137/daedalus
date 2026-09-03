from __future__ import annotations

import ast
import inspect

import daedalus.gates.repository.write_artifact_admission as module


FORBIDDEN_IMPORT_ROOTS = {
    "git",
    "subprocess",
    "sqlite3",
    "socket",
    "requests",
    "urllib",
}
FORBIDDEN_CALL_NAMES = {
    "exec",
    "eval",
    "open",
    "compile",
    "system",
    "popen",
    "run",
    "check_call",
    "check_output",
    "merge",
    "promote",
    "issue_owner_approval",
}


def _tree() -> ast.Module:
    return ast.parse(inspect.getsource(module))


def _function(name: str) -> ast.FunctionDef:
    for node in _tree().body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing function: {name}")


def _call_name(node: ast.Call) -> str | None:
    target = node.func
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def test_module_has_no_process_network_database_or_git_authority() -> None:
    tree = _tree()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".", 1)[0] not in FORBIDDEN_IMPORT_ROOTS
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".", 1)[0] not in FORBIDDEN_IMPORT_ROOTS
        elif isinstance(node, ast.Call):
            assert _call_name(node) not in FORBIDDEN_CALL_NAMES


def test_public_admission_has_one_resolver_then_one_verifier_call() -> None:
    function = _function("admit_repository_write_artifact")
    calls = [
        (_call_name(node), node.lineno)
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
    ]
    resolver = [line for name, line in calls if name == "resolve_repository_write_artifact"]
    verifier = [line for name, line in calls if name == "verify_repository_write_artifact"]
    assert len(resolver) == 1
    assert len(verifier) == 1
    assert resolver[0] < verifier[0]


def test_verifier_consumes_only_resolver_content() -> None:
    function = _function("admit_repository_write_artifact")
    verifier_calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and _call_name(node) == "verify_repository_write_artifact"
    ]
    assert len(verifier_calls) == 1
    call = verifier_calls[0]
    assert len(call.args) == 3
    content = call.args[2]
    assert isinstance(content, ast.Attribute)
    assert isinstance(content.value, ast.Name)
    assert content.value.id == "resolved"
    assert content.attr == "content"


def test_public_signature_has_no_callback_or_loose_authority_channel() -> None:
    signature = inspect.signature(module.admit_repository_write_artifact)
    assert all(
        parameter.kind
        not in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD)
        for parameter in signature.parameters.values()
    )
    forbidden = {
        "callback",
        "provider",
        "artifact_bytes",
        "content",
        "resolution_receipt",
        "verification_receipt",
        "owner_approval",
        "promotion_receipt",
    }
    assert forbidden.isdisjoint(signature.parameters)


def test_receipt_construction_binds_both_predecessor_receipt_digests() -> None:
    function = _function("admit_repository_write_artifact")
    constructors = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and _call_name(node) == "RepositoryWriteArtifactAdmissionReceipt"
    ]
    assert len(constructors) == 1
    keywords = {keyword.arg: keyword.value for keyword in constructors[0].keywords}
    for field, subject in (
        ("resolution_receipt_sha256", "resolution"),
        ("verification_receipt_sha256", "verification"),
    ):
        value = keywords[field]
        assert isinstance(value, ast.Attribute)
        assert isinstance(value.value, ast.Name)
        assert value.value.id == subject
        assert value.attr == "digest"


def test_all_gate_release_and_execution_claims_remain_absent() -> None:
    source = inspect.getsource(module)
    forbidden_assignments = (
        "closed=True",
        "closed = True",
        "security_boundary_claimed=True",
        "security_boundary_claimed = True",
        "runtime_effect_authorized=True",
        "runtime_effect_authorized = True",
        "provider_execution_allowed=True",
        "provider_execution_allowed = True",
    )
    assert all(fragment not in source for fragment in forbidden_assignments)
    assert "OwnerApproval(" not in source
    assert "PromotionReceipt(" not in source
