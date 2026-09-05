"""Canonical prompt-to-preview execution service for Genesis.

One explicit request is admitted by :mod:`.admission`, receives a persisted
``python.genesis`` Effect Lease, starts one canonical Attempt, materializes an
explicit empty CAS base into a checkout-external workspace, captures the
candidate CAS before executing it, and retains real build/test/runtime/Fourfold
evidence from fresh materializations of that identity.  It never merges,
promotes, deploys, or publishes the candidate.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import mimetypes
import os
import sqlite3
import stat
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from daedalus.atomic import ExclusiveFileLock, FileLockUnavailable
from daedalus.kernel.artifacts import ArtifactRef
from daedalus.kernel.attempt_execution import RunnerContext, TaskSpec
from daedalus.kernel.attempt_contracts import AttemptStateError
from daedalus.kernel.attempt_ledger import AttemptLedger
from daedalus.kernel.attempt_workspace import IsolatedAttemptCoordinator
from daedalus.kernel.effects import EffectLeaseError
from daedalus.kernel.interpreter import (
    interpreter_provenance,
    resolve_python_argv,
)
from daedalus.kernel.contracts import (
    AttemptContract,
    BuildIntentProposal,
    CanonicalContract,
    ContractProvenance,
    DesignContract,
    EvidenceItem,
    EvidencePacket,
    GenesisAutonomyPolicy,
    GenesisRunRecord,
    GraphProposal,
    MaterializationPlan,
    MissionContract,
    PolicyDecision,
    ProductSpec,
    ResourceUsage,
    RoundTripReport,
    RuntimeManifest,
    TargetFourfoldSpec,
    ToolchainManifest,
)
from daedalus.kernel.fourfold_evidence import (
    FourfoldEvidenceExpectation,
    assemble_fourfold_evidence_packet,
    verify_fourfold_evidence_packet,
)
from daedalus.kernel.offload_lease import (
    WaveLeaseDenied,
    WaveOffloadLease,
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
from daedalus.sensitivity import Policy
from daedalus.spine.envelope import canonical_json, canonical_sha
from daedalus.spine.killswitch import KillSwitch, LoopHalted
from daedalus.spine.picker import resolve_spine_db_path
from daedalus.storage import ArtifactStore, ArtifactStoreError
from daedalus.twin.contracts import FourfoldSnapshot
from daedalus.twin.reference_compiler import compile_reference_project

from .admission import (
    GENESIS_MAX_BYTES,
    GENESIS_MAX_FILES,
    GENESIS_POLICY_ID,
    GENESIS_POLICY_VERSION,
    GENESIS_TIMEOUT_S,
    ITEM_COLLECTION_BLUEPRINT,
    KANBAN_BOARD_BLUEPRINT,
    KANBAN_POLICY_VERSION,
    BoundGenesisPlan,
    GenesisPlan,
    GenesisRequest,
    bind_genesis_attempt,
    build_genesis_plan,
    denied_policy_decision,
    normalize_genesis_request,
)
from .materializer import render_project


ENTRYPOINT_ID = "python.genesis"
SWITCH_ENTRYPOINT_ID = "python.genesis_switch"
MAX_COMMAND_OUTPUT_BYTES = 256 * 1024
MAX_REPORT_BYTES = 16 * 1024 * 1024
MAX_GENESIS_EVIDENCE_ITEMS = 64
GENESIS_CONTROL_LOCK_TIMEOUT_S = 2.0
_INVOCATION_EFFECT_BINDING_SCHEMA = "daedalus-genesis-invocation-effect-binding/1"
_APPROVED_WEB_APP_TEMPLATE_SHA256 = (
    "8f0c5f1981bc8e08f355478f3a80a03a8a62198b5697924aed5cf5987d292275"
)
_CLI_BLACK_BOX_TEMPLATE = r"""
import json
from pathlib import Path
import subprocess
import sys

DATA = Path(".genesis-black-box-items.json")
SEARCH_REQUIRED = @@SEARCH_REQUIRED@@

def invoke(*args):
    completed = subprocess.run(
        [sys.executable, "-I", "app.py", "--data", str(DATA), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stdout + completed.stderr)
    return json.loads(completed.stdout)

first = invoke("add", "Alpha", "--details", "First detail")
second = invoke("add", "Probe", "--details", "Drawer two")
assert first == {"details": "First detail", "done": False, "id": 1, "title": "Alpha"}
assert second["id"] == 2
assert [item["id"] for item in invoke("list")] == [1, 2]
changed = invoke("update", "1", "Renamed", "--details", "Updated detail")
assert changed["title"] == "Renamed" and changed["details"] == "Updated detail"
assert invoke("toggle", "2")["done"] is True
if SEARCH_REQUIRED:
    assert [item["id"] for item in invoke("search", "DRAWER")] == [2]
assert invoke("delete", "1") == {"deleted": 1}
assert [item["id"] for item in invoke("list")] == [2]
print("GENESIS_CLI_BLACK_BOX_OK")
""".strip()
_CLI_BLACK_BOX_TEMPLATE_SHA256 = hashlib.sha256(
    _CLI_BLACK_BOX_TEMPLATE.encode("utf-8")
).hexdigest()
_EVALUATOR_SHA256 = canonical_sha(
    {
        "schema": "daedalus-genesis-evaluator/2",
        "approved_web_app_template_sha256": _APPROVED_WEB_APP_TEMPLATE_SHA256,
        "cli_black_box_template_sha256": _CLI_BLACK_BOX_TEMPLATE_SHA256,
        "checks": [
            "build",
            "test",
            "runtime",
            "package",
            "feature_conformance",
            "certified_template_conformance",
            "cli_black_box",
            "containment",
            "fourfold",
            "roundtrip",
        ],
        "candidate_execution": "each gate starts from the exact captured candidate CAS",
        "independence": (
            "kernel-owned contained command gates, exact approved web-template "
            "identity, CLI black-box scenarios, and reference compiler; web "
            "browser behavior is not executed or claimed"
        ),
    }
)
_APPROVED_KANBAN_APP_TEMPLATE_SHA256 = (
    "66244182208b8bae5777d16d71f859724f8f37d71abb4decf5c84834d023d941"
)
_APPROVED_KANBAN_MODEL_SHA256 = (
    "dbebac7873d9b9853b8ba5275a8c489bca2dc873dd710becae5b8f6bced6f647"
)
_APPROVED_KANBAN_SCHEMA_SHA256 = (
    "bb12c29e79a3767e578b7c126062669ddccc21b3b23ec76730bcf41bd729f054"
)
_KANBAN_EVALUATOR_SHA256 = canonical_sha(
    {
        "schema": "daedalus-genesis-kanban-evaluator/1",
        "blueprint": KANBAN_BOARD_BLUEPRINT,
        "policy_version": KANBAN_POLICY_VERSION,
        "approved_app_template_sha256": _APPROVED_KANBAN_APP_TEMPLATE_SHA256,
        "approved_model_sha256": _APPROVED_KANBAN_MODEL_SHA256,
        "approved_schema_sha256": _APPROVED_KANBAN_SCHEMA_SHA256,
        "checks": [
            "build",
            "test",
            "runtime",
            "package",
            "kanban_template_conformance",
            "containment",
            "fourfold",
            "roundtrip",
        ],
        "candidate_execution": "each gate starts from the exact captured candidate CAS",
        "independence": (
            "kernel-owned contained command gates, exact approved kanban app-template, "
            "model and schema identities, fixed-column markup, and reference compiler; "
            "browser behavior is not executed or claimed"
        ),
    }
)


class GenesisError(RuntimeError):
    """Base class for a structured Genesis execution refusal."""


class GenesisConflictError(GenesisError):
    """One idempotency key was reused for different request material."""


class GenesisReconciliationError(GenesisError):
    """A committed Attempt is missing its bound invocation-effect terminal."""


class GenesisPreviewError(GenesisError):
    """A candidate read request is unavailable, unsafe, or not green."""


@dataclass(frozen=True)
class _StatePaths:
    repo_root: Path
    state_root: Path
    source_store: Path
    workspace_parent: Path
    evidence_store: Path
    effect_evidence: Path
    spine_db: Path


@dataclass(frozen=True)
class _CommandObservation:
    name: str
    candidate_tree_sha256: str
    argv: tuple[str, ...]
    returncode: int | None
    output: str
    output_truncated: bool
    timed_out: bool
    cancelled: bool
    wall_time_ms: int
    containment: Mapping[str, Any]
    interpreter: Mapping[str, Any] | None = None

    @property
    def passed(self) -> bool:
        return (
            self.returncode == 0
            and not self.timed_out
            and not self.cancelled
            and self.containment.get("contained") is True
        )

    def to_dict(self) -> dict[str, Any]:
        result = {
            "schema": "daedalus-genesis-command-observation/2",
            "name": self.name,
            "candidate_tree_sha256": self.candidate_tree_sha256,
            "argv": list(self.argv),
            "returncode": self.returncode,
            "output": self.output,
            "output_truncated": self.output_truncated,
            "timed_out": self.timed_out,
            "cancelled": self.cancelled,
            "wall_time_ms": self.wall_time_ms,
            "containment": dict(self.containment),
            "passed": self.passed,
        }
        if self.interpreter is not None:
            result["interpreter"] = dict(self.interpreter)
        return result


@dataclass(frozen=True)
class _GenesisControl:
    """Held canonical switch plus the cross-lane candidate execution slot."""

    switch: KillSwitch
    lock: ExclusiveFileLock

    def close(self) -> None:
        self.lock.__exit__(None, None, None)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _state_paths(repo_root: str | os.PathLike[str], request: GenesisRequest) -> _StatePaths:
    root = Path(repo_root).resolve(strict=True)
    if root.is_symlink() or not root.is_dir():
        raise GenesisError("Genesis authority root must be a real directory")
    state = control_root(root) / "genesis"
    spine, error = resolve_spine_db_path(root)
    if error or spine is None:
        raise GenesisError(f"canonical Attempt spine is unavailable: {error}")
    return _StatePaths(
        repo_root=root,
        state_root=state,
        source_store=state / "source-cas",
        workspace_parent=state / "workspaces",
        evidence_store=state / "evidence" / request.run_id,
        effect_evidence=state / "effect-evidence" / request.run_id,
        spine_db=Path(spine),
    )


def _ensure_genesis_switch(repo_root: Path, run_id: str) -> _GenesisControl:
    """Acquire one execution slot and arm only an unstopped canonical permit.

    Clicking Build or invoking ``daedalus genesis`` is the explicit owner
    start for this product strand. It may initialise the shared canonical
    permit, but it never forces past the sticky marker written by an operator
    stop. The narrow control boundary comes before the lock/control-root
    directory creation, child probe and permit write. Genesis and Ariadne
    share this serial slot as the Windows MIC complement: Low
    Integrity is not a per-workspace allow-list, so two simultaneously running
    Low candidates could otherwise write into each other's Low-labelled
    workspaces. It is an execution mutex, not crash reconciliation.
    """

    from daedalus.budget import process_guard_boundary_decision
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        SWITCH_ENTRYPOINT_ID,
        REGISTRY_BY_ID[SWITCH_ENTRYPOINT_ID].effects,
        (process_guard_boundary_decision(),),
    )
    lock = ExclusiveFileLock(
        control_root(repo_root) / "candidate-execution.lock",
        timeout_s=GENESIS_CONTROL_LOCK_TIMEOUT_S,
        label="repository-local shared Genesis/Ariadne candidate execution lock",
    )
    try:
        lock.__enter__()
    except FileLockUnavailable as exc:
        raise GenesisError(
            "another Genesis or Ariadne candidate currently owns the isolated "
            "execution slot; retry this request"
        ) from exc
    try:
        switch = KillSwitch(repo_root=repo_root)
        state = switch.read_state()
        if not state.running:
            try:
                state = switch.arm(note=f"owner-directed {run_id}")
            except LoopHalted as exc:
                raise GenesisError(
                    f"canonical kill switch refused Genesis: {exc}"
                ) from exc
        if not state.running:
            raise GenesisError(
                f"canonical kill switch did not arm Genesis: {state.reason}"
            )
        return _GenesisControl(switch=switch, lock=lock)
    except BaseException:
        lock.__exit__(None, None, None)
        raise


def _provenance(
    request: GenesisRequest,
    *,
    origin: str,
    created_at: str,
    inputs: Sequence[str] = (),
) -> ContractProvenance:
    return ContractProvenance(
        origin=origin,
        source_revision=request.source_revision,
        created_at=created_at,
        input_digests=tuple(sorted(set(inputs))),
        trace_id=request.run_id,
    )


def _empty_input_tree(plan: GenesisPlan, *, created_at: str) -> StoredSourceTree:
    request = plan.request
    manifest = SourceTreeManifest(
        tree_id=f"empty-{request.run_id.removeprefix('genesis-')}",
        source_revision=request.source_revision,
        entries=tuple[SourceTreeEntry, ...](),
        ignored_roots=MANDATORY_IGNORED_ROOTS,
        provenance=_provenance(
            request,
            origin="genesis.empty-source-tree",
            created_at=created_at,
            inputs=(),
        ),
    )
    return StoredSourceTree(
        manifest=manifest,
        ref=ArtifactRef.from_sha256(manifest.digest),
    )


def _store_contract(store: SourceTreeStore, contract: CanonicalContract) -> ArtifactRef:
    ref = store.put_bytes(contract.to_json().encode("ascii"))
    if ref.sha256 != contract.digest:
        raise GenesisError("canonical contract bytes disagree with their digest")
    return ref


def _strict_report(payload: bytes) -> dict[str, Any]:
    try:
        value = json.loads(payload.decode("ascii"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GenesisError("persisted Genesis report is not canonical JSON") from exc
    if not isinstance(value, dict) or canonical_json(value).encode("ascii") != payload:
        raise GenesisError("persisted Genesis report is not canonical JSON")
    return value


def _evaluator_sha256(blueprint: str) -> str:
    if blueprint == ITEM_COLLECTION_BLUEPRINT:
        return _EVALUATOR_SHA256
    if blueprint == KANBAN_BOARD_BLUEPRINT:
        return _KANBAN_EVALUATOR_SHA256
    raise GenesisError(f"unsupported persisted Genesis blueprint: {blueprint!r}")


def _persisted_blueprint(
    policy: GenesisAutonomyPolicy,
    product: ProductSpec,
) -> str:
    """Select an evaluator only from the retained CAS-bound contract pair."""

    if policy.policy_id != GENESIS_POLICY_ID:
        raise GenesisError("persisted Genesis policy identity is unsupported")
    marker = product.defaults.get("blueprint")
    if (
        policy.policy_version == GENESIS_POLICY_VERSION
        and "blueprint" not in product.defaults
    ):
        return ITEM_COLLECTION_BLUEPRINT
    if (
        policy.policy_version == KANBAN_POLICY_VERSION
        and marker == KANBAN_BOARD_BLUEPRINT
        and product.target in {"desktop", "mobile", "web"}
        and tuple(policy.allowed_targets) == ("desktop", "mobile", "web")
    ):
        return KANBAN_BOARD_BLUEPRINT
    raise GenesisError(
        "persisted Genesis policy/ProductSpec blueprint combination is unsupported"
    )


def _feature_assurance(
    blueprint: str,
    target: str,
    round_trip: RoundTripReport | None,
) -> dict[str, Any]:
    if blueprint == ITEM_COLLECTION_BLUEPRINT:
        if target == "cli":
            return {
                "browser_behavior_verified": False,
                "candidate_owned": False,
                "cli_black_box_verified": bool(
                    round_trip and round_trip.checks.get("cli_black_box")
                ),
                "mechanism": (
                    "kernel-owned structural source conformance plus contained "
                    "CLI black-box scenario"
                ),
                "runtime_behavior_verified_by_this_check": True,
            }
        return {
            "approved_web_app_template_sha256": _APPROVED_WEB_APP_TEMPLATE_SHA256,
            "browser_behavior_verified": False,
            "candidate_owned": False,
            "mechanism": "kernel-owned certified-template conformance",
            "runtime_behavior_verified_by_this_check": False,
            "limitation": (
                "The exact approved app.js template and CONFIG are checked, but "
                "browser interactions are not executed; behavioral browser "
                "verification remains a separate release gap."
            ),
        }
    if blueprint == KANBAN_BOARD_BLUEPRINT:
        return {
            "approved_kanban_app_template_sha256": (
                _APPROVED_KANBAN_APP_TEMPLATE_SHA256
            ),
            "approved_kanban_model_sha256": _APPROVED_KANBAN_MODEL_SHA256,
            "approved_kanban_schema_sha256": _APPROVED_KANBAN_SCHEMA_SHA256,
            "blueprint": KANBAN_BOARD_BLUEPRINT,
            "browser_behavior_verified": False,
            "candidate_owned": False,
            "kanban_template_verified": bool(
                round_trip
                and round_trip.checks.get("kanban_template_conformance")
            ),
            "mechanism": (
                "kernel-owned certified kanban template plus pinned model/schema "
                "conformance"
            ),
            "runtime_behavior_verified_by_this_check": False,
            "limitation": (
                "Exact generated source identities and fixed-column wiring are "
                "checked, but browser interactions are not executed; behavioral "
                "browser verification remains a separate release gap."
            ),
        }
    raise GenesisError(f"unsupported Genesis assurance blueprint: {blueprint!r}")


def _invocation_effect_identity(
    granted: WaveOffloadLease,
    execution: Any,
    request: GenesisRequest,
    *,
    operation_sha256: str,
) -> dict[str, Any]:
    execution_key = f"lease_execution:{execution.execution_id}"
    subject_digest = granted.evidence_records.get("lease_subject")
    execution_digest = granted.evidence_records.get(execution_key)
    digests = {
        "operation_sha256": operation_sha256,
        "lease_sha256": granted.lease.digest,
        "execution_request_sha256": execution.digest,
        "lease_subject_record_sha256": subject_digest,
        "lease_execution_record_sha256": execution_digest,
    }
    try:
        checked = {
            name: ArtifactRef.from_sha256(str(value)).sha256
            for name, value in digests.items()
        }
        require_retained_effect_lease_start_records(
            granted.evidence_root,
            subject_record_sha256=checked["lease_subject_record_sha256"],
            execution_record_sha256=checked["lease_execution_record_sha256"],
            entrypoint_id=ENTRYPOINT_ID,
            source_revision=request.source_revision,
            attempt_id=request.attempt_id,
            operation_sha256=checked["operation_sha256"],
            expected_lease_sha256=checked["lease_sha256"],
            expected_execution_id=execution.execution_id,
            expected_execution_request_sha256=checked["execution_request_sha256"],
        )
    except (EffectLeaseError, OSError, TypeError, ValueError) as exc:
        raise GenesisError(
            "Genesis invocation effect evidence was not retained or is invalid"
        ) from exc
    return {
        "schema": _INVOCATION_EFFECT_BINDING_SCHEMA,
        "entrypoint_id": ENTRYPOINT_ID,
        "source_revision": request.source_revision,
        "attempt_id": request.attempt_id,
        "operation_sha256": checked["operation_sha256"],
        "lease_sha256": checked["lease_sha256"],
        "execution_id": execution.execution_id,
        "execution_request_sha256": checked["execution_request_sha256"],
        "lease_subject_record_sha256": checked["lease_subject_record_sha256"],
        "lease_execution_record_sha256": checked["lease_execution_record_sha256"],
    }


def _invocation_effect_binding(
    identity: Mapping[str, Any],
    *,
    expected_terminal_state: str,
) -> dict[str, Any]:
    if expected_terminal_state not in {"completed", "failed"}:
        raise GenesisError("Genesis invocation effect terminal state is invalid")
    return {**dict(identity), "expected_terminal_state": expected_terminal_state}


def _invocation_effect_output_digests(
    result: Mapping[str, Any],
) -> tuple[str, ...]:
    """Derive the exact outer-effect outputs from its canonical report."""

    digests = {canonical_sha(dict(result))}
    candidate = result.get("candidate")
    if isinstance(candidate, Mapping):
        try:
            candidate_ref = ArtifactRef(
                sha256=str(candidate["sha256"]),
                locator=str(candidate["locator"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GenesisError("Genesis report candidate output is invalid") from exc
        digests.add(candidate_ref.sha256)
    artifacts = result.get("artifacts")
    if isinstance(artifacts, Mapping):
        for name in ("evidence", "roundtrip"):
            if name in artifacts:
                digests.add(_report_artifact_ref(result, name).sha256)
    return tuple(sorted(digests))


def _require_invocation_effect_terminal(
    paths: _StatePaths,
    result: Mapping[str, Any],
    *,
    attempt_id: str,
    source_revision: str,
) -> None:
    """Require the terminal evidence bound before the Attempt report committed.

    The report cannot name the terminal record digest because the Attempt is the
    product commit and the invocation effect terminalizes immediately after it.
    It instead binds the original subject and execution records.  Their exact
    content then selects one content-addressed terminal record.  This keeps a
    post-commit crash visible on every replay without inventing another store or
    automatically repairing authoritative history.
    """

    binding = result.get("invocation_effect")
    if not isinstance(binding, Mapping):
        raise GenesisReconciliationError(
            "Genesis invocation effect needs reconciliation: report has no terminal binding"
        )
    expected_state = binding.get("expected_terminal_state")
    expected_keys = {
        "schema",
        "entrypoint_id",
        "source_revision",
        "attempt_id",
        "operation_sha256",
        "lease_sha256",
        "execution_id",
        "execution_request_sha256",
        "lease_subject_record_sha256",
        "lease_execution_record_sha256",
        "expected_terminal_state",
    }
    report_expected_state = (
        "completed"
        if result.get("status") in {"preview-ready", "succeeded"}
        else "failed"
        if result.get("status") == "failed"
        else None
    )
    if (
        set(binding) != expected_keys
        or binding.get("schema") != _INVOCATION_EFFECT_BINDING_SCHEMA
        or binding.get("entrypoint_id") != ENTRYPOINT_ID
        or binding.get("source_revision") != source_revision
        or binding.get("attempt_id") != attempt_id
        or expected_state not in {"completed", "failed"}
        or expected_state != report_expected_state
    ):
        raise GenesisReconciliationError(
            "Genesis invocation effect needs reconciliation: report terminal binding is invalid"
        )
    try:
        operation_sha256 = ArtifactRef.from_sha256(
            str(binding["operation_sha256"])
        ).sha256
        lease_sha256 = ArtifactRef.from_sha256(str(binding["lease_sha256"])).sha256
        execution_request_sha256 = ArtifactRef.from_sha256(
            str(binding["execution_request_sha256"])
        ).sha256
        subject_digest = ArtifactRef.from_sha256(
            str(binding["lease_subject_record_sha256"])
        ).sha256
        execution_digest = ArtifactRef.from_sha256(
            str(binding["lease_execution_record_sha256"])
        ).sha256
        execution_id = str(binding["execution_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise GenesisReconciliationError(
            "Genesis invocation effect needs reconciliation: report terminal binding is incomplete"
        ) from exc
    try:
        terminal = require_retained_effect_lease_terminal_record(
            paths.effect_evidence,
            subject_record_sha256=subject_digest,
            execution_record_sha256=execution_digest,
            entrypoint_id=ENTRYPOINT_ID,
            source_revision=source_revision,
            attempt_id=attempt_id,
            operation_sha256=operation_sha256,
            expected_terminal_state=str(expected_state),
            expected_output_digests=_invocation_effect_output_digests(result),
            expected_lease_sha256=lease_sha256,
            expected_execution_id=execution_id,
            expected_execution_request_sha256=execution_request_sha256,
        )
    except (EffectLeaseError, OSError, TypeError, ValueError) as exc:
        raise GenesisReconciliationError(
            f"Genesis invocation effect needs reconciliation: {exc}"
        ) from exc
    if (
        terminal.get("lease_sha256") != lease_sha256
        or terminal.get("execution_id") != execution_id
        or terminal.get("execution_request_sha256") != execution_request_sha256
    ):
        raise GenesisReconciliationError(
            "Genesis invocation effect needs reconciliation: report terminal binding is invalid"
        )


def _report_artifact_ref(
    result: Mapping[str, Any],
    name: str,
) -> ArtifactRef:
    artifacts = result.get("artifacts")
    row = artifacts.get(name) if isinstance(artifacts, Mapping) else None
    expected_kind = name.replace("_", " ")
    if (
        not isinstance(row, Mapping)
        or set(row) != {"kind", "sha256", "locator"}
        or row.get("kind") != expected_kind
    ):
        raise GenesisError(f"persisted Genesis {name} artifact row is invalid")
    try:
        return ArtifactRef(sha256=str(row["sha256"]), locator=str(row["locator"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise GenesisError(
            f"persisted Genesis {name} artifact identity is invalid"
        ) from exc


def _load_genesis_contract(
    store: SourceTreeStore,
    ref: ArtifactRef,
    contract_type: type[CanonicalContract],
    *,
    label: str,
) -> CanonicalContract:
    """Load one exact typed contract through the canonical bounded CAS reader."""

    try:
        raw = store.read_bytes(ref, max_bytes=MAX_REPORT_BYTES)
        value = json.loads(raw.decode("ascii"))
        if not isinstance(value, Mapping):
            raise ValueError("contract payload is not an object")
        contract = contract_type.from_dict(value)
    except (
        UnicodeError,
        json.JSONDecodeError,
        SourceTreeStoreError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise GenesisError(
            f"persisted Genesis {label} is unavailable or invalid"
        ) from exc
    canonical = contract.to_json().encode("ascii")
    if raw != canonical or contract.digest != ref.sha256:
        raise GenesisError(f"persisted Genesis {label} is noncanonical")
    return contract


def _verify_candidate_source_tree(
    store: SourceTreeStore,
    ref: ArtifactRef,
    *,
    source_revision: str,
    max_files: int,
    max_bytes: int,
) -> SourceTreeManifest:
    """Resolve one candidate manifest and every blob within its frozen budget."""

    try:
        manifest = store.load_tree(ref, max_manifest_bytes=MAX_REPORT_BYTES)
        if manifest.source_revision != source_revision:
            raise GenesisError(
                "persisted Genesis candidate source tree revision is invalid"
            )
        if len(manifest.entries) > max_files:
            raise GenesisError(
                "persisted Genesis candidate source tree exceeds its file bound"
            )
        total = 0
        for entry in manifest.entries:
            if entry.size > max_bytes:
                raise GenesisError(
                    "persisted Genesis candidate source tree exceeds its file-size bound"
                )
            total += entry.size
            if total > max_bytes:
                raise GenesisError(
                    "persisted Genesis candidate source tree exceeds its total-size bound"
                )
            payload = store.read_bytes(
                ArtifactRef.from_sha256(entry.blob_sha256),
                max_bytes=entry.size,
            )
            if len(payload) != entry.size:
                raise GenesisError(
                    "persisted Genesis candidate source tree entry size is invalid"
                )
    except GenesisError:
        raise
    except (SourceTreeStoreError, TypeError, ValueError) as exc:
        raise GenesisError(
            "persisted Genesis candidate source tree is unavailable or invalid"
        ) from exc
    return manifest


def _verify_terminal_genesis_chain(
    paths: _StatePaths,
    store: SourceTreeStore,
    request: GenesisRequest,
    existing: Any,
    result: Mapping[str, Any],
) -> SourceTreeManifest | None:
    """Verify every retained CAS identity before replaying a terminal report."""

    status = result.get("status")
    green = status in {"preview-ready", "succeeded"}
    if not green and status != "failed":
        raise GenesisError("terminal Genesis report has an invalid status")
    receipt = existing.completion.receipt
    if green and (receipt.outcome != "succeeded" or receipt.candidate_tree is None):
        raise GenesisError("green Genesis report lacks a successful Attempt receipt")
    if not green and receipt.outcome == "succeeded":
        raise GenesisError(
            "successful Genesis Attempt receipt does not carry a green report"
        )
    if canonical_sha(dict(result)) != receipt.report.sha256:
        raise GenesisError("terminal Genesis report digest differs from its Attempt receipt")

    revision = existing.start.source_revision
    try:
        input_manifest = store.load_tree(
            existing.start.input_tree,
            max_manifest_bytes=MAX_REPORT_BYTES,
        )
    except (SourceTreeStoreError, TypeError, ValueError) as exc:
        raise GenesisError(
            "persisted Genesis empty input source tree is unavailable or invalid"
        ) from exc
    if (
        input_manifest.source_revision != revision
        or input_manifest.entries
        or input_manifest.provenance.trace_id != request.run_id
    ):
        raise GenesisError("persisted Genesis empty input source tree is invalid")

    artifacts = result.get("artifacts")
    if not green and artifacts == {}:
        if any(result.get(name) is not None for name in ("candidate", "evidence", "roundtrip")):
            raise GenesisError("failed Genesis fallback report has partial artifact claims")
        if receipt.candidate_tree is None:
            return None
        return _verify_candidate_source_tree(
            store,
            receipt.candidate_tree,
            source_revision=existing.start.source_revision,
            max_files=MAX_GENESIS_EVIDENCE_ITEMS,
            max_bytes=MAX_REPORT_BYTES,
        )

    contract_types: dict[str, tuple[type[CanonicalContract], str]] = {
        "autonomy_policy": (GenesisAutonomyPolicy, "GenesisAutonomyPolicy"),
        "runtime_manifest": (RuntimeManifest, "RuntimeManifest"),
        "build_intent": (BuildIntentProposal, "BuildIntentProposal"),
        "product_spec": (ProductSpec, "ProductSpec"),
        "policy_decision": (PolicyDecision, "PolicyDecision"),
        "design_contract": (DesignContract, "DesignContract"),
        "target_fourfold": (TargetFourfoldSpec, "TargetFourfoldSpec"),
        "graph_proposal": (GraphProposal, "GraphProposal"),
        "mission": (MissionContract, "MissionContract"),
        "materialization_plan": (MaterializationPlan, "MaterializationPlan"),
        "toolchain_manifest": (ToolchainManifest, "ToolchainManifest"),
        "attempt": (AttemptContract, "AttemptContract"),
        "evidence": (EvidencePacket, "EvidencePacket"),
        "run_record": (GenesisRunRecord, "GenesisRunRecord"),
    }
    if isinstance(artifacts, Mapping) and (
        "actual_fourfold" in artifacts or "roundtrip" in artifacts
    ):
        contract_types["actual_fourfold"] = (FourfoldSnapshot, "FourfoldSnapshot")
        contract_types["roundtrip"] = (RoundTripReport, "RoundTripReport")
    if not isinstance(artifacts, Mapping) or set(artifacts) != set(contract_types):
        raise GenesisError("terminal Genesis report has an incomplete artifact set")
    refs: dict[str, ArtifactRef] = {}
    contracts: dict[str, CanonicalContract] = {}
    for name, (contract_type, label) in contract_types.items():
        ref = _report_artifact_ref(result, name)
        refs[name] = ref
        contracts[name] = _load_genesis_contract(
            store,
            ref,
            contract_type,
            label=label,
        )

    policy = contracts["autonomy_policy"]
    intent = contracts["build_intent"]
    product = contracts["product_spec"]
    decision = contracts["policy_decision"]
    design = contracts["design_contract"]
    target = contracts["target_fourfold"]
    graph = contracts["graph_proposal"]
    mission = contracts["mission"]
    materialization = contracts["materialization_plan"]
    toolchain = contracts["toolchain_manifest"]
    attempt = contracts["attempt"]
    packet = contracts["evidence"]
    snapshot = contracts.get("actual_fourfold")
    round_trip = contracts.get("roundtrip")
    run_record = contracts["run_record"]
    if not (
        isinstance(policy, GenesisAutonomyPolicy)
        and isinstance(intent, BuildIntentProposal)
        and isinstance(product, ProductSpec)
        and isinstance(decision, PolicyDecision)
        and isinstance(design, DesignContract)
        and isinstance(target, TargetFourfoldSpec)
        and isinstance(graph, GraphProposal)
        and isinstance(mission, MissionContract)
        and isinstance(materialization, MaterializationPlan)
        and isinstance(toolchain, ToolchainManifest)
        and isinstance(attempt, AttemptContract)
        and isinstance(packet, EvidencePacket)
        and isinstance(run_record, GenesisRunRecord)
        and (snapshot is None or isinstance(snapshot, FourfoldSnapshot))
        and (round_trip is None or isinstance(round_trip, RoundTripReport))
        and ((snapshot is None) == (round_trip is None))
    ):
        raise GenesisError("terminal Genesis report artifact types are invalid")
    if green and (snapshot is None or round_trip is None):
        raise GenesisError("green Genesis report lacks Fourfold/round-trip artifacts")

    persisted_blueprint = _persisted_blueprint(policy, product)
    expected_evaluator_sha256 = _evaluator_sha256(persisted_blueprint)

    lineage = request.lineage_id
    if any(
        getattr(contract.provenance, "source_revision", None) != revision
        or getattr(contract.provenance, "trace_id", None) != request.run_id
        for contract in contracts.values()
    ):
        raise GenesisError("terminal Genesis artifact provenance differs from its run")
    if any(
        getattr(contract, "lineage_id") != lineage
        for contract in (intent, product, design, target, graph, materialization, toolchain)
    ):
        raise GenesisError("terminal Genesis artifact lineage differs from its run")
    if (
        policy.source_revision != revision
        or intent.source_revision != revision
        or product.source_revision != revision
        or design.source_revision != revision
        or target.source_revision != revision
        or graph.source_revision != revision
        or mission.source_revision != revision
        or materialization.source_revision != revision
        or toolchain.source_revision != revision
        or attempt.base_revision != revision
        or packet.source_revision != revision
        or (snapshot is not None and snapshot.source_revision != revision)
        or (round_trip is not None and round_trip.source_revision != revision)
        or run_record.source_revision != revision
    ):
        raise GenesisError("terminal Genesis artifact revision differs from its Attempt")

    candidate = result.get("candidate")
    if (
        not isinstance(candidate, Mapping)
        or set(candidate) != {"kind", "sha256", "locator", "files"}
        or candidate.get("kind") != "candidate source tree"
    ):
        raise GenesisError("terminal Genesis candidate artifact row is invalid")
    try:
        candidate_ref = ArtifactRef(
            sha256=str(candidate["sha256"]),
            locator=str(candidate["locator"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise GenesisError("terminal Genesis candidate identity is invalid") from exc
    if candidate_ref != receipt.candidate_tree:
        raise GenesisError(
            "Genesis report candidate does not match its terminal Attempt receipt"
        )
    manifest = _verify_candidate_source_tree(
        store,
        candidate_ref,
        source_revision=revision,
        max_files=policy.max_files,
        max_bytes=policy.max_bytes,
    )
    if candidate.get("files") != [entry.path for entry in manifest.entries]:
        raise GenesisError("terminal Genesis candidate file inventory is invalid")

    evidence_row = result.get("evidence")
    roundtrip_row = result.get("roundtrip")
    mission_row = result.get("mission")
    if (
        not isinstance(evidence_row, Mapping)
        or set(evidence_row)
        != {"kind", "sha256", "locator", "status", "checks", "candidate_tree_sha256"}
        or evidence_row.get("kind") != "evidence packet"
        or evidence_row.get("sha256") != refs["evidence"].sha256
        or evidence_row.get("locator") != refs["evidence"].locator
        or evidence_row.get("status") != packet.evaluation_status
        or evidence_row.get("candidate_tree_sha256") != candidate_ref.sha256
        or evidence_row.get("checks")
        != [item.evidence_id for item in packet.items]
    ):
        raise GenesisError("terminal Genesis EvidencePacket report binding is invalid")
    if round_trip is None:
        if (
            not isinstance(roundtrip_row, Mapping)
            or set(roundtrip_row) != {"status", "error"}
            or roundtrip_row.get("status") != "failed"
            or not isinstance(roundtrip_row.get("error"), str)
        ):
            raise GenesisError("failed Genesis round-trip report claim is invalid")
    elif (
        not isinstance(roundtrip_row, Mapping)
        or set(roundtrip_row)
        != {"kind", "sha256", "locator", "status", "checks", "feature_assurance"}
        or roundtrip_row.get("kind") != "round-trip report"
        or roundtrip_row.get("sha256") != refs["roundtrip"].sha256
        or roundtrip_row.get("locator") != refs["roundtrip"].locator
        or roundtrip_row.get("status") != round_trip.status
        or dict(roundtrip_row.get("checks", {})) != dict(round_trip.checks)
        or dict(roundtrip_row.get("feature_assurance", {}))
        != _feature_assurance(persisted_blueprint, product.target, round_trip)
    ):
        raise GenesisError("terminal Genesis RoundTripReport report binding is invalid")
    if not isinstance(mission_row, Mapping) or dict(mission_row) != {
        "mission_id": mission.mission_id,
        "objective": mission.objective,
        "work_items": list(mission.work_item_ids),
        "success_criteria": list(mission.success_criteria),
        "policy_sha256": mission.policy_sha256,
    }:
        raise GenesisError("terminal Genesis MissionContract report binding is invalid")

    if (
        intent.runtime_manifest_sha256 != refs["runtime_manifest"].sha256
        or product.policy_sha256 != policy.digest
        or product.build_intent_proposal_sha256 != intent.digest
        or product.target != result.get("target")
        or dict(product.defaults) != dict(result.get("defaults", {}))
        or design.product_spec_sha256 != product.digest
        or target.product_spec_sha256 != product.digest
        or target.design_contract_sha256 != design.digest
        or graph.target_fourfold_spec_sha256 != target.digest
        or graph.runtime_manifest_sha256 != refs["runtime_manifest"].sha256
        or mission.mission_id != request.mission_id
        or mission.policy_sha256 != policy.digest
        or decision.verdict != "allow"
        or decision.subject_id != product.product_id
        or decision.subject_sha256 != product.digest
        or decision.policy_version != policy.policy_version
        or decision.policy_sha256 != policy.digest
        or (status == "preview-ready" and not policy.allow_isolated_preview)
        or materialization.product_spec_sha256 != product.digest
        or materialization.design_contract_sha256 != design.digest
        or materialization.target_fourfold_spec_sha256 != target.digest
        or materialization.graph_proposal_sha256 != graph.digest
        or materialization.input_tree != existing.start.input_tree
        or toolchain.materialization_plan_sha256 != materialization.digest
        or toolchain.target != result.get("target")
        or attempt.attempt_id != request.attempt_id
        or attempt.mission_id != mission.mission_id
        or attempt.digest != existing.start.attempt_sha256
        or attempt.digest != receipt.attempt_sha256
        or attempt.runtime_manifest_sha256 != refs["runtime_manifest"].sha256
        or attempt.policy_decision_sha256 != decision.digest
    ):
        raise GenesisError("terminal Genesis specification/Attempt chain is invalid")
    if (
        packet.mission_id != mission.mission_id
        or packet.attempt_id != attempt.attempt_id
        or packet.attempt_contract_sha256 != attempt.digest
        or packet.subject_sha256 != candidate_ref.sha256
        or packet.candidate_artifact_sha256 != candidate_ref.sha256
        or packet.candidate_artifact_locator != candidate_ref.locator
        or packet.policy_decision_sha256 != decision.digest
        or (green and packet.evaluation_status != "passed")
        or (not green and packet.evaluation_status != "failed")
        or len(packet.items) > MAX_GENESIS_EVIDENCE_ITEMS
    ):
        raise GenesisError("terminal Genesis EvidencePacket chain is invalid")
    for item in packet.items:
        item_candidate = item.details.get("candidate_tree_sha256")
        if item_candidate is None:
            item_candidate = item.details.get("candidate_artifact_sha256")
        if (
            item_candidate != candidate_ref.sha256
            or candidate_ref.sha256 not in item.provenance.input_digests
        ):
            raise GenesisError(
                "terminal Genesis evidence item candidate binding is invalid"
            )
    if (
        snapshot is not None
        and candidate_ref.sha256 not in snapshot.provenance.input_digests
    ):
        raise GenesisError(
            "terminal Genesis FourfoldSnapshot candidate binding is invalid"
        )
    if round_trip is not None and (
        round_trip.lineage_id != lineage
        or round_trip.mission_id != mission.mission_id
        or round_trip.candidate_tree != candidate_ref
        or round_trip.actual_fourfold != refs["actual_fourfold"]
        or round_trip.target_fourfold_spec_sha256 != target.digest
        or round_trip.evaluator_sha256 != expected_evaluator_sha256
        or round_trip.evidence_packet_sha256 != packet.digest
        or (green and round_trip.status != "passed")
        or (green and not all(round_trip.checks.values()))
        or (green and bool(round_trip.mismatches))
        or (not green and round_trip.status != "failed")
    ):
        raise GenesisError("terminal Genesis RoundTripReport chain is invalid")
    if (
        run_record.run_id != request.run_id
        or run_record.lineage_id != lineage
        or run_record.mission_id != mission.mission_id
        or run_record.status != status
        or run_record.policy_sha256 != policy.digest
        or run_record.product_spec_sha256 != product.digest
        or run_record.mission_contract_sha256 != mission.digest
        or run_record.work_item_ids != mission.work_item_ids
        or run_record.attempt_ids != (attempt.attempt_id,)
        or run_record.candidate_tree != candidate_ref
        or run_record.evidence_packet_sha256 != packet.digest
        or run_record.round_trip_report_sha256
        != (round_trip.digest if round_trip is not None else None)
    ):
        raise GenesisError("terminal Genesis GenesisRunRecord chain is invalid")

    evidence_store = ArtifactStore(paths.evidence_store)
    try:
        for item in packet.items:
            locator_prefix = "artifact-locator:sha256:"
            if not item.evidence_locator.startswith(locator_prefix):
                raise GenesisError("terminal Genesis evidence locator is invalid")
            locator = evidence_store.load_locator(
                item.evidence_locator.removeprefix(locator_prefix)
            )
            locator_inputs = locator.provenance.get("input_digests")
            if (
                locator.locator_uri != item.evidence_locator
                or locator.artifact_sha256 != item.output_sha256
                or locator.byte_length > MAX_REPORT_BYTES
                or locator.provenance.get("source_revision") != revision
                or locator.provenance.get("trace_id") != request.run_id
                or not isinstance(locator_inputs, list)
                or candidate_ref.sha256 not in locator_inputs
            ):
                raise GenesisError(
                    f"terminal Genesis evidence item {item.evidence_id} is invalid"
                )
            evidence_store.verify(locator)
    except GenesisError:
        raise
    except (ArtifactStoreError, OSError, TypeError, ValueError) as exc:
        raise GenesisError(
            "terminal Genesis evidence artifact is unavailable or invalid"
        ) from exc
    if green:
        assert isinstance(snapshot, FourfoldSnapshot)
        try:
            verify_fourfold_evidence_packet(
                packet,
                snapshot=snapshot,
                expectation=FourfoldEvidenceExpectation(
                    candidate_artifact_sha256=candidate_ref.sha256,
                    candidate_artifact_locator=candidate_ref.locator,
                    snapshot_sha256=snapshot.digest,
                    source_revision=revision,
                ),
                store=evidence_store,
            )
        except Exception as exc:
            raise GenesisError(
                "green Genesis Fourfold evidence chain is unavailable or invalid"
            ) from exc
    return manifest


def _read_existing(
    paths: _StatePaths,
    request: GenesisRequest,
    *,
    immutable: bool = True,
) -> dict[str, Any] | None:
    if not paths.source_store.is_dir() or not paths.spine_db.is_file():
        return None
    store = SourceTreeStore.open_existing(paths.source_store)
    existing = AttemptLedger.lookup_read_only(
        paths.spine_db,
        store,
        request.attempt_id,
        immutable=immutable,
    )
    if existing is None:
        return None
    if existing.start.source_revision != request.source_revision:
        raise GenesisConflictError(
            "request_key is already bound to different prompt, target, or stack material"
        )
    if existing.completion is None:
        return _pending_result(request)
    report = store.read_bytes(
        existing.completion.receipt.report,
        max_bytes=MAX_REPORT_BYTES,
    )
    result = _strict_report(report)
    if result.get("run_id") != request.run_id:
        raise GenesisError("persisted Genesis report belongs to another run")
    _verify_terminal_genesis_chain(paths, store, request, existing, result)
    _require_invocation_effect_terminal(
        paths,
        result,
        attempt_id=request.attempt_id,
        source_revision=existing.start.source_revision,
    )
    return result


def _pending_result(request: GenesisRequest) -> dict[str, Any]:
    return {
        "run_id": request.run_id,
        "request_key": request.request_key,
        "status": "running",
        "target": request.target,
        "defaults": dict(request.defaults),
        "blockers": [
            "A durable Attempt start exists without a terminal receipt. Genesis only "
            "replays terminal receipts; crash reconciliation is not implemented."
        ],
        "mission": {"mission_id": request.mission_id},
        "candidate": None,
        "evidence": None,
        "roundtrip": None,
        "preview": None,
        "artifacts": {},
        "publication": {
            "status": "not-requested",
            "owner_approval_required": True,
        },
    }


def _blocked_result(request: GenesisRequest, *, created_at: str) -> dict[str, Any]:
    decision = denied_policy_decision(request, created_at=created_at)
    return {
        "run_id": request.run_id,
        "request_key": request.request_key,
        "status": "blocked",
        "target": request.target,
        "defaults": dict(request.defaults),
        "blockers": list(request.blockers),
        "mission": None,
        "candidate": None,
        "evidence": None,
        "roundtrip": None,
        "preview": None,
        "artifacts": {},
        "admission": {
            "policy_decision": decision.to_dict(),
            "effect_started": False,
            "stack_required": request.stack_required,
            "target_required": request.target_required,
        },
        "publication": {
            "status": "not-requested",
            "owner_approval_required": True,
        },
    }


def _run_command(
    name: str,
    argv: Sequence[str],
    *,
    task_id: str,
    candidate_tree_sha256: str,
    workspace: Path,
    switch: KillSwitch,
    timeout_s: float,
) -> _CommandObservation:
    from daedalus.orchestration.execution.attempts import command_gate

    switch.checkpoint()
    displayed = tuple(str(part) for part in argv)
    actual = resolve_python_argv(displayed)
    interpreter = (
        interpreter_provenance(actual[0])
        if displayed and displayed[0] in ("python", sys.executable)
        else None
    )
    task = TaskSpec(
        task_id=task_id,
        instruction=f"Run the independent Genesis {name} check",
        base_revision=candidate_tree_sha256,
        gate_argv=displayed,
        gate_timeout_s=timeout_s,
    )
    result = command_gate(
        actual,
        timeout_s=timeout_s,
        poll_s=0.05,
        name=f"genesis-{name}",
        executes_candidate=True,
    )(
        RunnerContext(
            worktree=workspace,
            branch=f"genesis/{task_id}",
            base_revision=candidate_tree_sha256,
            task=task,
            is_cancelled=switch.should_stop,
        )
    )
    raw_output = result.output.encode("utf-8", errors="replace")
    truncated = len(raw_output) > MAX_COMMAND_OUTPUT_BYTES
    bounded = raw_output[:MAX_COMMAND_OUTPUT_BYTES]
    containment = (
        result.containment.summary() if result.containment is not None else {}
    )
    return _CommandObservation(
        name=name,
        candidate_tree_sha256=candidate_tree_sha256,
        argv=displayed,
        returncode=result.returncode,
        output=bounded.decode("utf-8", errors="replace"),
        output_truncated=truncated,
        timed_out=result.timed_out,
        cancelled=result.cancelled,
        wall_time_ms=max(0, int(round(result.duration_s * 1000))),
        containment=containment,
        interpreter=interpreter,
    )


def _evidence_item(
    observation: _CommandObservation,
    *,
    request: GenesisRequest,
    candidate: ArtifactRef,
    store: ArtifactStore,
    collected_at: str,
) -> EvidenceItem:
    if observation.candidate_tree_sha256 != candidate.sha256:
        raise GenesisError(
            "evaluator observation is bound to a different candidate CAS"
        )
    body = observation.to_dict()
    feature_conformance = observation.name == "feature_conformance"
    certified_template = observation.name == "certified_template_conformance"
    kanban_template = observation.name == "kanban_template_conformance"
    cli_black_box = observation.name == "cli_black_box"
    if kanban_template:
        body["schema"] = "daedalus-genesis-kanban-template-conformance-observation/1"
        body["kernel_owned"] = True
    elif certified_template:
        body["schema"] = (
            "daedalus-genesis-certified-template-conformance-observation/1"
        )
        body["kernel_owned"] = True
    elif feature_conformance:
        body["schema"] = (
            "daedalus-genesis-structural-feature-conformance-observation/1"
        )
        body["kernel_owned"] = True
    elif cli_black_box:
        body["schema"] = "daedalus-genesis-cli-black-box-observation/1"
        body["kernel_owned"] = True
    payload = canonical_json(body).encode("ascii")
    output_sha = hashlib.sha256(payload).hexdigest()
    locator = store.put_bytes(
        payload,
        expected_sha256=output_sha,
        media_type="application/json",
        metadata={
            "kind": (
                "genesis_kanban_template_conformance_observation"
                if kanban_template
                else "genesis_certified_template_conformance_observation"
                if certified_template
                else "genesis_structural_feature_conformance_observation"
                if feature_conformance
                else "genesis_cli_black_box_observation"
                if cli_black_box
                else "genesis_command_observation"
            ),
            "name": observation.name,
            "candidate_tree_sha256": candidate.sha256,
        },
        provenance={
            "origin": (
                "genesis.independent-kanban-template-conformance"
                if kanban_template
                else "genesis.independent-certified-template-conformance"
                if certified_template
                else "genesis.independent-structural-feature-conformance"
                if feature_conformance
                else "genesis.independent-cli-black-box"
                if cli_black_box
                else "genesis.independent-command-check"
            ),
            "source_revision": request.source_revision,
            "created_at": collected_at,
            "input_digests": [candidate.sha256],
            "trace_id": request.run_id,
        },
    )
    return EvidenceItem(
        evidence_id=f"{request.attempt_id}:{observation.name}",
        evaluator=f"genesis.{observation.name}",
        assurance="independent",
        verdict="passed" if observation.passed else "failed",
        output_sha256=output_sha,
        evidence_locator=locator.locator_uri,
        collected_at=collected_at,
        provenance=_provenance(
            request,
            origin=(
                "genesis.kanban-template-conformance-evidence"
                if kanban_template
                else "genesis.certified-template-conformance-evidence"
                if certified_template
                else "genesis.structural-feature-conformance-evidence"
                if feature_conformance
                else "genesis.cli-black-box-evidence"
                if cli_black_box
                else "genesis.command-evidence"
            ),
            created_at=collected_at,
            inputs=(output_sha, locator.locator_sha256, candidate.sha256),
        ),
        details={
            "argv": list(observation.argv),
            "returncode": observation.returncode,
            "timed_out": observation.timed_out,
            "cancelled": observation.cancelled,
            "wall_time_ms": observation.wall_time_ms,
            "output_truncated": observation.output_truncated,
            "containment": dict(observation.containment),
            "candidate_tree_sha256": observation.candidate_tree_sha256,
            **(
                {
                    "assurance_scope": (
                        "certified-kanban-template-model-schema-conformance"
                    ),
                    "runtime_behavior_verified_by_this_item": False,
                    "browser_behavior_verified": False,
                    "limitation": (
                        "Exact approved kanban source identities and fixed-column "
                        "wiring are checked without executing browser interactions."
                    ),
                }
                if kanban_template
                else
                {
                    "assurance_scope": (
                        "certified-template-conformance"
                        if certified_template
                        else "structural-source-conformance"
                    ),
                    "runtime_behavior_verified_by_this_item": False,
                    "browser_behavior_verified": False,
                    "limitation": (
                        "The exact approved app template and expected CONFIG are "
                        "checked without executing browser interactions."
                        if certified_template
                        else "Feature names, definitions, and dispatch are checked "
                        "without executing behavior."
                    ),
                }
                if certified_template or feature_conformance
                else {
                    "assurance_scope": "kernel-owned-cli-black-box",
                    "runtime_behavior_verified_by_this_item": True,
                    "browser_behavior_verified": False,
                }
                if cli_black_box
                else {}
            ),
        },
    )


def _failed_packet(
    *,
    plan: GenesisPlan,
    attempt_sha256: str,
    candidate: ArtifactRef,
    items: Sequence[EvidenceItem],
    collected_at: str,
    wall_time_ms: int,
) -> EvidencePacket:
    return EvidencePacket(
        packet_id=f"evidence-{plan.request.run_id.removeprefix('genesis-')}",
        mission_id=plan.request.mission_id,
        attempt_id=plan.request.attempt_id,
        source_revision=plan.request.source_revision,
        attempt_contract_sha256=attempt_sha256,
        subject_sha256=candidate.sha256,
        evaluation_status="failed",
        items=tuple(items),
        policy_decision_sha256=plan.policy_decision.digest,
        usage=ResourceUsage(wall_time_ms=wall_time_ms),
        candidate_artifact_sha256=candidate.sha256,
        candidate_artifact_locator=candidate.locator,
        provenance=_provenance(
            plan.request,
            origin="genesis.failed-evidence-packet",
            created_at=collected_at,
            inputs=(
                attempt_sha256,
                candidate.sha256,
                plan.policy_decision.digest,
                *(item.output_sha256 for item in items),
            ),
        ),
    )


def _artifact_row(kind: str, ref: ArtifactRef) -> dict[str, str]:
    return {"kind": kind, "sha256": ref.sha256, "locator": ref.locator}


def _mission_summary(plan: GenesisPlan) -> dict[str, Any]:
    return {
        "mission_id": plan.mission.mission_id,
        "objective": plan.mission.objective,
        "work_items": list(plan.mission.work_item_ids),
        "success_criteria": list(plan.mission.success_criteria),
        "policy_sha256": plan.policy.digest,
    }


def _write_rendered_files(
    workspace: Path,
    files: Mapping[str, bytes],
    *,
    max_bytes: int,
    max_files: int,
) -> None:
    if len(files) > max_files or sum(len(value) for value in files.values()) > max_bytes:
        raise GenesisError("materialized project exceeds its admitted file or byte budget")
    root = workspace.resolve(strict=True)
    for relative, payload in sorted(files.items()):
        path = workspace.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        parent = path.parent.resolve(strict=True)
        if parent != root and root not in parent.parents:
            raise GenesisError(f"generated path escaped the workspace: {relative}")
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())


def _fresh_candidate_workspace(
    store: SourceTreeStore,
    candidate: StoredSourceTree,
    *,
    workspace_parent: Path,
    run_id: str,
    label: str,
    max_bytes: int,
) -> Path:
    """Materialize one untouched evaluator input from the captured candidate CAS."""

    if not _is_gate_label(label):
        raise GenesisError("candidate evaluation workspace label is invalid")
    root = workspace_parent.resolve(strict=True)
    parent = workspace_parent / "evaluations" / run_id
    parent.mkdir(parents=True, exist_ok=True)
    resolved_parent = parent.resolve(strict=True)
    if resolved_parent != root and root not in resolved_parent.parents:
        raise GenesisError("candidate evaluation workspace escaped its authority root")
    destination = parent / label
    materialized = store.materialize_tree(
        candidate.ref,
        destination,
        max_file_bytes=max_bytes,
        max_total_bytes=max_bytes,
    )
    if materialized != candidate.manifest:
        raise GenesisError("fresh evaluator workspace differs from candidate CAS")
    return destination


def _is_gate_label(value: object) -> bool:
    text = str(value)
    return (
        1 <= len(text) <= 48
        and text[0] in "abcdefghijklmnopqrstuvwxyz"
        and all(character in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in text)
    )


def _cli_black_box_command(*, search_required: bool) -> tuple[str, ...]:
    source = _CLI_BLACK_BOX_TEMPLATE.replace(
        "@@SEARCH_REQUIRED@@", "True" if search_required else "False"
    )
    return ("python", "-I", "-c", source)


def _read_candidate_text(workspace: Path, relative: str, *, max_bytes: int) -> str:
    """Read one fixed evaluator input without following a candidate link."""

    root = workspace.resolve(strict=True)
    path = workspace / relative
    if path.is_symlink() or not path.is_file():
        raise GenesisError(
            f"feature-conformance input is not a regular file: {relative}"
        )
    resolved = path.resolve(strict=True)
    if resolved.parent != root and root not in resolved.parents:
        raise GenesisError(
            f"feature-conformance input escaped the workspace: {relative}"
        )
    if resolved.stat().st_size > max_bytes:
        raise GenesisError(
            f"feature-conformance input exceeds its read bound: {relative}"
        )
    try:
        return resolved.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise GenesisError(
            f"feature-conformance input is not UTF-8: {relative}"
        ) from exc


def _read_candidate_bytes(workspace: Path, relative: str, *, max_bytes: int) -> bytes:
    """Read one exact evaluator input without text newline normalization."""

    root = workspace.resolve(strict=True)
    path = workspace / relative
    if path.is_symlink() or not path.is_file():
        raise GenesisError(
            f"feature-conformance input is not a regular file: {relative}"
        )
    resolved = path.resolve(strict=True)
    if resolved.parent != root and root not in resolved.parents:
        raise GenesisError(
            f"feature-conformance input escaped the workspace: {relative}"
        )
    size = resolved.stat().st_size
    if size > max_bytes:
        raise GenesisError(
            f"feature-conformance input exceeds its read bound: {relative}"
        )
    payload = resolved.read_bytes()
    if len(payload) != size:
        raise GenesisError(
            f"feature-conformance input changed during its exact read: {relative}"
        )
    return payload


def _expected_web_config(plan: GenesisPlan) -> str:
    identity = json.dumps(
        {
            "features": list(plan.product.features),
            "product_name": plan.request.product_name,
            "prompt": plan.request.prompt,
            "target": plan.request.target,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    identity_sha256 = hashlib.sha256(identity).hexdigest()
    return json.dumps(
        {
            "objective": plan.request.prompt,
            "productName": plan.request.product_name,
            "storageKey": f"genesis-{identity_sha256[:20]}",
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _expected_kanban_config(plan: GenesisPlan) -> str:
    identity = json.dumps(
        {
            "blueprint": KANBAN_BOARD_BLUEPRINT,
            "features": list(plan.product.features),
            "product_name": plan.request.product_name,
            "prompt": plan.request.prompt,
            "schema": "daedalus-genesis-materializer-identity/2",
            "target": plan.request.target,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    identity_sha256 = hashlib.sha256(identity).hexdigest()
    return json.dumps(
        {
            "objective": plan.request.prompt,
            "productName": plan.request.product_name,
            "storageKey": f"genesis-kanban-{identity_sha256[:20]}",
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _kanban_conformance_observation(
    plan: GenesisPlan,
    *,
    candidate_tree_sha256: str,
    workspace: Path,
) -> _CommandObservation:
    started = time.monotonic()
    checks: dict[str, bool] = {}
    error: str | None = None
    observed_template_sha256: str | None = None
    observed_model_sha256: str | None = None
    observed_schema_sha256: str | None = None
    search_required = "search and filter cards" in plan.product.features
    try:
        page_payload = _read_candidate_bytes(
            workspace,
            "index.html",
            max_bytes=plan.policy.max_bytes,
        )
        source_payload = _read_candidate_bytes(
            workspace,
            "app.js",
            max_bytes=plan.policy.max_bytes,
        )
        model_payload = _read_candidate_bytes(
            workspace,
            "model.py",
            max_bytes=plan.policy.max_bytes,
        )
        schema_payload = _read_candidate_bytes(
            workspace,
            "schemas/card.schema.json",
            max_bytes=plan.policy.max_bytes,
        )
        page = page_payload.decode("utf-8")
        source = source_payload.decode("utf-8")
        expected_config = _expected_kanban_config(plan)
        exact_marker = f"const CONFIG = Object.freeze({expected_config});"
        if source.count(exact_marker) == 1:
            normalized = source.replace(
                exact_marker,
                "const CONFIG = Object.freeze(@@CONFIG@@);",
                1,
            )
            observed_template_sha256 = hashlib.sha256(
                normalized.encode("utf-8")
            ).hexdigest()
        observed_model_sha256 = hashlib.sha256(model_payload).hexdigest()
        observed_schema_sha256 = hashlib.sha256(schema_payload).hexdigest()
        checks["certified-kanban-app-template"] = (
            observed_template_sha256 == _APPROVED_KANBAN_APP_TEMPLATE_SHA256
        )
        checks["certified-card-model"] = (
            observed_model_sha256 == _APPROVED_KANBAN_MODEL_SHA256
        )
        checks["certified-card-schema"] = (
            observed_schema_sha256 == _APPROVED_KANBAN_SCHEMA_SHA256
        )
        checks["fixed-column-markup"] = all(
            page.count(marker) == 1
            for marker in (
                'data-column="backlog"',
                'data-column="in-progress"',
                'data-column="done"',
                'id="backlog-cards"',
                'id="in-progress-cards"',
                'id="done-cards"',
            )
        )
        checks["card-controls"] = all(
            marker in page
            for marker in ('id="card-form"', 'id="title"', 'id="details"')
        )
        checks["card-functions"] = all(
            f"function {name}" in source
            for name in ("createCard", "deleteCard", "moveCard", "updateCard")
        )
        checks["fixed-column-order"] = (
            "const COLUMNS = Object.freeze(['backlog', 'in-progress', 'done']);"
            in source
        )
        checks["keyboard-move-wiring"] = all(
            marker in source
            for marker in (
                "button('Move Back', 'secondary', () => moveCard(card.id, -1))",
                "button('Move Forward', '', () => moveCard(card.id, 1))",
                "card.column = COLUMNS[next];",
            )
        )
        checks["local-storage"] = "localStorage.setItem" in source
        checks["no-drag-and-drop"] = all(
            marker not in source.casefold()
            for marker in ("dragstart", "draggable", "ondrop")
        )
        if search_required:
            checks["search-control"] = (
                '<label for="filter">Search cards</label>' in page
                and 'id="filter" type="search"' in page
            )
            checks["search-function"] = (
                "function filterCards(cards, query)" in source
                and "cards.filter((card)" in source
            )
            checks["search-wiring"] = (
                "filterCards(state.cards" in source
                and "filterInput.addEventListener('input', render)" in source
            )
        else:
            checks["unrequested-search-control-absent"] = 'id="filter"' not in page
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"[:2000]

    passed = bool(checks) and all(checks.values()) and error is None
    payload: dict[str, Any] = {
        "schema": "daedalus-genesis-kanban-template-conformance/1",
        "blueprint": KANBAN_BOARD_BLUEPRINT,
        "approved_app_template_sha256": _APPROVED_KANBAN_APP_TEMPLATE_SHA256,
        "approved_model_sha256": _APPROVED_KANBAN_MODEL_SHA256,
        "approved_schema_sha256": _APPROVED_KANBAN_SCHEMA_SHA256,
        "assurance_scope": "certified-kanban-template-model-schema-conformance",
        "browser_behavior_verified": False,
        "candidate_tree_sha256": candidate_tree_sha256,
        "checks": dict(sorted(checks.items())),
        "observed_normalized_app_template_sha256": observed_template_sha256,
        "observed_model_sha256": observed_model_sha256,
        "observed_schema_sha256": observed_schema_sha256,
        "product_spec_sha256": plan.product.digest,
        "required_features": list(plan.product.features),
        "runtime_behavior_verified_by_this_check": False,
        "target": plan.request.target,
        "target_fourfold_spec_sha256": plan.target_spec.digest,
    }
    if error is not None:
        payload["error"] = error
    return _CommandObservation(
        name="kanban_template_conformance",
        candidate_tree_sha256=candidate_tree_sha256,
        argv=("kernel", "verify_certified_kanban_template"),
        returncode=0 if passed else 1,
        output=canonical_json(payload),
        output_truncated=False,
        timed_out=False,
        cancelled=False,
        wall_time_ms=max(0, int(round((time.monotonic() - started) * 1000))),
        containment={
            "contained": True,
            "mechanism": (
                "in-process kernel-owned read-only certified kanban template, "
                "model, schema, and markup inspector"
            ),
        },
    )


def _feature_conformance_observation(
    plan: GenesisPlan,
    *,
    candidate_tree_sha256: str,
    workspace: Path,
) -> _CommandObservation:
    """Independently inspect the bounded ProductSpec's source-level surface.

    Candidate-authored tests are useful build evidence, but they do not decide
    whether the expected feature structure exists. This evaluator lives
    outside the candidate workspace and derives its checks from the admitted
    ProductSpec. It checks local CRUD and optional title/details search controls,
    definitions, and wiring. It deliberately does not claim that a browser
    interaction was executed or that feature behavior was independently proven.
    """

    if plan.request.blueprint == KANBAN_BOARD_BLUEPRINT:
        return _kanban_conformance_observation(
            plan,
            candidate_tree_sha256=candidate_tree_sha256,
            workspace=workspace,
        )
    if plan.request.blueprint != ITEM_COLLECTION_BLUEPRINT:
        raise GenesisError(
            f"unsupported Genesis conformance blueprint: {plan.request.blueprint!r}"
        )

    started = time.monotonic()
    checks: dict[str, bool] = {}
    error: str | None = None
    observed_template_sha256: str | None = None
    search_required = "search and filter items" in plan.product.features
    try:
        if plan.request.target == "cli":
            source = _read_candidate_text(
                workspace,
                "app.py",
                max_bytes=plan.policy.max_bytes,
            )
            tree = ast.parse(source, filename="app.py")
            functions = {
                node.name
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            checks["crud-functions"] = {
                "add",
                "delete",
                "items",
                "toggle",
                "update",
            }.issubset(functions)
            if search_required:
                checks["search-function"] = "search" in functions
                checks["search-command"] = any(
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "add_parser"
                    and bool(node.args)
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "search"
                    for node in ast.walk(tree)
                )
                main = next(
                    (
                        node
                        for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == "main"
                    ),
                    None,
                )
                checks["search-dispatch"] = main is not None and any(
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "search"
                    for node in ast.walk(main)
                )
        else:
            page = _read_candidate_text(
                workspace,
                "index.html",
                max_bytes=plan.policy.max_bytes,
            )
            source = _read_candidate_text(
                workspace,
                "app.js",
                max_bytes=plan.policy.max_bytes,
            )
            expected_config = _expected_web_config(plan)
            exact_marker = f"const CONFIG = Object.freeze({expected_config});"
            if source.count(exact_marker) == 1:
                normalized = source.replace(
                    exact_marker,
                    "const CONFIG = Object.freeze(@@CONFIG@@);",
                    1,
                )
                observed_template_sha256 = hashlib.sha256(
                    normalized.encode("utf-8")
                ).hexdigest()
            checks["certified-web-app-template"] = (
                observed_template_sha256 == _APPROVED_WEB_APP_TEMPLATE_SHA256
            )
            checks["crud-controls"] = all(
                marker in page
                for marker in (
                    'id="item-form"',
                    'id="title"',
                    'id="details"',
                    'id="items"',
                )
            )
            checks["crud-functions"] = all(
                f"function {name}" in source
                for name in (
                    "createItem",
                    "deleteItem",
                    "toggleItem",
                    "updateItem",
                )
            )
            if search_required:
                checks["search-control"] = (
                    '<label for="filter">Search items</label>' in page
                    and 'id="filter" type="search"' in page
                )
                checks["search-function"] = (
                    "function filterItems(items, query)" in source
                    and "items.filter((item)" in source
                )
                checks["search-wiring"] = (
                    "filterItems(state.items" in source
                    and "filterInput.addEventListener('input', render)" in source
                )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"[:2000]

    passed = bool(checks) and all(checks.values()) and error is None
    web_target = plan.request.target != "cli"
    observation_name = (
        "certified_template_conformance" if web_target else "feature_conformance"
    )
    payload: dict[str, Any] = {
        "schema": (
            "daedalus-genesis-certified-template-conformance/1"
            if web_target
            else "daedalus-genesis-structural-feature-conformance/1"
        ),
        "approved_web_app_template_sha256": (
            _APPROVED_WEB_APP_TEMPLATE_SHA256 if web_target else None
        ),
        "assurance_scope": (
            "certified-template-conformance"
            if web_target
            else "structural-source-conformance"
        ),
        "browser_behavior_verified": False,
        "candidate_tree_sha256": candidate_tree_sha256,
        "checks": dict(sorted(checks.items())),
        "observed_normalized_web_app_template_sha256": observed_template_sha256,
        "product_spec_sha256": plan.product.digest,
        "required_features": list(plan.product.features),
        "runtime_behavior_verified_by_this_check": False,
        "target": plan.request.target,
        "target_fourfold_spec_sha256": plan.target_spec.digest,
    }
    if error is not None:
        payload["error"] = error
    return _CommandObservation(
        name=observation_name,
        candidate_tree_sha256=candidate_tree_sha256,
        argv=(
            "kernel",
            (
                "verify_certified_web_template"
                if web_target
                else "verify_structural_feature_conformance"
            ),
        ),
        returncode=0 if passed else 1,
        output=canonical_json(payload),
        output_truncated=False,
        timed_out=False,
        cancelled=False,
        wall_time_ms=max(0, int(round((time.monotonic() - started) * 1000))),
        containment={
            "contained": True,
            "mechanism": (
                "in-process kernel-owned read-only certified-template inspector"
                if web_target
                else "in-process kernel-owned read-only structural "
                "feature-conformance inspector"
            ),
        },
    )


def _failure_result(
    plan: GenesisPlan,
    *,
    reason: str,
    artifacts: Mapping[str, Any] | None = None,
    candidate: Mapping[str, Any] | None = None,
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "run_id": plan.request.run_id,
        "request_key": plan.request.request_key,
        "status": "failed",
        "target": plan.request.target,
        "defaults": dict(plan.request.defaults),
        "blockers": [reason, *plan.request.notices],
        "mission": _mission_summary(plan),
        "candidate": candidate,
        "evidence": evidence,
        "roundtrip": None,
        "preview": None,
        "artifacts": dict(artifacts or {}),
        "publication": {
            "status": "not-requested",
            "owner_approval_required": True,
        },
    }


def _persist_report(store: SourceTreeStore, result: Mapping[str, Any]) -> ArtifactRef:
    payload = canonical_json(dict(result)).encode("ascii")
    if len(payload) > MAX_REPORT_BYTES:
        raise GenesisError("Genesis terminal report exceeds its canonical read bound")
    return store.put_bytes(payload)


def _genesis_operation_sha(
    request: GenesisRequest,
    bound: BoundGenesisPlan,
    files: Mapping[str, bytes],
) -> str:
    """Bind a lease to stable operation material, never invocation timestamps."""

    toolchain = bound.toolchain
    rendered_files = [
        {
            "path": path,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        }
        for path, payload in sorted(files.items())
    ]
    commands = {
        "build": list(toolchain.build_command),
        "package": list(toolchain.package_command),
        "run": list(toolchain.run_command),
        "test": list(toolchain.test_command),
    }
    if request.blueprint == ITEM_COLLECTION_BLUEPRINT:
        return canonical_sha(
            {
                "schema": "daedalus-genesis-operation/1",
                "run_id": request.run_id,
                "source_revision": request.source_revision,
                "target": request.target,
                "stack": request.stack,
                "rendered_files": rendered_files,
                "commands": commands,
                "python_version": toolchain.versions["python"],
                "evaluator_sha256": _EVALUATOR_SHA256,
                "max_command_output_bytes": MAX_COMMAND_OUTPUT_BYTES,
                "max_report_bytes": MAX_REPORT_BYTES,
                "timeout_s": GENESIS_TIMEOUT_S,
            }
        )
    if request.blueprint != KANBAN_BOARD_BLUEPRINT:
        raise GenesisError(
            f"unsupported Genesis operation blueprint: {request.blueprint!r}"
        )
    return canonical_sha(
        {
            "schema": "daedalus-genesis-kanban-operation/1",
            "blueprint": request.blueprint,
            "run_id": request.run_id,
            "source_revision": request.source_revision,
            "target": request.target,
            "stack": request.stack,
            "rendered_files": rendered_files,
            "commands": commands,
            "python_version": toolchain.versions["python"],
            "evaluator_sha256": _KANBAN_EVALUATOR_SHA256,
            "max_command_output_bytes": MAX_COMMAND_OUTPUT_BYTES,
            "max_report_bytes": MAX_REPORT_BYTES,
            "timeout_s": GENESIS_TIMEOUT_S,
        }
    )


def _settle_committed_genesis_effect(
    granted: WaveOffloadLease,
    effect_start: Any,
    execution: Any,
    *,
    outcome: str,
    output_digests: Sequence[str],
    detail_sha256: str,
) -> bool:
    """Best-effort reconcile the outer effect after the Attempt is canonical.

    The Attempt terminal receipt is the product commit.  Once it exists, a
    transient outer-ledger or retention failure must not rewrite that fact as a
    different failure report for the first caller.  Retry the idempotent effect
    terminal once and retain what can be retained; a process crash between the
    two commits remains explicit reconciliation debt.
    """

    terminalized = False
    for _attempt in range(2):
        try:
            granted.authorization.finish_effect(
                effect_start.receipt,
                outcome=outcome,
                output_digests=tuple(output_digests),
                detail_sha256=detail_sha256,
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


def run_genesis(
    prompt: object,
    *,
    target: object | None = None,
    stack: object | None = None,
    request_key: object | None = None,
    repo_root: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Build one isolated, evidenced candidate or return a structured refusal."""

    request = normalize_genesis_request(
        prompt,
        target=target,
        stack=stack,
        request_key=request_key,
    )
    created_at = _utc_now()
    if not request.admitted:
        return _blocked_result(request, created_at=created_at)

    authority_root = Path.cwd() if repo_root is None else Path(repo_root)
    paths = _state_paths(authority_root, request)
    # This immutable lookup is an effect-free optimisation.  During an active
    # writer it can intentionally miss the WAL or observe a main database that
    # predates the Attempt schema.  Treat that transient projection as a miss;
    # the admitted, serial post-lock read below is authoritative and still
    # surfaces any stable corruption.  Likewise, never return a transient
    # pending projection while the slot owner may be about to commit.
    try:
        existing = _read_existing(paths, request)
    except (AttemptStateError, GenesisReconciliationError):
        existing = None
    if existing is not None and existing.get("status") != "running":
        return existing

    plan = build_genesis_plan(request, created_at=created_at)
    render_kwargs: dict[str, Any] = {"features": request.features}
    if request.blueprint == KANBAN_BOARD_BLUEPRINT:
        render_kwargs["blueprint"] = request.blueprint
    files = render_project(
        request.prompt,
        product_name=request.product_name,
        target=request.target,
        **render_kwargs,
    )
    empty_tree = _empty_input_tree(plan, created_at=created_at)
    bound = bind_genesis_attempt(
        plan,
        input_tree=empty_tree.ref,
        expected_outputs=tuple(files),
        python_version=".".join(str(part) for part in sys.version_info[:3]),
        created_at=created_at,
    )
    operation_sha = _genesis_operation_sha(request, bound, files)

    try:
        genesis_control = _ensure_genesis_switch(paths.repo_root, request.run_id)
    except GenesisError as exc:
        return {
            **_failure_result(plan, reason=str(exc)),
            "status": "blocked",
            "admission": {
                "effect_started": False,
                "genesis_control": "blocked",
            },
        }
    switch = genesis_control.switch

    try:
        granted = acquire_effect_lease(
            paths.repo_root,
            entrypoint_id=ENTRYPOINT_ID,
            source_revision=request.source_revision,
            mission_id=request.mission_id,
            attempt_id=request.attempt_id,
            positions=1,
            writable_paths=(".",),
            tools=("python",),
            max_spend_usd=None,
            timeout_s=GENESIS_TIMEOUT_S,
            contained=True,
            containment_evidence=(
                "IsolatedAttemptCoordinator materializes one exact empty CAS tree "
                "below the checkout-external Genesis workspace parent"
            ),
            write_policy=Policy(write_allow=(".",)),
            switch=switch,
            trace_id=request.run_id,
            evidence_root=paths.effect_evidence,
            subject_root=paths.repo_root,
            worktree_root=paths.workspace_parent,
            operation_sha256=operation_sha,
        )
    except BaseException:
        genesis_control.close()
        raise
    if isinstance(granted, WaveLeaseDenied):
        genesis_control.close()
        return {
            **_failure_result(
                plan,
                reason="; ".join(granted.reasons),
            ),
            "status": "blocked",
            "admission": {"effect_lease": granted.receipt(), "effect_started": False},
        }
    if not isinstance(granted, WaveOffloadLease):
        genesis_control.close()
        raise GenesisError("effect issuer returned an unknown result")

    try:
        execution = granted.execution_for(
            0,
            writable_paths=(".",),
            tools=("python",),
            operation_sha256=operation_sha,
        )
        invocation_effect_identity = _invocation_effect_identity(
            granted,
            execution,
            request,
            operation_sha256=operation_sha,
        )
        effect_start = granted.authorization.begin_effect(execution)
    except BaseException:
        genesis_control.close()
        raise

    # Normal mode=ro can see a live WAL and may create SQLite sidecars.  It is
    # therefore deliberately dominated by the fresh, stable-operation-bound
    # invocation lease and its durable begin_effect, while the shared slot
    # prevents another Genesis/Ariadne writer from changing underneath it.
    try:
        existing = _read_existing(paths, request, immutable=False)
    except BaseException as exc:
        if effect_start.execute:
            _settle_committed_genesis_effect(
                granted,
                effect_start,
                execution,
                outcome="FAILED",
                output_digests=(),
                detail_sha256=canonical_sha(
                    {"error_type": type(exc).__name__, "error": str(exc)}
                ),
            )
        genesis_control.close()
        raise
    if existing is not None:
        if effect_start.execute:
            settled = _settle_committed_genesis_effect(
                granted,
                effect_start,
                execution,
                outcome=(
                    "COMPLETED"
                    if existing.get("status") in {"preview-ready", "succeeded"}
                    else "FAILED"
                ),
                output_digests=_invocation_effect_output_digests(existing),
                detail_sha256=canonical_sha(existing),
            )
            if not settled:
                genesis_control.close()
                raise GenesisError(
                    "Genesis replay is canonical but its invocation effect needs "
                    "ledger/evidence reconciliation"
                )
        genesis_control.close()
        return existing
    if not effect_start.execute:
        genesis_control.close()
        raise GenesisError(
            "fresh Genesis invocation effect is already terminal or pending"
        )

    source_store: SourceTreeStore | None = None
    ledger: AttemptLedger | None = None
    prepared = None
    candidate_tree: StoredSourceTree | None = None
    report_ref: ArtifactRef | None = None
    effect_finished = False
    attempt_committed = False
    watch_started = False
    started = time.monotonic()
    try:
        switch.start_watch()
        watch_started = True
        switch.checkpoint()
        paths.workspace_parent.mkdir(parents=True, exist_ok=True)
        source_store = SourceTreeStore(paths.source_store)
        persisted_empty = source_store.put_bytes(empty_tree.manifest.to_json().encode("ascii"))
        if persisted_empty != empty_tree.ref:
            raise GenesisError("persisted empty source tree changed identity")

        ledger = AttemptLedger(paths.spine_db, source_store)
        coordinator = IsolatedAttemptCoordinator(
            primary_checkout=paths.repo_root,
            workspace_parent=paths.workspace_parent,
            source_store=source_store,
            ledger=ledger,
        )
        prepared = coordinator.prepare(
            bound.attempt,
            empty_tree,
            start_id=f"start-{request.run_id.removeprefix('genesis-')}",
        )
        if not prepared.begin.execute:
            if prepared.begin.completion is not None:
                attempt_committed = True
                report = source_store.read_bytes(
                    prepared.begin.completion.receipt.report,
                    max_bytes=MAX_REPORT_BYTES,
                )
                replay = _strict_report(report)
                if replay.get("run_id") != request.run_id:
                    raise GenesisError("persisted Genesis report belongs to another run")
                _verify_terminal_genesis_chain(
                    paths,
                    source_store,
                    request,
                    prepared.begin,
                    replay,
                )
                _require_invocation_effect_terminal(
                    paths,
                    replay,
                    attempt_id=request.attempt_id,
                    source_revision=prepared.begin.start.source_revision,
                )
                settled = _settle_committed_genesis_effect(
                    granted,
                    effect_start,
                    execution,
                    outcome=(
                        "COMPLETED"
                        if replay.get("status") in {"preview-ready", "succeeded"}
                        else "FAILED"
                    ),
                    output_digests=_invocation_effect_output_digests(replay),
                    detail_sha256=canonical_sha(replay),
                )
                if not settled:
                    raise GenesisError(
                        "Genesis replay is canonical but its invocation effect needs "
                        "ledger/evidence reconciliation"
                    )
                effect_finished = True
                return replay
            raise GenesisError("Attempt is pending reconciliation and was not replayed")
        assert prepared.workspace is not None

        _write_rendered_files(
            prepared.workspace,
            files,
            max_bytes=plan.policy.max_bytes,
            max_files=plan.policy.max_files,
        )
        # Candidate identity is fixed before any candidate-authored test or
        # runtime receives a writable directory. Every following gate starts
        # from a separate materialization of these exact CAS bytes.
        candidate_created_at = _utc_now()
        candidate_tree = source_store.capture_tree(
            prepared.workspace,
            tree_id=f"candidate-{request.run_id.removeprefix('genesis-')}",
            source_revision=request.source_revision,
            origin="genesis.candidate-source-tree",
            created_at=candidate_created_at,
            trace_id=request.run_id,
            ignored_roots=MANDATORY_IGNORED_ROOTS,
            max_file_bytes=plan.policy.max_bytes,
            max_total_bytes=plan.policy.max_bytes,
        )

        command_observations_list: list[_CommandObservation] = []
        for name, command, task_id in (
            ("build", bound.toolchain.build_command, plan.work_item_ids[3]),
            ("test", bound.toolchain.test_command, plan.work_item_ids[4]),
            ("runtime", bound.toolchain.run_command, plan.work_item_ids[5]),
            ("package", bound.toolchain.package_command, plan.work_item_ids[6]),
        ):
            gate_workspace = _fresh_candidate_workspace(
                source_store,
                candidate_tree,
                workspace_parent=paths.workspace_parent,
                run_id=request.run_id,
                label=name,
                max_bytes=plan.policy.max_bytes,
            )
            command_observations_list.append(
                _run_command(
                    name,
                    command,
                    task_id=task_id,
                    candidate_tree_sha256=candidate_tree.ref.sha256,
                    workspace=gate_workspace,
                    switch=switch,
                    timeout_s=30,
                )
            )

        if request.target == "cli":
            cli_workspace = _fresh_candidate_workspace(
                source_store,
                candidate_tree,
                workspace_parent=paths.workspace_parent,
                run_id=request.run_id,
                label="cli-black-box",
                max_bytes=plan.policy.max_bytes,
            )
            command_observations_list.append(
                _run_command(
                    "cli_black_box",
                    _cli_black_box_command(
                        search_required=(
                            "search and filter items" in plan.product.features
                        )
                    ),
                    task_id=plan.work_item_ids[4],
                    candidate_tree_sha256=candidate_tree.ref.sha256,
                    workspace=cli_workspace,
                    switch=switch,
                    timeout_s=30,
                )
            )

        command_observations = tuple(command_observations_list)
        conformance_workspace = _fresh_candidate_workspace(
            source_store,
            candidate_tree,
            workspace_parent=paths.workspace_parent,
            run_id=request.run_id,
            label="feature-conformance",
            max_bytes=plan.policy.max_bytes,
        )
        feature_conformance_observation = _feature_conformance_observation(
            plan,
            candidate_tree_sha256=candidate_tree.ref.sha256,
            workspace=conformance_workspace,
        )
        observations = (*command_observations, feature_conformance_observation)
        collected_at = _utc_now()
        artifact_store = ArtifactStore(paths.evidence_store)
        command_items = tuple(
            _evidence_item(
                observation,
                request=request,
                candidate=candidate_tree.ref,
                store=artifact_store,
                collected_at=collected_at,
            )
            for observation in observations
        )
        wall_time_ms = max(0, int(round((time.monotonic() - started) * 1000)))

        compile_error: str | None = None
        compiled = None
        try:
            fourfold_workspace = _fresh_candidate_workspace(
                source_store,
                candidate_tree,
                workspace_parent=paths.workspace_parent,
                run_id=request.run_id,
                label="fourfold",
                max_bytes=plan.policy.max_bytes,
            )
            compiled = compile_reference_project(
                fourfold_workspace,
                source_revision=request.source_revision,
                created_at=collected_at,
                trace_id=request.run_id,
                source_tree_sha256=candidate_tree.ref.sha256,
            )
        except Exception as exc:  # retained as negative evidence below
            compile_error = f"{type(exc).__name__}: {exc}"

        all_commands_passed = all(item.verdict == "passed" for item in command_items)
        if compiled is not None and all_commands_passed:
            packet = assemble_fourfold_evidence_packet(
                snapshot=compiled.snapshot,
                candidate_artifact_sha256=candidate_tree.ref.sha256,
                candidate_artifact_locator=candidate_tree.ref.locator,
                packet_id=f"evidence-{request.run_id.removeprefix('genesis-')}",
                mission_id=request.mission_id,
                attempt_id=request.attempt_id,
                attempt_contract_sha256=bound.attempt.digest,
                policy_decision_sha256=plan.policy_decision.digest,
                collected_at=collected_at,
                usage=ResourceUsage(wall_time_ms=wall_time_ms),
                trace_id=request.run_id,
                extra_items=command_items,
                store=artifact_store,
            )
        else:
            failure_items = list(command_items)
            if compile_error is not None:
                failure_observation = _CommandObservation(
                    name="fourfold",
                    candidate_tree_sha256=candidate_tree.ref.sha256,
                    argv=("kernel", "compile_reference_project"),
                    returncode=1,
                    output=compile_error,
                    output_truncated=False,
                    timed_out=False,
                    cancelled=False,
                    wall_time_ms=0,
                    containment={
                        "contained": True,
                        "mechanism": "in-process kernel evaluator",
                    },
                )
                failure_items.append(
                    _evidence_item(
                        failure_observation,
                        request=request,
                        candidate=candidate_tree.ref,
                        store=artifact_store,
                        collected_at=collected_at,
                    )
                )
            packet = _failed_packet(
                plan=plan,
                attempt_sha256=bound.attempt.digest,
                candidate=candidate_tree.ref,
                items=failure_items,
                collected_at=collected_at,
                wall_time_ms=wall_time_ms,
            )

        contract_refs: dict[str, ArtifactRef] = {
            "autonomy_policy": _store_contract(source_store, plan.policy),
            "runtime_manifest": _store_contract(source_store, plan.runtime_manifest),
            "build_intent": _store_contract(source_store, plan.intent),
            "product_spec": _store_contract(source_store, plan.product),
            "policy_decision": _store_contract(source_store, plan.policy_decision),
            "design_contract": _store_contract(source_store, plan.design),
            "target_fourfold": _store_contract(source_store, plan.target_spec),
            "graph_proposal": _store_contract(source_store, plan.graph),
            "mission": _store_contract(source_store, plan.mission),
            "materialization_plan": _store_contract(source_store, bound.materialization),
            "toolchain_manifest": _store_contract(source_store, bound.toolchain),
            "attempt": _store_contract(source_store, bound.attempt),
        }
        packet_ref = _store_contract(source_store, packet)
        contract_refs["evidence"] = packet_ref

        round_trip = None
        round_trip_ref = None
        if compiled is not None:
            actual_ref = _store_contract(source_store, compiled.snapshot)
            observation_by_name = {row.name: row for row in observations}
            checks = {
                "build": observation_by_name["build"].passed,
                "code": compiled.snapshot.plane_map["code"].status == "complete",
                "containment": all(
                    observation.containment.get("contained") is True
                    for observation in observations
                ),
                "data": compiled.snapshot.plane_map["data"].status == "complete",
                "knowledge": compiled.snapshot.plane_map["knowledge"].status == "complete",
                "package": observation_by_name["package"].passed,
                "runtime": observation_by_name["runtime"].passed,
                feature_conformance_observation.name: (
                    feature_conformance_observation.passed
                ),
                "test": observation_by_name["test"].passed,
                "type": compiled.snapshot.plane_map["type"].status == "complete",
            }
            if request.target == "cli":
                checks["cli_black_box"] = observation_by_name["cli_black_box"].passed
            mismatches = tuple(
                f"{name} check failed" for name, passed in checks.items() if not passed
            )
            evaluator_sha256 = _evaluator_sha256(request.blueprint)
            round_trip = RoundTripReport(
                report_id=f"roundtrip-{request.run_id.removeprefix('genesis-')}",
                lineage_id=request.lineage_id,
                mission_id=request.mission_id,
                source_revision=request.source_revision,
                candidate_tree=candidate_tree.ref,
                actual_fourfold=actual_ref,
                target_fourfold_spec_sha256=plan.target_spec.digest,
                evaluator_sha256=evaluator_sha256,
                evidence_packet_sha256=packet.digest,
                checks=checks,
                status="passed" if all(checks.values()) else "failed",
                mismatches=mismatches,
                provenance=_provenance(
                    request,
                    origin="genesis.roundtrip",
                    created_at=collected_at,
                    inputs=(
                        candidate_tree.ref.sha256,
                        actual_ref.sha256,
                        plan.target_spec.digest,
                        evaluator_sha256,
                        packet.digest,
                    ),
                ),
            )
            round_trip_ref = _store_contract(source_store, round_trip)
            contract_refs["actual_fourfold"] = actual_ref
            contract_refs["roundtrip"] = round_trip_ref

        green = packet.evaluation_status == "passed" and (
            round_trip is not None and round_trip.status == "passed"
        )
        status = (
            "succeeded"
            if green and request.target == "cli"
            else "preview-ready"
            if green
            else "failed"
        )
        run_record = GenesisRunRecord(
            run_id=request.run_id,
            lineage_id=request.lineage_id,
            mission_id=request.mission_id,
            source_revision=request.source_revision,
            policy_sha256=plan.policy.digest,
            product_spec_sha256=plan.product.digest,
            mission_contract_sha256=plan.mission.digest,
            status=status,
            work_item_ids=plan.work_item_ids,
            attempt_ids=(request.attempt_id,),
            repair_count=0,
            candidate_tree=candidate_tree.ref,
            evidence_packet_sha256=packet.digest,
            round_trip_report_sha256=(
                round_trip.digest if round_trip is not None else None
            ),
            provenance=_provenance(
                request,
                origin="genesis.run-record",
                created_at=collected_at,
                inputs=(
                    plan.policy.digest,
                    plan.product.digest,
                    plan.mission.digest,
                    candidate_tree.ref.sha256,
                    packet.digest,
                    *((round_trip.digest,) if round_trip is not None else ()),
                ),
            ),
        )
        run_ref = _store_contract(source_store, run_record)
        contract_refs["run_record"] = run_ref

        candidate_row = {
            **_artifact_row("candidate source tree", candidate_tree.ref),
            "files": [entry.path for entry in candidate_tree.manifest.entries],
        }
        evidence_row = {
            **_artifact_row("evidence packet", packet_ref),
            "status": packet.evaluation_status,
            "checks": [item.evidence_id for item in packet.items],
            "candidate_tree_sha256": candidate_tree.ref.sha256,
        }
        feature_assurance = _feature_assurance(
            request.blueprint,
            request.target,
            round_trip,
        )
        roundtrip_row = (
            {
                **_artifact_row("round-trip report", round_trip_ref),
                "status": round_trip.status,
                "checks": dict(round_trip.checks),
                "feature_assurance": feature_assurance,
            }
            if round_trip is not None and round_trip_ref is not None
            else {"status": "failed", "error": compile_error}
        )
        result = {
            "run_id": request.run_id,
            "request_key": request.request_key,
            "status": status,
            "target": request.target,
            "defaults": dict(request.defaults),
            "blockers": (
                list(request.notices)
                if green
                else [
                    *(f"{row.name} check failed" for row in observations if not row.passed),
                    *((compile_error,) if compile_error else ()),
                    *request.notices,
                ]
            ),
            "mission": _mission_summary(plan),
            "candidate": candidate_row,
            "evidence": evidence_row,
            "roundtrip": roundtrip_row,
            "preview": (
                {
                    "kind": "read-only-cas-preview",
                    "path": f"/api/genesis/{request.run_id}/preview/",
                }
                if status == "preview-ready"
                else None
            ),
            "artifacts": {
                name: _artifact_row(name.replace("_", " "), ref)
                for name, ref in sorted(contract_refs.items())
            },
            "invocation_effect": _invocation_effect_binding(
                invocation_effect_identity,
                expected_terminal_state="completed" if green else "failed",
            ),
            "publication": {
                "status": "not-requested",
                "owner_approval_required": True,
                "automatic_promotion": False,
            },
        }
        report_ref = _persist_report(source_store, result)
        ledger.complete(
            prepared.begin.start,
            receipt_id=f"terminal-{request.run_id.removeprefix('genesis-')}",
            outcome="succeeded" if green else "failed",
            report=report_ref,
            candidate_tree=candidate_tree,
        )
        attempt_committed = True
        settled = _settle_committed_genesis_effect(
            granted,
            effect_start,
            execution,
            outcome="COMPLETED" if green else "FAILED",
            output_digests=_invocation_effect_output_digests(result),
            detail_sha256=run_ref.sha256,
        )
        if not settled:
            raise GenesisError(
                "Genesis Attempt is canonical but its outer effect needs "
                "ledger/evidence reconciliation"
            )
        effect_finished = True
        return result
    except Exception as exc:
        if attempt_committed:
            # Never manufacture a second terminal truth after the canonical
            # Attempt commit.  The caller sees explicit reconciliation debt;
            # an exact Attempt replay remains available.
            raise
        reason = f"{type(exc).__name__}: {exc}"
        result = _failure_result(plan, reason=reason)
        result["invocation_effect"] = _invocation_effect_binding(
            invocation_effect_identity,
            expected_terminal_state="failed",
        )
        if source_store is None:
            source_store = SourceTreeStore(paths.source_store)
        report_ref = _persist_report(source_store, result)
        failure_committed = False
        failure_commit_error: Exception | None = None
        if ledger is not None and prepared is not None and prepared.begin.execute:
            try:
                ledger.complete(
                    prepared.begin.start,
                    receipt_id=f"terminal-{request.run_id.removeprefix('genesis-')}",
                    outcome="failed",
                    report=report_ref,
                    candidate_tree=candidate_tree,
                )
            except Exception as completion_exc:
                failure_commit_error = completion_exc
            else:
                attempt_committed = True
                failure_committed = True
        if not effect_finished:
            if failure_committed:
                settled = _settle_committed_genesis_effect(
                    granted,
                    effect_start,
                    execution,
                    outcome="FAILED",
                    output_digests=_invocation_effect_output_digests(result),
                    detail_sha256=report_ref.sha256,
                )
                if not settled:
                    raise GenesisReconciliationError(
                        "Genesis failed Attempt is canonical but its outer effect "
                        "needs ledger/evidence reconciliation"
                    )
                effect_finished = True
            elif failure_commit_error is not None:
                raise GenesisReconciliationError(
                    "Genesis failure report exists but its Attempt terminal receipt "
                    "could not be committed"
                ) from failure_commit_error
            else:
                try:
                    granted.authorization.finish_effect(
                        effect_start.receipt,
                        outcome="FAILED",
                        output_digests=(report_ref.sha256,),
                        detail_sha256=report_ref.sha256,
                    )
                    effect_finished = True
                    granted.retain_terminal_record(execution)
                except Exception as settlement_exc:
                    raise GenesisReconciliationError(
                        "Genesis failure report could not retain its outer terminal "
                        "effect record"
                    ) from settlement_exc
        return result
    finally:
        try:
            if watch_started:
                switch.stop_watch()
        finally:
            try:
                if ledger is not None and getattr(ledger, "_owns_spine", False):
                    ledger.spine.close()
            finally:
                # Cleanup failures above must never strand the repository-local
                # Genesis/Ariadne execution mutex.
                genesis_control.close()


@dataclass(frozen=True)
class _VerifiedGenesisCandidate:
    store: SourceTreeStore
    manifest: SourceTreeManifest
    manifest_bytes: bytes
    report_bytes: bytes


def _read_verified_genesis_candidate(
    run_id: str,
    *,
    repo_root: str | os.PathLike[str] | None,
    preview_only: bool,
    candidate_sha256: str | None = None,
) -> _VerifiedGenesisCandidate:
    """Resolve the existing Attempt, CAS and effect chain without a writer."""

    if not isinstance(run_id, str) or not re_fullmatch_run_id(run_id):
        raise GenesisPreviewError("invalid Genesis run id")
    suffix = run_id.removeprefix("genesis-")
    request_stub = GenesisRequest(
        prompt="preview",
        target="web",
        stack="python-stdlib",
        request_key="preview",
        source_revision="0" * 40,
        run_id=run_id,
        lineage_id=f"lineage-{suffix}",
        mission_id=f"mission-{suffix}",
        attempt_id=f"attempt-{suffix}",
        product_name="Preview",
        features=("preview",),
        target_required=False,
        stack_required=False,
        requested_target=None,
        requested_stack=None,
        defaults={},
        blockers=(),
        notices=(),
    )
    try:
        authority_root = Path.cwd() if repo_root is None else Path(repo_root)
        paths = _state_paths(authority_root, request_stub)
        if not paths.source_store.is_dir() or not paths.spine_db.is_file():
            raise GenesisPreviewError("Genesis run does not exist")
        store = SourceTreeStore.open_existing(paths.source_store)
        existing = AttemptLedger.lookup_read_only(
            paths.spine_db,
            store,
            request_stub.attempt_id,
        )
        if existing is None or existing.completion is None:
            raise GenesisPreviewError("Genesis run is not terminal")
        receipt = existing.completion.receipt
        if receipt.outcome != "succeeded" or receipt.candidate_tree is None:
            raise GenesisPreviewError("Genesis run has no successful candidate receipt")
        if (
            candidate_sha256 is not None
            and candidate_sha256 != receipt.candidate_tree.sha256
        ):
            raise GenesisPreviewError(
                "Genesis candidate digest does not match its terminal Attempt receipt"
            )
        report_bytes = store.read_bytes(receipt.report, max_bytes=MAX_REPORT_BYTES)
        result = _strict_report(report_bytes)
        statuses = {"preview-ready"} if preview_only else {"preview-ready", "succeeded"}
        if result.get("run_id") != run_id or result.get("status") not in statuses:
            raise GenesisPreviewError(
                "Genesis run has no green preview"
                if preview_only
                else "Genesis run has no successful source candidate"
            )
        candidate = result.get("candidate")
        if not isinstance(candidate, Mapping):
            raise GenesisPreviewError("Genesis candidate is missing")
        try:
            reported_candidate = ArtifactRef.from_sha256(
                str(candidate.get("sha256") or "")
            )
        except ValueError as exc:
            raise GenesisPreviewError("Genesis candidate identity is invalid") from exc
        if reported_candidate != receipt.candidate_tree:
            raise GenesisPreviewError(
                "Genesis report candidate does not match its terminal Attempt receipt"
            )
        manifest = _verify_terminal_genesis_chain(
            paths,
            store,
            request_stub,
            existing,
            result,
        )
        if manifest is None:
            raise GenesisError("Genesis run has no green candidate chain")
        _require_invocation_effect_terminal(
            paths,
            result,
            attempt_id=request_stub.attempt_id,
            source_revision=existing.start.source_revision,
        )
        manifest_bytes = store.read_bytes(
            receipt.candidate_tree, max_bytes=MAX_REPORT_BYTES,
        )
        if manifest_bytes != manifest.to_json().encode("ascii"):
            raise GenesisPreviewError(
                "Genesis candidate manifest bytes changed during verification"
            )
        return _VerifiedGenesisCandidate(store, manifest, manifest_bytes, report_bytes)
    except GenesisPreviewError:
        raise
    except (
        GenesisError,
        SourceTreeStoreError,
        AttemptStateError,
        ArtifactStoreError,
        OSError,
        sqlite3.Error,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise GenesisPreviewError(str(exc)) from exc


def _read_verified_candidate_blob(
    store: SourceTreeStore,
    entry: SourceTreeEntry,
) -> bytes:
    """Recheck exact size and identity on the bytes about to leave the service."""

    try:
        payload = store.read_bytes(
            ArtifactRef.from_sha256(entry.blob_sha256),
            max_bytes=entry.size,
        )
    except (SourceTreeStoreError, OSError, TypeError, ValueError) as exc:
        raise GenesisPreviewError("Genesis candidate blob is unavailable or invalid") from exc
    if (
        len(payload) != entry.size
        or hashlib.sha256(payload).hexdigest() != entry.blob_sha256
    ):
        raise GenesisPreviewError(
            "Genesis candidate blob size or digest changed during verification"
        )
    return payload


def read_genesis_preview(
    run_id: str,
    relative_path: str,
    *,
    repo_root: str | os.PathLike[str] | None = None,
) -> tuple[bytes, str]:
    """Resolve one green web/PWA file directly from its authoritative CAS tree."""

    verified = _read_verified_genesis_candidate(
        run_id, repo_root=repo_root, preview_only=True,
    )
    raw = str(relative_path or "").replace("\\", "/").lstrip("/")
    if raw in {"", "."}:
        raw = "index.html"
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or raw != path.as_posix()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise GenesisPreviewError("preview path is not safe")
    entry = next((row for row in verified.manifest.entries if row.path == raw), None)
    if entry is None:
        raise GenesisPreviewError("preview file does not exist")
    payload = _read_verified_candidate_blob(verified.store, entry)
    media_type = mimetypes.guess_type(raw)[0] or "application/octet-stream"
    if media_type.startswith("text/") or media_type in {
        "application/javascript",
        "application/json",
        "image/svg+xml",
    }:
        media_type += "; charset=utf-8"
    return payload, media_type


def read_genesis_source_archive(
    run_id: str,
    candidate_sha256: str,
    *,
    repo_root: str | os.PathLike[str] | None = None,
) -> bytes:
    """Export an exact verified candidate as a deterministic in-memory ZIP.

    The source-tree manifest remains the candidate identity. The archive is a
    read-only transport representation and carries no deployment or promotion.
    """

    if (
        not isinstance(candidate_sha256, str)
        or len(candidate_sha256) != 64
        or any(character not in "0123456789abcdef" for character in candidate_sha256)
    ):
        raise GenesisPreviewError("invalid Genesis candidate digest")
    verified = _read_verified_genesis_candidate(
        run_id,
        repo_root=repo_root,
        preview_only=False,
        candidate_sha256=candidate_sha256,
    )
    if (
        len(verified.manifest.entries) > GENESIS_MAX_FILES
        or sum(entry.size for entry in verified.manifest.entries) > GENESIS_MAX_BYTES
    ):
        raise GenesisPreviewError("Genesis source archive exceeds its transport bound")
    for entry in verified.manifest.entries:
        path = PurePosixPath(entry.path)
        if (
            path.is_absolute()
            or entry.path != path.as_posix()
            or "\\" in entry.path
            or any(
                part in {"", ".", ".."} or ":" in part or "\x00" in part
                for part in path.parts
            )
        ):
            raise GenesisPreviewError("Genesis source archive path is not safe")
    entries = {f"source/{entry.path}": entry for entry in verified.manifest.entries}
    metadata = {
        "source-tree.json": verified.manifest_bytes,
        "genesis-run.json": verified.report_bytes,
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_STORED) as archive:
        for name in sorted((*entries, *metadata)):
            entry = entries.get(name)
            payload = (
                _read_verified_candidate_blob(verified.store, entry)
                if entry is not None
                else metadata[name]
            )
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.compress_type = zipfile.ZIP_STORED
            mode = 0o755 if entry is not None and entry.executable else 0o644
            info.external_attr = (stat.S_IFREG | mode) << 16
            archive.writestr(info, payload)
    return output.getvalue()


def re_fullmatch_run_id(value: object) -> bool:
    text = str(value)
    return (
        len(text) == len("genesis-") + 24
        and text.startswith("genesis-")
        and all(character in "0123456789abcdef" for character in text[8:])
    )


__all__ = [
    "GenesisConflictError",
    "GenesisError",
    "GenesisPreviewError",
    "read_genesis_preview",
    "read_genesis_source_archive",
    "run_genesis",
]
