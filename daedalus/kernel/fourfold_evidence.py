# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Bind a real Fourfold snapshot into the canonical Gate-0 evidence chain.

This module is deliberately narrow. It does not compile repositories, create a
second evidence schema, authenticate artifact storage, consume approvals, or
promote candidates. It projects one already compiled :class:`FourfoldSnapshot`
into the existing :class:`EvidencePacket` and :class:`NominationReceipt`
contracts and verifies that every record still names the same candidate tree,
source revision, Forest and snapshot.

It does write exactly one thing: the snapshot's own canonical bytes, into the
caller's existing content-addressed :class:`~daedalus.storage.ArtifactStore`,
because the packet claims a locator for them. Until 2026-08-22 it claimed one
without writing anything -- ``artifact-locator:sha256:<snapshot digest>``,
shape-valid and resolvable in no store. MEASURED on the last Gate-1 receipt
before the fix: six of seven evidence locators resolved in the mission store,
and the Fourfold one did not. See :func:`_snapshot_locator`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, Sequence

from daedalus.schemas import (
    ContractProvenance,
    EvidenceItem,
    EvidencePacket,
    NominationReceipt,
    ResourceUsage,
    _artifact_locator,
    _locator_sha256,
    _revision,
    _sha256,
)
from daedalus.storage import (
    ArtifactStore,
    ArtifactStoreError,
    StorageUnavailable,
    artifact_locator_uri,
    artifact_manifest,
)
from daedalus.twin.contracts import FourfoldSnapshot

FOURFOLD_EVIDENCE_SCHEMA: Final[str] = "daedalus-fourfold-evidence/1"
FOURFOLD_EVALUATOR: Final[str] = "fourfold.snapshot-binding"

#: The media type of the stored snapshot bytes. They are the snapshot's own
#: canonical JSON -- the exact bytes ``FourfoldSnapshot.digest`` is taken over,
#: so a reader who resolves the locator can recompute the digest the packet
#: claims and rebuild the contract with ``FourfoldSnapshot.from_dict``.
_SNAPSHOT_MEDIA_TYPE: Final[str] = "application/json"

#: Where a caller that named no store puts the snapshot bytes. Repo-bound, not
#: a process global: it is recomputed from this file's location, holds nothing
#: mutable, and any caller with its own store (the Gate-1 slice has one per
#: mission) passes it explicitly rather than inheriting this one.
DEFAULT_EVIDENCE_STORE_ROOT: Final[Path] = (
    Path(__file__).resolve().parents[2] / "runs" / "kernel" / "evidence-store"
)


class FourfoldEvidenceMismatch(ValueError):
    """Raised when evidence no longer names the exact compiled candidate."""


class FourfoldEvidenceUnstorable(RuntimeError):
    """Raised when the snapshot bytes cannot be stored, so no packet is minted.

    Deliberately NOT a fall-back to a synthesised locator. An evidence locator
    is a promise that the bytes are re-readable; minting one for bytes that
    were never written turns an unavailable store into a permanently
    unverifiable promotion record, which is worse than a loud failure now.
    """


@dataclass(frozen=True)
class FourfoldEvidenceExpectation:
    """The exact identities a promotion reviewer expects to inspect.

    The candidate digest and locator are caller-owned inputs. They must be
    resolved from the candidate source-tree/CAS authority rather than copied
    out of the EvidencePacket under review. Gate-0 Fourfold evidence is always
    complete; partial semantics belong to a later, explicitly inconclusive
    Gate-2 path and cannot be enabled by a caller switch here.
    """

    candidate_artifact_sha256: str
    candidate_artifact_locator: str
    snapshot_sha256: str
    source_revision: str

    def __post_init__(self) -> None:
        candidate_sha = _sha256(
            self.candidate_artifact_sha256, "candidate_artifact_sha256"
        )
        candidate_locator = _artifact_locator(
            self.candidate_artifact_locator, "candidate_artifact_locator"
        )
        snapshot_sha = _sha256(self.snapshot_sha256, "snapshot_sha256")
        source_revision = _revision(self.source_revision, "source_revision")
        object.__setattr__(self, "candidate_artifact_sha256", candidate_sha)
        object.__setattr__(self, "candidate_artifact_locator", candidate_locator)
        object.__setattr__(self, "snapshot_sha256", snapshot_sha)
        object.__setattr__(self, "source_revision", source_revision)
        if _locator_sha256(candidate_locator) != candidate_sha:
            raise FourfoldEvidenceMismatch(
                "candidate artifact locator does not resolve to candidate digest"
            )


def _snapshot_bytes(snapshot: FourfoldSnapshot) -> bytes:
    """The exact bytes ``FourfoldSnapshot.digest`` is taken over."""
    return snapshot.to_json().encode("ascii")


def _snapshot_artifact_metadata(snapshot: FourfoldSnapshot) -> dict:
    """Store metadata derived ONLY from the snapshot.

    Nothing here may vary with wall-clock time, caller, or store location: the
    locator digest is a digest of this mapping among others, and a locator that
    changed between two runs over one snapshot could not be re-derived by a
    verifier holding no store.
    """
    return {
        "kind": "fourfold_snapshot",
        "contract_type": FourfoldSnapshot.CONTRACT_TYPE,
        "repository_id": snapshot.repository_id,
        "source_revision": snapshot.source_revision,
        "source_forest_sha256": snapshot.source_forest_sha256,
        "fourfold_snapshot_sha256": snapshot.digest,
    }


def _snapshot_manifest(snapshot: FourfoldSnapshot) -> tuple[bytes, bytes, str]:
    """``(payload, manifest_bytes, locator_sha256)`` -- a pure function of the
    snapshot, and identical to what the store will write for these bytes.

    The manifest provenance is the SNAPSHOT'S OWN provenance, not a fresh
    stamp: it is already the record of who compiled these bytes from which
    revision, and using it keeps the locator derivable. A ``created_at`` taken
    from the clock here would make one snapshot produce a different locator on
    every run, and the verifier could no longer say what the locator must be.
    """
    payload = _snapshot_bytes(snapshot)
    _, manifest_bytes, locator_sha256 = artifact_manifest(
        payload,
        media_type=_SNAPSHOT_MEDIA_TYPE,
        metadata=_snapshot_artifact_metadata(snapshot),
        provenance=snapshot.provenance.to_dict(),
    )
    return payload, manifest_bytes, locator_sha256


def _snapshot_locator(snapshot: FourfoldSnapshot) -> str:
    """THE locator for this snapshot: derivable, and it resolves.

    It used to be ``artifact-locator:sha256:<snapshot digest>``, synthesised
    out of the digest and stored nowhere. MEASURED on the last Gate-1 receipt
    before this change: six of the packet's seven evidence locators resolved in
    the mission store and this one resolved in no store at all -- a promotion
    record whose central artifact could not be read back.

    The shape stayed valid, which is exactly why it survived: a locator is
    checked for syntax by the schema and for resolution by nobody. Now the
    digest is the digest of the locator MANIFEST the store writes, computed
    through the store's own :func:`daedalus.storage.artifact_manifest`, so a
    verifier with no store can still re-derive the exact expected locator while
    a reader with the store gets the bytes.
    """
    return artifact_locator_uri(_snapshot_manifest(snapshot)[2])


def _store_snapshot(snapshot: FourfoldSnapshot, store: ArtifactStore) -> str:
    """Put the snapshot bytes in ``store``; return the locator that reads them.

    Refuses rather than returning an unresolvable locator. The equality check
    against :func:`_snapshot_locator` is not ceremony: prediction and storage
    share one manifest implementation today, and this is what goes red on the
    day someone gives them two.
    """
    payload, _, _ = _snapshot_manifest(snapshot)
    try:
        locator = store.put_bytes(
            payload,
            expected_sha256=snapshot.digest,
            media_type=_SNAPSHOT_MEDIA_TYPE,
            metadata=_snapshot_artifact_metadata(snapshot),
            provenance=snapshot.provenance.to_dict(),
        )
    except (ArtifactStoreError, StorageUnavailable, OSError, ValueError) as exc:
        raise FourfoldEvidenceUnstorable(
            f"the Fourfold snapshot bytes could not be stored in {store.root} "
            f"({type(exc).__name__}: {exc}); refusing to mint an evidence "
            "locator for bytes nobody can read back"
        ) from exc
    expected = _snapshot_locator(snapshot)
    if locator.locator_uri != expected:
        raise FourfoldEvidenceUnstorable(
            "the stored Fourfold snapshot locator "
            f"({locator.locator_uri}) is not the one this module derives "
            f"({expected}); prediction and storage have drifted apart"
        )
    if locator.artifact_sha256 != snapshot.digest:
        raise FourfoldEvidenceUnstorable(
            "the stored Fourfold snapshot bytes do not hash to the snapshot "
            f"digest ({locator.artifact_sha256} vs {snapshot.digest})"
        )
    return locator.locator_uri


def _resolve_store(store: ArtifactStore | None) -> ArtifactStore:
    if store is not None:
        if not isinstance(store, ArtifactStore):
            raise TypeError("store must be an ArtifactStore")
        return store
    return ArtifactStore(DEFAULT_EVIDENCE_STORE_ROOT)


def resolve_fourfold_snapshot_bytes(
    store: ArtifactStore,
    locator: str,
) -> bytes:
    """Read back what an evidence locator promises, or raise.

    The read a locator exists to make possible, in one place, so a receipt
    check and a test are not two different opinions about what "resolves"
    means.
    """
    checked = _artifact_locator(locator, "evidence_locator")
    loaded = store.load_locator(_locator_sha256(checked))
    return store.get_bytes(loaded.artifact_sha256)


def _canonical_snapshot(snapshot: FourfoldSnapshot) -> FourfoldSnapshot:
    if not isinstance(snapshot, FourfoldSnapshot):
        raise TypeError("snapshot must be a FourfoldSnapshot")
    rebuilt = FourfoldSnapshot.from_dict(snapshot.to_dict())
    if rebuilt != snapshot:
        raise FourfoldEvidenceMismatch("FourfoldSnapshot is not canonical")
    return rebuilt


def _canonical_packet(packet: EvidencePacket) -> EvidencePacket:
    if not isinstance(packet, EvidencePacket):
        raise TypeError("packet must be an EvidencePacket")
    rebuilt = EvidencePacket.from_dict(packet.to_dict())
    if rebuilt != packet:
        raise FourfoldEvidenceMismatch("EvidencePacket is not canonical")
    return rebuilt


def _canonical_nomination(nomination: NominationReceipt) -> NominationReceipt:
    if not isinstance(nomination, NominationReceipt):
        raise TypeError("nomination must be a NominationReceipt")
    rebuilt = NominationReceipt.from_dict(nomination.to_dict())
    if rebuilt != nomination:
        raise FourfoldEvidenceMismatch("NominationReceipt is not canonical")
    return rebuilt


def _require_snapshot_candidate_binding(
    snapshot: FourfoldSnapshot,
    candidate_artifact_sha256: str,
) -> None:
    """Require compiler evidence that the snapshot came from this candidate.

    Co-locating two digests in a packet is not a semantic binding: snapshot A
    could otherwise be repackaged beside candidate B. The snapshot compiler
    must retain the exact candidate source-bundle/CAS identity in provenance
    before this promotion-facing adapter may emit conclusive evidence.
    """

    candidate_sha = _sha256(
        candidate_artifact_sha256, "candidate_artifact_sha256"
    )
    if candidate_sha not in snapshot.provenance.input_digests:
        raise FourfoldEvidenceMismatch(
            "FourfoldSnapshot provenance does not bind candidate artifact digest"
        )


def assemble_fourfold_evidence_packet(
    *,
    snapshot: FourfoldSnapshot,
    candidate_artifact_sha256: str,
    candidate_artifact_locator: str,
    packet_id: str,
    mission_id: str,
    attempt_id: str,
    attempt_contract_sha256: str,
    policy_decision_sha256: str,
    collected_at: str,
    usage: ResourceUsage | None = None,
    trace_id: str | None = None,
    extra_items: tuple[EvidenceItem, ...] = (),
    store: ArtifactStore | None = None,
) -> EvidencePacket:
    """Create a passed packet for one complete candidate Fourfold snapshot.

    ``store`` is where the snapshot bytes are written so that the evidence
    locator this packet carries can be read back. A caller with its own store
    -- the Gate-1 slice keeps one per mission, beside the receipt -- passes it,
    and the bytes land next to the rest of that mission's evidence. A caller
    that names none gets :data:`DEFAULT_EVIDENCE_STORE_ROOT`, which is bound to
    this repository rather than being a module-level singleton. If the store
    cannot take the bytes, this raises :class:`FourfoldEvidenceUnstorable`; it
    does not fall back to a locator pointing at nothing.
    """

    snapshot = _canonical_snapshot(snapshot)
    store = _resolve_store(store)
    expectation = FourfoldEvidenceExpectation(
        candidate_artifact_sha256=candidate_artifact_sha256,
        candidate_artifact_locator=candidate_artifact_locator,
        snapshot_sha256=snapshot.digest,
        source_revision=snapshot.source_revision,
    )
    _require_snapshot_candidate_binding(
        snapshot,
        expectation.candidate_artifact_sha256,
    )
    attempt_sha = _sha256(attempt_contract_sha256, "attempt_contract_sha256")
    policy_sha = _sha256(policy_decision_sha256, "policy_decision_sha256")
    # STORE FIRST, then name what was stored. The other order is how the
    # unresolvable locator got in: a name minted from a digest, and nothing
    # ever written under it.
    snapshot_locator = _store_snapshot(snapshot, store)
    details = {
        "schema": FOURFOLD_EVIDENCE_SCHEMA,
        "repository_id": snapshot.repository_id,
        "source_revision": snapshot.source_revision,
        "candidate_artifact_sha256": expectation.candidate_artifact_sha256,
        "source_forest_sha256": snapshot.source_forest_sha256,
        "fourfold_snapshot_sha256": snapshot.digest,
        "plane_statuses": {
            plane.plane: plane.status for plane in snapshot.planes
        },
    }
    item = EvidenceItem(
        evidence_id=f"{attempt_id}:fourfold",
        evaluator=FOURFOLD_EVALUATOR,
        assurance="deterministic",
        verdict="passed",
        output_sha256=snapshot.digest,
        evidence_locator=snapshot_locator,
        collected_at=collected_at,
        provenance=ContractProvenance(
            origin="daedalus.kernel.fourfold-evidence",
            source_revision=snapshot.source_revision,
            created_at=collected_at,
            input_digests=tuple(
                sorted(
                    {
                        expectation.candidate_artifact_sha256,
                        snapshot.source_forest_sha256,
                        snapshot.digest,
                        # The locator's own digest. `EvidenceItem` requires it,
                        # and it used to arrive for free because the locator
                        # was synthesised FROM `snapshot.digest` -- the very
                        # coincidence that let an unstored locator look bound.
                        _locator_sha256(snapshot_locator),
                    }
                )
            ),
            trace_id=trace_id,
        ),
        details=details,
    )
    packet = EvidencePacket(
        packet_id=packet_id,
        mission_id=mission_id,
        attempt_id=attempt_id,
        source_revision=snapshot.source_revision,
        attempt_contract_sha256=attempt_sha,
        subject_sha256=expectation.candidate_artifact_sha256,
        evaluation_status="passed",
        items=(item, *tuple(extra_items)),
        policy_decision_sha256=policy_sha,
        usage=usage or ResourceUsage(),
        provenance=ContractProvenance(
            origin="daedalus.kernel.fourfold-evidence-packet",
            source_revision=snapshot.source_revision,
            created_at=collected_at,
            input_digests=tuple(
                sorted(
                    {
                        attempt_sha,
                        policy_sha,
                        expectation.candidate_artifact_sha256,
                        snapshot.digest,
                        *(extra.output_sha256 for extra in extra_items),
                        _locator_sha256(expectation.candidate_artifact_locator),
                    }
                )
            ),
            trace_id=trace_id,
        ),
        candidate_artifact_sha256=expectation.candidate_artifact_sha256,
        candidate_artifact_locator=expectation.candidate_artifact_locator,
    )
    verify_fourfold_evidence_packet(
        packet,
        snapshot=snapshot,
        expectation=expectation,
        store=store,
    )
    return packet


def assemble_fourfold_nomination_receipt(
    *,
    snapshot: FourfoldSnapshot,
    packet: EvidencePacket,
    expectation: FourfoldEvidenceExpectation,
    nomination_id: str,
    reasons: Sequence[str],
    created_at: str,
    trace_id: str | None = None,
) -> NominationReceipt:
    """Nominate the exact packet without creating owner or promotion authority."""

    snapshot = _canonical_snapshot(snapshot)
    packet = _canonical_packet(packet)
    verify_fourfold_evidence_packet(
        packet,
        snapshot=snapshot,
        expectation=expectation,
    )
    snapshot_locator = _snapshot_locator(snapshot)
    nomination = NominationReceipt(
        nomination_id=nomination_id,
        mission_id=packet.mission_id,
        attempt_id=packet.attempt_id,
        source_revision=snapshot.source_revision,
        candidate_artifact_sha256=expectation.candidate_artifact_sha256,
        candidate_artifact_locator=expectation.candidate_artifact_locator,
        evidence_packet_sha256=packet.digest,
        evidence_locator=snapshot_locator,
        policy_decision_sha256=packet.policy_decision_sha256,
        nomination_status="nominated",
        reasons=tuple(reasons),
        provenance=ContractProvenance(
            origin="daedalus.kernel.fourfold-nomination",
            source_revision=snapshot.source_revision,
            created_at=created_at,
            input_digests=tuple(
                sorted(
                    {
                        expectation.candidate_artifact_sha256,
                        _locator_sha256(expectation.candidate_artifact_locator),
                        packet.digest,
                        _locator_sha256(snapshot_locator),
                        packet.policy_decision_sha256,
                    }
                )
            ),
            trace_id=trace_id,
        ),
    )
    verify_fourfold_nomination_receipt(
        nomination,
        packet=packet,
        snapshot=snapshot,
        expectation=expectation,
    )
    return nomination


def verify_fourfold_evidence_packet(
    packet: EvidencePacket,
    *,
    snapshot: FourfoldSnapshot,
    expectation: FourfoldEvidenceExpectation,
    store: ArtifactStore | None = None,
) -> None:
    """Fail closed unless packet, candidate and complete snapshot are exact.

    ``store`` is optional because this verifier must stay usable by a reviewer
    holding a packet and a snapshot and nothing else -- the locator is derived,
    so its correctness is checkable without any store. When a store IS given,
    the locator is also RESOLVED and the bytes are required to be the snapshot:
    a derivation both sides compute the same wrong way would otherwise agree
    with itself forever, which is precisely how the synthesised locator
    survived.
    """

    packet = _canonical_packet(packet)
    snapshot = _canonical_snapshot(snapshot)
    _require_snapshot_candidate_binding(
        snapshot,
        expectation.candidate_artifact_sha256,
    )

    mismatches: list[str] = []
    if packet.source_revision != snapshot.source_revision:
        mismatches.append("source_revision")
    if expectation.source_revision != snapshot.source_revision:
        mismatches.append("expected_source_revision")
    if expectation.snapshot_sha256 != snapshot.digest:
        mismatches.append("expected_snapshot")
    incomplete = [
        plane.plane for plane in snapshot.planes if plane.status != "complete"
    ]
    if incomplete:
        mismatches.append("incomplete_planes:" + "+".join(sorted(incomplete)))
    if packet.subject_sha256 != expectation.candidate_artifact_sha256:
        mismatches.append("subject")
    if packet.candidate_artifact_sha256 != expectation.candidate_artifact_sha256:
        mismatches.append("candidate_digest")
    if packet.candidate_artifact_locator != expectation.candidate_artifact_locator:
        mismatches.append("candidate_locator")
    if packet.evaluation_status != "passed":
        mismatches.append("evaluation_status")

    items = [item for item in packet.items if item.evaluator == FOURFOLD_EVALUATOR]
    if len(items) != 1:
        mismatches.append("fourfold_evidence_count")
    else:
        item = items[0]
        expected_details = {
            "schema": FOURFOLD_EVIDENCE_SCHEMA,
            "repository_id": snapshot.repository_id,
            "source_revision": snapshot.source_revision,
            "candidate_artifact_sha256": expectation.candidate_artifact_sha256,
            "source_forest_sha256": snapshot.source_forest_sha256,
            "fourfold_snapshot_sha256": snapshot.digest,
            "plane_statuses": {
                plane.plane: plane.status for plane in snapshot.planes
            },
        }
        if item.assurance != "deterministic" or item.verdict != "passed":
            mismatches.append("fourfold_verdict")
        if item.output_sha256 != snapshot.digest:
            mismatches.append("snapshot_digest")
        if item.evidence_locator != _snapshot_locator(snapshot):
            mismatches.append("snapshot_locator")
        elif store is not None:
            try:
                stored = resolve_fourfold_snapshot_bytes(
                    store, item.evidence_locator)
            except Exception:                             # noqa: BLE001
                mismatches.append("snapshot_locator_unresolvable")
            else:
                if stored != _snapshot_bytes(snapshot):
                    mismatches.append("snapshot_locator_bytes")
        if dict(item.details) != expected_details:
            mismatches.append("fourfold_details")
        if item.provenance.source_revision != snapshot.source_revision:
            mismatches.append("fourfold_item_revision")
        item_inputs = set(item.provenance.input_digests)
        if expectation.candidate_artifact_sha256 not in item_inputs:
            mismatches.append("fourfold_item_candidate_provenance")
        if snapshot.source_forest_sha256 not in item_inputs:
            mismatches.append("fourfold_item_forest_provenance")
        if snapshot.digest not in item_inputs:
            mismatches.append("fourfold_item_snapshot_provenance")

    packet_inputs = set(packet.provenance.input_digests)
    if packet.provenance.source_revision != snapshot.source_revision:
        mismatches.append("packet_revision")
    if expectation.candidate_artifact_sha256 not in packet_inputs:
        mismatches.append("packet_candidate_provenance")
    if snapshot.digest not in packet_inputs:
        mismatches.append("packet_snapshot_provenance")
    if packet.attempt_contract_sha256 not in packet_inputs:
        mismatches.append("packet_attempt_provenance")
    if packet.policy_decision_sha256 not in packet_inputs:
        mismatches.append("packet_policy_provenance")

    if mismatches:
        raise FourfoldEvidenceMismatch(
            "Fourfold evidence binding mismatch: " + ", ".join(sorted(set(mismatches)))
        )


def verify_fourfold_nomination_receipt(
    nomination: NominationReceipt,
    *,
    packet: EvidencePacket,
    snapshot: FourfoldSnapshot,
    expectation: FourfoldEvidenceExpectation,
) -> None:
    """Verify that nomination retains the exact verified semantic evidence."""

    nomination = _canonical_nomination(nomination)
    packet = _canonical_packet(packet)
    snapshot = _canonical_snapshot(snapshot)
    verify_fourfold_evidence_packet(
        packet,
        snapshot=snapshot,
        expectation=expectation,
    )

    mismatches: list[str] = []
    if nomination.nomination_status != "nominated":
        mismatches.append("nomination_status")
    if nomination.source_revision != snapshot.source_revision:
        mismatches.append("source_revision")
    if nomination.mission_id != packet.mission_id:
        mismatches.append("mission_id")
    if nomination.attempt_id != packet.attempt_id:
        mismatches.append("attempt_id")
    if nomination.candidate_artifact_sha256 != expectation.candidate_artifact_sha256:
        mismatches.append("candidate_digest")
    if nomination.candidate_artifact_locator != expectation.candidate_artifact_locator:
        mismatches.append("candidate_locator")
    if nomination.evidence_packet_sha256 != packet.digest:
        mismatches.append("evidence_packet")
    if nomination.evidence_locator != _snapshot_locator(snapshot):
        mismatches.append("snapshot_locator")
    if nomination.policy_decision_sha256 != packet.policy_decision_sha256:
        mismatches.append("policy_decision")
    if mismatches:
        raise FourfoldEvidenceMismatch(
            "Fourfold nomination binding mismatch: "
            + ", ".join(sorted(set(mismatches)))
        )


__all__ = [
    "DEFAULT_EVIDENCE_STORE_ROOT",
    "FOURFOLD_EVIDENCE_SCHEMA",
    "FOURFOLD_EVALUATOR",
    "FourfoldEvidenceExpectation",
    "FourfoldEvidenceMismatch",
    "FourfoldEvidenceUnstorable",
    "assemble_fourfold_evidence_packet",
    "assemble_fourfold_nomination_receipt",
    "resolve_fourfold_snapshot_bytes",
    "verify_fourfold_evidence_packet",
    "verify_fourfold_nomination_receipt",
]
