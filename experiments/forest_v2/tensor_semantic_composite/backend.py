"""Offline direct-sum composition over caller-supplied semantic vectors.

This module deliberately has no model client and no fallback backend.  It
verifies a complete set of receipts and materialized vectors for one non-empty
input, then places the weighted blocks in their frozen offsets.  Missing or
extra blocks invalidate the composition.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Sequence

from experiments.forest_v2.tensor_embeddings.contracts import (
    canonical_digest,
    canonical_json_bytes,
)

from .contracts import (
    AUTHORITY,
    EGRESS_CLASSIFICATIONS,
    PURPOSE,
    ROLES,
    TOWERS,
    UNIT_NORM_TOLERANCE,
    CompositeBlock,
    CompositeReceipt,
    CompositeSpaceSpec,
    CompositeVector,
    SemanticContractError,
    VectorReceipt,
    _object_with_keys,
    _strict_json_loads,
    text_digest,
    vector_digest,
)


BACKEND_SCHEMA = "forest-v2.semantic-composite.direct-sum-backend/1"
EXECUTION_MODE = "precomputed_vectors_only"


def _finite_vector(value: object, *, label: str) -> tuple[float, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise SemanticContractError(f"{label} must be a one-dimensional sequence")
    result: list[float] = []
    for index, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise SemanticContractError(f"{label}[{index}] must be a real number")
        number = float(item)
        if not math.isfinite(number):
            raise SemanticContractError(f"{label}[{index}] must be finite")
        result.append(0.0 if number == 0.0 else number)
    if not result:
        raise SemanticContractError(f"{label} must not be empty")
    return tuple(result)


def _norm(values: Sequence[float], *, label: str) -> float:
    try:
        squared = math.fsum(value * value for value in values)
        result = math.sqrt(squared)
    except (OverflowError, ValueError) as exc:
        raise SemanticContractError(f"{label} norm is not finite") from exc
    if not math.isfinite(result):
        raise SemanticContractError(f"{label} norm is not finite")
    return result


def _canonical_unit(values: Sequence[float], *, label: str) -> tuple[float, ...]:
    norm = _norm(values, label=label)
    if norm == 0.0 or abs(norm - 1.0) > UNIT_NORM_TOLERANCE:
        raise SemanticContractError(
            f"{label} must be L2-normalized within {UNIT_NORM_TOLERANCE:g}"
        )
    normalized = tuple(value / norm for value in values)
    if not all(math.isfinite(value) for value in normalized):
        raise SemanticContractError(f"{label} normalization is not finite")
    return normalized


def _utf8_size(text: str) -> int:
    if type(text) is not str:
        raise SemanticContractError("model input must be text")
    try:
        return len(text.encode("utf-8", "strict"))
    except UnicodeEncodeError as exc:
        raise SemanticContractError("model input contains an invalid Unicode surrogate") from exc


@dataclass(frozen=True)
class VectorMaterial:
    """Ephemeral values paired with a redacted, content-addressed receipt."""

    receipt: VectorReceipt
    source_values: tuple[float, ...]
    output_values: tuple[float, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.receipt, VectorReceipt):
            raise SemanticContractError("receipt must be a VectorReceipt")
        object.__setattr__(
            self,
            "source_values",
            _finite_vector(self.source_values, label="source_values"),
        )
        object.__setattr__(
            self,
            "output_values",
            _finite_vector(self.output_values, label="output_values"),
        )


@dataclass(frozen=True)
class CompositionRequest:
    """Ephemeral, non-serializable input retained for fail-closed scoring."""

    materials: Mapping[str, VectorMaterial]
    source_id: str
    revision: str
    text: str
    role: str
    tower: str
    egress_classification: str
    egress_policy_receipt_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.materials, Mapping):
            raise SemanticContractError("materials must be a projection-ID mapping")
        copied = dict(self.materials)
        if len(copied) != len(self.materials):
            raise SemanticContractError("materials contain ambiguous duplicate keys")
        object.__setattr__(self, "materials", MappingProxyType(copied))


@dataclass(frozen=True)
class ComposedSemanticVector:
    """Composition result; scoring deliberately revalidates the source request."""

    vector: CompositeVector
    receipt: CompositeReceipt

    def __post_init__(self) -> None:
        if not isinstance(self.vector, CompositeVector) or not isinstance(
            self.receipt, CompositeReceipt
        ):
            raise SemanticContractError("composed vector and receipt have wrong types")
        if self.vector.space_id != self.receipt.space_id:
            raise SemanticContractError("composed vector and receipt spaces differ")
        if self.vector.vector_id != self.receipt.vector_id:
            raise SemanticContractError("composed receipt does not bind its vector")
        if (
            self.vector.egress_classification != self.receipt.egress_classification
            or self.vector.egress_policy_receipt_digest
            != self.receipt.egress_policy_receipt_digest
        ):
            raise SemanticContractError("composed vector lost its egress binding")


@dataclass(frozen=True)
class DirectSumBackend:
    """Precomputed-only, fail-closed composer for one exact block space."""

    space: CompositeSpaceSpec
    backend_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.space, CompositeSpaceSpec):
            raise SemanticContractError("space must be a CompositeSpaceSpec")
        expected = self._computed_id()
        if type(self.backend_id) is not str:
            raise SemanticContractError("backend_id must be a string")
        if self.backend_id and self.backend_id != expected:
            raise SemanticContractError("backend_id does not match the backend payload")
        object.__setattr__(self, "backend_id", expected)

    def _payload(self) -> dict[str, object]:
        return {
            "schema": BACKEND_SCHEMA,
            "authority": AUTHORITY,
            "purpose": PURPOSE,
            "promotion": "forbidden",
            "execution_mode": EXECUTION_MODE,
            "network": "forbidden",
            "model_execution": "forbidden",
            "filesystem_io": "forbidden",
            "subprocess": "forbidden",
            "composite_space_id": self.space.space_id,
            "encoder_manifest_ids": [
                block.encoder.encoder_id for block in self.space.blocks
            ],
            "projection_manifest_ids": [
                block.projection.projection_id for block in self.space.blocks
            ],
        }

    def _computed_id(self) -> str:
        return "semantic-direct-sum:" + canonical_digest(
            self._payload(), domain=BACKEND_SCHEMA
        )

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "backend_id": self.backend_id}

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(
        cls, value: object, *, space: CompositeSpaceSpec
    ) -> "DirectSumBackend":
        if not isinstance(space, CompositeSpaceSpec):
            raise SemanticContractError("space must be a CompositeSpaceSpec")
        data = _object_with_keys(
            value,
            frozenset(
                {
                    "schema",
                    "authority",
                    "purpose",
                    "promotion",
                    "execution_mode",
                    "network",
                    "model_execution",
                    "filesystem_io",
                    "subprocess",
                    "composite_space_id",
                    "encoder_manifest_ids",
                    "projection_manifest_ids",
                    "backend_id",
                }
            ),
            label="DirectSumBackend",
        )
        frozen = {
            "schema": BACKEND_SCHEMA,
            "authority": AUTHORITY,
            "purpose": PURPOSE,
            "promotion": "forbidden",
            "execution_mode": EXECUTION_MODE,
            "network": "forbidden",
            "model_execution": "forbidden",
            "filesystem_io": "forbidden",
            "subprocess": "forbidden",
            "composite_space_id": space.space_id,
            "encoder_manifest_ids": [block.encoder.encoder_id for block in space.blocks],
            "projection_manifest_ids": [
                block.projection.projection_id for block in space.blocks
            ],
        }
        for key, expected in frozen.items():
            if data[key] != expected:
                raise SemanticContractError(f"DirectSumBackend {key} was relabelled")
        return cls(space=space, backend_id=data["backend_id"])  # type: ignore[arg-type]

    @classmethod
    def from_bytes(
        cls, raw: bytes | str, *, space: CompositeSpaceSpec
    ) -> "DirectSumBackend":
        return cls.from_dict(_strict_json_loads(raw), space=space)

    @property
    def required_projection_ids(self) -> frozenset[str]:
        return frozenset(block.projection.projection_id for block in self.space.blocks)

    def _validate_material(
        self,
        block: CompositeBlock,
        material: VectorMaterial,
        *,
        source_id: str,
        revision: str,
        input_digest: str,
        input_bytes: int,
        role: str,
        tower: str,
        egress_classification: str,
        egress_policy_receipt_digest: str,
    ) -> tuple[float, ...]:
        receipt = material.receipt
        expected_source = {
            "source_id": source_id,
            "revision": revision,
            "input_digest": input_digest,
            "input_bytes": input_bytes,
            "role": role,
            "tower": tower,
            "egress_classification": egress_classification,
            "egress_policy_receipt_digest": egress_policy_receipt_digest,
        }
        for field_name, expected in expected_source.items():
            if getattr(receipt, field_name) != expected:
                raise SemanticContractError(
                    f"receipt {field_name} does not match the composed input"
                )
        if receipt.encoder_id != block.encoder.encoder_id:
            raise SemanticContractError("receipt belongs to a different encoder block")
        if receipt.projection_id != block.projection.projection_id:
            raise SemanticContractError("receipt belongs to a different projection block")
        if receipt.source_dimension != block.encoder.output_dimension:
            raise SemanticContractError("receipt source dimension mismatches encoder")
        if receipt.source_dimension != block.projection.source_dimension:
            raise SemanticContractError("receipt source dimension mismatches projection")
        if receipt.output_dimension != block.output_dimension:
            raise SemanticContractError("receipt output dimension mismatches block")
        if len(material.source_values) != receipt.source_dimension:
            raise SemanticContractError("source vector length mismatches receipt")
        if len(material.output_values) != receipt.output_dimension:
            raise SemanticContractError("output vector length mismatches receipt")

        source_digest = vector_digest(
            material.source_values,
            space_id=block.encoder.encoder_id,
            stage="encoder_output",
        )
        output_digest = vector_digest(
            material.output_values,
            space_id=block.projection.projection_id,
            stage="projection_output",
        )
        if receipt.source_vector_digest != source_digest:
            raise SemanticContractError("source vector digest mismatches receipt")
        if receipt.output_vector_digest != output_digest:
            raise SemanticContractError("output vector digest mismatches receipt")

        _canonical_unit(material.source_values, label="source vector")
        if block.projection.kind == "identity" and (
            material.source_values != material.output_values
        ):
            raise SemanticContractError("identity projection changed vector values")
        # The 1e-6 admission tolerance accommodates float32 producer output,
        # but leaving those small norm errors in the weighted blocks would make
        # the frozen 1e-10 direct-sum/fusion null false.  Normalize once in
        # reference float64 after digest/identity verification.  The aggregate
        # CompositeVector ID binds the exact normalized result.
        return _canonical_unit(material.output_values, label="output vector")

    def compose(
        self,
        materials: Mapping[str, VectorMaterial],
        *,
        source_id: str,
        revision: str,
        text: str,
        role: str,
        tower: str,
        egress_classification: str,
        egress_policy_receipt_digest: str,
    ) -> ComposedSemanticVector:
        """Validate and concatenate every required block for one input."""

        if not isinstance(materials, Mapping):
            raise SemanticContractError("materials must be a projection-ID mapping")
        if any(type(key) is not str for key in materials):
            raise SemanticContractError("material keys must be projection IDs")
        if type(source_id) is not str or not source_id:
            raise SemanticContractError("source_id must be non-empty text")
        if type(revision) is not str or not revision:
            raise SemanticContractError("revision must be non-empty text")
        input_bytes = _utf8_size(text)
        if input_bytes == 0:
            raise SemanticContractError(
                "empty role input is canonical_null, not a missing semantic vector"
            )
        if role not in ROLES:
            raise SemanticContractError(f"role must be one of {ROLES!r}")
        if tower not in TOWERS:
            raise SemanticContractError(f"tower must be one of {TOWERS!r}")
        if egress_classification not in EGRESS_CLASSIFICATIONS:
            raise SemanticContractError(
                f"egress_classification must be one of {EGRESS_CLASSIFICATIONS!r}"
            )
        actual_ids = frozenset(materials.keys())
        if actual_ids != self.required_projection_ids:
            missing = sorted(self.required_projection_ids - actual_ids)
            extra = sorted(actual_ids - self.required_projection_ids)
            raise SemanticContractError(
                f"semantic blocks must be complete; missing={missing!r}, extra={extra!r}"
            )
        if any(not isinstance(material, VectorMaterial) for material in materials.values()):
            raise SemanticContractError("every material must be a VectorMaterial")

        digest = text_digest(text)
        values: list[float] = []
        receipts: list[VectorReceipt] = []
        for block in self.space.blocks:
            material = materials[block.projection.projection_id]
            output = self._validate_material(
                block,
                material,
                source_id=source_id,
                revision=revision,
                input_digest=digest,
                input_bytes=input_bytes,
                role=role,
                tower=tower,
                egress_classification=egress_classification,
                egress_policy_receipt_digest=egress_policy_receipt_digest,
            )
            weighted = tuple(block.amplitude_weight * value for value in output)
            if len(values) != block.offset:
                raise SemanticContractError("runtime block offset is not gapless")
            if not all(math.isfinite(value) for value in weighted):
                raise SemanticContractError("weighted block contains a non-finite value")
            values.extend(weighted)
            receipts.append(material.receipt)

        if len(values) != self.space.total_dimension:
            raise SemanticContractError("composed vector has the wrong total dimension")
        vector = CompositeVector(
            space_id=self.space.space_id,
            values=tuple(values),
            egress_classification=egress_classification,
            egress_policy_receipt_digest=egress_policy_receipt_digest,
        )
        receipt = CompositeReceipt(
            space_id=self.space.space_id,
            source_id=source_id,
            revision=revision,
            input_digest=digest,
            input_bytes=input_bytes,
            role=role,
            tower=tower,
            vector_id=vector.vector_id,
            block_receipts=tuple(receipts),
            egress_classification=egress_classification,
            egress_policy_receipt_digest=egress_policy_receipt_digest,
        )
        return ComposedSemanticVector(vector=vector, receipt=receipt)

    def canonical_null(
        self,
        *,
        source_id: str,
        revision: str,
        text: str,
        role: str,
        tower: str,
        egress_classification: str,
        egress_policy_receipt_digest: str,
    ) -> ComposedSemanticVector:
        """Represent an actually empty role without minting encoder calls."""

        if role not in ROLES:
            raise SemanticContractError(f"role must be one of {ROLES!r}")
        if tower not in TOWERS:
            raise SemanticContractError(f"tower must be one of {TOWERS!r}")
        if type(text) is not str or text != "":
            raise SemanticContractError(
                "canonical_null requires the caller to supply exact empty text"
            )
        if egress_classification not in EGRESS_CLASSIFICATIONS:
            raise SemanticContractError(
                f"egress_classification must be one of {EGRESS_CLASSIFICATIONS!r}"
            )
        vector = CompositeVector(
            space_id=self.space.space_id,
            values=tuple(0.0 for _ in range(self.space.total_dimension)),
            egress_classification=egress_classification,
            egress_policy_receipt_digest=egress_policy_receipt_digest,
        )
        receipt = CompositeReceipt(
            space_id=self.space.space_id,
            source_id=source_id,
            revision=revision,
            input_digest=text_digest(text),
            input_bytes=0,
            role=role,
            tower=tower,
            vector_id=vector.vector_id,
            block_receipts=(),
            egress_classification=egress_classification,
            egress_policy_receipt_digest=egress_policy_receipt_digest,
            kind="canonical_null",
        )
        return ComposedSemanticVector(vector=vector, receipt=receipt)

    def score(
        self,
        query: CompositionRequest,
        document: CompositionRequest,
    ) -> float:
        """Revalidate both complete inputs, then sum corresponding block dots."""

        if not isinstance(query, CompositionRequest) or not isinstance(
            document, CompositionRequest
        ):
            raise SemanticContractError(
                "score expects two complete CompositionRequest objects"
            )
        if query.tower != "query" or document.tower != "document":
            raise SemanticContractError("score requires query and document tower order")
        composed_query = self.compose_request(query)
        composed_document = self.compose_request(document)
        return self._score_composed(composed_query, composed_document)

    def compose_request(
        self, request: CompositionRequest
    ) -> ComposedSemanticVector:
        """Dispatch exact empty input to null; validate all other inputs."""

        if not isinstance(request, CompositionRequest):
            raise SemanticContractError("compose_request expects a CompositionRequest")
        if request.text == "":
            if request.materials:
                raise SemanticContractError(
                    "canonical empty input must not carry encoder materials"
                )
            return self.canonical_null(
                source_id=request.source_id,
                revision=request.revision,
                text=request.text,
                role=request.role,
                tower=request.tower,
                egress_classification=request.egress_classification,
                egress_policy_receipt_digest=request.egress_policy_receipt_digest,
            )
        return self.compose(
            request.materials,
            source_id=request.source_id,
            revision=request.revision,
            text=request.text,
            role=request.role,
            tower=request.tower,
            egress_classification=request.egress_classification,
            egress_policy_receipt_digest=request.egress_policy_receipt_digest,
        )

    def _score_composed(
        self,
        query: ComposedSemanticVector,
        document: ComposedSemanticVector,
    ) -> float:
        if (
            query.vector.space_id != self.space.space_id
            or document.vector.space_id != self.space.space_id
        ):
            raise SemanticContractError("cross-space scoring is forbidden")
        expected_receipt_ids = tuple(
            block.projection.projection_id for block in self.space.blocks
        )
        for label, composed in (("query", query), ("document", document)):
            if composed.receipt.kind == "encoded":
                actual_receipt_ids = tuple(
                    receipt.projection_id
                    for receipt in composed.receipt.block_receipts
                )
                if actual_receipt_ids != expected_receipt_ids:
                    raise SemanticContractError(
                        f"{label} receipt does not contain the exact ordered block census"
                    )
        if (
            len(query.vector.values) != self.space.total_dimension
            or len(document.vector.values) != self.space.total_dimension
        ):
            raise SemanticContractError("composite vector dimension mismatches space")
        block_scores: list[float] = []
        for block in self.space.blocks:
            products = (
                query.vector.values[index] * document.vector.values[index]
                for index in range(block.offset, block.stop)
            )
            try:
                score = math.fsum(products)
            except OverflowError as exc:
                raise SemanticContractError("block score overflowed") from exc
            if not math.isfinite(score):
                raise SemanticContractError("block score is not finite")
            block_scores.append(score)
        try:
            result = math.fsum(block_scores)
        except OverflowError as exc:
            raise SemanticContractError("composite score overflowed") from exc
        if not math.isfinite(result):
            raise SemanticContractError("composite score is not finite")
        return result

    def weighted_score_fusion(self, block_dots: Mapping[str, float]) -> float:
        """The pre-registered algebraic null equivalent to :meth:`score`."""

        if not isinstance(block_dots, Mapping):
            raise SemanticContractError("block_dots must be a projection-ID mapping")
        if frozenset(block_dots) != self.required_projection_ids:
            raise SemanticContractError("score fusion requires exactly every frozen block")
        terms: list[float] = []
        for block in self.space.blocks:
            raw = block_dots[block.projection.projection_id]
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise SemanticContractError("each block dot must be a real number")
            score = float(raw)
            term = block.amplitude_weight**2 * score
            if not math.isfinite(score) or not math.isfinite(term):
                raise SemanticContractError("score fusion term must be finite")
            terms.append(term)
        try:
            result = math.fsum(terms)
        except OverflowError as exc:
            raise SemanticContractError("score fusion overflowed") from exc
        if not math.isfinite(result):
            raise SemanticContractError("score fusion is not finite")
        return result


__all__ = [
    "BACKEND_SCHEMA",
    "EXECUTION_MODE",
    "CompositionRequest",
    "ComposedSemanticVector",
    "DirectSumBackend",
    "VectorMaterial",
]
