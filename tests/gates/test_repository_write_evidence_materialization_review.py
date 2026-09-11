from __future__ import annotations

import ast
import inspect

import daedalus.gates.repository.write_evidence_materialization as materialization
from daedalus.gates.repository.write_classification import EvidenceKind


SOURCE = inspect.getsource(materialization)
TREE = ast.parse(SOURCE)


def _function(name: str) -> ast.FunctionDef:
    matches = [
        node
        for node in ast.walk(TREE)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(matches) == 1
    return matches[0]


def _call_name(call: ast.Call) -> str:
    target = call.func
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        parts = [target.attr]
        value = target.value
        while isinstance(value, ast.Attribute):
            parts.append(value.attr)
            value = value.value
        if isinstance(value, ast.Name):
            parts.append(value.id)
        return ".".join(reversed(parts))
    return ""


def test_module_is_read_only_and_has_no_effect_authority() -> None:
    imported_roots: set[str] = set()
    for node in ast.walk(TREE):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])
    assert imported_roots.isdisjoint(
        {
            "os",
            "pathlib",
            "shutil",
            "sqlite3",
            "socket",
            "subprocess",
            "tempfile",
            "urllib",
            "requests",
        }
    )

    forbidden_calls = {
        "open",
        "eval",
        "exec",
        "compile",
        "getattr",
        "setattr",
        "delattr",
        "importlib.import_module",
        "os.replace",
        "os.rename",
        "os.unlink",
        "subprocess.run",
        "subprocess.Popen",
    }
    calls = {_call_name(node) for node in ast.walk(TREE) if isinstance(node, ast.Call)}
    assert calls.isdisjoint(forbidden_calls)
    assert not any(name.endswith((".grant", ".begin", ".finish", ".promote")) for name in calls)


def test_public_materializer_accepts_no_callback_or_verifier_smuggling() -> None:
    function = _function("materialize_repository_write_evidence")
    assert [arg.arg for arg in function.args.args] == ["classification", "blobs"]
    assert function.args.vararg is None
    assert function.args.kwarg is None
    assert function.args.kwonlyargs == []
    forbidden = {"callback", "provider", "verifier", "authenticator", "issuer", "ledger"}
    assert forbidden.isdisjoint(arg.arg for arg in function.args.args)


def test_cas_digest_canonical_json_and_duplicate_key_fences_are_present() -> None:
    assert '^cas:sha256:([0-9a-f]{64})$' in SOURCE
    raw_hash = SOURCE.index("raw_sha256 = hashlib.sha256(raw).hexdigest()")
    raw_check = SOURCE.index("if raw_sha256 != binding.sha256")
    parse = SOURCE.index("document = json.loads(")
    canonical = SOURCE.index('canonical = canonical_json(document).encode("ascii")')
    payload_hash = SOURCE.index("payload_sha256 = hashlib.sha256(")
    semantic = SOURCE.index("_validate_payload(binding, payload)")
    assert raw_hash < raw_check < parse < canonical < payload_hash < semantic
    assert "evidence locator is reused across bindings" in SOURCE
    assert "evidence blob digest is reused across bindings" in SOURCE
    assert "unexpected evidence blob locators are present" in SOURCE


def test_every_evidence_kind_has_an_explicit_semantic_branch() -> None:
    function = _function("_validate_payload")
    attributes = {
        node.attr
        for node in ast.walk(function)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "EvidenceKind"
    }
    assert attributes == {kind.name for kind in EvidenceKind}
    assert "payload[\"conformant\"] is not True" in SOURCE
    assert "payload[\"disjoint\"] is not True" in SOURCE
    assert "payload[\"production_reachable\"] is not False" in SOURCE


def test_report_cannot_launder_empty_partial_or_materialized_bytes_into_trust() -> None:
    assert "return self.binding_count > 0 and not self.missing_locators" in SOURCE
    assert 'blockers.append("evidence-bindings-empty")' in SOURCE
    assert '"origin_authenticated": False' in SOURCE
    assert '"semantic_receipts_verified": False' in SOURCE
    assert '"evidence_authenticated": False' in SOURCE
    assert '"gate_report_bound": False' in SOURCE
    assert '"closed": False' in SOURCE
    assert '"content_addressed": True' in SOURCE
    assert '"canonical_bytes_verified": self.materialization_complete' in SOURCE
    assert '"binding_verified": self.materialization_complete' in SOURCE
    assert "parse_constant=_reject_nonfinite" in SOURCE
    assert "_MAX_EVIDENCE_BYTES = 1_048_576" in SOURCE


def test_materializer_does_not_mutate_gate_registry_or_promotion_state() -> None:
    assigned_attributes = {
        node.attr
        for node in ast.walk(TREE)
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store)
    }
    assert assigned_attributes.isdisjoint(
        {
            "ENTRYPOINTS",
            "GUARD_CONTRACT_IMPLEMENTED",
            "closed",
            "approved",
            "promoted",
            "merged",
        }
    )
    class_names = {
        node.name for node in TREE.body if isinstance(node, ast.ClassDef)
    }
    assert class_names == {
        "RepositoryWriteEvidenceMaterializationError",
        "MaterializedEvidenceRecord",
        "RepositoryWriteEvidenceMaterializationReport",
    }
