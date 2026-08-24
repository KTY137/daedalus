"""Gold-separated, budget-equal evaluation for tensor retrieval arms.

The evaluator owns gold labels and never places them in ``QueryView`` or a
retriever receipt.  All arms receive the same query object and candidate
universe; their receipts are compared after each call before a score is
accepted.  This module is effect-free and returns a validated diagnostic
report object.  It is not a scientific Decision API.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Sequence, Type

from experiments.forest_v2.s09_eval.contract import (
    Candidate,
    QueryView,
    validate_ranking,
)

from .algebra import flattened_cosine, normalized_structured_score
from .arm_census import REQUIRED_ARM_NAMES, TENSOR_ARM_NAMES
from .baseline_retrievers import (
    BASELINE_BACKEND_ID,
    BASELINE_RETRIEVER_TYPES,
    BaselineCandidateCache,
    BaselineCandidateInputReceipt,
    BaselineScoreReceipt,
    baseline_query_key,
)
from .contracts import canonical_digest
from .encoding import (
    RoleFields,
    TensorProductEncoder,
    canonical_source_digest,
    default_spec,
)
from .retrievers import (
    CandidateInputReceipt,
    CandidateTensorCache,
    FROZEN_HASH_SEEDS,
    FlatCosineRetriever,
    FlattenedBilinearRetriever,
    IdentityContractionRetriever,
    PlanePermutationControl,
    RolePermutationControl,
    TensorContractionRetriever,
    TensorLateInteractionRetriever,
    UniformKernelControl,
    ScoreReceipt,
    frozen_kernel,
)
from .stats import (
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    EVALUATION_PROTOCOL_DIGEST,
    NO_SCIENTIFIC_VERDICT,
    PACKET_ID,
    QUERY_VARIANTS,
    REPORT_SCHEMA,
    SPEC_DIGEST,
    first_hit_coverage,
    paired_bootstrap_difference,
    recall_at_k,
    reciprocal_rank,
    validate_report,
)


RetrieverType = Type[FlatCosineRetriever]
TENSOR_RETRIEVER_TYPES: tuple[type, ...] = (
    FlatCosineRetriever,
    IdentityContractionRetriever,
    TensorContractionRetriever,
    FlattenedBilinearRetriever,
    TensorLateInteractionRetriever,
    PlanePermutationControl,
    RolePermutationControl,
    UniformKernelControl,
)
DEFAULT_RETRIEVERS: tuple[type, ...] = (
    *TENSOR_RETRIEVER_TYPES,
    *BASELINE_RETRIEVER_TYPES,
)
if tuple(kind.name for kind in DEFAULT_RETRIEVERS) != REQUIRED_ARM_NAMES:
    raise RuntimeError("executable retriever census differs from the frozen arm census")
PRIMARY_ARM = TensorContractionRetriever.name
REFERENCE_ARM = FlatCosineRetriever.name
VECTOR_EQUIVALENT_ARM = FlattenedBilinearRetriever.name
NEGATIVE_CONTROLS = (
    PlanePermutationControl.name,
    RolePermutationControl.name,
    UniformKernelControl.name,
)
FROZEN_QUERY_VARIANTS = frozenset(QUERY_VARIANTS)
MAX_CANDIDATES_PER_CASE = 65_536
MAX_CONTENT_BYTES = 65_536
MAX_FILE_BYTES = 200_000
EVALUATED_RANK_LIMIT = 20
EQUIVALENCE_TOLERANCE = 1e-10


def benchmark_case_key(query: QueryView) -> str:
    """Collision-free report key for one case/query-variant pair."""

    return _case_variant_key(query.case_id, query.variant)


def _case_variant_key(case_id: str, variant: str) -> str:
    return json.dumps(
        [case_id, variant],
        ensure_ascii=False,
        separators=(",", ":"),
    )


@dataclass(frozen=True)
class BenchmarkCase:
    """Evaluator-only case; gold never enters :attr:`query`."""

    query: QueryView
    universe: tuple[Candidate, ...]
    gold: tuple[str, ...]
    recency_ranking: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if type(self.query.case_id) is not str or not self.query.case_id:
            raise ValueError("benchmark case_id must not be empty")
        if self.query.variant not in FROZEN_QUERY_VARIANTS:
            raise ValueError("benchmark query variant must be raw or scrubbed")
        if type(self.query.revision) is not str or not self.query.revision:
            raise ValueError("benchmark revision must not be empty")
        if type(self.query.text) is not str or not self.query.text:
            raise ValueError("benchmark query text must not be empty")
        if not self.universe:
            raise ValueError("benchmark universe must not be empty")
        if len(self.universe) > MAX_CANDIDATES_PER_CASE:
            raise ValueError("benchmark candidate cap exceeded")
        if any(not isinstance(candidate, Candidate) for candidate in self.universe):
            raise TypeError("benchmark universe must contain frozen s09 Candidate values")
        for candidate in self.universe:
            if type(candidate.path) is not str or not candidate.path:
                raise ValueError("candidate path must be non-empty text")
            if type(candidate.blob) is not str or not candidate.blob:
                raise ValueError("candidate blob must be non-empty text")
            if type(candidate.raw) is not bytes:
                raise ValueError("candidate raw source must be bytes")
            if not 0 < candidate.size <= MAX_FILE_BYTES:
                raise ValueError("candidate file size is outside the frozen budget")
            if not 0 < candidate.content_budget <= MAX_CONTENT_BYTES:
                raise ValueError("candidate content budget is outside the frozen cap")
            # The canonical s09 BlobStore deliberately retains only the bytes
            # visible through Candidate.text() for files larger than the
            # content budget.  Direct fixtures may instead carry the complete
            # blob; both forms expose exactly the same input to every arm.
            # Refuse arbitrary partial payloads, which would make the declared
            # file size and the actually available visible prefix diverge.
            visible_size = min(candidate.size, candidate.content_budget)
            if len(candidate.raw) not in {visible_size, candidate.size}:
                raise ValueError(
                    "candidate raw source must be the complete blob or its "
                    "exact budget-visible prefix"
                )
        paths = [candidate.path for candidate in self.universe]
        if len(set(paths)) != len(paths):
            raise ValueError("benchmark universe contains duplicate paths")
        if not self.gold:
            raise ValueError("benchmark gold must not be empty")
        outside = set(self.gold) - set(paths)
        if outside:
            raise ValueError(f"gold paths outside candidate universe: {sorted(outside)!r}")
        if self.recency_ranking is not None:
            if type(self.recency_ranking) is not tuple or any(
                type(path) is not str or not path for path in self.recency_ranking
            ):
                raise ValueError("recency ranking must be a tuple of non-empty paths")
            if len(set(self.recency_ranking)) != len(self.recency_ranking):
                raise ValueError("recency ranking contains duplicate paths")
            outside_recency = set(self.recency_ranking) - set(paths)
            if outside_recency:
                raise ValueError(
                    "recency paths outside candidate universe: "
                    f"{sorted(outside_recency)!r}"
                )


def _case_manifest(case: BenchmarkCase) -> dict[str, object]:
    return {
        "case_id": case.query.case_id,
        "variant": case.query.variant,
        "revision": case.query.revision,
        "query_digest": canonical_source_digest(case.query.text),
        "candidate_inputs": [
            {
                "path": candidate.path,
                "blob": candidate.blob,
                "size": candidate.size,
                "content_budget": candidate.content_budget,
                "text_digest": canonical_source_digest(candidate.text()),
            }
            for candidate in case.universe
        ],
        # Gold is evaluator-side but must be included in corpus identity so a
        # relabeled answer set cannot reuse an old report digest.
        "gold": list(case.gold),
        # Candidate carries no history.  The evaluator supplies this
        # caller-asserted, query-blind control and its order is therefore part
        # of corpus identity rather than undeclared ambient repository state.
        # The digest binds the assertion; it does not verify its historical
        # provenance.
        "recency_ranking": (
            list(case.recency_ranking)
            if case.recency_ranking is not None
            else None
        ),
    }


def corpus_digest(cases: Sequence[BenchmarkCase]) -> str:
    return "sha256:" + canonical_digest(
        [_case_manifest(case) for case in cases], domain="tensor-benchmark-corpus/1"
    )


def _metrics(ranking: Sequence[str], gold: Sequence[str]) -> dict[str, float]:
    return {
        "reciprocal_rank": reciprocal_rank(ranking, gold),
        "recall_at_1": recall_at_k(ranking, gold, 1),
        "recall_at_5": recall_at_k(ranking, gold, 5),
        "recall_at_10": recall_at_k(ranking, gold, 10),
        "recall_at_20": recall_at_k(ranking, gold, 20),
        "first_hit_coverage": first_hit_coverage(ranking, gold),
    }


def _failure(
    arm: str | None,
    seed: int | None,
    case_id: str | None,
    category: str,
    message: str,
) -> dict[str, object]:
    return {
        "arm": arm,
        "seed": seed,
        "case_id": case_id,
        "category": category,
        "message": message,
    }


def _validate_score_receipt_shape(
    arm: str,
    receipt: object,
    universe: Sequence[Candidate],
    measured_ranking: Sequence[str],
) -> None:
    """Refuse malformed arm evidence before cross-arm validation touches it."""

    tensor_arm = arm in TENSOR_ARM_NAMES
    expected_receipt_type = ScoreReceipt if tensor_arm else BaselineScoreReceipt
    expected_input_type = (
        CandidateInputReceipt if tensor_arm else BaselineCandidateInputReceipt
    )
    if type(receipt) is not expected_receipt_type:
        raise TypeError(
            f"{arm} returned {type(receipt).__name__}, expected "
            f"{expected_receipt_type.__name__}"
        )
    if receipt.retriever != arm:
        raise ValueError("receipt retriever name differs from the executed arm")
    if receipt.proposal_only is not True or (
        receipt.authority != "unverified-retrieval-proposal"
    ):
        raise ValueError("receipt attempts to claim authority beyond a proposal")
    if isinstance(receipt.seed, bool) or type(receipt.seed) is not int:
        raise TypeError("receipt seed must be an integer")
    if not tensor_arm and receipt.backend_id != BASELINE_BACKEND_ID:
        raise ValueError("baseline receipt backend identity is not frozen")
    if type(receipt.candidate_inputs) is not tuple or any(
        type(item) is not expected_input_type for item in receipt.candidate_inputs
    ):
        raise TypeError("receipt candidate_inputs has the wrong exact shape")

    expected_paths = tuple(sorted(candidate.path for candidate in universe))
    input_paths = tuple(item.path for item in receipt.candidate_inputs)
    if input_paths != expected_paths:
        raise ValueError("receipt candidate inputs differ from the common universe")
    for item in receipt.candidate_inputs:
        if (
            type(item.path) is not str
            or not item.path
            or type(item.blob) is not str
            or not item.blob
            or type(item.text_digest) is not str
            or not item.text_digest
        ):
            raise TypeError("receipt candidate identity is malformed")
        if tensor_arm and (
            type(item.tensor_id) is not str or not item.tensor_id
        ):
            raise TypeError("tensor receipt candidate tensor ID is malformed")

    if type(receipt.scores) is not tuple or len(receipt.scores) != len(expected_paths):
        raise TypeError("receipt must retain one score for every candidate")
    score_paths: list[str] = []
    for row in receipt.scores:
        if type(row) is not tuple or len(row) != 2:
            raise TypeError("receipt score rows must be exact (path, score) tuples")
        path, score = row
        if type(path) is not str or not path:
            raise TypeError("receipt score path is malformed")
        if isinstance(score, bool) or type(score) not in (int, float):
            raise TypeError("receipt score must be a real number")
        if not math.isfinite(float(score)):
            raise ValueError("receipt score must be finite")
        score_paths.append(path)
    if len(set(score_paths)) != len(score_paths) or set(score_paths) != set(expected_paths):
        raise ValueError("receipt scores do not cover the common universe exactly")
    canonical_scores = sorted(
        receipt.scores,
        key=lambda row: (-float(row[1]), row[0]),
    )
    expected_ranking = tuple(
        path
        for path, score in canonical_scores
        if tensor_arm or float(score) > 0.0
    )[:EVALUATED_RANK_LIMIT]
    if tuple(measured_ranking) != expected_ranking:
        raise ValueError("measured ranking is not bound to receipt score order")


def _equivalent_score_rows(
    left_rows: Sequence[tuple[str, float]],
    right_rows: Sequence[tuple[str, float]],
) -> bool:
    """Compare algebraic controls by candidate identity and evaluated order.

    Equivalent floating-point implementations may reverse a near-tie below
    the evaluated top-20 cutoff.  Receipt tuple position is therefore not an
    algebraic identity: every candidate score must agree by path within the
    frozen tolerance, while the ranking that actually enters metrics must be
    exactly the same.
    """

    left_scores = {path: float(score) for path, score in left_rows}
    right_scores = {path: float(score) for path, score in right_rows}
    if (
        len(left_scores) != len(left_rows)
        or len(right_scores) != len(right_rows)
        or left_scores.keys() != right_scores.keys()
    ):
        return False
    if any(
        not math.isfinite(left_scores[path])
        or not math.isfinite(right_scores[path])
        or not math.isclose(
            left_scores[path],
            right_scores[path],
            rel_tol=0.0,
            abs_tol=EQUIVALENCE_TOLERANCE,
        )
        for path in left_scores
    ):
        return False

    def evaluated_order(scores: dict[str, float]) -> tuple[str, ...]:
        return tuple(
            path
            for path, _score in sorted(
                scores.items(), key=lambda row: (-row[1], row[0])
            )[:EVALUATED_RANK_LIMIT]
        )

    return evaluated_order(left_scores) == evaluated_order(right_scores)


def _mean_seed_metric(
    arms: dict[str, object], arm: str, case_id: str, metric: str
) -> float:
    runs = arms[arm]
    assert isinstance(runs, dict)
    values = [runs[str(seed)]["per_case"][case_id][metric] for seed in FROZEN_HASH_SEEDS]
    return math.fsum(values) / len(values)


def _comparison(
    mean_scores: dict[str, dict[tuple[str, str], float]],
    left_arm: str,
    right_arm: str,
    variant: str,
) -> dict[str, object]:
    pairs = tuple(next(iter(mean_scores.values())))
    if variant == "all":
        # Raw and scrubbed are repeated views of one underlying task, not two
        # independent samples. Average the available variants within each base
        # case before the paired bootstrap resamples base cases.
        case_ids = tuple(dict.fromkeys(case_id for case_id, _ in pairs))

        def grouped(arm: str) -> dict[str, float]:
            return {
                case_id: math.fsum(
                    mean_scores[arm][pair] for pair in pairs if pair[0] == case_id
                )
                / sum(pair[0] == case_id for pair in pairs)
                for case_id in case_ids
            }

        left = grouped(left_arm)
        right = grouped(right_arm)
    else:
        selected = [pair for pair in pairs if pair[1] == variant]
        left = {
            case_id: mean_scores[left_arm][(case_id, variant)]
            for case_id, _ in selected
        }
        right = {
            case_id: mean_scores[right_arm][(case_id, variant)]
            for case_id, _ in selected
        }
    interval = paired_bootstrap_difference(left, right)
    return {
        "left_arm": left_arm,
        "right_arm": right_arm,
        "variant": variant,
        "metric": "reciprocal_rank",
        **interval.as_dict(),
        "superiority_claim": False,
    }


def run_benchmark(
    cases: Sequence[BenchmarkCase],
    *,
    retriever_types: Sequence[type] = DEFAULT_RETRIEVERS,
) -> dict[str, object]:
    """Return a strict **diagnostic** report with no scientific verdict.

    Gold and retrievers share one Python process in this convenience harness,
    which is not a security boundary against reflective plugin code.  Only the
    exact audited in-package arm classes are accepted, and this function emits
    only ``INCONCLUSIVE`` or ``NO_SCIENTIFIC_VERDICT``.  Neither this harness
    nor the structural ``sealed_eval`` module is a Decision API.  Supporting
    ``ADVANCE``/``KILL`` would require both an owner-recorded plan/Work-Packet
    amendment and an externally controlled trust chain.
    """

    case_tuple = tuple(cases)
    if not case_tuple:
        raise ValueError("benchmark needs at least one case")
    case_pairs = tuple(
        (case.query.case_id, case.query.variant) for case in case_tuple
    )
    case_ids = tuple(benchmark_case_key(case.query) for case in case_tuple)
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("benchmark (case_id, variant) pairs must be unique")
    if not retriever_types:
        raise ValueError("benchmark needs the complete frozen arm census")

    arm_names = tuple(str(getattr(kind, "name", "")) for kind in retriever_types)
    if any(not name for name in arm_names) or len(set(arm_names)) != len(arm_names):
        raise ValueError("retriever arms need unique non-empty class names")
    if any(kind not in DEFAULT_RETRIEVERS for kind in retriever_types):
        raise ValueError("diagnostic benchmark accepts only exact audited retriever classes")
    if tuple(retriever_types) != DEFAULT_RETRIEVERS or arm_names != REQUIRED_ARM_NAMES:
        raise ValueError("benchmark requires the complete frozen arm census in order")
    if any(case.recency_ranking is None for case in case_tuple):
        raise ValueError(
            "benchmark needs a caller-asserted recency ranking for every case"
        )

    base_inputs_by_case_id: dict[str, tuple[object, ...]] = {}
    recency_by_case_id: dict[str, tuple[str, ...] | None] = {}
    for case in case_tuple:
        base_inputs = (
            case.query.revision,
            case.query.repo,
            case.universe,
            case.gold,
        )
        prior_inputs = base_inputs_by_case_id.setdefault(
            case.query.case_id, base_inputs
        )
        if prior_inputs != base_inputs:
            raise ValueError(
                "all query variants of one case_id must share the same "
                "revision, repository, candidate universe, and evaluator gold"
            )
        prior = recency_by_case_id.setdefault(
            case.query.case_id, case.recency_ranking
        )
        if prior != case.recency_ranking:
            raise ValueError(
                "all query variants of one case_id must use the same "
                "caller-asserted recency ranking"
            )

    recency_by_query = {
        baseline_query_key(case.query): case.recency_ranking
        for case in case_tuple
    }

    arms: dict[str, dict[str, object]] = {name: {} for name in arm_names}
    failures: list[dict[str, object]] = []
    for seed in FROZEN_HASH_SEEDS:
        # Cache scope is one complete seed run.  All tensor arms reuse exact
        # candidate projections for that seed; all lexical arms reuse the
        # same visible-text/token preparation.  A later seed always starts
        # cold and cannot inherit a projection from an earlier TensorSpec.
        tensor_cache = CandidateTensorCache()
        baseline_cache = BaselineCandidateCache()
        retrievers = [
            kind(seed=seed, candidate_cache=tensor_cache)
            for kind in TENSOR_RETRIEVER_TYPES
        ] + [
            kind(
                seed=seed,
                candidate_cache=baseline_cache,
                recency_by_query=recency_by_query,
            )
            for kind in BASELINE_RETRIEVER_TYPES
        ]
        for name in arm_names:
            arms[name][str(seed)] = {"per_case": {}}
        for case in case_tuple:
            case_id = benchmark_case_key(case.query)
            receipts = []
            for retriever, name in zip(retrievers, arm_names):
                stage = "ranking"
                try:
                    raw = retriever.rank(case.query, case.universe)
                    ranking = validate_ranking(
                        name,
                        raw,
                        case.universe,
                        max_k=EVALUATED_RANK_LIMIT,
                    )
                    stage = "receipt"
                    receipt = retriever.score_receipt(case.query)
                    _validate_score_receipt_shape(
                        name,
                        receipt,
                        case.universe,
                        ranking,
                    )
                    receipts.append((name, receipt))
                    arms[name][str(seed)]["per_case"][case_id] = _metrics(
                        ranking, case.gold
                    )
                except Exception as exc:  # retain, never turn failure into a metric
                    failures.append(
                        _failure(
                            name,
                            seed,
                            case_id,
                            (
                                "input_receipt_validation_failure"
                                if stage == "receipt"
                                else "runtime_failure"
                            ),
                            f"{type(exc).__name__}: {exc}",
                        )
                    )

            if len(receipts) == len(arm_names):
                reference = receipts[0][1]
                reference_tensor_ids = tuple(
                    item.tensor_id for item in reference.candidate_inputs
                )
                for name, receipt in receipts:
                    common_mismatch = (
                        receipt.query_input_id != reference.query_input_id
                        or receipt.input_ids != reference.input_ids
                        or receipt.seed != reference.seed
                        or receipt.proposal_only is not True
                        or receipt.authority != "unverified-retrieval-proposal"
                    )
                    if name in TENSOR_ARM_NAMES:
                        budget_mismatch = (
                            receipt.query_tensor_id != reference.query_tensor_id
                            or tuple(
                                item.tensor_id for item in receipt.candidate_inputs
                            )
                            != reference_tensor_ids
                            or receipt.spec_id != reference.spec_id
                            or receipt.input_scalar_budget != 512
                            or receipt.dense_scalars_per_tensor != 512
                        )
                    else:
                        budget_mismatch = (
                            receipt.input_scalar_budget != 0
                            or receipt.dense_scalars_per_tensor != 0
                        )
                    mismatch = common_mismatch or budget_mismatch
                    if mismatch:
                        failures.append(
                            _failure(
                                name,
                                seed,
                                case_id,
                                "budget_or_input_mismatch",
                                "arm receipt differs from the common input/budget contract",
                            )
                        )
                receipt_by_name = dict(receipts)
                for left_name, right_name, label in (
                    (
                        IdentityContractionRetriever.name,
                        FlatCosineRetriever.name,
                        "identity_cosine_equivalence_failure",
                    ),
                    (
                        TensorContractionRetriever.name,
                        FlattenedBilinearRetriever.name,
                        "tensor_vector_bilinear_equivalence_failure",
                    ),
                ):
                    if left_name not in receipt_by_name or right_name not in receipt_by_name:
                        continue
                    if not _equivalent_score_rows(
                        receipt_by_name[left_name].scores,
                        receipt_by_name[right_name].scores,
                    ):
                        failures.append(
                            _failure(
                                left_name,
                                seed,
                                case_id,
                                label,
                                f"{left_name} differs from its exact {right_name} control",
                            )
                        )

    if not failures:
        status = "VALID"
    elif any(
        any(
            marker in str(item["category"])
            for marker in ("budget", "input", "isolation", "equivalence")
        )
        for item in failures
    ):
        status = "INVALID"
    else:
        status = "BLOCKED"
    comparisons: list[dict[str, object]] = []
    conclusion = NO_SCIENTIFIC_VERDICT if failures else "INCONCLUSIVE"
    if not failures:
        mean_values: dict[str, dict[tuple[str, str], float]] = {}
        for name in arm_names:
            mean_values[name] = {
                pair: _mean_seed_metric(
                    arms,
                    name,
                    _case_variant_key(*pair),
                    "reciprocal_rank",
                )
                for pair in case_pairs
            }
        comparison_variants = (
            "all",
            *(
                variant
                for variant in QUERY_VARIANTS
                if any(pair_variant == variant for _, pair_variant in case_pairs)
            ),
        )
        comparisons.extend(
            _comparison(mean_values, name, REFERENCE_ARM, variant)
            for name in arm_names
            if name != REFERENCE_ARM
            for variant in comparison_variants
        )

        # Negative controls test the named structure, so the causal contrast
        # is structured minus control (not control minus flat cosine).
        comparisons.extend(
            _comparison(mean_values, PRIMARY_ARM, control, variant)
            for control in NEGATIVE_CONTROLS
            for variant in comparison_variants
        )

    report: dict[str, object] = {
        "schema": REPORT_SCHEMA,
        "packet_id": PACKET_ID,
        "spec_digest": SPEC_DIGEST,
        "protocol_digest": EVALUATION_PROTOCOL_DIGEST,
        "corpus_digest": corpus_digest(case_tuple),
        "status": status,
        "required_arms": list(arm_names),
        "seeds": list(FROZEN_HASH_SEEDS),
        "case_ids": list(case_ids),
        "arms": arms,
        "failures": failures,
        "comparisons": comparisons,
        "conclusion": conclusion,
    }
    validate_report(
        report,
        expected_corpus_digest=report["corpus_digest"],
        expected_case_ids=case_ids,
    )
    return report


def synthetic_role_binding_construct() -> dict[str, object]:
    """Frozen algebraic construct: structure separates a cosine tie.

    This establishes construct validity only.  It is not a retrieval-effect
    estimate and cannot support a scientific decision; ``sealed_eval`` only
    validates structure.
    """

    spec = default_spec(seed=11)
    encoder = TensorProductEncoder(spec)
    filler = "parse record schema"
    digest = canonical_source_digest(filler)

    def tensor(fields: RoleFields, source_id: str, plane: str):
        return encoder.encode(
            fields,
            source_id=source_id,
            source_digest=digest,
            revision="synthetic-frozen-revision",
            plane=plane,
        ).tensor

    kernel = frozen_kernel(spec)
    query = tensor(RoleFields(path=filler), "query-path", "code")
    bound_match = tensor(RoleFields(symbol=filler), "match-symbol", "code")
    bag_decoy = tensor(RoleFields(neighbor=filler), "decoy-neighbor", "type")
    match_cosine = flattened_cosine(query, bound_match)
    decoy_cosine = flattened_cosine(query, bag_decoy)
    match_structured = normalized_structured_score(query, bound_match, kernel)
    decoy_structured = normalized_structured_score(query, bag_decoy, kernel)
    return {
        "schema": "forest-v2.tensor-role-binding-construct/1",
        "claim_scope": "construct-validity-only",
        "backend_id": encoder.backend.backend_id,
        "spec_id": spec.spec_id,
        "automatic_promotions": 0,
        "cosine": {"bound_match": match_cosine, "bag_decoy": decoy_cosine},
        "structured": {
            "bound_match": match_structured,
            "bag_decoy": decoy_structured,
        },
        "cosine_tie": math.isclose(match_cosine, decoy_cosine, abs_tol=1e-12),
        "structured_separates": match_structured > decoy_structured,
    }


__all__ = [
    "BenchmarkCase",
    "benchmark_case_key",
    "DEFAULT_RETRIEVERS",
    "NEGATIVE_CONTROLS",
    "PRIMARY_ARM",
    "REFERENCE_ARM",
    "REQUIRED_ARM_NAMES",
    "TENSOR_RETRIEVER_TYPES",
    "VECTOR_EQUIVALENT_ARM",
    "corpus_digest",
    "run_benchmark",
    "synthetic_role_binding_construct",
]
