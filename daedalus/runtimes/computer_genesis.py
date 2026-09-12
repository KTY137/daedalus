"""Computer-loop adapter to the canonical Genesis builder; never a second builder.

The composition root supplies the workload. Models supply a bounded product
request, not an output directory, executable, evaluator or publication permit.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from daedalus.kernel.policy.computer import ComputerRefused
from daedalus.runtimes.computer_daedalus import _mentions_host_path
from daedalus.sensitivity import secret_floor_rule
from daedalus.spine.envelope import canonical_sha


class GenesisPreRunRefusal(ComputerRefused):
    effect_state = "none"


class GenesisRunFailure(ComputerRefused):
    effect_state = "uncertain"


@dataclass(frozen=True)
class GenesisRunner:
    run_genesis: Callable[..., dict[str, Any]]


def _sha(value: Any) -> str | None:
    return value if type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) else None


def _row(value: Any) -> dict[str, Any]:
    return value if type(value) is dict else {}


class GenesisBuildTool:
    def __init__(self, authority_root: Path, checkpoint: Callable[[], None], runner: GenesisRunner) -> None:
        if not isinstance(runner, GenesisRunner) or not callable(runner.run_genesis):
            raise GenesisPreRunRefusal("Genesis runner is unavailable")
        self.root = Path(authority_root)
        self.checkpoint = checkpoint
        self.runner = runner

    def execute(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if type(arguments) is not dict or set(arguments) - {"prompt", "target", "stack"}:
            raise GenesisPreRunRefusal("unknown Genesis arguments; host paths and publication are not accepted")
        prompt = arguments.get("prompt")
        if type(prompt) is not str or not prompt.strip() or len(prompt) > 16_000 or "\x00" in prompt:
            raise GenesisPreRunRefusal("Genesis prompt must be non-empty bounded text")
        target = arguments.get("target", "web")
        if target not in ("web", "cli"):
            raise GenesisPreRunRefusal("Genesis target must be web or cli")
        stack = arguments.get("stack")
        if stack is not None and (type(stack) is not str or not stack or len(stack) > 100 or "\x00" in stack):
            raise GenesisPreRunRefusal("Genesis stack must be bounded text")
        self.checkpoint()
        request_key = "ikarus-tensor-genesis-" + canonical_sha({"prompt": prompt, "target": target, "stack": stack})
        try:
            receipt = self.runner.run_genesis(prompt, target=target, stack=stack, request_key=request_key,
                                              repo_root=self.root, caller_checkpoint=self.checkpoint)
            self.checkpoint()
        except Exception as exc:
            # A workload may already have written a canonical Attempt before
            # cancellation or failure: never claim that it had no effect.
            raise GenesisRunFailure(f"Genesis did not return a settled result: {type(exc).__name__}") from exc
        if type(receipt) is not dict:
            raise GenesisRunFailure("Genesis runner returned no structured receipt")
        try:
            data = json.loads(json.dumps(receipt, allow_nan=False))
        except (ValueError, TypeError) as exc:
            raise GenesisRunFailure("Genesis receipt is not strict JSON") from exc
        if data.get("request_key") != request_key or data.get("target") != target:
            raise GenesisRunFailure("Genesis result does not bind the requested build")
        run_id = data.get("run_id")
        if type(run_id) is not str or not re.fullmatch(r"genesis-[a-z0-9-]{1,100}", run_id):
            raise GenesisRunFailure("Genesis run identity is invalid")
        status = data.get("status")
        if status not in ("preview-ready", "succeeded", "failed", "blocked"):
            raise GenesisRunFailure("Genesis status is unsupported or pending reconciliation")
        candidate, evidence, roundtrip = (_row(data.get(name)) for name in ("candidate", "evidence", "roundtrip"))
        candidate_sha = _sha(candidate.get("sha256"))
        evidence_sha = _sha(evidence.get("sha256"))
        roundtrip_sha = _sha(roundtrip.get("sha256"))
        checks = _row(roundtrip.get("checks"))
        # Never coerce truthy strings or empty/malformed collections into proof.
        if any(type(k) is not str or not re.fullmatch(r"[a-z_]{1,80}", k) or type(v) is not bool
               for k, v in checks.items()):
            raise GenesisRunFailure("Genesis checks are not strict named boolean observations")
        green = status in ("preview-ready", "succeeded")
        publication = _row(data.get("publication"))
        if publication != {"status": "not-requested", "automatic_promotion": False, "owner_approval_required": True}:
            raise GenesisRunFailure("Genesis receipt has no explicit non-publication boundary")
        required = {"build", "test", "runtime", "package", "containment", "code", "type", "data", "knowledge"}
        if green and not (required <= checks.keys() and candidate_sha and evidence_sha and roundtrip_sha and checks and all(checks.values())
                          and evidence.get("candidate_tree_sha256") == candidate_sha
                          and evidence.get("status") == roundtrip.get("status") == "passed"):
            raise GenesisRunFailure("green Genesis receipt has inconsistent candidate/evidence bindings")
        blockers = data.get("blockers")
        blocker_list = blockers if type(blockers) is list else []
        safe_blockers = []
        for value in blocker_list[:12]:
            text = value[:250] if type(value) is str else "unreadable blocker"
            safe_blockers.append("details withheld; inspect the local Genesis receipt"
                                 if _mentions_host_path(text) or secret_floor_rule("", text) else text)
        return {
            "schema": "daedalus-computer-genesis-result/1", "kind": "genesis", "run_id": run_id,
            "status": status, "target": target, "candidate_tree_sha256": candidate_sha,
            "evidence_packet_sha256": evidence_sha, "roundtrip_sha256": roundtrip_sha,
            "receipt_sha256": canonical_sha(data), "checks": checks,
            "tensor_kernel_verified": checks.get("tensor_kernel") is True,
            "postcondition_verified": green and checks.get("tensor_kernel") is True,
            "host_mutation": True, "applied": False, "automatic_promotion": False,
            "blockers": safe_blockers, "blockers_elided": max(0, len(blocker_list) - 12),
            "scope": "supported Genesis blueprints only; isolated CAS candidate, not arbitrary software or deployment",
        }
