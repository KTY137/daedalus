"""Compatibility strangler for the sealed Kairos promotion seam.

The historical gating implementation remains byte-identical as a non-importable
package resource. It is verified against its exact Git blob identity and then
executed into this module's namespace so existing classes, functions, import
paths, pickle names and function globals stay compatible; only the public
promotion callable is replaced.
"""
from __future__ import annotations

import hashlib as _hashlib
import hmac as _hmac
from importlib.resources import files as _resource_files


_RETAINED_SOURCE_NAME = "_gated_writes_legacy.py.src"
_RETAINED_SOURCE_GIT_BLOB_SHA1 = "e31d24ec67f7c208ace34f5dd2e9fefe4e654a86"


def _git_blob_sha1(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return _hashlib.sha1(header + data, usedforsecurity=False).hexdigest()


def _verify_retained_source(data: bytes) -> bytes:
    """Refuse altered dynamically executed package data.

    The retained source is an exact blob already committed in Git. Binding its
    package bytes to that blob identity prevents packaging drift or a replaced
    resource from becoming an unreviewed effectful implementation. This is an
    integrity check over repository-owned bytes, not an authentication secret.
    """
    actual = _git_blob_sha1(data)
    if not _hmac.compare_digest(actual, _RETAINED_SOURCE_GIT_BLOB_SHA1):
        raise RuntimeError(
            "retained gated-write source integrity mismatch: "
            f"expected Git blob {_RETAINED_SOURCE_GIT_BLOB_SHA1}, got {actual}"
        )
    return data


_retained_source = _resource_files(__package__).joinpath(_RETAINED_SOURCE_NAME)
_retained_source_bytes = _verify_retained_source(_retained_source.read_bytes())
exec(
    compile(_retained_source_bytes, str(_retained_source), "exec"),
    globals(),
)

# Remove the historical callable immediately after materializing the retained
# implementation. No second module exists and no reference to the former
# unpersisted mutation seam is kept. Existing retained functions resolve the
# global name ``promote_candidates`` dynamically and therefore see the sealed
# replacement defined below.
del promote_candidates

from daedalus.kernel.promotion import (
    PromotionAuthorizationError,
    snapshot_promotion_candidates as _snapshot_promotion_candidates,
)


__doc__ = """Compatibility strangler for the sealed Kairos promotion seam.

All non-promotion symbols retain the canonical
``daedalus.kairos.gated_writes`` module identity. The old promotion callable is
removed before the persisted-authority replacement is defined.
"""


def _retired_legacy_promotion(*_args, **_kwargs):
    raise PromotionAuthorizationError(
        "the retained legacy promotion callable is retired; use "
        "daedalus.kairos.gated_writes.promote_candidates"
    )


class _LegacyFacade:
    """Test/review facade over retained helpers, never a second module.

    Attribute writes delegate to this module so monkeypatch-based compatibility
    tests continue to intercept the exact helper used by the sealed callable.
    The retired promotion function is the only deliberately divergent symbol.
    """

    def __getattr__(self, name: str):
        if name == "promote_candidates":
            return _retired_legacy_promotion
        try:
            return globals()[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value) -> None:
        if name == "promote_candidates":
            raise AttributeError("legacy promotion authority is retired")
        globals()[name] = value


_legacy = _LegacyFacade()


def _promotion_refusal(candidates: list[Any], exc: BaseException) -> dict[str, Any]:
    subjects = candidates if candidates else [None]
    return {
        "promoted": [],
        "refused": [
            {
                "task_id": getattr(
                    getattr(candidate, "result", None), "task_id", "unknown"
                ),
                "promoted": False,
                "reason": (
                    "promotion authorization refused: "
                    f"{type(exc).__name__}: {exc}"
                ),
            }
            for candidate in subjects
        ],
        "not_gated": [],
        "integration_branch": None,
        "authorization": None,
    }


def _legacy_unpersisted_refusal(candidates: list[Any]) -> dict[str, Any]:
    """Preserve the historical call shape without performing any effect.

    A previous compatibility adapter executed ``git rev-parse`` to improve the
    refusal message before a persisted ApprovalLedger and owner keyring were
    present. That process spawn was still an effect and therefore belonged
    behind the same authority boundary as the later promotion work. Legacy
    callers now receive one deterministic refusal without Git, lock, worktree,
    ledger discovery, provider access or repository mutation.
    """
    return _promotion_refusal(
        candidates,
        PromotionAuthorizationError(
            "persisted ApprovalLedger and owner keyring are mandatory before "
            "any promotion effect"
        ),
    )


def promote_candidates(
    repo_root: str,
    candidates: list[GatedCandidate],
    *,
    project: str | None,
    availability: dict,
    consumed_approval,
    evidence_packet,
    target_ref: str,
    approval_ledger=None,
    owner_keyring: Mapping[tuple[str, str], bytes | str] | None = None,
    ledger_path=None,
    lock_timeout_s: float = 120.0,
    gate_timeout_s: float = 900.0,
    cancel: Any = None,
) -> dict:
    """Promote one exact, persisted-owner-authorized candidate into a branch.

    This is still an explicit owner operation and never merges the integration
    branch. Persisted approval re-authentication and the live target-HEAD read
    occur while the cross-process promotion lock is held, immediately before
    the retained integration-worktree implementation is entered.

    The historical multi-candidate retry path is intentionally frozen here.
    It may regenerate a stale candidate after authorization, yielding bytes
    that the owner never approved. Until promotion consumes one combined CAS
    source-tree candidate, this sealed compatibility seam accepts exactly one
    clean candidate and requires its base revision to equal the authorized live
    target revision. Every refusal happens before worktree creation.

    Candidate material is snapshotted before the lock manager is constructed.
    The immutable local snapshot is used for authorization and for the retained
    apply path, so a caller cannot swap a mutable ``GatedCandidate.result``
    between those two operations.
    """
    try:
        root = Path(repo_root).resolve()
    except (TypeError, ValueError, OSError) as exc:
        return _promotion_refusal(
            [],
            PromotionAuthorizationError(f"invalid repository root: {exc}"),
        )
    try:
        submitted_candidates = tuple(candidates)
    except TypeError:
        return _promotion_refusal(
            [],
            PromotionAuthorizationError(
                "promotion candidates must be an iterable batch"
            ),
        )

    # Compatibility is fail-closed: old callers still receive a structured
    # diagnostic, but no path without persisted authority may execute Git,
    # acquire the lock, discover a ledger or construct a worktree manager.
    if approval_ledger is None or not owner_keyring:
        return _legacy_unpersisted_refusal(list(submitted_candidates))

    # Exact candidate identity is an authorization input. Do not silently
    # discard an ungated member and then authorize only a subset of the batch.
    if len(submitted_candidates) != 1:
        return _promotion_refusal(
            list(submitted_candidates),
            PromotionAuthorizationError(
                "sealed legacy promotion requires exactly one candidate"
            ),
        )
    try:
        sealed_candidates = list(
            _snapshot_promotion_candidates(submitted_candidates)
        )
    except Exception as exc:  # noqa: BLE001 - public boundary fails closed
        return _promotion_refusal(list(submitted_candidates), exc)

    candidate = sealed_candidates[0]
    result = candidate.result
    artifact = result.artifact

    try:
        manager = GitWorktreeManager(root)
        if ledger_path is None:
            from daedalus.spine.picker import resolve_spine_db_path

            ledger_path, ledger_error = resolve_spine_db_path(root)
            if ledger_error or ledger_path is None:
                raise PromotionAuthorizationError(
                    f"ledger unavailable: {ledger_error}"
                )
        lock_path = manager.worktree_root / "promotion.lock"
    except Exception as exc:  # noqa: BLE001 - infrastructure refusal, no mutation
        return _promotion_refusal(sealed_candidates, exc)

    try:
        with _PromotionLock(lock_path, timeout_s=lock_timeout_s):
            # These imports are deliberately inside the locked region. The
            # target ref is sampled only after lock acquisition, and the exact
            # persisted approval is re-authenticated before _promote_locked can
            # create an integration worktree.
            from daedalus.kernel.promotion import (
                authorize_persisted_promotion,
                resolve_live_target_revision,
            )

            # Temporary registry-anchor adapter: the effect inventory still
            # names the historical call anchor ``authorize_promotion``. Bind
            # that local name to the stronger persisted primitive until the
            # registry row moves in its own small Work Packet.
            authorize_promotion = authorize_persisted_promotion
            live_target_revision = resolve_live_target_revision(root, target_ref)
            authorization = authorize_promotion(
                approval_ledger=approval_ledger,
                owner_keyring=owner_keyring,
                consumed_approval=consumed_approval,
                evidence_packet=evidence_packet,
                candidates=sealed_candidates,
                target_ref=target_ref,
                live_target_revision=live_target_revision,
            )
            if artifact.base_revision != authorization.live_target_revision:
                raise PromotionAuthorizationError(
                    "candidate base is not the authorized live target revision; "
                    "stale regeneration requires new evidence and OwnerApproval"
                )

            report = _promote_locked(
                root,
                manager,
                sealed_candidates,
                project=project,
                availability=availability,
                ledger_path=ledger_path,
                gate_timeout_s=gate_timeout_s,
                cancel=cancel,
            )
    except PromotionUnavailable as exc:
        return _promotion_refusal(sealed_candidates, exc)
    except Exception as exc:  # noqa: BLE001 - public effect boundary fails closed
        return _promotion_refusal(sealed_candidates, exc)

    report["not_gated"] = []
    report["authorization"] = authorization.to_dict()
    return report


__all__ = tuple(sorted(name for name in globals() if not name.startswith("_")))