"""Deterministic gold evaluation for knowledge-to-Fourfold correlation.

This report answers whether a correlation result is useful and safe on a named
fixture.  It is not a Gate-2 closure artifact and it does not grade generated
code.  It measures only the correlation layer against content-addressed gold
cases, including negative expectations and abstention behavior.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, ClassVar, Sequence

from ..spine.envelope import canonical_sha
from .knowledge_correlation import (
    KnowledgeCorrelationError,
    KnowledgeCorrelationResult,
)
from .knowledge_sources import PROJECT_AUTHORITY_CLASSES


def _sha(value: str, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise KnowledgeCorrelationError(f"{label} must be sha256")
    try:
        int(value, 16)
    except ValueError as exc:
        raise KnowledgeCorrelationError(f"{label} must be sha256") from exc
    return value.lower()


def _strings(values: Sequence[str], label: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise KnowledgeCorrelationError(f"{label} must be a sequence")
    result = tuple(sorted(set(values)))
    if any(not isinstance(value, str) or not value.strip() for value in result):
        raise KnowledgeCorrelationError(f"{label} contains an invalid string")
    return result


@dataclass(frozen=True)
class CorrelationGoldCase:
    case_id: str
    claim_sha256: str
    required_node_ids: tuple[str, ...] = ()
    forbidden_node_ids: tuple[str, ...] = ()
    required_contradiction_kinds: tuple[str, ...] = ()
    required_unresolved_mentions: tuple[str, ...] = ()
    allow_extra_node_ids: bool = False

    SCHEMA: ClassVar[str] = "daedalus-knowledge-correlation-gold-case/1"

    def __post_init__(self) -> None:
        if not isinstance(self.case_id, str) or not self.case_id.strip():
            raise KnowledgeCorrelationError("gold case_id must not be empty")
        object.__setattr__(self, "claim_sha256", _sha(self.claim_sha256, "claim_sha256"))
        for name in (
            "required_node_ids",
            "forbidden_node_ids",
            "required_contradiction_kinds",
            "required_unresolved_mentions",
        ):
            object.__setattr__(self, name, _strings(getattr(self, name), name))
        overlap = set(self.required_node_ids).intersection(self.forbidden_node_ids)
        if overlap:
            raise KnowledgeCorrelationError(
                f"gold case requires and forbids the same nodes: {sorted(overlap)}"
            )
        if not (
            self.required_node_ids
            or self.forbidden_node_ids
            or self.required_contradiction_kinds
            or self.required_unresolved_mentions
        ):
            raise KnowledgeCorrelationError("gold case must assert at least one outcome")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "case_id": self.case_id,
            "claim_sha256": self.claim_sha256,
            "required_node_ids": list(self.required_node_ids),
            "forbidden_node_ids": list(self.forbidden_node_ids),
            "required_contradiction_kinds": list(self.required_contradiction_kinds),
            "required_unresolved_mentions": list(self.required_unresolved_mentions),
            "allow_extra_node_ids": self.allow_extra_node_ids,
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class CorrelationCaseEvaluation:
    case_id: str
    claim_sha256: str
    predicted_node_ids: tuple[str, ...]
    true_positive_node_ids: tuple[str, ...]
    false_positive_node_ids: tuple[str, ...]
    missing_node_ids: tuple[str, ...]
    forbidden_hits: tuple[str, ...]
    observed_contradiction_kinds: tuple[str, ...]
    missing_contradiction_kinds: tuple[str, ...]
    observed_unresolved_mentions: tuple[str, ...]
    missing_unresolved_mentions: tuple[str, ...]
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "claim_sha256": self.claim_sha256,
            "predicted_node_ids": list(self.predicted_node_ids),
            "true_positive_node_ids": list(self.true_positive_node_ids),
            "false_positive_node_ids": list(self.false_positive_node_ids),
            "missing_node_ids": list(self.missing_node_ids),
            "forbidden_hits": list(self.forbidden_hits),
            "observed_contradiction_kinds": list(self.observed_contradiction_kinds),
            "missing_contradiction_kinds": list(self.missing_contradiction_kinds),
            "observed_unresolved_mentions": list(self.observed_unresolved_mentions),
            "missing_unresolved_mentions": list(self.missing_unresolved_mentions),
            "blockers": list(self.blockers),
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class KnowledgeCorrelationEvaluationReport:
    result_sha256: str
    gold_sha256: str
    cases: tuple[CorrelationCaseEvaluation, ...]
    true_positives: int
    false_positives: int
    false_negatives: int
    forbidden_hits: int
    precision: float
    recall: float
    contradiction_recall: float
    unresolved_recall: float
    authority_escalations: int
    blockers: tuple[str, ...]
    closed: bool

    SCHEMA: ClassVar[str] = "daedalus-knowledge-correlation-evaluation/1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "result_sha256", _sha(self.result_sha256, "result_sha256"))
        object.__setattr__(self, "gold_sha256", _sha(self.gold_sha256, "gold_sha256"))
        for name in (
            "true_positives",
            "false_positives",
            "false_negatives",
            "forbidden_hits",
            "authority_escalations",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise KnowledgeCorrelationError(f"{name} must be a non-negative integer")
        for name in ("precision", "recall", "contradiction_recall", "unresolved_recall"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise KnowledgeCorrelationError(f"{name} must be in [0, 1]")
            object.__setattr__(self, name, round(value, 6))
        ordered = tuple(sorted(set(self.blockers)))
        object.__setattr__(self, "blockers", ordered)
        if self.closed != (not ordered):
            raise KnowledgeCorrelationError("evaluation closed flag must equal empty blocker set")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "result_sha256": self.result_sha256,
            "gold_sha256": self.gold_sha256,
            "cases": [case.to_dict() for case in self.cases],
            "metrics": {
                "true_positives": self.true_positives,
                "false_positives": self.false_positives,
                "false_negatives": self.false_negatives,
                "forbidden_hits": self.forbidden_hits,
                "precision": self.precision,
                "recall": self.recall,
                "contradiction_recall": self.contradiction_recall,
                "unresolved_recall": self.unresolved_recall,
                "authority_escalations": self.authority_escalations,
            },
            "blockers": list(self.blockers),
            "closed": self.closed,
            "gate_closure_claimed": False,
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def _ratio(found: int, required: int) -> float:
    return 1.0 if required == 0 else found / required


def evaluate_knowledge_correlation(
    result: KnowledgeCorrelationResult,
    cases: Sequence[CorrelationGoldCase],
    *,
    minimum_precision: float = 1.0,
    minimum_recall: float = 1.0,
    minimum_contradiction_recall: float = 1.0,
    minimum_unresolved_recall: float = 1.0,
) -> KnowledgeCorrelationEvaluationReport:
    """Evaluate exact claims against positive and negative gold expectations."""

    thresholds = {
        "precision": minimum_precision,
        "recall": minimum_recall,
        "contradiction_recall": minimum_contradiction_recall,
        "unresolved_recall": minimum_unresolved_recall,
    }
    for name, value in thresholds.items():
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise KnowledgeCorrelationError(f"{name} threshold must be in [0, 1]")
    gold = tuple(sorted(cases, key=lambda case: case.case_id))
    if not gold:
        raise KnowledgeCorrelationError("evaluation requires at least one gold case")
    if len({case.case_id for case in gold}) != len(gold):
        raise KnowledgeCorrelationError("gold case ids must be unique")
    if len({case.claim_sha256 for case in gold}) != len(gold):
        raise KnowledgeCorrelationError("one claim may appear in only one gold case")

    bundles = {bundle.claim.digest: bundle for bundle in result.bundles}
    case_results: list[CorrelationCaseEvaluation] = []
    tp = fp = fn = forbidden_total = 0
    contradiction_required = contradiction_found = 0
    unresolved_required = unresolved_found = 0
    blockers: list[str] = []

    for case in gold:
        bundle = bundles.get(case.claim_sha256)
        if bundle is None:
            case_blockers = (f"{case.case_id}: claim missing from result",)
            predicted: set[str] = set()
            observed_contradictions: set[str] = set()
            observed_unresolved: set[str] = set()
        else:
            case_blockers = ()
            predicted = {proposal.target_node_id for proposal in bundle.proposals}
            observed_contradictions = {item.kind for item in bundle.contradictions}
            observed_unresolved = {item.mention for item in bundle.unresolved}

        required = set(case.required_node_ids)
        forbidden = set(case.forbidden_node_ids)
        true_positive = required.intersection(predicted)
        missing = required - predicted
        forbidden_hits = forbidden.intersection(predicted)
        false_positive = set()
        if not case.allow_extra_node_ids:
            false_positive = predicted - required
        missing_contradictions = set(case.required_contradiction_kinds) - observed_contradictions
        missing_unresolved = set(case.required_unresolved_mentions) - observed_unresolved

        case_blocker_list = list(case_blockers)
        case_blocker_list.extend(
            f"{case.case_id}: missing node {node_id}" for node_id in sorted(missing)
        )
        case_blocker_list.extend(
            f"{case.case_id}: forbidden node {node_id}" for node_id in sorted(forbidden_hits)
        )
        case_blocker_list.extend(
            f"{case.case_id}: unexpected node {node_id}" for node_id in sorted(false_positive)
        )
        case_blocker_list.extend(
            f"{case.case_id}: missing contradiction {kind}"
            for kind in sorted(missing_contradictions)
        )
        case_blocker_list.extend(
            f"{case.case_id}: missing unresolved mention {mention}"
            for mention in sorted(missing_unresolved)
        )
        blockers.extend(case_blocker_list)
        tp += len(true_positive)
        fp += len(false_positive)
        fn += len(missing)
        forbidden_total += len(forbidden_hits)
        contradiction_required += len(case.required_contradiction_kinds)
        contradiction_found += len(set(case.required_contradiction_kinds) & observed_contradictions)
        unresolved_required += len(case.required_unresolved_mentions)
        unresolved_found += len(set(case.required_unresolved_mentions) & observed_unresolved)
        case_results.append(
            CorrelationCaseEvaluation(
                case_id=case.case_id,
                claim_sha256=case.claim_sha256,
                predicted_node_ids=tuple(sorted(predicted)),
                true_positive_node_ids=tuple(sorted(true_positive)),
                false_positive_node_ids=tuple(sorted(false_positive)),
                missing_node_ids=tuple(sorted(missing)),
                forbidden_hits=tuple(sorted(forbidden_hits)),
                observed_contradiction_kinds=tuple(sorted(observed_contradictions)),
                missing_contradiction_kinds=tuple(sorted(missing_contradictions)),
                observed_unresolved_mentions=tuple(sorted(observed_unresolved)),
                missing_unresolved_mentions=tuple(sorted(missing_unresolved)),
                blockers=tuple(sorted(case_blocker_list)),
            )
        )

    authority_escalations = sum(
        1
        for proposal in result.proposals
        if proposal.eligible_for_verification
        and proposal.source_authority not in PROJECT_AUTHORITY_CLASSES
    )
    if authority_escalations:
        blockers.append(
            f"authority escalation: {authority_escalations} non-project proposals became verification-eligible"
        )

    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    contradiction_recall = _ratio(contradiction_found, contradiction_required)
    unresolved_recall = _ratio(unresolved_found, unresolved_required)
    for name, actual in (
        ("precision", precision),
        ("recall", recall),
        ("contradiction_recall", contradiction_recall),
        ("unresolved_recall", unresolved_recall),
    ):
        if actual < thresholds[name]:
            blockers.append(
                f"{name} below threshold: {actual:.6f} < {thresholds[name]:.6f}"
            )
    if forbidden_total:
        blockers.append(f"forbidden correlation hits: {forbidden_total}")

    gold_sha = canonical_sha([case.to_dict() for case in gold])
    unique_blockers = tuple(sorted(set(blockers)))
    return KnowledgeCorrelationEvaluationReport(
        result_sha256=result.digest,
        gold_sha256=gold_sha,
        cases=tuple(case_results),
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        forbidden_hits=forbidden_total,
        precision=precision,
        recall=recall,
        contradiction_recall=contradiction_recall,
        unresolved_recall=unresolved_recall,
        authority_escalations=authority_escalations,
        blockers=unique_blockers,
        closed=not unique_blockers,
    )


__all__ = [
    "CorrelationCaseEvaluation",
    "CorrelationGoldCase",
    "KnowledgeCorrelationEvaluationReport",
    "evaluate_knowledge_correlation",
]
