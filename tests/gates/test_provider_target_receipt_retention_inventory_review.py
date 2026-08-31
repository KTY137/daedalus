from __future__ import annotations

import ast
import inspect
from pathlib import Path

from daedalus.gates import provider_target_receipt_retention_inventory as inventory
from daedalus.runtimes.contracts import retention as retention_contract

ROOT = Path(__file__).resolve().parents[2]


def _names(tree: ast.AST) -> set[str]:
    values: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            values.add(node.id)
        elif isinstance(node, ast.Attribute):
            values.add(node.attr)
    return values


def test_independent_review_finds_no_execution_or_write_authority() -> None:
    source = inspect.getsource(inventory)
    tree = ast.parse(source)
    names = _names(tree)

    assert not ({"subprocess", "socket", "requests", "urllib", "exec", "eval"} & names)
    assert "ProviderTargetReceiptLedger" not in inventory.__dict__
    assert "SourceTreeStore" not in inventory.__dict__
    assert "SpineLedger" not in inventory.__dict__
    assert "EffectExecutionRequest" not in inventory.__dict__

    public = inspect.signature(inventory.scan_provider_target_receipt_retention)
    assert list(public.parameters) == ["repository_root", "source_revision"]
    assert public.parameters["source_revision"].kind is inspect.Parameter.KEYWORD_ONLY


def test_independent_review_requires_non_authorizing_claims() -> None:
    source = "\n".join(
        (
            inspect.getsource(inventory),
            inspect.getsource(retention_contract),
        )
    )
    required = {
        '"wiring": "inventory_only"',
        '"guard_contract_bound": False',
        '"effect_lease_consumed": False',
        '"primary_checkout_target_proven": False',
        '"closed": False',
        '"canonical_inventory_integrated": False',
        '"guard_contracts_complete": False',
        '"effect_lease_semantics_verified": False',
        '"primary_checkout_mutation_excluded": False',
    }
    for claim in required:
        assert claim in source


def test_independent_review_covers_each_effectful_anchor() -> None:
    target = (
        ROOT / "daedalus/runtimes/provider_target_receipt_ledger.py"
    ).read_text(encoding="utf-8")
    inventory_source = inspect.getsource(inventory)
    for anchor in (
        "self.spine._txn",
        "connection.execute",
        "self.spine.record_intent",
        "self._install_single_receipt_invariant",
        "self._record_or_recover_intent",
        "self.source_store.put_bytes",
        "self.spine.mark_completed",
    ):
        assert anchor in target
        assert anchor in inventory_source


def test_scanner_source_contains_no_trust_escalation_vocabulary() -> None:
    source = inspect.getsource(inventory).lower()
    for forbidden in (
        "ownerapproval",
        "promotionreceipt",
        "provider_execution_allowed=true",
        "automatic promotion",
        "merge_pull_request",
    ):
        assert forbidden not in source
