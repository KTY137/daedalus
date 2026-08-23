"""Recall@k and MRR over a frozen gold set.

Both a macro and a micro recall are reported, because they answer different
questions and quoting only the flattering one is exactly the habit this
harness exists to prevent:

* **macro** averages the per-case recall, so every case counts once
  regardless of how many files it touched;
* **micro** pools gold paths, so a five-file case counts five times.

MRR is bounded by the largest cutoff (``MRR@max_k``): a gold file that never
appears inside the measured window contributes 0, not a tiny tail value the
run never actually looked at.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple


@dataclass(frozen=True)
class CaseScore:
    """What one retriever scored on one case."""

    case_id: str
    gold_total: int
    hits_at: Dict[int, int]
    first_hit_rank: int | None
    reciprocal_rank: float

    def recall_at(self, k: int) -> float:
        return self.hits_at[k] / self.gold_total if self.gold_total else 0.0


def score_case(
    case_id: str,
    ranking: Sequence[str],
    gold: Sequence[str],
    cutoffs: Sequence[int],
) -> CaseScore:
    gold_set = set(gold)
    hits_at = {k: len(gold_set & set(ranking[:k])) for k in cutoffs}
    first_rank = next(
        (i + 1 for i, path in enumerate(ranking) if path in gold_set), None
    )
    max_k = max(cutoffs) if cutoffs else 0
    rr = 1.0 / first_rank if first_rank is not None and first_rank <= max_k else 0.0
    return CaseScore(
        case_id=case_id,
        gold_total=len(gold_set),
        hits_at=hits_at,
        first_hit_rank=first_rank,
        reciprocal_rank=rr,
    )


@dataclass(frozen=True)
class Aggregate:
    """Pooled result for one retriever on one query variant."""

    retriever: str
    variant: str
    cases: int
    gold_total: int
    hits_at: Dict[int, int]
    macro_recall_at: Dict[int, float]
    micro_recall_at: Dict[int, float]
    mrr: float
    cases_with_any_hit: int
    median_first_hit_rank: float | None

    def as_dict(self) -> Dict[str, object]:
        return {
            "retriever": self.retriever,
            "variant": self.variant,
            "cases": self.cases,
            "gold_total": self.gold_total,
            "hits_at": {str(k): v for k, v in sorted(self.hits_at.items())},
            "macro_recall_at": {
                str(k): round(v, 4) for k, v in sorted(self.macro_recall_at.items())
            },
            "micro_recall_at": {
                str(k): round(v, 4) for k, v in sorted(self.micro_recall_at.items())
            },
            "mrr": round(self.mrr, 4),
            "cases_with_any_hit": self.cases_with_any_hit,
            "median_first_hit_rank": self.median_first_hit_rank,
        }


def _median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2


def aggregate(
    retriever: str,
    variant: str,
    scores: Sequence[CaseScore],
    cutoffs: Sequence[int],
) -> Aggregate:
    n = len(scores)
    gold_total = sum(s.gold_total for s in scores)
    hits_at = {k: sum(s.hits_at[k] for s in scores) for k in cutoffs}
    macro = {
        k: (sum(s.recall_at(k) for s in scores) / n if n else 0.0) for k in cutoffs
    }
    micro = {k: (hits_at[k] / gold_total if gold_total else 0.0) for k in cutoffs}
    max_k = max(cutoffs) if cutoffs else 0
    ranks: List[float] = [
        float(s.first_hit_rank)
        for s in scores
        if s.first_hit_rank is not None and s.first_hit_rank <= max_k
    ]
    return Aggregate(
        retriever=retriever,
        variant=variant,
        cases=n,
        gold_total=gold_total,
        hits_at=hits_at,
        macro_recall_at=macro,
        micro_recall_at=micro,
        mrr=(sum(s.reciprocal_rank for s in scores) / n if n else 0.0),
        cases_with_any_hit=sum(1 for s in scores if s.reciprocal_rank > 0),
        median_first_hit_rank=_median(ranks),
    )


def raw_table(aggregates: Sequence[Aggregate], cutoffs: Sequence[int]) -> str:
    """Render the RAW numbers, counts first, ratios second."""
    head = ["retriever", "variant"]
    head += [f"R@{k} (hits/gold)" for k in cutoffs]
    head += [f"macro R@{k}" for k in cutoffs]
    head += ["MRR", "hit cases", "med. rank"]
    lines = ["| " + " | ".join(head) + " |"]
    lines.append("| " + " | ".join(["---"] * len(head)) + " |")
    for agg in aggregates:
        row = [agg.retriever, agg.variant]
        row += [f"{agg.hits_at[k]}/{agg.gold_total}" for k in cutoffs]
        row += [f"{agg.macro_recall_at[k]:.3f}" for k in cutoffs]
        row += [
            f"{agg.mrr:.3f}",
            f"{agg.cases_with_any_hit}/{agg.cases}",
            "-" if agg.median_first_hit_rank is None else f"{agg.median_first_hit_rank:g}",
        ]
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)
