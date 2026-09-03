from __future__ import annotations

import dataclasses
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import daedalus.gates.repository.write_guard_structure as guard_structure
from daedalus.gates.guard_implementation_manifest import (
    GuardImplementationManifestBindingError,
    GuardImplementationManifestSignatureError,
    GuardImplementationRecord,
    issue_guard_implementation_manifest,
)
from daedalus.gates.python_target_structure import PythonTargetBindingError
from daedalus.gates.repository.write_classification import (
    EvidenceBinding,
    EvidenceKind,
    GuardDisposition,
    RepositoryWriteClassificationReport,
    SurfaceClassification,
    TargetDisposition,
    surface_binding_sha256,
)
from daedalus.gates.repository.write_evidence_materialization import (
    evidence_subject_sha256,
    materialize_repository_write_evidence,
)
from daedalus.gates.repository.write_evidence_origin import (
    RepositoryWriteEvidenceOriginSignatureError,
    issue_repository_write_evidence_origin_attestation,
)
from daedalus.gates.repository.write_inventory_v2 import RepositoryWriteSurface
from daedalus.gates.repository.write_guard_structure import (
    RepositoryWriteGuardStructureBindingError,
    RepositoryWriteGuardStructureError,
    verify_repository_write_guard_structure,
)
from daedalus.spine.envelope import canonical_json


REVISION = "a" * 40
COLLECTOR_SECRET = b"guard-structure-collector-secret-" * 2
GUARD_SECRET = b"guard-structure-manifest-secret-" * 2
ISSUED = datetime(2026, 8, 4, 18, 0, tzinfo=timezone.utc)
CONTRACT = "containment.attempt"
SURFACE_PATH = "daedalus/example.py"
SURFACE_SOURCE = b"def write_event(path):\n    path.write_text('event')\n"
SURFACE_LINE = 2
SURFACE_COLUMN = 4
IMPLEMENTATION_PATH = "daedalus/guard_impl.py"
IMPLEMENTATION_TARGET = "daedalus.guard_impl:Guard.check"
IMPLEMENTATION_SOURCE = (
    b"class Guard:\n"
    b"    def check(self, value):\n"
    b"        return bool(value)\n"
)


def _surface(
    *,
    path: str = SURFACE_PATH,
    line: int = SURFACE_LINE,
    column: int = SURFACE_COLUMN,
) -> RepositoryWriteSurface:
    return RepositoryWriteSurface(
        path=path,
        line=line,
        column=column,
        origin="base_v1",
        kind="path_method",
        callee="write_text",
        operation="write_text",
        blocking=True,
    )


def _evidence(
    surface: RepositoryWriteSurface,
    *,
    kind: EvidenceKind,
    payload: dict[str, object],
    contract: str = "",
) -> tuple[EvidenceBinding, bytes]:
    surface_sha256 = surface_binding_sha256(REVISION, surface)
    placeholder = EvidenceBinding(
        kind=kind,
        source_revision=REVISION,
        surface_sha256=surface_sha256,
        sha256="0" * 64,
        locator="cas:sha256:" + "0" * 64,
        guard_contract=contract,
    )
    payload_sha256 = hashlib.sha256(
        canonical_json(payload).encode("ascii")
    ).hexdigest()
    envelope = {
        "schema": "daedalus-gate0-repository-write-evidence-object/1",
        "kind": kind.value,
        "source_revision": REVISION,
        "surface_sha256": surface_sha256,
        "guard_contract": contract,
        "subject_sha256": evidence_subject_sha256(placeholder),
        "payload_sha256": payload_sha256,
        "payload": payload,
    }
    raw = canonical_json(envelope).encode("ascii")
    digest = hashlib.sha256(raw).hexdigest()
    return (
        EvidenceBinding(
            kind=kind,
            source_revision=REVISION,
            surface_sha256=surface_sha256,
            sha256=digest,
            locator=f"cas:sha256:{digest}",
            guard_contract=contract,
        ),
        raw,
    )


def _source_anchor(
    surface: RepositoryWriteSurface,
    *,
    source: bytes = SURFACE_SOURCE,
) -> tuple[EvidenceBinding, bytes]:
    return _evidence(
        surface,
        kind=EvidenceKind.SOURCE_ANCHOR,
        payload={
            "path": surface.path,
            "line": surface.line,
            "column": surface.column,
            "source_sha256": hashlib.sha256(source).hexdigest(),
        },
    )


def _guard_evidence(
    surface: RepositoryWriteSurface,
    *,
    contract: str = CONTRACT,
    target: str = IMPLEMENTATION_TARGET,
    implementation_source: bytes = IMPLEMENTATION_SOURCE,
) -> tuple[EvidenceBinding, bytes]:
    return _evidence(
        surface,
        kind=EvidenceKind.GUARD_CONTRACT,
        contract=contract,
        payload={
            "contract": contract,
            "implementation_target": target,
            "implementation_sha256": hashlib.sha256(
                implementation_source
            ).hexdigest(),
        },
    )


def _classification(
    *,
    surface: RepositoryWriteSurface | None = None,
    guard_items: tuple[tuple[EvidenceBinding, bytes], ...] | None = None,
    guarded: bool = True,
) -> tuple[RepositoryWriteClassificationReport, dict[str, bytes]]:
    selected = _surface() if surface is None else surface
    anchor = _source_anchor(selected)
    if guard_items is None:
        guard_items = (_guard_evidence(selected),) if guarded else ()
    evidence_items = (anchor, *guard_items)
    row = SurfaceClassification(
        source_revision=REVISION,
        surface=selected,
        target=TargetDisposition.PRIMARY_CHECKOUT,
        guard=(
            GuardDisposition.LOCAL_GUARDS
            if guarded
            else GuardDisposition.INVENTORY_ONLY
        ),
        production_reachable=True,
        guard_contracts=(CONTRACT,) if guarded else (),
        evidence=tuple(
            sorted(
                (binding for binding, _ in evidence_items),
                key=EvidenceBinding.sort_key,
            )
        ),
        notes="guard-structure fixture",
    )
    report = RepositoryWriteClassificationReport(
        source_revision=REVISION,
        inventory_digest="b" * 64,
        scan_input_sha256="c" * 64,
        inventory_surface_count=1,
        classifications=(row,),
        missing_surfaces=(),
    )
    return report, {
        binding.locator: raw for binding, raw in evidence_items
    }


def _attestation(
    classification: RepositoryWriteClassificationReport,
    blobs: dict[str, bytes],
):
    return issue_repository_write_evidence_origin_attestation(
        materialize_repository_write_evidence(classification, blobs),
        attestation_id="rwi.guard-structure.1",
        collector_id="gate.collector",
        collector_key_id="collector.key.1",
        collector_secret=COLLECTOR_SECRET,
        issued_at=ISSUED,
        expires_at=ISSUED + timedelta(hours=1),
    )


def _manifest(
    classification: RepositoryWriteClassificationReport,
    *,
    contract: str = CONTRACT,
    target: str = IMPLEMENTATION_TARGET,
    implementation_source: bytes = IMPLEMENTATION_SOURCE,
    classification_digest: str | None = None,
):
    return issue_guard_implementation_manifest(
        (
            GuardImplementationRecord(
                contract=contract,
                implementation_target=target,
                implementation_sha256=hashlib.sha256(
                    implementation_source
                ).hexdigest(),
            ),
        ),
        manifest_id="guard.structure.manifest.1",
        authority_id="gate.guard_registry",
        authority_key_id="guard.key.1",
        authority_secret=GUARD_SECRET,
        source_revision=REVISION,
        classification_digest=(
            classification.digest
            if classification_digest is None
            else classification_digest
        ),
        issued_at=ISSUED,
        expires_at=ISSUED + timedelta(hours=1),
    )


def _write_tree(
    root: Path,
    *,
    surface_source: bytes = SURFACE_SOURCE,
    implementation_source: bytes = IMPLEMENTATION_SOURCE,
) -> None:
    surface_path = root / SURFACE_PATH
    surface_path.parent.mkdir(parents=True, exist_ok=True)
    surface_path.write_bytes(surface_source)
    implementation_path = root / IMPLEMENTATION_PATH
    implementation_path.parent.mkdir(parents=True, exist_ok=True)
    implementation_path.write_bytes(implementation_source)


def _verify(
    classification: RepositoryWriteClassificationReport,
    blobs: dict[str, bytes],
    attestation,
    manifest,
    root: Path,
    **overrides: object,
):
    arguments = {
        "collector_keyring": {
            ("gate.collector", "collector.key.1"): COLLECTOR_SECRET
        },
        "expected_collector_id": "gate.collector",
        "guard_keyring": {
            ("gate.guard_registry", "guard.key.1"): GUARD_SECRET
        },
        "expected_guard_authority_id": "gate.guard_registry",
        "current_revision": REVISION,
        "now": ISSUED + timedelta(minutes=1),
        "repository_root": root,
    }
    arguments.update(overrides)
    return verify_repository_write_guard_structure(
        classification,
        blobs,
        attestation,
        manifest,
        **arguments,
    )


def test_guard_structure_joins_authenticated_subjects_without_behavior_claim(
    tmp_path: Path,
) -> None:
    _write_tree(tmp_path)
    classification, blobs = _classification()
    attestation = _attestation(classification, blobs)
    manifest = _manifest(classification)

    report = _verify(
        classification,
        blobs,
        attestation,
        manifest,
        tmp_path,
    )
    payload = report.to_dict()
    assert payload["origin_authenticated"] is True
    assert payload["source_anchor_semantics_verified"] is True
    assert payload["guard_manifest_authenticated"] is True
    assert payload["guard_contract_structure_verified"] is True
    assert payload["guard_contract_semantics_verified"] is False
    assert payload["semantic_receipts_verified"] is False
    assert payload["evidence_authenticated"] is False
    assert payload["gate_report_bound"] is False
    assert payload["closed"] is False
    assert payload["classification_count"] == 1
    assert payload["production_classification_count"] == 1
    assert payload["guard_contract_count"] == 1
    assert payload["guard_binding_count"] == 1
    assert payload["records"][0]["contract"] == CONTRACT
    assert (
        payload["records"][0]["implementation_target"]
        == IMPLEMENTATION_TARGET
    )
    assert payload["records"][0]["source_path"] == IMPLEMENTATION_PATH
    assert payload["records"][0]["definition_kind"] == "function"
    assert payload["blockers"] == [
        "effect-lease-semantic-verification-missing",
        "gate-report-binding-missing",
        "guard-contract-behavioral-verification-missing",
        "primary-checkout-disjointness-semantic-verification-missing",
        "retirement-semantic-verification-missing",
        "runtime-conformance-semantic-verification-missing",
    ]
    assert report.to_dict() == _verify(
        classification,
        blobs,
        attestation,
        manifest,
        tmp_path,
    ).to_dict()


def test_stale_revision_refuses_before_evidence_replay(tmp_path: Path) -> None:
    _write_tree(tmp_path)
    classification, blobs = _classification()
    with pytest.raises(
        RepositoryWriteGuardStructureBindingError,
        match="classification source revision is stale",
    ):
        _verify(
            classification,
            blobs,
            _attestation(classification, blobs),
            _manifest(classification),
            tmp_path,
            current_revision="d" * 40,
        )


def test_origin_and_guard_signatures_are_reverified(tmp_path: Path) -> None:
    _write_tree(tmp_path)
    classification, blobs = _classification()
    attestation = _attestation(classification, blobs)
    manifest = _manifest(classification)
    with pytest.raises(RepositoryWriteEvidenceOriginSignatureError):
        _verify(
            classification,
            blobs,
            attestation,
            manifest,
            tmp_path,
            collector_keyring={
                ("gate.collector", "collector.key.1"): b"wrong-secret-" * 4
            },
        )
    with pytest.raises(GuardImplementationManifestSignatureError):
        _verify(
            classification,
            blobs,
            attestation,
            manifest,
            tmp_path,
            guard_keyring={
                ("gate.guard_registry", "guard.key.1"):
                    b"wrong-guard-secret-" * 3
            },
        )


def test_manifest_must_bind_the_exact_classification(tmp_path: Path) -> None:
    _write_tree(tmp_path)
    classification, blobs = _classification()
    stale_manifest = _manifest(
        classification,
        classification_digest="f" * 64,
    )
    with pytest.raises(
        GuardImplementationManifestBindingError,
        match="classification digest is stale",
    ):
        _verify(
            classification,
            blobs,
            _attestation(classification, blobs),
            stale_manifest,
            tmp_path,
        )


def test_manifest_contract_set_must_equal_production_contracts(
    tmp_path: Path,
) -> None:
    _write_tree(tmp_path)
    classification, blobs = _classification()
    manifest = _manifest(classification, contract="other.contract")
    with pytest.raises(
        RepositoryWriteGuardStructureBindingError,
        match="contract set differs",
    ):
        _verify(
            classification,
            blobs,
            _attestation(classification, blobs),
            manifest,
            tmp_path,
        )


def test_guard_evidence_target_must_equal_authenticated_manifest(
    tmp_path: Path,
) -> None:
    _write_tree(tmp_path)
    surface = _surface()
    substituted = _guard_evidence(
        surface,
        target="daedalus.guard_impl:Guard.other",
    )
    classification, blobs = _classification(
        surface=surface,
        guard_items=(substituted,),
    )
    manifest = _manifest(classification)
    with pytest.raises(
        RepositoryWriteGuardStructureBindingError,
        match="target differs",
    ):
        _verify(
            classification,
            blobs,
            _attestation(classification, blobs),
            manifest,
            tmp_path,
        )


def test_guard_evidence_digest_must_equal_authenticated_manifest(
    tmp_path: Path,
) -> None:
    _write_tree(tmp_path)
    surface = _surface()
    substituted_source = IMPLEMENTATION_SOURCE + b"# alternate subject\n"
    substituted = _guard_evidence(
        surface,
        implementation_source=substituted_source,
    )
    classification, blobs = _classification(
        surface=surface,
        guard_items=(substituted,),
    )
    manifest = _manifest(classification)
    with pytest.raises(
        RepositoryWriteGuardStructureBindingError,
        match="source digest differs",
    ):
        _verify(
            classification,
            blobs,
            _attestation(classification, blobs),
            manifest,
            tmp_path,
        )


def test_current_implementation_bytes_must_match_the_manifest(
    tmp_path: Path,
) -> None:
    _write_tree(
        tmp_path,
        implementation_source=IMPLEMENTATION_SOURCE.replace(
            b"bool(value)", b"value is not None"
        ),
    )
    classification, blobs = _classification()
    with pytest.raises(PythonTargetBindingError, match="digest differs"):
        _verify(
            classification,
            blobs,
            _attestation(classification, blobs),
            _manifest(classification),
            tmp_path,
        )


def test_named_implementation_target_must_exist_uniquely(tmp_path: Path) -> None:
    missing_source = b"class Guard:\n    pass\n"
    _write_tree(tmp_path, implementation_source=missing_source)
    surface = _surface()
    guard_item = _guard_evidence(
        surface,
        implementation_source=missing_source,
    )
    classification, blobs = _classification(
        surface=surface,
        guard_items=(guard_item,),
    )
    manifest = _manifest(
        classification,
        implementation_source=missing_source,
    )
    with pytest.raises(PythonTargetBindingError, match="definition is missing"):
        _verify(
            classification,
            blobs,
            _attestation(classification, blobs),
            manifest,
            tmp_path,
        )

    ambiguous_source = (
        b"class Guard:\n"
        b"    def check(self, value):\n        return True\n"
        b"    def check(self, value):\n        return False\n"
    )
    _write_tree(tmp_path, implementation_source=ambiguous_source)
    guard_item = _guard_evidence(
        surface,
        implementation_source=ambiguous_source,
    )
    classification, blobs = _classification(
        surface=surface,
        guard_items=(guard_item,),
    )
    manifest = _manifest(
        classification,
        implementation_source=ambiguous_source,
    )
    with pytest.raises(PythonTargetBindingError, match="definition is ambiguous"):
        _verify(
            classification,
            blobs,
            _attestation(classification, blobs),
            manifest,
            tmp_path,
        )


def test_duplicate_guard_binding_for_one_contract_is_refused(
    tmp_path: Path,
) -> None:
    _write_tree(tmp_path)
    surface = _surface()
    first = _guard_evidence(surface)
    second = _guard_evidence(
        surface,
        target="daedalus.guard_impl:Guard.other",
    )
    classification, blobs = _classification(
        surface=surface,
        guard_items=(first, second),
    )
    with pytest.raises(
        RepositoryWriteGuardStructureBindingError,
        match="exactly one evidence binding",
    ):
        _verify(
            classification,
            blobs,
            _attestation(classification, blobs),
            _manifest(classification),
            tmp_path,
        )


def test_inventory_only_production_path_cannot_pass_vacuously(
    tmp_path: Path,
) -> None:
    _write_tree(tmp_path)
    classification, blobs = _classification(guarded=False)
    manifest = issue_guard_implementation_manifest(
        (
            GuardImplementationRecord(
                contract=CONTRACT,
                implementation_target=IMPLEMENTATION_TARGET,
                implementation_sha256=hashlib.sha256(
                    IMPLEMENTATION_SOURCE
                ).hexdigest(),
            ),
        ),
        manifest_id="guard.structure.manifest.inventory",
        authority_id="gate.guard_registry",
        authority_key_id="guard.key.1",
        authority_secret=GUARD_SECRET,
        source_revision=REVISION,
        classification_digest=classification.digest,
        issued_at=ISSUED,
        expires_at=ISSUED + timedelta(hours=1),
    )
    with pytest.raises(
        RepositoryWriteGuardStructureBindingError,
        match="lacks declared guarded structure",
    ):
        _verify(
            classification,
            blobs,
            _attestation(classification, blobs),
            manifest,
            tmp_path,
        )


def test_cross_layer_source_and_manifest_reports_cannot_be_detached(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_tree(tmp_path)
    classification, blobs = _classification()
    attestation = _attestation(classification, blobs)
    manifest = _manifest(classification)
    real_source = guard_structure.verify_repository_write_source_anchor_semantics

    def detached_source(*args, **kwargs):
        report = real_source(*args, **kwargs)
        return dataclasses.replace(report, materialization_digest="e" * 64)

    monkeypatch.setattr(
        guard_structure,
        "verify_repository_write_source_anchor_semantics",
        detached_source,
    )
    with pytest.raises(
        RepositoryWriteGuardStructureBindingError,
        match="chain mismatch",
    ):
        _verify(classification, blobs, attestation, manifest, tmp_path)

    monkeypatch.setattr(
        guard_structure,
        "verify_repository_write_source_anchor_semantics",
        real_source,
    )
    real_manifest = guard_structure.verify_guard_implementation_manifest

    def detached_manifest(*args, **kwargs):
        report = real_manifest(*args, **kwargs)
        return dataclasses.replace(report, manifest_digest="e" * 64)

    monkeypatch.setattr(
        guard_structure,
        "verify_guard_implementation_manifest",
        detached_manifest,
    )
    with pytest.raises(
        RepositoryWriteGuardStructureBindingError,
        match="chain mismatch",
    ):
        _verify(classification, blobs, attestation, manifest, tmp_path)


def test_blob_mapping_is_snapshotted_once_before_dependent_verifiers(
    tmp_path: Path,
) -> None:
    _write_tree(tmp_path)
    classification, blobs = _classification()

    class OneShotMapping(dict):
        calls = 0

        def items(self):
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("mapping was reread")
            return super().items()

    one_shot = OneShotMapping(blobs)
    report = _verify(
        classification,
        one_shot,
        _attestation(classification, blobs),
        _manifest(classification),
        tmp_path,
    )
    assert report.guard_binding_count == 1
    assert one_shot.calls == 1


def test_malformed_blob_mapping_fails_in_domain_boundary(tmp_path: Path) -> None:
    _write_tree(tmp_path)
    classification, blobs = _classification()
    with pytest.raises(RepositoryWriteGuardStructureError, match="mapping"):
        verify_repository_write_guard_structure(
            classification,
            [("not", b"a mapping")],
            _attestation(classification, blobs),
            _manifest(classification),
            collector_keyring={
                ("gate.collector", "collector.key.1"): COLLECTOR_SECRET
            },
            expected_collector_id="gate.collector",
            guard_keyring={
                ("gate.guard_registry", "guard.key.1"): GUARD_SECRET
            },
            expected_guard_authority_id="gate.guard_registry",
            current_revision=REVISION,
            now=ISSUED + timedelta(minutes=1),
            repository_root=tmp_path,
        )
