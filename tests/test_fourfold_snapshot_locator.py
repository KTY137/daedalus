# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""B1: the Fourfold evidence locator has to resolve to bytes somebody stored.

WHAT WENT WRONG, MEASURED on the last Gate-1 receipt before this change
(``runs/ignition/mission-gate1-voltage-ignition/receipt.json``, read against
its own ``store/``)::

    locator_resolves=True   gate1-attempt-binding
    locator_resolves=True   gate1-behavior
    locator_resolves=True   gate1-check-links
    locator_resolves=True   gate1-check-pytest
    locator_resolves=True   gate1-check-schema
    locator_resolves=True   gate1-graph-delta
    locator_resolves=False  gate1-voltage-composed-36d0b035558f:fourfold
    6/7 locators resolve

``assemble_fourfold_evidence_packet`` synthesised
``artifact-locator:sha256:<snapshot digest>`` and stored nothing. The URI was
shape-valid, the schema checked its syntax, and nobody checked that it pointed
at anything -- so the one artifact a promotion reviewer most needs to read, the
compiled four-plane snapshot itself, was the one artifact that could not be
read back. Every conclusive four-plane packet in the repository carries such a
locator.

WHAT THESE TESTS PIN, and it is deliberately more than "the file exists":

  * the locator RESOLVES, and the bytes behind it hash to the digest the packet
    claims -- an existence check alone would pass against a store holding the
    wrong bytes;
  * those bytes rebuild the exact ``FourfoldSnapshot``, so the promise is the
    snapshot and not merely some blob;
  * the locator is a pure function of the snapshot, identical in a second
    store, because a verifier that holds no store still has to be able to say
    what the locator MUST be;
  * a store that cannot take the bytes produces NO packet, rather than a packet
    with a locator pointing nowhere. That is the regression: falling back to a
    synthesised name is how the original defect would return.

TO SEE THEM GO RED, disable the guard rather than trusting the assertions:

  * restore ``return f"artifact-locator:sha256:{snapshot.digest}"`` in
    ``_snapshot_locator`` -- MEASURED with that mutation: the assembler raises
    ``FourfoldEvidenceUnstorable`` ("prediction and storage have drifted
    apart"), and dropping the ``_store_snapshot`` call as well takes every
    resolution test in this file red;
  * make ``_store_snapshot`` return ``_snapshot_locator(snapshot)`` without
    calling ``store.put_bytes`` -- the resolution tests go red and the refusal
    test goes red;
  * delete the ``elif store is not None:`` branch in
    ``verify_fourfold_evidence_packet`` -- only
    ``TestTheVerifierResolvesWhenGivenAStore`` notices, which is why it is here.

NOT COVERED, and named rather than implied: ``candidate_artifact_locator`` is
still synthesised from the source-bundle digest by both this module's callers
(``daedalus/ignition/gate1.py``, ``daedalus/ignition/runner.py``). It happens
to resolve in the Gate-1 store because the slice stores the bundle separately;
nothing here proves that, and it is a different seam.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from daedalus.kernel.fourfold_evidence import (  # noqa: E402
    FOURFOLD_EVALUATOR,
    FourfoldEvidenceMismatch,
    FourfoldEvidenceUnstorable,
    _snapshot_locator,
    assemble_fourfold_evidence_packet,
    resolve_fourfold_snapshot_bytes,
    verify_fourfold_evidence_packet,
)
from daedalus.kernel.fourfold_evidence import (  # noqa: E402
    FourfoldEvidenceExpectation,
)
from daedalus.schemas import ResourceUsage  # noqa: E402
from daedalus.spine.envelope import canonical_sha  # noqa: E402
from daedalus.storage import ArtifactStore  # noqa: E402
from daedalus.twin import compile_reference_project  # noqa: E402
from daedalus.twin.contracts import FourfoldSnapshot  # noqa: E402

REVISION = "b" * 40
NOW = "2026-08-01T21:30:00Z"
FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "fourfold_wiki_app"
ATTEMPT_SHA = canonical_sha({"attempt": "g0-rcp-04a"})
POLICY_SHA = canonical_sha({"policy": "gate0-read-only"})


@pytest.fixture(scope="module")
def compiled():
    return compile_reference_project(
        FIXTURE, source_revision=REVISION, created_at=NOW, trace_id="g0-rcp-04a")


def _expectation(result) -> FourfoldEvidenceExpectation:
    return FourfoldEvidenceExpectation(
        candidate_artifact_sha256=result.source_bundle_sha256,
        candidate_artifact_locator=(
            f"artifact-locator:sha256:{result.source_bundle_sha256}"),
        snapshot_sha256=result.snapshot.digest,
        source_revision=result.snapshot.source_revision,
    )


def _packet(result, store: ArtifactStore):
    return assemble_fourfold_evidence_packet(
        snapshot=result.snapshot,
        candidate_artifact_sha256=result.source_bundle_sha256,
        candidate_artifact_locator=(
            f"artifact-locator:sha256:{result.source_bundle_sha256}"),
        packet_id="g0-rcp-04a-evidence",
        mission_id="g0-rcp-04a",
        attempt_id="g0-rcp-04a-attempt",
        attempt_contract_sha256=ATTEMPT_SHA,
        policy_decision_sha256=POLICY_SHA,
        collected_at=NOW,
        usage=ResourceUsage(wall_time_ms=1),
        trace_id="g0-rcp-04a",
        store=store,
    )


def _fourfold_item(packet):
    return next(i for i in packet.items if i.evaluator == FOURFOLD_EVALUATOR)


class TestTheLocatorResolves:

    def test_the_locator_reads_back_the_bytes_it_names(self, compiled, tmp_path):
        store = ArtifactStore(tmp_path / "store")
        item = _fourfold_item(_packet(compiled, store))

        raw = resolve_fourfold_snapshot_bytes(store, item.evidence_locator)
        assert hashlib.sha256(raw).hexdigest() == item.output_sha256
        assert hashlib.sha256(raw).hexdigest() == compiled.snapshot.digest

    def test_the_stored_bytes_rebuild_the_exact_snapshot(self, compiled, tmp_path):
        """Existence is not the property. Being THE snapshot is."""
        store = ArtifactStore(tmp_path / "store")
        item = _fourfold_item(_packet(compiled, store))

        raw = resolve_fourfold_snapshot_bytes(store, item.evidence_locator)
        rebuilt = FourfoldSnapshot.from_dict(json.loads(raw.decode("ascii")))
        assert rebuilt == compiled.snapshot
        assert rebuilt.digest == compiled.snapshot.digest

    def test_the_locator_manifest_is_where_a_receipt_check_looks(
            self, compiled, tmp_path):
        """``tests/test_ignition_gate1.py`` resolves a locator by taking the
        digest after the last colon and asking for ``locator_path``. Same
        spelling here, so the two cannot disagree about what resolving means."""
        store = ArtifactStore(tmp_path / "store")
        item = _fourfold_item(_packet(compiled, store))

        digest = item.evidence_locator.rsplit(":", 1)[-1]
        assert store.locator_path(digest).exists()

    def test_the_item_provenance_binds_the_locator_digest(self, compiled, tmp_path):
        """It used to arrive for free: the synthesised locator's digest WAS the
        snapshot digest, so the binding looked satisfied without meaning
        anything."""
        store = ArtifactStore(tmp_path / "store")
        item = _fourfold_item(_packet(compiled, store))

        digest = item.evidence_locator.rsplit(":", 1)[-1]
        assert digest in item.provenance.input_digests
        assert digest != compiled.snapshot.digest


class TestTheLocatorIsDerivable:
    """A verifier holding a packet and a snapshot, and no store, must still be
    able to say what the locator has to be -- otherwise the record's own name
    for its bytes is unfalsifiable."""

    def test_the_same_snapshot_mints_the_same_locator_in_another_store(
            self, compiled, tmp_path):
        first = _fourfold_item(_packet(compiled, ArtifactStore(tmp_path / "a")))
        second = _fourfold_item(_packet(compiled, ArtifactStore(tmp_path / "b")))
        assert first.evidence_locator == second.evidence_locator

    def test_the_packet_digest_does_not_depend_on_the_store(self, compiled, tmp_path):
        """If it did, a promotion record would change identity by being filed
        somewhere else."""
        assert (_packet(compiled, ArtifactStore(tmp_path / "a")).digest
                == _packet(compiled, ArtifactStore(tmp_path / "b")).digest)

    def test_the_derivation_matches_what_was_stored(self, compiled, tmp_path):
        store = ArtifactStore(tmp_path / "store")
        item = _fourfold_item(_packet(compiled, store))
        assert item.evidence_locator == _snapshot_locator(compiled.snapshot)


class TestAnUnstorableSnapshotIsRefused:
    """No packet beats a packet whose central artifact points at nothing."""

    def test_a_store_that_cannot_take_the_bytes_produces_no_packet(
            self, compiled, tmp_path):
        blocker = tmp_path / "store"
        blocker.write_text("this is a file, not a store root")
        with pytest.raises(FourfoldEvidenceUnstorable) as caught:
            _packet(compiled, ArtifactStore(blocker))
        assert "refusing to mint an evidence locator" in str(caught.value)

    def test_a_reachable_store_does_produce_one(self, compiled, tmp_path):
        """The control. Without it, an assembler that refused EVERY store
        would satisfy the test above."""
        packet = _packet(compiled, ArtifactStore(tmp_path / "store"))
        assert packet.evaluation_status == "passed"
        assert _fourfold_item(packet).evidence_locator.startswith(
            "artifact-locator:sha256:")


class TestTheVerifierResolvesWhenGivenAStore:

    def test_a_packet_whose_blob_is_gone_is_refused(self, compiled, tmp_path):
        store = ArtifactStore(tmp_path / "store")
        packet = _packet(compiled, store)
        item = _fourfold_item(packet)
        blob = store.blob_path(item.output_sha256)
        blob.unlink()

        with pytest.raises(FourfoldEvidenceMismatch) as caught:
            verify_fourfold_evidence_packet(
                packet, snapshot=compiled.snapshot,
                expectation=_expectation(compiled), store=store)
        assert "snapshot_locator_unresolvable" in str(caught.value)

    def test_the_same_packet_passes_while_the_blob_is_there(
            self, compiled, tmp_path):
        """The control for the test above."""
        store = ArtifactStore(tmp_path / "store")
        packet = _packet(compiled, store)
        verify_fourfold_evidence_packet(
            packet, snapshot=compiled.snapshot,
            expectation=_expectation(compiled), store=store)

    def test_a_storeless_verification_is_still_allowed(self, compiled, tmp_path):
        """A promotion reviewer with the packet and the snapshot and no store
        keeps the derivation check; only the resolution check needs bytes."""
        store = ArtifactStore(tmp_path / "store")
        packet = _packet(compiled, store)
        store.blob_path(_fourfold_item(packet).output_sha256).unlink()
        verify_fourfold_evidence_packet(
            packet, snapshot=compiled.snapshot,
            expectation=_expectation(compiled))
