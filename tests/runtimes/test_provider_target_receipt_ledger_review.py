from __future__ import annotations

import ast
import inspect

import daedalus.runtimes.provider_target_receipt_ledger as ledger


def _function(name: str) -> ast.FunctionDef:
    tree = ast.parse(inspect.getsource(ledger))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing function {name}")


def _method(class_name: str, method_name: str) -> ast.FunctionDef:
    tree = ast.parse(inspect.getsource(ledger))
    cls = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    return next(
        node
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == method_name
    )


def test_retention_has_no_loader_provider_process_network_or_promotion_authority() -> None:
    source = inspect.getsource(ledger)
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    forbidden_import_roots = {
        "importlib",
        "subprocess",
        "socket",
        "requests",
        "urllib",
        "httpx",
    }
    assert not {name.split(".")[0] for name in imported} & forbidden_import_roots
    assert "OwnerApproval" not in source
    assert "PromotionReceipt" not in source
    assert "promote_candidates" not in source
    assert "provider_execution_allowed\": True" not in source
    assert "eval(" not in source
    assert "exec(" not in source
    assert "compile(" not in source


def test_authentication_and_validation_precede_intent_then_cas_then_terminal() -> None:
    rendered = ast.unparse(_method("ProviderTargetReceiptLedger", "retain"))
    verify_at = rendered.index("verify_provider_target_verification_receipt")
    payload_at = rendered.index("_receipt_bytes(receipt)")
    topology_at = rendered.index("_validate_topology")
    schema_at = rendered.index("self._install_single_receipt_invariant")
    intent_at = rendered.index("self._record_or_recover_intent")
    cas_at = rendered.index("self.source_store.put_bytes")
    terminal_at = rendered.index("self.spine.mark_completed")
    assert (
        verify_at
        < payload_at
        < topology_at
        < schema_at
        < intent_at
        < cas_at
        < terminal_at
    )

    helper = ast.unparse(
        _method("ProviderTargetReceiptLedger", "_record_or_recover_intent")
    )
    assert "self.spine.record_intent" in helper
    assert "self.source_store" not in helper


def test_replay_never_resolves_or_invokes_provider_targets() -> None:
    rendered = ast.unparse(_method("ProviderTargetReceiptLedger", "retain"))
    assert "if existing.state == STATE_COMPLETED" in rendered
    replay = rendered.split("if existing.state == STATE_COMPLETED", 1)[1]
    replay = replay.split("if existing.state != STATE_INTENDED", 1)[0]
    assert "put_bytes" not in replay
    assert "mark_completed" not in replay
    assert ".invoke(" not in replay
    assert "import_module" not in replay


def test_event_store_reader_is_read_only_and_rejects_ambiguous_state() -> None:
    rendered = ast.unparse(_function("_read_intent"))
    assert "mode=ro" in rendered
    assert "PRAGMA query_only=ON" in rendered
    assert "len(rows) != 1" in rendered
    assert "len(events) > 2" in rendered
    assert "STATE_FAILED" in rendered
    assert "canonical_json(payload) != raw_payload" in rendered
    assert "payload_sha" in rendered
    assert "UPDATE " not in rendered
    assert "INSERT " not in rendered
    assert "DELETE " not in rendered


def test_unknown_intent_and_terminal_outcomes_are_reread_not_guessed() -> None:
    intent = ast.unparse(
        _method("ProviderTargetReceiptLedger", "_record_or_recover_intent")
    )
    retain = ast.unparse(_method("ProviderTargetReceiptLedger", "retain"))
    assert "except sqlite3.DatabaseError as exc" in intent
    assert intent.count("_read_intent(self.spine.path, key)") >= 2
    assert "intent persistence is unresolved and requires replay" in intent
    assert "completion_error" in retain
    assert "terminal persistence is unresolved and requires replay" in retain
    assert "terminal is None or terminal.state == STATE_INTENDED" in retain


def test_exact_writer_store_receipt_and_projection_types_are_required() -> None:
    init = ast.unparse(_method("ProviderTargetReceiptLedger", "__init__"))
    retain = ast.unparse(_method("ProviderTargetReceiptLedger", "retain"))
    result = ast.unparse(
        next(
            node
            for node in ast.parse(inspect.getsource(ledger)).body
            if isinstance(node, ast.ClassDef)
            and node.name == "ProviderTargetReceiptRetentionResult"
        )
    )
    assert "type(spine) is not SpineLedger" in init
    assert "type(source_store) is not SourceTreeStore" in init
    assert (
        "type(receipt) is not ProviderExecutableTargetVerificationReceipt"
        in retain
    )
    assert "type(self.artifact) is not ArtifactRef" in result
    assert "type(self.projection) is not ProviderExecutableTargetProjection" in result


def test_primary_checkout_is_only_inspected_and_never_a_write_target() -> None:
    source = inspect.getsource(ledger)
    topology = ast.unparse(_function("_validate_topology"))
    retain = ast.unparse(_method("ProviderTargetReceiptLedger", "retain"))
    assert "primary_checkout" in topology
    assert "_paths_overlap(primary, store_root)" in topology
    assert "_paths_overlap(primary, event_store)" in topology
    assert "stat.S_ISREG(event_store_stat.st_mode)" in topology
    assert "event_store_stat.st_nlink != 1" in topology
    assert "_contains_symlink(path)" in topology
    assert "_validate_topology(self.primary_checkout, self.source_store, self.spine)" in retain
    assert "write_bytes" not in source
    assert "mkdir" not in source
    assert "primary_checkout" not in retain.replace(
        "_validate_topology(self.primary_checkout, self.source_store, self.spine)",
        "",
    )


def test_single_receipt_invariant_is_scoped_and_definition_checked() -> None:
    rendered = ast.unparse(
        _method("ProviderTargetReceiptLedger", "_install_single_receipt_invariant")
    )
    assert "CREATE UNIQUE INDEX IF NOT EXISTS" in rendered
    assert "ON intents(effect_key)" in rendered
    assert "WHERE kind=" in rendered
    assert "self.spine._txn()" in rendered
    assert "sqlite_master" in rendered
    assert "foreign definition" in rendered
