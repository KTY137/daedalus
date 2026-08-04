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
from daedalus.kernel.promotion_execution import PromotionExecutionLedger
from daedalus.kernel.promotion_fingerprint import fingerprint_primary_checkout


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
        "integration_revision": None,
        "authorization": None,
    }


def _legacy_unpersisted_refusal(candidates: list[Any]) -> dict[str, Any]:
    """Preserve the historical call shape without performing any effect."""
    return _promotion_refusal(
        candidates,
        PromotionAuthorizationError(
            "persisted ApprovalLedger, owner keyring and PromotionExecutionLedger "
            "are mandatory before any promotion effect"
        ),
    )


def _execution_pending_refusal(candidates, authorization, exc) -> dict[str, Any]:
    report = _promotion_refusal(candidates, exc)
    report["authorization"] = authorization.to_dict()
    report["promotion_execution_pending_reconciliation"] = True
    return report


def _complete_refusal(
    execution_ledger,
    start,
    candidates,
    authorization,
    root,
    exc,
):
    report = _promotion_refusal(candidates, exc)
    report["authorization"] = authorization.to_dict()
    try:
        primary_after = fingerprint_primary_checkout(root)
        completion = execution_ledger.complete(
            start,
            receipt_id=f"promotion-receipt-{authorization.authorization_sha256[:24]}",
            outcome="refused",
            report=report,
            primary_checkout_after_sha256=primary_after,
        )
    except Exception as terminal_error:  # noqa: BLE001 - retain pending truth
        return _execution_pending_refusal(
            candidates,
            authorization,
            PromotionAuthorizationError(
                "promotion was refused after its persisted start, but terminal "
                f"accounting requires reconciliation: {type(terminal_error).__name__}"
            ),
        )
    return completion.report_dict()


def _complete_fault(
    execution_ledger,
    start,
    candidates,
    authorization,
    root,
    exc,
    *,
    report=None,
    integration_branch=None,
    integration_revision=None,
):
    # A fault report must remain persistable even when the retained implementation
    # returned a malformed, oversized or non-JSON object. Raw untrusted report
    # material is deliberately not copied into the canonical terminal event.
    fault_report = {
        "promoted": [],
        "refused": [],
        "not_gated": [],
        "integration_branch": integration_branch,
        "integration_revision": integration_revision,
        "authorization": authorization.to_dict(),
        "fault": f"{type(exc).__name__}",
        "observed_report": report is not None,
    }
    try:
        primary_after = fingerprint_primary_checkout(root)
        completion = execution_ledger.complete(
            start,
            receipt_id=f"promotion-receipt-{authorization.authorization_sha256[:24]}",
            outcome="faulted",
            report=fault_report,
            integration_branch=integration_branch,
            integration_revision=integration_revision,
            primary_checkout_after_sha256=primary_after,
        )
    except Exception as terminal_error:  # noqa: BLE001 - retain pending truth
        return _execution_pending_refusal(
            candidates,
            authorization,
            PromotionAuthorizationError(
                "promotion fault occurred after its persisted start, but terminal "
                f"accounting requires reconciliation: {type(terminal_error).__name__}"
            ),
        )
    return completion.report_dict()


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
    promotion_execution_ledger=None,
    ledger_path=None,
    lock_timeout_s: float = 120.0,
    gate_timeout_s: float = 900.0,
    cancel: Any = None,
) -> dict:
    """Promote one exact candidate into an unmerged integration branch.

    Persisted owner authority is authenticated before any repository effect.
    The exact promotion execution start is then committed before lock-file or
    worktree mutation. Restart replay returns the retained terminal report, and
    an unresolved start never re-executes automatically.
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

    if (
        approval_ledger is None
        or not owner_keyring
        or not isinstance(promotion_execution_ledger, PromotionExecutionLedger)
    ):
        return _legacy_unpersisted_refusal(list(submitted_candidates))

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
    artifact = candidate.result.artifact

    try:
        from daedalus.kernel.promotion import authorize_persisted_promotion

        authorization = authorize_persisted_promotion(
            approval_ledger=approval_ledger,
            owner_keyring=owner_keyring,
            consumed_approval=consumed_approval,
            evidence_packet=evidence_packet,
            candidates=sealed_candidates,
            target_ref=target_ref,
            live_target_revision=(
                consumed_approval.verified.expected_target_revision
            ),
        )
    except Exception as exc:  # noqa: BLE001 - no effect has occurred
        return _promotion_refusal(sealed_candidates, exc)

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
        primary_before = fingerprint_primary_checkout(root)
        begin = promotion_execution_ledger.begin(
            authorization,
            start_id=f"promotion-start-{authorization.authorization_sha256[:24]}",
            primary_checkout_before_sha256=primary_before,
        )
    except Exception as exc:  # noqa: BLE001 - no promotion mutation occurred
        return _promotion_refusal(sealed_candidates, exc)

    if not begin.execute:
        if begin.completion is not None:
            return begin.completion.report_dict()
        return _execution_pending_refusal(
            sealed_candidates,
            authorization,
            PromotionAuthorizationError(
                "promotion has a persisted unresolved start; reconcile it before retry"
            ),
        )

    report: dict[str, Any] | None = None
    integration_branch: str | None = None
    integration_revision: str | None = None
    mutation_entered = False
    try:
        with _PromotionLock(lock_path, timeout_s=lock_timeout_s):
            from daedalus.kernel.promotion import (
                authorize_persisted_promotion,
                resolve_live_target_revision,
            )

            authorize_promotion = authorize_persisted_promotion
            live_target_revision = resolve_live_target_revision(root, target_ref)
            live_authorization = authorize_promotion(
                approval_ledger=approval_ledger,
                owner_keyring=owner_keyring,
                consumed_approval=consumed_approval,
                evidence_packet=evidence_packet,
                candidates=sealed_candidates,
                target_ref=target_ref,
                live_target_revision=live_target_revision,
            )
            if live_authorization.authorization_sha256 != authorization.authorization_sha256:
                raise PromotionAuthorizationError(
                    "live promotion authorization differs from persisted start"
                )
            if artifact.base_revision != live_authorization.live_target_revision:
                raise PromotionAuthorizationError(
                    "candidate base is not the authorized live target revision; "
                    "stale regeneration requires new evidence and OwnerApproval"
                )

            mutation_entered = True
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
            if isinstance(report, Mapping):
                observed_branch = report.get("integration_branch")
                if isinstance(observed_branch, str) and observed_branch:
                    integration_branch = observed_branch
            report["not_gated"] = []
            report["authorization"] = authorization.to_dict()

            promoted = report.get("promoted")
            refused = report.get("refused")
            if not isinstance(promoted, list) or not isinstance(refused, list):
                raise PromotionAuthorizationError(
                    "promotion implementation returned a malformed report"
                )
            if len(promoted) == 1 and not refused:
                if not isinstance(integration_branch, str) or not integration_branch:
                    raise PromotionAuthorizationError(
                        "successful promotion omitted its integration branch"
                    )
                integration_revision = resolve_live_target_revision(
                    root,
                    integration_branch,
                )
                report["integration_revision"] = integration_revision
                outcome = "faulted" if report.get("cleanup_error") else "succeeded"
            elif not promoted and refused:
                integration_branch = None
                integration_revision = None
                report["integration_branch"] = None
                report["integration_revision"] = None
                outcome = "faulted" if report.get("cleanup_error") else "refused"
            else:
                raise PromotionAuthorizationError(
                    "promotion result is neither one success nor one refusal"
                )
    except PromotionUnavailable as exc:
        if mutation_entered:
            return _complete_fault(
                promotion_execution_ledger,
                begin.start,
                sealed_candidates,
                authorization,
                root,
                exc,
                report=report,
                integration_branch=integration_branch,
                integration_revision=integration_revision,
            )
        return _complete_refusal(
            promotion_execution_ledger,
            begin.start,
            sealed_candidates,
            authorization,
            root,
            exc,
        )
    except PromotionAuthorizationError as exc:
        if mutation_entered:
            return _complete_fault(
                promotion_execution_ledger,
                begin.start,
                sealed_candidates,
                authorization,
                root,
                exc,
                report=report,
                integration_branch=integration_branch,
                integration_revision=integration_revision,
            )
        return _complete_refusal(
            promotion_execution_ledger,
            begin.start,
            sealed_candidates,
            authorization,
            root,
            exc,
        )
    except Exception as exc:  # noqa: BLE001 - retain explicit terminal fault
        return _complete_fault(
            promotion_execution_ledger,
            begin.start,
            sealed_candidates,
            authorization,
            root,
            exc,
            report=report,
            integration_branch=integration_branch,
            integration_revision=integration_revision,
        )

    try:
        primary_after = fingerprint_primary_checkout(root)
        completion = promotion_execution_ledger.complete(
            begin.start,
            receipt_id=f"promotion-receipt-{authorization.authorization_sha256[:24]}",
            outcome=outcome,
            report=report,
            integration_branch=integration_branch,
            integration_revision=integration_revision,
            primary_checkout_after_sha256=primary_after,
        )
    except Exception as exc:  # noqa: BLE001 - successful output is not released
        return _complete_fault(
            promotion_execution_ledger,
            begin.start,
            sealed_candidates,
            authorization,
            root,
            exc,
            report=report,
            integration_branch=integration_branch,
            integration_revision=integration_revision,
        )
    return completion.report_dict()


__all__ = tuple(sorted(name for name in globals() if not name.startswith("_")))

# Install the manager audit only after the sealed public callable exists. The
# installers preserve the public PromotionExecutionLedger class and wrap only
# a caller-supplied, already-typed ledger instance for the duration of one call.
from .promotion_manager_boundary import (
    install_promotion_manager_boundary as _install_promotion_manager_boundary,
)
from .promotion_manager_replay import (
    install_promotion_manager_replay_boundary as _install_promotion_manager_replay_boundary,
)

_install_promotion_manager_boundary(globals())
_install_promotion_manager_replay_boundary(globals())
del _install_promotion_manager_boundary
del _install_promotion_manager_replay_boundary
