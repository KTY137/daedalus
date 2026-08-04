from __future__ import annotations

import ast
import inspect
from pathlib import Path

from daedalus.kernel.runtime_effect_replay import (
    inspect_runtime_effect_execution,
)


SOURCE = Path("daedalus/kernel/runtime_effect_replay.py")


def _call_name(node: ast.Call) -> str:
    current = node.func
    parts: list[str] = []
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def test_projection_has_no_write_or_external_effect_authority() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_imports = {
        "os",
        "sqlite3",
        "subprocess",
        "socket",
        "docker",
        "git",
        "shutil",
        "tempfile",
        "importlib",
        "runpy",
    }
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not imported.intersection(forbidden_imports)
    calls = {
        _call_name(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    required = {
        "NonRuntimeEffectAuthorization",
        "inspect_effect_execution",
        "verify_runtime_bound_effect_lease",
    }
    assert required.issubset(calls)
    for forbidden in (
        "grant",
        "begin",
        "begin_effect",
        "finish",
        "finish_effect",
        "revoke",
        "admit",
        "quarantine",
        "subprocess.run",
        "subprocess.Popen",
        "open",
        "write_text",
        "write_bytes",
    ):
        assert forbidden not in calls
    assert "Callable" not in source
    assert "Protocol" not in source
    assert "**kwargs" not in source


def test_public_projection_accepts_only_authorization_and_execution() -> None:
    assert tuple(
        inspect.signature(inspect_runtime_effect_execution).parameters
    ) == ("authorization", "execution")


def test_inner_persisted_projection_precedes_runtime_capability_replay() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    inner_index = source.index(
        "effect_snapshot = inspect_effect_execution(inner, execution)"
    )
    missing_index = source.index("if effect_snapshot is None:")
    time_index = source.index("start_instant = _parse_utc(")
    verify_index = source.index("trust_record = verify_runtime_bound_effect_lease(")
    record_index = source.index(
        "trust_record.record_sha256 != authorization.capability.runtime_trust_record_sha256"
    )
    identity_index = source.index(
        "trust_record.runtime_id != authorization.capability.runtime_id"
    )
    assert inner_index < missing_index < time_index < verify_index
    assert verify_index < record_index < identity_index


def test_historical_verification_uses_retained_start_and_generation() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    required = (
        "effect_snapshot.start_receipt.started_at",
        "current_kill_switch_generation=(\n"
        "                authorization.capability.lease.kill_switch_generation\n"
        "            )",
        "now=start_instant",
        "runtime_trust_ledger=authorization.runtime_trust_ledger",
        "runtime_authority_keyring=authorization.runtime_authority_keyring",
        "registry=authorization.registry",
    )
    for fragment in required:
        assert fragment in source
    assert "authorization.current_kill_switch_generation" not in source


def test_adapter_carries_exact_inner_effect_subject() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    required = (
        "lease=authorization.capability.lease",
        "request=authorization.request",
        "policy_decision=authorization.policy_decision",
        "effect_ledger=authorization.effect_ledger",
        "lease_keyring=authorization.lease_keyring",
        "guard_decisions=authorization.guard_decisions",
        "registry=authorization.registry",
    )
    for fragment in required:
        assert fragment in source


def test_snapshot_exposes_state_and_trust_but_no_execution_method() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "execution: EffectExecutionReplaySnapshot" in source
    assert "runtime_trust_record: RuntimeTrustRecord" in source
    assert "verified_at: str" in source
    assert "def pending_reconciliation" in source
    for forbidden in (
        "def execute",
        "def begin",
        "def finish",
        "def grant",
        "def promote",
    ):
        assert forbidden not in source


def test_conservative_current_trust_boundary_is_documented() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "must still be active and authenticated" in source
    assert "refuses historical runtime capability replay after trust expiry or quarantine" in source
    assert "append-only runtime trust history" in source
