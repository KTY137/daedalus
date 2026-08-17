from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXECUTOR_PATH = ROOT / "tests" / "fixtures" / "effect_ledger_contention_fault_executor.py"
REVISION = "c" * 40


def _source_and_tree():
    source = EXECUTOR_PATH.read_text(encoding="utf-8")
    return source, ast.parse(source, filename=str(EXECUTOR_PATH))


def _load():
    name = "daedalus_test_effect_ledger_contention_review_module"
    spec = importlib.util.spec_from_file_location(name, EXECUTOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_authority_builds_against_the_current_kernel_contracts() -> None:
    """Contract drift must fail here, on every platform, not only on Linux.

    The fault body itself is Linux-host evidence, but the authority it leases
    is pure in-memory kernel contract construction.  Building it here is what
    catches a renamed or newly required contract field on a Windows checkout,
    where the platform gate would otherwise short-circuit before the executor
    ever touched ``EffectLeaseRequest``.
    """

    module = _load()
    registry, request, policy, lease, execution, guards = module._authority(REVISION)

    assert request.entrypoint_id in registry
    # The entrypoint declares no runtime_id, so the kernel requires both runtime
    # digests to be absent together; supplying either would be refused.
    assert request.runtime_manifest_sha256 is None
    assert request.runtime_conformance_sha256 is None
    assert lease.request_sha256 == request.digest
    assert lease.policy_decision_sha256 == policy.digest
    assert lease.runtime_manifest_sha256 is None
    assert lease.runtime_conformance_sha256 is None
    assert execution.kill_switch_generation == request.kill_switch_generation
    assert guards and guards[0].contract in registry[request.entrypoint_id].guard_contracts


def test_fixture_has_no_provider_or_process_effect_boundary() -> None:
    source, tree = _source_and_tree()
    forbidden = {
        ("subprocess", "Popen"),
        ("subprocess", "run"),
        ("os", "system"),
        ("os", "popen"),
    }
    observed: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
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
    assert "ledger.begin(" in source
    assert "provider_called = True" in source
    assert "execution_count == 0" in source


def test_bounded_ledger_changes_only_connection_timeout() -> None:
    source, tree = _source_and_tree()
    classes = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
    }
    bounded = classes["BoundedEffectLeaseLedger"]
    methods = {
        node.name
        for node in bounded.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert methods == {"__init__", "_connect"}
    assert "super().__init__(path)" in source
    assert "PRAGMA busy_timeout" in source
    assert "except sqlite3.Error" in source


def test_writer_lock_and_full_busy_interval_are_required() -> None:
    source, _ = _source_and_tree()
    assert 'blocker.execute("BEGIN IMMEDIATE")' in source
    assert "writer_lock_held = blocker.in_transaction" in source
    assert "writer_lock_held\n            and contention" in source
    assert "_BUSY_TIMEOUT_MS - _TIMEOUT_TOLERANCE_MS" in source
    assert 'HostFaultFact("writer-lock-held", "true")' in source


def test_raw_evidence_excludes_sqlite_message_and_plain_database_path() -> None:
    source, _ = _source_and_tree()
    assert '"database_path_sha256"' in source
    assert '"database_path"' not in source
    assert '"exception_module"' in source
    assert '"exception_type"' in source
    assert '"sqlite_errorcode"' in source
    assert '"exception_message"' not in source
    assert "str(exc).lower()" in source


def test_candidate_cannot_claim_trust_attestation_or_gate_closure() -> None:
    _, tree = _source_and_tree()
    forbidden_true = {"trusted", "attested", "gate_closure_claimed"}
    observed = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=False):
            if isinstance(key, ast.Constant) and key.value in forbidden_true:
                observed.add(key.value)
                assert isinstance(value, ast.Constant)
                assert value.value is False
    assert observed == forbidden_true


def test_only_sqlite_operational_error_is_classified_as_expected_fault() -> None:
    source, tree = _source_and_tree()
    handlers = [node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)]
    operational_handlers = [
        node
        for node in handlers
        if isinstance(node.type, ast.Attribute)
        and isinstance(node.type.value, ast.Name)
        and node.type.value.id == "sqlite3"
        and node.type.attr == "OperationalError"
    ]
    assert len(operational_handlers) == 1
    assert "except BaseException" not in source
    assert "except Exception as exc" not in source
