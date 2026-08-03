from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXECUTOR = ROOT / "tests" / "fixtures" / "runtime_trust_contention_fault_executor.py"
SOURCE = EXECUTOR.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE, filename=str(EXECUTOR))


def _function(name: str) -> ast.FunctionDef:
    for node in TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing function {name}")


def _class(name: str) -> ast.ClassDef:
    for node in TREE.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"missing class {name}")


def _calls(name: str) -> list[ast.Call]:
    result: list[ast.Call] = []
    for node in ast.walk(TREE):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == name:
            result.append(node)
        elif isinstance(node.func, ast.Attribute) and node.func.attr == name:
            result.append(node)
    return result


def test_fixture_uses_one_production_broker_and_no_second_effect_launcher() -> None:
    assert len(_calls("run_runtime_provider")) == 1
    forbidden = {
        ("subprocess", "Popen"),
        ("subprocess", "run"),
        ("os", "system"),
        ("os", "popen"),
    }
    observed: set[tuple[str, str]] = set()
    for node in ast.walk(TREE):
        if not isinstance(node, ast.Call):
            continue
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
        ):
            observed.add((node.func.value.id, node.func.attr))
        for keyword in node.keywords:
            assert not (
                keyword.arg == "shell"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
            )
    assert not (observed & forbidden)
    assert "run_in_docker_sandbox" not in SOURCE


def test_bounded_trust_ledger_changes_only_connection_timeout() -> None:
    bounded = _class("BoundedRuntimeTrustLedger")
    methods = {
        node.name
        for node in bounded.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert methods == {"__init__", "_connect"}
    text = ast.get_source_segment(SOURCE, bounded) or ""
    required = (
        "super().__init__(path, integrity_key=integrity_key)",
        "isolation_level=None",
        "timeout=self.busy_timeout_ms / 1000",
        'connection.execute("PRAGMA foreign_keys=ON")',
        'connection.execute("PRAGMA journal_mode=WAL")',
        'connection.execute("PRAGMA synchronous=FULL")',
        "PRAGMA busy_timeout=",
        "except sqlite3.Error",
        "connection.close()",
    )
    for expression in required:
        assert expression in text


def test_fault_setup_seeds_one_authenticated_active_production_record() -> None:
    text = ast.get_source_segment(SOURCE, _function("_seed_active_record")) or ""
    required = (
        "trust_store_module._make_record",
        "integrity_key=ledger._integrity_key",
        'state="ACTIVE"',
        'reason=""',
        'connection.execute("BEGIN IMMEDIATE")',
        "ledger._insert(connection, record)",
        'connection.execute("COMMIT")',
    )
    for expression in required:
        assert expression in text
    assert "verify_production_runtime_envelope" not in SOURCE
    assert "trusted_envelope_sha256s" not in SOURCE


def test_provider_holds_writer_lock_before_returning_opaque_value() -> None:
    execute = ast.get_source_segment(
        SOURCE,
        _function("_execute_runtime_trust_contention"),
    ) or ""
    invoke_start = execute.index("def invoke()")
    output_start = execute.index("def output_digests", invoke_start)
    invoke = execute[invoke_start:output_start]
    assert 'blocker.execute("BEGIN IMMEDIATE")' in invoke
    assert "writer_lock_held = blocker.in_transaction" in invoke
    assert "return provider_output" in invoke
    assert invoke.index('blocker.execute("BEGIN IMMEDIATE")') < invoke.index(
        "return provider_output"
    )


def test_broker_error_is_caught_without_releasing_provider_value() -> None:
    execute = ast.get_source_segment(
        SOURCE,
        _function("_execute_runtime_trust_contention"),
    ) or ""
    required = (
        "except sqlite3.OperationalError as exc",
        "observed_error = exc",
        "result_released = True",
        "if blocker.in_transaction",
        'blocker.execute("ROLLBACK")',
        'terminal_state == "CANCELLED"',
        'terminal_outcome == "CANCELLED"',
        "terminal_outputs == []",
        "terminal_detail is not None",
        "not output_digest_called",
        "not result_released",
        'observed_outcome="cancelled"',
    )
    for expression in required:
        assert expression in execute
    assert execute.index("run_runtime_provider(") < execute.index(
        'blocker.execute("ROLLBACK")'
    )


def test_pass_requires_active_lock_full_timeout_and_unchanged_trust_record() -> None:
    execute = ast.get_source_segment(
        SOURCE,
        _function("_execute_runtime_trust_contention"),
    ) or ""
    required = (
        "writer_lock_held\n            and contention",
        "_BUSY_TIMEOUT_MS - _TIMEOUT_TOLERANCE_MS",
        "elapsed_ms < 5_000",
        "trust_record_still_active",
        "provider_output.encode(\"utf-8\") not in raw",
        "len(raw) <= _MAX_RAW_EVIDENCE_BYTES",
    )
    for expression in required:
        assert expression in execute


def test_sqlite_extended_codes_are_reduced_to_busy_or_locked_base() -> None:
    text = ast.get_source_segment(SOURCE, _function("_is_lock_contention")) or ""
    assert "code & 0xFF" in text
    assert 'str(exc).lower()' in text
    assert '"locked" in text or "busy" in text' in text
    payload = ast.get_source_segment(
        SOURCE,
        _function("_execute_runtime_trust_contention"),
    ) or ""
    assert '"exception_message"' not in payload


def test_raw_evidence_excludes_provider_value_plain_paths_and_exception_text() -> None:
    execute = ast.get_source_segment(
        SOURCE,
        _function("_execute_runtime_trust_contention"),
    ) or ""
    assert '"trust_database_path_sha256"' in execute
    assert '"effect_database_path_sha256"' in execute
    assert '"trust_database_path"' not in execute
    assert '"effect_database_path"' not in execute
    assert '"exception_module"' in execute
    assert '"exception_type"' in execute
    assert '"exception_message"' not in execute
    assert '"provider_output"' not in execute
    assert "provider_output.encode(\"utf-8\") not in raw" in execute


def test_implementation_identity_binds_all_production_authority_sources() -> None:
    text = ast.get_source_segment(SOURCE, _function("implementation_sha256")) or ""
    required = (
        "Path(__file__).resolve()",
        'broker_module, "production runtime broker"',
        'trust_store_module, "production runtime trust ledger"',
        'runtime_effects_module, "runtime effect authority"',
        'effects_module, "production effect ledger"',
        '"busy_timeout_ms": _BUSY_TIMEOUT_MS',
        '"timeout_tolerance_ms": _TIMEOUT_TOLERANCE_MS',
    )
    for expression in required:
        assert expression in text


def test_candidate_output_cannot_claim_trust_attestation_or_gate_closure() -> None:
    assert '"trusted": True' not in SOURCE
    assert '"attested": True' not in SOURCE
    assert '"gate_closure_claimed": True' not in SOURCE
    assert '"trusted": False' in SOURCE
    assert '"attested": False' in SOURCE
    assert '"gate_closure_claimed": False' in SOURCE


def test_only_operational_error_is_classified_as_the_expected_fault() -> None:
    execute = _function("_execute_runtime_trust_contention")
    handlers = [
        node for node in ast.walk(execute) if isinstance(node, ast.ExceptHandler)
    ]
    operational = [
        node
        for node in handlers
        if isinstance(node.type, ast.Attribute)
        and isinstance(node.type.value, ast.Name)
        and node.type.value.id == "sqlite3"
        and node.type.attr == "OperationalError"
    ]
    assert len(operational) == 1
    assert "except BaseException" not in (
        ast.get_source_segment(SOURCE, execute) or ""
    )
