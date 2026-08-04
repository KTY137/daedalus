"""Restart-safe manager-audit binding for live promotion accounting.

This second narrow layer is installed after ``promotion_manager_boundary``.
It selects the typed per-call ledger proxy retained by that boundary, fixes
terminal report identity before the canonical write, and refuses to trust a
persisted completion whose manager audit cannot be reconstructed exactly after
restart.  The public ``PromotionExecutionLedger`` class remains untouched.
"""
from __future__ import annotations

import math
import re
from dataclasses import replace
from typing import Any, Mapping, MutableMapping

from daedalus.kairos import promotion_manager_boundary as manager_boundary
from daedalus.kernel.promotion import resolve_live_target_revision
from daedalus.spine.envelope import canonical_sha

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_AUDIT_SCHEMA = "daedalus-promotion-manager-audit/1"


class PromotionManagerReplayError(ValueError):
    """Persisted manager evidence is malformed or semantically contradictory."""


def _object(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PromotionManagerReplayError(f"{label} must be an object")
    result = dict(value)
    if set(result) != keys:
        raise PromotionManagerReplayError(f"{label} has wrong fields")
    return result


def _text(value: Any, label: str, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or not value:
        raise PromotionManagerReplayError(f"{label} must be non-empty text")
    return value


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise PromotionManagerReplayError(f"{label} must be lowercase SHA-256")
    return value


def _strict_json(value: Any, label: str = "manager audit") -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PromotionManagerReplayError(f"{label} contains non-finite float")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise PromotionManagerReplayError(
                    f"{label} contains non-string object key"
                )
            normalized[key] = _strict_json(item, f"{label}.{key}")
        return normalized
    if isinstance(value, (list, tuple)):
        return [_strict_json(item, f"{label}[]") for item in value]
    raise PromotionManagerReplayError(
        f"{label} contains non-JSON value {type(value).__name__}"
    )


def _error(value: Any, label: str) -> dict[str, str] | None:
    if value is None:
        return None
    body = _object(
        value,
        {"error_type", "message_prefix", "message_sha256"},
        label,
    )
    return {
        "error_type": _text(body["error_type"], f"{label}.error_type"),
        "message_prefix": (
            body["message_prefix"]
            if isinstance(body["message_prefix"], str)
            else (_ for _ in ()).throw(
                PromotionManagerReplayError(
                    f"{label}.message_prefix must be text"
                )
            )
        ),
        "message_sha256": _sha(
            body["message_sha256"],
            f"{label}.message_sha256",
        ),
    }


def _allocation(value: Any, index: int) -> dict[str, Any]:
    label = f"manager audit allocation[{index}]"
    body = _object(
        value,
        {"base_revision", "branch", "status", "worktree_path", "error"},
        label,
    )
    status = _text(body["status"], f"{label}.status")
    if status not in {"succeeded", "failed"}:
        raise PromotionManagerReplayError(f"{label}.status is invalid")
    worktree = _text(
        body["worktree_path"],
        f"{label}.worktree_path",
        optional=True,
    )
    error = _error(body["error"], f"{label}.error")
    if status == "succeeded":
        if worktree is None or error is not None:
            raise PromotionManagerReplayError(f"{label} success shape is invalid")
    elif worktree is not None or error is None:
        raise PromotionManagerReplayError(f"{label} failure shape is invalid")
    return {
        "base_revision": _text(
            body["base_revision"], f"{label}.base_revision"
        ),
        "branch": _text(body["branch"], f"{label}.branch"),
        "status": status,
        "worktree_path": worktree,
        "error": error,
    }


def _cleanup(value: Any, index: int) -> dict[str, Any]:
    label = f"manager audit cleanup[{index}]"
    body = _object(value, {"worktree_path", "status", "error"}, label)
    status = _text(body["status"], f"{label}.status")
    if status not in {"succeeded", "failed"}:
        raise PromotionManagerReplayError(f"{label}.status is invalid")
    error = _error(body["error"], f"{label}.error")
    if (status == "succeeded") != (error is None):
        raise PromotionManagerReplayError(f"{label} error contradicts status")
    return {
        "worktree_path": _text(
            body["worktree_path"], f"{label}.worktree_path"
        ),
        "status": status,
        "error": error,
    }


def _reap(value: Any, index: int) -> dict[str, Any]:
    label = f"manager audit reap[{index}]"
    body = _object(value, {"status", "result", "error"}, label)
    status = _text(body["status"], f"{label}.status")
    if status not in {"succeeded", "failed"}:
        raise PromotionManagerReplayError(f"{label}.status is invalid")
    error = _error(body["error"], f"{label}.error")
    result = _strict_json(body["result"], f"{label}.result")
    if status == "succeeded":
        if error is not None:
            raise PromotionManagerReplayError(f"{label} success has error")
    elif error is None:
        raise PromotionManagerReplayError(f"{label} failure lacks error")
    return {"status": status, "result": result, "error": error}


def parse_manager_audit(value: Any) -> dict[str, Any]:
    """Parse one exact audit object without accepting omitted or extra fields."""
    normalized = _strict_json(value)
    body = _object(
        normalized,
        {"schema", "allocations", "cleanups", "reaps"},
        "manager audit",
    )
    if body["schema"] != _AUDIT_SCHEMA:
        raise PromotionManagerReplayError("manager audit schema is invalid")
    for name in ("allocations", "cleanups", "reaps"):
        if not isinstance(body[name], list):
            raise PromotionManagerReplayError(f"manager audit {name} must be array")
    return {
        "schema": _AUDIT_SCHEMA,
        "allocations": [
            _allocation(item, index)
            for index, item in enumerate(body["allocations"])
        ],
        "cleanups": [
            _cleanup(item, index)
            for index, item in enumerate(body["cleanups"])
        ],
        "reaps": [
            _reap(item, index) for index, item in enumerate(body["reaps"])
        ],
    }


def _reaper_action(audit: Mapping[str, Any], branch: str) -> str | None:
    reaps = audit["reaps"]
    if len(reaps) != 1 or reaps[0]["status"] != "succeeded":
        return None
    result = reaps[0]["result"]
    if not isinstance(result, list):
        return None
    matches = [
        row
        for row in result
        if isinstance(row, Mapping) and row.get("branch") == branch
    ]
    if len(matches) != 1 or not isinstance(matches[0].get("action"), str):
        return None
    return str(matches[0]["action"])


def _common_successful_lifecycle(
    audit: Mapping[str, Any],
) -> tuple[Mapping[str, Any], str]:
    allocations = audit["allocations"]
    cleanups = audit["cleanups"]
    reaps = audit["reaps"]
    if len(allocations) != 1 or allocations[0]["status"] != "succeeded":
        raise PromotionManagerReplayError("audit lacks one successful allocation")
    allocation = allocations[0]
    if len(cleanups) != 1 or cleanups[0]["status"] != "succeeded":
        raise PromotionManagerReplayError("audit lacks one successful cleanup")
    if cleanups[0]["worktree_path"] != allocation["worktree_path"]:
        raise PromotionManagerReplayError("audit cleanup targets another worktree")
    if len(reaps) != 1 or reaps[0]["status"] != "succeeded":
        raise PromotionManagerReplayError("audit lacks one successful reaper run")
    return allocation, str(allocation["branch"])


def validate_persisted_manager_completion(completion: Any) -> None:
    """Fail if a terminal completion cannot be proven from its retained audit."""
    receipt = completion.receipt
    report = completion.report_dict()
    raw_audit = report.get("manager_audit")
    raw_digest = report.get("manager_audit_sha256")
    mutation_entered = report.get("mutation_entered") is True

    if raw_audit is None and raw_digest is None:
        if (
            receipt.outcome == "refused"
            and not mutation_entered
            and receipt.integration_branch is None
            and receipt.integration_revision is None
        ):
            return
        raise PromotionManagerReplayError(
            "post-mutation completion has no manager audit"
        )
    if raw_audit is None or raw_digest is None:
        raise PromotionManagerReplayError("manager audit and digest are inseparable")

    audit = parse_manager_audit(raw_audit)
    digest = _sha(raw_digest, "manager_audit_sha256")
    if digest != canonical_sha(audit):
        raise PromotionManagerReplayError("manager audit digest mismatch")

    report_branch = report.get("integration_branch")
    report_revision = report.get("integration_revision")
    if report_branch != receipt.integration_branch:
        raise PromotionManagerReplayError("report and receipt branch differ")
    if report_revision != receipt.integration_revision:
        raise PromotionManagerReplayError("report and receipt revision differ")

    if receipt.outcome == "succeeded":
        allocation, branch = _common_successful_lifecycle(audit)
        if receipt.integration_branch != branch:
            raise PromotionManagerReplayError("success branch differs from allocation")
        if receipt.integration_revision is None:
            raise PromotionManagerReplayError("success has no integration revision")
        if _reaper_action(audit, branch) != "retained":
            raise PromotionManagerReplayError("success branch was not retained")
        if allocation["worktree_path"] is None:
            raise PromotionManagerReplayError("success allocation has no worktree")
        return

    if receipt.outcome == "refused":
        _allocation_row, branch = _common_successful_lifecycle(audit)
        if receipt.integration_branch is not None or receipt.integration_revision is not None:
            raise PromotionManagerReplayError("refusal retained integration identity")
        if _reaper_action(audit, branch) not in {"deleted", "absent"}:
            raise PromotionManagerReplayError("refusal lacks branch deletion proof")
        return

    if receipt.outcome != "faulted" or not report.get("fault"):
        raise PromotionManagerReplayError("terminal manager outcome is invalid")

    allocations = audit["allocations"]
    if len(allocations) != 1:
        if not mutation_entered and not allocations and receipt.integration_branch is None:
            return
        raise PromotionManagerReplayError("fault has ambiguous allocation evidence")
    allocation = allocations[0]
    branch = str(allocation["branch"])
    if receipt.integration_branch is not None:
        if receipt.integration_branch != branch or receipt.integration_revision is None:
            raise PromotionManagerReplayError("fault identity differs from allocation")
        return
    _allocation_row, common_branch = _common_successful_lifecycle(audit)
    if _reaper_action(audit, common_branch) not in {"deleted", "absent"}:
        raise PromotionManagerReplayError("branchless fault lacks deletion proof")


class _ReplayAuditedExecutionLedger(manager_boundary._AuditedExecutionLedger):
    """Typed replay-validating proxy over one canonical ledger instance."""

    def begin(self, *args: Any, **kwargs: Any) -> Any:
        result = self._delegate.begin(*args, **kwargs)
        completion = getattr(result, "completion", None)
        if completion is None:
            return result
        try:
            validate_persisted_manager_completion(completion)
        except PromotionManagerReplayError:
            return replace(result, execute=False, completion=None)
        return result

    def complete(
        self,
        start: Any,
        *,
        receipt_id: str,
        outcome: str,
        report: Mapping[str, Any],
        primary_checkout_after_sha256: str,
        integration_branch: str | None = None,
        integration_revision: str | None = None,
    ) -> Any:
        manager = self._state.active_manager.get()
        if manager is None:
            return self._delegate.complete(
                start,
                receipt_id=receipt_id,
                outcome=outcome,
                report=report,
                primary_checkout_after_sha256=primary_checkout_after_sha256,
                integration_branch=integration_branch,
                integration_revision=integration_revision,
            )

        snapshot = manager.snapshot()
        enriched = dict(report)
        enriched["manager_audit"] = snapshot.to_dict()
        enriched["manager_audit_sha256"] = snapshot.digest
        try:
            assessed_outcome, assessed_branch, assessed_revision = (
                manager_boundary._assess_completion(
                    manager=manager,
                    snapshot=snapshot,
                    outcome=outcome,
                    report=enriched,
                    integration_branch=integration_branch,
                    integration_revision=integration_revision,
                )
            )
        except manager_boundary.PromotionManagerAuditFault as exc:
            assessed_outcome = "faulted"
            assessed_branch = exc.integration_branch
            assessed_revision = exc.integration_revision
            if assessed_branch is not None and assessed_revision is None:
                try:
                    assessed_revision = resolve_live_target_revision(
                        manager.repository_path,
                        assessed_branch,
                    )
                except Exception as resolve_exc:
                    raise manager_boundary.PromotionManagerAuditPending(
                        "manager fault branch revision cannot be proven"
                    ) from resolve_exc
            enriched["fault"] = {
                "type": (
                    f"{type(exc).__module__}.{type(exc).__qualname__}"
                ),
                "message": str(exc),
            }

        enriched["integration_branch"] = assessed_branch
        enriched["integration_revision"] = assessed_revision
        return self._delegate.complete(
            start,
            receipt_id=receipt_id,
            outcome=assessed_outcome,
            report=enriched,
            primary_checkout_after_sha256=primary_checkout_after_sha256,
            integration_branch=assessed_branch,
            integration_revision=assessed_revision,
        )


def install_promotion_manager_replay_boundary(
    namespace: MutableMapping[str, Any],
) -> None:
    """Select replay validation for per-call typed ledger wrapping."""
    state = namespace.get("_promotion_manager_boundary_state")
    ledger_type = namespace.get("PromotionExecutionLedger")
    if (
        not isinstance(state, manager_boundary._BoundaryState)
        or not isinstance(ledger_type, type)
        or ledger_type is not state.ledger_type
    ):
        raise RuntimeError("promotion manager replay installation target is invalid")
    if namespace.get("_promotion_manager_replay_wrapper") is not None:
        raise RuntimeError("promotion manager replay boundary is already installed")

    state.ledger_wrapper = _ReplayAuditedExecutionLedger
    namespace["_MANAGER_AUDIT_V1_LEDGER_TYPE"] = ledger_type
    namespace["_promotion_manager_replay_wrapper"] = (
        _ReplayAuditedExecutionLedger
    )


__all__ = [
    "PromotionManagerReplayError",
    "install_promotion_manager_replay_boundary",
    "parse_manager_audit",
    "validate_persisted_manager_completion",
]
