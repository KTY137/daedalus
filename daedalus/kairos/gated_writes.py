"""Compatibility strangler for the sealed Kairos promotion seam.

The historical gating implementation remains byte-identical as a non-importable
package resource. It is verified against its exact Git blob identity and then
executed into this module's namespace so existing classes, functions, import
paths, pickle names and function globals stay compatible. The public promotion
callable and its small locked helper are replaced with persisted-authority and
persisted-receipt variants.
"""
from __future__ import annotations

import hashlib as _hashlib
import hmac as _hmac
import json as _json
import stat as _stat
from importlib.resources import files as _resource_files


_RETAINED_SOURCE_NAME = "_gated_writes_legacy.py.src"
_RETAINED_SOURCE_GIT_BLOB_SHA1 = "e31d24ec67f7c208ace34f5dd2e9fefe4e654a86"


def _git_blob_sha1(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return _hashlib.sha1(header + data, usedforsecurity=False).hexdigest()


def _verify_retained_source(data: bytes) -> bytes:
    """Refuse altered dynamically executed package data."""
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

# Remove both inherited live mutation functions before installing their sealed
# replacements. Existing retained functions resolve globals dynamically.
del promote_candidates
del _promote_locked

from daedalus.kernel.promotion import PromotionAuthorizationError
from daedalus.kernel.promotion_receipts import (
    PromotionLedger,
    PromotionReceiptError,
)
from daedalus.spine.envelope import canonical_json as _canonical_json
from daedalus.spine.envelope import canonical_sha as _canonical_sha


__doc__ = """Compatibility strangler for the sealed Kairos promotion seam.

All non-promotion symbols retain the canonical
``daedalus.kairos.gated_writes`` module identity. The inherited live promotion
functions are removed before persisted-authority replacements are defined.
"""


def _retired_legacy_promotion(*_args, **_kwargs):
    raise PromotionAuthorizationError(
        "the retained legacy promotion callable is retired; use "
        "daedalus.kairos.gated_writes.promote_candidates"
    )


class _LegacyFacade:
    """Test/review facade over retained helpers, never a second module."""

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
        "promotion_start": None,
        "promotion_receipt": None,
    }


def _legacy_unpersisted_refusal(
    root: Path,
    candidates: list[Any],
    *,
    consumed_approval,
    evidence_packet,
    target_ref: str,
) -> dict[str, Any]:
    """Preserve old negative-call diagnostics without granting authority."""
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
            "persisted ApprovalLedger, PromotionLedger and owner keyring are mandatory"
        ),
    )


def _primary_git(
    root: Path,
    args: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run one read-only Git query with repository-controlled hooks disabled."""
    pre: list[str] = []
    for key_value in _GIT_EXEC_CONFIG:
        pre.extend(("-c", key_value))
    environment = _hardened_env()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    process = subprocess.run(
        ["git", "-C", str(root), *pre, *args],
        cwd=str(root),
        capture_output=True,
        timeout=120,
        env=environment,
        check=False,
    )
    if check and process.returncode != 0:
        detail = process.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed in {root}: {detail}")
    return process


def _split_nul(payload: bytes) -> tuple[bytes, ...]:
    return tuple(item for item in payload.split(b"\0") if item)


def _stat_signature(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        int(value.st_mode),
        int(value.st_size),
        int(getattr(value, "st_mtime_ns", int(value.st_mtime * 1_000_000_000))),
        int(getattr(value, "st_ctime_ns", int(value.st_ctime * 1_000_000_000))),
        int(getattr(value, "st_dev", 0)),
        int(getattr(value, "st_ino", 0)),
    )


def _primary_path_state(root: Path, raw_path: bytes) -> dict[str, object]:
    relative = os.fsdecode(raw_path)
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise RuntimeError(f"Git returned an unsafe checkout path: {relative!r}")
    full_path = root / path
    encoded_path = raw_path.hex()
    try:
        before = os.lstat(full_path)
    except FileNotFoundError:
        return {"path_hex": encoded_path, "kind": "missing"}

    kind = _stat.S_IFMT(before.st_mode)
    state: dict[str, object] = {
        "path_hex": encoded_path,
        "mode": int(before.st_mode),
        "size": int(before.st_size),
        "mtime_ns": int(
            getattr(before, "st_mtime_ns", int(before.st_mtime * 1_000_000_000))
        ),
    }
    if kind == _stat.S_IFREG:
        digest = _hashlib.sha256()
        flags = os.O_RDONLY
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(full_path, flags)
        try:
            opened = os.fstat(descriptor)
            if _stat.S_IFMT(opened.st_mode) != _stat.S_IFREG:
                raise RuntimeError(f"checkout path changed type while hashing: {relative!r}")
            while True:
                block = os.read(descriptor, 1024 * 1024)
                if not block:
                    break
                digest.update(block)
            opened_after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        state.update(
            {
                "kind": "regular",
                "content_sha256": digest.hexdigest(),
            }
        )
        if _stat_signature(opened) != _stat_signature(opened_after):
            raise RuntimeError(f"checkout file changed while hashing: {relative!r}")
    elif kind == _stat.S_IFLNK:
        target = os.readlink(full_path)
        state.update(
            {
                "kind": "symlink",
                "target_hex": os.fsencode(target).hex(),
            }
        )
    elif kind == _stat.S_IFDIR:
        state["kind"] = "directory"
    else:
        state.update(
            {
                "kind": "special",
                "device": int(getattr(before, "st_rdev", 0)),
            }
        )

    try:
        after = os.lstat(full_path)
    except FileNotFoundError as exc:
        raise RuntimeError(f"checkout path disappeared while hashing: {relative!r}") from exc
    if _stat_signature(before) != _stat_signature(after):
        raise RuntimeError(f"checkout path changed while hashing: {relative!r}")
    return state


def _primary_inventory(root: Path) -> tuple[bytes, bytes, bytes, tuple[bytes, ...]]:
    head = _primary_git(root, ["rev-parse", "--verify", "HEAD"]).stdout.strip()
    index = _primary_git(root, ["ls-files", "--stage", "-z"]).stdout
    status = _primary_git(
        root,
        [
            "status",
            "--porcelain=v2",
            "-z",
            "--untracked-files=all",
            "--ignore-submodules=none",
        ],
    ).stdout
    paths = tuple(
        sorted(
            set(
                _split_nul(
                    _primary_git(
                        root,
                        [
                            "ls-files",
                            "-z",
                            "--cached",
                            "--others",
                            "--exclude-standard",
                        ],
                    ).stdout
                )
            )
        )
    )
    return head, index, status, paths


def _primary_checkout_fingerprint(root: Path) -> str:
    """Hash HEAD, index, status and all tracked/nonignored worktree bytes.

    Git metadata itself is deliberately excluded: creating an integration
    branch changes refs under ``.git`` but must not count as a primary checkout
    mutation. Ignored runtime state is also excluded. The complete inventory is
    sampled twice around byte hashing and any unstable read fails closed.
    """
    first = _primary_inventory(root)
    states = tuple(_primary_path_state(root, raw_path) for raw_path in first[3])
    second = _primary_inventory(root)
    if first != second:
        raise RuntimeError("primary checkout changed during fingerprint capture")
    head = first[0].decode("ascii", "strict")
    if len(head) not in {40, 64} or any(character not in "0123456789abcdef" for character in head):
        raise RuntimeError("primary checkout HEAD is not a canonical revision")
    return _canonical_sha(
        {
            "schema": "daedalus.primary-checkout-fingerprint/1",
            "head": head,
            "index_hex": first[1].hex(),
            "status_hex": first[2].hex(),
            "paths": states,
        }
    )


def _planned_integration_branch(authorization) -> str:
    return f"kairos-integration-{authorization.authorization_sha256[:40]}"


def _stable_start_id(authorization) -> str:
    return f"promotion-start-{authorization.authorization_sha256[:40]}"


def _stable_receipt_id(authorization) -> str:
    return f"promotion-receipt-{authorization.authorization_sha256[:40]}"


def _branch_revision(root: Path, branch: str) -> str | None:
    process = _primary_git(
        root,
        ["rev-parse", "--verify", f"refs/heads/{branch}"],
        check=False,
    )
    if process.returncode != 0:
        return None
    revision = process.stdout.decode("ascii", "strict").strip()
    if len(revision) not in {40, 64} or any(
        character not in "0123456789abcdef" for character in revision
    ):
        raise RuntimeError("integration branch resolved to a malformed revision")
    return revision


def _promote_locked(
    root: Path,
    manager: GitWorktreeManager,
    gated: list[GatedCandidate],
    *,
    integration_branch: str,
    project: str | None,
    availability: dict,
    ledger_path,
    gate_timeout_s: float,
    cancel: Any,
) -> dict:
    """Retained integration algorithm with a deterministic branch identity."""
    if not _git_available(root):
        return {
            "promoted": [],
            "refused": [
                {"task_id": "all", "promoted": False, "reason": "git not available"}
            ],
            "integration_branch": None,
        }

    from daedalus.config import resolve_project

    data = resolve_project(str(root), project) or {}
    base_commit = _rev_parse_head(root)
    integration_worktree = manager.create_worktree(base_commit, integration_branch)
    integration_git = _PinnedWorktreeGit(integration_worktree)
    if integration_git.admin_dir is None:
        try:
            manager.cleanup_worktree(integration_worktree)
        except Exception:
            pass
        return {
            "promoted": [],
            "refused": [
                {
                    "task_id": "all",
                    "promoted": False,
                    "reason": (
                        f"could not pin git admin dir for integration worktree "
                        f"{integration_worktree}; refusing to apply candidate bytes"
                    ),
                }
            ],
            "integration_branch": integration_branch,
        }

    promoted: list[dict] = []
    refused: list[dict] = []
    cleanup_error: str | None = None
    try:
        for candidate in gated:
            ok, reason, effective = _promote_one(
                candidate,
                root=root,
                integration_worktree=integration_worktree,
                integration_git=integration_git,
                project_data=data,
                project=project,
                availability=availability,
                ledger_path=ledger_path,
                gate_timeout_s=gate_timeout_s,
                cancel=cancel,
            )
            record = {
                "task_id": candidate.result.task_id,
                "promoted": ok,
                "reason": reason,
                "integration_branch": integration_branch,
            }
            if effective is not candidate:
                record["reattempted"] = True
                record["new_task_id"] = effective.result.task_id
            (promoted if ok else refused).append(record)
    finally:
        try:
            manager.cleanup_worktree(integration_worktree)
            manager.reap_branches()
        except Exception as exc:  # noqa: BLE001 - operation is already terminal
            cleanup_error = f"{type(exc).__name__}: {exc}"

    report = {
        "promoted": promoted,
        "refused": refused,
        "integration_branch": integration_branch,
    }
    if cleanup_error is not None:
        report["cleanup_error"] = cleanup_error
    return report


def _normalise_operation_report(
    report: Mapping[str, object],
    *,
    actual_branch: str | None,
) -> dict[str, object]:
    try:
        payload = _json.loads(_canonical_json(report))
    except (TypeError, ValueError) as exc:
        return {
            "promoted": [],
            "refused": [],
            "not_gated": [],
            "integration_branch": actual_branch,
            "fault": f"retained promotion report was not canonical: {type(exc).__name__}: {exc}",
        }
    if not isinstance(payload, dict):
        return {
            "promoted": [],
            "refused": [],
            "not_gated": [],
            "integration_branch": actual_branch,
            "fault": "retained promotion report was not an object",
        }
    promoted = payload.get("promoted", [])
    refused = payload.get("refused", [])
    not_gated = payload.get("not_gated", [])
    if not isinstance(promoted, list) or not isinstance(refused, list) or not isinstance(
        not_gated, list
    ):
        return {
            "promoted": [],
            "refused": [],
            "not_gated": [],
            "integration_branch": actual_branch,
            "fault": "retained promotion report outcome collections were malformed",
            "retained_report_sha256": _canonical_sha(payload),
        }
    payload["promoted"] = promoted
    payload["refused"] = refused
    payload["not_gated"] = not_gated
    reported_branch = payload.get("integration_branch")
    if reported_branch != actual_branch:
        payload["reported_integration_branch"] = reported_branch
        payload["integration_branch"] = actual_branch
        payload["fault"] = "retained promotion report integration branch mismatch"
    return payload


def _terminal_outcome(
    report: dict[str, object],
    *,
    primary_before: str,
    primary_after: str,
    raised: BaseException | None,
) -> str:
    if primary_before != primary_after:
        report["fault"] = "primary checkout fingerprint changed during promotion"
        return "faulted"
    if raised is not None:
        report["fault"] = f"{type(raised).__name__}: {raised}"
        return "faulted"
    if report.get("cleanup_error") is not None or report.get("fault") is not None:
        return "faulted"
    promoted = report.get("promoted", [])
    refused = report.get("refused", [])
    not_gated = report.get("not_gated", [])
    if (
        isinstance(promoted, list)
        and len(promoted) == 1
        and isinstance(promoted[0], Mapping)
        and promoted[0].get("promoted") is True
        and refused == []
        and not_gated == []
    ):
        return "succeeded"
    if promoted == [] and (bool(refused) or bool(not_gated)):
        return "refused"
    report["fault"] = "promotion report did not describe one terminal outcome"
    return "faulted"


def _completion_report(completion, authorization, *, replayed: bool) -> dict[str, object]:
    report = completion.report_dict()
    report["authorization"] = authorization.to_dict()
    report["promotion_start"] = {
        "start_sha256": completion.receipt.start_sha256,
        "replayed": replayed,
    }
    report["promotion_receipt"] = completion.receipt.to_dict()
    return report


def _pending_report(
    candidate,
    authorization,
    start,
    reason: str,
    *,
    operation_report: Mapping[str, object] | None = None,
) -> dict[str, object]:
    report: dict[str, object] = {
        "promoted": [],
        "refused": [
            {
                "task_id": getattr(candidate.result, "task_id", "unknown"),
                "promoted": False,
                "reason": reason,
            }
        ],
        "not_gated": [],
        "integration_branch": None,
        "authorization": authorization.to_dict(),
        "promotion_start": start.to_dict(),
        "promotion_receipt": None,
        "pending_reconciliation": True,
    }
    if operation_report is not None:
        report["unreceipted_operation_report"] = _json.loads(
            _canonical_json(operation_report)
        )
    return report


def _reconcile_pending(
    root: Path,
    candidate,
    authorization,
    promotion_ledger: PromotionLedger,
    start,
) -> dict[str, object]:
    """Terminalize an interrupted start without ever re-running mutation."""
    try:
        primary_after = _primary_checkout_fingerprint(root)
        branch = _planned_integration_branch(authorization)
        revision = _branch_revision(root, branch)
        actual_branch = branch if revision is not None else None
        report = {
            "promoted": [],
            "refused": [],
            "not_gated": [],
            "integration_branch": actual_branch,
            "fault": (
                "pending promotion start recovered without a terminal receipt; "
                "automatic execution was refused"
            ),
            "reconciliation": {
                "integration_branch_present": revision is not None,
                "integration_revision": revision,
            },
        }
        completion = promotion_ledger.complete(
            start,
            receipt_id=_stable_receipt_id(authorization),
            outcome="faulted",
            report=report,
            primary_checkout_after_sha256=primary_after,
            integration_branch=actual_branch,
            integration_revision=revision,
        )
    except Exception as exc:  # noqa: BLE001 - remain pending rather than rerun
        return _pending_report(
            candidate,
            authorization,
            start,
            f"pending promotion reconciliation failed: {type(exc).__name__}: {exc}",
        )
    return _completion_report(completion, authorization, replayed=True)


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
    promotion_ledger: PromotionLedger | None = None,
    owner_keyring: Mapping[tuple[str, str], bytes | str] | None = None,
    ledger_path=None,
    lock_timeout_s: float = 120.0,
    gate_timeout_s: float = 900.0,
    cancel: Any = None,
) -> dict:
    """Promote one exact candidate with persisted start and terminal receipts.

    This operation remains an explicit owner action and never merges the
    integration branch. Every exact replay is non-executable.
    """
    root = Path(repo_root).resolve()

    if approval_ledger is None or promotion_ledger is None or not owner_keyring:
        return _legacy_unpersisted_refusal(
            root,
            candidates,
            consumed_approval=consumed_approval,
            evidence_packet=evidence_packet,
            target_ref=target_ref,
        )
    if not isinstance(promotion_ledger, PromotionLedger):
        return _promotion_refusal(
            candidates,
            PromotionAuthorizationError("promotion_ledger must be PromotionLedger"),
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
                "promotion_start": None,
                "promotion_receipt": None,
                "refused": [
                    {
                        "task_id": result.task_id,
                        "promoted": False,
                        "reason": f"ledger unavailable: {ledger_error}",
                    }
                ],
            }

    lock_path = manager.worktree_root / "promotion.lock"
    try:
        with _PromotionLock(lock_path, timeout_s=lock_timeout_s):
            from daedalus.kernel.promotion import (
                authorize_persisted_promotion,
                resolve_live_target_revision,
            )

            # Preserve the current effect-registry guard anchor while binding it
            # to the stronger persisted primitive.
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

            primary_before = _primary_checkout_fingerprint(root)
            begin = promotion_ledger.begin(
                authorization,
                start_id=_stable_start_id(authorization),
                primary_checkout_before_sha256=primary_before,
            )
            if not begin.execute:
                if begin.completion is not None:
                    return _completion_report(
                        begin.completion, authorization, replayed=True
                    )
                return _reconcile_pending(
                    root,
                    candidate,
                    authorization,
                    promotion_ledger,
                    begin.start,
                )

            integration_branch = _planned_integration_branch(authorization)
            retained_report: Mapping[str, object] = {
                "promoted": [],
                "refused": [],
                "not_gated": [],
                "integration_branch": None,
            }
            raised: BaseException | None = None
            try:
                retained_report = _promote_locked(
                    root,
                    manager,
                    candidates,
                    integration_branch=integration_branch,
                    project=project,
                    availability=availability,
                    ledger_path=ledger_path,
                    gate_timeout_s=gate_timeout_s,
                    cancel=cancel,
                )
            except Exception as exc:  # noqa: BLE001 - persist terminal fault
                raised = exc

            try:
                primary_after = _primary_checkout_fingerprint(root)
            except Exception as exc:  # noqa: BLE001 - cannot invent after state
                return _pending_report(
                    candidate,
                    authorization,
                    begin.start,
                    (
                        "promotion executed but primary checkout fingerprint could "
                        f"not be measured: {type(exc).__name__}: {exc}"
                    ),
                    operation_report=retained_report,
                )

            revision = _branch_revision(root, integration_branch)
            actual_branch = integration_branch if revision is not None else None
            operation_report = _normalise_operation_report(
                retained_report,
                actual_branch=actual_branch,
            )
            outcome = _terminal_outcome(
                operation_report,
                primary_before=primary_before,
                primary_after=primary_after,
                raised=raised,
            )
            try:
                completion = promotion_ledger.complete(
                    begin.start,
                    receipt_id=_stable_receipt_id(authorization),
                    outcome=outcome,
                    report=operation_report,
                    primary_checkout_after_sha256=primary_after,
                    integration_branch=actual_branch,
                    integration_revision=revision,
                )
            except PromotionReceiptError as exc:
                return _pending_report(
                    candidate,
                    authorization,
                    begin.start,
                    f"terminal PromotionReceipt persistence failed: {type(exc).__name__}: {exc}",
                    operation_report=operation_report,
                )
            return _completion_report(completion, authorization, replayed=False)
    except PromotionUnavailable as exc:
        return {
            "promoted": [],
            "integration_branch": None,
            "authorization": None,
            "promotion_start": None,
            "promotion_receipt": None,
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
        return _promotion_refusal(candidates, exc)


__all__ = tuple(sorted(name for name in globals() if not name.startswith("_")))
