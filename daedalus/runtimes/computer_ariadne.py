"""``daedalus.ariadne_campaign``: the computer loop's door to one Ariadne
controlled-repair campaign on the registered project (G1-IKARUS-47).

The tool NOMINATES. It hands a planner-proposed bounded repair
(``target_path``, ``before``, ``after``) to the canonical
``daedalus.ariadne.run_campaign`` -- the same function the ``daedalus ariadne``
CLI door and ``POST /api/ariadne`` call -- which materializes its three arms
from CAS into a checkout-external workspace under the subject's control root,
runs the frozen evaluator per arm under equal budgets, and writes a
``CampaignReceipt``. Nothing here applies a candidate anywhere.

Import direction (tests/contracts/test_import_scc_hierarchy.py): the
``daedalus.ariadne`` package imports the orchestration and runtimes packages,
so this module must not import it. The runner and the HEAD reader are handed
in by the orchestration caller (``computer_loop.campaign_runner()``), exactly
as ``ProjectReaders`` is for the observations.

Honesty (G1-SELF-01, master plan §8.1): the campaign's evaluator is the
frozen exact-match evaluator; a nomination proves isolation, provenance,
budget equality and non-application, not improvement. The result says so.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from daedalus.kernel.policy.computer import ComputerPolicy, ComputerRefused
from daedalus.kernel.source_trees import MANDATORY_IGNORED_ROOTS
from daedalus.runtimes.computer_daedalus import (
    _looks_like_host_path,
    _mentions_host_path,
    planner_lane,
)

#: The frozen evaluator's name in the receipt and in every result.
EVALUATOR_LABEL = "ariadne-frozen-evaluator (exact match)"
RESULT_SCHEMA = "daedalus-computer-ariadne-result/1"
MAX_TARGET_PATH_CHARS = 1000
MAX_FRAGMENT_CHARS = 200_000
TIMEOUT_MIN_S = 1
TIMEOUT_MAX_S = 120
TIMEOUT_DEFAULT_S = 30
_CAMPAIGN_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")
#: The roots the campaign itself refuses, from the one definition
#: (``kernel.source_trees``), so the refusal happens BEFORE the runner is
#: entered and cannot drift from the campaign's.
_IGNORED_ROOTS = frozenset(item.casefold() for item in MANDATORY_IGNORED_ROOTS)


class _PreRunRefusal(ComputerRefused):
    """Raised before the runner was entered: provably no effect."""

    effect_state = "none"


class _CampaignFailure(ComputerRefused):
    """The runner was entered and did not return a receipt: the campaign's own
    ledger and evidence say what happened; the computer lease cannot claim
    "no effect" and stays for reconciliation."""

    effect_state = "uncertain"


@dataclass(frozen=True)
class CampaignRunner:
    """What the orchestration layer hands in.

    ``run_campaign(**kwargs) -> dict`` is ``daedalus.ariadne.run_campaign``;
    ``head_revision(repo_root) -> str`` returns the subject's exact 40-hex HEAD
    through a read-only ``git rev-parse``; ``protected_prefix_for(relative)``
    is ``daedalus.ariadne.campaign.protected_prefix_for`` (the leakage boundary
    as code, G1-ARIADNE-10) so the refusal here and the campaign's agree by
    construction.
    """

    run_campaign: Callable[..., dict[str, Any]]
    head_revision: Callable[[str], str]
    protected_prefix_for: Callable[[str], str | None]


class AriadneCampaignTool:
    def __init__(self, policy: ComputerPolicy, project: str, checkpoint: Callable[[], None],
                 authority_root: Path, runner: CampaignRunner) -> None:
        self._policy = policy
        self._project = project
        self._checkpoint = checkpoint
        self._authority_root = Path(authority_root)
        self._runner = runner

    # ------------------------------------------------------------------ admission
    @property
    def lane(self) -> str:
        return planner_lane(self._policy)

    def _repo_root(self) -> str:
        from daedalus.foundation.projects import load_project, resolve_repo_root
        try:
            config = load_project(self._project)
            root = resolve_repo_root(config.get("repo_root"), self._project)
        except Exception as exc:  # noqa: BLE001 - every registry failure is a refusal, never a guess
            raise _PreRunRefusal(f"registered project is unavailable: {type(exc).__name__}: {exc}") from exc
        if not isinstance(root, str) or not root:
            raise _PreRunRefusal("registered project has no repository root")
        return root

    def _admit_target_path(self, value: object) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > MAX_TARGET_PATH_CHARS or "\x00" in value:
            raise _PreRunRefusal("target_path must be a bounded repository-relative path")
        relative = value.strip().replace("\\", "/")
        if _looks_like_host_path(relative) or relative.startswith("/") or ".." in relative.split("/"):
            raise _PreRunRefusal("target_path must be repository-relative, without '..' or an absolute prefix")
        if relative.split("/", 1)[0].casefold() in _IGNORED_ROOTS:
            raise _PreRunRefusal("target_path must not enter a mandatory ignored root")
        protected = self._runner.protected_prefix_for(relative)
        if protected is not None:
            raise _PreRunRefusal(
                "target_path is inside the self-Renovation leakage boundary (master plan section 8.1): "
                f"{protected}")
        return relative

    @staticmethod
    def _fragment(value: object, label: str, *, allow_empty: bool) -> str:
        if not isinstance(value, str):
            raise _PreRunRefusal(f"{label} must be text")
        if not value and not allow_empty:
            raise _PreRunRefusal(f"{label} must be non-empty")
        if len(value) > MAX_FRAGMENT_CHARS:
            raise _PreRunRefusal(f"{label} exceeds {MAX_FRAGMENT_CHARS} characters")
        return value

    @staticmethod
    def _timeout(value: object) -> int:
        if value is None:
            return TIMEOUT_DEFAULT_S
        if isinstance(value, bool) or not isinstance(value, int) or not TIMEOUT_MIN_S <= value <= TIMEOUT_MAX_S:
            raise _PreRunRefusal(f"timeout_s must be an integer between {TIMEOUT_MIN_S} and {TIMEOUT_MAX_S}")
        return value

    @staticmethod
    def _campaign_id(value: object, operation: Mapping[str, Any]) -> str:
        if value is None:
            digest = hashlib.sha256(json.dumps(operation, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
            return f"ikarus-{digest[:24]}"
        if not isinstance(value, str) or not _CAMPAIGN_ID_RE.fullmatch(value):
            raise _PreRunRefusal("campaign_id must be 1-64 path-free letters, digits, '.', '_' or '-'")
        return value

    # ------------------------------------------------------------------ execution
    def execute(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if type(arguments) is not dict:
            raise _PreRunRefusal("tool arguments must be an object")
        self._checkpoint()
        relative = self._admit_target_path(arguments.get("target_path"))
        before = self._fragment(arguments.get("before"), "before", allow_empty=False)
        after = self._fragment(arguments.get("after"), "after", allow_empty=True)
        if before == after:
            raise _PreRunRefusal("repair must replace before with a different value")
        timeout_s = self._timeout(arguments.get("timeout_s"))
        operation = {"target_path": relative, "before_sha256": hashlib.sha256(before.encode("utf-8")).hexdigest(),
                     "after_sha256": hashlib.sha256(after.encode("utf-8")).hexdigest(), "timeout_s": timeout_s,
                     "project": self._project}
        campaign_id = self._campaign_id(arguments.get("campaign_id"), operation)
        repo_root = self._repo_root()
        self._checkpoint()
        try:
            source_revision = self._runner.head_revision(repo_root)
        except Exception as exc:  # noqa: BLE001 - a HEAD that cannot be read is a refusal before any effect
            raise _PreRunRefusal(f"subject HEAD is unavailable: {type(exc).__name__}: {exc}") from exc
        if not isinstance(source_revision, str) or len(source_revision) != 40 or any(
                ch not in "0123456789abcdef" for ch in source_revision):
            raise _PreRunRefusal("subject HEAD must be the exact lowercase 40-hex revision")
        self._checkpoint()
        # From here on the runner owns the effect: its own lease, ledger and
        # evidence under the subject's control root. A failure is reported
        # with the campaign's own error class and text, never re-tried.
        try:
            receipt = self._runner.run_campaign(
                repo_root=repo_root, source_revision=source_revision, campaign_id=campaign_id,
                target_path=relative, before=before, after=after, timeout_s=timeout_s)
        except Exception as exc:  # noqa: BLE001 - classified by name, surfaced, never swallowed
            raise _CampaignFailure(f"{type(exc).__name__}: {exc}"[:1200]) from exc
        if not isinstance(receipt, Mapping):
            raise _CampaignFailure("campaign runner returned no receipt")
        return self._project_receipt(receipt, relative, campaign_id, source_revision)

    # ------------------------------------------------------------------ projection
    def _project_receipt(self, receipt: Mapping[str, Any], relative: str, campaign_id: str,
                         source_revision: str) -> dict[str, Any]:
        """The receipt as the planner may see it: verdicts, hashes and counts.

        No locator (they are absolute paths under the control root), no
        ``after`` text, no trial detail beyond verdict and wall time. The
        target path is echoed only if the lane's gate admits it -- the planner
        named it, but a retained mission report is read by more than the
        planner.
        """
        trials = []
        for trial in receipt.get("trials") or ():
            if not isinstance(trial, Mapping):
                continue
            usage_raw = trial.get("usage")
            usage: Mapping[str, Any] = usage_raw if isinstance(usage_raw, Mapping) else {}
            trials.append({
                "variant_id": str(trial.get("variant_id", "")),
                "status": str(trial.get("status", "")),
                "wall_time_ms": usage.get("wall_time_ms"),
                "negative_outcomes": [str(x) for x in (trial.get("negative_outcomes") or ())],
                "blockers": [str(x) for x in (trial.get("blockers") or ())],
            })
        equality_raw = receipt.get("budget_equality")
        equality: Mapping[str, Any] = equality_raw if isinstance(equality_raw, Mapping) else {}
        receipt_sha256 = hashlib.sha256(
            json.dumps(receipt, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()
        outcome = str(receipt.get("outcome", ""))
        target = relative if self._admit_path(relative) else "<withheld>"
        result = {
            "schema": RESULT_SCHEMA,
            "kind": "campaign",
            "project": self._project,
            "lane": self.lane,
            "outcome": outcome,
            "campaign_id": campaign_id,
            "source_revision": source_revision,
            "target_path": target,
            "selected_variant_id": receipt.get("selected_variant_id"),
            "selected_seed": receipt.get("selected_seed"),
            "selection_mode": receipt.get("selection_mode"),
            "trials": trials,
            "budget_equality": {key: equality.get(key) for key in
                                ("configured_equal", "realized_usage_recorded", "within_budget")},
            "negative_outcomes": [str(x) for x in (receipt.get("negative_outcomes") or ())],
            "candidate_tree_sha256": receipt.get("candidate_tree_sha256"),
            "nomination_receipt_sha256": receipt.get("nomination_receipt_sha256"),
            "campaign_receipt_sha256": receipt_sha256,
            "evaluator": EVALUATOR_LABEL,
            "applied": False,
            "host_mutation": True,
            "postcondition_verified": outcome == "nominated" and bool(receipt.get("nomination_receipt_sha256")),
            "note": ("nominated candidates are content-addressed evidence under the subject's control root; "
                     "nothing was applied to any checkout, and the frozen exact-match evaluator proves the "
                     "machinery, not improvement"),
        }
        rendered = json.dumps(result, ensure_ascii=False, default=str)
        if _mentions_host_path(rendered):
            raise _CampaignFailure("campaign projection carried a host path; withheld")
        return json.loads(json.dumps(result, ensure_ascii=False, default=str, allow_nan=False))

    def _admit_path(self, relative: str) -> bool:
        from daedalus.foundation.projects import load_project
        from daedalus.sensitivity import load_policy, slice_egress_rule
        try:
            policy = load_policy(load_project(self._project))
        except Exception:  # noqa: BLE001 - an unreadable policy withholds, never admits
            return False
        return slice_egress_rule(relative, relative, lane=self.lane, policy=policy) is None
