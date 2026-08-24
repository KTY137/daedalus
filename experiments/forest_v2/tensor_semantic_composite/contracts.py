"""Strict contracts for the semantic direct-sum Gate-0 experiment.

The contracts are deliberately inert and stdlib-only.  They bind externally
produced encoder vectors and receipts but never execute a model, read a file,
call a network service, or confer evidentiary authority.  Every vector remains
a retrieval proposal derived from caller-supplied, unverified material.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Mapping, Sequence

from experiments.forest_v2.tensor_embeddings.contracts import (
    ContractError,
    canonical_digest,
    canonical_json_bytes,
)


ENCODER_SCHEMA = "forest-v2.semantic-composite.encoder-manifest/1"
PROJECTION_SCHEMA = "forest-v2.semantic-composite.projection-manifest/1"
SPACE_SCHEMA = "forest-v2.semantic-composite.space/1"
VECTOR_RECEIPT_SCHEMA = "forest-v2.semantic-composite.vector-receipt/1"
COMPOSITE_VECTOR_SCHEMA = "forest-v2.semantic-composite.vector/1"
COMPOSITE_RECEIPT_SCHEMA = "forest-v2.semantic-composite.receipt/1"

CLASSIFICATION = "EXPERIMENT"
ACTIVE_GATE = 0
AUTOMATIC_PROMOTIONS = 0
AUTHORITY = "caller_supplied_unverified"
PURPOSE = "retrieval_proposal_only"
ROLES = ("path", "symbol", "content", "neighbor")
TOWERS = ("query", "document")
EGRESS_CLASSIFICATIONS = ("local_only", "trusted_only", "untrusted_allowed")

COMPOSITION = "weighted_direct_sum"
SCORE_OPERATOR = "block_diagonal_dot"
BLOCK_NORMALIZATION = (
    "verify_l2_then_float64_renormalize_each_block_no_global_renormalization"
)
ROUTING = "all_blocks_for_every_nonempty_input"

MAX_ENCODERS = 8
MAX_COMPONENT_DIMENSION = 8_192
MAX_TOTAL_DIMENSION = 16_384
MAX_TEXT_FIELD_LENGTH = 4_096
UNIT_NORM_TOLERANCE = 1e-6
EMPTY_SHA256 = "sha256:" + hashlib.sha256(b"").hexdigest()
PACKET_SPEC_DIGEST = (
    "sha256:7338880c92ed1cd4e389baef55ae33f648882b83166212d37df3d43835013b46"
)

_SHA256 = "sha256:"
class SemanticContractError(ContractError):
    """A semantic-composite contract is malformed or self-inconsistent."""


def _strict_json_loads(raw: bytes | str) -> object:
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise SemanticContractError("serialized contract is not UTF-8") from exc
    elif type(raw) is str:
        text = raw
    else:
        raise SemanticContractError("serialized contract must be bytes or str")

    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise SemanticContractError(f"duplicate JSON key: {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise SemanticContractError(f"non-finite JSON number is forbidden: {value}")

    try:
        return json.loads(
            text,
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
    except SemanticContractError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise SemanticContractError(f"invalid serialized contract: {exc}") from exc


def _object_with_keys(
    value: object, expected: frozenset[str], *, label: str
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SemanticContractError(f"{label} must be an object")
    if any(type(key) is not str for key in value):
        raise SemanticContractError(f"{label} keys must be strings")
    actual = frozenset(value.keys())
    unknown = actual - expected
    missing = expected - actual
    if unknown:
        raise SemanticContractError(f"{label} has unknown keys: {sorted(unknown)!r}")
    if missing:
        raise SemanticContractError(f"{label} is missing keys: {sorted(missing)!r}")
    return value


def _text(value: object, *, label: str, allow_empty: bool = False) -> str:
    if type(value) is not str:
        raise SemanticContractError(f"{label} must be a string")
    if value.strip() != value or (not allow_empty and not value):
        raise SemanticContractError(f"{label} must be non-empty and whitespace-trimmed")
    if len(value) > MAX_TEXT_FIELD_LENGTH:
        raise SemanticContractError(f"{label} exceeds the contract length cap")
    if "\x00" in value or any(ord(character) < 32 for character in value):
        raise SemanticContractError(f"{label} contains a forbidden control character")
    try:
        value.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise SemanticContractError(f"{label} contains an invalid Unicode surrogate") from exc
    return value


def _exact_int(
    value: object,
    *,
    label: str,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or type(value) is not int:
        raise SemanticContractError(f"{label} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        suffix = f" and at most {maximum}" if maximum is not None else ""
        raise SemanticContractError(f"{label} must be at least {minimum}{suffix}")
    return value


def _positive_float(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SemanticContractError(f"{label} must be a real number")
    result = float(value)
    if not math.isfinite(result) or not 0.0 < result <= 1.0:
        raise SemanticContractError(f"{label} must be finite and in (0, 1]")
    return result


def _sha256(value: object, *, label: str) -> str:
    if (
        type(value) is not str
        or len(value) != len(_SHA256) + 64
        or not value.startswith(_SHA256)
        or any(character not in "0123456789abcdef" for character in value[len(_SHA256) :])
    ):
        raise SemanticContractError(f"{label} must be a lowercase sha256 digest")
    return value


def _content_id(value: object, *, label: str, prefix: str) -> str:
    if (
        type(value) is not str
        or len(value) != len(prefix) + 64
        or not value.startswith(prefix)
        or any(character not in "0123456789abcdef" for character in value[len(prefix) :])
    ):
        raise SemanticContractError(f"{label} must be a {prefix!r} content ID")
    return value


def _vector(value: object, *, label: str) -> tuple[float, ...]:
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
    if len(result) > MAX_TOTAL_DIMENSION:
        raise SemanticContractError(f"{label} exceeds the dimension cap")
    return tuple(result)


def text_digest(text: str) -> str:
    """Digest exact UTF-8 model input without retaining the input itself."""

    if type(text) is not str:
        raise SemanticContractError("model input must be text")
    try:
        raw = text.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise SemanticContractError("model input contains an invalid Unicode surrogate") from exc
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def vector_digest(
    values: Sequence[float], *, space_id: str, stage: str
) -> str:
    """Digest numeric values inside their encoder or projection space.

    Identical coordinates from unrelated encoders intentionally get different
    digests.  This closes the otherwise easy vector-substitution ambiguity.
    """

    vector = _vector(values, label="values")
    if stage == "encoder_output":
        checked_space = _content_id(
            space_id, label="space_id", prefix="encoder:"
        )
    elif stage == "projection_output":
        checked_space = _content_id(
            space_id, label="space_id", prefix="projection:"
        )
    else:
        raise SemanticContractError(
            "stage must be 'encoder_output' or 'projection_output'"
        )
    payload = {
        "schema": "forest-v2.semantic-composite.vector-values/1",
        "space_id": checked_space,
        "stage": stage,
        "dimension": len(vector),
        "values": list(vector),
    }
    return "sha256:" + canonical_digest(
        payload, domain="forest-v2.semantic-composite.vector-values/1"
    )


@dataclass(frozen=True)
class EncoderManifest:
    """Immutable query/document encoder identity for one comparable space."""

    provider: str
    model_name: str
    model_revision: str
    source_locator: str
    query_checkpoint_digest: str
    document_checkpoint_digest: str
    tokenizer_name: str
    tokenizer_revision: str
    tokenizer_digest: str
    query_template_digest: str
    document_template_digest: str
    preprocessing_digest: str
    pooling: str
    pooling_config_digest: str
    truncation_strategy: str
    truncation_tokens: int
    add_special_tokens: bool
    output_dimension: int
    output_dtype: str
    output_normalization: str
    shared_space_evidence_digest: str
    adapter_digest: str
    license_spdx: str
    license_evidence_digest: str
    license_evidence_locator: str
    encoder_id: str = ""

    def __post_init__(self) -> None:
        text_fields = (
            "provider",
            "model_name",
            "model_revision",
            "source_locator",
            "tokenizer_name",
            "tokenizer_revision",
            "pooling",
            "output_dtype",
            "license_spdx",
            "license_evidence_locator",
        )
        for field_name in text_fields:
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), label=field_name),
            )
        digest_fields = (
            "query_checkpoint_digest",
            "document_checkpoint_digest",
            "tokenizer_digest",
            "query_template_digest",
            "document_template_digest",
            "preprocessing_digest",
            "pooling_config_digest",
            "shared_space_evidence_digest",
            "adapter_digest",
            "license_evidence_digest",
        )
        for field_name in digest_fields:
            object.__setattr__(
                self,
                field_name,
                _sha256(getattr(self, field_name), label=field_name),
            )
        if self.truncation_strategy not in {"left", "right", "head_tail"}:
            raise SemanticContractError(
                "truncation_strategy must be 'left', 'right', or 'head_tail'"
            )
        if type(self.add_special_tokens) is not bool:
            raise SemanticContractError("add_special_tokens must be a boolean")
        if self.pooling not in {
            "cls_token",
            "mean_attention_masked",
            "last_non_padding_token",
            "eos_token",
            "model_native_declared",
        }:
            raise SemanticContractError("pooling is not a supported explicit strategy")
        if self.output_dtype not in {"float16", "bfloat16", "float32", "float64"}:
            raise SemanticContractError("output_dtype is not a supported explicit dtype")
        object.__setattr__(
            self,
            "truncation_tokens",
            _exact_int(
                self.truncation_tokens,
                label="truncation_tokens",
                minimum=1,
                maximum=10_000_000,
            ),
        )
        object.__setattr__(
            self,
            "output_dimension",
            _exact_int(
                self.output_dimension,
                label="output_dimension",
                minimum=1,
                maximum=MAX_COMPONENT_DIMENSION,
            ),
        )
        if self.output_normalization != "l2":
            raise SemanticContractError("output_normalization must be 'l2'")
        expected = self._computed_id()
        if type(self.encoder_id) is not str:
            raise SemanticContractError("encoder_id must be a string")
        if self.encoder_id and self.encoder_id != expected:
            raise SemanticContractError("encoder_id does not match the manifest payload")
        object.__setattr__(self, "encoder_id", expected)

    def _payload(self) -> dict[str, object]:
        return {
            "schema": ENCODER_SCHEMA,
            "authority": AUTHORITY,
            "purpose": PURPOSE,
            "promotion": "forbidden",
            "provider": self.provider,
            "model_name": self.model_name,
            "model_revision": self.model_revision,
            "source_locator": self.source_locator,
            "query_checkpoint_digest": self.query_checkpoint_digest,
            "document_checkpoint_digest": self.document_checkpoint_digest,
            "tokenizer_name": self.tokenizer_name,
            "tokenizer_revision": self.tokenizer_revision,
            "tokenizer_digest": self.tokenizer_digest,
            "query_template_digest": self.query_template_digest,
            "document_template_digest": self.document_template_digest,
            "preprocessing_digest": self.preprocessing_digest,
            "pooling": self.pooling,
            "pooling_config_digest": self.pooling_config_digest,
            "truncation_strategy": self.truncation_strategy,
            "truncation_tokens": self.truncation_tokens,
            "add_special_tokens": self.add_special_tokens,
            "output_dimension": self.output_dimension,
            "output_dtype": self.output_dtype,
            "output_normalization": self.output_normalization,
            "shared_space_evidence_digest": self.shared_space_evidence_digest,
            "adapter_digest": self.adapter_digest,
            "license_spdx": self.license_spdx,
            "license_evidence_digest": self.license_evidence_digest,
            "license_evidence_locator": self.license_evidence_locator,
        }

    def _computed_id(self) -> str:
        return "encoder:" + canonical_digest(self._payload(), domain=ENCODER_SCHEMA)

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "encoder_id": self.encoder_id}

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> "EncoderManifest":
        keys = frozenset(
            {
                "schema",
                "authority",
                "purpose",
                "promotion",
                "provider",
                "model_name",
                "model_revision",
                "source_locator",
                "query_checkpoint_digest",
                "document_checkpoint_digest",
                "tokenizer_name",
                "tokenizer_revision",
                "tokenizer_digest",
                "query_template_digest",
                "document_template_digest",
                "preprocessing_digest",
                "pooling",
                "pooling_config_digest",
                "truncation_strategy",
                "truncation_tokens",
                "add_special_tokens",
                "output_dimension",
                "output_dtype",
                "output_normalization",
                "shared_space_evidence_digest",
                "adapter_digest",
                "license_spdx",
                "license_evidence_digest",
                "license_evidence_locator",
                "encoder_id",
            }
        )
        data = _object_with_keys(value, keys, label="EncoderManifest")
        if data["schema"] != ENCODER_SCHEMA:
            raise SemanticContractError(
                f"unsupported EncoderManifest schema: {data['schema']!r}"
            )
        if (
            data["authority"] != AUTHORITY
            or data["purpose"] != PURPOSE
            or data["promotion"] != "forbidden"
        ):
            raise SemanticContractError("encoder authority or promotion was relabelled")
        return cls(
            **{
                key: data[key]
                for key in keys
                if key not in {"schema", "authority", "purpose", "promotion"}
            }
        )  # type: ignore[arg-type]

    @classmethod
    def from_bytes(cls, raw: bytes | str) -> "EncoderManifest":
        return cls.from_dict(_strict_json_loads(raw))


@dataclass(frozen=True)
class ProjectionManifest:
    """Identity-only projection contract for packet 002.

    Learned projections intentionally require a new schema and Work Packet;
    representing them under this identity schema is a hard refusal.
    """

    encoder_id: str
    kind: str
    source_dimension: int
    output_dimension: int
    parameter_format: str
    parameter_digest: str
    parameter_bytes: int
    output_normalization: str
    training: None = None
    projection_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "encoder_id",
            _content_id(self.encoder_id, label="encoder_id", prefix="encoder:"),
        )
        if self.kind != "identity":
            raise SemanticContractError(
                "packet 002 permits only identity projections; trained heads need a new schema"
            )
        source_dimension = _exact_int(
            self.source_dimension,
            label="source_dimension",
            minimum=1,
            maximum=MAX_COMPONENT_DIMENSION,
        )
        output_dimension = _exact_int(
            self.output_dimension,
            label="output_dimension",
            minimum=1,
            maximum=MAX_COMPONENT_DIMENSION,
        )
        object.__setattr__(self, "source_dimension", source_dimension)
        object.__setattr__(self, "output_dimension", output_dimension)
        if source_dimension != output_dimension:
            raise SemanticContractError("identity projection dimensions must be equal")
        if self.parameter_format != "none":
            raise SemanticContractError("identity projection parameter_format must be 'none'")
        object.__setattr__(
            self,
            "parameter_digest",
            _sha256(self.parameter_digest, label="parameter_digest"),
        )
        if self.parameter_digest != EMPTY_SHA256:
            raise SemanticContractError("identity projection must bind the empty artifact")
        object.__setattr__(
            self,
            "parameter_bytes",
            _exact_int(self.parameter_bytes, label="parameter_bytes", minimum=0, maximum=0),
        )
        if self.output_normalization != "l2-preserved":
            raise SemanticContractError("identity output_normalization must be 'l2-preserved'")
        if self.training is not None:
            raise SemanticContractError("identity projection training must be null")
        expected = self._computed_id()
        if type(self.projection_id) is not str:
            raise SemanticContractError("projection_id must be a string")
        if self.projection_id and self.projection_id != expected:
            raise SemanticContractError("projection_id does not match the manifest payload")
        object.__setattr__(self, "projection_id", expected)

    @classmethod
    def identity(cls, encoder: EncoderManifest) -> "ProjectionManifest":
        if not isinstance(encoder, EncoderManifest):
            raise SemanticContractError("identity projection requires an EncoderManifest")
        return cls(
            encoder_id=encoder.encoder_id,
            kind="identity",
            source_dimension=encoder.output_dimension,
            output_dimension=encoder.output_dimension,
            parameter_format="none",
            parameter_digest=EMPTY_SHA256,
            parameter_bytes=0,
            output_normalization="l2-preserved",
            training=None,
        )

    def _payload(self) -> dict[str, object]:
        return {
            "schema": PROJECTION_SCHEMA,
            "authority": AUTHORITY,
            "purpose": PURPOSE,
            "promotion": "forbidden",
            "encoder_id": self.encoder_id,
            "kind": self.kind,
            "source_dimension": self.source_dimension,
            "output_dimension": self.output_dimension,
            "parameter_format": self.parameter_format,
            "parameter_digest": self.parameter_digest,
            "parameter_bytes": self.parameter_bytes,
            "output_normalization": self.output_normalization,
            "training": self.training,
        }

    def _computed_id(self) -> str:
        return "projection:" + canonical_digest(self._payload(), domain=PROJECTION_SCHEMA)

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "projection_id": self.projection_id}

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> "ProjectionManifest":
        keys = frozenset(
            {
                "schema",
                "authority",
                "purpose",
                "promotion",
                "encoder_id",
                "kind",
                "source_dimension",
                "output_dimension",
                "parameter_format",
                "parameter_digest",
                "parameter_bytes",
                "output_normalization",
                "training",
                "projection_id",
            }
        )
        data = _object_with_keys(value, keys, label="ProjectionManifest")
        if data["schema"] != PROJECTION_SCHEMA:
            raise SemanticContractError(
                f"unsupported ProjectionManifest schema: {data['schema']!r}"
            )
        if (
            data["authority"] != AUTHORITY
            or data["purpose"] != PURPOSE
            or data["promotion"] != "forbidden"
        ):
            raise SemanticContractError("projection authority or promotion was relabelled")
        return cls(
            **{
                key: data[key]
                for key in keys
                if key not in {"schema", "authority", "purpose", "promotion"}
            }
        )  # type: ignore[arg-type]

    @classmethod
    def from_bytes(cls, raw: bytes | str) -> "ProjectionManifest":
        return cls.from_dict(_strict_json_loads(raw))


@dataclass(frozen=True)
class CompositeBlock:
    encoder: EncoderManifest
    projection: ProjectionManifest
    offset: int
    output_dimension: int
    amplitude_weight: float

    def __post_init__(self) -> None:
        if not isinstance(self.encoder, EncoderManifest):
            raise SemanticContractError("block encoder must be an EncoderManifest")
        if not isinstance(self.projection, ProjectionManifest):
            raise SemanticContractError("block projection must be a ProjectionManifest")
        if self.projection.encoder_id != self.encoder.encoder_id:
            raise SemanticContractError("block projection belongs to a different encoder")
        if self.projection.source_dimension != self.encoder.output_dimension:
            raise SemanticContractError("block projection source dimension mismatches encoder")
        offset = _exact_int(
            self.offset, label="offset", minimum=0, maximum=MAX_TOTAL_DIMENSION
        )
        dimension = _exact_int(
            self.output_dimension,
            label="output_dimension",
            minimum=1,
            maximum=MAX_COMPONENT_DIMENSION,
        )
        if dimension != self.projection.output_dimension:
            raise SemanticContractError("block output dimension mismatches projection")
        object.__setattr__(self, "offset", offset)
        object.__setattr__(self, "output_dimension", dimension)
        object.__setattr__(
            self,
            "amplitude_weight",
            _positive_float(self.amplitude_weight, label="amplitude_weight"),
        )

    @property
    def stop(self) -> int:
        return self.offset + self.output_dimension

    def to_dict(self) -> dict[str, object]:
        return {
            "encoder": self.encoder.to_dict(),
            "projection": self.projection.to_dict(),
            "offset": self.offset,
            "output_dimension": self.output_dimension,
            "amplitude_weight": self.amplitude_weight,
        }

    @classmethod
    def from_dict(cls, value: object) -> "CompositeBlock":
        data = _object_with_keys(
            value,
            frozenset(
                {
                    "encoder",
                    "projection",
                    "offset",
                    "output_dimension",
                    "amplitude_weight",
                }
            ),
            label="CompositeBlock",
        )
        return cls(
            encoder=EncoderManifest.from_dict(data["encoder"]),
            projection=ProjectionManifest.from_dict(data["projection"]),
            offset=data["offset"],  # type: ignore[arg-type]
            output_dimension=data["output_dimension"],  # type: ignore[arg-type]
            amplitude_weight=data["amplitude_weight"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class CompositeSpaceSpec:
    """Ordered, gapless block space with no cross-encoder coordinates."""

    blocks: tuple[CompositeBlock, ...]
    experiment_spec_digest: str
    composition: str = COMPOSITION
    score_operator: str = SCORE_OPERATOR
    block_normalization: str = BLOCK_NORMALIZATION
    routing: str = ROUTING
    space_id: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.blocks, (str, bytes)) or not isinstance(self.blocks, Sequence):
            raise SemanticContractError("blocks must be a sequence")
        blocks = tuple(self.blocks)
        if not 1 <= len(blocks) <= MAX_ENCODERS:
            raise SemanticContractError(f"blocks must contain between 1 and {MAX_ENCODERS} items")
        if any(not isinstance(block, CompositeBlock) for block in blocks):
            raise SemanticContractError("every block must be a CompositeBlock")
        expected_offset = 0
        encoder_ids: set[str] = set()
        projection_ids: set[str] = set()
        for index, block in enumerate(blocks):
            if block.offset != expected_offset:
                raise SemanticContractError(
                    f"blocks[{index}] starts at {block.offset}; expected gapless offset {expected_offset}"
                )
            expected_offset = block.stop
            if block.encoder.encoder_id in encoder_ids:
                raise SemanticContractError("encoder IDs must be unique across blocks")
            if block.projection.projection_id in projection_ids:
                raise SemanticContractError("projection IDs must be unique across blocks")
            encoder_ids.add(block.encoder.encoder_id)
            projection_ids.add(block.projection.projection_id)
        if expected_offset > MAX_TOTAL_DIMENSION:
            raise SemanticContractError("composite space exceeds the total dimension cap")
        object.__setattr__(
            self,
            "experiment_spec_digest",
            _sha256(self.experiment_spec_digest, label="experiment_spec_digest"),
        )
        if self.experiment_spec_digest != PACKET_SPEC_DIGEST:
            raise SemanticContractError(
                "experiment_spec_digest is not the frozen Packet 002 protocol"
            )
        if self.composition != COMPOSITION:
            raise SemanticContractError(f"composition must be {COMPOSITION!r}")
        if self.score_operator != SCORE_OPERATOR:
            raise SemanticContractError(f"score_operator must be {SCORE_OPERATOR!r}")
        if self.block_normalization != BLOCK_NORMALIZATION:
            raise SemanticContractError(
                f"block_normalization must be {BLOCK_NORMALIZATION!r}"
            )
        if self.routing != ROUTING:
            raise SemanticContractError(f"routing must be {ROUTING!r}")
        object.__setattr__(self, "blocks", blocks)
        expected = self._computed_id()
        if type(self.space_id) is not str:
            raise SemanticContractError("space_id must be a string")
        if self.space_id and self.space_id != expected:
            raise SemanticContractError("space_id does not match the space payload")
        object.__setattr__(self, "space_id", expected)

    @property
    def total_dimension(self) -> int:
        return self.blocks[-1].stop

    @property
    def amplitude_norm_squared(self) -> float:
        result = sum(block.amplitude_weight**2 for block in self.blocks)
        if not math.isfinite(result) or result <= 0.0:
            raise SemanticContractError("block weights have an invalid squared norm")
        return result

    @classmethod
    def from_encoders(
        cls,
        encoders: Sequence[EncoderManifest],
        *,
        experiment_spec_digest: str,
        amplitude_weights: Sequence[float] | None = None,
    ) -> "CompositeSpaceSpec":
        if isinstance(encoders, (str, bytes)) or not isinstance(encoders, Sequence):
            raise SemanticContractError("encoders must be a sequence")
        encoder_tuple = tuple(encoders)
        if amplitude_weights is None:
            weight_tuple = tuple(1.0 for _ in encoder_tuple)
        else:
            if isinstance(amplitude_weights, (str, bytes)) or not isinstance(
                amplitude_weights, Sequence
            ):
                raise SemanticContractError("amplitude_weights must be a sequence")
            weight_tuple = tuple(amplitude_weights)
        if len(weight_tuple) != len(encoder_tuple):
            raise SemanticContractError("one amplitude weight is required per encoder")
        blocks: list[CompositeBlock] = []
        offset = 0
        for encoder, weight in zip(encoder_tuple, weight_tuple):
            if not isinstance(encoder, EncoderManifest):
                raise SemanticContractError("every encoder must be an EncoderManifest")
            projection = ProjectionManifest.identity(encoder)
            blocks.append(
                CompositeBlock(
                    encoder=encoder,
                    projection=projection,
                    offset=offset,
                    output_dimension=projection.output_dimension,
                    amplitude_weight=weight,
                )
            )
            offset += projection.output_dimension
        return cls(tuple(blocks), experiment_spec_digest=experiment_spec_digest)

    def _payload(self) -> dict[str, object]:
        return {
            "schema": SPACE_SCHEMA,
            "classification": CLASSIFICATION,
            "active_gate": ACTIVE_GATE,
            "automatic_promotions": AUTOMATIC_PROMOTIONS,
            "authority": AUTHORITY,
            "purpose": PURPOSE,
            "experiment_spec_digest": self.experiment_spec_digest,
            "composition": self.composition,
            "score_operator": self.score_operator,
            "cross_space_terms": "forbidden",
            "composite_normalization": "none",
            "block_normalization": self.block_normalization,
            "routing": self.routing,
            "total_dimension": self.total_dimension,
            "blocks": [block.to_dict() for block in self.blocks],
        }

    def _computed_id(self) -> str:
        return "semantic-space:" + canonical_digest(self._payload(), domain=SPACE_SCHEMA)

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "space_id": self.space_id}

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> "CompositeSpaceSpec":
        data = _object_with_keys(
            value,
            frozenset(
                {
                    "schema",
                    "classification",
                    "active_gate",
                    "automatic_promotions",
                    "authority",
                    "purpose",
                    "experiment_spec_digest",
                    "composition",
                    "score_operator",
                    "cross_space_terms",
                    "composite_normalization",
                    "block_normalization",
                    "routing",
                    "total_dimension",
                    "blocks",
                    "space_id",
                }
            ),
            label="CompositeSpaceSpec",
        )
        if data["schema"] != SPACE_SCHEMA:
            raise SemanticContractError(
                f"unsupported CompositeSpaceSpec schema: {data['schema']!r}"
            )
        if data["classification"] != CLASSIFICATION:
            raise SemanticContractError("classification is not EXPERIMENT")
        if _exact_int(data["active_gate"], label="active_gate") != ACTIVE_GATE:
            raise SemanticContractError("active_gate is not the frozen Gate 0")
        if _exact_int(
            data["automatic_promotions"], label="automatic_promotions"
        ) != 0:
            raise SemanticContractError("automatic_promotions must be exactly zero")
        if data["authority"] != AUTHORITY or data["purpose"] != PURPOSE:
            raise SemanticContractError("space authority or purpose was relabelled")
        if data["cross_space_terms"] != "forbidden":
            raise SemanticContractError("cross_space_terms must be forbidden")
        if data["composite_normalization"] != "none":
            raise SemanticContractError("global composite normalization is forbidden")
        raw_blocks = data["blocks"]
        if not isinstance(raw_blocks, list):
            raise SemanticContractError("serialized blocks must be a JSON array")
        result = cls(
            blocks=tuple(CompositeBlock.from_dict(block) for block in raw_blocks),
            experiment_spec_digest=data["experiment_spec_digest"],  # type: ignore[arg-type]
            composition=data["composition"],  # type: ignore[arg-type]
            score_operator=data["score_operator"],  # type: ignore[arg-type]
            block_normalization=data["block_normalization"],  # type: ignore[arg-type]
            routing=data["routing"],  # type: ignore[arg-type]
            space_id=data["space_id"],  # type: ignore[arg-type]
        )
        serialized_dimension = _exact_int(
            data["total_dimension"],
            label="total_dimension",
            minimum=1,
            maximum=MAX_TOTAL_DIMENSION,
        )
        if serialized_dimension != result.total_dimension:
            raise SemanticContractError("total_dimension does not match the block layout")
        return result

    @classmethod
    def from_bytes(cls, raw: bytes | str) -> "CompositeSpaceSpec":
        return cls.from_dict(_strict_json_loads(raw))


@dataclass(frozen=True)
class VectorReceipt:
    """Redacted receipt for one externally generated block vector."""

    source_id: str
    revision: str
    input_digest: str
    input_bytes: int
    role: str
    tower: str
    encoder_id: str
    projection_id: str
    source_dimension: int
    output_dimension: int
    source_vector_digest: str
    output_vector_digest: str
    input_tokens: int
    producer_receipt_digest: str
    execution_receipt_digest: str
    cost_receipt_digest: str
    egress_classification: str
    egress_policy_receipt_digest: str
    authority: str = AUTHORITY
    purpose: str = PURPOSE
    receipt_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _text(self.source_id, label="source_id"))
        object.__setattr__(self, "revision", _text(self.revision, label="revision"))
        object.__setattr__(
            self, "input_digest", _sha256(self.input_digest, label="input_digest")
        )
        object.__setattr__(
            self,
            "input_bytes",
            _exact_int(self.input_bytes, label="input_bytes", minimum=1),
        )
        if self.role not in ROLES:
            raise SemanticContractError(f"role must be one of {ROLES!r}")
        if self.tower not in TOWERS:
            raise SemanticContractError(f"tower must be one of {TOWERS!r}")
        object.__setattr__(
            self,
            "encoder_id",
            _content_id(self.encoder_id, label="encoder_id", prefix="encoder:"),
        )
        object.__setattr__(
            self,
            "projection_id",
            _content_id(
                self.projection_id, label="projection_id", prefix="projection:"
            ),
        )
        source_dimension = _exact_int(
            self.source_dimension,
            label="source_dimension",
            minimum=1,
            maximum=MAX_COMPONENT_DIMENSION,
        )
        output_dimension = _exact_int(
            self.output_dimension,
            label="output_dimension",
            minimum=1,
            maximum=MAX_COMPONENT_DIMENSION,
        )
        object.__setattr__(self, "source_dimension", source_dimension)
        object.__setattr__(self, "output_dimension", output_dimension)
        object.__setattr__(
            self,
            "source_vector_digest",
            _sha256(self.source_vector_digest, label="source_vector_digest"),
        )
        object.__setattr__(
            self,
            "output_vector_digest",
            _sha256(self.output_vector_digest, label="output_vector_digest"),
        )
        object.__setattr__(
            self,
            "input_tokens",
            _exact_int(self.input_tokens, label="input_tokens", minimum=1),
        )
        for field_name in (
            "producer_receipt_digest",
            "execution_receipt_digest",
            "cost_receipt_digest",
            "egress_policy_receipt_digest",
        ):
            object.__setattr__(
                self,
                field_name,
                _sha256(getattr(self, field_name), label=field_name),
            )
        if self.egress_classification not in EGRESS_CLASSIFICATIONS:
            raise SemanticContractError(
                f"egress_classification must be one of {EGRESS_CLASSIFICATIONS!r}"
            )
        if self.authority != AUTHORITY:
            raise SemanticContractError(f"authority must be {AUTHORITY!r}")
        if self.purpose != PURPOSE:
            raise SemanticContractError(f"purpose must be {PURPOSE!r}")
        expected = self._computed_id()
        if type(self.receipt_id) is not str:
            raise SemanticContractError("receipt_id must be a string")
        if self.receipt_id and self.receipt_id != expected:
            raise SemanticContractError("receipt_id does not match the receipt payload")
        object.__setattr__(self, "receipt_id", expected)

    def _payload(self) -> dict[str, object]:
        return {
            "schema": VECTOR_RECEIPT_SCHEMA,
            "source_id": self.source_id,
            "revision": self.revision,
            "input_digest": self.input_digest,
            "input_bytes": self.input_bytes,
            "role": self.role,
            "tower": self.tower,
            "encoder_id": self.encoder_id,
            "projection_id": self.projection_id,
            "source_dimension": self.source_dimension,
            "output_dimension": self.output_dimension,
            "source_vector_digest": self.source_vector_digest,
            "output_vector_digest": self.output_vector_digest,
            "input_tokens": self.input_tokens,
            "encoder_calls": 1,
            "producer_receipt_digest": self.producer_receipt_digest,
            "execution_receipt_digest": self.execution_receipt_digest,
            "cost_receipt_digest": self.cost_receipt_digest,
            "egress_classification": self.egress_classification,
            "egress_policy_receipt_digest": self.egress_policy_receipt_digest,
            "authority": self.authority,
            "purpose": self.purpose,
            "promotion": "forbidden",
        }

    def _computed_id(self) -> str:
        return "semantic-vector-receipt:" + canonical_digest(
            self._payload(), domain=VECTOR_RECEIPT_SCHEMA
        )

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "receipt_id": self.receipt_id}

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> "VectorReceipt":
        keys = frozenset(
            {
                "schema",
                "source_id",
                "revision",
                "input_digest",
                "input_bytes",
                "role",
                "tower",
                "encoder_id",
                "projection_id",
                "source_dimension",
                "output_dimension",
                "source_vector_digest",
                "output_vector_digest",
                "input_tokens",
                "encoder_calls",
                "producer_receipt_digest",
                "execution_receipt_digest",
                "cost_receipt_digest",
                "egress_classification",
                "egress_policy_receipt_digest",
                "authority",
                "purpose",
                "promotion",
                "receipt_id",
            }
        )
        data = _object_with_keys(value, keys, label="VectorReceipt")
        if data["schema"] != VECTOR_RECEIPT_SCHEMA:
            raise SemanticContractError(
                f"unsupported VectorReceipt schema: {data['schema']!r}"
            )
        if _exact_int(
            data["encoder_calls"],
            label="encoder_calls",
            minimum=1,
            maximum=1,
        ) != 1:
            raise SemanticContractError("each VectorReceipt must bind exactly one encoder call")
        if data["promotion"] != "forbidden":
            raise SemanticContractError("VectorReceipt promotion must be forbidden")
        return cls(
            **{
                key: data[key]
                for key in keys
                if key not in {"schema", "encoder_calls", "promotion"}
            }
        )  # type: ignore[arg-type]

    @classmethod
    def from_bytes(cls, raw: bytes | str) -> "VectorReceipt":
        return cls.from_dict(_strict_json_loads(raw))


@dataclass(frozen=True)
class CompositeVector:
    """One composite vector bound to an exact semantic block space."""

    space_id: str
    values: tuple[float, ...]
    egress_classification: str
    egress_policy_receipt_digest: str
    vector_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "space_id",
            _content_id(self.space_id, label="space_id", prefix="semantic-space:"),
        )
        object.__setattr__(self, "values", _vector(self.values, label="values"))
        if self.egress_classification not in EGRESS_CLASSIFICATIONS:
            raise SemanticContractError(
                f"egress_classification must be one of {EGRESS_CLASSIFICATIONS!r}"
            )
        object.__setattr__(
            self,
            "egress_policy_receipt_digest",
            _sha256(
                self.egress_policy_receipt_digest,
                label="egress_policy_receipt_digest",
            ),
        )
        expected = self._computed_id()
        if type(self.vector_id) is not str:
            raise SemanticContractError("vector_id must be a string")
        if self.vector_id and self.vector_id != expected:
            raise SemanticContractError("vector_id does not match the vector payload")
        object.__setattr__(self, "vector_id", expected)

    def _payload(self) -> dict[str, object]:
        return {
            "schema": COMPOSITE_VECTOR_SCHEMA,
            "authority": AUTHORITY,
            "purpose": PURPOSE,
            "promotion": "forbidden",
            "space_id": self.space_id,
            "values": list(self.values),
            "egress_classification": self.egress_classification,
            "egress_policy_receipt_digest": self.egress_policy_receipt_digest,
        }

    def _computed_id(self) -> str:
        return "semantic-vector:" + canonical_digest(
            self._payload(), domain=COMPOSITE_VECTOR_SCHEMA
        )

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "vector_id": self.vector_id}

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> "CompositeVector":
        data = _object_with_keys(
            value,
            frozenset(
                {
                    "schema",
                    "authority",
                    "purpose",
                    "promotion",
                    "space_id",
                    "values",
                    "egress_classification",
                    "egress_policy_receipt_digest",
                    "vector_id",
                }
            ),
            label="CompositeVector",
        )
        if data["schema"] != COMPOSITE_VECTOR_SCHEMA:
            raise SemanticContractError(
                f"unsupported CompositeVector schema: {data['schema']!r}"
            )
        if (
            data["authority"] != AUTHORITY
            or data["purpose"] != PURPOSE
            or data["promotion"] != "forbidden"
        ):
            raise SemanticContractError("composite vector authority was relabelled")
        values = data["values"]
        if not isinstance(values, list):
            raise SemanticContractError("serialized values must be a JSON array")
        return cls(
            space_id=data["space_id"],  # type: ignore[arg-type]
            values=tuple(values),  # type: ignore[arg-type]
            egress_classification=data["egress_classification"],  # type: ignore[arg-type]
            egress_policy_receipt_digest=data["egress_policy_receipt_digest"],  # type: ignore[arg-type]
            vector_id=data["vector_id"],  # type: ignore[arg-type]
        )

    @classmethod
    def from_bytes(cls, raw: bytes | str) -> "CompositeVector":
        return cls.from_dict(_strict_json_loads(raw))


@dataclass(frozen=True)
class CompositeReceipt:
    """Aggregate, redacted cost/provenance receipt for one composition."""

    space_id: str
    source_id: str
    revision: str
    input_digest: str
    input_bytes: int
    role: str
    tower: str
    vector_id: str
    block_receipts: tuple[VectorReceipt, ...]
    egress_classification: str
    egress_policy_receipt_digest: str
    kind: str = "encoded"
    authority: str = AUTHORITY
    purpose: str = PURPOSE
    receipt_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "space_id",
            _content_id(self.space_id, label="space_id", prefix="semantic-space:"),
        )
        object.__setattr__(self, "source_id", _text(self.source_id, label="source_id"))
        object.__setattr__(self, "revision", _text(self.revision, label="revision"))
        object.__setattr__(
            self, "input_digest", _sha256(self.input_digest, label="input_digest")
        )
        object.__setattr__(
            self,
            "input_bytes",
            _exact_int(self.input_bytes, label="input_bytes", minimum=0),
        )
        if self.role not in ROLES:
            raise SemanticContractError(f"role must be one of {ROLES!r}")
        if self.tower not in TOWERS:
            raise SemanticContractError(f"tower must be one of {TOWERS!r}")
        object.__setattr__(
            self,
            "vector_id",
            _content_id(self.vector_id, label="vector_id", prefix="semantic-vector:"),
        )
        if self.egress_classification not in EGRESS_CLASSIFICATIONS:
            raise SemanticContractError(
                f"egress_classification must be one of {EGRESS_CLASSIFICATIONS!r}"
            )
        object.__setattr__(
            self,
            "egress_policy_receipt_digest",
            _sha256(
                self.egress_policy_receipt_digest,
                label="egress_policy_receipt_digest",
            ),
        )
        if isinstance(self.block_receipts, (str, bytes)) or not isinstance(
            self.block_receipts, Sequence
        ):
            raise SemanticContractError("block_receipts must be a sequence")
        receipts = tuple(self.block_receipts)
        if any(not isinstance(receipt, VectorReceipt) for receipt in receipts):
            raise SemanticContractError("every block receipt must be a VectorReceipt")
        object.__setattr__(self, "block_receipts", receipts)
        if self.kind not in {"encoded", "canonical_null"}:
            raise SemanticContractError("kind must be 'encoded' or 'canonical_null'")
        if self.kind == "encoded" and not receipts:
            raise SemanticContractError("encoded receipt must contain block receipts")
        if self.kind == "canonical_null" and receipts:
            raise SemanticContractError("canonical_null must not contain encoder receipts")
        if self.kind == "encoded" and self.input_bytes == 0:
            raise SemanticContractError("encoded receipt must bind non-empty input bytes")
        if self.kind == "canonical_null" and (
            self.input_bytes != 0 or self.input_digest != text_digest("")
        ):
            raise SemanticContractError(
                "canonical_null must bind the exact empty input"
            )
        if len({receipt.receipt_id for receipt in receipts}) != len(receipts):
            raise SemanticContractError("block receipt IDs must be unique")
        if len({receipt.encoder_id for receipt in receipts}) != len(receipts):
            raise SemanticContractError("block receipt encoder IDs must be unique")
        if len({receipt.projection_id for receipt in receipts}) != len(receipts):
            raise SemanticContractError("block receipt projection IDs must be unique")
        for receipt in receipts:
            if (
                receipt.source_id != self.source_id
                or receipt.revision != self.revision
                or receipt.input_digest != self.input_digest
                or receipt.input_bytes != self.input_bytes
                or receipt.role != self.role
                or receipt.tower != self.tower
                or receipt.egress_classification != self.egress_classification
                or receipt.egress_policy_receipt_digest
                != self.egress_policy_receipt_digest
            ):
                raise SemanticContractError("block receipt source binding mismatches aggregate")
        if self.authority != AUTHORITY or self.purpose != PURPOSE:
            raise SemanticContractError("aggregate authority or purpose was relabelled")
        expected = self._computed_id()
        if type(self.receipt_id) is not str:
            raise SemanticContractError("receipt_id must be a string")
        if self.receipt_id and self.receipt_id != expected:
            raise SemanticContractError("receipt_id does not match the aggregate payload")
        object.__setattr__(self, "receipt_id", expected)

    @property
    def encoder_calls(self) -> int:
        return len(self.block_receipts)

    @property
    def encoder_input_tokens(self) -> int:
        return sum(receipt.input_tokens for receipt in self.block_receipts)

    @property
    def encoder_input_bytes(self) -> int:
        return sum(receipt.input_bytes for receipt in self.block_receipts)

    def _payload(self) -> dict[str, object]:
        return {
            "schema": COMPOSITE_RECEIPT_SCHEMA,
            "space_id": self.space_id,
            "source_id": self.source_id,
            "revision": self.revision,
            "input_digest": self.input_digest,
            "input_bytes": self.input_bytes,
            "role": self.role,
            "tower": self.tower,
            "vector_id": self.vector_id,
            "kind": self.kind,
            "block_receipts": [receipt.to_dict() for receipt in self.block_receipts],
            "egress_classification": self.egress_classification,
            "egress_policy_receipt_digest": self.egress_policy_receipt_digest,
            "encoder_calls": self.encoder_calls,
            "encoder_input_tokens": self.encoder_input_tokens,
            "encoder_input_bytes": self.encoder_input_bytes,
            "authority": self.authority,
            "purpose": self.purpose,
            "promotion": "forbidden",
        }

    def _computed_id(self) -> str:
        return "semantic-composite-receipt:" + canonical_digest(
            self._payload(), domain=COMPOSITE_RECEIPT_SCHEMA
        )

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "receipt_id": self.receipt_id}

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> "CompositeReceipt":
        data = _object_with_keys(
            value,
            frozenset(
                {
                    "schema",
                    "space_id",
                    "source_id",
                    "revision",
                    "input_digest",
                    "input_bytes",
                    "role",
                    "tower",
                    "vector_id",
                    "kind",
                    "block_receipts",
                    "egress_classification",
                    "egress_policy_receipt_digest",
                    "encoder_calls",
                    "encoder_input_tokens",
                    "encoder_input_bytes",
                    "authority",
                    "purpose",
                    "promotion",
                    "receipt_id",
                }
            ),
            label="CompositeReceipt",
        )
        if data["schema"] != COMPOSITE_RECEIPT_SCHEMA:
            raise SemanticContractError(
                f"unsupported CompositeReceipt schema: {data['schema']!r}"
            )
        if data["promotion"] != "forbidden":
            raise SemanticContractError("CompositeReceipt promotion must be forbidden")
        raw_receipts = data["block_receipts"]
        if not isinstance(raw_receipts, list):
            raise SemanticContractError("serialized block_receipts must be a JSON array")
        result = cls(
            space_id=data["space_id"],  # type: ignore[arg-type]
            source_id=data["source_id"],  # type: ignore[arg-type]
            revision=data["revision"],  # type: ignore[arg-type]
            input_digest=data["input_digest"],  # type: ignore[arg-type]
            input_bytes=data["input_bytes"],  # type: ignore[arg-type]
            role=data["role"],  # type: ignore[arg-type]
            tower=data["tower"],  # type: ignore[arg-type]
            vector_id=data["vector_id"],  # type: ignore[arg-type]
            block_receipts=tuple(VectorReceipt.from_dict(item) for item in raw_receipts),
            egress_classification=data["egress_classification"],  # type: ignore[arg-type]
            egress_policy_receipt_digest=data["egress_policy_receipt_digest"],  # type: ignore[arg-type]
            kind=data["kind"],  # type: ignore[arg-type]
            authority=data["authority"],  # type: ignore[arg-type]
            purpose=data["purpose"],  # type: ignore[arg-type]
            receipt_id=data["receipt_id"],  # type: ignore[arg-type]
        )
        expected_derived = {
            "encoder_calls": result.encoder_calls,
            "encoder_input_tokens": result.encoder_input_tokens,
            "encoder_input_bytes": result.encoder_input_bytes,
        }
        for name, expected in expected_derived.items():
            actual = _exact_int(data[name], label=name, minimum=0)
            if actual != expected:
                raise SemanticContractError(f"{name} does not match block receipts")
        return result

    @classmethod
    def from_bytes(cls, raw: bytes | str) -> "CompositeReceipt":
        return cls.from_dict(_strict_json_loads(raw))


__all__ = [
    "ACTIVE_GATE",
    "AUTHORITY",
    "AUTOMATIC_PROMOTIONS",
    "BLOCK_NORMALIZATION",
    "CLASSIFICATION",
    "COMPOSITE_RECEIPT_SCHEMA",
    "COMPOSITE_VECTOR_SCHEMA",
    "COMPOSITION",
    "EMPTY_SHA256",
    "EGRESS_CLASSIFICATIONS",
    "ENCODER_SCHEMA",
    "MAX_COMPONENT_DIMENSION",
    "MAX_ENCODERS",
    "MAX_TOTAL_DIMENSION",
    "PACKET_SPEC_DIGEST",
    "PROJECTION_SCHEMA",
    "PURPOSE",
    "ROLES",
    "ROUTING",
    "SCORE_OPERATOR",
    "SPACE_SCHEMA",
    "TOWERS",
    "UNIT_NORM_TOLERANCE",
    "VECTOR_RECEIPT_SCHEMA",
    "CompositeBlock",
    "CompositeReceipt",
    "CompositeSpaceSpec",
    "CompositeVector",
    "EncoderManifest",
    "ProjectionManifest",
    "SemanticContractError",
    "VectorReceipt",
    "text_digest",
    "vector_digest",
]
