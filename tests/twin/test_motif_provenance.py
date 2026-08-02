from __future__ import annotations

import json

import pytest

from daedalus.twin.motifs import (
    CrossRepositoryAlignment,
    MotifProvenance,
    MotifProvenanceError,
    MotifSupport,
)


def support(repository_id: str, digit: str) -> MotifSupport:
    return MotifSupport(
        repository_id=repository_id,
        source_revision=digit * 40,
        project_twin_manifest_sha256=digit * 64,
        subgraph_sha256=(hex((int(digit, 16) + 1) % 16)[2:]) * 64,
        license_spdx="MIT",
        extractor_contract_sha256=(hex((int(digit, 16) + 2) % 16)[2:]) * 64,
        evidence_sha256=(hex((int(digit, 16) + 3) % 16)[2:]) * 64,
        temporal_cutoff="2026-08-02T00:00:00Z",
    )


def alignment(left: MotifSupport, right: MotifSupport, *, verified: bool = True) -> CrossRepositoryAlignment:
    first, second = sorted((left.digest, right.digest))
    return CrossRepositoryAlignment(
        left_support_sha256=first,
        right_support_sha256=second,
        mapping_sha256="a" * 64,
        algorithm_contract_sha256="b" * 64,
        status="verified" if verified else "rejected",
        evidence_sha256="c" * 64 if verified else None,
        limitation=None if verified else "alignment did not preserve the declared invariant",
    )


def motif(*, verified: bool = True) -> MotifProvenance:
    left = support("spring-framework", "1")
    right = support("tokio", "2")
    link = alignment(left, right, verified=verified)
    return MotifProvenance(
        schema="daedalus-motif-provenance/1",
        motif_id="bounded-service-lifecycle",
        supports=(left, right),
        alignments=(link,),
        invariant_sha256s=("d" * 64,),
        negative_example_sha256s=("e" * 64,),
        evaluator_evidence_sha256s=("f" * 64,),
    )


def test_verified_cross_repository_motif_is_canonical_and_closed() -> None:
    value = motif()
    assert value.closed_for_gate2
    assert value.blockers == ()
    assert MotifProvenance.from_json_bytes(value.to_json_bytes()) == value
    assert len(value.digest) == 64


def test_rejected_alignment_is_retained_but_cannot_close_gate2() -> None:
    value = motif(verified=False)
    assert not value.closed_for_gate2
    assert value.blockers == (
        "no-verified-cross-repository-alignment",
        "support-spring-framework-unaligned",
        "support-tokio-unaligned",
    )


def test_alignment_refuses_unknown_support_and_same_support() -> None:
    left = support("spring-framework", "1")
    right = support("tokio", "2")
    unknown = support("unknown-repository", "3")
    link = alignment(left, unknown)
    with pytest.raises(MotifProvenanceError, match="unknown support"):
        MotifProvenance(
            schema="daedalus-motif-provenance/1",
            motif_id="invalid-motif",
            supports=(left, right),
            alignments=(link,),
            invariant_sha256s=("d" * 64,),
            negative_example_sha256s=("e" * 64,),
            evaluator_evidence_sha256s=("f" * 64,),
        )
    with pytest.raises(MotifProvenanceError, match="distinct supports"):
        CrossRepositoryAlignment(
            left_support_sha256=left.digest,
            right_support_sha256=left.digest,
            mapping_sha256="a" * 64,
            algorithm_contract_sha256="b" * 64,
            status="verified",
            evidence_sha256="c" * 64,
            limitation=None,
        )


def test_support_identity_license_and_temporal_cutoff_are_required() -> None:
    with pytest.raises(MotifProvenanceError, match="SPDX"):
        MotifSupport(
            repository_id="tokio",
            source_revision="1" * 40,
            project_twin_manifest_sha256="1" * 64,
            subgraph_sha256="2" * 64,
            license_spdx="not a license",
            extractor_contract_sha256="3" * 64,
            evidence_sha256="4" * 64,
            temporal_cutoff="2026-08-02T00:00:00Z",
        )
    with pytest.raises(MotifProvenanceError, match="UTC seconds"):
        MotifSupport(
            repository_id="tokio",
            source_revision="1" * 40,
            project_twin_manifest_sha256="1" * 64,
            subgraph_sha256="2" * 64,
            license_spdx="MIT",
            extractor_contract_sha256="3" * 64,
            evidence_sha256="4" * 64,
            temporal_cutoff="2026-08-02",
        )


def test_duplicate_repository_supports_and_noncanonical_alignment_order_refuse() -> None:
    left = support("tokio", "1")
    right = support("tokio", "2")
    with pytest.raises(MotifProvenanceError, match="unique sorted repository_id"):
        MotifProvenance(
            schema="daedalus-motif-provenance/1",
            motif_id="duplicate-support",
            supports=(left, right),
            alignments=(),
            invariant_sha256s=("d" * 64,),
            negative_example_sha256s=("e" * 64,),
            evaluator_evidence_sha256s=("f" * 64,),
        )
    first, second = sorted((left.digest, right.digest))
    with pytest.raises(MotifProvenanceError, match="canonical order"):
        CrossRepositoryAlignment(
            left_support_sha256=second,
            right_support_sha256=first,
            mapping_sha256="a" * 64,
            algorithm_contract_sha256="b" * 64,
            status="verified",
            evidence_sha256="c" * 64,
            limitation=None,
        )


def test_tampered_blockers_and_noncanonical_json_refuse() -> None:
    value = motif()
    payload = value.to_dict()
    payload["blockers"] = ["fabricated-blocker"]
    with pytest.raises(MotifProvenanceError, match="mechanically derived"):
        MotifProvenance.from_dict(payload)
    pretty = (json.dumps(value.to_dict(), indent=2, sort_keys=True) + "\n").encode()
    with pytest.raises(MotifProvenanceError, match="canonical JSON"):
        MotifProvenance.from_json_bytes(pretty)
