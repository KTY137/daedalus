from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXECUTOR = (
    ROOT / "tests" / "fixtures" / "runtime_trust_contention_fault_executor.py"
)
BROKER = ROOT / "daedalus" / "runtimes" / "broker.py"
EXECUTOR_SOURCE = EXECUTOR.read_text(encoding="utf-8")
BROKER_SOURCE = BROKER.read_text(encoding="utf-8")
EXECUTOR_TREE = ast.parse(EXECUTOR_SOURCE)
BROKER_TREE = ast.parse(BROKER_SOURCE)


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


def _method(class_node: ast.ClassDef, name: str) -> ast.FunctionDef:
    for node in class_node.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing method {class_node.name}.{name}")


def test_production_broker_converts_sqlite_fence_errors_before_output_return() -> None:
    function = _function(BROKER_TREE, "_finish_completed_under_runtime_fence")
    text = ast.get_source_segment(BROKER_SOURCE, function) or ""
    required = (
        "except sqlite3.Error as exc",
        "RuntimeProviderTrustFenceError",
        "runtime trust terminal fence SQLite operation failed",
        "_rollback_runtime_fence(connection)",
        "connection.close()",
    )
    for expression in required:
        assert expression in text
    assert text.index("except sqlite3.Error as exc") < text.index("except BaseException")

    connect_try = text.index("connection = ledger._connect()")
    connect_error = text.index("except sqlite3.Error as exc", connect_try)
    begin = text.index('connection.execute("BEGIN IMMEDIATE")')
    assert connect_try < connect_error < begin
    assert "could not open its SQLite authority" in text[connect_try:begin]


def test_production_broker_cancels_only_trust_fence_classification() -> None:
    function = _function(BROKER_TREE, "run_runtime_provider")
    text = ast.get_source_segment(BROKER_SOURCE, function) or ""
    catch = text.index("except RuntimeProviderTrustFenceError as exc")
    returned = text.index("return RuntimeInvocationResult", catch)
    block = text[catch:returned]
    assert "_cancel_for_trust_loss" in block
    assert 'phase="terminal-runtime-fence"' in block
    assert "raise" in block
    assert "RuntimeProviderStateError" not in block


def test_sqlite_rollback_swallow_is_narrow_and_cannot_replace_original_failure() -> None:
    function = _function(BROKER_TREE, "_rollback_runtime_fence")
    text = ast.get_source_segment(BROKER_SOURCE, function) or ""
    assert "if not connection.in_transaction" in text
    assert 'connection.execute("ROLLBACK")' in text
    handlers = [node for node in ast.walk(function) if isinstance(node, ast.ExceptHandler)]
    assert len(handlers) == 1
    handler = handlers[0]
    assert handler.type is not None
    assert ast.get_source_segment(BROKER_SOURCE, handler.type) == "BaseException"
    assert len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass)


def test_test_ledger_subclass_changes_only_timeout_connect_seam() -> None:
    class_node = _class(EXECUTOR_TREE, "BoundedRuntimeTrustLedger")
    method_names = {
        node.name for node in class_node.body if isinstance(node, ast.FunctionDef)
    }
    assert method_names == {"__init__", "_connect"}
    connect = _method(class_node, "_connect")
    text = ast.get_source_segment(EXECUTOR_SOURCE, connect) or ""
    required = (
        "sqlite3.connect",
        "isolation_level=None",
        "timeout=self._fault_busy_timeout_ms / 1000",
        "PRAGMA foreign_keys=ON",
        "PRAGMA journal_mode=WAL",
        "PRAGMA synchronous=FULL",
        "PRAGMA busy_timeout=",
    )
    for expression in required:
        assert expression in text


def test_fixture_uses_real_broker_real_trust_lookup_and_real_sqlite_writer_lock() -> None:
    class_node = _class(EXECUTOR_TREE, "RuntimeTrustContentionAuthorization")
    verify = _method(class_node, "verify")
    verify_text = ast.get_source_segment(EXECUTOR_SOURCE, verify) or ""
    required = (
        "self.runtime_trust_ledger.require_active",
        "if self.verify_calls == 2",
        "sqlite3.connect",
        'writer.execute("BEGIN IMMEDIATE")',
        "self._writer = writer",
    )
    for expression in required:
        assert expression in verify_text

    execute = _function(EXECUTOR_TREE, "_execute_runtime_trust_contention")
    execute_text = ast.get_source_segment(EXECUTOR_SOURCE, execute) or ""
    assert "run_runtime_provider(" in execute_text
    assert "authorization.release_writer()" in execute_text
    assert "ledger.require_active(" in execute_text
    assert "RuntimeProviderTrustFenceError" in execute_text
    assert "sqlite3.OperationalError" in execute_text


def test_fixture_seed_is_local_setup_not_an_admission_or_trust_claim() -> None:
    seed = _function(EXECUTOR_TREE, "_seed_record")
    text = ast.get_source_segment(EXECUTOR_SOURCE, seed) or ""
    assert "trust_store_module._make_record" in text
    assert "ledger._insert" in text
    assert 'state="ACTIVE"' in text
    assert "admit(" not in text
    assert "RuntimeTrustAttestation" not in EXECUTOR_SOURCE
    assert "RuntimeFaultAttestation" not in EXECUTOR_SOURCE


def test_pass_requires_cancelled_terminal_no_outputs_and_authenticated_row_survival() -> None:
    function = _function(EXECUTOR_TREE, "_execute_runtime_trust_contention")
    text = ast.get_source_segment(EXECUTOR_SOURCE, function) or ""
    required = (
        "writer_active_before_release",
        "authorization.provider_invoked",
        "authorization.output_evidence_built",
        "returned_value is False",
        "isinstance(raised, RuntimeProviderTrustFenceError)",
        "isinstance(cause, sqlite3.OperationalError)",
        "sqlite_base_code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}",
        "len(authorization.terminals) == 1",
        'authorization.terminals[0].outcome == "cancelled"',
        "authorization.terminals[0].output_digests == ()",
        "authorization.terminals[0].detail_sha256 is not None",
        "durable.record_sha256 == record.record_sha256",
        'durable.state == "ACTIVE"',
    )
    for expression in required:
        assert expression in text


def test_provider_value_and_exception_text_are_not_retained() -> None:
    function = _function(EXECUTOR_TREE, "_execute_runtime_trust_contention")
    text = ast.get_source_segment(EXECUTOR_SOURCE, function) or ""
    assert '"provider_value"' not in text
    assert '"exception_text"' not in text
    assert '"exception_message"' not in text
    assert "str(raised)" not in text
    assert "str(cause)" not in text
    assert '"output-must-be-withheld"' not in text[text.index("payload = {") :]


def test_implementation_identity_binds_executor_broker_store_and_timing() -> None:
    function = _function(EXECUTOR_TREE, "implementation_sha256")
    text = ast.get_source_segment(EXECUTOR_SOURCE, function) or ""
    required = (
        "Path(__file__).resolve()",
        "broker_module",
        "trust_store_module",
        '"busy_timeout_ms": _BUSY_TIMEOUT_MS',
        '"min_elapsed_ms": _MIN_ELAPSED_MS',
        '"max_elapsed_ms": _MAX_ELAPSED_MS',
    )
    for expression in required:
        assert expression in text


def test_candidate_output_cannot_claim_trust_attestation_or_gate_closure() -> None:
    assert '"trusted": True' not in EXECUTOR_SOURCE
    assert '"attested": True' not in EXECUTOR_SOURCE
    assert '"gate_closure_claimed": True' not in EXECUTOR_SOURCE
    assert '"trusted": False' in EXECUTOR_SOURCE
    assert '"attested": False' in EXECUTOR_SOURCE
    assert '"gate_closure_claimed": False' in EXECUTOR_SOURCE
