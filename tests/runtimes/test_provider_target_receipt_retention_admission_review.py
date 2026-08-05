from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE = (
    ROOT
    / "daedalus"
    / "runtimes"
    / "provider_target_receipt_retention_admission.py"
)


def _tree() -> ast.Module:
    return ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))


def _qualified_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _qualified_name(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(matches) == 1
    return matches[0]


def _class(tree: ast.Module, name: str) -> ast.ClassDef:
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == name
    ]
    assert len(matches) == 1
    return matches[0]


def test_admission_has_no_writer_process_network_or_promotion_authority() -> None:
    tree = _tree()
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    forbidden_imports = {
        "sqlite3",
        "subprocess",
        "socket",
        "urllib",
        "requests",
        "httpx",
        "shutil",
        "tempfile",
    }
    assert imported_modules.isdisjoint(forbidden_imports)

    forbidden_terminal_calls = {
        "open",
        "write_bytes",
        "write_text",
        "mkdir",
        "touch",
        "unlink",
        "replace",
        "rename",
        "symlink_to",
        "hardlink_to",
        "connect",
        "run",
        "Popen",
        "grant",
        "begin",
        "begin_effect",
        "finish",
        "finish_effect",
        "revoke",
        "retain",
        "put_bytes",
        "record_intent",
        "mark_completed",
        "run_runtime_provider",
        "promote_candidates",
    }
    calls = {
        name
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for name in [_qualified_name(node.func)]
        if name is not None
    }
    assert all(
        name.rsplit(".", 1)[-1] not in forbidden_terminal_calls
        for name in calls
    )


def test_preflight_and_topology_are_double_fenced_around_persisted_replay() -> None:
    function = _function(
        _tree(),
        "verify_provider_target_receipt_retention_admission",
    )
    calls = [
        (_qualified_name(node.func), node.lineno)
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
    ]
    positions: dict[str, list[int]] = {}
    for name, line in calls:
        if name is not None:
            positions.setdefault(name, []).append(line)

    assert len(positions["_replay_preflight"]) == 2
    assert len(positions["_verify_topology"]) == 2
    assert len(positions["inspect_effect_execution"]) == 1
    preflight_lines = sorted(positions["_replay_preflight"])
    topology_lines = sorted(positions["_verify_topology"])
    replay_line = positions["inspect_effect_execution"][0]
    assert (
        preflight_lines[0]
        < topology_lines[0]
        < replay_line
        < topology_lines[1]
        < preflight_lines[1]
    )


def test_admission_requires_exact_persisted_authority_types() -> None:
    function = _function(
        _tree(),
        "verify_provider_target_receipt_retention_admission",
    )
    source = ast.unparse(function)
    for required in (
        "EffectExecutionRequest",
        "NonRuntimeEffectAuthorization",
        "ProviderTargetReceiptLedger",
        "EffectLease",
        "EffectLeaseRequest",
        "PolicyDecision",
        "EffectLeaseLedger",
    ):
        assert required in source
    assert "type(value) is not expected" in source
    assert "type(replay) is not EffectExecutionReplaySnapshot" in source


def test_guard_is_one_exact_allowed_signed_preflight_decision() -> None:
    function = _function(_tree(), "_exact_guard")
    source = ast.unparse(function)
    assert "type(guards) is not tuple" in source
    assert "len(guards) != 1" in source
    assert "type(guards[0]) is not GuardDecision" in source
    assert "guards[0] != expected" in source
    assert "contract=RETENTION_GUARD_CONTRACT" in source
    assert "allowed=True" in source
    assert "evidence=preflight.guard_evidence" in source


def test_topology_binds_real_nonaliased_disjoint_paths_and_sqlite_companions() -> None:
    tree = _tree()
    identity = ast.unparse(_function(tree, "_identity"))
    topology = ast.unparse(_function(tree, "_verify_topology"))
    companions = ast.unparse(_function(tree, "_sqlite_companions"))

    assert "_contains_symlink(absolute)" in identity
    assert "resolved = absolute.resolve(strict=True)" in identity
    assert "stat.S_ISDIR(info.st_mode)" in identity
    assert "stat.S_ISREG(info.st_mode)" in identity
    assert "info.st_nlink != 1" in identity
    assert "_same_identity(primary, ledger_primary)" in topology
    assert "_same_identity(event, expected_event)" in topology
    assert "_same_identity(cas, expected_cas)" in topology
    assert "_overlap(primary[0], root[0])" in topology
    assert "_overlap(left[0], right[0]) or _same_identity(left, right)" in topology
    assert "_sqlite_companions(store)" in topology
    for suffix in ("-wal", "-shm", "-journal"):
        assert suffix in companions


def test_admission_receipt_permanently_refuses_write_reexecution_and_gate_claims() -> None:
    tree = _tree()
    receipt_class = _class(
        tree,
        "ProviderTargetReceiptRetentionAdmissionReceipt",
    )
    methods = {
        node.name: node
        for node in receipt_class.body
        if isinstance(node, ast.FunctionDef)
    }
    returns = [
        node
        for node in ast.walk(methods["to_dict"])
        if isinstance(node, ast.Return)
    ]
    assert len(returns) == 1
    payload = returns[0].value
    assert isinstance(payload, ast.Dict)
    constants = {
        key.value: value.value
        for key, value in zip(payload.keys, payload.values)
        if isinstance(key, ast.Constant)
        and isinstance(key.value, str)
        and isinstance(value, ast.Constant)
    }
    assert constants["persisted_effect_lease_verified"] is True
    assert constants["primary_checkout_disjointness_verified"] is True
    for field in (
        "retention_write_performed",
        "automatic_reexecution_allowed",
        "canonical_entrypoint_registered",
        "gate_transition_authorized",
        "closed",
    ):
        assert constants[field] is False


def test_replay_preflight_binds_all_live_subject_digests() -> None:
    function = _function(_tree(), "_replay_preflight")
    source = ast.unparse(function)
    for comparison in (
        "preflight.retention_execution_request_sha256 != execution.digest",
        "preflight.retention_effect_lease_sha256 != effect_lease.digest",
        "preflight.provider_target_receipt_sha256 != receipt.digest",
        "preflight.retention_inventory_sha256 != inventory.digest",
        "preflight.retention_authority_sha256 != authority.digest",
    ):
        assert comparison in source
    assert "type(preflight) is not ProviderTargetReceiptRetentionPreflightReceipt" in source


def test_public_api_accepts_no_callback_provider_or_promotion_authority() -> None:
    function = _function(
        _tree(),
        "verify_provider_target_receipt_retention_admission",
    )
    arguments = {
        argument.arg
        for argument in (
            *function.args.posonlyargs,
            *function.args.args,
            *function.args.kwonlyargs,
        )
    }
    forbidden = {
        "callback",
        "invoke",
        "writer",
        "provider",
        "begin_effect",
        "finish_effect",
        "promotion",
        "owner_approval",
        "merge",
    }
    assert arguments.isdisjoint(forbidden)
    assert function.args.vararg is None
    assert function.args.kwarg is None
