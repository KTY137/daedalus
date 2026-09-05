"""One bounded deterministic repair campaign; nomination is the terminal ceiling."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from daedalus.atomic import ExclusiveFileLock, FileLockUnavailable
from daedalus.gates.repository.head_revision import verify_repository_head_revision
from daedalus.gates.repository.tree import (
    RepositoryTreeRaceError,
    RepositoryTreeReadError,
    read_repository_source,
)
from daedalus.kernel.artifacts import ArtifactRef
from daedalus.kernel.attempt_execution import RunnerContext, TaskSpec
from daedalus.kernel.interpreter import (
    interpreter_provenance as _interpreter_provenance,
    stdlib_interpreter as _evaluator_interpreter,
)
from daedalus.kernel.attempt_contracts import AttemptTerminalReceipt
from daedalus.kernel.attempts import AttemptLedger, IsolatedAttemptCoordinator
from daedalus.kernel.effects import EffectLeaseError
from daedalus.kernel.campaigns import (
    CampaignIdentityConflict,
    CampaignLifecycleError,
    begin_campaign,
    campaign_contract_for_spec,
    complete_campaign,
    fail_campaign,
    load_attempt_contract,
    load_attempt_receipt,
    load_evidence_packet,
    lookup_campaign_read_only,
    store_contract,
)
from daedalus.kernel.contracts import (
    AttemptContract,
    CampaignBudgetEqualityEvidence,
    CampaignReceipt,
    CampaignTrialReceipt,
    ContractProvenance,
    EvidenceItem,
    EvidencePacket,
    ExperimentSpec,
    NominationReceipt,
    ResourceBudget,
    ResourceUsage,
)
from daedalus.kernel.offload_lease import (
    ATTEMPT_ENTRYPOINT_ID,
    WaveLeaseDenied,
    acquire_attempt_lease,
    acquire_effect_lease,
    control_root,
    require_retained_effect_lease_start_records,
    require_retained_effect_lease_terminal_record,
)
from daedalus.kernel.source_trees import (
    MANDATORY_IGNORED_ROOTS,
    SourceTreeEntry,
    SourceTreeManifest,
    SourceTreeStore,
    SourceTreeStoreError,
    StoredSourceTree,
)
from daedalus.orchestration.execution.attempts import command_gate
from daedalus.runtimes.contracts.repository import (
    RepositoryHeadRevisionBindingError,
    RepositoryHeadRevisionRaceError,
    RepositoryHeadRevisionShapeError,
)
from daedalus.sensitivity import Policy
from daedalus.spine.envelope import canonical_json, canonical_sha
from daedalus.spine.killswitch import KillSwitch
from daedalus.spine.picker import resolve_spine_db_path


ENTRYPOINT_ID = "python.ariadne_campaign"
EVALUATOR_SOURCE = """import hashlib,json,pathlib,sys
p=pathlib.Path(sys.argv[1]); got=hashlib.sha256(p.read_bytes()).hexdigest(); expected=sys.argv[2]
print(json.dumps({'expected_sha256':expected,'observed_sha256':got,'passed':got==expected},sort_keys=True,separators=(',',':')))
raise SystemExit(0 if got==expected else 1)
"""
EVALUATOR_SHA256 = hashlib.sha256(EVALUATOR_SOURCE.encode("utf-8")).hexdigest()
#: Retained evaluator observations: ``/1`` predates interpreter provenance,
#: ``/2`` records the path-free identity of the interpreter that ran the arm.
_EVALUATOR_OBSERVATION_SCHEMAS = (
    "daedalus-ariadne-evaluator-observation/1",
    "daedalus-ariadne-evaluator-observation/2",
)
_EVALUATOR_OBSERVATION_KEYS = (
    "schema", "variant_id", "seed", "evaluator_sha256", "passed", "returncode",
    "output", "output_sha256", "candidate_tree_sha256", "expected_sha256",
    "observed_sha256", "containment",
)
_INTERPRETER_PROVENANCE_KEYS = frozenset(
    {"implementation", "version", "platform", "binary_sha256"}
)
_CAMPAIGN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MAX_REPAIR_FRAGMENT_BYTES = 1 * 1024 * 1024
MAX_CAMPAIGN_FILE_BYTES = 16 * 1024 * 1024
_NEGATIVE_CONTROL_SUFFIX = "__ariadne_negative__"
_OUTER_EFFECT_BINDING_SCHEMA = "daedalus-ariadne-outer-effect-binding/1"
_INNER_EFFECT_BINDING_SCHEMA = "daedalus-ariadne-inner-effect-binding/1"
_ATTEMPT_REPORT_SCHEMA = "daedalus-ariadne-attempt-report/2"
_EVALUATOR_ERROR_SCHEMA = "daedalus-ariadne-evaluator-error/1"
_MAX_OUTER_EFFECT_BINDING_BYTES = 64 * 1024
_MAX_ATTEMPT_REPORT_BYTES = 1 * 1024 * 1024
_MAX_RECEIPT_PROVENANCE_INPUTS = 256


class AriadneCampaignError(RuntimeError):
    pass


class AriadneRequestError(AriadneCampaignError):
    """The owner-supplied campaign subject is malformed or unavailable."""


class AriadneConflictError(AriadneCampaignError):
    """A stable request binding no longer matches repository state."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _prov(origin: str, revision: str, at: str, *digests: str, trace: str):
    return ContractProvenance(
        origin=origin,
        source_revision=revision,
        created_at=at,
        input_digests=tuple(sorted(set(digests))),
        trace_id=trace,
    )


def _campaign_id(value: object) -> str:
    text = value if isinstance(value, str) else ""
    if not _CAMPAIGN_ID_RE.fullmatch(text):
        raise AriadneCampaignError(
            "campaign_id must be 1-64 path-free letters, digits, '.', '_' or '-'"
        )
    return text


def _repair_fragment(value: object, *, label: str, allow_empty: bool) -> tuple[str, bytes]:
    if type(value) is not str:
        raise AriadneCampaignError(f"{label} must be a strict string")
    if not value and not allow_empty:
        raise AriadneCampaignError(f"{label} must be non-empty")
    try:
        payload = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise AriadneCampaignError(f"{label} must be strict UTF-8") from exc
    if len(payload) > MAX_REPAIR_FRAGMENT_BYTES:
        raise AriadneCampaignError(
            f"{label} exceeds the {MAX_REPAIR_FRAGMENT_BYTES}-byte repair-fragment ceiling"
        )
    return value, payload


def _is_domain_failure(failure: BaseException) -> bool:
    """True for a campaign-domain verdict that the retained failed receipt already carries.

    Cancellation (``LoopHalted``) and foreign exceptions (a crash inside the
    gate, ``OSError``) are not verdicts about the candidate and keep raising.
    """
    from daedalus.spine.killswitch import LoopHalted

    if isinstance(failure, LoopHalted):
        return False
    return isinstance(failure, AriadneCampaignError)


def _verify_head(root: Path, source_revision: str):
    try:
        return verify_repository_head_revision(root, source_revision)
    except (RepositoryHeadRevisionBindingError, RepositoryHeadRevisionRaceError) as exc:
        raise AriadneConflictError(f"source_revision conflict: {exc}") from exc
    except RepositoryHeadRevisionShapeError as exc:
        message = f"repository HEAD is unavailable or unsafe: {exc}"
        if _is_gitdir_pointer_file(root / ".git"):
            # Deliberately unsupported subject layout (G1-ARIADNE-06): a gitdir
            # pointer is bytes a candidate can rewrite, so the gate never
            # follows it (tests/test_git_is_a_process_launcher.py measured the
            # attack). Name the layout and the remedy instead of the bare
            # shape error.
            message += (
                "; the subject is a linked git worktree (.git is a gitdir pointer "
                "file), a deliberately unsupported subject layout: clone the "
                "repository or use its common checkout"
            )
        raise AriadneRequestError(message) from exc


def _is_gitdir_pointer_file(path: Path) -> bool:
    """True when ``.git`` is a regular file whose first line is ``gitdir:``."""
    try:
        if path.is_symlink() or not path.is_file():
            return False
        with path.open("rb") as stream:
            return stream.read(7) == b"gitdir:"
    except OSError:
        return False


_BASE_BINDING_SCHEMA = "daedalus-ariadne-base-tree-binding/1"


def _base_tree_binding(
    *, campaign_id: str, source_revision: str, relative: str, base_file_sha256: str
) -> dict[str, Any]:
    """What the campaign base IS: the working-tree bytes, content-addressed.

    The receipt binds ``source_revision`` (the verified HEAD) and the base
    tree (CAS). It never verified that the base bytes are the file's content
    AT that revision, and a raw byte compare against the HEAD blob would lie
    under git line-ending filters. So the claim is stated instead of faked:
    ``base_source`` is the working tree and ``head_content_verified`` is
    false until a separate packet verifies it through git itself.
    """
    return {
        "schema": _BASE_BINDING_SCHEMA,
        "campaign_id": campaign_id,
        "source_revision": source_revision,
        "target_path": relative,
        "base_file_sha256": base_file_sha256,
        "base_source": "working-tree",
        "head_content_verified": False,
    }


def _admit_target_path(value: str) -> str:
    """Pure path admission: no filesystem, no repository, no HEAD.

    Shape and mandatory-ignored-root refusals happen before the repository is
    observed at all, so a refused request leaves no trace and needs no
    ``.git``. Reading the admitted path is :func:`_safe_target`.
    """
    if type(value) is not str:
        raise AriadneRequestError("target_path must be a strict string")
    try:
        task = TaskSpec(
            task_id="ariadne-admission",
            instruction="admit",
            target_paths=(value,),
        )
    except (TypeError, ValueError) as exc:
        raise AriadneRequestError(f"target_path is invalid: {exc}") from exc
    relative = task.target_paths[0]
    ignored = {item.casefold() for item in MANDATORY_IGNORED_ROOTS}
    if relative.split("/", 1)[0].casefold() in ignored:
        raise AriadneRequestError(
            "target_path must not enter a mandatory ignored root"
        )
    return relative


def _safe_target(root: Path, value: str):
    relative = _admit_target_path(value)
    try:
        return relative, read_repository_source(root, relative)
    except RepositoryTreeRaceError as exc:
        raise AriadneConflictError(f"target_path changed during admission: {exc}") from exc
    except RepositoryTreeReadError as exc:
        raise AriadneRequestError(f"target_path is unavailable or unsafe: {exc}") from exc


def _store_scoped_tree(
    store: SourceTreeStore,
    *,
    payload: bytes,
    relative: str,
    tree_id: str,
    source_revision: str,
    created_at: str,
    trace_id: str,
    origin: str,
) -> StoredSourceTree:
    """Persist one stabilized target file in the canonical source-tree CAS."""
    blob = store.put_bytes(payload)
    manifest = SourceTreeManifest(
        tree_id=tree_id,
        source_revision=source_revision,
        entries=(SourceTreeEntry(
            path=relative, blob_sha256=blob.sha256, size=len(payload), executable=False,
        ),),
        ignored_roots=MANDATORY_IGNORED_ROOTS,
        provenance=_prov(origin, source_revision, created_at, blob.sha256, trace=trace_id),
    )
    ref = store.put_bytes(manifest.to_json().encode("ascii"))
    return StoredSourceTree(manifest=manifest, ref=ref)


def _verify_frozen_evaluator_output(
    result: Any,
    candidate: StoredSourceTree,
    *,
    relative: str,
    expected_sha256: str,
) -> dict[str, Any]:
    """Bind the evaluator verdict to the exact candidate blob it observed."""

    entries = tuple(candidate.manifest.entries)
    if len(entries) != 1 or entries[0].path != relative:
        raise AriadneCampaignError(
            "candidate tree is not the frozen one-file evaluator subject"
        )
    try:
        value = json.loads(result.output)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise AriadneCampaignError("frozen evaluator output is invalid") from exc
    if (
        not isinstance(value, dict)
        or set(value) != {"expected_sha256", "observed_sha256", "passed"}
        or canonical_json(value) + "\n" != result.output
        or type(value.get("passed")) is not bool
        or value.get("expected_sha256") != expected_sha256
        or value.get("observed_sha256") != entries[0].blob_sha256
        or value.get("passed")
        != (value.get("observed_sha256") == expected_sha256)
        or bool(result.passed) != value.get("passed")
        or result.returncode != (0 if value.get("passed") else 1)
    ):
        raise AriadneCampaignError(
            "frozen evaluator output does not bind the candidate CAS blob"
        )
    return value


def _bounded_failure(exc: BaseException) -> tuple[str, str]:
    """Return bounded, reproducible failure text suitable for retained evidence."""

    error_type = type(exc).__name__[:200] or "Exception"
    message = str(exc)
    if len(message) > 2000:
        message = message[:1997] + "..."
    return error_type, message or error_type


def _inner_effect_binding(
    granted: Any,
    execution: Any,
    attempt: AttemptContract,
    *,
    expected_terminal_state: str,
) -> dict[str, str]:
    """Freeze and verify one attempt lease identity before its terminal commit."""

    if expected_terminal_state not in {"completed", "failed"}:
        raise AriadneCampaignError("inner effect expected terminal state is invalid")
    subject_digest = granted.evidence_records.get("lease_subject")
    execution_digest = granted.evidence_records.get(
        f"lease_execution:{execution.execution_id}"
    )
    digests = {
        "operation_sha256": attempt.digest,
        "lease_sha256": granted.lease.digest,
        "lease_subject_record_sha256": subject_digest,
        "lease_execution_record_sha256": execution_digest,
    }
    if any(
        not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None
        for value in digests.values()
    ):
        raise AriadneCampaignError(
            "inner attempt effect evidence was not retained before commit"
        )
    try:
        chain = require_retained_effect_lease_start_records(
            granted.evidence_root,
            subject_record_sha256=subject_digest,
            execution_record_sha256=execution_digest,
            entrypoint_id=ATTEMPT_ENTRYPOINT_ID,
            source_revision=attempt.base_revision,
            attempt_id=attempt.attempt_id,
            operation_sha256=attempt.digest,
            expected_lease_sha256=granted.lease.digest,
            expected_execution_id=execution.execution_id,
            expected_execution_request_sha256=execution.digest,
        )
    except (EffectLeaseError, OSError, TypeError, ValueError) as exc:
        raise AriadneCampaignError(
            "inner attempt effect evidence is unavailable or invalid before commit"
        ) from exc
    request = chain["subject_record"].get("request")
    execution_payload = chain.get("execution")
    if (
        not isinstance(request, dict)
        or request.get("mission_id") != attempt.mission_id
        or not isinstance(execution_payload, dict)
        or tuple(execution_payload.get("writable_paths", ()))
        != tuple(attempt.writable_paths)
        or tuple(execution_payload.get("tools", ())) != ("python",)
    ):
        raise AriadneCampaignError(
            "inner attempt effect evidence differs from its AttemptContract"
        )
    return {
        "schema": _INNER_EFFECT_BINDING_SCHEMA,
        "campaign_id": str(attempt.campaign_id),
        "source_revision": attempt.base_revision,
        "attempt_id": attempt.attempt_id,
        "entrypoint_id": ATTEMPT_ENTRYPOINT_ID,
        **digests,
        "execution_id": execution.execution_id,
        "execution_request_sha256": execution.digest,
        "expected_terminal_state": expected_terminal_state,
    }


def _store_attempt_report(
    store: SourceTreeStore,
    *,
    packet_ref: ArtifactRef,
    observation_ref: ArtifactRef,
    inner_effect: dict[str, str],
) -> ArtifactRef:
    report = {
        "schema": _ATTEMPT_REPORT_SCHEMA,
        "evidence": packet_ref.to_dict(),
        "observation": observation_ref.to_dict(),
        "inner_effect": inner_effect,
    }
    return store.put_bytes(canonical_json(report).encode("ascii"))


def _require_bound_inner_terminal(
    evidence_root: Path,
    binding: dict[str, Any],
    attempt: AttemptContract,
    attempt_receipt: AttemptTerminalReceipt,
) -> None:
    """Verify a report-bound inner subject -> execution -> terminal chain."""

    expected_state = (
        "completed" if attempt_receipt.outcome == "succeeded" else "failed"
    )
    expected_keys = {
        "schema",
        "campaign_id",
        "source_revision",
        "attempt_id",
        "entrypoint_id",
        "operation_sha256",
        "lease_sha256",
        "lease_subject_record_sha256",
        "lease_execution_record_sha256",
        "execution_id",
        "execution_request_sha256",
        "expected_terminal_state",
    }
    if (
        set(binding) != expected_keys
        or binding.get("schema") != _INNER_EFFECT_BINDING_SCHEMA
        or binding.get("campaign_id") != attempt.mission_id
        or binding.get("campaign_id") != attempt.campaign_id
        or binding.get("source_revision") != attempt.base_revision
        or binding.get("attempt_id") != attempt.attempt_id
        or binding.get("entrypoint_id") != ATTEMPT_ENTRYPOINT_ID
        or binding.get("operation_sha256") != attempt.digest
        or binding.get("expected_terminal_state") != expected_state
    ):
        raise AriadneCampaignError(
            "inner attempt effect binding differs from its terminal Attempt receipt"
        )
    try:
        terminal = require_retained_effect_lease_terminal_record(
            evidence_root,
            subject_record_sha256=str(binding["lease_subject_record_sha256"]),
            execution_record_sha256=str(binding["lease_execution_record_sha256"]),
            entrypoint_id=ATTEMPT_ENTRYPOINT_ID,
            source_revision=attempt.base_revision,
            attempt_id=attempt.attempt_id,
            operation_sha256=attempt.digest,
            expected_lease_sha256=str(binding["lease_sha256"]),
            expected_execution_id=str(binding["execution_id"]),
            expected_execution_request_sha256=str(
                binding["execution_request_sha256"]
            ),
            expected_terminal_state=expected_state,
            expected_output_digests=(attempt_receipt.digest,),
        )
    except (EffectLeaseError, OSError, TypeError, ValueError) as exc:
        raise AriadneCampaignError(
            f"inner attempt effect needs reconciliation: {exc}"
        ) from exc
    if (
        terminal.get("lease_sha256") != binding["lease_sha256"]
        or terminal.get("execution_id") != binding["execution_id"]
        or terminal.get("execution_request_sha256")
        != binding["execution_request_sha256"]
    ):
        raise AriadneCampaignError(
            "inner attempt effect needs reconciliation: terminal binding is invalid"
        )


def _require_campaign_inner_effect_terminals(
    store: SourceTreeStore,
    evidence_root: Path,
    receipt: CampaignReceipt,
) -> None:
    """Replay every controlled-repair Attempt and its exact inner lease chain."""

    for trial in receipt.trials:
        if trial.receipt_profile != "controlled-repair-v1":
            continue
        if (
            len(trial.attempt_ids) != 1
            or len(trial.attempt_contract_locators) != 1
            or len(trial.attempt_receipt_locators) != 1
        ):
            raise AriadneCampaignError(
                "controlled-repair trial does not retain exactly one Attempt chain"
            )
        try:
            attempt = load_attempt_contract(
                store, trial.attempt_contract_locators[0]
            )
            loaded_receipt = load_attempt_receipt(
                store, trial.attempt_receipt_locators[0]
            )
            if not isinstance(loaded_receipt, AttemptTerminalReceipt):
                raise AriadneCampaignError(
                    "controlled-repair trial uses the wrong Attempt receipt profile"
                )
            packet = load_evidence_packet(store, trial.evidence_packet_locator)
            payload = store.read_bytes(
                loaded_receipt.report, max_bytes=_MAX_ATTEMPT_REPORT_BYTES
            )
            report = json.loads(payload.decode("ascii"))
        except AriadneCampaignError:
            raise
        except (
            CampaignLifecycleError,
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            SourceTreeStoreError,
            TypeError,
            ValueError,
        ) as exc:
            raise AriadneCampaignError(
                "controlled-repair Attempt report is unavailable or invalid"
            ) from exc
        if (
            not isinstance(report, dict)
            or set(report) != {"schema", "evidence", "observation", "inner_effect"}
            or report.get("schema") != _ATTEMPT_REPORT_SCHEMA
            or canonical_json(report).encode("ascii") != payload
        ):
            raise AriadneCampaignError(
                "controlled-repair Attempt report is noncanonical or malformed"
            )
        try:
            evidence_ref = ArtifactRef(**report["evidence"])
            observation_ref = ArtifactRef(**report["observation"])
            observation_payload = store.read_bytes(
                observation_ref, max_bytes=_MAX_ATTEMPT_REPORT_BYTES
            )
            observation = json.loads(observation_payload.decode("ascii"))
        except (
            UnicodeError,
            json.JSONDecodeError,
            SourceTreeStoreError,
            TypeError,
            ValueError,
        ) as exc:
            raise AriadneCampaignError(
                "controlled-repair Attempt observation is unavailable or invalid"
            ) from exc
        if (
            evidence_ref.sha256 != packet.digest
            or evidence_ref.locator != trial.evidence_packet_locator
            or packet.digest != trial.evidence_packet_sha256
            or len(packet.items) != 1
            or packet.items[0].output_sha256 != observation_ref.sha256
            or packet.items[0].evidence_locator != observation_ref.locator
        ):
            raise AriadneCampaignError(
                "controlled-repair Attempt report does not bind its EvidencePacket"
            )
        if (
            not isinstance(observation, dict)
            or canonical_json(observation).encode("ascii") != observation_payload
        ):
            raise AriadneCampaignError(
                "controlled-repair Attempt observation is noncanonical"
            )
        if observation.get("schema") == _EVALUATOR_ERROR_SCHEMA:
            if (
                set(observation)
                != {
                    "schema",
                    "campaign_id",
                    "attempt_id",
                    "variant_id",
                    "seed",
                    "candidate_tree_sha256",
                    "attempt_contract_sha256",
                    "evaluator_sha256",
                    "error_type",
                    "error",
                }
                or observation.get("campaign_id") != receipt.campaign_id
                or observation.get("attempt_id") != attempt.attempt_id
                or observation.get("variant_id") != trial.variant_id
                or observation.get("seed") != trial.seed
                or observation.get("candidate_tree_sha256")
                != trial.candidate_tree_sha256
                or observation.get("attempt_contract_sha256") != attempt.digest
                or observation.get("evaluator_sha256") != EVALUATOR_SHA256
                or not isinstance(observation.get("error_type"), str)
                or not observation.get("error_type")
                or not isinstance(observation.get("error"), str)
                or not observation.get("error")
                or packet.evaluation_status != "failed"
                or packet.items[0].verdict != "error"
            ):
                raise AriadneCampaignError(
                    "controlled-repair error observation is not bound to its trial"
                )
        elif observation.get("schema") in _EVALUATOR_OBSERVATION_SCHEMAS:
            output = observation.get("output")
            passed = observation.get("passed")
            interpreter = observation.get("interpreter")
            expected_keys = set(_EVALUATOR_OBSERVATION_KEYS)
            if observation.get("schema") == _EVALUATOR_OBSERVATION_SCHEMAS[-1]:
                expected_keys.add("interpreter")
                interpreter_bound = (
                    isinstance(interpreter, dict)
                    and set(interpreter) == _INTERPRETER_PROVENANCE_KEYS
                    and all(type(interpreter[key]) is str for key in interpreter)
                    and len(interpreter["binary_sha256"]) == 64
                )
            else:
                interpreter_bound = interpreter is None
            if (
                set(observation) != expected_keys
                or not interpreter_bound
                or observation.get("variant_id") != trial.variant_id
                or observation.get("seed") != trial.seed
                or observation.get("evaluator_sha256") != EVALUATOR_SHA256
                or observation.get("candidate_tree_sha256")
                != trial.candidate_tree_sha256
                or type(passed) is not bool
                or observation.get("returncode") != (0 if passed else 1)
                or not isinstance(output, str)
                or observation.get("output_sha256")
                != hashlib.sha256(output.encode("utf-8")).hexdigest()
                or packet.items[0].verdict != ("passed" if passed else "failed")
            ):
                raise AriadneCampaignError(
                    "controlled-repair evaluator observation is not bound to its trial"
                )
        else:
            raise AriadneCampaignError(
                "controlled-repair Attempt observation schema is not recognized"
            )
        binding = report.get("inner_effect")
        if not isinstance(binding, dict):
            raise AriadneCampaignError(
                "controlled-repair Attempt report lacks a typed inner effect binding"
            )
        _require_bound_inner_terminal(
            evidence_root, binding, attempt, loaded_receipt
        )


def _faulted_attempt_trial(
    *,
    store: SourceTreeStore,
    ledger: AttemptLedger,
    attempt_begin: Any,
    attempt: AttemptContract,
    attempt_ref: ArtifactRef,
    inner: Any,
    inner_execution: Any,
    inner_start: Any,
    candidate: StoredSourceTree,
    base: StoredSourceTree,
    campaign_id: str,
    source_revision: str,
    variant: str,
    role: str,
    seed: int,
    budget_sha256: str,
    started_at: str,
    usage: ResourceUsage,
    failure: BaseException,
    evidence_root: Path,
) -> tuple[CampaignTrialReceipt, str | None]:
    """Retain a post-capture failure as a faulted, candidate-bound Attempt."""

    error_type, error_message = _bounded_failure(failure)
    finished_at = _now()
    observation = {
        "schema": _EVALUATOR_ERROR_SCHEMA,
        "campaign_id": campaign_id,
        "attempt_id": attempt.attempt_id,
        "variant_id": variant,
        "seed": seed,
        "candidate_tree_sha256": candidate.ref.sha256,
        "attempt_contract_sha256": attempt.digest,
        "evaluator_sha256": EVALUATOR_SHA256,
        "error_type": error_type,
        "error": error_message,
    }
    observation_ref = store.put_bytes(canonical_json(observation).encode("ascii"))
    item_provenance = _prov(
        "ariadne.frozen-evaluator",
        source_revision,
        finished_at,
        observation_ref.sha256,
        trace=campaign_id,
    )
    item = EvidenceItem(
        evidence_id=f"evidence-{attempt.attempt_id}",
        evaluator="ariadne-frozen-evaluator",
        assurance="independent",
        verdict="error",
        output_sha256=observation_ref.sha256,
        evidence_locator=observation_ref.locator,
        collected_at=finished_at,
        provenance=item_provenance,
        details={
            "configured_budget_sha256": budget_sha256,
            "error_type": error_type,
            "phase": "post-candidate-capture",
        },
    )
    packet = EvidencePacket(
        packet_id=f"packet-{attempt.attempt_id}",
        mission_id=campaign_id,
        attempt_id=attempt.attempt_id,
        source_revision=source_revision,
        attempt_contract_sha256=attempt.digest,
        subject_sha256=candidate.ref.sha256,
        evaluation_status="failed",
        items=(item,),
        policy_decision_sha256=attempt.policy_decision_sha256,
        usage=usage,
        candidate_artifact_sha256=candidate.ref.sha256,
        candidate_artifact_locator=candidate.ref.locator,
        provenance=_prov(
            "ariadne.controlled-repair.error-evidence",
            source_revision,
            finished_at,
            attempt.digest,
            candidate.ref.sha256,
            attempt.policy_decision_sha256,
            observation_ref.sha256,
            trace=campaign_id,
        ),
    )
    packet_ref = store_contract(store, packet)
    binding = _inner_effect_binding(
        inner,
        inner_execution,
        attempt,
        expected_terminal_state="failed",
    )
    report_ref = _store_attempt_report(
        store,
        packet_ref=packet_ref,
        observation_ref=observation_ref,
        inner_effect=binding,
    )
    completion = ledger.complete(
        attempt_begin.start,
        receipt_id=f"terminal-{attempt.attempt_id}",
        outcome="faulted",
        report=report_ref,
        candidate_tree=candidate,
    )
    receipt_ref = store_contract(store, completion.receipt)
    terminal_error: str | None = None
    try:
        inner.authorization.finish_effect(
            inner_start.receipt,
            outcome="FAILED",
            output_digests=(receipt_ref.sha256,),
        )
        terminal_record = inner.retain_terminal_record(inner_execution)
        if terminal_record is None:
            raise AriadneCampaignError(
                "inner attempt effect terminal evidence was not retained"
            )
        _require_bound_inner_terminal(
            evidence_root, binding, attempt, completion.receipt
        )
    except BaseException as exc:
        terminal_type, terminal_message = _bounded_failure(exc)
        terminal_error = f"{terminal_type}: {terminal_message}"[:1000]
    blocker = f"{error_type}: {error_message}"[:1000]
    trial = CampaignTrialReceipt(
        campaign_id=campaign_id,
        seed=seed,
        replay_role="origin",
        stage="complete",
        status="error",
        base_source_tree_sha256=base.ref.sha256,
        base_source_tree_locator=base.ref.locator,
        mission_sha256=None,
        mission_locator=None,
        attempt_ids=(attempt.attempt_id,),
        attempt_contract_sha256s=(attempt.digest,),
        attempt_contract_locators=(attempt_ref.locator,),
        attempt_receipt_sha256s=(completion.receipt.digest,),
        attempt_receipt_locators=(receipt_ref.locator,),
        gate1_receipt_sha256=None,
        gate1_receipt_locator=None,
        candidate_tree_sha256=candidate.ref.sha256,
        candidate_tree_locator=candidate.ref.locator,
        candidate_source_bundle_sha256=None,
        candidate_snapshot_sha256=None,
        candidate_snapshot_locator=None,
        graph_delta_sha256=None,
        evidence_packet_sha256=packet.digest,
        evidence_packet_locator=packet_ref.locator,
        metrics={"exact_match": 0},
        usage=usage,
        negative_outcomes=("post-capture-error",),
        blockers=(blocker,),
        started_at=started_at,
        finished_at=finished_at,
        variant_id=variant,
        arm_role=role,
        configured_budget_sha256=budget_sha256,
        receipt_profile="controlled-repair-v1",
    )
    return trial, terminal_error


def _complete_failed_campaign_receipt(
    *,
    store: SourceTreeStore,
    ledger: AttemptLedger,
    campaign_begin: Any,
    contract: Any,
    contract_ref: ArtifactRef,
    spec: ExperimentSpec,
    spec_ref: ArtifactRef,
    granted: Any,
    execution: Any,
    trials: list[CampaignTrialReceipt],
    campaign_id: str,
    source_revision: str,
    operation_sha256: str,
    started_at: str,
    blocker: str,
    reproducibility_note: str,
    additional_negative_outcomes: tuple[str, ...] = (),
    base_binding_sha256: str | None = None,
) -> tuple[CampaignReceipt, ArtifactRef]:
    """Commit an addressable failed CampaignReceipt instead of STATE_FAILED."""

    outer_binding = _outer_effect_binding(
        granted,
        execution,
        campaign_id=campaign_id,
        source_revision=source_revision,
        operation_sha256=operation_sha256,
    )
    outer_binding_ref = store.put_bytes(canonical_json(outer_binding).encode("ascii"))
    finished_at = _now()
    receipt_inputs = {
        contract.digest,
        spec.digest,
        outer_binding_ref.sha256,
        *(() if base_binding_sha256 is None else (base_binding_sha256,)),
        *(
            digest
            for trial in trials
            for digest in (
                trial.base_source_tree_sha256,
                *trial.attempt_contract_sha256s,
                *trial.attempt_receipt_sha256s,
                trial.candidate_tree_sha256,
                trial.evidence_packet_sha256,
            )
            if digest is not None
        ),
    }
    negative_outcomes = {
        f"{trial.variant_id}:{outcome}"
        for trial in trials
        for outcome in trial.negative_outcomes
    }
    negative_outcomes.update(additional_negative_outcomes)
    receipt = CampaignReceipt(
        campaign_id=campaign_id,
        source_revision=source_revision,
        campaign_contract_sha256=contract.digest,
        campaign_contract_locator=contract_ref.locator,
        experiment_spec_sha256=spec.digest,
        experiment_spec_locator=spec_ref.locator,
        metric_names=("exact_match",),
        trials=tuple(trials),
        execution_order=tuple(trial.seed for trial in trials),
        outcome="failed",
        selected_seed=None,
        candidate_tree_sha256=None,
        candidate_tree_locator=None,
        nomination_receipt_sha256=None,
        nomination_receipt_locator=None,
        usage=ResourceUsage(
            input_tokens=sum(trial.usage.input_tokens for trial in trials),
            output_tokens=sum(trial.usage.output_tokens for trial in trials),
            cost_microusd=sum(trial.usage.cost_microusd for trial in trials),
            wall_time_ms=sum(trial.usage.wall_time_ms for trial in trials),
            est_input_tokens=sum(
                trial.usage.est_input_tokens for trial in trials
            ),
        ),
        overhead_usage=ResourceUsage(),
        negative_outcomes=tuple(sorted(negative_outcomes)),
        reproducibility_note=reproducibility_note,
        blockers=(blocker[:1000],),
        started_at=started_at,
        finished_at=finished_at,
        provenance=_prov(
            "ariadne.controlled-repair.receipt",
            source_revision,
            finished_at,
            *receipt_inputs,
            trace=campaign_id,
        ),
        selection_mode="best-passed-trial",
        selected_variant_id=None,
        budget_equality=None,
    )
    receipt_ref = complete_campaign(ledger.spine, store, campaign_begin, receipt)
    return receipt, receipt_ref


def _settle_committed_outer_effect(
    granted: Any,
    effect_start: Any,
    execution: Any,
    receipt_sha256: str,
) -> bool:
    """Reconcile a post-commit outer effect as COMPLETED, never FAILED.

    Campaign completion in the canonical spine is the scientific commit.  A
    transient terminal-ledger/evidence error after it cannot roll that fact
    back.  Retry the idempotent completion once, retain what can be retained,
    and report whether both terminal state and retained evidence are durable.
    """
    terminalized = False
    for _attempt in range(2):
        try:
            granted.authorization.finish_effect(
                effect_start.receipt,
                outcome="COMPLETED",
                output_digests=(receipt_sha256,),
            )
            terminalized = True
            break
        except BaseException:
            continue
    retained = False
    try:
        retained = granted.retain_terminal_record(execution) is not None
    except BaseException:
        pass
    return terminalized and retained


def _outer_effect_binding(
    granted: Any,
    execution: Any,
    *,
    campaign_id: str,
    source_revision: str,
    operation_sha256: str,
) -> dict[str, str]:
    subject_digest = granted.evidence_records.get("lease_subject")
    execution_digest = granted.evidence_records.get(
        f"lease_execution:{execution.execution_id}"
    )
    digests = {
        "operation_sha256": operation_sha256,
        "lease_sha256": granted.lease.digest,
        "lease_subject_record_sha256": subject_digest,
        "lease_execution_record_sha256": execution_digest,
    }
    if any(
        not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None
        for value in digests.values()
    ):
        raise AriadneCampaignError(
            "outer campaign effect evidence was not retained before commit"
        )
    try:
        require_retained_effect_lease_start_records(
            granted.evidence_root,
            subject_record_sha256=subject_digest,
            execution_record_sha256=execution_digest,
            entrypoint_id=ENTRYPOINT_ID,
            source_revision=source_revision,
            attempt_id=f"{campaign_id}-campaign",
            operation_sha256=operation_sha256,
            expected_lease_sha256=granted.lease.digest,
            expected_execution_id=execution.execution_id,
            expected_execution_request_sha256=execution.digest,
        )
    except (EffectLeaseError, OSError, TypeError, ValueError) as exc:
        raise AriadneCampaignError(
            "outer campaign effect evidence is unavailable or invalid before commit"
        ) from exc
    return {
        "schema": _OUTER_EFFECT_BINDING_SCHEMA,
        "campaign_id": campaign_id,
        "source_revision": source_revision,
        "attempt_id": f"{campaign_id}-campaign",
        "entrypoint_id": ENTRYPOINT_ID,
        **digests,
        "execution_id": execution.execution_id,
        "execution_request_sha256": execution.digest,
        "expected_terminal_state": "completed",
    }


def _require_campaign_outer_effect_terminal(
    store: SourceTreeStore,
    evidence_root: Path,
    receipt: CampaignReceipt,
    *,
    operation_sha256: str,
) -> None:
    """Keep post-commit outer-effect debt visible on every campaign replay."""

    inputs = tuple(receipt.provenance.input_digests)
    if len(inputs) > _MAX_RECEIPT_PROVENANCE_INPUTS:
        raise AriadneCampaignError(
            "campaign outer effect needs reconciliation: provenance input bound exceeded"
        )
    matches: list[dict[str, Any]] = []
    for digest in inputs:
        try:
            payload = store.read_bytes(
                ArtifactRef.from_sha256(digest),
                max_bytes=_MAX_OUTER_EFFECT_BINDING_BYTES,
            )
            value = json.loads(payload.decode("ascii"))
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            SourceTreeStoreError,
            TypeError,
            ValueError,
        ):
            continue
        if (
            isinstance(value, dict)
            and value.get("schema") == _OUTER_EFFECT_BINDING_SCHEMA
        ):
            if canonical_json(value).encode("ascii") != payload:
                raise AriadneCampaignError(
                    "campaign outer effect needs reconciliation: binding is noncanonical"
                )
            matches.append(value)
    if len(matches) != 1:
        raise AriadneCampaignError(
            "campaign outer effect needs reconciliation: binding is missing or ambiguous"
        )
    binding = matches[0]
    expected_keys = {
        "schema",
        "campaign_id",
        "source_revision",
        "attempt_id",
        "entrypoint_id",
        "operation_sha256",
        "lease_sha256",
        "lease_subject_record_sha256",
        "lease_execution_record_sha256",
        "execution_id",
        "execution_request_sha256",
        "expected_terminal_state",
    }
    if (
        set(binding) != expected_keys
        or binding.get("campaign_id") != receipt.campaign_id
        or binding.get("source_revision") != receipt.source_revision
        or binding.get("attempt_id") != f"{receipt.campaign_id}-campaign"
        or binding.get("entrypoint_id") != ENTRYPOINT_ID
        or binding.get("operation_sha256") != operation_sha256
        or binding.get("expected_terminal_state") != "completed"
    ):
        raise AriadneCampaignError(
            "campaign outer effect needs reconciliation: binding is invalid"
        )
    try:
        terminal = require_retained_effect_lease_terminal_record(
            evidence_root,
            subject_record_sha256=str(binding["lease_subject_record_sha256"]),
            execution_record_sha256=str(binding["lease_execution_record_sha256"]),
            entrypoint_id=ENTRYPOINT_ID,
            source_revision=receipt.source_revision,
            attempt_id=f"{receipt.campaign_id}-campaign",
            operation_sha256=operation_sha256,
            expected_lease_sha256=str(binding["lease_sha256"]),
            expected_execution_id=str(binding["execution_id"]),
            expected_execution_request_sha256=str(
                binding["execution_request_sha256"]
            ),
            expected_terminal_state="completed",
            expected_output_digests=(receipt.digest,),
        )
        if (
            terminal.get("lease_sha256") != binding["lease_sha256"]
            or terminal.get("execution_id") != binding["execution_id"]
            or terminal.get("execution_request_sha256")
            != binding["execution_request_sha256"]
        ):
            raise AriadneCampaignError(
                "campaign outer effect needs reconciliation: binding is invalid"
            )
    except (EffectLeaseError, OSError, TypeError, ValueError) as exc:
        raise AriadneCampaignError(
            f"campaign outer effect needs reconciliation: {exc}"
        ) from exc


def run_campaign(
    *,
    repo_root: str | os.PathLike[str],
    source_revision: str,
    campaign_id: str,
    target_path: str,
    before: str,
    after: str,
    timeout_s: int = 30,
) -> dict[str, Any]:
    """Run baseline, negative control, and repair once under equal budgets."""
    campaign_id = _campaign_id(campaign_id)
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, int) or timeout_s <= 0:
        raise AriadneCampaignError("timeout_s must be a positive integer")
    before, before_bytes = _repair_fragment(
        before, label="before", allow_empty=False
    )
    after, after_bytes = _repair_fragment(
        after, label="after", allow_empty=True
    )
    if before == after:
        raise AriadneCampaignError("repair must replace before with a different value")
    root = Path(repo_root).resolve(strict=True)
    if len(source_revision) != 40 or any(c not in "0123456789abcdef" for c in source_revision):
        raise AriadneCampaignError("source_revision must be the exact lowercase 40-hex Git HEAD")
    # HEAD is observed BEFORE and AFTER the target read (G1-ARIADNE-05): a
    # commit or checkout between the two would bind bytes of revision X to a
    # receipt labelled Y, and nothing else here would notice.
    _admit_target_path(target_path)  # pure refusals first: no repository observed yet
    head_receipt = _verify_head(root, source_revision)
    relative, target_snapshot = _safe_target(root, target_path)
    if _verify_head(root, source_revision).to_dict() != head_receipt.to_dict():
        raise AriadneConflictError(
            "source_revision conflict: repository HEAD changed while the target was read"
        )
    head_receipt_sha = canonical_sha(head_receipt.to_dict())
    try:
        original = target_snapshot.source.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise AriadneCampaignError("target must be strict UTF-8") from exc
    if original.count(before) != 1:
        raise AriadneCampaignError("before text must occur exactly once in the frozen target")
    original_bytes = target_snapshot.source
    expected = original.replace(before, after, 1).encode("utf-8", errors="strict")
    negative_replacement = before + _NEGATIVE_CONTROL_SUFFIX
    if negative_replacement == after:
        # Keep the control deterministically distinct even when the requested
        # repair happens to equal the standard mutant.  One extra suffix is
        # sufficient because one string cannot equal both lengths.
        negative_replacement += _NEGATIVE_CONTROL_SUFFIX
    negative_control = original.replace(
        before, negative_replacement, 1
    ).encode("utf-8", errors="strict")
    if negative_control == expected:
        raise AriadneCampaignError("negative control must differ from the requested repair")
    if len(expected) > MAX_CAMPAIGN_FILE_BYTES:
        raise AriadneCampaignError(
            f"repair output exceeds the {MAX_CAMPAIGN_FILE_BYTES}-byte campaign file ceiling"
        )
    if len(negative_control) > MAX_CAMPAIGN_FILE_BYTES:
        raise AriadneCampaignError(
            "negative-control output exceeds the "
            f"{MAX_CAMPAIGN_FILE_BYTES}-byte campaign file ceiling"
        )
    expected_sha = hashlib.sha256(expected).hexdigest()
    operation_sha = canonical_sha({
        "schema": "daedalus-ariadne-controlled-repair/2",
        "campaign_id": campaign_id,
        "source_revision": source_revision,
        "target_path": relative,
        "base_file_sha256": target_snapshot.source_sha256,
        "before_sha256": hashlib.sha256(before_bytes).hexdigest(),
        "after_sha256": hashlib.sha256(after_bytes).hexdigest(),
        "expected_sha256": expected_sha,
        "negative_control_sha256": hashlib.sha256(negative_control).hexdigest(),
        "evaluator_sha256": EVALUATOR_SHA256,
        "timeout_s": timeout_s,
        "repair_fragment_max_bytes": MAX_REPAIR_FRAGMENT_BYTES,
        "campaign_file_max_bytes": MAX_CAMPAIGN_FILE_BYTES,
        "negative_control_suffix_sha256": hashlib.sha256(
            _NEGATIVE_CONTROL_SUFFIX.encode("ascii")
        ).hexdigest(),
    })
    state = control_root(root) / "ariadne"
    effect_evidence_root = state / "effect-evidence" / campaign_id
    workspace_parent = state / "workspaces"
    switch = KillSwitch(repo_root=root)
    spine_path, error = resolve_spine_db_path(root)
    if error or spine_path is None:
        raise AriadneCampaignError(f"canonical spine unavailable: {error}")
    granted = acquire_effect_lease(
        root,
        entrypoint_id=ENTRYPOINT_ID,
        source_revision=source_revision,
        mission_id=campaign_id,
        attempt_id=f"{campaign_id}-campaign",
        positions=1,
        writable_paths=(relative,),
        tools=("python",),
        max_spend_usd=None,
        timeout_s=timeout_s * 3,
        contained=True,
        containment_evidence="each arm is materialized from exact CAS below a checkout-external Attempt workspace",
        write_policy=Policy(write_allow=(relative,)),
        switch=switch,
        trace_id=campaign_id,
        evidence_root=effect_evidence_root,
        subject_root=root,
        worktree_root=workspace_parent,
        operation_sha256=operation_sha,
    )
    if isinstance(granted, WaveLeaseDenied):
        raise AriadneCampaignError("effect lease denied: " + "; ".join(granted.reasons))
    execution = granted.execution_for(
        0, writable_paths=(relative,), tools=("python",), operation_sha256=operation_sha
    )
    # Retention is part of this product boundary, not best-effort telemetry.
    # Refuse before begin_effect, the serial lock, CAS, SQLite, or workspaces
    # can mutate when the exact outer subject/execution chain is unavailable.
    _outer_effect_binding(
        granted,
        execution,
        campaign_id=campaign_id,
        source_revision=source_revision,
        operation_sha256=operation_sha,
    )
    effect_start = granted.authorization.begin_effect(execution)

    lock = ExclusiveFileLock(
        control_root(root) / "candidate-execution.lock", timeout_s=2.0,
        label="shared Genesis/Ariadne candidate execution lock",
    )
    lock_acquired = False
    store: SourceTreeStore | None = None
    ledger: AttemptLedger | None = None
    campaign_begin = None
    campaign_committed = False
    active_attempt_begin = None
    active_inner = None
    active_inner_execution = None
    active_inner_start = None
    try:
        try:
            lock.__enter__()
            lock_acquired = True
        except FileLockUnavailable as exc:
            raise AriadneCampaignError(
                "another Genesis/Ariadne candidate execution is active; retry"
            ) from exc
        # A mode=ro SpineLedger may create SQLite WAL/SHM companions. Replay
        # therefore comes only after the canonical lease/begin boundary and
        # while holding the shared serial slot. A caller that waited for an
        # identical campaign now sees its terminal WAL before creating CAS or
        # Attempt state. The Campaign spine, not an outer lease ID, owns replay.
        try:
            replay = lookup_campaign_read_only(
                str(spine_path), str(state / "source-cas"), campaign_id,
                expected_operation_sha256=operation_sha,
            )
        except CampaignIdentityConflict as exc:
            # Same id, changed frozen material: a conflict with a durable
            # campaign, the same class as a stale HEAD (HTTP 409). Corrupt or
            # malformed retained state below stays a campaign error (400).
            raise AriadneConflictError(str(exc)) from exc
        except CampaignLifecycleError as exc:
            raise AriadneCampaignError(str(exc)) from exc
        if replay is not None:
            replay_store = SourceTreeStore.open_existing(state / "source-cas")
            _require_campaign_inner_effect_terminals(
                replay_store,
                effect_evidence_root,
                replay.receipt,
            )
            _require_campaign_outer_effect_terminal(
                replay_store,
                effect_evidence_root,
                replay.receipt,
                operation_sha256=operation_sha,
            )
            if effect_start.execute:
                settled = _settle_committed_outer_effect(
                    granted, effect_start, execution, replay.receipt.digest
                )
                if not settled:
                    raise AriadneCampaignError(
                        "campaign replay is canonical but its invocation effect needs "
                        "ledger/evidence reconciliation"
                    )
            return replay.receipt.to_dict()
        if not effect_start.execute:
            raise AriadneCampaignError(
                "effect execution is already terminal or pending; inspect "
                "retained campaign state"
            )
        store = SourceTreeStore(state / "source-cas")
        workspace_parent.mkdir(parents=True, exist_ok=True)
        ledger = AttemptLedger(spine_path, store)
        evaluator_ref = store.put_bytes(EVALUATOR_SOURCE.encode("utf-8"))
        if evaluator_ref.sha256 != EVALUATOR_SHA256:
            raise AriadneCampaignError("frozen evaluator CAS identity changed")
        head_ref = store.put_bytes(canonical_json(head_receipt.to_dict()).encode("ascii"))
        if head_ref.sha256 != head_receipt_sha:
            raise AriadneCampaignError("verified HEAD receipt CAS identity changed")
        created = _now()
        base = _store_scoped_tree(
            store, payload=original_bytes, relative=relative,
            tree_id=f"{campaign_id}-base", source_revision=source_revision,
            origin="ariadne.controlled-repair.working-tree-base", created_at=created,
            trace_id=campaign_id,
        )
        base_binding_ref = store.put_bytes(canonical_json(_base_tree_binding(
            campaign_id=campaign_id, source_revision=source_revision,
            relative=relative, base_file_sha256=target_snapshot.source_sha256,
        )).encode("ascii"))
        budget = ResourceBudget(max_wall_time_s=timeout_s, max_attempts=1)
        budget_sha = canonical_sha(asdict(budget))
        task_sha = operation_sha
        frozen = {
            "compiler": canonical_sha({"kind": "exact-text-replace-v1"}),
            "evaluator": EVALUATOR_SHA256,
            "fixture": expected_sha,
            "generator": canonical_sha({"arms": ["no-change", "negative-control", "repair"]}),
            "model": canonical_sha({"kind": "none-deterministic"}),
            "operator": canonical_sha({"kind": "bounded-text-replace-v1"}),
            "head_revision": head_receipt_sha,
        }
        expires = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(timespec="microseconds")
        spec_inputs = (task_sha, base.ref.sha256, head_receipt_sha, *frozen.values())
        spec = ExperimentSpec(
            campaign_id=campaign_id, source_revision=source_revision,
            objective=f"Replace one exact occurrence in {relative}",
            task_sha256s=(task_sha,), baseline_sha256s=(base.ref.sha256,),
            base_source_tree_sha256=base.ref.sha256, base_source_tree_locator=base.ref.locator,
            seeds=(0, 1, 2), metrics=("exact_match",), operator_axis="repair_variant",
            seed_derivation="fixed ordered arms: 0 baseline, 1 negative control, 2 repair",
            selection_policy="best_passed_trial", attempts_per_seed=1,
            metric_acceptance={"exact_match": 1}, gate_timeout_s=timeout_s,
            frozen_components=frozen, writable_paths=(relative,), budget=budget,
            created_at=created, expires_at=expires,
            provenance=_prov("ariadne.controlled-repair.spec", source_revision, created, *spec_inputs, trace=campaign_id),
        )
        spec_ref = store_contract(store, spec)
        contract_at = _now()
        contract_inputs = (spec.digest, task_sha, base.ref.sha256, EVALUATOR_SHA256, *frozen.values())
        contract = campaign_contract_for_spec(
            spec,
            provenance=_prov("ariadne.controlled-repair.contract", source_revision, contract_at, *contract_inputs, trace=campaign_id),
        )
        contract_ref = store_contract(store, contract)
        campaign_begin = begin_campaign(ledger.spine, store, contract, contract_ref, spec_ref)
        if not campaign_begin.execute:
            assert campaign_begin.receipt is not None
            _require_campaign_inner_effect_terminals(
                store,
                effect_evidence_root,
                campaign_begin.receipt,
            )
            _require_campaign_outer_effect_terminal(
                store,
                effect_evidence_root,
                campaign_begin.receipt,
                operation_sha256=operation_sha,
            )
            settled = _settle_committed_outer_effect(
                granted,
                effect_start,
                execution,
                campaign_begin.receipt.digest,
            )
            if not settled:
                raise AriadneCampaignError(
                    "campaign replay is canonical but its invocation effect needs "
                    "ledger/evidence reconciliation"
                )
            return campaign_begin.receipt.to_dict()
        coordinator = IsolatedAttemptCoordinator(
            primary_checkout=root, workspace_parent=workspace_parent,
            source_store=store, ledger=ledger,
        )
        trials: list[CampaignTrialReceipt] = []
        evidence_by_key: dict[tuple[str, int], EvidencePacket] = {}
        arms = (("baseline", "baseline", 0), ("negative-control", "candidate", 1), ("repair", "candidate", 2))
        # Resolved once per campaign so every arm runs under the same
        # interpreter; the observation records its identity, never its path.
        evaluator_interpreter = _evaluator_interpreter()
        interpreter_provenance = _interpreter_provenance(evaluator_interpreter)
        for variant, role, seed in arms:
            switch.checkpoint()
            started = _now()
            attempt_id = f"{campaign_id}-{variant}"
            task = TaskSpec(
                task_id=attempt_id,
                instruction=f"Ariadne controlled repair arm {variant}",
                base_revision=source_revision,
                target_paths=(relative,),
                gate_argv=("python", "-I", "-c", EVALUATOR_SOURCE, relative, expected_sha),
                gate_timeout_s=timeout_s,
            )
            attempt_inputs = (task.digest, operation_sha, granted.policy_decision.digest)
            attempt = AttemptContract.from_task_spec(
                task, attempt_id=attempt_id, mission_id=campaign_id,
                runtime_manifest_sha256=operation_sha,
                policy_decision_sha256=granted.policy_decision.digest,
                budget=budget, campaign_id=campaign_id, base_revision=source_revision,
                provenance=_prov("ariadne.controlled-repair.attempt", source_revision, started, *attempt_inputs, trace=campaign_id),
            )
            attempt_ref = store_contract(store, attempt)
            relative_workspace = f"attempts/{attempt.attempt_id}-{attempt.digest[:16]}"
            attempt_begin = ledger.begin(
                attempt, base, start_id=f"start-{attempt_id}",
                workspace_parent_sha256=coordinator.workspace_parent_sha256,
                workspace_relative_path=relative_workspace,
            )
            if not attempt_begin.execute:
                raise AriadneCampaignError(f"attempt {attempt_id} is pending or already terminal")
            active_attempt_begin = attempt_begin
            inner = acquire_attempt_lease(
                root, source_revision=source_revision, mission_id=campaign_id,
                attempt_id=attempt_id, effect_key=f"attempt-lifecycle:{attempt_id}",
                writable_paths=(relative,), write_policy=Policy(write_allow=(relative,)),
                contained=True,
                containment_evidence=(
                    "exact base CAS materialized below the external campaign "
                    "workspace while the shared Genesis/Ariadne slot is held"
                ),
                subject_root=root, worktree_root=workspace_parent,
                intent_ledger_path_resolver=resolve_spine_db_path,
                trace_id=campaign_id, switch=switch,
                evidence_root=effect_evidence_root,
                operation_sha256=attempt.digest,
            )
            if isinstance(inner, WaveLeaseDenied):
                raise AriadneCampaignError("per-attempt lease denied: " + "; ".join(inner.reasons))
            inner_execution = inner.execution_for(
                0,
                writable_paths=(relative,),
                tools=("python",),
                operation_sha256=attempt.digest,
            )
            # As with the outer Campaign lease, missing retained start evidence
            # is a pre-effect refusal. The terminal-state value is immaterial
            # to this start-only validation and is re-bound after evaluation.
            _inner_effect_binding(
                inner,
                inner_execution,
                attempt,
                expected_terminal_state="failed",
            )
            inner_start = inner.authorization.begin_effect(inner_execution)
            if not inner_start.execute:
                raise AriadneCampaignError(f"attempt {attempt_id} effect is pending or terminal")
            active_inner = inner
            active_inner_execution = inner_execution
            active_inner_start = inner_start
            workspace = workspace_parent.joinpath(*relative_workspace.split("/"))
            store.materialize_tree(base.ref, workspace)
            candidate_file = workspace / relative
            if variant == "negative-control":
                candidate_file.write_bytes(negative_control)
            elif variant == "repair":
                candidate_file.write_bytes(expected)
            candidate_at = _now()
            candidate = store.capture_tree(
                workspace, tree_id=f"{attempt_id}-candidate",
                source_revision=source_revision,
                origin="ariadne.controlled-repair.candidate",
                created_at=candidate_at, trace_id=campaign_id,
                max_file_bytes=MAX_CAMPAIGN_FILE_BYTES,
                max_total_bytes=MAX_CAMPAIGN_FILE_BYTES,
            )
            usage = ResourceUsage()
            try:
                evaluation_workspace = (
                    workspace_parent
                    / "evaluations"
                    / f"{attempt.attempt_id}-{candidate.ref.sha256[:16]}"
                )
                materialized_candidate = store.materialize_tree(
                    candidate.ref,
                    evaluation_workspace,
                    max_file_bytes=MAX_CAMPAIGN_FILE_BYTES,
                    max_total_bytes=MAX_CAMPAIGN_FILE_BYTES,
                )
                if materialized_candidate != candidate.manifest:
                    raise AriadneCampaignError(
                        "fresh evaluator materialization differs from candidate CAS"
                    )
                result = command_gate(
                    (
                        evaluator_interpreter,
                        "-I",
                        "-S",
                        "-c",
                        EVALUATOR_SOURCE,
                        relative,
                        expected_sha,
                    ),
                    timeout_s=timeout_s,
                    poll_s=0.05,
                    name="ariadne-frozen-evaluator",
                    executes_candidate=True,
                )(
                    RunnerContext(
                        worktree=evaluation_workspace,
                        branch=f"ariadne/{attempt_id}",
                        base_revision=source_revision,
                        task=task,
                        is_cancelled=switch.should_stop,
                    )
                )
                finished = _now()
                usage = ResourceUsage(
                    wall_time_ms=max(0, int(round(result.duration_s * 1000)))
                )
                budget_violations = budget.violations(usage)
                trial_passed = bool(result.passed) and not budget_violations
                evaluator_value = _verify_frozen_evaluator_output(
                    result,
                    candidate,
                    relative=relative,
                    expected_sha256=expected_sha,
                )
                observation = {
                    "schema": "daedalus-ariadne-evaluator-observation/2",
                    "variant_id": variant,
                    "seed": seed,
                    "evaluator_sha256": EVALUATOR_SHA256,
                    "passed": result.passed,
                    "returncode": result.returncode,
                    "output": result.output,
                    "output_sha256": result.output_sha256,
                    "candidate_tree_sha256": candidate.ref.sha256,
                    "expected_sha256": evaluator_value["expected_sha256"],
                    "observed_sha256": evaluator_value["observed_sha256"],
                    "containment": (
                        result.containment.summary() if result.containment else None
                    ),
                    "interpreter": interpreter_provenance,
                }
                observation_ref = store.put_bytes(
                    canonical_json(observation).encode("ascii")
                )
                item_prov = _prov(
                    "ariadne.frozen-evaluator",
                    source_revision,
                    finished,
                    observation_ref.sha256,
                    trace=campaign_id,
                )
                item = EvidenceItem(
                    evidence_id=f"evidence-{attempt_id}",
                    evaluator="ariadne-frozen-evaluator",
                    assurance="independent",
                    verdict="passed" if result.passed else "failed",
                    output_sha256=observation_ref.sha256,
                    evidence_locator=observation_ref.locator,
                    collected_at=finished,
                    provenance=item_prov,
                    details={
                        "evaluator_sha256": EVALUATOR_SHA256,
                        "configured_budget_sha256": budget_sha,
                    },
                )
                packet_inputs = (
                    attempt.digest,
                    candidate.ref.sha256,
                    granted.policy_decision.digest,
                    observation_ref.sha256,
                )
                packet = EvidencePacket(
                    packet_id=f"packet-{attempt_id}",
                    mission_id=campaign_id,
                    attempt_id=attempt_id,
                    source_revision=source_revision,
                    attempt_contract_sha256=attempt.digest,
                    subject_sha256=candidate.ref.sha256,
                    evaluation_status="passed" if result.passed else "failed",
                    items=(item,),
                    policy_decision_sha256=granted.policy_decision.digest,
                    usage=usage,
                    candidate_artifact_sha256=candidate.ref.sha256,
                    candidate_artifact_locator=candidate.ref.locator,
                    provenance=_prov(
                        "ariadne.controlled-repair.evidence",
                        source_revision,
                        finished,
                        *packet_inputs,
                        trace=campaign_id,
                    ),
                )
                packet_ref = store_contract(store, packet)
                inner_binding = _inner_effect_binding(
                    inner,
                    inner_execution,
                    attempt,
                    expected_terminal_state=(
                        "completed" if trial_passed else "failed"
                    ),
                )
                report_ref = _store_attempt_report(
                    store,
                    packet_ref=packet_ref,
                    observation_ref=observation_ref,
                    inner_effect=inner_binding,
                )
                completion = ledger.complete(
                    attempt_begin.start,
                    receipt_id=f"terminal-{attempt_id}",
                    outcome="succeeded" if trial_passed else "failed",
                    report=report_ref,
                    candidate_tree=candidate,
                )
            except BaseException as arm_failure:
                faulted_trial, terminal_error = _faulted_attempt_trial(
                    store=store,
                    ledger=ledger,
                    attempt_begin=attempt_begin,
                    attempt=attempt,
                    attempt_ref=attempt_ref,
                    inner=inner,
                    inner_execution=inner_execution,
                    inner_start=inner_start,
                    candidate=candidate,
                    base=base,
                    campaign_id=campaign_id,
                    source_revision=source_revision,
                    variant=variant,
                    role=role,
                    seed=seed,
                    budget_sha256=budget_sha,
                    started_at=started,
                    usage=usage,
                    failure=arm_failure,
                    evidence_root=effect_evidence_root,
                )
                trials.append(faulted_trial)
                failure_type, failure_message = _bounded_failure(arm_failure)
                blocker = f"{variant}:{failure_type}: {failure_message}"
                if terminal_error is not None:
                    blocker = f"{blocker}; inner-terminal: {terminal_error}"
                failed_receipt, failed_receipt_ref = _complete_failed_campaign_receipt(
                    store=store,
                    ledger=ledger,
                    campaign_begin=campaign_begin,
                    contract=contract,
                    contract_ref=contract_ref,
                    spec=spec,
                    spec_ref=spec_ref,
                    granted=granted,
                    execution=execution,
                    trials=trials,
                    campaign_id=campaign_id,
                    source_revision=source_revision,
                    operation_sha256=operation_sha,
                    started_at=created,
                    base_binding_sha256=base_binding_ref.sha256,
                    blocker=blocker,
                    reproducibility_note=(
                        "The campaign stopped at the first post-capture error; "
                        "the exact candidate, error observation, EvidencePacket, "
                        "faulted Attempt, and frozen trial prefix are retained."
                    ),
                    additional_negative_outcomes=(
                        (f"{variant}:inner-terminal-evidence-unavailable",)
                        if terminal_error is not None
                        else ()
                    ),
                )
                campaign_committed = True
                if terminal_error is None:
                    _require_campaign_inner_effect_terminals(
                        store,
                        effect_evidence_root,
                        failed_receipt,
                    )
                settled = _settle_committed_outer_effect(
                    granted,
                    effect_start,
                    execution,
                    failed_receipt_ref.sha256,
                )
                if not settled:
                    raise AriadneCampaignError(
                        "Campaign failure receipt is canonical but its outer effect "
                        "needs ledger/evidence reconciliation"
                    ) from arm_failure
                if terminal_error is not None:
                    raise AriadneCampaignError(
                        "Campaign failure receipt is canonical but its inner Attempt "
                        f"effect needs reconciliation: {terminal_error}"
                    ) from arm_failure
                if _is_domain_failure(arm_failure):
                    # G1-ARIADNE-04: an evaluator-contract violation is a retained
                    # negative outcome. The failed receipt is canonical, settled and
                    # replayable, so it IS the result of this call, not an error a
                    # caller has to replay for. Foreign crashes and cancellations
                    # still raise: those are faults the operator must see as such.
                    return failed_receipt.to_dict()
                raise
            receipt_ref = store_contract(store, completion.receipt)
            negative_outcomes = []
            blockers = []
            if not result.passed:
                negative_outcomes.append("frozen-evaluator-rejected")
                blockers.append("exact-match-failed")
            if budget_violations:
                negative_outcomes.append("budget-exhausted")
                blockers.extend(f"budget: {item}" for item in budget_violations)
            trial = CampaignTrialReceipt(
                campaign_id=campaign_id, seed=seed, replay_role="origin", stage="complete",
                status="passed" if trial_passed else "failed",
                base_source_tree_sha256=base.ref.sha256, base_source_tree_locator=base.ref.locator,
                mission_sha256=None, mission_locator=None, attempt_ids=(attempt_id,),
                attempt_contract_sha256s=(attempt.digest,), attempt_contract_locators=(attempt_ref.locator,),
                attempt_receipt_sha256s=(completion.receipt.digest,), attempt_receipt_locators=(receipt_ref.locator,),
                gate1_receipt_sha256=None, gate1_receipt_locator=None,
                candidate_tree_sha256=candidate.ref.sha256, candidate_tree_locator=candidate.ref.locator,
                candidate_source_bundle_sha256=None, candidate_snapshot_sha256=None,
                candidate_snapshot_locator=None, graph_delta_sha256=None,
                evidence_packet_sha256=packet.digest, evidence_packet_locator=packet_ref.locator,
                metrics={"exact_match": 1 if result.passed else 0}, usage=usage,
                negative_outcomes=tuple(negative_outcomes),
                blockers=tuple(blockers),
                started_at=started, finished_at=finished, variant_id=variant, arm_role=role,
                configured_budget_sha256=budget_sha, receipt_profile="controlled-repair-v1",
            )
            try:
                inner.authorization.finish_effect(
                    inner_start.receipt,
                    outcome="COMPLETED" if trial_passed else "FAILED",
                    output_digests=(receipt_ref.sha256,),
                )
                terminal_record = inner.retain_terminal_record(inner_execution)
                if terminal_record is None:
                    raise AriadneCampaignError(
                        "inner attempt effect terminal evidence was not retained"
                    )
                _require_bound_inner_terminal(
                    effect_evidence_root,
                    inner_binding,
                    attempt,
                    completion.receipt,
                )
            except BaseException as terminal_failure:
                trials.append(trial)
                terminal_type, terminal_message = _bounded_failure(terminal_failure)
                _failed_receipt, failed_receipt_ref = _complete_failed_campaign_receipt(
                    store=store,
                    ledger=ledger,
                    campaign_begin=campaign_begin,
                    contract=contract,
                    contract_ref=contract_ref,
                    spec=spec,
                    spec_ref=spec_ref,
                    granted=granted,
                    execution=execution,
                    trials=trials,
                    campaign_id=campaign_id,
                    source_revision=source_revision,
                    operation_sha256=operation_sha,
                    started_at=created,
                    base_binding_sha256=base_binding_ref.sha256,
                    blocker=(
                        f"{variant}:inner-terminal-evidence:{terminal_type}:"
                        f" {terminal_message}"
                    ),
                    reproducibility_note=(
                        "The retained trial and Attempt are canonical, but the "
                        "inner attempt-effect terminal evidence did not verify; "
                        "the campaign stopped before the next frozen arm."
                    ),
                    additional_negative_outcomes=(
                        f"{variant}:inner-terminal-evidence-unavailable",
                    ),
                )
                campaign_committed = True
                settled = _settle_committed_outer_effect(
                    granted,
                    effect_start,
                    execution,
                    failed_receipt_ref.sha256,
                )
                if not settled:
                    raise AriadneCampaignError(
                        "Campaign failure receipt is canonical but its outer effect "
                        "needs ledger/evidence reconciliation"
                    ) from terminal_failure
                raise AriadneCampaignError(
                    "Campaign failure receipt is canonical but its inner Attempt "
                    "effect needs reconciliation"
                ) from terminal_failure
            active_attempt_begin = None
            active_inner = None
            active_inner_execution = None
            active_inner_start = None
            trials.append(trial)
            evidence_by_key[(variant, seed)] = packet
            if budget_violations:
                receipt, receipt_ref = _complete_failed_campaign_receipt(
                    store=store,
                    ledger=ledger,
                    campaign_begin=campaign_begin,
                    contract=contract,
                    contract_ref=contract_ref,
                    spec=spec,
                    spec_ref=spec_ref,
                    granted=granted,
                    execution=execution,
                    trials=trials,
                    campaign_id=campaign_id,
                    source_revision=source_revision,
                    operation_sha256=operation_sha,
                    started_at=created,
                    base_binding_sha256=base_binding_ref.sha256,
                    blocker="; ".join(
                        f"{variant}:{violation}" for violation in budget_violations
                    ),
                    reproducibility_note=(
                        "The frozen campaign stopped before its next seed when "
                        "the retained trial exceeded its equal budget ceiling."
                    ),
                )
                campaign_committed = True
                _require_campaign_inner_effect_terminals(
                    store,
                    effect_evidence_root,
                    receipt,
                )
                settled = _settle_committed_outer_effect(
                    granted, effect_start, execution, receipt_ref.sha256
                )
                if not settled:
                    raise AriadneCampaignError(
                        "Campaign receipt is canonical but its outer effect needs "
                        "ledger/evidence reconciliation"
                    )
                return receipt.to_dict()
        trial_by_variant = {trial.variant_id: trial for trial in trials}
        baseline_trial = trial_by_variant["baseline"]
        negative_trial = trial_by_variant["negative-control"]
        repair_trial = trial_by_variant["repair"]
        if (
            baseline_trial.status != "failed"
            or negative_trial.status != "failed"
            or repair_trial.status != "passed"
        ):
            raise AriadneCampaignError(
                "controlled repair requires failed baseline and negative control "
                "plus a passed repair"
            )
        selected = repair_trial
        selected_packet = evidence_by_key[(selected.variant_id, selected.seed)]
        nomination_at = _now()
        nomination_inputs = (selected.candidate_tree_sha256, selected_packet.digest, granted.policy_decision.digest)
        nomination = NominationReceipt(
            nomination_id=f"nomination-{campaign_id}", mission_id=campaign_id,
            attempt_id=selected.attempt_ids[0], source_revision=source_revision,
            candidate_artifact_sha256=selected.candidate_tree_sha256,
            candidate_artifact_locator=selected.candidate_tree_locator,
            evidence_packet_sha256=selected_packet.digest,
            evidence_locator=selected.evidence_packet_locator,
            policy_decision_sha256=granted.policy_decision.digest,
            nomination_status="nominated", reasons=("passed frozen exact-match evaluator under equal configured budget",),
            provenance=_prov("ariadne.controlled-repair.nomination", source_revision, nomination_at, *nomination_inputs, trace=campaign_id),
        )
        nomination_ref = store_contract(store, nomination)
        usage = ResourceUsage(wall_time_ms=sum(t.usage.wall_time_ms for t in trials))
        budget_equality = CampaignBudgetEqualityEvidence(
            configured_budget_sha256=budget_sha,
            trial_keys=tuple(f"{t.variant_id}:{t.seed}" for t in trials),
            trial_budget_sha256s=tuple(t.configured_budget_sha256 for t in trials),
            realized_usage_sha256s=tuple(canonical_sha(asdict(t.usage)) for t in trials),
            configured_equal=True, realized_usage_recorded=True,
            within_budget=all(not budget.violations(t.usage) for t in trials),
        )
        outer_binding = _outer_effect_binding(
            granted,
            execution,
            campaign_id=campaign_id,
            source_revision=source_revision,
            operation_sha256=operation_sha,
        )
        outer_binding_ref = store.put_bytes(
            canonical_json(outer_binding).encode("ascii")
        )
        finished = _now()
        receipt_inputs = {
            contract.digest, spec.digest, selected.candidate_tree_sha256,
            outer_binding_ref.sha256, base_binding_ref.sha256,
            nomination.digest, *(digest for t in trials for digest in (
                t.base_source_tree_sha256, *t.attempt_contract_sha256s,
                *t.attempt_receipt_sha256s, t.candidate_tree_sha256, t.evidence_packet_sha256,
            ) if digest is not None),
        }
        receipt = CampaignReceipt(
            campaign_id=campaign_id, source_revision=source_revision,
            campaign_contract_sha256=contract.digest, campaign_contract_locator=contract_ref.locator,
            experiment_spec_sha256=spec.digest, experiment_spec_locator=spec_ref.locator,
            metric_names=("exact_match",), trials=tuple(trials), execution_order=(0, 1, 2),
            outcome="nominated", selected_seed=selected.seed,
            candidate_tree_sha256=selected.candidate_tree_sha256,
            candidate_tree_locator=selected.candidate_tree_locator,
            nomination_receipt_sha256=nomination.digest,
            nomination_receipt_locator=nomination_ref.locator,
            usage=usage, overhead_usage=ResourceUsage(),
            negative_outcomes=tuple(sorted({
                f"{t.variant_id}:{outcome}"
                for t in trials for outcome in t.negative_outcomes
            })),
            reproducibility_note=(
                "The exact working-tree bytes are identified by base_source_tree_sha256; "
                "source_revision is independently verified HEAD provenance. Replay uses "
                "that base CAS, frozen evaluator, ordered arms, and equal ceilings."
            ),
            blockers=(), started_at=created, finished_at=finished,
            provenance=_prov("ariadne.controlled-repair.receipt", source_revision, finished, *receipt_inputs, trace=campaign_id),
            selection_mode="best-passed-trial", selected_variant_id=selected.variant_id,
            budget_equality=budget_equality,
        )
        receipt_ref = complete_campaign(ledger.spine, store, campaign_begin, receipt)
        campaign_committed = True
        _require_campaign_inner_effect_terminals(
            store,
            effect_evidence_root,
            receipt,
        )
        settled = _settle_committed_outer_effect(
            granted, effect_start, execution, receipt_ref.sha256
        )
        if not settled:
            raise AriadneCampaignError(
                "Campaign receipt is canonical but its outer effect needs "
                "ledger/evidence reconciliation"
            )
        return receipt.to_dict()
    except BaseException as exc:
        if campaign_committed:
            # The receipt is already canonical and durable. Never rewrite the
            # outer effect as FAILED. The caller sees explicit reconciliation
            # debt and every replay checks the receipt-bound terminal record.
            raise
        # Terminalise the innermost admitted unit first.  Cleanup failures are
        # deliberately swallowed here so the original campaign failure remains
        # the reported cause; the durable attempt/effect paths retain their own
        # failure evidence whenever they are still writable.
        if active_attempt_begin is not None and ledger is not None and store is not None:
            try:
                failure_report = store.put_bytes(canonical_json({
                    "schema": "daedalus-ariadne-attempt-failure/1",
                    "error_type": type(exc).__name__, "error": str(exc),
                }).encode("ascii"))
                ledger.complete(
                    active_attempt_begin.start,
                    receipt_id=f"terminal-{active_attempt_begin.start.attempt_id}",
                    outcome="faulted", report=failure_report, candidate_tree=None,
                )
            except BaseException:
                pass
        if active_inner is not None and active_inner_start is not None:
            try:
                active_inner.authorization.finish_effect(
                    active_inner_start.receipt, outcome="FAILED", output_digests=()
                )
                if active_inner_execution is not None:
                    active_inner.retain_terminal_record(active_inner_execution)
            except BaseException:
                pass
        if (
            not campaign_committed
            and campaign_begin is not None
            and campaign_begin.execute
            and ledger is not None
        ):
            try:
                fail_campaign(ledger.spine, campaign_begin, f"{type(exc).__name__}: {exc}")
            except BaseException:
                pass
        if effect_start.execute:
            try:
                granted.authorization.finish_effect(
                    effect_start.receipt, outcome="FAILED", output_digests=()
                )
                granted.retain_terminal_record(execution)
            except BaseException:
                pass
        raise
    finally:
        if ledger is not None:
            ledger.spine.close()
        if lock_acquired:
            lock.__exit__(None, None, None)
