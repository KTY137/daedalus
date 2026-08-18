"""The honest rollup: per-criterion findings into a per-prior prejudice.

"Prejudice" is the right word and is used deliberately.  This report is
**advisory**.  It gates nothing, promotes nothing, blocks nothing, and has
no write path.  Master plan invariant 5 keeps promotion sealed behind owner
approval, and section 15 says a kill result is archived evidence plus an
amendment proposal -- never an automatic deletion.  A KILL here means "the
measured evidence says open an amendment", and a human still opens it.

The rollup rule per prior is deliberately asymmetric, because the costs are
asymmetric: one fired kill criterion outranks any number of passes (the
plan says *any* of the listed outcomes stops the track), while a KEEP
requires that every decidable criterion for that prior passed.  Anything
else is INCONCLUSIVE, which is a real answer and not a soft KEEP.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Sequence, Tuple

from .criteria import (
    INCONCLUSIVE,
    KEEP,
    KILL,
    NOT_EVALUABLE,
    EvalConfig,
    Finding,
)
from .schema import ResultSet, roles_present

BANNER = (
    "ADVISORY -- this report gates nothing, promotes nothing and blocks nothing. "
    "A KILL is a proposal to open an amendment (plan section 15), not an action."
)


@dataclass(frozen=True)
class PriorVerdict:
    prior: str
    verdict: str
    decided: int
    total: int
    killed_by: Tuple[str, ...]
    rationale: str


@dataclass(frozen=True)
class Report:
    run_id: str
    source: str
    primary_metric: str
    n_cases: int
    seeds: int
    config: EvalConfig
    findings: Tuple[Finding, ...]
    priors: Tuple[PriorVerdict, ...]
    roles: Tuple[str, ...]

    @property
    def coverage(self) -> Tuple[int, int]:
        decided = sum(1 for f in self.findings if f.verdict != NOT_EVALUABLE)
        return decided, len(self.findings)


def roll_up(findings: Sequence[Finding]) -> List[PriorVerdict]:
    by_prior: Dict[str, List[Finding]] = {}
    for f in findings:
        by_prior.setdefault(f.prior, []).append(f)
    out: List[PriorVerdict] = []
    for prior in sorted(by_prior):
        group = by_prior[prior]
        decidable = [f for f in group if f.verdict != NOT_EVALUABLE]
        killed = tuple(f.plan_ref for f in decidable if f.verdict == KILL)
        if not decidable:
            verdict = NOT_EVALUABLE
            rationale = "no criterion for this prior could be decided from this run"
        elif killed:
            verdict = KILL
            rationale = (
                f"{len(killed)} kill criterion/criteria fired ({', '.join(killed)}); "
                f"the plan stops or redesigns the track on any single one"
            )
        elif all(f.verdict == KEEP for f in decidable):
            verdict = KEEP
            rationale = (
                f"all {len(decidable)} decidable criteria passed; the prior survives "
                f"this run (it is not thereby proven)"
            )
        else:
            n_inc = sum(1 for f in decidable if f.verdict == INCONCLUSIVE)
            verdict = INCONCLUSIVE
            rationale = (
                f"{n_inc} of {len(decidable)} decidable criteria could not be called; "
                f"this is not a pass"
            )
        out.append(
            PriorVerdict(prior, verdict, len(decidable), len(group), killed, rationale)
        )
    return out


def build(rs: ResultSet, findings: Sequence[Finding], cfg: EvalConfig) -> Report:
    return Report(
        run_id=rs.run_id,
        source=rs.source,
        primary_metric=rs.primary_metric,
        n_cases=len(rs.cases),
        seeds=rs.seeds,
        config=cfg,
        findings=tuple(findings),
        priors=tuple(roll_up(findings)),
        roles=tuple(roles_present(rs)),
    )


def to_json(rep: Report) -> Dict[str, object]:
    return {
        "advisory": True,
        "banner": BANNER,
        "run_id": rep.run_id,
        "source": rep.source,
        "primary_metric": rep.primary_metric,
        "n_cases": rep.n_cases,
        "seeds": rep.seeds,
        "roles_present": list(rep.roles),
        "config": {
            "margin": rep.config.margin,
            "confidence": rep.config.confidence,
            "resamples": rep.config.resamples,
            "seed": rep.config.seed,
            "min_cases": rep.config.min_cases,
            "min_seeds": rep.config.min_seeds,
            "budget_tolerance": rep.config.budget_tolerance,
        },
        "coverage": {"decided": rep.coverage[0], "criteria": rep.coverage[1]},
        "priors": [
            {
                "prior": p.prior,
                "verdict": p.verdict,
                "decided": p.decided,
                "total": p.total,
                "killed_by": list(p.killed_by),
                "rationale": p.rationale,
            }
            for p in rep.priors
        ],
        "findings": [
            {
                "key": f.key,
                "plan_ref": f.plan_ref,
                "prior": f.prior,
                "statement": f.statement,
                "verdict": f.verdict,
                "rationale": f.rationale,
                "warnings": list(f.warnings),
                "missing": list(f.missing),
                "comparisons": [
                    {
                        "label": c.label,
                        "treatment": c.treatment,
                        "baseline": c.baseline,
                        "n": c.n,
                        "mean_treatment": c.mean_treatment,
                        "mean_baseline": c.mean_baseline,
                        "mean_diff": c.mean_diff,
                        "ci_low": c.ci_low,
                        "ci_high": c.ci_high,
                        "confidence": c.confidence,
                        "margin": c.margin,
                        "wins": c.wins,
                        "losses": c.losses,
                        "ties": c.ties,
                        "stdev_diff": c.stdev_diff,
                        "state": c.state,
                    }
                    for c in f.comparisons
                ],
            }
            for f in rep.findings
        ],
    }


_MARK = {KEEP: "[KEEP]", KILL: "[KILL]", INCONCLUSIVE: "[????]", NOT_EVALUABLE: "[ -- ]"}


def render(rep: Report) -> str:
    """Plain-ASCII text report (Windows consoles are not UTF-8 by default)."""
    w: List[str] = []
    add = w.append
    add("=" * 78)
    add("Forest v2 kill-criteria evaluation (master plan section 14)")
    add("=" * 78)
    for line in _wrap(BANNER, 78):
        add(line)
    add("")
    add(f"run              {rep.run_id}")
    if rep.source:
        add(f"source           {rep.source}")
    add(f"primary metric   {rep.primary_metric}   (declared in the input, not chosen here)")
    add(f"cases / seeds    {rep.n_cases} / {rep.seeds}")
    add(f"roles present    {', '.join(rep.roles) if rep.roles else '(none)'}")
    cfg = rep.config
    add(
        f"decision rule    CI{int(cfg.confidence * 100)} percentile bootstrap "
        f"({cfg.resamples} resamples, seed {cfg.seed}), "
        f"equivalence margin +/-{cfg.margin}, min_cases {cfg.min_cases}"
    )
    decided, total = rep.coverage
    add(f"coverage         {decided} of {total} plan criteria decidable from this run")
    add("")
    add("-" * 78)
    add("PREJUDICE PER PRIOR")
    add("-" * 78)
    for p in rep.priors:
        add(f"{_MARK[p.verdict]} {p.prior}  ({p.decided}/{p.total} decidable)")
        for line in _wrap(p.rationale, 74):
            add("      " + line)
    add("")
    add("-" * 78)
    add("CRITERIA")
    add("-" * 78)
    for f in rep.findings:
        add(f"{_MARK[f.verdict]} {f.plan_ref}  {f.key}")
        for line in _wrap('"' + f.statement + '"', 72):
            add("       " + line)
        for line in _wrap(f.rationale, 72):
            add("       " + line)
        for c in f.comparisons:
            add(f"         {c.describe()}")
        for warn in f.warnings:
            for i, line in enumerate(_wrap(warn, 68)):
                add(("       ! " if i == 0 else "         ") + line)
        if f.missing:
            add(f"       missing: {', '.join(f.missing)}")
        add("")
    add("-" * 78)
    add("Absence of a difference is not evidence of equivalence: an INCONCLUSIVE")
    add("verdict means the run was too small or too noisy to decide, and must not")
    add("be read as a pass. Underpowered and budget-asymmetric comparisons are")
    add("withheld rather than reported as results.")
    add("-" * 78)
    return "\n".join(w)


def _wrap(text: str, width: int) -> List[str]:
    words, lines, cur = text.split(), [], ""
    for word in words:
        if cur and len(cur) + 1 + len(word) > width:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}" if cur else word
    if cur:
        lines.append(cur)
    return lines or [""]
