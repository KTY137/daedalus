"""Algebraic and refusal tests for the offline direct-sum backend."""
from __future__ import annotations

import ast
import hashlib
import math
from dataclasses import replace
from pathlib import Path

import pytest

from experiments.forest_v2.tensor_embeddings.algebra import flattened_cosine
from experiments.forest_v2.tensor_embeddings.encoding import (
    PrecomputedFillerBackend,
    RoleFields,
    TensorProductEncoder,
    canonical_source_digest,
    default_spec,
)
from experiments.forest_v2.tensor_semantic_composite.backend import (
    CompositionRequest,
    DirectSumBackend,
    VectorMaterial,
)
from experiments.forest_v2.tensor_semantic_composite.contracts import (
    CompositeSpaceSpec,
    CompositeVector,
    EncoderManifest,
    PACKET_SPEC_DIGEST,
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


def setup_backend() -> DirectSumBackend:
    return DirectSumBackend(
        CompositeSpaceSpec.from_encoders(
            (encoder("alpha", 2), encoder("beta", 3)),
            experiment_spec_digest=SPEC_DIGEST,
            amplitude_weights=(0.5, 1.0),
        )
    )


def material_for(
    backend: DirectSumBackend,
    block_index: int,
    values: tuple[float, ...],
    *,
    source_id: str,
    revision: str,
    text: str,
    tower: str,
    role: str = "content",
) -> VectorMaterial:
    block = backend.space.blocks[block_index]
    receipt = VectorReceipt(
        source_id=source_id,
        revision=revision,
        input_digest=text_digest(text),
        input_bytes=len(text.encode("utf-8")),
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
        input_tokens=2 + block_index,
        producer_receipt_digest=sha(block.encoder.encoder_id + ":producer"),
        execution_receipt_digest=sha(block.encoder.encoder_id + ":execution"),
        cost_receipt_digest=sha(block.encoder.encoder_id + ":cost"),
        egress_classification="local_only",
        egress_policy_receipt_digest=sha("egress-policy"),
    )
    return VectorMaterial(receipt, values, values)


def materials_for(
    backend: DirectSumBackend,
    vectors: tuple[tuple[float, ...], ...],
    *,
    source_id: str,
    revision: str,
    text: str,
    tower: str,
) -> dict[str, VectorMaterial]:
    return {
        block.projection.projection_id: material_for(
            backend,
            index,
            vectors[index],
            source_id=source_id,
            revision=revision,
            text=text,
            tower=tower,
        )
        for index, block in enumerate(backend.space.blocks)
    }


def request_for(
    backend: DirectSumBackend,
    vectors: tuple[tuple[float, ...], ...],
    *,
    source_id: str,
    revision: str,
    text: str,
    tower: str,
) -> CompositionRequest:
    return CompositionRequest(
        materials=materials_for(
            backend,
            vectors,
            source_id=source_id,
            revision=revision,
            text=text,
            tower=tower,
        ),
        source_id=source_id,
        revision=revision,
        text=text,
        role="content",
        tower=tower,
        egress_classification="local_only",
        egress_policy_receipt_digest=sha("egress-policy"),
    )


def compose_request(
    backend: DirectSumBackend, request: CompositionRequest
):
    return backend.compose_request(request)


def test_backend_contract_is_canonical_and_tamper_evident() -> None:
    backend = setup_backend()
    recovered = DirectSumBackend.from_bytes(
        backend.canonical_bytes(), space=backend.space
    )
    assert recovered == backend
    assert recovered.canonical_bytes() == backend.canonical_bytes()

    mutated = backend.to_dict()
    mutated["network"] = "allowed"
    with pytest.raises(SemanticContractError, match="network"):
        DirectSumBackend.from_dict(mutated, space=backend.space)
    with pytest.raises(SemanticContractError, match="does not match"):
        replace(backend, backend_id="semantic-direct-sum:" + "0" * 64)


def test_direct_sum_equals_declared_weight_squared_score_fusion() -> None:
    backend = setup_backend()
    query_vectors = ((1.0, 0.0), (0.0, 1.0, 0.0))
    document_vectors = ((0.6, 0.8), (0.0, 0.8, 0.6))
    query_request = request_for(
        backend,
        query_vectors,
        source_id="query:q1",
        revision="revision-1",
        text="find parser",
        tower="query",
    )
    document_request = request_for(
        backend,
        document_vectors,
        source_id="src/parser.py",
        revision="revision-1",
        text="parser implementation",
        tower="document",
    )
    query = compose_request(backend, query_request)
    document = compose_request(backend, document_request)

    per_block_dots = {
        backend.space.blocks[0].projection.projection_id: 0.6,
        backend.space.blocks[1].projection.projection_id: 0.8,
    }
    expected = 0.5**2 * 0.6 + 1.0**2 * 0.8
    assert backend.score(query_request, document_request) == pytest.approx(
        expected, abs=1e-15
    )
    assert backend.weighted_score_fusion(per_block_dots) == pytest.approx(
        expected, abs=1e-15
    )
    assert math.sqrt(
        sum(value * value for value in query.vector.values)
    ) == pytest.approx(
        math.sqrt(1.25), abs=1e-15
    )
    assert query.receipt.encoder_calls == 2
    assert query.receipt.encoder_input_tokens == 5
    assert document.receipt.encoder_calls == 2


def _tensor_cosine_for_precomputed_pair(
    query_text: str,
    document_text: str,
    query_values: tuple[float, ...],
    document_values: tuple[float, ...],
) -> float:
    filler = PrecomputedFillerBackend(
        {
            PrecomputedFillerBackend.key(query_text, "content"): query_values,
            PrecomputedFillerBackend.key(document_text, "content"): document_values,
        }
    )
    encoder_impl = TensorProductEncoder(
        default_spec(seed=11, feature_dimension=len(query_values)), filler
    )
    query = encoder_impl.encode(
        RoleFields(content=query_text),
        source_id="query:q1",
        source_digest=canonical_source_digest(query_text),
        revision="revision-1",
        plane="code",
    )
    document = encoder_impl.encode(
        RoleFields(content=document_text),
        source_id="src/parser.py",
        source_digest=canonical_source_digest(document_text),
        revision="revision-1",
        plane="code",
    )
    return flattened_cosine(query.tensor, document.tensor)


def test_direct_sum_plugs_into_existing_tensor_construct_without_new_kernel() -> None:
    """Packet 001's tensor construct sees one wider filler, not a new subsystem."""

    backend = setup_backend()
    query_text = "find parser"
    document_text = "parser implementation"
    query_blocks = ((1.0, 0.0), (0.0, 1.0, 0.0))
    document_blocks = ((0.6, 0.8), (0.0, 0.8, 0.6))
    query = backend.compose(
        materials_for(
            backend,
            query_blocks,
            source_id="query:q1",
            revision="revision-1",
            text=query_text,
            tower="query",
        ),
        source_id="query:q1",
        revision="revision-1",
        text=query_text,
        role="content",
        tower="query",
        egress_classification="local_only",
        egress_policy_receipt_digest=sha("egress-policy"),
    )
    document = backend.compose(
        materials_for(
            backend,
            document_blocks,
            source_id="src/parser.py",
            revision="revision-1",
            text=document_text,
            tower="document",
        ),
        source_id="src/parser.py",
        revision="revision-1",
        text=document_text,
        role="content",
        tower="document",
        egress_classification="local_only",
        egress_policy_receipt_digest=sha("egress-policy"),
    )

    direct_tensor_score = _tensor_cosine_for_precomputed_pair(
        query_text,
        document_text,
        query.vector.values,
        document.vector.values,
    )
    singleton_scores = tuple(
        _tensor_cosine_for_precomputed_pair(
            query_text,
            document_text,
            query_blocks[index],
            document_blocks[index],
        )
        for index in range(2)
    )
    normalized_fusion = backend.weighted_score_fusion(
        {
            block.projection.projection_id: singleton_scores[index]
            for index, block in enumerate(backend.space.blocks)
        }
    ) / backend.space.amplitude_norm_squared
    assert direct_tensor_score == pytest.approx(normalized_fusion, abs=1e-15)
    assert direct_tensor_score == pytest.approx(0.76, abs=1e-15)


def test_accepted_float32_norm_error_is_removed_before_tensor_null() -> None:
    backend = setup_backend()
    query_text = "near unit query"
    document_text = "near unit document"
    query_blocks = ((1.0000005, 0.0), (0.0, 0.9999995, 0.0))
    document_blocks = (
        (0.6 * 0.9999996, 0.8 * 0.9999996),
        (0.0, 0.8 * 1.0000004, 0.6 * 1.0000004),
    )
    query_request = request_for(
        backend,
        query_blocks,
        source_id="query:q-near",
        revision="revision-1",
        text=query_text,
        tower="query",
    )
    document_request = request_for(
        backend,
        document_blocks,
        source_id="src/near.py",
        revision="revision-1",
        text=document_text,
        tower="document",
    )
    query = compose_request(backend, query_request)
    document = compose_request(backend, document_request)
    direct_tensor_score = _tensor_cosine_for_precomputed_pair(
        query_text,
        document_text,
        query.vector.values,
        document.vector.values,
    )
    singleton_scores = tuple(
        _tensor_cosine_for_precomputed_pair(
            query_text,
            document_text,
            query_blocks[index],
            document_blocks[index],
        )
        for index in range(2)
    )
    normalized_fusion = backend.weighted_score_fusion(
        {
            block.projection.projection_id: singleton_scores[index]
            for index, block in enumerate(backend.space.blocks)
        }
    ) / backend.space.amplitude_norm_squared
    assert abs(direct_tensor_score - normalized_fusion) <= 1e-10
    assert backend.score(query_request, document_request) == pytest.approx(
        backend.weighted_score_fusion(
            {
                block.projection.projection_id: singleton_scores[index]
                for index, block in enumerate(backend.space.blocks)
            }
        ),
        abs=1e-10,
    )


def test_missing_extra_and_mixed_source_blocks_refuse_without_fallback() -> None:
    backend = setup_backend()
    materials = materials_for(
        backend,
        ((1.0, 0.0), (0.0, 1.0, 0.0)),
        source_id="query:q1",
        revision="revision-1",
        text="find parser",
        tower="query",
    )
    missing = dict(materials)
    missing.pop(next(iter(missing)))
    with pytest.raises(SemanticContractError, match="missing="):
        backend.compose(
            missing,
            source_id="query:q1",
            revision="revision-1",
            text="find parser",
            role="content",
            tower="query",
            egress_classification="local_only",
            egress_policy_receipt_digest=sha("egress-policy"),
        )

    extra = dict(materials)
    extra["projection:" + "0" * 64] = next(iter(materials.values()))
    with pytest.raises(SemanticContractError, match="extra="):
        backend.compose(
            extra,
            source_id="query:q1",
            revision="revision-1",
            text="find parser",
            role="content",
            tower="query",
            egress_classification="local_only",
            egress_policy_receipt_digest=sha("egress-policy"),
        )

    mixed = dict(materials)
    second_key = backend.space.blocks[1].projection.projection_id
    second = mixed[second_key]
    mixed[second_key] = replace(
        second,
        receipt=replace(second.receipt, source_id="query:other", receipt_id=""),
    )
    with pytest.raises(SemanticContractError, match="source_id"):
        backend.compose(
            mixed,
            source_id="query:q1",
            revision="revision-1",
            text="find parser",
            role="content",
            tower="query",
            egress_classification="local_only",
            egress_policy_receipt_digest=sha("egress-policy"),
        )


def test_vector_substitution_tower_swap_and_identity_change_refuse() -> None:
    backend = setup_backend()
    materials = materials_for(
        backend,
        ((1.0, 0.0), (0.0, 1.0, 0.0)),
        source_id="query:q1",
        revision="revision-1",
        text="find parser",
        tower="query",
    )
    first_key = backend.space.blocks[0].projection.projection_id
    original = materials[first_key]

    substituted = dict(materials)
    substituted[first_key] = replace(original, source_values=(0.0, 1.0), output_values=(0.0, 1.0))
    with pytest.raises(SemanticContractError, match="digest"):
        backend.compose(
            substituted,
            source_id="query:q1",
            revision="revision-1",
            text="find parser",
            role="content",
            tower="query",
            egress_classification="local_only",
            egress_policy_receipt_digest=sha("egress-policy"),
        )

    swapped_tower = dict(materials)
    swapped_tower[first_key] = replace(
        original,
        receipt=replace(original.receipt, tower="document", receipt_id=""),
    )
    with pytest.raises(SemanticContractError, match="tower"):
        backend.compose(
            swapped_tower,
            source_id="query:q1",
            revision="revision-1",
            text="find parser",
            role="content",
            tower="query",
            egress_classification="local_only",
            egress_policy_receipt_digest=sha("egress-policy"),
        )

    changed = (0.0, 1.0)
    changed_output = dict(materials)
    changed_output[first_key] = replace(
        original,
        output_values=changed,
        receipt=replace(
            original.receipt,
            output_vector_digest=vector_digest(
                changed,
                space_id=backend.space.blocks[0].projection.projection_id,
                stage="projection_output",
            ),
            receipt_id="",
        ),
    )
    with pytest.raises(SemanticContractError, match="identity projection changed"):
        backend.compose(
            changed_output,
            source_id="query:q1",
            revision="revision-1",
            text="find parser",
            role="content",
            tower="query",
            egress_classification="local_only",
            egress_policy_receipt_digest=sha("egress-policy"),
        )


@pytest.mark.parametrize(
    ("values", "message"),
    (
        ((0.0, 0.0), "L2-normalized"),
        ((2.0, 0.0), "L2-normalized"),
        ((float("inf"), 0.0), "finite"),
        ((True, 0.0), "real number"),
    ),
)
def test_invalid_material_values_refuse(values: tuple[object, ...], message: str) -> None:
    backend = setup_backend()
    block = backend.space.blocks[0]
    valid = material_for(
        backend,
        0,
        (1.0, 0.0),
        source_id="query:q1",
        revision="revision-1",
        text="find parser",
        tower="query",
    )
    if all(
        not isinstance(item, bool)
        and isinstance(item, (int, float))
        and math.isfinite(float(item))
        for item in values
    ):
        invalid = replace(
            valid,
            source_values=values,
            output_values=values,
            receipt=replace(
                valid.receipt,
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
                receipt_id="",
            ),
        )
        with pytest.raises(SemanticContractError, match=message):
            backend._validate_material(
                block,
                invalid,
                source_id="query:q1",
                revision="revision-1",
                input_digest=text_digest("find parser"),
                input_bytes=len("find parser"),
                role="content",
                tower="query",
                egress_classification="local_only",
                egress_policy_receipt_digest=sha("egress-policy"),
            )
    else:
        with pytest.raises(SemanticContractError, match=message):
            VectorMaterial(valid.receipt, values, values)  # type: ignore[arg-type]


def test_empty_role_is_explicit_canonical_null_not_missingness() -> None:
    backend = setup_backend()
    with pytest.raises(SemanticContractError, match="canonical_null"):
        backend.compose(
            {},
            source_id="src/a.py",
            revision="revision-1",
            text="",
            role="neighbor",
            tower="document",
            egress_classification="local_only",
            egress_policy_receipt_digest=sha("egress-policy"),
        )
    composed = backend.canonical_null(
        source_id="src/a.py",
        revision="revision-1",
        text="",
        role="neighbor",
        tower="document",
        egress_classification="local_only",
        egress_policy_receipt_digest=sha("egress-policy"),
    )
    assert composed.vector.values == (0.0,) * backend.space.total_dimension
    assert composed.receipt.kind == "canonical_null"
    assert composed.receipt.encoder_calls == 0
    assert composed.receipt.encoder_input_tokens == 0
    with pytest.raises(SemanticContractError, match="exact empty text"):
        backend.canonical_null(
            source_id="src/a.py",
            revision="revision-1",
            text="encoder failed",
            role="neighbor",
            tower="document",
            egress_classification="local_only",
            egress_policy_receipt_digest=sha("egress-policy"),
        )


def test_empty_composition_requests_score_as_zero_without_encoder_calls() -> None:
    backend = setup_backend()
    query_null = CompositionRequest(
        materials={},
        source_id="query:q1",
        revision="revision-1",
        text="",
        role="neighbor",
        tower="query",
        egress_classification="local_only",
        egress_policy_receipt_digest=sha("egress-policy"),
    )
    document_null = CompositionRequest(
        materials={},
        source_id="src/a.py",
        revision="revision-1",
        text="",
        role="neighbor",
        tower="document",
        egress_classification="local_only",
        egress_policy_receipt_digest=sha("egress-policy"),
    )
    document = request_for(
        backend,
        ((0.6, 0.8), (0.0, 0.8, 0.6)),
        source_id="src/a.py",
        revision="revision-1",
        text="parser implementation",
        tower="document",
    )
    assert backend.score(query_null, document) == 0.0
    assert backend.score(query_null, document_null) == 0.0

    illegal_missingness = replace(
        query_null,
        materials=materials_for(
            backend,
            ((1.0, 0.0), (0.0, 1.0, 0.0)),
            source_id="query:q1",
            revision="revision-1",
            text="find parser",
            tower="query",
        ),
    )
    with pytest.raises(SemanticContractError, match="must not carry"):
        backend.compose_request(illegal_missingness)


def test_cross_space_and_unverified_raw_vector_scoring_refuse() -> None:
    backend = setup_backend()
    query_request = request_for(
        backend,
        ((1.0, 0.0), (0.0, 1.0, 0.0)),
        source_id="query:q1",
        revision="revision-1",
        text="find parser",
        tower="query",
    )
    other = DirectSumBackend(
        CompositeSpaceSpec.from_encoders(
            (encoder("alpha", 2), encoder("beta", 3)),
            experiment_spec_digest=SPEC_DIGEST,
            amplitude_weights=(0.25, 1.0),
        )
    )
    document_request = request_for(
        other,
        ((0.6, 0.8), (0.0, 0.8, 0.6)),
        source_id="src/parser.py",
        revision="revision-1",
        text="parser implementation",
        tower="document",
    )
    query = compose_request(backend, query_request)
    document = compose_request(other, document_request)
    with pytest.raises(SemanticContractError, match="complete CompositionRequest"):
        backend.score(query, document)  # type: ignore[arg-type]

    raw_unverified = CompositeVector(
        backend.space.space_id,
        (1.0, 0.0),
        egress_classification="local_only",
        egress_policy_receipt_digest=sha("egress-policy"),
    )
    with pytest.raises(SemanticContractError, match="complete CompositionRequest"):
        backend.score(query_request, raw_unverified)  # type: ignore[arg-type]

    forged_result = replace(
        query,
        vector=CompositeVector(
            backend.space.space_id,
            tuple(10.0 for _ in range(backend.space.total_dimension)),
            egress_classification="local_only",
            egress_policy_receipt_digest=sha("egress-policy"),
        ),
        receipt=replace(
            query.receipt,
            vector_id=CompositeVector(
                backend.space.space_id,
                tuple(10.0 for _ in range(backend.space.total_dimension)),
                egress_classification="local_only",
                egress_policy_receipt_digest=sha("egress-policy"),
            ).vector_id,
            receipt_id="",
        ),
    )
    with pytest.raises(SemanticContractError, match="complete CompositionRequest"):
        backend.score(forged_result, document_request)  # type: ignore[arg-type]


def test_runtime_modules_are_inert_and_expose_no_authority_api() -> None:
    package = Path(__file__).resolve().parent
    runtime_files = (package / "contracts.py", package / "backend.py")
    forbidden_import_roots = {
        "aiohttp",
        "anthropic",
        "boto3",
        "httpx",
        "openai",
        "requests",
        "socket",
        "subprocess",
        "torch",
        "transformers",
        "urllib",
    }
    forbidden_class_or_function_names = {
        "Decision",
        "Promotion",
        "TrustedEdge",
        "advance",
        "embed",
        "kill",
        "promote",
    }
    for path in runtime_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports: set[str] = set()
        declarations: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".", 1)[0])
            elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                declarations.add(node.name)
        assert not imports & forbidden_import_roots
        assert not declarations & forbidden_class_or_function_names
