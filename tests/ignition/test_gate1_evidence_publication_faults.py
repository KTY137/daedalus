"""Real-door material publication failures preserve the previous latest.

The candidate and every check run normally. Only the selected output/packet
CAS write fails. This is a storage refusal, which must propagate without
publishing a replacement refusal receipt. Structural or missing-contract
refusals whose storage succeeds have a different, separately tested contract.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from daedalus.ignition import gate1
from daedalus.kernel.attempt_execution import AttemptResult
from daedalus.kernel.source_trees import SourceTreeStore
from daedalus.schemas import EvidencePacket
from daedalus.spine.envelope import canonical_sha
from daedalus.storage import ArtifactStore, ArtifactStoreError


NOW = "2026-09-06T00:00:00Z"


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*") if path.is_file()
    }


@pytest.mark.parametrize("stage", ["output", "packet"])
def test_material_publication_failure_preserves_latest_and_prior_evidence(
    tmp_path, monkeypatch, record_property, door, stage,
):
    source = tmp_path / "source"
    shutil.copytree(gate1.DEFAULT_FIXTURE, source)
    source_before = _files(source)
    fixture_before = gate1.tree_digest(gate1.DEFAULT_FIXTURE)
    receipts, workspace = tmp_path / "receipts", tmp_path / "workspace"
    mission_root = receipts / gate1.SESSION_MISSION_ID
    store = ArtifactStore(mission_root / "store")
    sentinel = b"an earlier measured output survives a later storage failure\n"
    prior_locator = store.put_bytes(
        sentinel,
        provenance={
            "origin": "tests.ignition.publication-fault",
            "source_revision": fixture_before,
            "created_at": NOW,
            "input_digests": [hashlib.sha256(sentinel).hexdigest()],
            "trace_id": None,
        },
    )
    store_before = _files(store.root)
    latest = mission_root / "receipt.json"
    # Opaque prior observation; no fabricated successful mission or replay.
    prior_bytes = b'{"legacy-observation": "prior latest bytes"}\r\n'
    latest.write_bytes(prior_bytes)
    observations = tmp_path / "publication-observations"
    observations.mkdir()
    (observations / "prior-latest.bin").write_bytes(prior_bytes)
    fault_message = f"G1-IGNITION-04 injected {stage} CAS publication failure"
    captures, compiles, contracts = [], [], []
    reports, actual_puts, faults = [], [], []
    real_capture = SourceTreeStore.capture_tree
    real_compile = gate1.compile_reference_project
    real_contract_set = AttemptResult.contract_set
    real_store_check = gate1._store_check
    real_put = ArtifactStore.put_bytes

    def observe_capture(target, candidate, **kwargs):
        captured_revision = gate1.tree_digest(Path(candidate))
        captured = real_capture(target, candidate, **kwargs)
        captures.append((target, Path(candidate), dict(kwargs), captured, captured_revision))
        return captured

    def observe_compile(candidate, **kwargs):
        entry_revision = gate1.tree_digest(Path(candidate))
        compiled = real_compile(candidate, **kwargs)
        compiles.append((dict(kwargs), compiled, entry_revision))
        return compiled

    def observe_contract_set(attempt):
        actual = real_contract_set(attempt)
        contracts.append(actual)
        return actual

    def observe_store_check(target, report, **kwargs):
        reports.append((report, dict(kwargs)))
        return real_store_check(target, report, **kwargs)

    def fail_selected_put(target, data, **kwargs):
        raw = bytes(data)
        packet_body = None
        if target.root == store.root and stage == "packet":
            try:
                parsed = json.loads(raw)
            except (ValueError, UnicodeError):
                parsed = None
            if (isinstance(parsed, dict)
                    and parsed.get("contract_type") == "daedalus.evidence"
                    and parsed.get("packet_id") == "gate1-voltage-evidence"):
                packet_body = parsed
        is_output = (
            stage == "output"
            and (kwargs.get("metadata") or {}).get("kind") == "ignition_check_output"
        )
        if target.root == store.root and (is_output or packet_body is not None):
            faults.append((raw, dict(kwargs), packet_body))
            (observations / f"refused-{stage}-{len(faults)}.bin").write_bytes(raw)
            if stage == "output":
                raise ArtifactStoreError(fault_message)
            raise OSError(fault_message)
        locator = real_put(target, raw, **kwargs)
        if target.root == store.root:
            actual_puts.append((locator, raw))
            (observations / f"stored-{locator.artifact_sha256}.bin").write_bytes(raw)
        return locator

    result, caught = None, None
    with monkeypatch.context() as patcher:
        patcher.setattr(SourceTreeStore, "capture_tree", observe_capture)
        patcher.setattr(gate1, "compile_reference_project", observe_compile)
        patcher.setattr(AttemptResult, "contract_set", observe_contract_set)
        patcher.setattr(gate1, "_store_check", observe_store_check)
        patcher.setattr(ArtifactStore, "put_bytes", fail_selected_put)
        try:
            result = door(
                fixture_root=source, receipt_root=receipts, workspace=workspace,
                collected_at=NOW, gate_timeout_s=300,
            )
        except Exception as exc:  # Retain the outcome before any new assertion.
            caught = exc

    measurement = {
        "stage": stage, "gate_timeout_s": 300, "collected_at": NOW,
        "fault_count": len(faults), "returned_result": result is not None,
        "exception_type": type(caught).__name__ if caught else None,
        "exception_message": str(caught) if caught else None,
        "capture_sha256s": [row[3].ref.sha256 for row in captures],
        "capture_entry_revisions": [row[4] for row in captures],
        "compiled_snapshot_sha256s": [row[1].snapshot.digest for row in compiles],
        "compile_entry_revisions": [row[2] for row in compiles],
        "actual_attempt_ids": [c.attempt.attempt_id for c in contracts if c is not None],
        "prior_latest_unchanged": latest.exists() and latest.read_bytes() == prior_bytes,
        "prior_store_unchanged": all(
            (store.root / rel).exists() and (store.root / rel).read_bytes() == raw
            for rel, raw in store_before.items()
        ),
        "actual_stored_locators": [locator.portable_summary() for locator, _ in actual_puts],
    }
    record_property("material_publication_failure", json.dumps(measurement, sort_keys=True))
    record_property("material_publication_evidence_dir", str(observations))
    (observations / "measurement.json").write_text(
        json.dumps(measurement, indent=2), encoding="utf-8",
    )

    assert len(faults) == 1, "the selected actual material publication must be reached once"
    assert isinstance(caught, (ArtifactStoreError, OSError)), repr(caught)
    assert fault_message in str(caught)
    assert result is None, "a failed material write must not publish a replacement result"
    assert latest.read_bytes() == prior_bytes
    for relative, raw in store_before.items():
        assert (store.root / relative).read_bytes() == raw
    assert store.verify(prior_locator) == prior_locator
    assert store.get_bytes(prior_locator.uri) == sentinel
    for locator, raw in actual_puts:
        assert store.verify(locator) == locator
        assert store.get_bytes(locator.uri) == raw
    assert _files(source) == source_before
    assert gate1.tree_digest(gate1.DEFAULT_FIXTURE) == fixture_before

    candidate_store, candidate_path, _, candidate, captured_revision = next(
        row for row in captures if row[2].get("origin") == "daedalus.ignition.gate1-candidate"
    )
    compile_arguments, compiled, compile_entry_revision = next(
        row for row in compiles if row[0].get("trace_id") == "gate1-bias-voltage-candidate"
    )
    assert candidate_path == workspace / "candidate"
    assert compile_arguments["source_tree_sha256"] == candidate.ref.sha256
    # Normal checks can create bytecode in this mutable workspace. Compare
    # the measured entry states that supplied the retained candidate identity.
    assert compile_arguments["source_revision"] == captured_revision == compile_entry_revision
    assert candidate_store.load_tree(candidate.ref) == candidate.manifest
    assert candidate.manifest.source_revision == captured_revision
    assert all(plane.status == "complete" for plane in compiled.snapshot.planes)
    assert len(contracts) == 2 and all(c is not None and c.complete for c in contracts)
    if stage == "output":
        raw, kwargs, _ = faults[0]
        observed = next(report for report, _ in reports
                        if report.kind == kwargs["metadata"]["check_kind"])
        assert raw == observed.output_bytes
        assert hashlib.sha256(raw).hexdigest() == observed.output_sha256
        assert kwargs["provenance"]["source_revision"] == compile_arguments["source_revision"]
    else:
        raw, _, packet_body = faults[0]
        packet = EvidencePacket.from_dict(packet_body)
        assert raw == packet.to_json().encode("utf-8")
        assert packet.candidate_artifact_sha256 == candidate.ref.sha256
        assert packet.candidate_artifact_locator == candidate.ref.locator
        assert packet.source_revision == compile_arguments["source_revision"]
        for field, member in (("attempt_contract_sha256", "attempt"),
                              ("policy_decision_sha256", "policy")):
            assert getattr(packet, field) == canonical_sha({
                "schema": f"daedalus-ignition-{member}-chain/1",
                "digests": [getattr(c, member).digest for c in contracts],
            })
        structural = next(item for item in packet.items
                          if item.evaluator == "fourfold.snapshot-binding")
        assert structural.output_sha256 == compiled.snapshot.digest
        for item in packet.items:
            locator = store.load_locator(item.evidence_locator.rsplit(":", 1)[-1])
            assert store.verify(locator) == locator
            assert locator.artifact_sha256 == item.output_sha256
