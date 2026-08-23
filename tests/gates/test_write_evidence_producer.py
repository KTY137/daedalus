"""The in-process producer: what it takes before a surface may be central.

The producer lives in ``scripts/declare_write_surfaces.py`` because that script
is already the one thing in this repository that produces
``SurfaceClassification`` rows and the evidence objects they bind; a second
producer of the same artifact class would be a second answer to "what is this
surface".  What is tested here is the gate in front of the central row, not the
dominance analysis (``tests/test_declare_write_surfaces.py`` owns that).

Every test needs a real granted lease in a real on-disk ledger, so pytest's
``tmp_path``/``monkeypatch`` are forced, exactly as in
``tests/kernel/test_write_evidence_records.py``.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from daedalus.gates.repository_write_classification import (
    EvidenceKind,
    GuardDisposition,
    TargetDisposition,
    surface_classification_verdict,
)
from daedalus.gates.repository_write_inventory_v2 import RepositoryWriteSurface
from daedalus.kernel import offload_lease as ol
from daedalus.spine.envelope import canonical_json
from daedalus.spine.killswitch import KillSwitch

REPO_ROOT = Path(__file__).resolve().parents[2]
REVISION = "0" * 40
ISSUED = "2026-08-23T12:00:00.000000+00:00"
MECHANISM = "gated_writes.run_write_wave: one TaskAttempt worktree per write task"


def _load_generator():
    path = REPO_ROOT / "scripts" / "declare_write_surfaces.py"
    spec = importlib.util.spec_from_file_location("declare_write_surfaces", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["declare_write_surfaces"] = module
    spec.loader.exec_module(module)
    return module


GEN = _load_generator()


@pytest.fixture
def control(tmp_path, monkeypatch):
    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(tmp_path / "killswitch"))
    switch = KillSwitch(repo_root=str(REPO_ROOT))
    switch.arm(note="write-evidence producer test")
    return switch


def _lease(switch, attempt_id):
    return ol.acquire_wave_offload_lease(
        str(REPO_ROOT),
        source_revision=REVISION,
        mission_id="producer-test",
        attempt_id=attempt_id,
        positions=1,
        lanes=("ollama",),
        max_spend_usd=0.25,
        timeout_s=900,
        writable_paths=("docs/x.md",),
        contained=True,
        containment_evidence=MECHANISM,
        switch=switch,
    )


def _store():
    return ol.write_evidence_root(str(REPO_ROOT), REVISION)


def _evidence():
    return GEN.load_retained_write_evidence(
        _store(),
        source_revision=REVISION,
        control_root_sha256=ol.write_root_identity_sha256(
            ol.control_root(str(REPO_ROOT))
        ),
    )


def _terminalise(lease):
    execution = lease.execution_for(0, ("docs/x.md",))
    start = lease.authorization.begin_effect(execution)
    lease.authorization.finish_effect(start.receipt, outcome="COMPLETED")
    records, refusals = ol.harvest_effect_lease_terminal_records(
        _store(),
        control_root_path=ol.control_root(str(REPO_ROOT)),
        keyring=ol.issuer_keyring(str(REPO_ROOT)),
    )
    assert refusals == () and len(records) == 1
    return execution, records[0]


def _surface():
    return RepositoryWriteSurface(
        path="daedalus/offload.py",
        line=1,
        column=0,
        origin="base_v1",
        kind="call",
        callee="offload.write",
        operation="write",
        blocking=True,
    )


def _anchor(surface):
    return GEN.source_anchor_evidence(REVISION, surface, "1" * 64)


# --------------------------------------------------------------------------- #
# only a replayed, terminal, non-runtime execution opens a door                 #
# --------------------------------------------------------------------------- #
def test_a_granted_only_lease_authenticates_no_door(control):
    lease = _lease(control, "p-granted")
    assert lease.granted
    doors, refusals = GEN.authenticated_doors(
        REPO_ROOT, _evidence(), keyring=ol.issuer_keyring(str(REPO_ROOT))
    )
    assert doors == {}
    # There is nothing to refuse yet either: no terminal record was retained,
    # because no execution ever terminalised.
    assert refusals == ()
    assert _evidence().terminals == ()


def test_a_terminal_execution_authenticates_its_door(control):
    lease = _lease(control, "p-terminal")
    execution, terminal = _terminalise(lease)
    doors, refusals = GEN.authenticated_doors(
        REPO_ROOT, _evidence(), keyring=ol.issuer_keyring(str(REPO_ROOT))
    )
    assert refusals == ()
    assert set(doors) == {"python.offload"}
    door = doors["python.offload"]
    assert door.execution_id == execution.execution_id
    assert door.terminal["terminal_state"] == "completed"
    # The contracts are the ones the lease was actually issued under, read off
    # the retained decisions -- not the registry row's declaration.
    assert door.guard_contracts == (
        "budget.process_guard",
        "containment.attempt",
        "provider.egress_policy",
        "provider.write_policy",
    )
    assert door.implementation_target == ol.ISSUER_TARGET


def test_a_terminal_record_naming_another_execution_is_refused(control):
    """A signature is not a replay, and neither is a retained field: the
    producer re-derives the execution identity from the ledger."""

    lease = _lease(control, "p-swapped")
    _terminalise(lease)
    path = sorted((_store() / "lease-terminal").glob("*.json"))[0]
    body = json.loads(path.read_text(encoding="utf-8"))
    body["execution_id"] = body["execution_id"] + "-forged"
    body["record_sha256"] = GEN._record_sha256(body)
    path.write_bytes(canonical_json(body).encode("ascii"))

    evidence = _evidence()
    assert len(evidence.terminals) == 1  # the digest still binds the body
    doors, refusals = GEN.authenticated_doors(
        REPO_ROOT, evidence, keyring=ol.issuer_keyring(str(REPO_ROOT))
    )
    assert doors == {}
    assert any("names another execution" in reason for reason in refusals)


def test_harvesting_twice_republishes_one_record(control):
    """The record is about a past fact, so its identity must not move with the
    harvest's clock -- otherwise every re-harvest leaves a near-identical file
    and the producer sees two terminal records for one execution."""

    lease = _lease(control, "p-twice")
    _terminalise(lease)
    first = sorted((_store() / "lease-terminal").glob("*.json"))
    ol.harvest_effect_lease_terminal_records(
        _store(),
        control_root_path=ol.control_root(str(REPO_ROOT)),
        keyring=ol.issuer_keyring(str(REPO_ROOT)),
    )
    assert sorted((_store() / "lease-terminal").glob("*.json")) == first
    assert len(_evidence().terminals) == 1


def test_a_terminal_record_without_its_subject_is_refused(control):
    lease = _lease(control, "p-orphan")
    _terminalise(lease)
    for path in (_store() / "lease-subject").glob("*.json"):
        path.unlink()
    doors, refusals = GEN.authenticated_doors(
        REPO_ROOT, _evidence(), keyring=ol.issuer_keyring(str(REPO_ROOT))
    )
    assert doors == {}
    assert any("no retained subject record" in reason for reason in refusals)


# --------------------------------------------------------------------------- #
# the row a document cannot express                                             #
# --------------------------------------------------------------------------- #
def test_the_central_row_holds_an_admission_and_no_runtime_receipt(control, tmp_path):
    lease = _lease(control, "p-row")
    _terminalise(lease)
    doors, _ = GEN.authenticated_doors(
        REPO_ROOT, _evidence(), keyring=ol.issuer_keyring(str(REPO_ROOT))
    )
    evidence = _evidence()
    surface = _surface()
    row, blobs = GEN.central_row(
        doors["python.offload"],
        surface,
        _anchor(surface),
        evidence.disjointness[0],
        source_revision=REVISION,
        collector_secret_bytes=GEN.collector_secret(tmp_path / "collector.key"),
        issued_at=ISSUED,
    )
    assert row.guard is GuardDisposition.CENTRAL
    assert row.target is TargetDisposition.CHECKOUT_EXTERNAL
    assert row.production_reachable is True
    assert row.non_runtime_conformity is not None
    kinds = {item.kind for item in row.evidence}
    assert EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT not in kinds
    assert {
        EvidenceKind.SOURCE_ANCHOR,
        EvidenceKind.GUARD_CONTRACT,
        EvidenceKind.EFFECT_LEASE_RECEIPT,
        EvidenceKind.PRIMARY_CHECKOUT_DISJOINTNESS_RECEIPT,
    } <= kinds
    assert row.candidate_blockers == ()
    assert surface_classification_verdict(row) == "cleared:central"
    # Every minted object is real CAS: the materialization verifier replays it.
    from daedalus.gates.repository_write_evidence_materialization import (
        materialize_repository_write_evidence,
    )
    from daedalus.gates.repository_write_classification import (
        RepositoryWriteClassificationReport,
    )

    report = RepositoryWriteClassificationReport(
        source_revision=REVISION,
        inventory_digest="6" * 64,
        scan_input_sha256="7" * 64,
        inventory_surface_count=1,
        classifications=(row,),
        missing_surfaces=(),
    )
    materialization = materialize_repository_write_evidence(report, blobs)
    assert materialization.missing_locators == ()
    assert materialization.materialization_complete


def test_the_declaration_file_refuses_to_carry_an_admitted_row(control, tmp_path):
    """The wire has no key for the admission, so writing the row would drop the
    one thing that makes it legal."""

    lease = _lease(control, "p-wire")
    _terminalise(lease)
    doors, _ = GEN.authenticated_doors(
        REPO_ROOT, _evidence(), keyring=ol.issuer_keyring(str(REPO_ROOT))
    )
    surface = _surface()
    row, _ = GEN.central_row(
        doors["python.offload"],
        surface,
        _anchor(surface),
        _evidence().disjointness[0],
        source_revision=REVISION,
        collector_secret_bytes=GEN.collector_secret(tmp_path / "collector.key"),
        issued_at=ISSUED,
    )
    derivation = GEN.Derivation(
        source_revision=REVISION,
        inventory_digest="6" * 64,
        inventory_surface_count=1,
        rows=(row,),
        blobs={},
        per_door=(),
        skipped_doors=(),
        undominated_in_door_modules=0,
    )
    with pytest.raises(GEN.DeclarationError, match="no wire shape"):
        GEN.declaration_document(derivation)
    # ``to_dict`` is where the field would have to appear, and it does not.
    assert "non_runtime_conformity" not in row.to_dict()


def test_an_admission_signed_with_another_key_is_refused(control, tmp_path):
    lease = _lease(control, "p-forged-collector")
    _terminalise(lease)
    doors, _ = GEN.authenticated_doors(
        REPO_ROOT, _evidence(), keyring=ol.issuer_keyring(str(REPO_ROOT))
    )
    from daedalus.gates.repository_write_classification import (
        NonRuntimeConformityAdmission,
        RepositoryWriteClassificationError,
        issue_non_runtime_conformity_binding,
        surface_binding_sha256,
    )

    surface = _surface()
    binding = issue_non_runtime_conformity_binding(
        source_revision=REVISION,
        surface_sha256=surface_binding_sha256(REVISION, surface),
        execution_id=doors["python.offload"].execution_id,
        collector_id=GEN.COLLECTOR_ID,
        collector_key_id=GEN.COLLECTOR_KEY_ID,
        issued_at=ISSUED,
        secret=b"a-different-collector-secret-32-bytes-long",
    )
    with pytest.raises(RepositoryWriteClassificationError, match="does not verify"):
        NonRuntimeConformityAdmission(
            binding=binding,
            subject=doors["python.offload"].replay_subject,
            collector_secrets={
                GEN.COLLECTOR_KEY_ID: GEN.collector_secret(tmp_path / "collector.key")
            },
        )
