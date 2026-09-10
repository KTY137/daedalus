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
import os
import re
import time
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
#: The campaign's own rule (``campaign._CAMPAIGN_ID_RE``): first character
#: alphanumeric, then up to 63 of ``[A-Za-z0-9._-]`` (Odysseus round 1, D3: a
#: looser rule here let ``.hidden`` reach the runner and be refused there).
_CAMPAIGN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_WINDOWS_RESERVED = frozenset({"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
                               *(f"lpt{i}" for i in range(1, 10))})
TRIALS_SHOWN = 8
LIST_SHOWN = 10
#: Every projected value is bounded as well as every list: a receipt field is
#: producer-supplied, and a 2 MB ``selection_mode`` yielded a 2.5 MB projection
#: (Odysseus round 2 of this packet, D9).
MAX_VALUE_CHARS = 200
#: How far the evidence freshness check may look back, in seconds: filesystem
#: timestamp granularity and a clock that ticks between the two reads.
EVIDENCE_MTIME_TOLERANCE_S = 2.0
#: Names the subject's filesystem would fold together or rewrite. The evidence
#: directory is named after the campaign ID, and Windows resolves ``camp1``,
#: ``CAMP1`` and ``camp1.`` to ONE directory, so two IDs this adapter treats as
#: distinct would share one postcondition (Odysseus round 2, D11).
_RESERVED_NAMES = frozenset({"con", "prn", "aux", "nul", "com0", "com1", "com2", "com3", "com4", "com5",
                             "com6", "com7", "com8", "com9", "lpt0", "lpt1", "lpt2", "lpt3", "lpt4",
                             "lpt5", "lpt6", "lpt7", "lpt8", "lpt9"})
#: The roots the campaign itself refuses, from the one definition
#: (``kernel.source_trees``), so the refusal happens BEFORE the runner is
#: entered and cannot drift from the campaign's.
_IGNORED_ROOTS = frozenset(item.casefold() for item in MANDATORY_IGNORED_ROOTS)


_MESSAGE_WITHHELD = "<message withheld: host path>"


def _safe_failure_text(exc: BaseException) -> str:
    """``ClassName: message`` -- but the message only if it names no host path.

    Refusal and failure texts reach the planner's history like any result
    (Cerberus round 1 of this packet, CRITICAL 1: ``git rev-parse`` and the
    campaign's own ``repo_root is unavailable or unsafe: [WinError 2] …`` carried
    the subject's absolute path). The campaign's clean texts ("before text must
    occur exactly once", "linked git worktree") stay useful.
    """
    message = str(exc)[:1200]
    if not message:
        return type(exc).__name__
    if _mentions_host_path(message) or _looks_like_host_path(message):
        return f"{type(exc).__name__}: {_MESSAGE_WITHHELD}"
    return f"{type(exc).__name__}: {message}"


def _listed(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _short(value: Any) -> Any:
    """A projected value, bounded. Numbers and ``None`` pass; everything else
    is text and is cut at :data:`MAX_VALUE_CHARS` with the loss stated."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = value if isinstance(value, str) else str(value)
    if len(text) <= MAX_VALUE_CHARS:
        return text
    return text[:MAX_VALUE_CHARS] + f"...(+{len(text) - MAX_VALUE_CHARS} chars)"


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


class _PreRunRefusal(ComputerRefused):
    """Raised before the runner was entered: provably no CAMPAIGN effect (the
    computer lease and its evidence are written and settled as cancelled)."""

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
        if not isinstance(runner, CampaignRunner):
            raise ComputerRefused("campaign runner has the wrong type")
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
            raise _PreRunRefusal(f"registered project is unavailable: {type(exc).__name__}") from exc
        if not isinstance(root, str) or not root:
            raise _PreRunRefusal("registered project has no repository root")
        return root

    def _admit_target_path(self, value: object) -> str:
        """Lexical admission of the requested path -- the spelling, not the file.

        Every segment is held to the kernel's own path rule (no ``..``, no
        ``.``, no empty segment, no trailing dot or space, no ``:``, no
        Windows-invalid character, no device name): Odysseus round 1 of this
        packet drove ``daedalus/spine./killswitch.py`` (Windows strips the dot)
        and ``./daedalus/spine/x.py`` past a check that looked at the string
        only. The resolved FILE is checked again in :meth:`_admit_target_file`.
        """
        if not isinstance(value, str) or not value.strip() or len(value) > MAX_TARGET_PATH_CHARS or "\x00" in value:
            raise _PreRunRefusal("target_path must be a bounded repository-relative path")
        relative = value.strip().replace("\\", "/")
        if _looks_like_host_path(relative) or relative.startswith("/"):
            raise _PreRunRefusal("target_path must be repository-relative, without '..' or an absolute prefix")
        segments = relative.split("/")
        for segment in segments:
            if segment in ("", ".", ".."):
                raise _PreRunRefusal("target_path must be repository-relative, without '..' or an absolute prefix")
            if segment.rstrip(" .") != segment or ":" in segment or any(
                    ord(ch) < 32 or ch in '<>"|?*' for ch in segment):
                raise _PreRunRefusal("target_path segment has a spelling the subject filesystem would rewrite")
            if segment.split(".", 1)[0].casefold() in _WINDOWS_RESERVED:
                raise _PreRunRefusal("target_path names a Windows device")
        if segments[0].casefold() in _IGNORED_ROOTS:
            raise _PreRunRefusal("target_path must not enter a mandatory ignored root")
        protected = self._runner.protected_prefix_for(relative)
        if protected is not None:
            raise _PreRunRefusal(
                "target_path is inside the self-Renovation leakage boundary (master plan section 8.1): "
                f"{protected}")
        return relative

    def _admit_target_file(self, repo_root: str, relative: str) -> None:
        """The requested path must denote the same regular file once RESOLVED.

        Odysseus round 1 of this packet (D1, high): a directory junction inside
        the subject (``shortcut`` -> ``daedalus/spine``) is not a symlink for
        ``S_ISLNK``, so ``shortcut/killswitch.py`` passed every string check and
        the campaign nominated a change to a protected file. The real path is
        resolved (junctions and symlinks included), must stay inside the
        resolved subject, must spell the very path that was requested, and is
        held to the leakage boundary again. Reads only; no effect.
        """
        subject = Path(repo_root)
        try:
            real_root = Path(os.path.realpath(subject))
            candidate = subject.joinpath(*relative.split("/"))
            real = Path(os.path.realpath(candidate))
            resolved = real.relative_to(real_root).as_posix()
        except (OSError, ValueError) as exc:
            raise _PreRunRefusal(f"target_path does not resolve inside the subject: {type(exc).__name__}") from exc
        if resolved.casefold() != relative.casefold():
            raise _PreRunRefusal("target_path resolves through a link, junction or a rewritten spelling")
        protected = self._runner.protected_prefix_for(resolved)
        if protected is not None:
            raise _PreRunRefusal(
                "target_path is inside the self-Renovation leakage boundary (master plan section 8.1): "
                f"{protected}")
        try:
            info = os.lstat(candidate)
        except OSError as exc:
            raise _PreRunRefusal(f"target_path is not a regular file in the subject: {type(exc).__name__}") from exc
        import stat
        if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise _PreRunRefusal("target_path is not a regular file in the subject")
        # A HARD link is a second NAME for one inode, not a link the resolver
        # can see: ``os.path.realpath`` returns the requested spelling and the
        # boundary check passes, while the file also lives inside the leakage
        # boundary (Odysseus round 2 of this packet: a hardlink to
        # ``daedalus/spine/killswitch.py`` was admitted). The kernel has this
        # check but resolves against the computer workspace, so it never sees
        # the subject's tree.
        if getattr(info, "st_nlink", 1) > 1:
            raise _PreRunRefusal("target_path has more than one name (hard link); the subject file is ambiguous")

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
        # The ID names a directory, so it is held to the same filesystem
        # spelling rule as the target path segments (Odysseus round 2, D11).
        if value != value.casefold() or value.rstrip(". ") != value or value.split(".")[0].casefold() in _RESERVED_NAMES:
            raise _PreRunRefusal("campaign_id must be lower case, must not end in '.' or a space, and must not "
                                 "be a reserved device name: the evidence directory is named after it")
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
        # The evidence check below must prove THIS run wrote evidence: the
        # default campaign ID is derived from the operation, so a receipt
        # forged for an operation that already ran once would otherwise inherit
        # the first run's directory (Odysseus round 2 of this packet, D4).
        started_at = time.time()
        self._checkpoint()
        self._admit_target_file(repo_root, relative)
        try:
            source_revision = self._runner.head_revision(repo_root)
        except Exception as exc:  # noqa: BLE001 - a HEAD that cannot be read is a refusal before any effect
            raise _PreRunRefusal(f"subject HEAD is unavailable: {_safe_failure_text(exc)}") from exc
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
            raise _CampaignFailure(_safe_failure_text(exc)) from exc
        if not isinstance(receipt, Mapping):
            raise _CampaignFailure("campaign runner returned no receipt")
        # Nothing below may raise a PRE-run refusal: the campaign has run. The
        # projection takes what it needs as arguments and turns any failure of
        # the evidence check into ``evidence_present=False`` (Cerberus round 2
        # of this packet, NEW-1: a second registry read inside the projection
        # raised ``_PreRunRefusal`` after the runner and the lease was settled
        # as if nothing had happened).
        return self._project_receipt(receipt, relative, campaign_id, source_revision, repo_root, started_at)

    # ------------------------------------------------------------------ projection
    def _project_receipt(self, receipt: Mapping[str, Any], relative: str, campaign_id: str,
                         source_revision: str, repo_root: str, started_at: float) -> dict[str, Any]:
        """The receipt as the planner may see it: verdicts, hashes and counts.

        No locator (they are absolute paths under the control root), no
        ``after`` text, no trial detail beyond verdict and wall time. The
        target path is echoed only if the lane's gate admits it -- the planner
        named it, but a retained mission report is read by more than the
        planner.

        The receipt is rendered ONCE (``default=str``); its digest is taken over
        that text and the projection is built from the PARSED rendering, so no
        value is stringified a second time on the way out (Odysseus round 1 of
        this packet, D6).
        """
        try:
            receipt_text = json.dumps(receipt, sort_keys=True, ensure_ascii=False, default=str, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise _CampaignFailure(f"campaign receipt is not renderable: {type(exc).__name__}") from exc
        receipt_sha256 = hashlib.sha256(receipt_text.encode("utf-8")).hexdigest()
        data: Mapping[str, Any] = json.loads(receipt_text)
        trials = []
        all_trials = [t for t in (data.get("trials") or ()) if isinstance(t, Mapping)] \
            if isinstance(data.get("trials"), (list, tuple)) else []
        for trial in all_trials[:TRIALS_SHOWN]:
            usage_raw = trial.get("usage")
            usage: Mapping[str, Any] = usage_raw if isinstance(usage_raw, Mapping) else {}
            trials.append({
                "variant_id": _short(str(trial.get("variant_id", ""))),
                "status": _short(str(trial.get("status", ""))),
                "wall_time_ms": _short(usage.get("wall_time_ms")),
                "negative_outcomes": [_short(str(x)) for x in _listed(trial.get("negative_outcomes"))][:LIST_SHOWN],
                "blockers": [_short(str(x)) for x in _listed(trial.get("blockers"))][:LIST_SHOWN],
            })
        equality_raw = data.get("budget_equality")
        equality: Mapping[str, Any] = equality_raw if isinstance(equality_raw, Mapping) else {}
        outcome = _short(str(data.get("outcome", "")))
        try:
            target = relative if self._admit_path(relative) else "<withheld>"
        except Exception:  # noqa: BLE001 - same rule: after the runner nothing here may refuse
            target = "<withheld>"
        negative = [_short(str(x)) for x in _listed(data.get("negative_outcomes"))]
        candidate_sha = data.get("candidate_tree_sha256")
        nomination_sha = data.get("nomination_receipt_sha256")
        # The postcondition is BACKED (Odysseus round 1, D4): a nomination, two
        # well-formed digests, and evidence written under the subject's control
        # root DURING this run (Odysseus round 2, D4 residue: the directory is
        # named after the campaign ID, and the default ID is a digest of the
        # operation, so a second call with the same operation found the first
        # run's directory). ``EVIDENCE_MTIME_TOLERANCE_S`` absorbs filesystem
        # timestamp granularity; the check says evidence appeared around this
        # run, never that a particular receipt produced it.
        try:
            from daedalus.spine.killswitch import control_root
            evidence_dir = control_root(Path(repo_root)) / "ariadne" / "effect-evidence" / campaign_id
            floor = started_at - EVIDENCE_MTIME_TOLERANCE_S
            evidence_present = evidence_dir.is_dir() and any(
                entry.is_file() and entry.stat().st_mtime >= floor for entry in evidence_dir.rglob("*"))
        except Exception:  # noqa: BLE001 - after the runner, a failed check is "not verified", never a refusal
            evidence_present = False
        verified = (outcome == "nominated" and _is_sha256(candidate_sha) and _is_sha256(nomination_sha)
                    and evidence_present)
        result = {
            "schema": RESULT_SCHEMA,
            "kind": "campaign",
            "project": self._project,
            "lane": self.lane,
            "outcome": outcome,
            "campaign_id": campaign_id,
            "source_revision": source_revision,
            "target_path": target,
            "selected_variant_id": _short(data.get("selected_variant_id")),
            "selected_seed": _short(data.get("selected_seed")),
            "selection_mode": _short(data.get("selection_mode")),
            "trials": trials,
            "trials_elided": max(0, len(all_trials) - TRIALS_SHOWN),
            "budget_equality": {key: _short(equality.get(key)) for key in
                                ("configured_equal", "realized_usage_recorded", "within_budget")},
            "negative_outcomes": negative[:LIST_SHOWN],
            "negative_outcomes_elided": max(0, len(negative) - LIST_SHOWN),
            "candidate_tree_sha256": candidate_sha if _is_sha256(candidate_sha) else None,
            "nomination_receipt_sha256": nomination_sha if _is_sha256(nomination_sha) else None,
            "campaign_receipt_sha256": receipt_sha256,
            "evaluator": EVALUATOR_LABEL,
            "applied": False,
            "host_mutation": True,
            "postcondition_verified": verified,
            "evidence_present": evidence_present,
            "note": ("nominated candidates are content-addressed evidence under the subject's control root; "
                     "nothing was applied to any checkout, and the frozen exact-match evaluator proves the "
                     "machinery, not improvement"),
        }
        # Rendered ONCE; the gate reads the rendering and the rendering is what
        # is returned (Odysseus round 1, D6; the G1-IKARUS-46 doctrine). A value
        # that cannot be rendered is a failure, not a crash.
        try:
            rendered_text = json.dumps(result, ensure_ascii=False, default=str, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise _CampaignFailure(f"campaign projection is not renderable: {type(exc).__name__}") from exc
        if _mentions_host_path(rendered_text) or _looks_like_host_path(rendered_text):
            raise _CampaignFailure("campaign projection carried a host path; withheld")
        return json.loads(rendered_text)

    def _admit_path(self, relative: str) -> bool:
        """The lane's gate on the target path echo (a retained report is read
        by more than the planner). On the TRUSTED lane ``slice_egress_rule``
        applies the secret floor only -- exactly as for the Voice -- so a path
        the project's deny list names is echoed there and withheld on the
        untrusted lane (Cerberus round 2, NEW-2: stated, not claimed away)."""
        from daedalus.foundation.projects import load_project
        from daedalus.sensitivity import load_policy, slice_egress_rule
        try:
            policy = load_policy(load_project(self._project))
        except Exception:  # noqa: BLE001 - an unreadable policy withholds, never admits
            return False
        return slice_egress_rule(relative, relative, lane=self.lane, policy=policy) is None
