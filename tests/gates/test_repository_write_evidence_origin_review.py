from __future__ import annotations

import ast
from pathlib import Path


TARGET = (
    Path(__file__).resolve().parents[2]
    / "daedalus/gates/repository_write_evidence_origin.py"
)
SOURCE = TARGET.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _function(name: str) -> ast.FunctionDef:
    for node in ast.walk(TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing function {name}")


def test_module_has_no_repository_runtime_or_process_authority() -> None:
    forbidden_import_roots = {
        "asyncio",
        "os",
        "pathlib",
        "shutil",
        "socket",
        "sqlite3",
        "subprocess",
        "tempfile",
    }
    imported: set[str] = set()
    for node in ast.walk(TREE):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", 1)[0])
    assert imported.isdisjoint(forbidden_import_roots)
    assert "promote_candidates" not in SOURCE
    assert "OwnerApproval" not in SOURCE
    assert "PromotionReceipt" not in SOURCE
    assert "EffectLeaseLedger" not in SOURCE
    assert "RuntimeConformanceReceipt" not in SOURCE
    assert "ENTRYPOINTS" not in SOURCE
    assert "REGISTRY_BY_ID" not in SOURCE


def test_public_authority_signatures_are_explicit_and_do_not_smuggle_callbacks() -> None:
    for name in (
        "issue_repository_write_evidence_origin_attestation",
        "verify_repository_write_evidence_origin",
    ):
        function = _function(name)
        assert function.args.vararg is None
        assert function.args.kwarg is None
        names = {
            argument.arg
            for argument in (
                function.args.posonlyargs
                + function.args.args
                + function.args.kwonlyargs
            )
        }
        assert not names.intersection(
            {
                "callback",
                "executor",
                "provider",
                "promoter",
                "verifier",
                "writer",
            }
        )


def test_verifier_authenticates_signature_before_live_projection() -> None:
    function = _function("verify_repository_write_evidence_origin")
    lines = {
        "signature": next(
            node.lineno
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "compare_digest"
        ),
        "projection": next(
            node.lineno
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_projection"
        ),
    }
    assert lines["signature"] < lines["projection"]


def test_parser_orders_size_encoding_parse_canonical_and_shape_fences() -> None:
    function = _function("parse_repository_write_evidence_origin_attestation")
    source = ast.get_source_segment(SOURCE, function)
    assert source is not None
    anchors = (
        "len(raw) > _MAX_ATTESTATION_BYTES",
        "raw.startswith",
        "json.loads",
        "raw != canonical",
        "RepositoryWriteEvidenceOriginAttestation.from_dict",
    )
    positions = [source.index(anchor) for anchor in anchors]
    assert positions == sorted(positions)


def test_report_never_escalates_semantic_gate_or_closure_authority() -> None:
    report_class = next(
        node
        for node in TREE.body
        if isinstance(node, ast.ClassDef)
        and node.name == "RepositoryWriteEvidenceOriginReport"
    )
    payload_function = next(
        node
        for node in report_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "_payload"
    )
    segment = ast.get_source_segment(SOURCE, payload_function)
    assert segment is not None
    assert '"origin_authenticated": True' in segment
    assert '"semantic_receipts_verified": False' in segment
    assert '"evidence_authenticated": False' in segment
    assert '"gate_report_bound": False' in segment
    assert '"closed": False' in segment


def test_signature_ttl_and_input_bounds_are_fixed() -> None:
    signature = _function("_signature")
    segment = ast.get_source_segment(SOURCE, signature)
    assert segment is not None
    assert "hmac.new" in segment
    assert "hashlib.sha256" in segment
    assert "_MAX_TTL = timedelta(hours=24)" in SOURCE
    assert "_MAX_ATTESTATION_BYTES = 1_048_576" in SOURCE


def test_module_has_no_file_network_database_or_effect_mutation_calls() -> None:
    forbidden_calls = {
        "connect",
        "open",
        "unlink",
        "write_bytes",
        "write_text",
        "mkdir",
        "run",
        "Popen",
        "grant",
        "begin",
        "finish",
        "promote",
        "merge",
    }
    observed = {
        node.func.attr
        for node in ast.walk(TREE)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
    }
    observed.update(
        node.func.id
        for node in ast.walk(TREE)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
    )
    assert observed.isdisjoint(forbidden_calls)


def test_exact_live_binding_comparisons_remain_explicit() -> None:
    expected = (
        '"collector_id": (attestation.collector_id, collector)',
        '"source_revision": (attestation.source_revision, revision)',
        '"materialization_source_revision": (',
        '"classification_digest": (',
        '"materialization_digest": (',
        '"binding_count": (',
        '"record_sha256s": (',
        '"blob_sha256s": (',
        '"payload_sha256s": (',
        '"record_set_sha256": (',
    )
    for anchor in expected:
        assert anchor in SOURCE
