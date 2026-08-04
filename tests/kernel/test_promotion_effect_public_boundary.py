from __future__ import annotations

import hashlib
import inspect
import json
from types import ModuleType
import threading

import pytest

from daedalus.kairos.promotion_effect_public_boundary import (
    PromotionEffectPublicBoundaryError,
    _install_boundary,
)


def _fixture(*, delegate=None):
    gated = ModuleType("daedalus.kairos.gated_writes")
    lifecycle = ModuleType("daedalus.kairos.promotion_effect_lifecycle")
    calls: list[tuple[tuple, dict]] = []

    if delegate is None:
        def delegate(repo_root, candidates, *, project=None, availability=None):
            calls.append(((repo_root, candidates), {
                "project": project,
                "availability": availability,
            }))
            return {"delegate": True, "candidate_count": len(candidates)}

    def refusal(candidates, exc):
        return {
            "promoted": [],
            "refused": [{"reason": str(exc)} for _ in (candidates or [None])],
            "not_gated": [],
            "integration_branch": None,
            "integration_revision": None,
            "authorization": None,
        }

    gated.promote_candidates = delegate
    gated._promotion_refusal = refusal
    lifecycle.gated_writes = gated

    def lifecycle_entry(*args, promotion_effect_capability, **kwargs):
        assert promotion_effect_capability == "capability"
        return lifecycle.gated_writes.promote_candidates(*args, **kwargs)

    lifecycle.promote_candidates_with_effect_lifecycle = lifecycle_entry
    return gated, lifecycle, calls, delegate


def test_installation_is_inert_and_receipt_is_canonical():
    gated, lifecycle, calls, delegate = _fixture()

    receipt = _install_boundary(gated.__dict__, lifecycle)

    assert calls == []
    assert receipt.entrypoint_id == "python.promote_candidates"
    assert receipt.direct_delegate_blocked is True
    assert receipt.automatic_promotion_allowed is False
    assert receipt.visible_signature == str(inspect.signature(delegate))
    body = receipt.to_dict()
    digest = body.pop("receipt_sha256")
    assert digest == hashlib.sha256(
        json.dumps(
            body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def test_missing_capability_refuses_before_delegate():
    gated, lifecycle, calls, _delegate = _fixture()
    _install_boundary(gated.__dict__, lifecycle)

    report = gated.promote_candidates(
        "/repo",
        [object()],
        project="demo",
        availability={},
    )

    assert calls == []
    assert report["promoted"] == []
    assert report["promotion_effect_boundary"] == {
        "schema": "daedalus-promotion-public-boundary/1",
        "entrypoint_id": "python.promote_candidates",
        "entered": False,
        "automatic_promotion_allowed": False,
        "reason": "missing_promotion_effect_capability",
    }


def test_exact_capability_path_enters_lifecycle_then_delegate_once():
    gated, lifecycle, calls, _delegate = _fixture()
    _install_boundary(gated.__dict__, lifecycle)

    report = gated.promote_candidates(
        "/repo",
        [object()],
        project="demo",
        availability={"git": True},
        promotion_effect_capability="capability",
    )

    assert report == {"delegate": True, "candidate_count": 1}
    assert len(calls) == 1
    assert calls[0][1] == {"project": "demo", "availability": {"git": True}}


def test_direct_delegate_and_direct_lifecycle_calls_are_blocked():
    gated, lifecycle, calls, _delegate = _fixture()
    _install_boundary(gated.__dict__, lifecycle)

    with pytest.raises(PromotionEffectPublicBoundaryError, match="reachable only"):
        lifecycle.gated_writes.promote_candidates(
            "/repo",
            [],
            project=None,
            availability={},
        )
    with pytest.raises(PromotionEffectPublicBoundaryError, match="reachable only"):
        lifecycle.promote_candidates_with_effect_lifecycle(
            "/repo",
            [],
            project=None,
            availability={},
            promotion_effect_capability="capability",
        )
    assert calls == []


def test_visible_metadata_is_preserved_without_wrapped_bypass():
    gated, lifecycle, _calls, delegate = _fixture()
    _install_boundary(gated.__dict__, lifecycle)

    public = gated.promote_candidates
    assert public.__name__ == delegate.__name__
    assert public.__qualname__ == delegate.__qualname__
    assert public.__module__ == delegate.__module__
    assert inspect.signature(public) == inspect.signature(delegate)
    assert not hasattr(public, "__wrapped__")
    assert public.promotion_effect_boundary_receipt["direct_delegate_blocked"] is True


def test_exact_reinstallation_is_read_only_and_tampering_refuses():
    gated, lifecycle, calls, _delegate = _fixture()
    first = _install_boundary(gated.__dict__, lifecycle)
    public = gated.promote_candidates

    second = _install_boundary(gated.__dict__, lifecycle)
    assert second == first
    assert gated.promote_candidates is public
    assert calls == []

    gated.promote_candidates = lambda *_args, **_kwargs: None
    with pytest.raises(PromotionEffectPublicBoundaryError, match="changed after"):
        _install_boundary(gated.__dict__, lifecycle)


def test_namespace_substitution_and_malformed_lifecycle_refuse():
    gated, lifecycle, _calls, _delegate = _fixture()
    other = ModuleType("other")
    other.promote_candidates = gated.promote_candidates
    other._promotion_refusal = gated._promotion_refusal

    with pytest.raises(PromotionEffectPublicBoundaryError, match="share identity"):
        _install_boundary(other.__dict__, lifecycle)

    malformed = ModuleType("malformed")
    malformed.gated_writes = gated
    with pytest.raises(PromotionEffectPublicBoundaryError, match="entrypoint is missing"):
        _install_boundary(gated.__dict__, malformed)


def test_exception_resets_delegate_scope():
    def exploding(repo_root, candidates, *, project=None, availability=None):
        raise RuntimeError("boom")

    gated, lifecycle, _calls, _delegate = _fixture(delegate=exploding)
    _install_boundary(gated.__dict__, lifecycle)

    with pytest.raises(RuntimeError, match="boom"):
        gated.promote_candidates(
            "/repo",
            [],
            project=None,
            availability={},
            promotion_effect_capability="capability",
        )
    with pytest.raises(PromotionEffectPublicBoundaryError, match="reachable only"):
        lifecycle.gated_writes.promote_candidates(
            "/repo",
            [],
            project=None,
            availability={},
        )


def test_context_scope_does_not_authorize_another_thread():
    entered = threading.Event()
    release = threading.Event()

    def blocking(repo_root, candidates, *, project=None, availability=None):
        entered.set()
        assert release.wait(timeout=5)
        return {"ok": True}

    gated, lifecycle, _calls, _delegate = _fixture(delegate=blocking)
    _install_boundary(gated.__dict__, lifecycle)
    result: list[dict] = []

    thread = threading.Thread(
        target=lambda: result.append(
            gated.promote_candidates(
                "/repo",
                [],
                project=None,
                availability={},
                promotion_effect_capability="capability",
            )
        )
    )
    thread.start()
    assert entered.wait(timeout=5)
    try:
        with pytest.raises(PromotionEffectPublicBoundaryError, match="reachable only"):
            lifecycle.gated_writes.promote_candidates(
                "/repo",
                [],
                project=None,
                availability={},
            )
    finally:
        release.set()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert result == [{"ok": True}]
