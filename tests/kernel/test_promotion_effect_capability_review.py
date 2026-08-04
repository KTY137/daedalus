from __future__ import annotations

import ast
import inspect
from pathlib import Path

from daedalus.kernel.promotion_effects import (
    PROMOTION_EFFECTS,
    PROMOTION_ENTRYPOINT_ID,
    PROMOTION_GUARD_CONTRACTS,
    PROMOTION_TARGET,
    PromotionEffectCapability,
)
from daedalus.spine.effect_boundary import REGISTRY_BY_ID, Wiring


SOURCE = Path("daedalus/kernel/promotion_effects.py")


def test_capability_is_inert_and_does_not_create_competing_authority() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    called_attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert "issue_effect_lease" not in imported
    assert "issue_owner_approval" not in imported
    assert "authorize_promotion" not in imported
    assert "promote_candidates" not in imported
    assert "issue_effect_lease" not in called_names
    assert "subprocess" not in source
    assert "os.system" not in source
    assert "GitWorktreeManager" not in source
    assert "run_in_docker_sandbox" not in source
    assert {"grant", "begin_effect", "finish_effect"} <= called_attributes


def test_capability_contract_is_exact_and_canonical_registry_stays_blocked() -> None:
    assert PROMOTION_ENTRYPOINT_ID == "python.promote_candidates"
    assert PROMOTION_TARGET == "daedalus.kairos.gated_writes:promote_candidates"
    assert PROMOTION_EFFECTS == (
        "filesystem_write",
        "process_spawn",
        "repository_mutation",
    )
    assert PROMOTION_GUARD_CONTRACTS == (
        "containment.worktree",
        "promotion.owner_approval",
        "spine.intent_ledger",
    )

    canonical = REGISTRY_BY_ID[PROMOTION_ENTRYPOINT_ID]
    assert canonical.wiring is Wiring.LOCAL_GUARDS
    assert canonical.target == PROMOTION_TARGET
    assert tuple(sorted(effect.value for effect in canonical.effects)) == PROMOTION_EFFECTS
    assert tuple(sorted(canonical.guard_contracts)) == PROMOTION_GUARD_CONTRACTS


def test_public_methods_do_not_accept_caller_owned_time_or_authority() -> None:
    signatures = {
        name: tuple(inspect.signature(getattr(PromotionEffectCapability, name)).parameters)
        for name in ("grant", "begin", "finish")
    }
    assert signatures["grant"] == ("self",)
    assert signatures["begin"] == ("self",)
    assert signatures["finish"] == (
        "self",
        "start_receipt",
        "outcome",
        "output_digests",
        "detail_sha256",
    )


def test_source_requires_all_subject_and_guard_bindings() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    required_fragments = (
        "promotion authorization digest does not bind its fields",
        '"request_attempt"',
        '"execution_id"',
        '"idempotency_key"',
        "request.provenance.input_digests",
        "candidate_artifact_sha256",
        "evidence_packet_sha256",
        "approval_consumption_sha256",
        "promotion.owner_approval",
        "owner-approval guard evidence does not bind approval consumption",
        '"git" not in scope.tools',
        "row.wiring is not Wiring.CENTRAL",
    )
    for fragment in required_fragments:
        assert fragment in source
