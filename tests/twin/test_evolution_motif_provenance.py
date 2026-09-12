from __future__ import annotations

import pytest

from daedalus.evolution.motifs import (
    CrossRepositoryAlignment,
    MotifProvenance,
    MotifSupport,
)
from daedalus.kernel.contracts.base import ContractProvenance
from daedalus.spine.envelope import canonical_sha


def _sha(char: str) -> str:
    return char * 64


def _support(repository_id: str, revision_char: str, digest_char: str) -> MotifSupport:
    return MotifSupport(
        repository_id=repository_id,
        source_revision=revision_char * 40,
        project_twin_manifest_sha256=_sha(digest_char),
        subgraph_sha256=_sha(chr(ord(digest_char) + 1)),
        license_spdx="Apache-2.0",
        extractor_contract_sha256=_sha(chr(ord(digest_char) + 2)),
        evidence_sha256=_sha(chr(ord(digest_char) + 3)),
        temporal_cutoff="2026-09-01T00:00:00Z",
    )


def _alignment(
    supports: tuple[MotifSupport, MotifSupport],
    *,
    status: str = "verified",
) -> CrossRepositoryAlignment:
    left, right = sorted(item.digest for item in supports)
    return CrossRepositoryAlignment(
        left_support_sha256=left,
        right_support_sha256=right,
        mapping_sha256=_sha("e"),
        algorithm_contract_sha256=_sha("f"),
        status=status,
        evidence_sha256=_sha("a") if status == "verified" else None,
        limitation=None if status == "verified" else "mapping disagreed on held-out nodes",
    )


def _provenance(inputs: tuple[str, ...]) -> ContractProvenance:
    return ContractProvenance(
        origin="tests.evolution.motif",
        source_revision="9" * 40,
        created_at="2026-09-12T05:00:00Z",
        input_digests=inputs,
    )


def _motif(*, alignment_status: str = "verified") -> MotifProvenance:
    supports = (
        _support("alpha-repo", "1", "1"),
        _support("beta-repo", "2", "5"),
    )
    alignment = _alignment(supports, status=alignment_status)
    invariants = (_sha("b"),)
    negatives = (_sha("c"),)
    evaluators = (_sha("d"),)
    inputs = tuple(
        sorted(
            (
                *(item.digest for item in supports),
                alignment.digest,
                *invariants,
                *negatives,
                *evaluators,
            )
        )
    )
    return MotifProvenance(
        motif_id="revision-bound-repair",
        supports=supports,
        alignments=(alignment,),
        invariant_sha256s=invariants,
        negative_example_sha256s=negatives,
        evaluator_evidence_sha256s=evaluators,
        provenance=_provenance(inputs),
    )


def test_motif_round_trip_uses_canonical_contract_identity() -> None:
    motif = _motif()

    assert motif.evidence_gaps == ()
    assert motif.digest == canonical_sha(motif.to_dict())
    assert MotifProvenance.from_dict(motif.to_dict()) == motif
    assert motif.to_dict()["contract_type"] == "evolution.motif-provenance"
    assert not hasattr(motif, "closed_for_gate2")


def test_rejected_alignment_retains_negative_evidence_without_gate_claim() -> None:
    motif = _motif(alignment_status="rejected")

    assert motif.evidence_gaps == (
        "no-verified-cross-repository-alignment",
        "support-alpha-repo-unaligned",
        "support-beta-repo-unaligned",
    )
    assert motif.alignments[0].evidence_sha256 is None
    assert motif.alignments[0].limitation


def test_motif_provenance_must_bind_all_referenced_evidence() -> None:
    motif = _motif()
    payload = motif.to_dict()
    payload["provenance"]["input_digests"].remove(_sha("d"))

    with pytest.raises(ValueError, match="does not bind referenced input"):
        MotifProvenance.from_dict(payload)


def test_alignment_must_reference_declared_supports() -> None:
    motif = _motif()
    payload = motif.to_dict()
    payload["alignments"][0]["left_support_sha256"] = _sha("0")
    referenced = payload["provenance"]["input_digests"]
    referenced.append(_sha("0"))
    referenced.sort()

    with pytest.raises(ValueError, match="unknown support"):
        MotifProvenance.from_dict(payload)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("repository_id", "Alpha_repo", "lowercase kebab-case"),
        ("license_spdx", "Apache 2.0", "SPDX"),
        ("temporal_cutoff", "2026-09-01", "timezone"),
    ],
)
def test_support_rejects_noncanonical_provenance_fields(
    field: str,
    value: str,
    message: str,
) -> None:
    kwargs = {
        "repository_id": "alpha-repo",
        "source_revision": "1" * 40,
        "project_twin_manifest_sha256": _sha("1"),
        "subgraph_sha256": _sha("2"),
        "license_spdx": "Apache-2.0",
        "extractor_contract_sha256": _sha("3"),
        "evidence_sha256": _sha("4"),
        "temporal_cutoff": "2026-09-01T00:00:00Z",
    }
    kwargs[field] = value

    with pytest.raises(ValueError, match=message):
        MotifSupport(**kwargs)
