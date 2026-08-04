from __future__ import annotations

import dataclasses
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import daedalus.gates.repository_write_source_anchor_semantics as source_anchor_semantics
from daedalus.gates.repository_write_classification import (
    EvidenceBinding,
    EvidenceKind,
    GuardDisposition,
    RepositoryWriteClassificationReport,
    SurfaceClassification,
    TargetDisposition,
    surface_binding_sha256,
)
from daedalus.gates.repository_write_evidence_materialization import (
    evidence_subject_sha256,
    materialize_repository_write_evidence,
)
from daedalus.gates.repository_write_evidence_origin import (
    RepositoryWriteEvidenceOriginSignatureError,
    issue_repository_write_evidence_origin_attestation,
)
from daedalus.gates.repository_write_inventory_v2 import RepositoryWriteSurface
from daedalus.gates.repository_write_source_anchor_semantics import (
    RepositoryWriteSourceAnchorBindingError,
    RepositoryWriteSourceAnchorSemanticsError,
    RepositoryWriteSourceAnchorTreeError,
    verify_repository_write_source_anchor_semantics,
)
from daedalus.spine.envelope import canonical_json


REVISION = "a" * 40
SECRET = b"source-anchor-collector-secret-" * 2
ISSUED = datetime(2026, 8, 4, 16, 0, tzinfo=timezone.utc)
SOURCE = b"def write_event(path):\n    path.write_text('event')\n"
PATH = "daedalus/example.py"
LINE = 2
COLUMN = 4


def _surface(*, path: str = PATH, line: int = LINE, column: int = COLUMN):
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


def _source_anchor(
    surface: RepositoryWriteSurface,
    *,
    payload_path: str | None = None,
    payload_line: int | None = None,
    payload_column: int | None = None,
    source: bytes = SOURCE,
) -> tuple[EvidenceBinding, bytes]:
    surface_sha256 = surface_binding_sha256(REVISION, surface)
    placeholder = EvidenceBinding(
        kind=EvidenceKind.SOURCE_ANCHOR,
        source_revision=REVISION,
        surface_sha256=surface_sha256,
        sha256="0" * 64,
        locator="cas:sha256:" + "0" * 64,
    )
    payload = {
        "path": surface.path if payload_path is None else payload_path,
        "line": surface.line if payload_line is None else payload_line,
        "column": surface.column if payload_column is None else payload_column,
        "source_sha256": hashlib.sha256(source).hexdigest(),
    }
    payload_sha256 = hashlib.sha256(
        canonical_json(payload).encode("ascii")
    ).hexdigest()
    envelope = {
        "schema": "daedalus-gate0-repository-write-evidence-object/1",
        "kind": EvidenceKind.SOURCE_ANCHOR.value,
        "source_revision": REVISION,
        "surface_sha256": surface_sha256,
        "guard_contract": "",
        "subject_sha256": evidence_subject_sha256(placeholder),
        "payload_sha256": payload_sha256,
        "payload": payload,
    }
    raw = canonical_json(envelope).encode("ascii")
    blob_sha256 = hashlib.sha256(raw).hexdigest()
    return (
        EvidenceBinding(
            kind=EvidenceKind.SOURCE_ANCHOR,
            source_revision=REVISION,
            surface_sha256=surface_sha256,
            sha256=blob_sha256,
            locator=f"cas:sha256:{blob_sha256}",
        ),
        raw,
    )


def _classification(
    *,
    surface: RepositoryWriteSurface | None = None,
    anchors: tuple[tuple[EvidenceBinding, bytes], ...] | None = None,
) -> tuple[RepositoryWriteClassificationReport, dict[str, bytes]]:
    selected = _surface() if surface is None else surface
    if anchors is None:
        anchors = (_source_anchor(selected),)
    evidence = tuple(
        sorted((item[0] for item in anchors), key=EvidenceBinding.sort_key)
    )
    row = SurfaceClassification(
        source_revision=REVISION,
        surface=selected,
        target=TargetDisposition.PRIMARY_CHECKOUT,
        guard=GuardDisposition.INVENTORY_ONLY,
        production_reachable=True,
        guard_contracts=(),
        evidence=evidence,
        notes="fixture remains a blocking write surface",
    )
    report = RepositoryWriteClassificationReport(
        source_revision=REVISION,
        inventory_digest="b" * 64,
        scan_input_sha256="c" * 64,
        inventory_surface_count=1,
        classifications=(row,),
        missing_surfaces=(),
    )
    return report, {binding.locator: raw for binding, raw in anchors}


def _attestation(
    classification: RepositoryWriteClassificationReport,
    blobs: dict[str, bytes],
):
    return issue_repository_write_evidence_origin_attestation(
        materialize_repository_write_evidence(classification, blobs),
        attestation_id="rwi.source-anchor.1",
        collector_id="gate.collector",
        collector_key_id="collector.key.1",
        collector_secret=SECRET,
        issued_at=ISSUED,
        expires_at=ISSUED + timedelta(hours=1),
    )


def _write_tree(root: Path, *, source: bytes = SOURCE) -> None:
    target = root / PATH
    target.parent.mkdir(parents=True)
    target.write_bytes(source)


def _verify(
    classification: RepositoryWriteClassificationReport,
    blobs: dict[str, bytes],
    attestation,
    root: Path,
    **overrides: object,
):
    arguments = {
        "keyring": {("gate.collector", "collector.key.1"): SECRET},
        "expected_collector_id": "gate.collector",
        "current_revision": REVISION,
        "now": ISSUED + timedelta(minutes=1),
        "repository_root": root,
    }
    arguments.update(overrides)
    return verify_repository_write_source_anchor_semantics(
        classification,
        blobs,
        attestation,
        **arguments,
    )


def test_source_anchor_semantics_bind_authenticated_origin_and_exact_source(
    tmp_path: Path,
) -> None:
    _write_tree(tmp_path)
    classification, blobs = _classification()
    attestation = _attestation(classification, blobs)

    report = _verify(classification, blobs, attestation, tmp_path)
    payload = report.to_dict()
    assert payload["origin_authenticated"] is True
    assert payload["source_anchor_semantics_verified"] is True
    assert payload["semantic_receipts_verified"] is False
    assert payload["evidence_authenticated"] is False
    assert payload["gate_report_bound"] is False
    assert payload["closed"] is False
    assert payload["classification_count"] == 1
    assert payload["source_anchor_count"] == 1
    assert payload["records"] == [
        {
            "surface_sha256": surface_binding_sha256(REVISION, _surface()),
            "locator": next(iter(blobs)),
            "path": PATH,
            "line": LINE,
            "column": COLUMN,
            "source_sha256": hashlib.sha256(SOURCE).hexdigest(),
        }
    ]
    assert payload["blockers"] == [
        "effect-lease-semantic-verification-missing",
        "gate-report-binding-missing",
        "guard-contract-semantic-verification-missing",
        "primary-checkout-disjointness-semantic-verification-missing",
        "retirement-semantic-verification-missing",
        "runtime-conformance-semantic-verification-missing",
    ]
    assert report.to_dict() == _verify(
        classification, blobs, attestation, tmp_path
    ).to_dict()


def test_changed_source_bytes_refuse_after_origin_authentication(tmp_path: Path) -> None:
    _write_tree(tmp_path, source=SOURCE.replace(b"event", b"changed"))
    classification, blobs = _classification()
    with pytest.raises(
        RepositoryWriteSourceAnchorBindingError,
        match="current source bytes",
    ):
        _verify(classification, blobs, _attestation(classification, blobs), tmp_path)


@pytest.mark.parametrize(
    ("payload_path", "payload_line", "payload_column"),
    [
        ("daedalus/other.py", LINE, COLUMN),
        (PATH, LINE + 1, COLUMN),
        (PATH, LINE, COLUMN + 1),
    ],
)
def test_payload_position_must_equal_the_classified_surface(
    tmp_path: Path,
    payload_path: str,
    payload_line: int,
    payload_column: int,
) -> None:
    _write_tree(tmp_path)
    surface = _surface()
    anchor = _source_anchor(
        surface,
        payload_path=payload_path,
        payload_line=payload_line,
        payload_column=payload_column,
    )
    classification, blobs = _classification(surface=surface, anchors=(anchor,))
    with pytest.raises(
        RepositoryWriteSourceAnchorBindingError,
        match="position differs",
    ):
        _verify(classification, blobs, _attestation(classification, blobs), tmp_path)


def test_anchor_must_point_to_a_non_whitespace_byte(tmp_path: Path) -> None:
    _write_tree(tmp_path)
    surface = _surface(column=0)
    anchor = _source_anchor(surface)
    classification, blobs = _classification(surface=surface, anchors=(anchor,))
    with pytest.raises(
        RepositoryWriteSourceAnchorBindingError,
        match="points at whitespace",
    ):
        _verify(classification, blobs, _attestation(classification, blobs), tmp_path)


def test_every_classification_requires_exactly_one_anchor(tmp_path: Path) -> None:
    _write_tree(tmp_path)
    surface = _surface()
    first = _source_anchor(surface)
    second = _source_anchor(surface, payload_column=COLUMN + 1)
    classification, blobs = _classification(
        surface=surface,
        anchors=(first, second),
    )
    with pytest.raises(
        RepositoryWriteSourceAnchorBindingError,
        match="exactly one",
    ):
        _verify(classification, blobs, _attestation(classification, blobs), tmp_path)


def test_stale_revision_refuses_before_materialization(tmp_path: Path) -> None:
    _write_tree(tmp_path)
    classification, blobs = _classification()
    with pytest.raises(
        RepositoryWriteSourceAnchorBindingError,
        match="stale",
    ):
        _verify(
            classification,
            blobs,
            _attestation(classification, blobs),
            tmp_path,
            current_revision="d" * 40,
        )


def test_origin_signature_is_reverified_not_trusted_as_a_report(tmp_path: Path) -> None:
    _write_tree(tmp_path)
    classification, blobs = _classification()
    attestation = _attestation(classification, blobs)
    with pytest.raises(RepositoryWriteEvidenceOriginSignatureError):
        _verify(
            classification,
            blobs,
            attestation,
            tmp_path,
            keyring={
                ("gate.collector", "collector.key.1"): b"wrong-secret-" * 4
            },
        )


def test_cross_layer_digest_chain_cannot_be_detached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_tree(tmp_path)
    classification, blobs = _classification()
    attestation = _attestation(classification, blobs)
    real_verify = source_anchor_semantics.verify_repository_write_evidence_origin

    def substitute(*args, **kwargs):
        report = real_verify(*args, **kwargs)
        return dataclasses.replace(report, attestation_digest="d" * 64)

    monkeypatch.setattr(
        source_anchor_semantics,
        "verify_repository_write_evidence_origin",
        substitute,
    )
    with pytest.raises(
        RepositoryWriteSourceAnchorBindingError,
        match="chain mismatch",
    ):
        _verify(classification, blobs, attestation, tmp_path)


def test_drive_qualified_source_path_is_refused_before_tree_access(
    tmp_path: Path,
) -> None:
    surface = _surface(path="C:/outside.py")
    anchor = _source_anchor(surface)
    classification, blobs = _classification(surface=surface, anchors=(anchor,))
    with pytest.raises(
        RepositoryWriteSourceAnchorSemanticsError,
        match="repository-relative",
    ):
        _verify(
            classification,
            blobs,
            _attestation(classification, blobs),
            tmp_path,
        )


def test_symlink_file_or_parent_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "real.py"
    target.write_bytes(SOURCE)
    package = tmp_path / "daedalus"
    try:
        package.mkdir()
        (package / "example.py").symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")
    classification, blobs = _classification()
    with pytest.raises(RepositoryWriteSourceAnchorTreeError, match="symlink"):
        _verify(classification, blobs, _attestation(classification, blobs), tmp_path)


def test_symlink_parent_is_refused(tmp_path: Path) -> None:
    real_package = tmp_path / "real-package"
    real_package.mkdir()
    (real_package / "example.py").write_bytes(SOURCE)
    try:
        (tmp_path / "daedalus").symlink_to(real_package, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks unavailable on this platform")
    classification, blobs = _classification()
    with pytest.raises(RepositoryWriteSourceAnchorTreeError, match="symlink"):
        _verify(
            classification,
            blobs,
            _attestation(classification, blobs),
            tmp_path,
        )


def test_malformed_repository_root_and_empty_classification_refuse(
    tmp_path: Path,
) -> None:
    classification, blobs = _classification()
    with pytest.raises(RepositoryWriteSourceAnchorTreeError):
        _verify(
            classification,
            blobs,
            _attestation(classification, blobs),
            "not-a-path",
        )

    empty = dataclasses.replace(
        classification,
        inventory_surface_count=0,
        classifications=(),
    )
    with pytest.raises(
        RepositoryWriteSourceAnchorSemanticsError,
        match="requires classified surfaces",
    ):
        _verify(empty, {}, _attestation(classification, blobs), tmp_path)
