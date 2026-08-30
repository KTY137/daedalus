# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import inspect

import daedalus.kernel.attempt_ledger as ledger_impl
import daedalus.kernel.attempt_workspace as workspace_impl


def test_ledger_requires_and_retains_one_exact_source_store() -> None:
    init_source = inspect.getsource(ledger_impl.AttemptLedger.__init__)
    coordinator_source = inspect.getsource(
        workspace_impl.IsolatedAttemptCoordinator.__init__
    )
    assert "source_store: SourceTreeStore" in init_source
    assert "self.source_store = source_store" in init_source
    assert "ledger.source_store is not source_store" in coordinator_source
    assert "share the exact SourceTreeStore" in coordinator_source


def test_begin_reloads_input_manifest_from_selected_store_before_spine_write() -> None:
    source = inspect.getsource(ledger_impl.AttemptLedger.begin)
    assert source.index("self.source_store.load_tree(input_tree.ref)") < source.index(
        "self.spine.record_intent"
    )
    assert "input tree manifest differs from the ledger CAS object" in source


def test_terminal_material_is_verified_before_receipt_construction() -> None:
    source = inspect.getsource(ledger_impl.AttemptLedger.complete)
    report_at = source.index("self.source_store.read_bytes(report")
    candidate_at = source.index("self.source_store.load_tree(candidate_tree.ref)")
    receipt_at = source.index("AttemptTerminalReceipt(")
    assert report_at < receipt_at
    assert candidate_at < receipt_at
    assert "candidate tree manifest differs from the ledger CAS object" in source


def test_persisted_terminal_replay_reverifies_report_and_candidate_objects() -> None:
    source = inspect.getsource(ledger_impl.AttemptLedger._completion_for)
    assert "self.source_store.read_bytes(receipt.report" in source
    assert "self.source_store.load_tree(receipt.candidate_tree)" in source
    assert "persisted candidate tree revision differs" in source


def test_no_cas_reference_is_accepted_by_shape_only() -> None:
    ledger_source = inspect.getsource(ledger_impl)
    workspace_source = inspect.getsource(workspace_impl)
    source = ledger_source + "\n" + workspace_source
    assert "isinstance(input_tree, StoredSourceTree)" in source
    assert "isinstance(report, ArtifactRef)" in source
    assert "isinstance(candidate_tree, StoredSourceTree)" in source
    assert "isinstance(source_store, SourceTreeStore)" in source
