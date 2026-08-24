"""Gold-free s09 retrievers for the frozen tensor-embedding experiment.

Every arm encodes the same ``QueryView.text`` and the same value returned by
``Candidate.text()`` with one :class:`TensorProductEncoder` configuration.
No retriever reads ``QueryView.repo``, a gold set, a filesystem path, history,
or any production store.  Scores are retrieval proposals only.

The structured matrices below are literal copies of ``EXPERIMENT_SPEC.json``.
They are constants rather than runtime file reads so zero-argument s09 loading
cannot gain an undeclared filesystem dependency.  The companion test checks
the constants against the frozen JSON.
"""
from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import dataclass
from typing import Sequence

from experiments.forest_v2.s09_eval.contract import (
    Candidate,
    ContractViolation,
    QueryView,
)

from .algebra import (
    PreparedFiberMaxSimQuery,
    PreparedFlattenedBilinearQuery,
    fiber_maxsim,
    flattened_cosine,
    identity_contraction,
    normalized_flattened_bilinear_score,
    normalized_prepared_flattened_bilinear_score,
    normalized_structured_score,
    prepare_fiber_maxsim_query,
    prepare_flattened_bilinear_query,
    prepared_fiber_maxsim,
)
from .contracts import CPTensor, Matrix, SeparableKernel, TensorSpec
from .encoding import (
    EncodedArtifact,
    HashingFillerBackend,
    PrecomputedFillerBackend,
    fields_from_candidate,
    TensorProductEncoder,
    canonical_source_digest,
    default_spec,
)


EXPERIMENT_SCHEMA = "forest-v2.tensor-embedding-experiment/1"
PACKET_ID = "EXPERIMENT-TENSOR-EMBEDDINGS-001"
SCORE_RECEIPT_SCHEMA = "forest-v2.tensor-score-receipt/1"

FROZEN_HASH_SEEDS = (11, 23, 47, 89, 131)
DEFAULT_HASH_SEED = FROZEN_HASH_SEEDS[0]
FROZEN_DENSE_SCALARS = 512

PLANE_KERNEL: Matrix = (
    (1.0, 0.5, 0.5, 0.5),
    (0.5, 1.0, 0.25, 0.25),
    (0.5, 0.25, 1.0, 0.5),
    (0.5, 0.25, 0.5, 1.0),
)

ROLE_KERNEL: Matrix = (
    (1.0, 0.75, 0.25, 0.1),
    (0.75, 1.0, 0.5, 0.25),
    (0.25, 0.5, 1.0, 0.25),
    (0.1, 0.25, 0.25, 1.0),
)

# Fixed-point-free cycles.  The controls permute document-side label meaning
# while leaving the query coordinates and frozen kernel coordinates in place.
# Applying one permutation to every side would only rename coordinates and
# would not be a negative control.
PLANE_PERMUTATION = (1, 2, 3, 0)
ROLE_PERMUTATION = (1, 2, 3, 0)

DEFAULT_CANDIDATE_CACHE_ENTRIES = 20_000
DEFAULT_PREPARED_QUERY_CACHE_ENTRIES = 256


@dataclass(frozen=True)
class CandidateTensorCacheInfo:
    """Cold/warm and eviction counters for one explicit evaluation cache."""

    warm_hits: int
    cold_misses: int
    evictions: int
    current_size: int
    max_entries: int


CandidateTensorCacheKey = tuple[str, str, str, str, str, str, str]

_CACHEABLE_BACKEND_TYPES = (HashingFillerBackend, PrecomputedFillerBackend)


def _implementation_identity(value: object, method_name: str) -> str:
    """Name the concrete class and method implementation used by a cache key."""

    kind = type(value)
    method = getattr(kind, method_name, None)
    method_module = getattr(method, "__module__", "")
    method_name_value = getattr(method, "__qualname__", repr(method))
    return (
        f"{kind.__module__}.{kind.__qualname__}:"
        f"{method_module}.{method_name_value}"
    )


class CandidateTensorCache:
    """Caller-owned LRU for exact, fully bound candidate projections.

    The cache is deliberately not process-global.  One benchmark/evaluation
    run may pass the same instance to all of its retriever arms, while a new
    run starts cold by constructing or clearing an instance.  Cache identity
    binds the encoder implementation, an immutable built-in backend and its
    content-addressed identity, TensorSpec, revision, source identity, and the
    exact budget-visible text.  Custom encoders and backends always bypass the
    cache because their output may depend on undeclared mutable state.  Hits
    return the original immutable artifact instead of relabeling a tensor with
    the current encoder's identity.
    """

    def __init__(self, max_entries: int = DEFAULT_CANDIDATE_CACHE_ENTRIES) -> None:
        if isinstance(max_entries, bool) or type(max_entries) is not int or max_entries <= 0:
            raise ValueError("max_entries must be a positive integer")
        self.max_entries = max_entries
        self._entries: "OrderedDict[CandidateTensorCacheKey, EncodedArtifact]" = (
            OrderedDict()
        )
        self._warm_hits = 0
        self._cold_misses = 0
        self._evictions = 0

    @staticmethod
    def _key(
        encoder: TensorProductEncoder,
        candidate: Candidate,
        text: str,
        revision: str,
    ) -> CandidateTensorCacheKey | None:
        if not isinstance(encoder, TensorProductEncoder):
            raise TypeError("encoder must be a TensorProductEncoder")
        if type(candidate.path) is not str or not candidate.path:
            raise ContractViolation("candidate path must be a non-empty string")
        if type(candidate.blob) is not str:
            raise ContractViolation("candidate blob must be a string")
        if type(text) is not str:
            raise ContractViolation("candidate text must be a string")
        if type(revision) is not str or not revision:
            raise ContractViolation("candidate revision must be a non-empty string")
        backend = encoder.backend
        if (
            type(encoder) is not TensorProductEncoder
            or type(backend) not in _CACHEABLE_BACKEND_TYPES
        ):
            return None
        encoder_identity = _implementation_identity(encoder, "encode_candidate")
        backend_identity = (
            _implementation_identity(backend, "embed") + ":" + backend.backend_id
        )
        return (
            encoder_identity,
            backend_identity,
            encoder.spec.spec_id,
            revision,
            candidate.path,
            candidate.blob,
            canonical_source_digest(text),
        )

    def encode_candidate(
        self,
        encoder: TensorProductEncoder,
        candidate: Candidate,
        text: str,
        revision: str,
    ) -> EncodedArtifact:
        """Return a warm projection or perform one cold exact encoding."""

        key = self._key(encoder, candidate, text, revision)
        if key is None:
            artifact = encoder.encode_candidate(
                candidate.path, text, blob=candidate.blob, revision=revision
            )
            self._cold_misses += 1
            return artifact

        cached = self._entries.get(key)
        if cached is not None:
            if (
                cached.backend_id != encoder.backend.backend_id
                or cached.tensor.spec != encoder.spec
                or cached.revision != revision
                or cached.source_id != candidate.path
                or cached.fields != fields_from_candidate(candidate.path, text)
            ):
                raise ContractViolation("candidate cache identity invariant failed")
            self._warm_hits += 1
            self._entries.move_to_end(key)
            return cached

        artifact = encoder.encode_candidate(
            candidate.path, text, blob=candidate.blob, revision=revision
        )
        self._cold_misses += 1
        self._entries[key] = artifact
        if len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
            self._evictions += 1
        return artifact

    def clear(self) -> None:
        """Start a new cold run and reset all cache measurement counters."""

        self._entries.clear()
        self._warm_hits = 0
        self._cold_misses = 0
        self._evictions = 0

    def info(self) -> CandidateTensorCacheInfo:
        """Return immutable cold/warm and eviction measurements."""

        return CandidateTensorCacheInfo(
            warm_hits=self._warm_hits,
            cold_misses=self._cold_misses,
            evictions=self._evictions,
            current_size=len(self._entries),
            max_entries=self.max_entries,
        )


def _permuted_document_columns(matrix: Matrix, permutation: Sequence[int]) -> Matrix:
    size = len(matrix)
    if tuple(sorted(permutation)) != tuple(range(size)):
        raise ValueError("control permutation must contain every matrix column once")
    return tuple(tuple(row[column] for column in permutation) for row in matrix)


def _uniform_matrix(size: int) -> Matrix:
    return tuple(tuple(1.0 for _ in range(size)) for _ in range(size))


def frozen_kernel(spec: TensorSpec) -> SeparableKernel:
    """Return the literal pre-registered structured kernel for ``spec``."""

    return SeparableKernel(
        spec=spec,
        plane_matrix=PLANE_KERNEL,
        role_matrix=ROLE_KERNEL,
    )


@dataclass(frozen=True)
class CandidateInputReceipt:
    """Identity of exactly the candidate view consumed by one scoring call."""

    path: str
    blob: str
    text_digest: str
    source_digest: str
    source_binding: str
    tensor_id: str
    text_characters: int

    @property
    def input_id(self) -> tuple[str, str, str]:
        # ``blob`` identifies the s09 candidate while ``text_digest`` binds the
        # budget-truncated Candidate.text() view actually consumed.
        return (self.path, self.blob, self.text_digest)

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "blob": self.blob,
            "text_digest": self.text_digest,
            "source_digest": self.source_digest,
            "source_binding": self.source_binding,
            "tensor_id": self.tensor_id,
            "text_characters": self.text_characters,
        }


@dataclass(frozen=True)
class ScoreReceipt:
    """Replay receipt for one query; it conveys no evidentiary authority."""

    retriever: str
    score_kind: str
    query_case_id: str
    query_variant: str
    revision: str
    query_text_digest: str
    query_tensor_id: str
    candidate_inputs: tuple[CandidateInputReceipt, ...]
    scores: tuple[tuple[str, float], ...]
    spec_id: str
    kernel_id: str
    backend_id: str
    seed: int
    dense_scalars_per_tensor: int
    input_scalar_budget: int
    schema: str = SCORE_RECEIPT_SCHEMA
    experiment_schema: str = EXPERIMENT_SCHEMA
    packet_id: str = PACKET_ID
    proposal_only: bool = True
    authority: str = "unverified-retrieval-proposal"

    @property
    def query_input_id(self) -> tuple[str, str, str, str]:
        return (
            self.query_case_id,
            self.query_variant,
            self.revision,
            self.query_text_digest,
        )

    @property
    def input_ids(self) -> tuple[tuple[str, str, str], ...]:
        return tuple(item.input_id for item in self.candidate_inputs)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "experiment_schema": self.experiment_schema,
            "packet_id": self.packet_id,
            "retriever": self.retriever,
            "score_kind": self.score_kind,
            "proposal_only": self.proposal_only,
            "authority": self.authority,
            "query": {
                "case_id": self.query_case_id,
                "variant": self.query_variant,
                "revision": self.revision,
                "text_digest": self.query_text_digest,
                "tensor_id": self.query_tensor_id,
            },
            "candidate_inputs": [item.to_dict() for item in self.candidate_inputs],
            "scores": [[path, score] for path, score in self.scores],
            "spec_id": self.spec_id,
            "kernel_id": self.kernel_id,
            "backend_id": self.backend_id,
            "seed": self.seed,
            "dense_scalars_per_tensor": self.dense_scalars_per_tensor,
            "input_scalar_budget": self.input_scalar_budget,
        }


@dataclass(frozen=True)
class _PreparedCandidate:
    candidate: Candidate
    text: str
    encoded: EncodedArtifact


QueryReceiptKey = tuple[str, str, str, str]


def _query_key(query: QueryView) -> QueryReceiptKey:
    # Deliberately enumerate the allowed fields.  In particular, do not use
    # dataclasses.asdict/query.__dict__, which would also copy a repo or an
    # accidental future gold-bearing field into experiment state.
    case_id = query.case_id
    variant = query.variant
    text = query.text
    revision = query.revision
    if not isinstance(case_id, str) or not case_id:
        raise ContractViolation("query case_id must be a non-empty string")
    if not isinstance(variant, str) or not variant:
        raise ContractViolation("query variant must be a non-empty string")
    if not isinstance(text, str):
        raise ContractViolation("query text must be a string")
    if not isinstance(revision, str) or not revision:
        raise ContractViolation("query revision must be a non-empty string")
    return (case_id, variant, revision, canonical_source_digest(text))


class _TensorRetriever:
    """Common encoder, input validation, tie-breaking and receipt behavior."""

    name = "tensor_abstract"
    score_kind = "abstract"

    def __init__(
        self,
        seed: int = DEFAULT_HASH_SEED,
        *,
        candidate_cache: CandidateTensorCache | None = None,
    ) -> None:
        if seed not in FROZEN_HASH_SEEDS:
            raise ValueError(f"seed must be one of the frozen seeds {FROZEN_HASH_SEEDS!r}")
        self.encoder = TensorProductEncoder(spec=default_spec(seed=seed))
        if self.encoder.spec.dense_scalar_count != FROZEN_DENSE_SCALARS:
            raise ValueError("frozen tensor spec must contain exactly 512 dense scalars")
        self.kernel = self._make_kernel(self.encoder.spec)
        if candidate_cache is not None and not isinstance(
            candidate_cache, CandidateTensorCache
        ):
            raise TypeError("candidate_cache must be a CandidateTensorCache")
        self.candidate_cache = candidate_cache or CandidateTensorCache()
        self.score_receipts: dict[QueryReceiptKey, ScoreReceipt] = {}
        self.last_score_receipt: ScoreReceipt | None = None

    def _make_kernel(self, spec: TensorSpec) -> SeparableKernel:
        return frozen_kernel(spec)

    def _score(self, query: CPTensor, document: CPTensor) -> float:
        raise NotImplementedError

    def _prepare_scoring_query(self, query: CPTensor) -> object:
        """Prepare query-constant score state once before the document loop."""

        return query

    def _score_prepared(self, query: object, document: CPTensor) -> float:
        if not isinstance(query, CPTensor):
            raise TypeError("default tensor scorer requires a CPTensor query")
        return self._score(query, document)

    def rank(self, query: QueryView, universe: Sequence[Candidate]) -> list[str]:
        query_key = _query_key(query)
        revision = query_key[2]
        encoded_query = self.encoder.encode_query(
            query.text,
            query_id=f"{query.case_id}:{query.variant}",
            revision=revision,
        )
        prepared = self._prepare_candidates(universe, revision=revision)
        scoring_query = self._prepare_scoring_query(encoded_query.tensor)

        scored: list[tuple[str, float]] = []
        for item in prepared:
            score = float(self._score_prepared(scoring_query, item.encoded.tensor))
            if not math.isfinite(score):
                raise ContractViolation(
                    f"retriever {self.name!r} produced a non-finite score for "
                    f"{item.candidate.path!r}"
                )
            scored.append((item.candidate.path, score))
        scored.sort(key=lambda item: (-item[1], item[0]))

        receipt = ScoreReceipt(
            retriever=self.name,
            score_kind=self.score_kind,
            query_case_id=query.case_id,
            query_variant=query.variant,
            revision=revision,
            query_text_digest=encoded_query.source_digest,
            query_tensor_id=encoded_query.tensor.tensor_id,
            candidate_inputs=tuple(
                CandidateInputReceipt(
                    path=item.candidate.path,
                    blob=item.candidate.blob,
                    text_digest=canonical_source_digest(item.text),
                    source_digest=item.encoded.source_digest,
                    source_binding=item.encoded.source_binding,
                    tensor_id=item.encoded.tensor.tensor_id,
                    text_characters=len(item.text),
                )
                for item in prepared
            ),
            scores=tuple(scored),
            spec_id=self.encoder.spec.spec_id,
            kernel_id=self.kernel.kernel_id,
            backend_id=encoded_query.backend_id,
            seed=self.encoder.spec.seed,
            dense_scalars_per_tensor=self.encoder.spec.dense_scalar_count,
            input_scalar_budget=(
                len(self.encoder.spec.planes)
                * len(self.encoder.spec.roles)
                * self.encoder.spec.feature_dimension
            ),
        )
        self.score_receipts[query_key] = receipt
        self.last_score_receipt = receipt
        return [path for path, _score in scored]

    def score_receipt(self, query: QueryView) -> ScoreReceipt:
        """Return the retained receipt for ``query`` after :meth:`rank`."""

        key = _query_key(query)
        try:
            return self.score_receipts[key]
        except KeyError as exc:
            raise KeyError("query has not been ranked by this retriever") from exc

    def _prepare_candidates(
        self, universe: Sequence[Candidate], *, revision: str
    ) -> tuple[_PreparedCandidate, ...]:
        candidates: list[Candidate] = []
        seen: set[str] = set()
        for candidate in universe:
            path = candidate.path
            if not isinstance(path, str) or not path:
                raise ContractViolation("candidate path must be a non-empty string")
            if path in seen:
                raise ContractViolation(f"candidate universe contains duplicate path {path!r}")
            if not isinstance(candidate.blob, str):
                raise ContractViolation(f"candidate {path!r} blob must be a string")
            seen.add(path)
            candidates.append(candidate)

        prepared: list[_PreparedCandidate] = []
        for candidate in sorted(candidates, key=lambda item: item.path):
            # Candidate.text() is the sole content boundary.  Do not inspect
            # raw bytes, the repository, or the filesystem.
            text = candidate.text()
            if not isinstance(text, str):
                raise ContractViolation(f"Candidate.text() for {candidate.path!r} is not str")
            encoded = self.candidate_cache.encode_candidate(
                self.encoder, candidate, text, revision
            )
            prepared.append(_PreparedCandidate(candidate, text, encoded))
        return tuple(prepared)


class FlatCosineRetriever(_TensorRetriever):
    """Flattened cosine over the exact same globally normalized tensor."""

    name = "flattened_cosine_same_scalars"
    score_kind = "flattened_cosine"

    def _make_kernel(self, spec: TensorSpec) -> SeparableKernel:
        # Cosine has no compatibility kernel, but the identity kernel ID makes
        # the algebraic comparator explicit and receipt-comparable.
        return SeparableKernel.identity(spec)

    def _score(self, query: CPTensor, document: CPTensor) -> float:
        return flattened_cosine(query, document)


class IdentityContractionRetriever(_TensorRetriever):
    """Identity contraction; required to rank exactly like flat cosine."""

    name = "identity_contraction"
    score_kind = "identity_contraction"

    def _make_kernel(self, spec: TensorSpec) -> SeparableKernel:
        return SeparableKernel.identity(spec)

    def _score(self, query: CPTensor, document: CPTensor) -> float:
        return identity_contraction(query, document)


class TensorContractionRetriever(_TensorRetriever):
    """Primary pre-registered plane/role structured contraction."""

    name = "structured_contraction"
    score_kind = "normalized_structured_contraction"

    def _score(self, query: CPTensor, document: CPTensor) -> float:
        return normalized_structured_score(query, document, self.kernel)


class FlattenedBilinearRetriever(_TensorRetriever):
    """Vectorized Kronecker-bilinear null control for tensor contraction."""

    name = "flattened_bilinear_same_kernel"
    score_kind = "normalized_flattened_kronecker_bilinear"

    def __init__(
        self,
        seed: int = DEFAULT_HASH_SEED,
        *,
        candidate_cache: CandidateTensorCache | None = None,
    ) -> None:
        super().__init__(seed=seed, candidate_cache=candidate_cache)
        self._prepared_query_cache: "OrderedDict[tuple[str, str, str], PreparedFlattenedBilinearQuery]" = OrderedDict()

    def _prepare_scoring_query(
        self, query: CPTensor
    ) -> PreparedFlattenedBilinearQuery:
        # tensor_id binds the exact numeric query, spec_id binds its frozen
        # seed/coordinate system, and kernel_id binds the transform itself.
        key = (query.tensor_id, query.spec_id, self.kernel.kernel_id)
        cached = self._prepared_query_cache.get(key)
        if cached is not None:
            self._prepared_query_cache.move_to_end(key)
            return cached
        prepared = prepare_flattened_bilinear_query(query, self.kernel)
        self._prepared_query_cache[key] = prepared
        if len(self._prepared_query_cache) > DEFAULT_PREPARED_QUERY_CACHE_ENTRIES:
            self._prepared_query_cache.popitem(last=False)
        return prepared

    def _score_prepared(self, query: object, document: CPTensor) -> float:
        if not isinstance(query, PreparedFlattenedBilinearQuery):
            raise TypeError("flattened bilinear scorer requires a prepared query")
        # Keep _score as the single load-bearing scoring seam.  Besides making
        # the optimized and reference forms explicit in one place, benchmark
        # fault injection against _score must still reach the production path.
        return self._score(query, document)

    def _score(
        self,
        query: CPTensor | PreparedFlattenedBilinearQuery,
        document: CPTensor,
    ) -> float:
        if isinstance(query, PreparedFlattenedBilinearQuery):
            return normalized_prepared_flattened_bilinear_score(query, document)
        return normalized_flattened_bilinear_score(query, document, self.kernel)


class TensorLateInteractionRetriever(_TensorRetriever):
    """Secondary fiber-wise MaxSim arm over the same encoded tensor."""

    name = "tensor_late_interaction"
    score_kind = "fiber_maxsim"

    def __init__(
        self,
        seed: int = DEFAULT_HASH_SEED,
        *,
        candidate_cache: CandidateTensorCache | None = None,
    ) -> None:
        super().__init__(seed=seed, candidate_cache=candidate_cache)
        self._prepared_query_cache: (
            "OrderedDict[tuple[str, str, str], PreparedFiberMaxSimQuery]"
        ) = OrderedDict()

    def _prepare_scoring_query(self, query: CPTensor) -> PreparedFiberMaxSimQuery:
        key = (query.tensor_id, query.spec_id, self.kernel.kernel_id)
        cached = self._prepared_query_cache.get(key)
        if cached is not None:
            self._prepared_query_cache.move_to_end(key)
            return cached
        prepared = prepare_fiber_maxsim_query(query, self.kernel)
        self._prepared_query_cache[key] = prepared
        if len(self._prepared_query_cache) > DEFAULT_PREPARED_QUERY_CACHE_ENTRIES:
            self._prepared_query_cache.popitem(last=False)
        return prepared

    def _score_prepared(self, query: object, document: CPTensor) -> float:
        if not isinstance(query, PreparedFiberMaxSimQuery):
            raise TypeError("late-interaction scorer requires a prepared query")
        # Keep _score as the load-bearing seam used by benchmark fault
        # injection; preparation must not bypass an overridden scorer.
        return self._score(query, document)

    def _score(
        self,
        query: CPTensor | PreparedFiberMaxSimQuery,
        document: CPTensor,
    ) -> float:
        if isinstance(query, PreparedFiberMaxSimQuery):
            return prepared_fiber_maxsim(query, document)
        return fiber_maxsim(query, document, self.kernel)


class PlanePermutationControl(TensorContractionRetriever):
    """Document-side plane labels are cyclically misaligned with the kernel."""

    name = "plane_label_permutation"
    score_kind = "plane_permutation_control"

    def _make_kernel(self, spec: TensorSpec) -> SeparableKernel:
        return SeparableKernel(
            spec=spec,
            plane_matrix=_permuted_document_columns(PLANE_KERNEL, PLANE_PERMUTATION),
            role_matrix=ROLE_KERNEL,
        )


class RolePermutationControl(TensorContractionRetriever):
    """Document-side role labels are cyclically misaligned with the kernel."""

    name = "role_label_permutation"
    score_kind = "role_permutation_control"

    def _make_kernel(self, spec: TensorSpec) -> SeparableKernel:
        return SeparableKernel(
            spec=spec,
            plane_matrix=PLANE_KERNEL,
            role_matrix=_permuted_document_columns(ROLE_KERNEL, ROLE_PERMUTATION),
        )


class UniformKernelControl(TensorContractionRetriever):
    """All planes and roles are uniformly compatible; named axes collapse."""

    name = "uniform_kernel"
    score_kind = "uniform_kernel_control"

    def _make_kernel(self, spec: TensorSpec) -> SeparableKernel:
        return SeparableKernel(
            spec=spec,
            plane_matrix=_uniform_matrix(len(spec.planes)),
            role_matrix=_uniform_matrix(len(spec.roles)),
        )


__all__ = [
    "EXPERIMENT_SCHEMA",
    "PACKET_ID",
    "SCORE_RECEIPT_SCHEMA",
    "FROZEN_HASH_SEEDS",
    "DEFAULT_HASH_SEED",
    "FROZEN_DENSE_SCALARS",
    "PLANE_KERNEL",
    "ROLE_KERNEL",
    "PLANE_PERMUTATION",
    "ROLE_PERMUTATION",
    "DEFAULT_CANDIDATE_CACHE_ENTRIES",
    "CandidateTensorCache",
    "CandidateTensorCacheInfo",
    "CandidateInputReceipt",
    "ScoreReceipt",
    "frozen_kernel",
    "FlatCosineRetriever",
    "FlattenedBilinearRetriever",
    "IdentityContractionRetriever",
    "TensorContractionRetriever",
    "TensorLateInteractionRetriever",
    "PlanePermutationControl",
    "RolePermutationControl",
    "UniformKernelControl",
]
