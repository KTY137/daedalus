from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from daedalus.gates import release as release_module
from daedalus.gates.release import (
    Gate0ReleaseBindingError,
    Gate0ReleaseBlocked,
    Gate0ReleaseReceipt,
    Gate0ReleaseSignatureError,
    issue_gate0_release_receipt,
    load_gate0_release_receipt,
    load_strict_gate_report,
    parse_gate0_release_receipt,
    strict_gate_report_artifact_sha256,
    validate_strict_gate_report_payload,
    verify_gate0_release_receipt,
)
from daedalus.gates.report import GateReport
from daedalus.spine.writer_inventory import scan_event_store_writers

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "gates" / "test_evidence_trust_bundle.py"
RELEASE_SECRET = b"external-release-verifier-secret-material-32-bytes"
VERIFIER_KEY = ("external-gate0-release-verifier", "release-key-1")


def _load_fixture():
    name = "daedalus_test_release_evidence_fixture"
    spec = importlib.util.spec_from_file_location(name, FIXTURE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fixture = _load_fixture()


def _install_production_package(root: Path) -> None:
    package = root / "daedalus"
    package.mkdir(exist_ok=True)
    (package / "__init__.py").write_text("", encoding="utf-8")


def _report(root: Path, **changes) -> GateReport:
    revision = changes.get("source_revision", fixture.REVISION)
    inventory = scan_event_store_writers(root, source_revision=revision)
    values = {
        "gate": 0,
        "source_revision": fixture.REVISION,
        "registry_sha256": fixture.REGISTRY,
        "security_boundary_claimed": True,
        "owner_approval_enforced": True,
        "event_store_writer_inventory_sha256": inventory.digest,
        "event_store_writer_failures": tuple(
            f"{site.path}:{site.line}:{site.column}:{site.kind}:{site.callee}"
            for site in inventory.blockers
        ),
    }
    values.update(changes)
    return GateReport(**values)


def _release_index(index, report: GateReport):
    report_artifact = fixture._artifact(
        "gate-report-release",
        "gate-report",
        content=strict_gate_report_artifact_sha256(report),
        locator="a" * 64,
    )
    effect_inventory = fixture._artifact(
        "effect-inventory-release",
        "effect-inventory",
        content=fixture.REGISTRY,
        locator="b" * 64,
    )
    artifacts = tuple(
        sorted(
            (*index.artifacts, report_artifact, effect_inventory),
            key=lambda item: item.artifact_id,
        )
    )
    requirements = tuple(
        sorted(
            set(index.required_artifact_kinds)
            | {"gate-report", "effect-inventory"}
        )
    )
    provenance = fixture._provenance(
        "tests.gate-evidence-index",
        fixture.PLAN,
        index.registry_sha256,
        *(item.digest for item in artifacts),
    )
    return dataclasses.replace(
        index,
        required_artifact_kinds=requirements,
        artifacts=artifacts,
        provenance=provenance,
    )


def _inputs(
    tmp_path: Path,
    *,
    owner_present: bool = True,
    report_changes: dict | None = None,
):
    root = fixture._repo(tmp_path)
    _install_production_package(root)
    report = _report(root, **(report_changes or {}))
    index = _release_index(
        fixture._index(owner_present=owner_present),
        report,
    )
    bundle = fixture._bundle(index, root)
    return root, report, index, bundle


def _issue(report, index, bundle, root, **changes):
    values = {
        "repo_root": root,
        "collector_keyring": {fixture.COLLECTOR_KEY: fixture.SECRET},
        "expected_collector_id": "external-release-collector",
        "expected_workflow_paths": {
            "gate0-contracts": fixture.WORKFLOW_PATH
        },
        "current_revision": fixture.REVISION,
        "current_tree_revision": fixture.TREE,
        "receipt_id": "gate0-release-receipt-1",
        "verifier_id": "external-gate0-release-verifier",
        "verifier_key_id": "release-key-1",
        "verifier_secret": RELEASE_SECRET,
        "verified_at": fixture.NOW + timedelta(minutes=2),
    }
    values.update(changes)
    return issue_gate0_release_receipt(report, index, bundle, **values)


def _verify(receipt, report, index, bundle, root, **changes):
    values = {
        "repo_root": root,
        "collector_keyring": {fixture.COLLECTOR_KEY: fixture.SECRET},
        "expected_collector_id": "external-release-collector",
        "expected_workflow_paths": {
            "gate0-contracts": fixture.WORKFLOW_PATH
        },
        "verifier_keyring": {VERIFIER_KEY: RELEASE_SECRET},
        "expected_verifier_id": "external-gate0-release-verifier",
        "current_revision": fixture.REVISION,
        "current_tree_revision": fixture.TREE,
        "now": fixture.NOW + timedelta(minutes=3),
    }
    values.update(changes)
    return verify_gate0_release_receipt(
        receipt,
        report,
        index,
        bundle,
        **values,
    )


def _canonical_report_digest(payload: dict) -> str:
    body = dict(payload)
    body.pop("report_sha256", None)
    return hashlib.sha256(
        json.dumps(
            body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def _resign(receipt: Gate0ReleaseReceipt, **changes) -> Gate0ReleaseReceipt:
    payload = receipt.to_dict()
    payload.update(changes)
    payload["signature_sha256"] = "0" * 64
    if "verified_at" in changes:
        payload["provenance"]["created_at"] = payload["verified_at"]
    digests = tuple(
        sorted(
            {
                payload["gate_report_sha256"],
                payload["gate_report_artifact_sha256"],
                payload["registry_sha256"],
                payload["evidence_index_sha256"],
                payload["trust_bundle_sha256"],
                payload["requirements_sha256"],
            }
        )
    )
    payload["provenance"]["input_digests"] = list(digests)
    placeholder = Gate0ReleaseReceipt.from_dict(payload)
    return dataclasses.replace(
        placeholder,
        signature_sha256=release_module._signature(
            placeholder.signing_digest,
            RELEASE_SECRET,
        ),
    )


def test_release_receipt_round_trip_signature_and_exact_bindings(
    tmp_path: Path,
) -> None:
    root, report, index, bundle = _inputs(tmp_path)
    receipt = _issue(report, index, bundle, root)

    assert report.closed is True
    assert Gate0ReleaseReceipt.from_dict(receipt.to_dict()) == receipt
    assert receipt.signature_sha256 != "0" * 64
    assert receipt.gate_report_sha256 == report.to_dict()["report_sha256"]
    assert receipt.evidence_index_sha256 == index.digest
    assert receipt.trust_bundle_sha256 == bundle.digest
    _verify(receipt, report, index, bundle, root)

    path = tmp_path / "release-receipt.json"
    path.write_text(json.dumps(receipt.to_dict()), encoding="utf-8")
    assert load_gate0_release_receipt(path) == receipt


def test_strict_gate_report_loader_rejects_coercion_and_derived_field_forgery(
    tmp_path: Path,
) -> None:
    root, report, _, _ = _inputs(tmp_path)
    payload = report.to_dict()

    string_bool = dict(payload)
    string_bool["closed"] = "true"
    with pytest.raises(ValueError, match="boolean"):
        validate_strict_gate_report_payload(string_bool)

    string_array = dict(payload)
    string_array["diagnostics"] = "looks-good"
    with pytest.raises(ValueError, match="array"):
        validate_strict_gate_report_payload(string_array)

    extra = dict(payload)
    extra["trusted"] = True
    with pytest.raises(ValueError, match="fields"):
        validate_strict_gate_report_payload(extra)

    forged_closed = dict(payload)
    forged_closed["closed"] = False
    forged_closed["report_sha256"] = _canonical_report_digest(forged_closed)
    with pytest.raises(ValueError, match="closed value"):
        validate_strict_gate_report_payload(forged_closed)

    forged_blockers = dict(payload)
    forged_blockers["blockers"] = ["foreign:claim"]
    forged_blockers["report_sha256"] = _canonical_report_digest(
        forged_blockers
    )
    with pytest.raises(ValueError, match="blockers"):
        validate_strict_gate_report_payload(forged_blockers)

    malformed_revision = dict(payload)
    malformed_revision["source_revision"] = "working-tree"
    malformed_revision["report_sha256"] = _canonical_report_digest(
        malformed_revision
    )
    with pytest.raises(ValueError, match="source_revision"):
        validate_strict_gate_report_payload(malformed_revision)

    duplicate = tmp_path / "duplicate-report.json"
    duplicate.write_text(
        '{"schema":"daedalus-gate-report/2","schema":"foreign"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_strict_gate_report(duplicate)
    assert root.exists()


def test_open_report_and_missing_owner_evidence_refuse_release(
    tmp_path: Path,
) -> None:
    root, open_report, index, bundle = _inputs(
        tmp_path,
        report_changes={"security_boundary_claimed": False},
    )
    with pytest.raises(Gate0ReleaseBlocked, match="security_boundary_claimed:false"):
        _issue(open_report, index, bundle, root)

    no_owner_root, no_owner_report, no_owner_index, no_owner_bundle = _inputs(
        tmp_path / "no-owner",
        owner_present=False,
    )
    with pytest.raises(ValueError, match="owner-decision:missing"):
        _issue(
            no_owner_report,
            no_owner_index,
            no_owner_bundle,
            no_owner_root,
        )


def test_report_revision_registry_and_current_tree_mismatches_refuse(
    tmp_path: Path,
) -> None:
    root, report, index, bundle = _inputs(tmp_path)
    with pytest.raises(Gate0ReleaseBindingError, match="report_source_revision"):
        _issue(
            _report(root, source_revision="e" * 40),
            index,
            bundle,
            root,
        )
    with pytest.raises(Gate0ReleaseBindingError, match="report_registry_sha256"):
        _issue(
            _report(root, registry_sha256="e" * 64),
            index,
            bundle,
            root,
        )
    with pytest.raises(Gate0ReleaseBindingError, match="source_tree_revision"):
        _issue(
            report,
            index,
            bundle,
            root,
            current_tree_revision="e" * 40,
        )


def test_live_writer_inventory_is_recomputed_before_release(tmp_path: Path) -> None:
    root, report, index, bundle = _inputs(tmp_path)
    receipt = _issue(report, index, bundle, root)

    (root / "daedalus" / "legacy_writer.py").write_text(
        "from daedalus.spine import SpineLedger\n"
        "SpineLedger('state.sqlite3')\n",
        encoding="utf-8",
    )
    with pytest.raises(
        Gate0ReleaseBindingError,
        match="event_store_writer_inventory_sha256",
    ):
        _verify(receipt, report, index, bundle, root)


def test_forged_writer_inventory_digest_refuses_even_when_report_is_signed(
    tmp_path: Path,
) -> None:
    root, _, _, _ = _inputs(tmp_path / "base")
    forged = _report(
        root,
        event_store_writer_inventory_sha256="e" * 64,
    )
    index = _release_index(fixture._index(), forged)
    bundle = fixture._bundle(index, root)
    with pytest.raises(
        Gate0ReleaseBindingError,
        match="event_store_writer_inventory_sha256",
    ):
        _issue(forged, index, bundle, root)


def test_workflow_drift_is_rechecked_before_receipt_issue_and_replay(
    tmp_path: Path,
) -> None:
    root, report, index, bundle = _inputs(tmp_path)
    receipt = _issue(report, index, bundle, root)
    (root / fixture.WORKFLOW_PATH).write_text(
        "name: replaced\non: [push]\njobs: {}\n",
        encoding="utf-8",
    )
    with pytest.raises(Exception, match="definition digest mismatch"):
        _verify(receipt, report, index, bundle, root)


def test_verifier_key_scope_signature_and_expected_identity_refuse(
    tmp_path: Path,
) -> None:
    root, report, index, bundle = _inputs(tmp_path)
    receipt = _issue(report, index, bundle, root)

    with pytest.raises(Gate0ReleaseSignatureError, match="unknown"):
        _verify(receipt, report, index, bundle, root, verifier_keyring={})
    with pytest.raises(Gate0ReleaseSignatureError, match="unknown"):
        _verify(
            receipt,
            report,
            index,
            bundle,
            root,
            verifier_keyring={
                ("foreign-verifier", "release-key-1"): RELEASE_SECRET
            },
        )
    tampered = dataclasses.replace(receipt, signature_sha256="e" * 64)
    with pytest.raises(Gate0ReleaseSignatureError, match="signature"):
        _verify(tampered, report, index, bundle, root)
    with pytest.raises(Gate0ReleaseBindingError, match="verifier_id"):
        _verify(
            receipt,
            report,
            index,
            bundle,
            root,
            expected_verifier_id="foreign-verifier",
        )


def test_receipt_cannot_be_repacked_for_another_report_or_index(
    tmp_path: Path,
) -> None:
    root, report, index, bundle = _inputs(tmp_path)
    receipt = _issue(report, index, bundle, root)

    other_report = _report(root, diagnostics=("different-release-observation",))
    with pytest.raises(
        Gate0ReleaseBindingError,
        match="gate_report_artifact_sha256",
    ):
        _verify(receipt, other_report, index, bundle, root)

    repacked = _resign(receipt, gate_report_sha256="f" * 64)
    with pytest.raises(Gate0ReleaseBindingError, match="gate_report_sha256"):
        _verify(repacked, report, index, bundle, root)

    foreign_index = fixture._index(registry="e" * 64)
    with pytest.raises(Gate0ReleaseBindingError):
        _verify(receipt, report, foreign_index, bundle, root)


def test_future_and_pre_bundle_signed_receipts_refuse(tmp_path: Path) -> None:
    root, report, index, bundle = _inputs(tmp_path)
    receipt = _issue(report, index, bundle, root)

    future = _resign(
        receipt,
        verified_at=(fixture.NOW + timedelta(minutes=5)).isoformat(),
    )
    with pytest.raises(Gate0ReleaseBindingError, match="future"):
        _verify(
            future,
            report,
            index,
            bundle,
            root,
            now=fixture.NOW + timedelta(minutes=3),
        )

    predating = _resign(
        receipt,
        verified_at=fixture.NOW.isoformat(),
    )
    with pytest.raises(Gate0ReleaseBindingError, match="predates"):
        _verify(predating, report, index, bundle, root)


def test_receipt_wire_rejects_extra_fields_duplicate_keys_and_non_objects(
    tmp_path: Path,
) -> None:
    root, report, index, bundle = _inputs(tmp_path)
    receipt = _issue(report, index, bundle, root)
    payload = receipt.to_dict()
    payload["closed"] = True
    with pytest.raises(ValueError, match="unknown field"):
        parse_gate0_release_receipt(payload)
    with pytest.raises(ValueError, match="object"):
        parse_gate0_release_receipt([])  # type: ignore[arg-type]

    duplicate = tmp_path / "duplicate-receipt.json"
    duplicate.write_text(
        '{"contract_type":"x","contract_type":"y"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_gate0_release_receipt(duplicate)
