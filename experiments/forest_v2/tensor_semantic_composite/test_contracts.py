"""Strict/adversarial tests for semantic-composite contracts."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from experiments.forest_v2.tensor_embeddings.contracts import canonical_digest
from experiments.forest_v2.tensor_semantic_composite.contracts import (
    AUTHORITY,
    EMPTY_SHA256,
    PURPOSE,
    CompositeBlock,
    CompositeReceipt,
    CompositeSpaceSpec,
    CompositeVector,
    EncoderManifest,
    PACKET_SPEC_DIGEST,
    ProjectionManifest,
    SemanticContractError,
    VectorReceipt,
    text_digest,
    vector_digest,
)


def sha(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


SPEC_DIGEST = PACKET_SPEC_DIGEST


def encoder(name: str, dimension: int) -> EncoderManifest:
    return EncoderManifest(
        provider="fixture-provider",
        model_name=name,
        model_revision="immutable-r1",
        source_locator=f"fixture://{name}",
        query_checkpoint_digest=sha(name + ":query-checkpoint"),
        document_checkpoint_digest=sha(name + ":document-checkpoint"),
        tokenizer_name=name + "-tokenizer",
        tokenizer_revision="immutable-t1",
        tokenizer_digest=sha(name + ":tokenizer"),
        query_template_digest=sha(name + ":query-template"),
        document_template_digest=sha(name + ":document-template"),
        preprocessing_digest=sha(name + ":preprocessing"),
        pooling="mean_attention_masked",
        pooling_config_digest=sha(name + ":pooling-config"),
        truncation_strategy="right",
        truncation_tokens=512,
        add_special_tokens=True,
        output_dimension=dimension,
        output_dtype="float32",
        output_normalization="l2",
        shared_space_evidence_digest=sha(name + ":shared-space"),
        adapter_digest=sha(name + ":adapter"),
        license_spdx="Apache-2.0",
        license_evidence_digest=sha(name + ":license"),
        license_evidence_locator=f"fixture://{name}/license",
    )


def test_exported_packet_digest_matches_exact_canonical_protocol() -> None:
    path = Path(__file__).with_name("EXPERIMENT_SPEC.json")
    protocol = json.loads(path.read_text(encoding="utf-8"))
    actual = "sha256:" + canonical_digest(protocol, domain=protocol["schema"])
    assert actual == PACKET_SPEC_DIGEST

    with pytest.raises(SemanticContractError, match="frozen Packet 002"):
        CompositeSpaceSpec.from_encoders(
            (encoder("alpha", 2),),
            experiment_spec_digest=sha("arbitrary-spec"),
        )


def receipt_for(
    block: CompositeBlock,
    values: tuple[float, ...],
    *,
    source_id: str = "query:q1",
    revision: str = "revision-1",
    text: str = "find parser",
    role: str = "content",
    tower: str = "query",
    tokens: int = 3,
) -> VectorReceipt:
    raw = text.encode("utf-8")
    return VectorReceipt(
        source_id=source_id,
        revision=revision,
        input_digest=text_digest(text),
        input_bytes=len(raw),
        role=role,
        tower=tower,
        encoder_id=block.encoder.encoder_id,
        projection_id=block.projection.projection_id,
        source_dimension=block.encoder.output_dimension,
        output_dimension=block.output_dimension,
        source_vector_digest=vector_digest(
            values,
            space_id=block.encoder.encoder_id,
            stage="encoder_output",
        ),
        output_vector_digest=vector_digest(
            values,
            space_id=block.projection.projection_id,
            stage="projection_output",
        ),
        input_tokens=tokens,
        producer_receipt_digest=sha(block.encoder.encoder_id + ":producer"),
        execution_receipt_digest=sha(block.encoder.encoder_id + ":execution"),
        cost_receipt_digest=sha(block.encoder.encoder_id + ":cost"),
        egress_classification="local_only",
        egress_policy_receipt_digest=sha("egress-policy"),
    )


def test_encoder_manifest_is_canonical_roundtrippable_and_content_addressed() -> None:
    original = encoder("alpha", 3)
    recovered = EncoderManifest.from_bytes(original.canonical_bytes())
    assert recovered == original
    assert recovered.canonical_bytes() == original.canonical_bytes()
    assert original.encoder_id.startswith("encoder:")

    with pytest.raises(SemanticContractError, match="does not match"):
        replace(original, model_revision="mutable-latest")


@pytest.mark.parametrize(
    ("field", "bad"),
    (
        ("output_dimension", True),
        ("truncation_tokens", 1.0),
        ("add_special_tokens", 1),
        ("query_checkpoint_digest", "not-a-digest"),
        ("output_normalization", "none"),
        ("truncation_strategy", "silent-middle"),
    ),
)
def test_encoder_manifest_refuses_ambiguous_identity_fields(
    field: str, bad: object
) -> None:
    values = encoder("alpha", 3).__dict__.copy()
    values.pop("encoder_id")
    values[field] = bad
    with pytest.raises(SemanticContractError):
        EncoderManifest(**values)


def test_strict_loader_refuses_unknown_duplicate_and_relabelled_authority() -> None:
    manifest = encoder("alpha", 3)
    unknown = manifest.to_dict()
    unknown["surprise"] = True
    with pytest.raises(SemanticContractError, match="unknown keys"):
        EncoderManifest.from_dict(unknown)

    duplicated = manifest.canonical_bytes().decode("utf-8").replace(
        '"provider":"fixture-provider"',
        '"provider":"fixture-provider","provider":"other"',
    )
    with pytest.raises(SemanticContractError, match="duplicate JSON key"):
        EncoderManifest.from_bytes(duplicated)

    relabelled = manifest.to_dict()
    relabelled["authority"] = "verified"
    with pytest.raises(SemanticContractError, match="authority"):
        EncoderManifest.from_dict(relabelled)


def test_projection_v1_is_identity_only_and_binds_empty_parameters() -> None:
    source = encoder("alpha", 3)
    projection = ProjectionManifest.identity(source)
    assert ProjectionManifest.from_bytes(projection.canonical_bytes()) == projection
    assert projection.parameter_digest == EMPTY_SHA256
    assert projection.training is None

    values = projection.__dict__.copy()
    values.pop("projection_id")
    values["kind"] = "trained_low_rank"
    with pytest.raises(SemanticContractError, match="only identity"):
        ProjectionManifest(**values)

    values = projection.__dict__.copy()
    values.pop("projection_id")
    values["output_dimension"] = 2
    with pytest.raises(SemanticContractError, match="dimensions must be equal"):
        ProjectionManifest(**values)


def test_space_is_ordered_gapless_unique_and_dimension_bound() -> None:
    first = encoder("alpha", 2)
    second = encoder("beta", 3)
    space = CompositeSpaceSpec.from_encoders(
        (first, second),
        experiment_spec_digest=SPEC_DIGEST,
        amplitude_weights=(0.5, 1.0),
    )
    assert space.total_dimension == 5
    assert tuple(block.offset for block in space.blocks) == (0, 2)
    assert CompositeSpaceSpec.from_bytes(space.canonical_bytes()) == space

    with pytest.raises(SemanticContractError, match="gapless offset"):
        CompositeSpaceSpec(
            (space.blocks[0], replace(space.blocks[1], offset=3)),
            experiment_spec_digest=SPEC_DIGEST,
        )
    with pytest.raises(SemanticContractError, match="unique"):
        CompositeSpaceSpec.from_encoders(
            (first, first), experiment_spec_digest=SPEC_DIGEST
        )
    with pytest.raises(SemanticContractError, match=r"\(0, 1\]"):
        CompositeSpaceSpec.from_encoders(
            (first, second),
            experiment_spec_digest=SPEC_DIGEST,
            amplitude_weights=(0.5, 2.0),
        )
    with pytest.raises(SemanticContractError, match="integer"):
        replace(space.blocks[0], offset=True)


def test_space_loader_recomputes_total_dimension_and_rejects_float_gate() -> None:
    space = CompositeSpaceSpec.from_encoders(
        (encoder("alpha", 2), encoder("beta", 3)),
        experiment_spec_digest=SPEC_DIGEST,
    )
    mutated = space.to_dict()
    mutated["total_dimension"] = 6
    with pytest.raises(SemanticContractError, match="does not match"):
        CompositeSpaceSpec.from_dict(mutated)

    mutated = space.to_dict()
    mutated["active_gate"] = 0.0
    with pytest.raises(SemanticContractError, match="integer"):
        CompositeSpaceSpec.from_dict(mutated)


def test_vector_digests_are_space_and_stage_bound() -> None:
    first = encoder("alpha", 2)
    second = encoder("beta", 2)
    first_projection = ProjectionManifest.identity(first)
    values = (1.0, 0.0)
    digests = {
        vector_digest(values, space_id=first.encoder_id, stage="encoder_output"),
        vector_digest(values, space_id=second.encoder_id, stage="encoder_output"),
        vector_digest(
            values,
            space_id=first_projection.projection_id,
            stage="projection_output",
        ),
    }
    assert len(digests) == 3
    with pytest.raises(SemanticContractError, match="stage"):
        vector_digest(values, space_id=first.encoder_id, stage="mystery")


def test_vector_receipt_roundtrip_rejects_bool_cost_and_tampering() -> None:
    block = CompositeSpaceSpec.from_encoders(
        (encoder("alpha", 2),), experiment_spec_digest=SPEC_DIGEST
    ).blocks[0]
    receipt = receipt_for(block, (1.0, 0.0))
    assert VectorReceipt.from_bytes(receipt.canonical_bytes()) == receipt
    assert receipt.authority == AUTHORITY
    assert receipt.purpose == PURPOSE
    assert b"find parser" not in receipt.canonical_bytes()

    for noncanonical_one in (True, 1.0):
        mutated = receipt.to_dict()
        mutated["encoder_calls"] = noncanonical_one
        with pytest.raises(SemanticContractError, match="integer"):
            VectorReceipt.from_dict(mutated)
    with pytest.raises(SemanticContractError, match="does not match"):
        replace(receipt, input_tokens=4)


def test_composite_vector_and_receipt_are_strict_content_addresses() -> None:
    space = CompositeSpaceSpec.from_encoders(
        (encoder("alpha", 2),), experiment_spec_digest=SPEC_DIGEST
    )
    block = space.blocks[0]
    vector = CompositeVector(
        space.space_id,
        (1.0, 0.0),
        egress_classification="local_only",
        egress_policy_receipt_digest=sha("egress-policy"),
    )
    block_receipt = receipt_for(block, (1.0, 0.0))
    aggregate = CompositeReceipt(
        space_id=space.space_id,
        source_id=block_receipt.source_id,
        revision=block_receipt.revision,
        input_digest=block_receipt.input_digest,
        input_bytes=block_receipt.input_bytes,
        role=block_receipt.role,
        tower=block_receipt.tower,
        vector_id=vector.vector_id,
        block_receipts=(block_receipt,),
        egress_classification="local_only",
        egress_policy_receipt_digest=sha("egress-policy"),
    )
    assert CompositeVector.from_bytes(vector.canonical_bytes()) == vector
    assert CompositeReceipt.from_bytes(aggregate.canonical_bytes()) == aggregate
    assert aggregate.encoder_calls == 1
    assert aggregate.encoder_input_tokens == block_receipt.input_tokens

    wrong_source = replace(block_receipt, source_id="query:q2", receipt_id="")
    with pytest.raises(SemanticContractError, match="source binding"):
        replace(aggregate, block_receipts=(wrong_source,), receipt_id="")


def test_nonfinite_numbers_and_invalid_unicode_refuse() -> None:
    space = CompositeSpaceSpec.from_encoders(
        (encoder("alpha", 2),), experiment_spec_digest=SPEC_DIGEST
    )
    with pytest.raises(SemanticContractError, match="finite"):
        CompositeVector(
            space.space_id,
            (float("nan"), 0.0),
            egress_classification="local_only",
            egress_policy_receipt_digest=sha("egress-policy"),
        )
    with pytest.raises(SemanticContractError, match="surrogate"):
        text_digest("\ud800")


def test_negative_zero_has_one_canonical_vector_representation() -> None:
    space = CompositeSpaceSpec.from_encoders(
        (encoder("alpha", 2),), experiment_spec_digest=SPEC_DIGEST
    )
    negative = CompositeVector(
        space.space_id,
        (-0.0, 1.0),
        egress_classification="local_only",
        egress_policy_receipt_digest=sha("egress-policy"),
    )
    positive = CompositeVector(
        space.space_id,
        (0.0, 1.0),
        egress_classification="local_only",
        egress_policy_receipt_digest=sha("egress-policy"),
    )
    assert negative == positive
    assert negative.canonical_bytes() == positive.canonical_bytes()
