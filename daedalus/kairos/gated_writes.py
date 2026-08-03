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

from daedalus.kernel.promotion import PromotionAuthorizationError


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
            for candidate in candidates
        ],
        "not_gated": [],
        "integration_branch": None,
        "authorization": None,
    }


def _legacy_unpersisted_refusal(
    root: Path,
    candidates: list[Any],
    *,
    consumed_approval,
    evidence_packet,
    target_ref: str,
) -> dict[str, Any]:
    """Preserve old negative-call diagnostics without granting authority.

    Historical callers did not supply every persisted authority. They remain
    import/call compatible, but this adapter can only refuse. A pure binding
    preflight is used solely to retain a precise stale-head or candidate
    mismatch reason; even a successful preflight is converted into a
    persisted-authority-required refusal and cannot reach a lock or worktree.
    """
    try:
        from daedalus.kernel.promotion import (
            authorize_promotion,
            resolve_live_target_revision,
        )

        live_target_revision = resolve_live_target_revision(root, target_ref)
        authorize_promotion(
            consumed_approval=consumed_approval,
            evidence_packet=evidence_packet,
            candidates=candidates,
            target_ref=target_ref,
            live_target_revision=live_target_revision,
        )
    except Exception as exc:  # noqa: BLE001 - diagnostic refusal only
        return _promotion_refusal(candidates, exc)
    return _promotion_refusal(
        candidates,
        PromotionAuthorizationError(
            "persisted ApprovalLedger, owner keyring and PromotionLedger "
            "are mandatory"
        ),
    )


def _run_primary_git(root: Path, args: list[str]) -> bytes:
    """Run one read-only, non-interactive Git query against the primary tree."""
    pre: list[str] = []
    for key_value in _GIT_EXEC_CONFIG:
        pre += ["-c", key_value]
    env = _hardened_env()
    env["GIT_OPTIONAL_LOCKS"] = "0"
    proc = subprocess.run(
        ["git", "--no-optional-locks", *pre, *args],
        cwd=str(root),
        capture_output=True,
        check=False,
        timeout=30,
        env=env,
    )
    if proc.returncode != 0:
        raise PromotionAuthorizationError(
            f"primary checkout Git query failed: {args[0]}"
        )
    return bytes(proc.stdout)


def _primary_checkout_fingerprint(root: Path) -> tuple[str, bool]:
    """Bind HEAD and exact porcelain status without refreshing the Git index."""
    head = _run_primary_git(root, ["rev-parse", "--verify", "HEAD"]).strip()
    if len(head) not in {40, 64}:
        raise PromotionAuthorizationError(
            "primary checkout HEAD did not resolve to a revision"
        )
    status = _run_primary_git(
        root,
        [
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--ignore-submodules=none",
        ],
    )
    payload = (
        b"daedalus-primary-checkout/1\0"
        + head
        + b"\0"
        + _hashlib.sha256(status).digest()
    )
    return _hashlib.sha256(payload).hexdigest(), not status


def _resolve_integration_revision(root: Path, branch: str) -> str:
    raw = _run_primary_git(
        root, ["rev-parse", "--verify", f"refs/heads/{branch}"]
    ).decode("ascii", "strict").strip()
    if len(raw) not in {40, 64} or any(ch not in "0123456789abcdef" for ch in raw):
        raise PromotionAuthorizationError(
            "integration branch did not resolve to a revision"
        )
    return raw


def _record_ids(authorization) -> tuple[str, str]:
    digest = str(authorization.authorization_sha256)
    if len(digest) != 64:
        raise PromotionAuthorizationError(
            "promotion authorization has no canonical digest"
        )
    token = digest[:32]
    return f"promotion-start-{token}", f"promotion-receipt-{token}"


def _terminal_response(
    completion,
    *,
    authorization,
    start,
    replayed: bool,
) -> dict[str, Any]:
    report = completion.report_dict()
    report["authorization"] = authorization.to_dict()
    report["promotion_start"] = start.to_dict()
    report["promotion_receipt"] = completion.receipt.to_dict()
    report["promotion_replayed"] = replayed
    return report


def _pending_response(candidates, *, authorization, start, reason: str) -> dict[str, Any]:
    task_id = getattr(getattr(candidates[0], "result", None), "task_id", "unknown")
    return {
        "promoted": [],
        "refused": [
            {
                "task_id": task_id,
                "promoted": False,
                "reason": reason,
            }
        ],
        "not_gated": [],
        "integration_branch": None,
        "authorization": authorization.to_dict(),
        "promotion_start": start.to_dict(),
        "promotion_receipt": None,
        "promotion_pending_reconciliation": True,
    }


def _classify_terminal_report(
    report: Mapping[str, object],
    *,
    primary_unchanged: bool,
) -> str:
    promoted = report.get("promoted", [])
    refused = report.get("refused", [])
    not_gated = report.get("not_gated", [])
    cleanup_error = report.get("cleanup_error")
    if not primary_unchanged:
        return "faulted"
    if (
        isinstance(promoted, list)
        and len(promoted) == 1
        and isinstance(promoted[0], Mapping)
        and promoted[0].get("promoted") is True
        and refused == []
        and not_gated == []
        and cleanup_error is None
    ):
        return "succeeded"
    if promoted == [] and (
        (isinstance(refused, list) and bool(refused))
        or (isinstance(not_gated, list) and bool(not_gated))
    ):
        return "refused"
    return "faulted"


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
    promotion_ledger=None,
    ledger_path=None,
    lock_timeout_s: float = 120.0,
    gate_timeout_s: float = 900.0,
    cancel: Any = None,
) -> dict:
    """Promote one exact candidate with persisted start and terminal receipts.

    The operation remains an explicit owner action and never merges the
    integration branch. Under the cross-process promotion lock it re-reads the
    live target, re-authenticates the persisted OwnerApproval, requires a clean
    primary checkout, persists a PromotionStartRecord, and only then enters the
    retained integration-worktree implementation.

    Exact terminal replay returns the persisted report without re-execution.
    A start without a terminal receipt is an unknown outcome and is never
    retried automatically; an operator must reconcile it.
    """
    root = Path(repo_root).resolve()

    if approval_ledger is None or not owner_keyring or promotion_ledger is None:
        return _legacy_unpersisted_refusal(
            root,
            candidates,
            consumed_approval=consumed_approval,
            evidence_packet=evidence_packet,
            target_ref=target_ref,
        )

    if len(candidates) != 1:
        return _promotion_refusal(
            candidates,
            PromotionAuthorizationError(
                "sealed legacy promotion requires exactly one candidate"
            ),
        )
    candidate = candidates[0]
    result = getattr(candidate, "result", None)
    artifact = getattr(result, "artifact", None)
    if (
        not bool(getattr(result, "ok", False))
        or artifact is None
        or bool(getattr(artifact, "is_empty", True))
    ):
        return _promotion_refusal(
            candidates,
            PromotionAuthorizationError(
                "sealed legacy promotion requires one clean non-empty candidate"
            ),
        )

    from daedalus.kernel.promotion_receipts import PromotionLedger

    if not isinstance(promotion_ledger, PromotionLedger):
        return _promotion_refusal(
            candidates,
            PromotionAuthorizationError(
                "sealed promotion requires the canonical PromotionLedger"
            ),
        )

    manager = GitWorktreeManager(root)
    if ledger_path is None:
        from daedalus.spine.picker import resolve_spine_db_path

        ledger_path, ledger_error = resolve_spine_db_path(root)
        if ledger_error or ledger_path is None:
            return {
                "promoted": [],
                "not_gated": [],
                "integration_branch": None,
                "authorization": None,
                "refused": [
                    {
                        "task_id": result.task_id,
                        "promoted": False,
                        "reason": f"ledger unavailable: {ledger_error}",
                    }
                ],
            }

    lock_path = manager.worktree_root / "promotion.lock"
    authorization = None
    begin_result = None
    receipt_id = None
    try:
        with _PromotionLock(lock_path, timeout_s=lock_timeout_s):
            from daedalus.kernel.promotion import (
                authorize_persisted_promotion,
                resolve_live_target_revision,
            )

            authorize_promotion = authorize_persisted_promotion
            live_target_revision = resolve_live_target_revision(root, target_ref)
            authorization = authorize_promotion(
                approval_ledger=approval_ledger,
                owner_keyring=owner_keyring,
                consumed_approval=consumed_approval,
                evidence_packet=evidence_packet,
                candidates=candidates,
                target_ref=target_ref,
                live_target_revision=live_target_revision,
            )
            if str(artifact.base_revision) != authorization.live_target_revision:
                raise PromotionAuthorizationError(
                    "candidate base is not the authorized live target revision; "
                    "stale regeneration requires new evidence and OwnerApproval"
                )

            primary_before, primary_clean = _primary_checkout_fingerprint(root)
            if not primary_clean:
                raise PromotionAuthorizationError(
                    "primary checkout must be clean before promotion starts"
                )
            start_id, receipt_id = _record_ids(authorization)
            begin_result = promotion_ledger.begin(
                authorization,
                start_id=start_id,
                primary_checkout_before_sha256=primary_before,
            )
            if not begin_result.execute:
                if begin_result.completion is not None:
                    persisted = promotion_ledger.verify_receipt(
                        begin_result.completion
                    )
                    return _terminal_response(
                        persisted,
                        authorization=authorization,
                        start=begin_result.start,
                        replayed=True,
                    )
                return _pending_response(
                    candidates,
                    authorization=authorization,
                    start=begin_result.start,
                    reason=(
                        "promotion start is pending reconciliation; automatic "
                        "re-execution is forbidden"
                    ),
                )

            execution_error = None
            try:
                report = _promote_locked(
                    root,
                    manager,
                    candidates,
                    project=project,
                    availability=availability,
                    ledger_path=ledger_path,
                    gate_timeout_s=gate_timeout_s,
                    cancel=cancel,
                )
            except BaseException as exc:  # persist unknown effect outcome first
                execution_error = exc
                report = {
                    "promoted": [],
                    "refused": [
                        {
                            "task_id": result.task_id,
                            "promoted": False,
                            "reason": (
                                "promotion execution fault: "
                                f"{type(exc).__name__}"
                            ),
                        }
                    ],
                    "not_gated": [],
                    "integration_branch": None,
                    "fault": {
                        "code": "promotion-execution-error",
                        "type": type(exc).__name__,
                    },
                }

            primary_after, primary_after_clean = _primary_checkout_fingerprint(root)
            primary_unchanged = (
                primary_after_clean
                and primary_after == begin_result.start.primary_checkout_before_sha256
            )
            if not primary_unchanged:
                report = dict(report)
                report["fault"] = {
                    "code": "primary-checkout-identity-changed",
                    "type": "PromotionPrimaryCheckoutMutation",
                }

            report = dict(report)
            report["not_gated"] = list(report.get("not_gated", []))
            report["authorization"] = authorization.to_dict()
            outcome = _classify_terminal_report(
                report,
                primary_unchanged=primary_unchanged,
            )
            integration_branch = report.get("integration_branch")
            integration_revision = None
            if integration_branch is not None and not isinstance(
                integration_branch, str
            ):
                outcome = "faulted"
                report["fault"] = {
                    "code": "malformed-integration-branch",
                    "type": "PromotionIntegrationIdentityError",
                }
                report["integration_branch"] = None
                integration_branch = None
            if isinstance(integration_branch, str):
                try:
                    integration_revision = _resolve_integration_revision(
                        root, integration_branch
                    )
                except Exception as exc:  # noqa: BLE001
                    outcome = "faulted"
                    report["fault"] = {
                        "code": "integration-revision-unavailable",
                        "type": type(exc).__name__,
                    }
                    report["integration_branch"] = None
                    integration_branch = None
            if outcome == "succeeded" and (
                integration_branch is None or integration_revision is None
            ):
                outcome = "faulted"
                report["fault"] = {
                    "code": "missing-integration-identity",
                    "type": "PromotionIntegrationIdentityError",
                }
            if outcome == "faulted" and not report.get("fault") and not report.get(
                "cleanup_error"
            ):
                report["fault"] = {
                    "code": "terminal-report-inconsistent",
                    "type": "PromotionTerminalReportError",
                }

            completion = promotion_ledger.complete(
                begin_result.start,
                receipt_id=receipt_id,
                outcome=outcome,
                report=report,
                primary_checkout_after_sha256=primary_after,
                integration_branch=integration_branch,
                integration_revision=integration_revision,
            )
            persisted = promotion_ledger.verify_receipt(completion)
            response = _terminal_response(
                persisted,
                authorization=authorization,
                start=begin_result.start,
                replayed=False,
            )
            if execution_error is not None:
                if isinstance(execution_error, (KeyboardInterrupt, SystemExit)):
                    raise execution_error
            return response
    except PromotionUnavailable as exc:
        return {
            "promoted": [],
            "integration_branch": None,
            "authorization": None,
            "not_gated": [],
            "refused": [
                {
                    "task_id": result.task_id,
                    "promoted": False,
                    "reason": str(exc),
                }
            ],
        }
    except Exception as exc:  # noqa: BLE001 - public effect boundary fails closed
        if begin_result is not None and begin_result.execute and authorization is not None:
            return _pending_response(
                candidates,
                authorization=authorization,
                start=begin_result.start,
                reason=(
                    "promotion terminal persistence or reconciliation failed; "
                    f"pending operator review ({type(exc).__name__})"
                ),
            )
        return _promotion_refusal(candidates, exc)

    raise AssertionError("sealed promotion boundary returned without a result")


__all__ = tuple(sorted(name for name in globals() if not name.startswith("_")))
