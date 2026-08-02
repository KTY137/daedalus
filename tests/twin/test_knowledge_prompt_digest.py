"""Digest and bounded-omission regressions for knowledge prompt envelopes."""
from __future__ import annotations

import hashlib

import pytest

from daedalus.twin.knowledge_correlation import KnowledgeCorrelationError
from daedalus.twin.knowledge_prompt import KnowledgePromptEnvelope


SHA = "a" * 64


def test_prompt_payload_sha256_is_the_hash_of_exact_utf8_bytes() -> None:
    payload = '{"content_trust":"untrusted-data","schema":"fixture/1"}'
    expected = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    envelope = KnowledgePromptEnvelope(
        source_revision="1" * 40,
        snapshot_sha256=SHA,
        corpus_sha256="b" * 64,
        context_sha256="c" * 64,
        payload_sha256=expected,
        target_paths=("src/events.py",),
        included_claims=0,
        omitted_claim_sha256s=(),
        payload_json=payload,
    )
    assert envelope.payload_sha256 == expected

    with pytest.raises(KnowledgeCorrelationError, match="payload digest"):
        KnowledgePromptEnvelope(
            source_revision="1" * 40,
            snapshot_sha256=SHA,
            corpus_sha256="b" * 64,
            context_sha256="c" * 64,
            payload_sha256="d" * 64,
            target_paths=("src/events.py",),
            included_claims=0,
            omitted_claim_sha256s=(),
            payload_json=payload,
        )


def test_outer_envelope_summarizes_large_omission_sets() -> None:
    payload = '{"content_trust":"untrusted-data","schema":"fixture/1"}'
    omitted = tuple(hashlib.sha256(str(index).encode()).hexdigest() for index in range(5_000))
    envelope = KnowledgePromptEnvelope(
        source_revision="1" * 40,
        snapshot_sha256=SHA,
        corpus_sha256="b" * 64,
        context_sha256="c" * 64,
        payload_sha256=hashlib.sha256(payload.encode()).hexdigest(),
        target_paths=("src/events.py",),
        included_claims=0,
        omitted_claim_sha256s=omitted,
        payload_json=payload,
    )
    encoded = envelope.to_dict()
    assert encoded["omitted_claims"]["count"] == 5_000
    assert len(encoded["omitted_claims"]["preview"]) == 16
    assert encoded["omitted_claims"]["preview_truncated"] is True
    assert len(encoded["omitted_claims"]["set_sha256"]) == 64
    assert len(envelope.prompt_text) < 1_000
