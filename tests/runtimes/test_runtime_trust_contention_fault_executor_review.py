# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
import importlib.util
import sys
from datetime import datetime, timezone
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


def test_no_stand_in_authority_object_reaches_the_broker() -> None:
    """The broker's exactness rule must be satisfied, not worked around.

    Since G0-RTC-07A ``run_runtime_provider`` refuses anything that is not an
    exact ``RuntimeBoundEffectAuthorization``.  The fixture must therefore hand
    over the real capability object; a local delegating class would be fixture
    drift dressed up as a fault.
    """

    classes = {node.name for node in TREE.body if isinstance(node, ast.ClassDef)}
    assert "TerminalFenceLockAuthorization" not in classes
    assert "self._inner" not in SOURCE
    execute = ast.get_source_segment(SOURCE, _function(TREE, "_execute")) or ""
    assert "authorization=authorization" in execute
    for call in _calls(TREE, "run_runtime_provider"):
        keywords = {keyword.arg for keyword in call.keywords}
        assert "observation_authority" in keywords
        assert "observation_binding_ledger" in keywords
    assert "issue_provider_observation_authority(" in SOURCE
    assert "ProviderObservationBindingLedger(" in SOURCE


def test_contention_ledger_arms_exactly_one_writer_at_the_fence() -> None:
    value = _class("TerminalFenceContentionTrustLedger")
    assert value.bases and getattr(value.bases[0], "id", None) == "BoundedRuntimeTrustLedger"
    methods = {
        node.name
        for node in value.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert methods == {
        "__init__",
        "_connect",
        "require_active",
        "mark_invoked",
        "_arm_writer",
        "plain_verify_calls",
        "writer_active",
        "release_writer",
    }
    text = ast.get_source_segment(SOURCE, value) or ""
    required = (
        "record = super().require_active(**kwargs)",
        "if self._invoked:",
        "self._plain_verify_calls += 1",
        # one-shot, and only once the last plain verify has already passed
        "if self._armed or self._plain_verify_calls < 2:",
        "self._armed = True",
        'writer.execute("BEGIN IMMEDIATE")',
        "writer.in_transaction",
    )
    for expression in required:
        assert expression in text


def test_writer_is_injected_after_output_evidence_and_last_plain_verify() -> None:
    execute = ast.get_source_segment(SOURCE, _function(TREE, "_execute")) or ""
    proxy = ast.get_source_segment(SOURCE, _class("_FenceArmingConnection")) or ""
    ledger = ast.get_source_segment(
        SOURCE,
        _class("TerminalFenceContentionTrustLedger"),
    ) or ""
    assert "output_called = True" in execute
    assert "trust.mark_invoked()" in execute
    # The fence is the only trust-store caller that begins a transaction on a
    # connection it did not open with a ``with`` block.
    assert 'if not self._entered and statement.strip().upper().startswith("BEGIN")' in proxy
    assert "self._entered = True" in proxy
    assert "if self._armed or self._plain_verify_calls < 2:" in ledger
    assert "run_runtime_provider(" in execute
    assert "except RuntimeProviderTrustFenceError as exc" in execute
    # The count must be read before the replay run adds verifies of its own.
    assert "plain_verify_calls = trust.plain_verify_calls" in execute


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
        "plain_verify_calls == 2",
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
        '_module_path(provider_observation_module, "provider observation")',
        '"busy_timeout_ms": _BUSY_TIMEOUT_MS',
        '"timeout_tolerance_ms": _TIMEOUT_TOLERANCE_MS',
    ):
        assert expression in value


def _load():
    name = "daedalus_test_runtime_trust_contention_review_module"
    spec = importlib.util.spec_from_file_location(name, EXECUTOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_authority_builds_against_the_current_runtime_contracts(tmp_path) -> None:
    """Contract drift must fail here, on every platform, not only on Linux.

    The contention itself is Linux-host evidence, but everything the fault
    leans on -- the trust record, the runtime-bound lease, the exact
    authorization type and the signed observation authority -- is ordinary
    persisted setup.  Building it here is what catches the next exactness rule
    or required contract field on a Windows checkout, instead of leaving it to
    surface as a container failure months later.
    """

    module = _load()
    now = datetime.now(timezone.utc)
    (
        trust,
        record,
        effects,
        authorization,
        execution,
        observation_authority,
        observation_ledger,
    ) = module._authority(root=tmp_path, source_revision="a" * 40, now=now)

    # The broker compares by exact type, so a subclass would not be accepted.
    assert type(authorization) is module.RuntimeBoundEffectAuthorization
    assert type(observation_authority) is module.provider_observation_module.ProviderObservationAuthority
    assert type(observation_ledger) is module.ProviderObservationBindingLedger
    assert observation_authority.execution_request_sha256 == execution.digest
    assert observation_authority.lease_sha256 == authorization.capability.lease.digest
    assert observation_authority.entrypoint_id == authorization.request.entrypoint_id
    assert record.state == "ACTIVE"
    assert effects.path.parent == tmp_path
    # The tripwire is disarmed until the provider has actually been invoked.
    assert trust.plain_verify_calls == 0
    assert trust.writer_active is False


def test_candidate_cannot_claim_trust_attestation_or_gate_closure() -> None:
    assert '"trusted": True' not in SOURCE
    assert '"attested": True' not in SOURCE
    assert '"gate_closure_claimed": True' not in SOURCE
    assert '"trusted": False' in SOURCE
    assert '"attested": False' in SOURCE
    assert '"gate_closure_claimed": False' in SOURCE
