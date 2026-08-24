"""Tamper-evident, caller-owned persistence and proposal-only search index.

``TensorIndex.canonical_bytes()`` is the complete persistence format.  This
module intentionally has no save/open/write helper: an authorized caller may
store those bytes, while the experiment itself remains stdout/read-only.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .algebra import (
    explain_contraction,
    fiber_maxsim,
    flattened_cosine,
    identity_contraction,
    normalized_structured_score,
)
from .contracts import (
    NORMALIZATION,
    PLANES,
    ROLES,
    CPTensor,
    DenseTensor,
    SeparableKernel,
    TensorLike,
    TensorSpec,
    TensorTrain,
    canonical_digest,
    canonical_json_bytes,
)
from .encoding import (
    EncodedArtifact,
    HASH_BACKEND_ID,
    HashingFillerBackend,
    RoleFields,
    SOURCE_BINDINGS,
    TensorProductEncoder,
    canonical_source_digest,
    validate_source_binding_evidence,
)
from .retrievers import frozen_kernel
from .stats import FROZEN_SEEDS, SPEC_DIGEST


INDEX_SCHEMA = "forest-v2.tensor-index/2"
INDEX_DOCUMENT_SCHEMA = "forest-v2.tensor-index-document/1"
PROPOSAL_SCHEMA = "forest-v2.tensor-retrieval-proposal/2"
AUTHORITY = "unverified-retrieval-proposal"
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_CONTENT_ID = re.compile(r"^(?:index|tspec|kernel|cp|dense|tt):[0-9a-f]{64}$")
_TENSOR_PREFIXES = {"cp": "cp:", "dense": "dense:", "tt": "tt:"}
MAX_INDEX_DOCUMENTS = 65_536


class IndexContractError(ValueError):
    pass


def _exact_mapping(value: object, keys: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise IndexContractError(f"{label} must be an object")
    actual = set(value)
    if actual != keys:
        unknown = sorted(actual - keys)
        missing = sorted(keys - actual)
        raise IndexContractError(
            f"{label} key mismatch; unknown={unknown!r}, missing={missing!r}"
        )
    if any(type(key) is not str for key in value):
        raise IndexContractError(f"{label} keys must be strings")
    return value


def _strict_loads(raw: bytes | str) -> object:
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise IndexContractError("index bytes are not UTF-8") from exc
    elif type(raw) is str:
        text = raw
    else:
        raise IndexContractError("index input must be bytes or str")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        out: dict[str, object] = {}
        for key, value in items:
            if key in out:
                raise IndexContractError(f"duplicate JSON key {key!r}")
            out[key] = value
        return out

    def reject(value: str) -> object:
        raise IndexContractError(f"non-finite JSON number {value} is forbidden")

    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=reject)
    except IndexContractError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise IndexContractError(f"invalid index JSON: {exc}") from exc


def _tensor_kind(tensor: TensorLike) -> str:
    if isinstance(tensor, CPTensor):
        return "cp"
    if isinstance(tensor, DenseTensor):
        return "dense"
    if isinstance(tensor, TensorTrain):
        return "tt"
    raise IndexContractError("document tensor has an unsupported representation")


def _convert_tensor(tensor: CPTensor, representation: str) -> TensorLike:
    if representation == "cp":
        return tensor
    if representation == "dense":
        return tensor.to_dense()
    if representation == "tt":
        return tensor.to_tensor_train()
    raise IndexContractError("representation must be 'cp', 'dense', or 'tt'")


@dataclass(frozen=True)
class IndexDocument:
    source_id: str
    source_digest: str
    source_binding: str
    source_evidence: str
    revision: str
    plane: str | None
    backend_id: str
    tensor: TensorLike
    fields: RoleFields

    def __post_init__(self) -> None:
        if type(self.source_id) is not str or not self.source_id:
            raise IndexContractError("document source_id must not be empty")
        if type(self.source_digest) is not str or not _SHA256.fullmatch(self.source_digest):
            raise IndexContractError("document source_digest must be sha256:<hex>")
        if self.source_binding not in SOURCE_BINDINGS:
            raise IndexContractError("document source_binding is unknown")
        if type(self.source_evidence) is not str:
            raise IndexContractError("document source_evidence must be text")
        if type(self.revision) is not str or not self.revision:
            raise IndexContractError("document revision must not be empty")
        if type(self.backend_id) is not str or not self.backend_id:
            raise IndexContractError("document backend_id must not be empty")
        if self.backend_id != HASH_BACKEND_ID:
            raise IndexContractError("persisted index requires the frozen hashing backend")
        if not isinstance(self.tensor, (CPTensor, DenseTensor, TensorTrain)):
            raise IndexContractError("document tensor has an unsupported type")
        if not isinstance(self.fields, RoleFields):
            raise IndexContractError("document fields must be RoleFields")
        if self.plane is None:
            raise IndexContractError("index documents require a one-hot plane")
        if self.plane not in self.tensor.spec.planes:
            raise IndexContractError(f"unknown document plane {self.plane!r}")
        if self.source_binding == "query_content_sha256_verified":
            raise IndexContractError("query-bound artifacts cannot be index documents")
        try:
            validate_source_binding_evidence(
                source_id=self.source_id,
                source_digest=self.source_digest,
                source_binding=self.source_binding,
                source_evidence=self.source_evidence,
                revision=self.revision,
                plane=self.plane,
                fields=self.fields,
            )
        except (TypeError, ValueError) as exc:
            raise IndexContractError(f"document source binding is invalid: {exc}") from exc
        try:
            expected_cp = TensorProductEncoder(
                self.tensor.spec, HashingFillerBackend(self.tensor.spec.seed)
            ).encode(
                self.fields,
                source_id=self.source_id,
                source_digest=self.source_digest,
                revision=self.revision,
                plane=self.plane,
            ).tensor
            expected_tensor = _convert_tensor(expected_cp, _tensor_kind(self.tensor))
        except (TypeError, ValueError) as exc:
            raise IndexContractError(f"document projection cannot be replayed: {exc}") from exc
        if expected_tensor != self.tensor:
            raise IndexContractError("document tensor does not match its replayed role fields")

    @classmethod
    def from_encoded(
        cls, artifact: EncodedArtifact, *, representation: str = "cp"
    ) -> "IndexDocument":
        if not isinstance(artifact, EncodedArtifact):
            raise IndexContractError("artifact must be EncodedArtifact")
        return cls(
            source_id=artifact.source_id,
            source_digest=artifact.source_digest,
            source_binding=artifact.source_binding,
            source_evidence=artifact.source_evidence,
            revision=artifact.revision,
            plane=artifact.plane,
            backend_id=artifact.backend_id,
            tensor=_convert_tensor(artifact.tensor, representation),
            fields=artifact.fields,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": INDEX_DOCUMENT_SCHEMA,
            "source_id": self.source_id,
            "source_digest": self.source_digest,
            "source_binding": self.source_binding,
            "source_evidence": self.source_evidence,
            "revision": self.revision,
            "plane": self.plane,
            "backend_id": self.backend_id,
            "tensor_kind": _tensor_kind(self.tensor),
            "tensor": self.tensor.to_dict(),
            "fields": self.fields.as_mapping(),
        }

    @classmethod
    def from_dict(cls, value: object, spec: TensorSpec) -> "IndexDocument":
        data = _exact_mapping(
            value,
            {
                "schema",
                "source_id",
                "source_digest",
                "source_binding",
                "source_evidence",
                "revision",
                "plane",
                "backend_id",
                "tensor_kind",
                "tensor",
                "fields",
            },
            "IndexDocument",
        )
        if data["schema"] != INDEX_DOCUMENT_SCHEMA:
            raise IndexContractError("unsupported index-document schema")
        kind = data["tensor_kind"]
        if kind == "cp":
            tensor = CPTensor.from_dict(data["tensor"], spec)
        elif kind == "dense":
            tensor = DenseTensor.from_dict(data["tensor"], spec)
        elif kind == "tt":
            tensor = TensorTrain.from_dict(data["tensor"], spec)
        else:
            raise IndexContractError(f"unsupported tensor_kind {kind!r}")
        if not str(tensor.tensor_id).startswith(_TENSOR_PREFIXES[str(kind)]):
            raise IndexContractError("tensor id prefix disagrees with tensor_kind")
        fields_data = _exact_mapping(
            data["fields"], {"path", "symbol", "content", "neighbor"}, "role fields"
        )
        if any(type(fields_data[name]) is not str for name in fields_data):
            raise IndexContractError("role fields must contain strings")
        return cls(
            source_id=data["source_id"],
            source_digest=data["source_digest"],
            source_binding=data["source_binding"],
            source_evidence=data["source_evidence"],
            revision=data["revision"],
            plane=data["plane"],
            backend_id=data["backend_id"],
            tensor=tensor,
            fields=RoleFields(
                path=fields_data["path"],
                symbol=fields_data["symbol"],
                content=fields_data["content"],
                neighbor=fields_data["neighbor"],
            ),
        )


@dataclass(frozen=True)
class SearchHit:
    rank: int
    source_id: str
    source_digest: str
    source_binding: str
    revision: str
    tensor_id: str
    score: float
    mode: str
    index_id: str
    experiment_spec_digest: str
    corpus_digest: str
    spec_id: str
    backend_id: str
    kernel_id: str | None
    query_source_id: str
    query_source_digest: str
    query_source_binding: str
    query_tensor_id: str
    explanation: tuple[dict[str, object], ...] = ()
    explanation_total_terms: int = 0
    explanation_numerator: float | None = None
    explanation_normalization_bound: float | None = None

    def __post_init__(self) -> None:
        if isinstance(self.rank, bool) or type(self.rank) is not int or self.rank < 1:
            raise IndexContractError("search-hit rank must be positive")
        for label, value in (
            ("source_id", self.source_id),
            ("revision", self.revision),
        ):
            if type(value) is not str or not value:
                raise IndexContractError(f"search-hit {label} must not be empty")
        if type(self.source_digest) is not str or not _SHA256.fullmatch(
            self.source_digest
        ):
            raise IndexContractError("search-hit source_digest must be sha256:<hex>")
        if self.source_binding not in SOURCE_BINDINGS or self.source_binding == (
            "query_content_sha256_verified"
        ):
            raise IndexContractError("search-hit document source binding is invalid")
        if self.mode not in {"cosine", "identity", "structured", "maxsim"}:
            raise IndexContractError("search-hit mode is unsupported")
        for label, value in (
            ("index_id", self.index_id),
            ("experiment_spec_digest", self.experiment_spec_digest),
            ("corpus_digest", self.corpus_digest),
            ("spec_id", self.spec_id),
            ("backend_id", self.backend_id),
            ("query_source_id", self.query_source_id),
            ("query_source_digest", self.query_source_digest),
            ("query_tensor_id", self.query_tensor_id),
        ):
            if type(value) is not str or not value:
                raise IndexContractError(f"search-hit {label} must not be empty")
        for label, value in (
            ("index_id", self.index_id),
            ("spec_id", self.spec_id),
            ("tensor_id", self.tensor_id),
            ("query_tensor_id", self.query_tensor_id),
        ):
            if not _CONTENT_ID.fullmatch(value):
                raise IndexContractError(f"search-hit {label} is not content-addressed")
        for label, value in (
            ("experiment_spec_digest", self.experiment_spec_digest),
            ("corpus_digest", self.corpus_digest),
            ("query_source_digest", self.query_source_digest),
        ):
            if not _SHA256.fullmatch(value):
                raise IndexContractError(f"search-hit {label} must be sha256:<hex>")
        if self.query_source_binding != "query_content_sha256_verified":
            raise IndexContractError("search-hit query must use the verified query binding")
        if self.mode in {"structured", "maxsim"}:
            if type(self.kernel_id) is not str or not self.kernel_id:
                raise IndexContractError("structured search hit requires kernel_id")
            if not _CONTENT_ID.fullmatch(self.kernel_id):
                raise IndexContractError("search-hit kernel_id is not content-addressed")
        elif self.kernel_id is not None:
            raise IndexContractError("non-kernel search hit must use null kernel_id")
        if isinstance(self.score, bool) or not isinstance(self.score, (int, float)):
            raise IndexContractError("search-hit score must be a real number")
        if not math.isfinite(self.score):
            raise IndexContractError("search-hit score must be finite")
        if not isinstance(self.explanation, tuple) or any(
            not isinstance(item, Mapping) for item in self.explanation
        ):
            raise IndexContractError("search-hit explanation must be a tuple of objects")
        if (
            isinstance(self.explanation_total_terms, bool)
            or type(self.explanation_total_terms) is not int
            or self.explanation_total_terms < len(self.explanation)
        ):
            raise IndexContractError("explanation total cannot be smaller than shown terms")
        for value in (self.explanation_numerator, self.explanation_normalization_bound):
            if value is not None and not math.isfinite(value):
                raise IndexContractError("explanation summary values must be finite")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": PROPOSAL_SCHEMA,
            "authority": AUTHORITY,
            "rank": self.rank,
            "source_id": self.source_id,
            "source_digest": self.source_digest,
            "source_binding": self.source_binding,
            "revision": self.revision,
            "tensor_id": self.tensor_id,
            "score": self.score,
            "mode": self.mode,
            "index_id": self.index_id,
            "experiment_spec_digest": self.experiment_spec_digest,
            "corpus_digest": self.corpus_digest,
            "spec_id": self.spec_id,
            "backend_id": self.backend_id,
            "kernel_id": self.kernel_id,
            "query_source_id": self.query_source_id,
            "query_source_digest": self.query_source_digest,
            "query_source_binding": self.query_source_binding,
            "query_tensor_id": self.query_tensor_id,
            "explanation": list(self.explanation),
            "explanation_summary": {
                "shown_terms": len(self.explanation),
                "total_terms": self.explanation_total_terms,
                "truncated": self.explanation_total_terms > len(self.explanation),
                "numerator": self.explanation_numerator,
                "normalization_bound": self.explanation_normalization_bound,
            },
        }


@dataclass(frozen=True)
class TensorIndex:
    spec: TensorSpec
    kernel: SeparableKernel
    experiment_spec_digest: str
    backend_id: str
    representation: str
    source_revision: str
    corpus_digest: str
    documents: tuple[IndexDocument, ...]
    index_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.spec, TensorSpec):
            raise IndexContractError("index spec must be TensorSpec")
        if not isinstance(self.kernel, SeparableKernel) or self.kernel.spec != self.spec:
            raise IndexContractError("index kernel must match its TensorSpec")
        if self.kernel != frozen_kernel(self.spec):
            raise IndexContractError("index kernel differs from the frozen experiment kernel")
        if self.experiment_spec_digest != SPEC_DIGEST:
            raise IndexContractError(
                "index experiment_spec_digest does not match the frozen experiment spec"
            )
        if (
            self.spec.planes != PLANES
            or self.spec.roles != ROLES
            or self.spec.feature_dimension != 32
            or self.spec.seed not in FROZEN_SEEDS
            or self.spec.normalization != NORMALIZATION
            or self.spec.dense_scalar_count != 512
        ):
            raise IndexContractError("index TensorSpec is outside the frozen 4x4x32 policy")
        if self.representation not in _TENSOR_PREFIXES:
            raise IndexContractError("unsupported index representation")
        if type(self.backend_id) is not str or not self.backend_id:
            raise IndexContractError("index backend_id must not be empty")
        if type(self.source_revision) is not str or not self.source_revision:
            raise IndexContractError("index source_revision must not be empty")
        if type(self.corpus_digest) is not str or not _SHA256.fullmatch(self.corpus_digest):
            raise IndexContractError("index corpus_digest must be sha256:<hex>")
        documents = tuple(self.documents)
        if not documents:
            raise IndexContractError("index documents must not be empty")
        if len(documents) > MAX_INDEX_DOCUMENTS:
            raise IndexContractError("index document cap exceeded")
        if tuple(sorted(documents, key=lambda item: item.source_id)) != documents:
            raise IndexContractError("index documents must be sorted by source_id")
        seen: set[str] = set()
        for document in documents:
            if not isinstance(document, IndexDocument):
                raise IndexContractError("index documents must be IndexDocument values")
            if document.source_id in seen:
                raise IndexContractError(f"duplicate source_id {document.source_id!r}")
            seen.add(document.source_id)
            if document.tensor.spec != self.spec:
                raise IndexContractError("document TensorSpec differs from index TensorSpec")
            if document.backend_id != self.backend_id:
                raise IndexContractError("document backend differs from index backend")
            if document.revision != self.source_revision:
                raise IndexContractError("document revision differs from index revision")
            if _tensor_kind(document.tensor) != self.representation:
                raise IndexContractError("mixed tensor representations are forbidden")
        object.__setattr__(self, "documents", documents)
        expected_corpus = self.compute_corpus_digest(documents)
        if self.corpus_digest != expected_corpus:
            raise IndexContractError("corpus_digest does not address index sources")
        expected_index = self._computed_id()
        if type(self.index_id) is not str:
            raise IndexContractError("index_id must be a string")
        if self.index_id:
            if self.index_id != expected_index:
                raise IndexContractError("index_id does not address the index body")
        else:
            object.__setattr__(self, "index_id", expected_index)

    @staticmethod
    def compute_corpus_digest(documents: Sequence[IndexDocument]) -> str:
        manifest = [
            {
                "source_id": document.source_id,
                "source_digest": document.source_digest,
                "source_binding": document.source_binding,
                "source_evidence_digest": canonical_source_digest(
                    document.source_evidence
                ),
                "role_fields_digest": "sha256:"
                + canonical_digest(
                    document.fields.as_mapping(), domain="tensor-index-role-fields/1"
                ),
                "revision": document.revision,
            }
            for document in documents
        ]
        return "sha256:" + canonical_digest(manifest, domain="tensor-index-corpus/1")

    @classmethod
    def build(
        cls,
        artifacts: Sequence[EncodedArtifact],
        *,
        representation: str = "cp",
    ) -> "TensorIndex":
        if not artifacts:
            raise IndexContractError("cannot build an empty tensor index")
        if len(artifacts) > MAX_INDEX_DOCUMENTS:
            raise IndexContractError("index document cap exceeded")
        by_source: dict[str, IndexDocument] = {}
        for artifact in artifacts:
            document = IndexDocument.from_encoded(artifact, representation=representation)
            prior = by_source.get(document.source_id)
            if prior is None:
                by_source[document.source_id] = document
            elif prior != document:
                raise IndexContractError(
                    f"source_id {document.source_id!r} has conflicting content"
                )
        documents = tuple(sorted(by_source.values(), key=lambda item: item.source_id))
        first = documents[0]
        corpus_digest = cls.compute_corpus_digest(documents)
        return cls(
            spec=first.tensor.spec,
            kernel=frozen_kernel(first.tensor.spec),
            experiment_spec_digest=SPEC_DIGEST,
            backend_id=first.backend_id,
            representation=representation,
            source_revision=first.revision,
            corpus_digest=corpus_digest,
            documents=documents,
        )

    def _payload(self) -> dict[str, object]:
        return {
            "schema": INDEX_SCHEMA,
            "spec": self.spec.to_dict(),
            "kernel": self.kernel.to_dict(),
            "experiment_spec_digest": self.experiment_spec_digest,
            "backend_id": self.backend_id,
            "representation": self.representation,
            "source_revision": self.source_revision,
            "corpus_digest": self.corpus_digest,
            "kernel_id": self.kernel.kernel_id,
            "documents": [document.to_dict() for document in self.documents],
        }

    def _computed_id(self) -> str:
        return "index:" + canonical_digest(self._payload(), domain=INDEX_SCHEMA)

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "index_id": self.index_id}

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def storage_receipt(self) -> dict[str, object]:
        """Measure this derived index without creating another persisted store."""

        from .storage import numeric_scalar_count

        per_document = [
            numeric_scalar_count(document.tensor) for document in self.documents
        ]
        return {
            "schema": "forest-v2.tensor-index-storage-receipt/1",
            "index_id": self.index_id,
            "corpus_digest": self.corpus_digest,
            "kernel_id": self.kernel.kernel_id,
            "representation": self.representation,
            "documents": len(self.documents),
            "numeric_scalars": sum(per_document),
            "dense_equivalent_scalars": len(self.documents)
            * self.spec.dense_scalar_count,
            "canonical_bytes": len(self.canonical_bytes()),
            "automatic_promotions": 0,
        }

    @classmethod
    def from_dict(cls, value: object) -> "TensorIndex":
        data = _exact_mapping(
            value,
            {
                "schema",
                "spec",
                "kernel",
                "experiment_spec_digest",
                "backend_id",
                "representation",
                "source_revision",
                "corpus_digest",
                "kernel_id",
                "documents",
                "index_id",
            },
            "TensorIndex",
        )
        if data["schema"] != INDEX_SCHEMA:
            raise IndexContractError("unsupported tensor-index schema")
        if type(data["index_id"]) is not str or not data["index_id"]:
            raise IndexContractError("serialized index_id must be a non-empty string")
        spec = TensorSpec.from_dict(data["spec"])
        kernel = SeparableKernel.from_dict(data["kernel"], spec)
        if data["kernel_id"] != kernel.kernel_id:
            raise IndexContractError("top-level kernel_id does not match kernel body")
        raw_documents = data["documents"]
        if not isinstance(raw_documents, list):
            raise IndexContractError("index documents must be an array")
        if len(raw_documents) > MAX_INDEX_DOCUMENTS:
            raise IndexContractError("index document cap exceeded")
        documents = tuple(IndexDocument.from_dict(item, spec) for item in raw_documents)
        return cls(
            spec=spec,
            kernel=kernel,
            experiment_spec_digest=data["experiment_spec_digest"],
            backend_id=data["backend_id"],
            representation=data["representation"],
            source_revision=data["source_revision"],
            corpus_digest=data["corpus_digest"],
            documents=documents,
            index_id=data["index_id"],
        )

    @classmethod
    def from_bytes(cls, raw: bytes | str) -> "TensorIndex":
        return cls.from_dict(_strict_loads(raw))

    def search(
        self,
        query: EncodedArtifact,
        *,
        mode: str,
        kernel: SeparableKernel | None = None,
        limit: int = 20,
        explain_top: int = 8,
    ) -> tuple[SearchHit, ...]:
        if not isinstance(query, EncodedArtifact):
            raise IndexContractError("query must be EncodedArtifact")
        if (
            query.source_binding != "query_content_sha256_verified"
            or query.plane is not None
        ):
            raise IndexContractError(
                "search requires a plane-unspecified, verified query artifact"
            )
        if query.tensor.spec != self.spec:
            raise IndexContractError("query TensorSpec differs from index TensorSpec")
        if query.backend_id != self.backend_id:
            raise IndexContractError("query backend differs from index backend")
        if query.revision != self.source_revision:
            raise IndexContractError("query revision differs from index revision")
        try:
            validate_source_binding_evidence(
                source_id=query.source_id,
                source_digest=query.source_digest,
                source_binding=query.source_binding,
                source_evidence=query.source_evidence,
                revision=query.revision,
                plane=query.plane,
                fields=query.fields,
            )
            expected_query = TensorProductEncoder(
                self.spec, HashingFillerBackend(self.spec.seed)
            ).encode_query(
                query.source_evidence,
                query_id=query.source_id,
                revision=query.revision,
            )
        except (TypeError, ValueError) as exc:
            raise IndexContractError(f"query source binding is invalid: {exc}") from exc
        if expected_query.tensor != query.tensor:
            raise IndexContractError("query tensor does not match its replayed evidence")
        if isinstance(limit, bool) or type(limit) is not int or limit < 1:
            raise IndexContractError("search limit must be a positive integer")
        if isinstance(explain_top, bool) or type(explain_top) is not int or explain_top < 0:
            raise IndexContractError("explain_top must be a non-negative integer")
        if mode not in {"cosine", "identity", "structured", "maxsim"}:
            raise IndexContractError(f"unsupported search mode {mode!r}")
        if mode in {"structured", "maxsim"}:
            if not isinstance(kernel, SeparableKernel) or kernel != self.kernel:
                raise IndexContractError(f"{mode} search requires the index-bound kernel")
        elif kernel is not None:
            raise IndexContractError(f"{mode} search does not accept a kernel")

        scored: list[tuple[float, IndexDocument]] = []
        for document in self.documents:
            if mode == "cosine":
                score = flattened_cosine(query.tensor, document.tensor)
            elif mode == "identity":
                score = identity_contraction(query.tensor, document.tensor)
            elif mode == "structured":
                assert kernel is not None
                score = normalized_structured_score(query.tensor, document.tensor, kernel)
            else:
                assert kernel is not None
                score = fiber_maxsim(query.tensor, document.tensor, kernel)
            if not math.isfinite(score):
                raise IndexContractError("search produced a non-finite score")
            scored.append((score, document))
        scored.sort(key=lambda item: (-item[0], item[1].source_id))
        hits: list[SearchHit] = []
        for rank, (score, document) in enumerate(scored[:limit], 1):
            explanation: tuple[dict[str, object], ...] = ()
            explanation_total = 0
            explanation_numerator = None
            explanation_bound = None
            if mode == "structured":
                assert kernel is not None
                # Explanation is intentionally post-ranking: computing the
                # dense additive decomposition for every losing candidate
                # changes no rank and would dominate query cost.
                details = explain_contraction(query.tensor, document.tensor, kernel)
                strongest = sorted(
                    details.contributions,
                    key=lambda item: (
                        -abs(item.value),
                        item.query_plane,
                        item.document_plane,
                        item.query_role,
                        item.document_role,
                    ),
                )[:explain_top]
                explanation = tuple(
                    {
                        "query_plane": item.query_plane,
                        "document_plane": item.document_plane,
                        "query_role": item.query_role,
                        "document_role": item.document_role,
                        "feature_dot": item.feature_dot,
                        "plane_weight": item.plane_weight,
                        "role_weight": item.role_weight,
                        "contribution": item.value,
                    }
                    for item in strongest
                )
                explanation_total = len(details.contributions)
                explanation_numerator = details.numerator
                explanation_bound = details.normalization_bound
            hits.append(
                SearchHit(
                    rank=rank,
                    source_id=document.source_id,
                    source_digest=document.source_digest,
                    source_binding=document.source_binding,
                    revision=document.revision,
                    tensor_id=document.tensor.tensor_id,
                    score=score,
                    mode=mode,
                    index_id=self.index_id,
                    experiment_spec_digest=self.experiment_spec_digest,
                    corpus_digest=self.corpus_digest,
                    spec_id=self.spec.spec_id,
                    backend_id=self.backend_id,
                    kernel_id=kernel.kernel_id if kernel is not None else None,
                    query_source_id=query.source_id,
                    query_source_digest=query.source_digest,
                    query_source_binding=query.source_binding,
                    query_tensor_id=query.tensor.tensor_id,
                    explanation=explanation,
                    explanation_total_terms=explanation_total,
                    explanation_numerator=explanation_numerator,
                    explanation_normalization_bound=explanation_bound,
                )
            )
        return tuple(hits)


__all__ = [
    "AUTHORITY",
    "INDEX_DOCUMENT_SCHEMA",
    "INDEX_SCHEMA",
    "MAX_INDEX_DOCUMENTS",
    "PROPOSAL_SCHEMA",
    "IndexContractError",
    "IndexDocument",
    "SearchHit",
    "TensorIndex",
]
