from __future__ import annotations

import ast
import inspect
import json
import textwrap
from pathlib import Path

from daedalus.kernel import AttemptLedger, IsolatedAttemptCoordinator
from daedalus.spine.effect_boundary import ENTRYPOINTS


ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "docs/work-packets/G0-ATT-13B_EFFECT_INVENTORY.json"
EXPECTED = {
    "daedalus.kernel.attempt_ledger:AttemptLedger.begin": {
        "registry_id": "kernel.attempt.begin",
        "effects": ["filesystem_write"],
        "guards": ["spine.intent_ledger"],
        "anchors": ["record_intent"],
    },
    "daedalus.kernel.attempt_ledger:AttemptLedger.complete": {
        "registry_id": "kernel.attempt.complete",
        "effects": ["filesystem_write"],
        "guards": ["spine.intent_ledger"],
        "anchors": ["mark_completed"],
    },
    "daedalus.kernel.attempt_workspace:IsolatedAttemptCoordinator.prepare": {
        "registry_id": "kernel.attempt.prepare",
        "effects": ["filesystem_write"],
        "guards": ["spine.intent_ledger", "containment.attempt"],
        "anchors": ["begin", "materialize_tree"],
    },
}


def _called_names(function) -> set[str]:
    # inspect.getsource of a METHOD keeps its class-body indentation, and
    # ast.parse refuses indented module text -- so without the dedent this
    # helper raised IndentationError before any anchor assertion could run.
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        current = node.func
        parts: list[str] = []
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        if parts:
            names.add(".".join(reversed(parts)))
    return names


def test_public_attempt_effects_are_registered_or_explicit_blockers() -> None:
    review = json.loads(REVIEW.read_text(encoding="utf-8"))
    assert review["schema"] == "daedalus-gate0-effect-inventory-review/1"
    assert review["security_boundary_claimed"] is False

    registry = {row.target: row for row in ENTRYPOINTS}
    blockers = {row["target"]: row for row in review["findings"]}
    assert set(blockers) <= set(EXPECTED)

    for target, expected in EXPECTED.items():
        registered = registry.get(target)
        blocker = blockers.get(target)
        assert (registered is None) != (blocker is None), (
            f"{target} must have exactly one canonical registry row or one open "
            "machine-readable blocker"
        )
        if registered is not None:
            assert registered.id == expected["registry_id"]
            assert [effect.value for effect in registered.effects] == expected["effects"]
            assert list(registered.guard_contracts) == expected["guards"]
            assert [anchor.call for anchor in registered.anchors] == expected["anchors"]
        else:
            assert review["status"] == "open"
            assert blocker["severity"] == "blocker"
            assert blocker["current_wiring"] == "unregistered"
            assert blocker["registry_id"] == expected["registry_id"]
            assert blocker["effects"] == expected["effects"]
            assert blocker["required_guards"] == expected["guards"]
            assert blocker["anchors"] == expected["anchors"]


def test_inventory_targets_exist_on_the_stable_public_kernel_surface() -> None:
    assert AttemptLedger.begin.__module__ == "daedalus.kernel.attempt_ledger"
    assert AttemptLedger.complete.__module__ == "daedalus.kernel.attempt_ledger"
    assert (
        IsolatedAttemptCoordinator.prepare.__module__
        == "daedalus.kernel.attempt_workspace"
    )


def test_inventory_anchors_are_mechanically_present() -> None:
    calls = {
        "daedalus.kernel.attempt_ledger:AttemptLedger.begin": _called_names(
            AttemptLedger.begin
        ),
        "daedalus.kernel.attempt_ledger:AttemptLedger.complete": _called_names(
            AttemptLedger.complete
        ),
        "daedalus.kernel.attempt_workspace:IsolatedAttemptCoordinator.prepare": _called_names(
            IsolatedAttemptCoordinator.prepare
        ),
    }
    for target, expected in EXPECTED.items():
        for anchor in expected["anchors"]:
            assert any(
                called == anchor or called.endswith("." + anchor)
                for called in calls[target]
            ), f"{target} no longer calls required anchor {anchor}"


def test_blocker_cannot_be_marked_resolved_while_targets_are_unregistered() -> None:
    review = json.loads(REVIEW.read_text(encoding="utf-8"))
    registry_targets = {row.target for row in ENTRYPOINTS}
    unresolved = [
        row for row in review["findings"] if row["target"] not in registry_targets
    ]
    if unresolved:
        assert review["status"] == "open"
        assert review["verification_state"]["registry_patch"] == "open"
        assert review["verification_state"]["independent_review"] == "open"
