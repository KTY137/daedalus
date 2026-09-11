"""Explicit owner computer-policy editing, never a model-callable tool."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any

from daedalus.atomic import ExclusiveFileLock
from daedalus.budget import process_guard_boundary_decision
from daedalus.kernel.artifacts import store_canonical_json
from daedalus.kernel.policy.computer import ComputerPolicy, ComputerRefused, load_policy, policy_path
from daedalus.spine.effect_boundary import REGISTRY_BY_ID, GuardDecision, begin_effect
from daedalus.spine.envelope import canonical_sha


ENTRYPOINT = "python.ikarus_computer_configure"


def _candidate(authority_root: Path, payload: dict[str, Any]) -> ComputerPolicy:
    if not isinstance(payload, dict):
        raise ComputerRefused("configuration requires the full computer policy object")
    try:
        if len(json.dumps(payload, allow_nan=False)) > 65536:
            raise ComputerRefused("computer policy exceeds its size bound")
        policy = ComputerPolicy.from_dict(payload)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ComputerRefused(f"invalid computer policy: {exc}") from exc
    if set(payload) != set(policy.to_dict()):
        raise ComputerRefused("configuration requires every field of the computer policy schema")
    # Validate the supplied spelling before ComputerPolicy resolves it: resolving
    # first would erase evidence of a workspace symlink or junction.
    supplied = Path(payload["workspace"]).expanduser()
    for item in (supplied, *supplied.parents):
        try:
            metadata = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
            raise ComputerRefused("linked computer workspaces are refused")
    control = policy_path(authority_root).parent.resolve()
    installation = Path(__file__).resolve().parents[2]
    for protected in (control, installation):
        if policy.workspace.is_relative_to(protected) or protected.is_relative_to(policy.workspace):
            raise ComputerRefused("computer workspace must be disjoint from control state and the installation")
    if not policy.workspace.is_dir():
        raise ComputerRefused("configured computer workspace must be an existing directory")
    policy.path(".", must_exist=True)
    return policy


def configure_computer(
    authority_root: Path,
    payload: dict[str, Any],
    *,
    owner_confirmed: bool = False,
    expected_policy_sha256: str,
) -> dict[str, Any]:
    """Compare-and-replace existing owner policy with canonical evidence.

    The explicit interface supplies transient owner confirmation. The policy
    itself never stores confirmation or grants a model configuration authority.
    Callers must inspect a failure reporting a changed policy before retrying.
    """
    if owner_confirmed is not True:
        raise ComputerRefused("explicit owner configuration is required")
    if (not isinstance(expected_policy_sha256, str) or len(expected_policy_sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in expected_policy_sha256)):
        raise ComputerRefused("expected_policy_sha256 must be a complete lowercase SHA-256")
    root = Path(authority_root).resolve()
    current = load_policy(root)
    if current.digest != expected_policy_sha256:
        raise ComputerRefused("computer policy changed; inspect the current policy before configuring")
    proposed = _candidate(root, payload)
    if proposed.digest == current.digest:
        return {"ok": True, "changed": False, "policy_sha256": current.digest,
                "policy": current.to_dict(), "evidence": None}
    request_sha = canonical_sha({"base_policy_sha256": current.digest, "policy": proposed.to_dict()})
    receipt = begin_effect(
        ENTRYPOINT, REGISTRY_BY_ID[ENTRYPOINT].effects,
        (process_guard_boundary_decision(), GuardDecision("computer.configuration", True,
            f"explicit owner configuration; base={current.digest}; result={proposed.digest}; request={request_sha}")),
    )
    destination = policy_path(root)
    control = destination.parent
    with ExclusiveFileLock(control / "computer-setup.lock", timeout_s=1, label="computer policy update"):
        if load_policy(root).digest != current.digest:
            raise ComputerRefused("computer policy changed while acquiring configuration lock")
        _candidate(root, payload)
        started = store_canonical_json(control / "computer-artifacts", {
            "schema": "daedalus-computer-configuration/1", "phase": "admitted",
            "base_policy_sha256": current.digest, "result_policy_sha256": proposed.digest,
            "request_sha256": request_sha, "boundary": receipt.to_dict(),
        })
        temporary: Path | None = None
        replaced = False
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                             prefix="computer-policy-", suffix=".tmp", dir=control, delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(proposed.to_dict(), stream, indent=2, ensure_ascii=False, allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            if load_policy(root).digest != current.digest:
                raise ComputerRefused("computer policy changed during configuration preparation")
            os.replace(temporary, destination)
            replaced = True
            if load_policy(root).digest != proposed.digest:
                raise ComputerRefused("configuration readback differs from the requested policy")
            finished = store_canonical_json(control / "computer-artifacts", {
                "schema": "daedalus-computer-configuration/1", "phase": "completed",
                "start_sha256": started.sha256, "base_policy_sha256": current.digest,
                "result_policy_sha256": proposed.digest,
            })
        except Exception as exc:
            if replaced:
                raise ComputerRefused("computer policy was changed, but final verification/evidence failed; inspect current policy before retrying") from exc
            raise
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return {"ok": True, "changed": True, "policy_sha256": proposed.digest,
            "policy": proposed.to_dict(), "evidence": finished.to_dict(), "start_evidence": started.to_dict()}
