from __future__ import annotations

import ast
import inspect

import daedalus.kernel.attempt_contracts as contracts
import daedalus.kernel.attempt_ledger as ledger_impl
import daedalus.kernel.attempt_spine_reader as reader_impl
import daedalus.kernel.attempt_workspace as workspace_impl
import daedalus.kernel.attempts as compatibility


def _method(module, class_name: str, method_name: str) -> ast.FunctionDef:
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == method_name:
                    return child
    raise AssertionError(f"missing {class_name}.{method_name}")


def test_prepare_persists_start_before_materialization_and_replay_returns_first() -> None:
    method = _method(workspace_impl, "IsolatedAttemptCoordinator", "prepare")
    source = ast.unparse(method)
    assert source.index("self.ledger.begin") < source.index(
        "self.source_store.materialize_tree"
    )
    assert source.index("if not begin.execute") < source.index(
        "self.source_store.materialize_tree"
    )
    assert "PreparedAttempt(begin=begin, workspace=None)" in source


def test_process_abort_is_not_terminalized_as_known_failure() -> None:
    method = _method(workspace_impl, "IsolatedAttemptCoordinator", "prepare")
    handlers = [node for node in ast.walk(method) if isinstance(node, ast.ExceptHandler)]
    materialization_handlers = [
        node
        for node in handlers
        if isinstance(node.type, ast.Name) and node.type.id == "Exception"
    ]
    assert len(materialization_handlers) == 1
    assert all(
        not (isinstance(node.type, ast.Name) and node.type.id == "BaseException")
        for node in handlers
    )


def test_attempt_lifecycle_extends_the_single_existing_event_spine() -> None:
    implementation_source = "\n".join(
        inspect.getsource(module)
        for module in (contracts, reader_impl, ledger_impl, workspace_impl)
    )
    init_source = inspect.getsource(ledger_impl.AttemptLedger.__init__)
    install_source = inspect.getsource(
        ledger_impl.AttemptLedger._install_single_start_invariant
    )
    assert "SpineLedger" in init_source
    assert "self.spine" in init_source
    assert "read_only" in init_source
    assert "CREATE UNIQUE INDEX" in install_source
    assert "ON intents(effect_key)" in install_source
    assert "CREATE TABLE" not in implementation_source
    assert "attempt_starts" not in implementation_source
    assert "attempt_terminals" not in implementation_source


def test_begin_records_one_canonical_spine_intent_and_pending_never_executes() -> None:
    source = inspect.getsource(ledger_impl.AttemptLedger.begin)
    assert "self.spine.record_intent" in source
    assert "_ATTEMPT_INTENT_KIND" in source
    assert "persisted.same_subject(start)" in source
    assert "execute=created" in source
    assert source.index("self.source_store.load_tree(input_tree.ref)") < source.index(
        "self.spine.record_intent"
    )


def test_terminal_resolution_uses_the_same_spine_and_is_once_only() -> None:
    source = inspect.getsource(ledger_impl.AttemptLedger.complete)
    assert "self.spine.mark_completed" in source
    assert "IntentAlreadyResolved" in source
    assert "existing.receipt.same_subject(receipt)" in source
    assert "effect_id=receipt.digest" in source
    assert "return existing" in source


def test_workspace_and_primary_cas_roots_are_pairwise_disjoint() -> None:
    source = inspect.getsource(workspace_impl.IsolatedAttemptCoordinator.__init__)
    assert "workspace parent and primary checkout" in source
    assert "workspace parent and source-tree store" in source
    assert "_is_same_or_within(left, right)" in source
    assert "_is_same_or_within(right, left)" in source


def test_lifecycle_modules_have_no_runtime_provider_or_promotion_authority() -> None:
    source = "\n".join(
        inspect.getsource(module)
        for module in (contracts, reader_impl, ledger_impl, workspace_impl)
    )
    forbidden = (
        "subprocess",
        "docker",
        "provider.invoke",
        "run_in_docker_sandbox",
        "OwnerApproval",
        "EffectLease",
        "promote_candidates",
        "merge_pull_request",
        "git checkout",
        "git reset",
        "git clean",
    )
    for token in forbidden:
        assert token not in source


def test_success_receipt_structurally_requires_candidate_tree() -> None:
    source = inspect.getsource(contracts.AttemptTerminalReceipt.__post_init__)
    assert 'self.outcome == "succeeded"' in source
    assert "successful attempt must bind a candidate source tree" in source
    assert "attempt terminal provenance must bind exactly its inputs" in source


def test_persisted_start_and_terminal_are_reparsed_before_use() -> None:
    start_source = inspect.getsource(ledger_impl.AttemptLedger._decode_start_intent)
    terminal_source = inspect.getsource(
        ledger_impl.AttemptLedger._decode_terminal_result
    )
    reader_source = inspect.getsource(reader_impl.read_attempt_intents)
    assert "_strict_json" in start_source
    assert "AttemptStartRecord.from_dict" in start_source
    assert "payload digest is invalid" in start_source
    assert "AttemptTerminalReceipt.from_dict" in terminal_source
    assert "effect_id does not bind receipt digest" in terminal_source
    assert "persisted attempt terminal event detail" in reader_source
    assert "event sequence is invalid" in reader_source


def test_public_mutation_api_has_no_caller_supplied_lifecycle_time() -> None:
    begin = inspect.signature(ledger_impl.AttemptLedger.begin)
    complete = inspect.signature(ledger_impl.AttemptLedger.complete)
    prepare = inspect.signature(workspace_impl.IsolatedAttemptCoordinator.prepare)
    assert "started_at" not in begin.parameters
    assert "started_at" not in prepare.parameters
    assert "completed_at" not in complete.parameters


def test_authority_time_is_sampled_inside_start_and_terminal_transitions() -> None:
    begin_source = inspect.getsource(ledger_impl.AttemptLedger.begin)
    complete_source = inspect.getsource(ledger_impl.AttemptLedger.complete)
    assert "started_at = _authority_now()" in begin_source
    assert begin_source.index("started_at = _authority_now()") < begin_source.index(
        "self.spine.record_intent"
    )
    assert "completed_at = _authority_now()" in complete_source
    assert complete_source.index("completed_at = _authority_now()") < complete_source.index(
        "self.spine.mark_completed"
    )
    assert "_require_authority_event_order" in inspect.getsource(
        ledger_impl.AttemptLedger._decode_start_intent
    )
    assert "_require_authority_event_order" in inspect.getsource(
        ledger_impl.AttemptLedger._decode_terminal_result
    )


def test_stable_attempts_import_path_is_a_thin_compatibility_surface() -> None:
    assert compatibility.AttemptLedger is ledger_impl.AttemptLedger
    assert (
        compatibility.IsolatedAttemptCoordinator
        is workspace_impl.IsolatedAttemptCoordinator
    )
    assert compatibility.AttemptStartRecord is contracts.AttemptStartRecord
    source = inspect.getsource(compatibility)
    assert "Compatibility surface" in source
    assert "sqlite3" not in source
    assert "class AttemptLedger" not in source
