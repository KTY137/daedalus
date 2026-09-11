from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE = (
    ROOT
    / "daedalus"
    / "runtimes"
    / "provider" / "target_receipt_retention_admission.py"
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


def _source(node: ast.AST) -> str:
    return ast.unparse(node)


def _string_literals(node: ast.AST) -> set[str]:
    return {
        child.value
        for child in ast.walk(node)
        if isinstance(child, ast.Constant) and isinstance(child.value, str)
    }


def test_admission_has_no_writer_process_network_or_promotion_authority() -> None:
    tree = _tree()
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    # sqlite3 is intentionally imported only to authenticate the already-open
    # Spine connection with PRAGMA database_list. The dedicated review below
    # pins that SQL surface to one read-only literal.
    forbidden_imports = {
        "subprocess",
        "socket",
        "urllib",
        "requests",
        "httpx",
        "shutil",
        "tempfile",
    }
    assert imported_modules.isdisjoint(forbidden_imports)
    assert "sqlite3" in imported_modules

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


def test_live_spine_inspection_is_one_exact_read_only_pragma() -> None:
    tree = _tree()
    function = _function(tree, "_spine_database_identity")
    source = _source(function)
    literals = _string_literals(function)
    calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and _qualified_name(node.func) == "connection.execute"
    ]

    assert len(calls) == 1
    assert len(calls[0].args) == 1
    assert isinstance(calls[0].args[0], ast.Constant)
    assert calls[0].args[0].value == "PRAGMA database_list"
    assert "type(connection) is not sqlite3.Connection" in source
    assert "getattr(spine, '_conn', None)" in source
    assert "getattr(spine, '_lock', None)" in source
    assert "with lock:" in source
    assert "len(main_rows) != 1" in source
    assert "row[1] == 'main'" in source
    assert "return _identity" in source

    forbidden_sql = {
        "INSERT",
        "UPDATE",
        "DELETE",
        "CREATE",
        "DROP",
        "ALTER",
        "ATTACH",
        "DETACH",
        "REPLACE",
        "VACUUM",
        "BEGIN",
        "COMMIT",
        "ROLLBACK",
        "PRAGMA journal_mode",
        "PRAGMA synchronous",
        "PRAGMA query_only",
    }
    assert all(
        not any(token in literal.upper() for token in forbidden_sql)
        for literal in literals
    )


def test_preflight_topology_and_persisted_state_are_double_fenced() -> None:
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
    assert len(positions["_inspect_persisted_execution"]) == 2
    assert len(positions["_verify_live_unstarted_authority"]) == 2
    preflight = sorted(positions["_replay_preflight"])
    topology = sorted(positions["_verify_topology"])
    replay = sorted(positions["_inspect_persisted_execution"])
    live = sorted(positions["_verify_live_unstarted_authority"])
    assert (
        preflight[0]
        < topology[0]
        < replay[0]
        < live[0]
        < topology[1]
        < preflight[1]
        < replay[1]
        < live[1]
    )
    source = _source(function)
    assert "if final_topology != topology" in source
    assert "if final_preflight.digest != preflight.digest" in source
    assert "if final_replay != replay" in source
    assert "if _exact_guard(authorization, final_preflight) != guard" in source


def test_topology_snapshot_retains_all_concrete_filesystem_identities() -> None:
    tree = _tree()
    snapshot = _class(tree, "_TopologySnapshot")
    annotated = {
        node.target.id
        for node in snapshot.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
    }
    assert annotated == {
        "primary",
        "retention_root",
        "event_store",
        "receipt_cas",
        "receipt_cas_objects",
        "effect_store",
        "sqlite_companions",
    }

    identity = _source(_function(tree, "_identity"))
    topology = _source(_function(tree, "_verify_topology"))
    companions = _source(_function(tree, "_sqlite_companion_paths"))
    assert "return (resolved, int(info.st_dev), int(info.st_ino))" in identity
    assert "_contains_symlink(absolute)" in identity
    assert "absolute.resolve(strict=True)" in identity
    assert "stat.S_ISDIR(info.st_mode)" in identity
    assert "stat.S_ISREG(info.st_mode)" in identity
    assert "info.st_nlink != 1" in identity
    assert "return _TopologySnapshot" in topology
    assert "receipt_cas_objects=objects" in topology
    assert "sqlite_companions=tuple(companions)" in topology
    for suffix in ("-wal", "-shm", "-journal"):
        assert suffix in companions


def test_topology_binds_live_writable_spine_and_real_cas_object_target() -> None:
    source = _source(_function(_tree(), "_verify_topology"))
    assert "type(spine) is not SpineLedger" in source
    assert "type(source_store) is not SourceTreeStore" in source
    assert "spine.read_only" in source
    assert "connected_event = _spine_database_identity(spine)" in source
    assert "_same_identity(event, connected_event)" in source
    assert "SpineLedger.path is detached from its live SQLite connection" in source
    assert "retention_ledger.source_store.objects" in source
    assert "expected_cas[0] / 'objects'" in source
    assert "_same_identity(objects, expected_objects)" in source
    assert "objects[0].parent != cas[0]" in source
    assert "_same_identity(primary, ledger_primary)" in source
    assert "_same_identity(event, expected_event)" in source
    assert "_same_identity(cas, expected_cas)" in source
    assert "_overlap(primary[0], root[0])" in source
    assert "root[0] not in event[0].parents" in source
    assert "root[0] not in cas[0].parents" in source
    assert "_overlap(left[0], right[0]) or _same_identity(left, right)" in source
    assert "identity_key in known_identities" in source
    assert "_overlap(companion[0], path)" in source


def test_admission_requires_exact_persisted_authority_types_and_bindings() -> None:
    tree = _tree()
    verifier = _source(
        _function(tree, "verify_provider_target_receipt_retention_admission")
    )
    shape = _source(_function(tree, "_verify_authorization_shape"))
    for required in (
        "EffectExecutionRequest",
        "NonRuntimeEffectAuthorization",
        "ProviderTargetReceiptLedger",
        "EffectLease",
        "EffectLeaseRequest",
        "PolicyDecision",
        "EffectLeaseLedger",
    ):
        assert required in verifier or required in shape
    assert "type(value) is not expected" in verifier
    assert "type(value) is not expected" in shape
    assert "authorization.effect_ledger.path must be pathlib.Path" in shape
    for binding in (
        "lease.request_id != request.request_id",
        "lease.request_sha256 != request.digest",
        "lease.policy_decision_id != policy.decision_id",
        "lease.policy_decision_sha256 != policy.digest",
        "policy.subject_id != request.request_id",
        "policy.subject_sha256 != request.digest",
        "policy.verdict != 'allow'",
        "lease.requested_effects != request.requested_effects",
        "lease.effect_scope != request.effect_scope",
        "policy.effect_scope != request.effect_scope",
        "lease.kill_switch_generation != request.kill_switch_generation",
    ):
        assert binding in shape


def test_persisted_replay_is_exact_and_unstarted_authority_is_live() -> None:
    tree = _tree()
    inspect_source = _source(_function(tree, "_inspect_persisted_execution"))
    live_source = _source(_function(tree, "_verify_live_unstarted_authority"))
    assert "inspect_effect_execution(authorization, execution)" in inspect_source
    assert "type(replay) is not EffectExecutionReplaySnapshot" in inspect_source
    assert "except EffectReplayProjectionError" in inspect_source
    assert "authorization.verify()" in live_source
    assert "except (EffectLeaseError, TypeError, ValueError)" in live_source
    assert "not live and authentic" in live_source


def test_guard_is_one_exact_allowed_signed_preflight_decision() -> None:
    source = _source(_function(_tree(), "_exact_guard"))
    assert "type(guards) is not tuple" in source
    assert "len(guards) != 1" in source
    assert "type(guards[0]) is not GuardDecision" in source
    assert "guards[0] != expected" in source
    assert "contract=RETENTION_GUARD_CONTRACT" in source
    assert "allowed=True" in source
    assert "evidence=preflight.guard_evidence" in source


def test_replayed_preflight_binds_all_live_subject_digests() -> None:
    source = _source(_function(_tree(), "_replay_preflight"))
    for comparison in (
        "preflight.retention_execution_request_sha256 != execution.digest",
        "preflight.retention_effect_lease_sha256 != effect_lease.digest",
        "preflight.provider_target_receipt_sha256 != receipt.digest",
        "preflight.retention_inventory_sha256 != inventory.digest",
        "preflight.retention_authority_sha256 != authority.digest",
    ):
        assert comparison in source
    assert "type(preflight) is not ProviderTargetReceiptRetentionPreflightReceipt" in source


def test_receipt_permanently_refuses_write_reexecution_registry_and_gate_claims() -> None:
    receipt_class = _class(
        _tree(),
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

    from_dict = _source(methods["from_dict"])
    assert "payload[field] is not expected" in from_dict
    assert "state not in _EXECUTION_STATES" in from_dict


def test_receipt_shape_is_bounded_and_revision_is_exact_commit_sha() -> None:
    receipt_class = _class(
        _tree(),
        "ProviderTargetReceiptRetentionAdmissionReceipt",
    )
    post_init = next(
        node
        for node in receipt_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "__post_init__"
    )
    source = _source(post_init)
    assert "_REVISION_40.fullmatch(revision) is None" in source
    assert "_GUARD_EVIDENCE.fullmatch(self.guard_evidence) is None" in source
    assert "len(value) > 4096" in source
    assert "'\\x00' in value" in source
    assert "'\\r' in value" in source
    assert "'\\n' in value" in source
    assert "state and execution receipts disagree" in source


def test_public_api_accepts_no_callback_writer_provider_or_promotion_authority() -> None:
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
