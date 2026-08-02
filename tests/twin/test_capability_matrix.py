from __future__ import annotations

import json

import pytest

from daedalus.twin.capabilities import (
    CapabilityClaim,
    CapabilityMatrix,
    CapabilityMatrixError,
    LanguageCapabilityProfile,
)

CAPABILITIES = (
    "behavioral_validation",
    "cross_plane_bindings",
    "data_schema",
    "discovery",
    "knowledge_links",
    "symbols",
    "syntax",
    "types",
)


def claim(name: str, state: str = "unsupported") -> CapabilityClaim:
    if state == "complete":
        return CapabilityClaim(name, state, "sha256:" + "a" * 64, None)
    if state == "partial":
        return CapabilityClaim(name, state, "sha256:" + "b" * 64, "bounded extractor coverage")
    return CapabilityClaim(name, state, None, "not implemented in Gate 2")


def profile(language_id: str = "rust") -> LanguageCapabilityProfile:
    states = {"discovery": "complete", "syntax": "partial"}
    return LanguageCapabilityProfile(
        language_id=language_id,
        extractor_contract="sha256:" + "c" * 64,
        claims=tuple(claim(name, states.get(name, "unsupported")) for name in CAPABILITIES),
    )


def matrix() -> CapabilityMatrix:
    return CapabilityMatrix(
        schema="daedalus-capability-matrix/1",
        corpus_manifest_digest="sha256:" + "d" * 64,
        profiles=(profile(),),
    )


def test_round_trip_is_canonical_and_deterministic() -> None:
    value = matrix()
    payload = value.to_json_bytes()
    assert CapabilityMatrix.from_json_bytes(payload) == value
    assert value.digest == CapabilityMatrix.from_json_bytes(payload).digest
    pretty = (json.dumps(value.to_dict(), indent=2, sort_keys=True) + "\n").encode()
    with pytest.raises(CapabilityMatrixError, match="canonical JSON"):
        CapabilityMatrix.from_json_bytes(pretty)


def test_complete_and_partial_claims_require_content_addressed_evidence() -> None:
    with pytest.raises(CapabilityMatrixError, match="require sha256 evidence"):
        CapabilityClaim("discovery", "complete", None, None)
    with pytest.raises(CapabilityMatrixError, match="require sha256 evidence"):
        CapabilityClaim("syntax", "partial", "reviewed", "bounded")
    with pytest.raises(CapabilityMatrixError, match="must not carry success evidence"):
        CapabilityClaim("types", "unsupported", "sha256:" + "a" * 64, "unsupported")


def test_partial_unsupported_and_failed_states_require_explicit_limitations() -> None:
    for state in ("partial", "unsupported", "failed"):
        evidence = "sha256:" + "a" * 64 if state == "partial" else None
        with pytest.raises(CapabilityMatrixError, match="limitation"):
            CapabilityClaim("symbols", state, evidence, None)


def test_every_profile_must_cover_the_exact_canonical_capability_set() -> None:
    with pytest.raises(CapabilityMatrixError, match="every capability"):
        LanguageCapabilityProfile(
            language_id="rust",
            extractor_contract="sha256:" + "c" * 64,
            claims=(claim("discovery", "complete"),),
        )
    reversed_claims = tuple(reversed(profile().claims))
    with pytest.raises(CapabilityMatrixError, match="canonical order"):
        LanguageCapabilityProfile(
            language_id="rust",
            extractor_contract="sha256:" + "c" * 64,
            claims=reversed_claims,
        )


def test_failed_capabilities_are_mechanical_gate_blockers() -> None:
    claims = tuple(
        CapabilityClaim(name, "failed", None, "extractor crashed") if name == "syntax" else claim(name)
        for name in CAPABILITIES
    )
    value = CapabilityMatrix(
        schema="daedalus-capability-matrix/1",
        corpus_manifest_digest="sha256:" + "d" * 64,
        profiles=(LanguageCapabilityProfile("rust", "sha256:" + "c" * 64, claims),),
    )
    assert value.blockers == ("rust:syntax:failed",)


def test_profiles_are_unique_and_sorted() -> None:
    with pytest.raises(CapabilityMatrixError, match="unique and sorted"):
        CapabilityMatrix(
            schema="daedalus-capability-matrix/1",
            corpus_manifest_digest="sha256:" + "d" * 64,
            profiles=(profile("rust"), profile("cpp")),
        )
