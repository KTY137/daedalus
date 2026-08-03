from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXECUTOR = ROOT / "tests" / "fixtures" / "unknown_outcome_reconciliation_fault_executor.py"
RECOVERY = ROOT / "daedalus" / "kernel" / "effect_recovery.py"
SOURCE = EXECUTOR.read_text(encoding="utf-8")
RECOVERY_SOURCE = RECOVERY.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE, filename=str(EXECUTOR))
RECOVERY_TREE = ast.parse(RECOVERY_SOURCE, filename=str(RECOVERY))


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing function {name}")


def _class(tree: ast.Module, name: str) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"missing class {name}")


def test_crash_worker_commits_one_unique_ack_then_exits_without_terminal_access() -> None:
    worker = ast.get_source_segment(SOURCE, _function(TREE, "_crash_worker")) or ""
    required = (
        'connection.execute("BEGIN IMMEDIATE")',
        "WHERE idempotency_key=?",
        "external idempotency key already exists",
        "INSERT INTO external_effects",
        'connection.execute("COMMIT")',
        "os._exit(_CRASH_RETURN_CODE)",
    )
    for expression in required:
        assert expression in worker
    assert worker.index('connection.execute("COMMIT")') < worker.index(
        "os._exit(_CRASH_RETURN_CODE)"
    )
    assert "EffectLeaseLedger" not in worker
    assert "finish_effect" not in worker
    assert "reconcile_unknown_effect" not in worker


def test_parent_persists_start_before_crash_and_never_reinvokes_worker() -> None:
    execute = ast.get_source_segment(SOURCE, _function(TREE, "_execute")) or ""
    start = execute.index("start = authorization.begin_effect(execution)")
    worker = execute.index("worker = subprocess.run(")
    observation = execute.index("observation = issue_external_effect_observation(")
    recovery = execute.index("first = reconcile_unknown_effect(")
    replay = execute.index("replay = authorization.begin_effect(execution)")
    assert start < worker < observation < recovery < replay
    assert len(
        [
            node
            for node in ast.walk(_function(TREE, "_execute"))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "run"
        ]
    ) == 1


def test_observation_is_hmac_authenticated_and_exactly_bound() -> None:
    value = _class(RECOVERY_TREE, "ExternalEffectObservation")
    text = ast.get_source_segment(RECOVERY_SOURCE, value) or ""
    required = (
        "observation_id",
        "provider_id",
        "execution_id",
        "idempotency_key",
        "start_receipt_sha256",
        "acknowledgement_sha256",
        "output_digests",
        "issuer_key_id",
        "observed_at",
        "signature_sha256",
        "provenance",
        'body["signature_sha256"] = "0" * 64',
        "tuple(self.provenance.input_digests) != required",
        "exactly the retained evidence digests",
    )
    for expression in required:
        assert expression in text
    assert "issubset" not in text

    verify = ast.get_source_segment(
        RECOVERY_SOURCE,
        _function(RECOVERY_TREE, "verify_external_effect_observation"),
    ) or ""
    for expression in (
        "hmac.compare_digest",
        'raise EffectRecoverySignatureError("recovery observation signature mismatch")',
        '"provider_id"',
        '"execution_id"',
        '"idempotency_key"',
        '"start_receipt_sha256"',
        '"source_revision"',
        "recovery observation is from the future",
        "recovery observation is stale",
    ):
        assert expression in verify


def test_start_binding_and_acknowledgement_causality_are_checked_twice() -> None:
    binding = ast.get_source_segment(
        RECOVERY_SOURCE,
        _function(RECOVERY_TREE, "_validate_start_binding"),
    ) or ""
    for expression in (
        "start_receipt.execution_id",
        "execution.execution_id",
        "start_receipt.idempotency_key",
        "execution.idempotency_key",
        "start_receipt.execution_request_sha256",
        "execution.digest",
        "start_receipt.started_at",
    ):
        assert expression in binding

    issue = ast.get_source_segment(
        RECOVERY_SOURCE,
        _function(RECOVERY_TREE, "issue_external_effect_observation"),
    ) or ""
    verify = ast.get_source_segment(
        RECOVERY_SOURCE,
        _function(RECOVERY_TREE, "verify_external_effect_observation"),
    ) or ""
    for text in (issue, verify):
        assert "_validate_start_binding(execution, start_receipt)" in text
        assert "external acknowledgement predates the durable effect start" in text


def test_recovery_can_only_complete_started_execution_under_exact_observation() -> None:
    reconcile = ast.get_source_segment(
        RECOVERY_SOURCE,
        _function(RECOVERY_TREE, "reconcile_unknown_effect"),
    ) or ""
    required = (
        "verify_external_effect_observation(",
        'if state == "STARTED"',
        'outcome="COMPLETED"',
        "output_digests=observation.output_digests",
        "detail_sha256=observation.digest",
        "except EffectLeaseStateError",
        "receipt is not None and _matches(",
        "execution is terminal under different recovery evidence",
    )
    for expression in required:
        assert expression in reconcile
    match = ast.get_source_segment(
        RECOVERY_SOURCE,
        _function(RECOVERY_TREE, "_matches"),
    ) or ""
    for expression in (
        "receipt.lease_sha256 == start_receipt.lease_sha256",
        "receipt.execution_id == start_receipt.execution_id",
        "receipt.start_receipt_sha256 == start_receipt.receipt_sha256",
        'receipt.outcome == "COMPLETED"',
        "receipt.output_digests == observation.output_digests",
        "receipt.detail_sha256 == observation.digest",
    ):
        assert expression in match


def test_persisted_terminal_parser_is_duplicate_rejecting_exact_and_digest_bound() -> None:
    parser = ast.get_source_segment(
        RECOVERY_SOURCE,
        _function(RECOVERY_TREE, "_terminal_from_row"),
    ) or ""
    required = (
        "object_pairs_hook=_strict_object",
        "parse_constant=",
        "set(payload) != _TERMINAL_FIELDS",
        "terminal output digests are not canonical",
        "canonical_sha(body) != claimed",
        "terminal receipt index mismatch",
        "terminal state and receipt disagree",
    )
    for expression in required:
        assert expression in parser


def test_pass_requires_real_crash_started_state_one_external_row_and_inert_replay() -> None:
    execute = ast.get_source_segment(SOURCE, _function(TREE, "_execute")) or ""
    required = (
        "worker.returncode == _CRASH_RETURN_CODE",
        'state_after_crash == "STARTED"',
        "external_count_after_crash == 1",
        "first.reconciled is True",
        "second.reconciled is False",
        "first.terminal_receipt == second.terminal_receipt",
        'first.terminal_receipt.outcome == "COMPLETED"',
        "first.terminal_receipt.detail_sha256 == observation.digest",
        'final_state == "COMPLETED"',
        "replay.execute is False",
        "replay.receipt == start.receipt",
        "external_count_after_recovery == 1",
        "output_value.encode(\"utf-8\") not in raw",
    )
    for expression in required:
        assert expression in execute


def test_evidence_excludes_output_plain_paths_and_child_output_text() -> None:
    execute = ast.get_source_segment(SOURCE, _function(TREE, "_execute")) or ""
    assert '"effect_database_path_sha256"' in execute
    assert '"external_database_path_sha256"' in execute
    assert '"effect_database_path"' not in execute
    assert '"external_database_path"' not in execute
    assert '"worker_stdout_sha256"' in execute
    assert '"worker_stderr_sha256"' in execute
    assert '"worker_stdout"' not in execute
    assert '"worker_stderr"' not in execute
    assert '"output_value"' not in execute
    assert "output_value.encode(\"utf-8\") not in raw" in execute


def test_implementation_identity_binds_recovery_and_effect_sources() -> None:
    identity = ast.get_source_segment(
        SOURCE,
        _function(TREE, "implementation_sha256"),
    ) or ""
    for expression in (
        "Path(__file__).resolve()",
        '_module_path(recovery_module, "effect recovery")',
        '_module_path(effects_module, "effect ledger")',
        '"crash_return_code": _CRASH_RETURN_CODE',
    ):
        assert expression in identity


def test_candidate_output_cannot_claim_trust_attestation_or_gate_closure() -> None:
    assert '"trusted": True' not in SOURCE
    assert '"attested": True' not in SOURCE
    assert '"gate_closure_claimed": True' not in SOURCE
    assert '"trusted": False' in SOURCE
    assert '"attested": False' in SOURCE
    assert '"gate_closure_claimed": False' in SOURCE
