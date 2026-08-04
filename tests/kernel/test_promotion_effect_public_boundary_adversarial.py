from __future__ import annotations

from types import ModuleType

import pytest

from daedalus.kairos.promotion_effect_public_boundary import (
    PromotionEffectPublicBoundaryError,
    _install_boundary,
)


def _modules():
    gated = ModuleType("daedalus.kairos.gated_writes")
    lifecycle = ModuleType("daedalus.kairos.promotion_effect_lifecycle")
    effects: list[str] = []

    def delegate(repo_root, candidates, **kwargs):
        effects.append(repo_root)
        return {"ok": True}

    def refusal(candidates, exc):
        return {"refused": [str(exc)], "promoted": []}

    def lifecycle_entry(*args, promotion_effect_capability, **kwargs):
        if promotion_effect_capability != "exact":
            raise ValueError("wrong capability")
        return lifecycle.gated_writes.promote_candidates(*args, **kwargs)

    gated.promote_candidates = delegate
    gated._promotion_refusal = refusal
    lifecycle.gated_writes = gated
    lifecycle.promote_candidates_with_effect_lifecycle = lifecycle_entry
    return gated, lifecycle, effects


def test_forged_marker_refuses_without_replacing_public_entrypoint():
    gated, lifecycle, effects = _modules()
    original = gated.promote_candidates
    gated._PROMOTION_EFFECT_PUBLIC_BOUNDARY_INSTALLATION = object()

    with pytest.raises(PromotionEffectPublicBoundaryError, match="unexpected type"):
        _install_boundary(gated.__dict__, lifecycle)

    assert gated.promote_candidates is original
    assert lifecycle.gated_writes is gated
    assert effects == []


def test_missing_refusal_helper_raises_without_entering_delegate():
    gated, lifecycle, effects = _modules()
    del gated._promotion_refusal
    _install_boundary(gated.__dict__, lifecycle)

    with pytest.raises(PromotionEffectPublicBoundaryError, match="mandatory"):
        gated.promote_candidates("/repo", [])

    assert effects == []


def test_wrong_capability_failure_does_not_leave_delegate_authorized():
    gated, lifecycle, effects = _modules()
    _install_boundary(gated.__dict__, lifecycle)

    with pytest.raises(ValueError, match="wrong capability"):
        gated.promote_candidates(
            "/repo",
            [],
            promotion_effect_capability="substituted",
        )
    with pytest.raises(PromotionEffectPublicBoundaryError, match="reachable only"):
        lifecycle.gated_writes.promote_candidates("/repo", [])
    assert effects == []


def test_lifecycle_facade_substitution_is_detected_on_replay():
    gated, lifecycle, effects = _modules()
    _install_boundary(gated.__dict__, lifecycle)
    lifecycle.gated_writes = ModuleType("substituted")

    with pytest.raises(PromotionEffectPublicBoundaryError, match="facade changed"):
        _install_boundary(gated.__dict__, lifecycle)
    assert effects == []


def test_receipt_projection_mutation_does_not_change_installed_authority():
    gated, lifecycle, effects = _modules()
    receipt = _install_boundary(gated.__dict__, lifecycle)
    projection = gated.promote_candidates.promotion_effect_boundary_receipt
    projection["direct_delegate_blocked"] = False
    projection["automatic_promotion_allowed"] = True

    replay = _install_boundary(gated.__dict__, lifecycle)
    assert replay == receipt
    assert replay.direct_delegate_blocked is True
    assert replay.automatic_promotion_allowed is False
    assert effects == []


def test_candidate_iterator_failure_still_refuses_without_delegate():
    gated, lifecycle, effects = _modules()
    _install_boundary(gated.__dict__, lifecycle)

    class Broken:
        def __iter__(self):
            raise ValueError("malformed")

    report = gated.promote_candidates("/repo", Broken())
    assert report["promoted"] == []
    assert report["promotion_effect_boundary"]["entered"] is False
    assert effects == []


def test_nested_public_calls_do_not_leak_scope_after_inner_failure():
    gated, lifecycle, effects = _modules()
    _install_boundary(gated.__dict__, lifecycle)
    original_lifecycle = lifecycle.promote_candidates_with_effect_lifecycle

    def nested(*args, promotion_effect_capability, **kwargs):
        assert promotion_effect_capability == "exact"
        with pytest.raises(ValueError, match="wrong capability"):
            gated.promote_candidates(
                "/inner",
                [],
                promotion_effect_capability="wrong",
            )
        return original_lifecycle(
            *args,
            promotion_effect_capability=promotion_effect_capability,
            **kwargs,
        )

    lifecycle.promote_candidates_with_effect_lifecycle = nested
    # The installer captured the exact lifecycle callable, so a later module
    # substitution cannot alter the installed route.
    report = gated.promote_candidates(
        "/outer",
        [],
        promotion_effect_capability="exact",
    )
    assert report == {"ok": True}
    assert effects == ["/outer"]
    with pytest.raises(PromotionEffectPublicBoundaryError, match="reachable only"):
        lifecycle.gated_writes.promote_candidates("/repo", [])
