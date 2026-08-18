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
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .criteria import (
    INCONCLUSIVE,
    KEEP,
    KILL,
    NOT_EVALUABLE,
    UNDECIDABLE,
    EvalConfig,
    Finding,
    register_entries,
)
from .plan_register import RegisterCheck, verify_quietly
from .plane_range import CrossTab, crosstab, render_crosstab
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
    #: criteria this run *could* have decided and did not, because it did not
    #: carry the arms.  Distinct from the criteria this input schema can never
    #: decide: those are a limit of the instrument, these are a hole in the run.
    uninstrumented: Tuple[str, ...] = ()
    #: criteria whose data could never decide them, at any sample size.  Kept
    #: apart from ``uninstrumented``: shipping the missing arm fixes that one,
    #: and fixes nothing here.
    undecidable: Tuple[str, ...] = ()


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
    #: (arm_id, role, notes) for every arm. Criteria select arms by *role*, so
    #: a role label is all that stands between "cross-plane fusion" and
    #: whatever the run actually measured. Printing what each label was
    #: attached to is the only thing here that can expose a substituted
    #: comparator; the evaluator itself cannot know.
    arms: Tuple[Tuple[str, str, str], ...] = ()
    #: the 1:1 comparison of the criteria register against the living plan;
    #: None when the plan was not reachable, which the report says in words
    #: rather than printing an unverified denominator as if it were checked.
    register: Optional[RegisterCheck] = None

    #: the gold-label plane x arm-reach cross-tab, printed before any number
    crosstab: Optional[CrossTab] = None

    @property
    def coverage(self) -> Tuple[int, int]:
        """(decided, total) -- both counted, neither a constant.

        The total is the size of the criteria register, which
        ``plan_register`` checks against the plan bullet for bullet.  The
        earlier version of this slice published 60% because its register had
        lost a criterion and the denominator shrank with it.

        UNDECIDABLE does not count as decided.  It used to be able to: an
        undecidable criterion that reported a number inflated this fraction
        *and* the confidence in it at the same time.
        """
        decided = sum(
            1 for f in self.findings
            if f.verdict not in (NOT_EVALUABLE, UNDECIDABLE)
        )
        return decided, len(self.findings)

    @property
    def verdict_counts(self) -> Dict[str, int]:
        counts = {v: 0 for v in (KEEP, KILL, INCONCLUSIVE, UNDECIDABLE, NOT_EVALUABLE)}
        for f in self.findings:
            counts[f.verdict] = counts.get(f.verdict, 0) + 1
        return counts

    @property
    def coverage_fraction(self) -> float:
        decided, total = self.coverage
        return (decided / total) if total else 0.0


def roll_up(findings: Sequence[Finding]) -> List[PriorVerdict]:
    by_prior: Dict[str, List[Finding]] = {}
    for f in findings:
        by_prior.setdefault(f.prior, []).append(f)
    out: List[PriorVerdict] = []
    for prior in sorted(by_prior):
        group = by_prior[prior]
        decidable = [
            f for f in group if f.verdict not in (NOT_EVALUABLE, UNDECIDABLE)
        ]
        killed = tuple(f.plan_ref for f in decidable if f.verdict == KILL)
        # A criterion this evaluator implements, that this run left unasked
        # because it shipped no control arm for it.  Not the same thing as a
        # criterion the input schema can never carry.
        gaps = tuple(
            f.plan_ref for f in group if f.verdict == NOT_EVALUABLE and f.missing
        )
        # A criterion whose input could never decide it.  Shipping an arm
        # fixes a gap; nothing about this run's size fixes one of these.
        undecidable = tuple(f.plan_ref for f in group if f.verdict == UNDECIDABLE)
        if not decidable and undecidable:
            verdict = UNDECIDABLE
            rationale = (
                f"no criterion for this prior could be decided, and "
                f"{len(undecidable)} of them ({', '.join(undecidable)}) could not be "
                f"decided by this data at any sample size -- the object the criterion "
                f"names, or the observation that would separate the arms, is absent "
                f"from the input. A larger run of the same data would only narrow the "
                f"intervals around a comparison that cannot move"
            )
        elif not decidable:
            verdict = NOT_EVALUABLE
            rationale = "no criterion for this prior could be decided from this run"
        elif killed:
            verdict = KILL
            rationale = (
                f"{len(killed)} kill criterion/criteria fired ({', '.join(killed)}); "
                f"the plan stops or redesigns the track on any single one"
            )
        elif all(f.verdict == KEEP for f in decidable) and (gaps or undecidable):
            # Otherwise a prior survives by being under-instrumented: ship a
            # run without the rewiring control, the ablations or the
            # token-matched arm and every criterion that could have killed it
            # is silently absent from the denominator.  Omission is not a pass.
            # An UNDECIDABLE is the harder version of the same thing -- not a
            # missing arm, a missing observation -- so it is named separately
            # and never folded into the gaps.
            verdict = INCONCLUSIVE
            parts = [
                f"all {len(decidable)} criteria this run could decide passed, but "
                f"the prior was not tested where it is weakest"
            ]
            if gaps:
                parts.append(
                    f"{len(gaps)} implemented criteria ({', '.join(gaps)}) were never "
                    f"asked -- the run carries no control arm for them"
                )
            if undecidable:
                parts.append(
                    f"{len(undecidable)} ({', '.join(undecidable)}) were UNDECIDABLE: "
                    f"this data cannot decide them at any sample size, so shipping a "
                    f"bigger run of it would change nothing"
                )
            rationale = "; ".join(parts)
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
            PriorVerdict(
                prior, verdict, len(decidable), len(group), killed, rationale, gaps,
                undecidable,
            )
        )
    return out


def build(
    rs: ResultSet,
    findings: Sequence[Finding],
    cfg: EvalConfig,
    register: Optional[RegisterCheck] = None,
) -> Report:
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
        arms=tuple((a.arm_id, a.role, a.notes) for a in rs.arms),
        register=register if register is not None else verify_quietly(register_entries()),
        crosstab=crosstab(rs),
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
        "arms": [
            {"arm_id": arm_id, "role": role, "notes": notes}
            for arm_id, role, notes in rep.arms
        ],
        "config": {
            "margin": rep.config.margin,
            "confidence": rep.config.confidence,
            "resamples": rep.config.resamples,
            "seed": rep.config.seed,
            "min_cases": rep.config.min_cases,
            "min_seeds": rep.config.min_seeds,
            "budget_tolerance": rep.config.budget_tolerance,
        },
        "coverage": {
            "decided": rep.coverage[0],
            "criteria": rep.coverage[1],
            "fraction": rep.coverage_fraction,
        },
        "verdict_counts": rep.verdict_counts,
        "dynamic_range": _crosstab_json(rep.crosstab),
        "register": _register_json(rep.register),
        "priors": [
            {
                "prior": p.prior,
                "verdict": p.verdict,
                "decided": p.decided,
                "total": p.total,
                "killed_by": list(p.killed_by),
                "uninstrumented": list(p.uninstrumented),
                "undecidable": list(p.undecidable),
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


def _crosstab_json(ct: Optional[CrossTab]) -> Dict[str, object]:
    """The cross-tab, machine-readable, next to the numbers it licenses."""
    if ct is None:
        return {"gold_planes_declared": False, "rows": []}
    return {
        "gold_planes_declared": ct.gold_planes_declared,
        "cases": ct.cases,
        "cases_without_a_declared_gold_plane": ct.unlabelled,
        "planes_never_a_retrieval_target": list(ct.never_targeted()),
        "rows": [
            {
                "plane": r.plane,
                "documents": r.documents,
                "gold_labels": r.gold_labels,
                "arms": {
                    arm_id: {"in_index_scope": can, "documents_returned": got}
                    for arm_id, (can, got) in r.per_arm.items()
                },
            }
            for r in ct.rows
        ],
    }


def _register_json(check: Optional[RegisterCheck]) -> Dict[str, object]:
    """Provenance for the coverage denominator, stated rather than assumed."""
    if check is None:
        return {
            "verified": False,
            "reason": (
                "the master plan was not reachable from this process; the "
                "denominator below is this package's own register and has not "
                "been checked against the living plan"
            ),
        }
    return {
        "verified": check.ok,
        "plan_path": check.section.plan_path,
        "plan_sha256": check.section.plan_digest,
        "plan_section": check.section.section,
        "bullets_in_plan": check.n_extracted,
        "criteria_registered": check.n_registered,
        "mismatches": list(check.mismatches),
    }


_MARK = {
    KEEP: "[KEEP]",
    KILL: "[KILL]",
    INCONCLUSIVE: "[????]",
    UNDECIDABLE: "[XXXX]",
    NOT_EVALUABLE: "[ -- ]",
}


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
    add(
        f"coverage         {decided} of {total} plan criteria decidable from this "
        f"run ({100.0 * rep.coverage_fraction:.1f}%)"
    )
    counts = rep.verdict_counts
    add(
        "verdicts         "
        + "  ".join(f"{name} {counts[name]}" for name in (
            KEEP, KILL, INCONCLUSIVE, UNDECIDABLE, NOT_EVALUABLE
        ))
    )
    chk = rep.register
    if chk is None:
        add(
            "register         NOT VERIFIED -- the master plan was not reachable; "
            "the denominator above is unchecked"
        )
    elif chk.ok:
        add(
            f"register         verified 1:1 against {chk.section.plan_path} "
            f"section {chk.section.section}"
        )
        add(
            f"                 ({chk.n_extracted} bullets, plan sha256 "
            f"{chk.section.plan_digest[:12]})"
        )
    else:
        add(
            f"register         MISMATCH against the living plan "
            f"({len(chk.mismatches)} problem(s)) -- the coverage figure is unsound"
        )
        for problem in chk.mismatches:
            for part in problem.splitlines():
                for line in _wrap(part, 72):
                    add("                 " + line)
    add("")
    if rep.arms:
        add("-" * 78)
        add("ARMS AS LABELLED  (criteria select by role -- check the labels)")
        add("-" * 78)
        for arm_id, role, notes in rep.arms:
            add(f"  {role:18s} {arm_id}")
            for line in _wrap(notes, 68):
                add("       " + line)
        add("")
    if rep.crosstab is not None:
        add("-" * 78)
        for line in render_crosstab(rep.crosstab):
            add(line)
        add("")
    add("-" * 78)
    add("PREJUDICE PER PRIOR")
    add("-" * 78)
    for p in rep.priors:
        add(f"{_MARK[p.verdict]} {p.prior}  ({p.decided}/{p.total} decidable)")
        for line in _wrap(p.rationale, 74):
            add("      " + line)
        if p.uninstrumented:
            for line in _wrap(
                "not asked by this run (no control arm shipped): "
                + ", ".join(p.uninstrumented), 74
            ):
                add("      " + line)
        if p.undecidable:
            for line in _wrap(
                "UNDECIDABLE on this data at any sample size: "
                + ", ".join(p.undecidable), 74
            ):
                add("      " + line)
    add("")
    add("-" * 78)
    add("CRITERIA")
    add("-" * 78)
    for f in rep.findings:
        add(f"{_MARK[f.verdict]} {f.plan_ref}  {f.key}  {f.verdict}")
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
    add("")
    add("UNDECIDABLE is not INCONCLUSIVE. INCONCLUSIVE says this data could have")
    add("decided and did not, so a larger run would help. UNDECIDABLE says this")
    add("data could never decide it: the object the criterion names, or the")
    add("observation that separates the two arms, is not in the input. Enlarging")
    add("such a run shrinks the interval around a comparison that cannot move,")
    add("which walks towards a verdict without measuring anything.")
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
