"""Restart-safe Campaign lifecycle over the canonical CAS and Event Spine.

This module schedules nothing and promotes nothing.  It freezes an experiment,
records a single durable campaign start, and retains one terminal receipt.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Mapping, TypeVar

from daedalus.kernel.artifacts import ArtifactRef
from daedalus.kernel.attempt_contracts import AttemptTerminalReceipt
from daedalus.kernel.contracts import (
    AttemptContract,
    AttemptReceipt,
    CampaignContract,
    CampaignReceipt,
    ContractProvenance,
    EvidencePacket,
    ExperimentSpec,
    NominationReceipt,
)
from daedalus.kernel.contracts.base import CanonicalContract
from daedalus.kernel.source_trees import (
    SourceTreeManifest,
    SourceTreeStore,
    SourceTreeStoreError,
)
from daedalus.spine.envelope import canonical_json
from daedalus.spine.envelope import canonical_sha
from daedalus.spine.ledger import (
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_INTENDED,
    IntentAlreadyResolved,
    SpineLedger,
)


CAMPAIGN_RUN_KIND = "campaign.lifecycle"
_SCHEMA = "daedalus-campaign-lifecycle/1"
_MAX_CONTRACT_BYTES = 16 * 1024 * 1024
_MAX_REPLAY_TREE_FILE_BYTES = 64 * 1024 * 1024
_MAX_REPLAY_TREE_TOTAL_BYTES = 256 * 1024 * 1024
T = TypeVar("T", bound=CanonicalContract)


class CampaignLifecycleError(RuntimeError):
    pass


class CampaignAlreadyTerminal(CampaignLifecycleError):
    pass


class CampaignPendingReconciliation(CampaignLifecycleError):
    pass


class CampaignIdentityConflict(CampaignLifecycleError):
    """A campaign id was reused with different frozen material.

    The request is well-formed; it conflicts with a durable campaign of the
    same identity. Facades answer it as a conflict (HTTP 409), never as a
    malformed request, and never by forking state under the old id.
    """



@dataclass(frozen=True)
class CampaignBeginResult:
    contract: CampaignContract
    intent_id: int
    execute: bool
    receipt: CampaignReceipt | None = None


@dataclass(frozen=True)
class CampaignReplayResult:
    """A completed Campaign chain loaded without opening a writable store."""

    spec: ExperimentSpec
    contract: CampaignContract
    receipt: CampaignReceipt


def store_contract(store: SourceTreeStore, contract: CanonicalContract) -> ArtifactRef:
    if not isinstance(store, SourceTreeStore) or not isinstance(contract, CanonicalContract):
        raise CampaignLifecycleError("store_contract requires canonical CAS and contract")
    return store.put_bytes(canonical_json(contract.to_dict()).encode("ascii"))


def _load(store: SourceTreeStore, ref: ArtifactRef | str, cls: type[T]) -> T:
    try:
        raw = store.read_bytes(ref, max_bytes=_MAX_CONTRACT_BYTES)
        value = json.loads(raw.decode("ascii"))
        contract = cls.from_dict(value)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        SourceTreeStoreError,
        TypeError,
        ValueError,
        KeyError,
    ) as exc:
        raise CampaignLifecycleError(f"invalid persisted {cls.__name__}") from exc
    if raw != canonical_json(contract.to_dict()).encode("ascii"):
        raise CampaignLifecycleError(f"persisted {cls.__name__} is noncanonical")
    return contract


def load_experiment_spec(store: SourceTreeStore, ref: ArtifactRef | str) -> ExperimentSpec:
    return _load(store, ref, ExperimentSpec)


def load_campaign_contract(store: SourceTreeStore, ref: ArtifactRef | str) -> CampaignContract:
    return _load(store, ref, CampaignContract)


def load_campaign_receipt(store: SourceTreeStore, ref: ArtifactRef | str) -> CampaignReceipt:
    return _load(store, ref, CampaignReceipt)


def load_nomination_receipt(
    store: SourceTreeStore, ref: ArtifactRef | str
) -> NominationReceipt:
    return _load(store, ref, NominationReceipt)


def load_attempt_contract(
    store: SourceTreeStore, ref: ArtifactRef | str
) -> AttemptContract:
    """Load one canonical AttemptContract through the campaign CAS boundary."""

    return _load(store, ref, AttemptContract)


def _load_attempt_receipt(
    store: SourceTreeStore, ref: ArtifactRef | str
) -> AttemptReceipt | AttemptTerminalReceipt:
    errors: list[CampaignLifecycleError] = []
    for receipt_type in (AttemptTerminalReceipt, AttemptReceipt):
        try:
            return _load(store, ref, receipt_type)
        except CampaignLifecycleError as exc:
            errors.append(exc)
    raise CampaignLifecycleError("invalid persisted attempt receipt") from errors[-1]


def load_attempt_receipt(
    store: SourceTreeStore, ref: ArtifactRef | str
) -> AttemptReceipt | AttemptTerminalReceipt:
    """Load either canonical Attempt receipt profile without guessing bytes."""

    return _load_attempt_receipt(store, ref)


def load_evidence_packet(
    store: SourceTreeStore, ref: ArtifactRef | str
) -> EvidencePacket:
    """Load one canonical EvidencePacket through the campaign CAS boundary."""

    return _load(store, ref, EvidencePacket)


def _verify_source_tree(
    store: SourceTreeStore,
    locator: str,
    expected_sha256: str,
    *,
    source_revision: str,
    label: str,
) -> SourceTreeManifest:
    """Resolve one typed source-tree manifest and every blob it names."""

    try:
        manifest = store.load_tree(locator, max_manifest_bytes=_MAX_CONTRACT_BYTES)
        if manifest.digest != expected_sha256:
            raise CampaignLifecycleError(f"{label} digest does not match its manifest")
        if manifest.source_revision != source_revision:
            raise CampaignLifecycleError(f"{label} revision differs from campaign")
        total = 0
        for entry in manifest.entries:
            if entry.size > _MAX_REPLAY_TREE_FILE_BYTES:
                raise CampaignLifecycleError(f"{label} entry exceeds replay file bound")
            total += entry.size
            if total > _MAX_REPLAY_TREE_TOTAL_BYTES:
                raise CampaignLifecycleError(f"{label} exceeds replay total bound")
            payload = store.read_bytes(
                ArtifactRef.from_sha256(entry.blob_sha256),
                max_bytes=entry.size,
            )
            if len(payload) != entry.size:
                raise CampaignLifecycleError(f"{label} entry size is inconsistent")
        return manifest
    except CampaignLifecycleError:
        raise
    except (SourceTreeStoreError, TypeError, ValueError) as exc:
        raise CampaignLifecycleError(f"invalid persisted {label}") from exc


def _require_artifact(store: SourceTreeStore, ref: ArtifactRef | str, *, label: str) -> bytes:
    try:
        return store.read_bytes(ref, max_bytes=_MAX_CONTRACT_BYTES)
    except (SourceTreeStoreError, TypeError, ValueError) as exc:
        raise CampaignLifecycleError(f"invalid persisted {label}") from exc


def campaign_contract_for_spec(
    spec: ExperimentSpec,
    *,
    provenance: ContractProvenance,
) -> CampaignContract:
    """Derive the executable contract without weakening the frozen spec."""
    if not isinstance(spec, ExperimentSpec):
        raise CampaignLifecycleError("spec must be ExperimentSpec")
    return CampaignContract(
        campaign_id=spec.campaign_id,
        source_revision=spec.source_revision,
        experiment_spec_sha256=spec.digest,
        evaluator_sha256=spec.frozen_components["evaluator"],
        task_sha256s=spec.task_sha256s,
        baseline_sha256s=spec.baseline_sha256s,
        seeds=spec.seeds,
        metrics=spec.metrics,
        operator_axis=spec.operator_axis,
        frozen_components=spec.frozen_components,
        writable_paths=spec.writable_paths,
        budget=spec.budget,
        expires_at=spec.expires_at,
        provenance=provenance,
        execution_limit_policy=spec.execution_limit_policy,
        execution_limit_policy_sha256=spec.execution_limit_policy_sha256,
        base_source_tree_sha256=spec.base_source_tree_sha256,
        base_source_tree_locator=spec.base_source_tree_locator,
        seed_derivation=spec.seed_derivation,
        selection_policy=spec.selection_policy,
        attempts_per_seed=spec.attempts_per_seed,
        metric_acceptance=spec.metric_acceptance,
        gate_timeout_s=spec.gate_timeout_s,
    )


def _require_contract_matches_spec(
    contract: CampaignContract,
    spec: ExperimentSpec,
) -> None:
    """Require every Spec-derived execution field to remain mutually exact."""

    expected = campaign_contract_for_spec(spec, provenance=contract.provenance)
    if contract != expected:
        raise CampaignLifecycleError(
            "CampaignContract execution fields differ from ExperimentSpec"
        )


def _rows(spine: SpineLedger, campaign_id: str):
    return spine.intents_by_effect_key(
        f"campaign:{campaign_id}", kind=CAMPAIGN_RUN_KIND
    )


def lookup_campaign_read_only(
    spine_path: str,
    store_root: str,
    campaign_id: str,
    *,
    expected_operation_sha256: str,
) -> CampaignReplayResult | None:
    """Load one completed chain after the caller crosses its effect boundary.

    A missing database creates nothing.  An existing WAL-mode database may
    require SQLite ``-wal``/``-shm`` companions even through ``mode=ro``, so
    this helper is not a pre-authorisation inspection seam.  Reusing an id with
    changed request material is a binding error, while an unresolved start is
    reconciliation work rather than permission to execute the effects again.
    """
    from pathlib import Path

    database = Path(spine_path)
    cas = Path(store_root)
    if not database.is_file():
        return None
    if not cas.is_dir():
        raise CampaignLifecycleError(
            "partial persisted Campaign state is unsafe: the spine database "
            f"exists ({database}) but its source-tree CAS is missing ({cas}); "
            "the spine is repository-local while the CAS lives under the "
            "control root, so a different control root (DAEDALUS_KILLSWITCH) "
            "against a repository with an existing spine produces exactly this"
        )
    store = SourceTreeStore.open_existing(cas)
    spine = SpineLedger(database, read_only=True)
    try:
        rows = _rows(spine, campaign_id)
        if not rows:
            return None
        if len(rows) != 1:
            raise CampaignLifecycleError("campaign has multiple lifecycle starts")
        row = rows[0]
        payload = row.payload
        if not isinstance(payload, Mapping) or set(payload) != {
            "schema", "campaign_id", "contract", "experiment"
        } or payload.get("schema") != _SCHEMA or payload.get("campaign_id") != campaign_id:
            raise CampaignLifecycleError("persisted campaign start is malformed")
        contract_ref = ArtifactRef(**payload["contract"])
        spec_ref = ArtifactRef(**payload["experiment"])
        spec = load_experiment_spec(store, spec_ref)
        contract = load_campaign_contract(store, contract_ref)
        if spec.task_sha256s != (expected_operation_sha256,):
            raise CampaignIdentityConflict(
                "campaign_id was reused with changed repair inputs"
            )
        if row.state == STATE_INTENDED:
            raise CampaignPendingReconciliation("campaign has an unresolved durable start")
        if row.state == STATE_FAILED:
            raise CampaignAlreadyTerminal(row.error or "campaign previously failed")
        result = row.result
        if not isinstance(result, Mapping) or set(result) != {"receipt"}:
            raise CampaignLifecycleError("campaign terminal event is malformed")
        receipt = load_campaign_receipt(store, result["receipt"])
        verify_campaign_chain(store, contract, spec, receipt)
        return CampaignReplayResult(spec=spec, contract=contract, receipt=receipt)
    finally:
        spine.close()


def begin_campaign(
    spine: SpineLedger,
    store: SourceTreeStore,
    contract: CampaignContract,
    contract_ref: ArtifactRef,
    spec_ref: ArtifactRef,
) -> CampaignBeginResult:
    """Durably admit exactly one campaign identity before any trial effect."""
    if load_campaign_contract(store, contract_ref) != contract:
        raise CampaignLifecycleError("campaign contract CAS binding mismatch")
    spec = load_experiment_spec(store, spec_ref)
    if spec.digest != contract.experiment_spec_sha256:
        raise CampaignLifecycleError("campaign does not bind submitted experiment")
    _require_contract_matches_spec(contract, spec)
    payload = {
        "schema": _SCHEMA,
        "campaign_id": contract.campaign_id,
        "contract": contract_ref.to_dict(),
        "experiment": spec_ref.to_dict(),
    }
    rows = _rows(spine, contract.campaign_id)
    if rows:
        if len(rows) != 1 or rows[0].payload != payload:
            raise CampaignLifecycleError("campaign identity was reused with different material")
        row = rows[0]
        if row.state == STATE_INTENDED:
            raise CampaignPendingReconciliation("campaign has an unresolved durable start")
        if row.state == STATE_FAILED:
            raise CampaignAlreadyTerminal(row.error or "campaign previously failed")
        result = row.result
        if not isinstance(result, Mapping) or set(result) != {"receipt"}:
            raise CampaignLifecycleError("campaign terminal event is malformed")
        receipt = load_campaign_receipt(store, result["receipt"])
        verify_campaign_chain(store, contract, spec, receipt)
        return CampaignBeginResult(contract, row.id, False, receipt)
    intent = spine.record_intent(
        CAMPAIGN_RUN_KIND,
        payload,
        effect_key=f"campaign:{contract.campaign_id}",
        trace_id=contract.campaign_id,
    )
    return CampaignBeginResult(contract, intent.id, True, None)


def complete_campaign(
    spine: SpineLedger,
    store: SourceTreeStore,
    begin: CampaignBeginResult,
    receipt: CampaignReceipt,
) -> ArtifactRef:
    if not begin.execute:
        raise CampaignAlreadyTerminal("campaign was not admitted for execution")
    verify_campaign_chain(store, begin.contract, None, receipt)
    ref = store_contract(store, receipt)
    try:
        spine.mark_completed(begin.intent_id, effect_id=receipt.digest, result={"receipt": ref.locator})
    except IntentAlreadyResolved as exc:
        raise CampaignAlreadyTerminal("campaign already resolved") from exc
    return ref


def fail_campaign(spine: SpineLedger, begin: CampaignBeginResult, error: str) -> None:
    if not begin.execute:
        raise CampaignAlreadyTerminal("campaign was not admitted for execution")
    try:
        spine.mark_failed(begin.intent_id, str(error))
    except IntentAlreadyResolved as exc:
        raise CampaignAlreadyTerminal("campaign already resolved") from exc


def verify_campaign_chain(
    store: SourceTreeStore,
    contract: CampaignContract,
    spec: ExperimentSpec | None,
    receipt: CampaignReceipt,
) -> None:
    """Verify all campaign-level bindings and every referenced CAS object."""
    if receipt.campaign_id != contract.campaign_id:
        raise CampaignLifecycleError("receipt belongs to another campaign")
    if receipt.source_revision != contract.source_revision:
        raise CampaignLifecycleError("receipt revision differs from campaign")
    if receipt.campaign_contract_sha256 != contract.digest:
        raise CampaignLifecycleError("receipt does not bind campaign contract")
    if receipt.experiment_spec_sha256 != contract.experiment_spec_sha256:
        raise CampaignLifecycleError("receipt does not bind experiment spec")
    if spec is not None and spec.digest != contract.experiment_spec_sha256:
        raise CampaignLifecycleError("experiment spec differs from campaign")
    if tuple(receipt.metric_names) != tuple(contract.metrics):
        raise CampaignLifecycleError("receipt metrics differ from campaign")
    retained_order = tuple(receipt.execution_order)
    frozen_order = tuple(contract.seeds)
    nomination: NominationReceipt | None = None
    selected_trial = None
    if receipt.outcome == "nominated":
        if retained_order != frozen_order or len(receipt.trials) != len(frozen_order):
            raise CampaignLifecycleError(
                "nominated receipt does not retain every frozen trial in order"
            )
    elif (
        not retained_order
        or retained_order != frozen_order[: len(retained_order)]
        or len(receipt.trials) != len(retained_order)
    ):
        raise CampaignLifecycleError(
            "terminal receipt does not retain a frozen trial-order prefix"
        )
    budget_sha = canonical_sha(asdict(contract.budget))
    if (
        receipt.outcome == "nominated"
        and receipt.selection_mode == "best-passed-trial"
    ):
        if receipt.budget_equality is None:
            raise CampaignLifecycleError("best-trial receipt lacks budget evidence")
        if receipt.budget_equality.configured_budget_sha256 != budget_sha:
            raise CampaignLifecycleError(
                "receipt budget evidence differs from CampaignContract budget"
            )
    persisted_contract = load_campaign_contract(
        store, receipt.campaign_contract_locator
    )
    persisted_spec = load_experiment_spec(store, receipt.experiment_spec_locator)
    if persisted_contract != contract:
        raise CampaignLifecycleError("persisted CampaignContract differs from campaign")
    if persisted_spec.digest != contract.experiment_spec_sha256:
        raise CampaignLifecycleError("persisted ExperimentSpec differs from campaign")
    if spec is not None and persisted_spec != spec:
        raise CampaignLifecycleError("submitted ExperimentSpec differs from persisted campaign")
    _require_contract_matches_spec(contract, persisted_spec)
    verified_trees: dict[str, SourceTreeManifest] = {}

    def verify_tree_once(
        locator: str, digest: str, *, label: str
    ) -> SourceTreeManifest:
        if digest in verified_trees:
            return verified_trees[digest]
        manifest = _verify_source_tree(
            store,
            locator,
            digest,
            source_revision=receipt.source_revision,
            label=label,
        )
        verified_trees[digest] = manifest
        return manifest

    if (
        contract.base_source_tree_sha256 is None
        or contract.base_source_tree_locator is None
    ):
        raise CampaignLifecycleError("campaign lacks its frozen base source tree")
    verify_tree_once(
        contract.base_source_tree_locator,
        contract.base_source_tree_sha256,
        label="CampaignContract base source tree",
    )

    if receipt.outcome == "nominated":
        if receipt.nomination_receipt_locator is None:
            raise CampaignLifecycleError("nominated campaign lacks nomination locator")
        nomination = load_nomination_receipt(
            store, receipt.nomination_receipt_locator
        )
        selected = [
            trial
            for trial in receipt.trials
            if trial.seed == receipt.selected_seed
            and (
                receipt.selected_variant_id is None
                or trial.variant_id == receipt.selected_variant_id
            )
        ]
        if len(selected) != 1:
            raise CampaignLifecycleError(
                "nomination does not select exactly one retained trial"
            )
        selected_trial = selected[0]
        if (
            nomination.digest != receipt.nomination_receipt_sha256
            or nomination.nomination_status != "nominated"
            or nomination.mission_id != receipt.campaign_id
            or nomination.source_revision != receipt.source_revision
            or nomination.attempt_id not in selected_trial.attempt_ids
            or nomination.candidate_artifact_sha256
            != receipt.candidate_tree_sha256
            or nomination.candidate_artifact_sha256
            != selected_trial.candidate_tree_sha256
            or nomination.candidate_artifact_locator
            != selected_trial.candidate_tree_locator
            or nomination.evidence_packet_sha256
            != selected_trial.evidence_packet_sha256
            or nomination.evidence_locator
            != selected_trial.evidence_packet_locator
        ):
            raise CampaignLifecycleError(
                "nomination receipt does not bind the selected campaign trial"
            )
    packets: dict[str, EvidencePacket] = {}
    attempts_by_id: dict[str, AttemptContract] = {}
    for trial in receipt.trials:
        if trial.seed not in contract.seeds:
            raise CampaignLifecycleError("receipt contains an unregistered seed")
        if trial.configured_budget_sha256 != budget_sha:
            raise CampaignLifecycleError("trial configured budget differs from campaign")
        if (
            trial.base_source_tree_sha256 != contract.base_source_tree_sha256
            or trial.base_source_tree_locator != contract.base_source_tree_locator
        ):
            raise CampaignLifecycleError(
                "trial base source tree differs from frozen campaign base"
            )
        verify_tree_once(
            trial.base_source_tree_locator,
            trial.base_source_tree_sha256,
            label=f"trial {trial.variant_id}:{trial.seed} base source tree",
        )
        if trial.candidate_tree_locator is not None and trial.candidate_tree_sha256 is not None:
            verify_tree_once(
                trial.candidate_tree_locator,
                trial.candidate_tree_sha256,
                label=f"trial {trial.variant_id}:{trial.seed} candidate source tree",
            )

        attempts: dict[str, AttemptContract] = {}
        for expected_id, digest, locator in zip(
            trial.attempt_ids,
            trial.attempt_contract_sha256s,
            trial.attempt_contract_locators,
            strict=True,
        ):
            attempt = _load(store, locator, AttemptContract)
            if (
                attempt.digest != digest
                or attempt.attempt_id != expected_id
                or attempt.mission_id != receipt.campaign_id
                or attempt.campaign_id != receipt.campaign_id
                or attempt.base_revision != receipt.source_revision
                or attempt.budget != contract.budget
                or attempt.writable_paths != contract.writable_paths
                or attempt.execution_limit_policy
                != contract.execution_limit_policy
                or attempt.execution_limit_policy_sha256
                != contract.execution_limit_policy_sha256
            ):
                raise CampaignLifecycleError(
                    "attempt contract does not bind its campaign trial"
                )
            attempts[attempt.attempt_id] = attempt
            if attempt.attempt_id in attempts_by_id:
                raise CampaignLifecycleError(
                    "attempt identity is duplicated across campaign trials"
                )
            attempts_by_id[attempt.attempt_id] = attempt

        retained_receipt_ids: set[str] = set()
        for expected_id, digest, locator in zip(
            trial.attempt_ids,
            trial.attempt_receipt_sha256s,
            trial.attempt_receipt_locators,
            strict=True,
        ):
            attempt_receipt = _load_attempt_receipt(store, locator)
            if attempt_receipt.digest != digest:
                raise CampaignLifecycleError(
                    "attempt receipt digest differs from campaign trial"
                )
            if attempt_receipt.attempt_id != expected_id:
                raise CampaignLifecycleError(
                    "attempt receipt order differs from retained attempts"
                )
            if attempt_receipt.attempt_id in retained_receipt_ids:
                raise CampaignLifecycleError(
                    "campaign trial retains a duplicate attempt receipt"
                )
            retained_receipt_ids.add(attempt_receipt.attempt_id)
            attempt = attempts.get(attempt_receipt.attempt_id)
            if attempt is None:
                raise CampaignLifecycleError(
                    "attempt receipt does not name a retained trial attempt"
                )
            bound_attempt_sha = getattr(
                attempt_receipt,
                "attempt_sha256",
                getattr(attempt_receipt, "attempt_contract_sha256", None),
            )
            receipt_mission_id = getattr(attempt_receipt, "mission_id", None)
            if (
                (
                    receipt_mission_id is not None
                    and receipt_mission_id != receipt.campaign_id
                )
                or attempt_receipt.source_revision != receipt.source_revision
                or bound_attempt_sha != attempt.digest
            ):
                raise CampaignLifecycleError(
                    "attempt receipt does not bind its campaign attempt"
                )
            if isinstance(attempt_receipt, AttemptTerminalReceipt):
                expected_candidate = (
                    None
                    if trial.candidate_tree_sha256 is None
                    else ArtifactRef(
                        sha256=trial.candidate_tree_sha256,
                        locator=trial.candidate_tree_locator,
                    )
                )
                if (
                    attempt_receipt.input_tree_sha256
                    != trial.base_source_tree_sha256
                    or attempt_receipt.candidate_tree != expected_candidate
                    or (
                        trial.receipt_profile == "controlled-repair-v1"
                        and (
                            (trial.status == "passed")
                            != (attempt_receipt.outcome == "succeeded")
                        )
                    )
                ):
                    raise CampaignLifecycleError(
                        "attempt terminal receipt differs from its campaign trial"
                    )
            else:
                if (
                    attempt_receipt.runtime_manifest_sha256
                    != attempt.runtime_manifest_sha256
                    or attempt_receipt.policy_decision_sha256
                    != attempt.policy_decision_sha256
                    or (
                        trial.evidence_packet_sha256 is not None
                        and attempt_receipt.evidence_packet_sha256
                        != trial.evidence_packet_sha256
                    )
                ):
                    raise CampaignLifecycleError(
                        "attempt receipt execution bindings differ from its contract"
                    )
            report = getattr(attempt_receipt, "report", None)
            if report is not None:
                _require_artifact(
                    store,
                    report,
                    label=f"attempt {attempt_receipt.attempt_id} report",
                )

        if trial.evidence_packet_locator is not None:
            if trial.evidence_packet_sha256 is None:
                raise CampaignLifecycleError("trial evidence locator has no digest")
            packet = _load(store, trial.evidence_packet_locator, EvidencePacket)
            if (
                packet.digest != trial.evidence_packet_sha256
                or packet.mission_id != receipt.campaign_id
                or packet.attempt_id not in trial.attempt_ids
                or packet.source_revision != receipt.source_revision
                or packet.attempt_contract_sha256
                != attempts[packet.attempt_id].digest
                or packet.subject_sha256 != trial.candidate_tree_sha256
                or packet.candidate_artifact_sha256
                != trial.candidate_tree_sha256
                or packet.candidate_artifact_locator
                != trial.candidate_tree_locator
                or packet.policy_decision_sha256
                != attempts[packet.attempt_id].policy_decision_sha256
            ):
                raise CampaignLifecycleError(
                    "evidence packet does not bind its campaign trial"
                )
            if trial.status == "passed" and packet.evaluation_status != "passed":
                raise CampaignLifecycleError(
                    "passed campaign trial lacks passing evidence"
                )
            if (
                receipt.outcome == "nominated"
                and trial is selected_trial
                and packet.evaluation_status != "passed"
            ):
                raise CampaignLifecycleError(
                    "selected campaign trial lacks passing evidence"
                )
            packets[packet.digest] = packet
            for item in packet.items:
                if (
                    ArtifactRef.from_sha256(item.output_sha256).locator
                    != item.evidence_locator
                ):
                    raise CampaignLifecycleError(
                        "evidence item output does not bind its artifact locator"
                    )
                _require_artifact(
                    store,
                    item.evidence_locator,
                    label=f"evidence item {item.evidence_id}",
                )

    if nomination is not None and selected_trial is not None:
        selected_packet = packets.get(str(selected_trial.evidence_packet_sha256))
        selected_attempt = attempts_by_id.get(nomination.attempt_id)
        if (
            selected_packet is None
            or selected_attempt is None
            or nomination.policy_decision_sha256
            != selected_packet.policy_decision_sha256
            or nomination.policy_decision_sha256
            != selected_attempt.policy_decision_sha256
        ):
            raise CampaignLifecycleError(
                "nomination policy evidence differs from selected campaign trial"
            )
