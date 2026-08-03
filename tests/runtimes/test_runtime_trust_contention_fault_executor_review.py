from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXECUTOR = ROOT / "tests" / "fixtures" / "runtime_trust_contention_fault_executor.py"
BROKER = ROOT / "daedalus" / "runtimes" / "broker.py"
SOURCE = EXECUTOR.read_text(encoding="utf-8")
BROKER_SOURCE = BROKER.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE, filename=str(EXECUTOR))
BROKER_TREE = ast.parse(BROKER_SOURCE, filename=str(BROKER))


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing function {name}")


def _class(name: str) -> ast.ClassDef:
    for node in TREE.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"missing class {name}")


def _calls(tree: ast.AST, name: str) -> list[ast.Call]:
    result = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == name:
            result.append(node)
        if isinstance(node.func, ast.Attribute) and node.func.attr == name:
            result.append(node)
    return result


def test_fixture_uses_one_production_broker_and_no_second_launcher() -> None:
    assert len(_calls(TREE, "run_runtime_provider")) == 2  # fault plus exact replay
    assert "subprocess" not in SOURCE
    assert "run_in_docker_sandbox" not in SOURCE
    assert "shell=True" not in SOURCE.replace(" ", "")
    forbidden = {"Popen", "system", "popen", "spawnv", "spawnve", "spawnvp"}
    for node in ast.walk(TREE):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in forbidden


def test_bounded_trust_subclass_changes_only_connection_timeout() -> None:
    value = _class("BoundedRuntimeTrustLedger")
    methods = {
        node.name
        for node in value.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert methods == {"__init__", "_connect"}
    text = ast.get_source_segment(SOURCE, value) or ""
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


def test_authorization_wrapper_delegates_real_effect_authority() -> None:
    value = _class("TerminalFenceLockAuthorization")
    methods = {
        node.name
        for node in value.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert methods == {
        "__init__",
        "grant",
        "begin_effect",
        "finish_effect",
        "verify",
        "plain_verify_calls",
        "writer_active",
        "release_writer",
    }
    text = ast.get_source_segment(SOURCE, value) or ""
    required = (
        "self._inner.grant()",
        "self._inner.begin_effect(execution)",
        "self._inner.finish_effect(start_receipt, **kwargs)",
        "record = self._inner.verify(now=now)",
        "self._plain_verify_calls += 1",
        "if self._plain_verify_calls == 2",
        'writer.execute("BEGIN IMMEDIATE")',
        "writer.in_transaction",
    )
    for expression in required:
        assert expression in text


def test_writer_is_injected_after_output_evidence_and_last_plain_verify() -> None:
    execute = ast.get_source_segment(SOURCE, _function(TREE, "_execute")) or ""
    wrapper = ast.get_source_segment(
        SOURCE,
        next(
            node
            for node in _class("TerminalFenceLockAuthorization").body
            if isinstance(node, ast.FunctionDef) and node.name == "verify"
        ),
    ) or ""
    assert "output_called = True" in execute
    assert "if self._plain_verify_calls == 2" in wrapper
    assert 'writer.execute("BEGIN IMMEDIATE")' in wrapper
    assert "run_runtime_provider(" in execute
    assert "except RuntimeProviderTrustFenceError as exc" in execute


def test_production_broker_converts_sqlite_at_terminal_fence() -> None:
    finish = ast.get_source_segment(
        BROKER_SOURCE,
        _function(BROKER_TREE, "_finish_completed_under_runtime_fence"),
    ) or ""
    rollback = ast.get_source_segment(
        BROKER_SOURCE,
        _function(BROKER_TREE, "_rollback_runtime_fence"),
    ) or ""
    required = (
        "except sqlite3.Error as exc",
        "raise RuntimeProviderTrustFenceError",
        "_rollback_runtime_fence(connection)",
        "finally:",
        "connection.close()",
    )
    for expression in required:
        assert expression in finish
    assert "if not connection.in_transaction" in rollback
    assert 'connection.execute("ROLLBACK")' in rollback


def test_only_terminal_fence_error_enters_trust_loss_cancellation() -> None:
    broker = ast.get_source_segment(
        BROKER_SOURCE,
        _function(BROKER_TREE, "run_runtime_provider"),
    ) or ""
    fence_call = broker.index("terminal = _finish_completed_under_runtime_fence")
    fence_handler = broker.index("except RuntimeProviderTrustFenceError as exc")
    cancel = broker.index('_cancel_for_trust_loss(', fence_handler)
    returned = broker.index("return RuntimeInvocationResult", cancel)
    assert fence_call < fence_handler < cancel < returned
    assert 'phase="terminal-runtime-fence"' in broker[fence_handler:returned]


def test_pass_requires_real_cancelled_terminal_output_withholding_and_replay() -> None:
    execute = ast.get_source_segment(SOURCE, _function(TREE, "_execute")) or ""
    required = (
        "authorization.plain_verify_calls == 2",
        "and lock_held",
        "and contention",
        "isinstance(observed, RuntimeProviderTrustFenceError)",
        "and provider_called",
        "and output_called",
        "and not released",
        'and state == "CANCELLED"',
        'and outcome == "CANCELLED"',
        "and terminal_outputs == []",
        "and detail is not None",
        "and trust_unchanged",
        "and replay_inert",
        "provider_output.encode(\"utf-8\") not in raw",
    )
    for expression in required:
        assert expression in execute
    assert "EffectLeaseLedger(" in SOURCE
    assert "RuntimeBoundEffectAuthorization(" in SOURCE
    assert "issue_runtime_bound_effect_lease(" in SOURCE


def test_replay_callbacks_are_distinct_and_required_inert() -> None:
    execute = ast.get_source_segment(SOURCE, _function(TREE, "_execute")) or ""
    required = (
        "replay_provider = False",
        "replay_outputs = False",
        "def replay_invoke()",
        "def replay_digest(result: str)",
        "replay.executed is False",
        "replay.value is None",
        "replay.terminal_receipt is None",
        "not replay_provider",
        "not replay_outputs",
        "_terminal(effects.path, execution.execution_id) == terminal",
    )
    for expression in required:
        assert expression in execute


def test_evidence_excludes_value_paths_and_exception_text() -> None:
    execute = ast.get_source_segment(SOURCE, _function(TREE, "_execute")) or ""
    assert '"trust_database_path_sha256"' in execute
    assert '"effect_database_path_sha256"' in execute
    assert '"trust_database_path"' not in execute
    assert '"effect_database_path"' not in execute
    assert '"exception_message"' not in execute
    assert '"provider_output"' not in execute
    assert "provider_output.encode(\"utf-8\") not in raw" in execute


def test_identity_binds_every_production_authority_source() -> None:
    value = ast.get_source_segment(
        SOURCE,
        _function(TREE, "implementation_sha256"),
    ) or ""
    for expression in (
        "Path(__file__).resolve()",
        '_module_path(broker_module, "broker")',
        '_module_path(trust_store_module, "trust store")',
        '_module_path(runtime_effects_module, "runtime effects")',
        '_module_path(effects_module, "effect ledger")',
        '"busy_timeout_ms": _BUSY_TIMEOUT_MS',
        '"timeout_tolerance_ms": _TIMEOUT_TOLERANCE_MS',
    ):
        assert expression in value


def test_candidate_cannot_claim_trust_attestation_or_gate_closure() -> None:
    assert '"trusted": True' not in SOURCE
    assert '"attested": True' not in SOURCE
    assert '"gate_closure_claimed": True' not in SOURCE
    assert '"trusted": False' in SOURCE
    assert '"attested": False' in SOURCE
    assert '"gate_closure_claimed": False' in SOURCE
