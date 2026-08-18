"""The master plan's kill criteria as machine-checkable predicates.

Section numbering note: the kill criteria are **section 14** in plan revision
5 (they were section 13 in earlier revisions; section 13 is now "Forbidden
default directions").  ``plan_ref`` below cites the live numbering.

``REGISTER`` at the foot of this module is the code's copy of that list, and
``plan_register.verify`` re-derives the same list from the living plan every
time the checks run.  A copy is allowed to exist -- the evaluator must work
on a machine that has only a result file -- but it is not allowed to be
*unchecked*, and it is never the source of a published number.  The report's
coverage is ``n_decided / n_extracted``, computed from the register, never a
literal.  (The first version of this module registered fifteen criteria for a
sixteen-bullet plan, skipped the corpus-licensing bullet entirely, and
published the resulting 9/15 = 60%.  Nine of sixteen is 56.3%.)

Nine bullets are decidable from a retrieval result set; seven are not,
because they need evidence this format does not carry (behavioural outcomes,
snapshot cost telemetry, verifier precision, Genesis conformance, corpus
licensing and provenance).  Those seven are reported as ``NOT_EVALUABLE``
with the reason, and they are *counted*, so the report can state what
fraction of the plan's kill surface a given run actually covers.  Quietly
shipping nine checks and calling it "the kill criteria" would be the
dishonest version; quietly shipping nine of sixteen and dividing by fifteen
is the same dishonesty with a decimal point.

Three guards sit in front of every verdict:

*Dynamic range.*  Before any comparison metric is reported, the gold-label
plane x arm-reach cross-tab has to show that the comparison could have come
out the other way.  When the planes that distinguish the two arms carry zero
gold labels, or an arm sits at a structural 0%/100% ceiling, or the object the
criterion names (cross-plane edges, a fusion retriever) is absent from the
input, the verdict is ``UNDECIDABLE`` and no number is printed.  See
``plane_range``; the gate is inside ``_compare_arms``, so a criterion cannot
report a comparison by forgetting to ask.

*Power.*  Fewer than ``min_cases`` paired cases and the verdict is
``INCONCLUSIVE`` regardless of what the interval says.  The plan asks for
5-10 seeds where variance matters; a kill decision taken on four noisy
cases is not a measurement.

*Budget symmetry.*  The plan requires "identical compute/token budgets".
When the arms' budgets differ, the guard asks who the asymmetry favoured:

===============  ==================  ==========================================
verdict          asymmetry favours   result
===============  ==================  ==========================================
KEEP             the treatment       downgraded -- a win bought with more budget
KEEP             the baseline        stands, and is *stronger* than measured
KILL             the treatment       stands, and is conservative
KILL             the baseline        downgraded -- the loss may be starvation
===============  ==================  ==========================================
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .plane_range import (
    RangeRefused,
    Refusal,
    cross_plane_edge_refusal,
    fusion_arm,
    range_refusal,
)
from .schema import Arm, ResultSet
from .stats import (
    DEFAULT_CONFIDENCE,
    DEFAULT_MARGIN,
    DEFAULT_RESAMPLES,
    Paired,
    compare,
)

KEEP = "KEEP"
KILL = "KILL"
INCONCLUSIVE = "INCONCLUSIVE"
NOT_EVALUABLE = "NOT_EVALUABLE"
#: The data could never decide this, at any sample size -- the object the
#: criterion names is absent from the input, or the observation that would
#: separate the two arms does not occur in it.  Kept strictly apart from
#: ``INCONCLUSIVE`` (the data could decide and did not) and from
#: ``NOT_EVALUABLE`` (the run shipped no such arm, or the format cannot carry
#: the evidence).  Conflating the three is how a category error hides: an
#: INCONCLUSIVE invites a bigger run, and a bigger run of data that contains
#: no distinguishing observation walks straight to a verdict.
UNDECIDABLE = "UNDECIDABLE"

PRIOR_TWIN = "four_plane_project_twin"
PRIOR_LATENT = "latent_cross_plane_discovery"
PRIOR_GRAPH_CTX = "graph_conditioned_context"
PRIOR_GENESIS = "genesis_motif_composition"
PRIOR_CORPUS = "repository_corpus_reuse"
PRIOR_ORCH = "orchestration_evolution"

#: The section-14 bullets, wording as the plan words them, keyed by the index
#: the plan gives them.  Checked verbatim against the living plan by
#: ``plan_register.verify``; edit only to follow the plan, never to make a
#: check pass.
PLAN_STATEMENTS: Dict[str, str] = {
    "14.1": "the full representation does not beat code-only or BM25 retrieval",
    "14.2": "degree-preserving randomized cross-plane edges perform equivalently",
    "14.3": "four independent indices perform equivalently to cross-plane fusion",
    "14.4": "a plane has no marginal contribution in ablation",
    "14.5": "graph movement does not predict or cause behavioral improvement",
    "14.6": (
        "graph-conditioned prioritization does not beat random or evaluator-only choice"
    ),
    "14.7": "the gain disappears after temporal and knowledge-leakage scrubbing",
    "14.8": "extra context tokens explain the whole gain",
    "14.9": "graph construction/query cost worsens the quality/cost frontier",
    "14.10": "revision-atomic snapshots cannot be maintained at usable cost",
    "14.11": (
        "embedding proposals cannot achieve useful precision after verification cost"
    ),
    "14.12": (
        "benefits disappear on held-out repositories, under equal context budgets, "
        "or in cross-project transfer"
    ),
    "14.13": (
        "motif composition does not outperform direct generation after equalizing "
        "model, tokens, repair budget, and evaluator access"
    ),
    "14.14": (
        "Genesis round-trip conformance fails to predict buildable, usable software"
    ),
    "14.15": (
        "corpus licensing/provenance or extraction cost prevents reproducible reuse"
    ),
    "14.16": (
        "orchestration evolution gains vanish when evaluated on unseen repositories "
        "and fixed models"
    ),
}


@dataclass(frozen=True)
class EvalConfig:
    """Everything a verdict depends on, declared before the data is seen."""

    margin: float = DEFAULT_MARGIN
    confidence: float = DEFAULT_CONFIDENCE
    resamples: int = DEFAULT_RESAMPLES
    seed: int = 20260818
    min_cases: int = 10
    min_seeds: int = 5
    budget_tolerance: float = 0.05
    cost_tolerance: float = 0.05


@dataclass(frozen=True)
class Finding:
    key: str
    plan_ref: str
    prior: str
    statement: str
    verdict: str
    rationale: str
    comparisons: Tuple[Paired, ...] = ()
    warnings: Tuple[str, ...] = ()
    missing: Tuple[str, ...] = ()


# ---------------------------------------------------------------- helpers


def _cases_for(rs: ResultSet, group: Optional[str]) -> Tuple[str, ...]:
    if group is None:
        return rs.cases
    got = rs.group(group)
    return got or ()


def _compare_arms(
    rs: ResultSet,
    cfg: EvalConfig,
    label: str,
    treat: Arm,
    base: Arm,
    cases: Sequence[str],
) -> Paired:
    """The one place a comparison metric is produced -- and its gate.

    The dynamic-range precondition is enforced here rather than in each
    criterion, so a new criterion cannot report a number by forgetting to
    ask.  ``RangeRefused`` propagates to ``evaluate``, which turns it into an
    ``UNDECIDABLE`` finding for whichever criterion raised it.
    """
    refusal = range_refusal(rs, treat, base, cases)
    if refusal is not None:
        raise RangeRefused(refusal, label)
    return compare(
        label,
        treat.arm_id,
        base.arm_id,
        [treat.scores[c] for c in cases],
        [base.scores[c] for c in cases],
        margin=cfg.margin,
        confidence=cfg.confidence,
        resamples=cfg.resamples,
        seed=cfg.seed,
    )


def _budget_favour(treat: Arm, base: Arm, cfg: EvalConfig) -> Tuple[str, str]:
    """Who did an unequal budget favour?  Returns (favour, note)."""
    t, b = treat.budget_tokens, base.budget_tokens
    if t is None or b is None:
        return ("unknown", "")
    if b <= 0 or t <= 0:
        return ("unknown", "")
    ratio = t / b
    if abs(ratio - 1.0) <= cfg.budget_tolerance:
        return ("equal", "")
    if ratio > 1.0:
        return (
            "treatment",
            f"budget asymmetry: {treat.arm_id} had {ratio:.2f}x the tokens of {base.arm_id}",
        )
    return (
        "baseline",
        f"budget asymmetry: {treat.arm_id} had {ratio:.2f}x the tokens of {base.arm_id}",
    )


def _guard(
    verdict: str,
    rationale: str,
    comps: Sequence[Paired],
    warnings: List[str],
    cfg: EvalConfig,
    favours: Sequence[str],
) -> Tuple[str, str, Tuple[str, ...]]:
    """Apply the power and budget-symmetry guards to a provisional verdict."""
    if verdict in (NOT_EVALUABLE, UNDECIDABLE):
        return verdict, rationale, tuple(warnings)

    thin = [c for c in comps if c.n < cfg.min_cases]
    if thin:
        warnings.append(
            f"underpowered: {thin[0].n} paired cases < min_cases={cfg.min_cases}; "
            f"verdict withheld"
        )
        return INCONCLUSIVE, rationale + " (withheld: too few cases to decide)", tuple(warnings)

    if verdict == KEEP and "treatment" in favours:
        warnings.append(
            "verdict downgraded: the treatment won with the larger budget, "
            "which the plan does not accept as a win"
        )
        return INCONCLUSIVE, rationale + " (withheld: unequal budget favoured the treatment)", tuple(warnings)
    if verdict == KILL and "baseline" in favours:
        warnings.append(
            "verdict downgraded: the treatment lost with the smaller budget, "
            "which is starvation rather than refutation"
        )
        return INCONCLUSIVE, rationale + " (withheld: unequal budget favoured the baseline)", tuple(warnings)
    if verdict == KILL and "treatment" in favours:
        warnings.append("kill is conservative: the treatment held the larger budget")
    if verdict == KEEP and "baseline" in favours:
        warnings.append("keep is conservative: the treatment held the smaller budget")
    return verdict, rationale, tuple(warnings)


def _missing(rs: ResultSet, needed: Sequence[str], variant: str) -> Tuple[str, ...]:
    return tuple(r for r in needed if rs.find(r, variant) is None)


def _not_evaluable(
    key: str, ref: str, prior: str, statement: str, why: str, missing: Sequence[str] = ()
) -> Finding:
    return Finding(
        key=key,
        plan_ref=ref,
        prior=prior,
        statement=statement,
        verdict=NOT_EVALUABLE,
        rationale=why,
        missing=tuple(missing),
    )


def _undecidable(
    key: str, ref: str, prior: str, statement: str, refusal: Refusal
) -> Finding:
    """The data could never decide this -- not a verdict, and not a maybe."""
    return Finding(
        key=key,
        plan_ref=ref,
        prior=prior,
        statement=statement,
        verdict=UNDECIDABLE,
        rationale=refusal.reason,
        warnings=tuple(refusal.detail),
    )


def _superiority_verdict(comps: Sequence[Paired]) -> Tuple[str, str]:
    """KEEP only when the treatment beats every baseline it was asked to beat."""
    failures = [c for c in comps if c.equivalent or c.inferior]
    undecided = [c for c in comps if c.inconclusive]
    if failures:
        worst = failures[0]
        return (
            KILL,
            f"kill condition met: {worst.treatment} does not beat {worst.baseline} "
            f"(diff {worst.mean_diff:+.4f}, CI [{worst.ci_low:+.4f},{worst.ci_high:+.4f}], "
            f"{worst.state})",
        )
    if undecided:
        return (
            INCONCLUSIVE,
            f"interval too wide to decide against {undecided[0].baseline}",
        )
    return (
        KEEP,
        "the treatment beats every required baseline with the interval clear of zero",
    )


def _equivalence_verdict(comp: Paired, control: str, kill_note: str = "") -> Tuple[str, str]:
    """KILL when a control performs equivalently (or better).

    ``kill_note`` lets a caller say what the equivalence *means* for its own
    criterion without rewriting the returned string afterwards.
    """
    head = f"kill condition met: {kill_note}" if kill_note else "kill condition met:"
    if comp.inferior and not comp.equivalent:
        return (
            KILL,
            f"{head} {control} outperforms the treatment "
            f"(diff {comp.mean_diff:+.4f}, CI [{comp.ci_low:+.4f},{comp.ci_high:+.4f}])",
        )
    if comp.equivalent:
        return (
            KILL,
            f"{head} {control} performs equivalently -- the whole CI "
            f"[{comp.ci_low:+.4f},{comp.ci_high:+.4f}] lies inside the practical margin "
            f"+/-{comp.margin}",
        )
    if comp.superior:
        return (
            KEEP,
            f"the treatment beats {control} by {comp.mean_diff:+.4f} "
            f"(CI [{comp.ci_low:+.4f},{comp.ci_high:+.4f}])",
        )
    return (
        INCONCLUSIVE,
        f"cannot separate the treatment from {control}, and the interval is too wide "
        f"to call them equivalent either (CI [{comp.ci_low:+.4f},{comp.ci_high:+.4f}] "
        f"vs margin +/-{comp.margin})",
    )


def _pick_baseline(rs: ResultSet, variant: str) -> Optional[Arm]:
    """The reference baseline, chosen by fixed priority -- never by score."""
    for role in ("code_only", "bm25"):
        arm = rs.find(role, variant)
        if arm is not None:
            return arm
    return None


# -------------------------------------------------------------- criteria


def c_full_beats_cheap_retrieval(rs: ResultSet, cfg: EvalConfig) -> Finding:
    ref, key = "14.1", "full_beats_code_only_and_bm25"
    statement = PLAN_STATEMENTS[ref]
    variant = rs.default_variant
    missing = _missing(rs, ("full", "code_only", "bm25"), variant)
    if missing:
        return _not_evaluable(
            key, ref, PRIOR_TWIN, statement,
            f"run lacks the arms this criterion compares (variant {variant!r})",
            missing,
        )
    full = rs.find("full", variant)
    comps, warns, favours = [], [], []
    for role in ("code_only", "bm25"):
        base = rs.find(role, variant)
        comp = _compare_arms(rs, cfg, f"{key}:{role}", full, base, rs.cases)
        comps.append(comp)
        favour, note = _budget_favour(full, base, cfg)
        favours.append(favour)
        if note:
            warns.append(note)
        if comp.superior and comp.equivalent:
            warns.append(
                f"the win over {role} is real but smaller than the practical margin "
                f"+/-{cfg.margin}"
            )
    verdict, rationale = _superiority_verdict(comps)
    verdict, rationale, warns_t = _guard(verdict, rationale, comps, warns, cfg, favours)
    return Finding(key, ref, PRIOR_TWIN, statement, verdict, rationale, tuple(comps), warns_t)


def c_rewired_edges_equivalent(rs: ResultSet, cfg: EvalConfig) -> Finding:
    """14.2 names cross-plane edges, so it counts them before it compares.

    A criterion must verify that the object it names exists in its input.
    Measured on s08: 992 edges, 0 of them cross a plane, endpoint plane
    counts ``{code: 1984}``.  The rewiring control there randomises an
    intra-code import/call graph, so the comparison -- whichever way it comes
    out -- is not evidence about cross-plane edges.  The arm check comes
    *after* this one deliberately: shipping the missing rewiring control
    would not make the graph cross-plane.
    """
    ref, key = "14.2", "rewired_cross_plane_edges_equivalent"
    statement = PLAN_STATEMENTS[ref]
    variant = rs.default_variant
    edges = cross_plane_edge_refusal(rs)
    if edges is not None:
        return _undecidable(key, ref, PRIOR_TWIN, statement, edges)
    missing = _missing(rs, ("full", "rewired"), variant)
    if missing:
        return _not_evaluable(
            key, ref, PRIOR_TWIN, statement,
            "run carries no degree-preserving rewiring control", missing,
        )
    full, rewired = rs.find("full", variant), rs.find("rewired", variant)
    comp = _compare_arms(rs, cfg, key, full, rewired, rs.cases)
    favour, note = _budget_favour(full, rewired, cfg)
    warns = [note] if note else []
    verdict, rationale = _equivalence_verdict(comp, "the rewired control")
    verdict, rationale, warns_t = _guard(verdict, rationale, [comp], warns, cfg, [favour])
    return Finding(key, ref, PRIOR_TWIN, statement, verdict, rationale, (comp,), warns_t)


def c_separate_indices_equivalent(rs: ResultSet, cfg: EvalConfig) -> Finding:
    """14.3 names a cross-plane fusion arm, so it demands a real one.

    The role label ``fusion`` is not accepted on its own and there is no
    fallback to ``full`` -- that fallback was measured minting a hard KILL out
    of a one-string relabel of real s08 data, for a comparison nobody ran.  No
    cross-plane fusion retriever is implemented anywhere in this program (s08
    ships five retrievers and s09 five more, none of them fusion), so every
    14.3 verdict this evaluator could previously emit was a category error.
    A missing or unattested fusion arm is UNDECIDABLE, never a verdict, and
    never merely "this run forgot an arm": the arm does not exist to ship.
    """
    ref, key = "14.3", "four_indices_equal_fusion"
    statement = PLAN_STATEMENTS[ref]
    variant = rs.default_variant
    fusion, refusal = fusion_arm(rs, variant)
    if refusal is not None:
        return _undecidable(key, ref, PRIOR_TWIN, statement, refusal)
    separate = rs.find("separate_indices", variant)
    if separate is None:
        return _not_evaluable(
            key, ref, PRIOR_TWIN, statement,
            "run carries an attested fusion arm but no four-independent-indices "
            "arm to compare it against",
            ("separate_indices",),
        )
    comp = _compare_arms(rs, cfg, key, fusion, separate, rs.cases)
    favour, note = _budget_favour(fusion, separate, cfg)
    att = fusion.retriever
    warns = [
        f"fusion arm attested as {att.implementation} ({att.mechanism} over "
        f"{', '.join(att.combines_planes)}) -- read the implementation string "
        f"before reading the verdict"
    ]
    if note:
        warns.append(note)
    verdict, rationale = _equivalence_verdict(comp, "four independent indices")
    verdict, rationale, warns_t = _guard(verdict, rationale, [comp], warns, cfg, [favour])
    return Finding(key, ref, PRIOR_TWIN, statement, verdict, rationale, (comp,), warns_t)


def c_plane_marginal_contribution(rs: ResultSet, cfg: EvalConfig) -> Finding:
    ref, key = "14.4", "plane_has_no_marginal_contribution"
    statement = PLAN_STATEMENTS[ref]
    variant = rs.default_variant
    full = rs.find("full", variant)
    ablations = rs.ablation_arms(variant)
    if full is None or not ablations:
        return _not_evaluable(
            key, ref, PRIOR_TWIN, statement,
            "run carries no plane ablation arms",
            ("full",) if full is None else ("ablate:<plane>",),
        )
    comps, warns, favours, dead = [], [], [], []
    for ab in sorted(ablations, key=lambda a: a.role):
        comp = _compare_arms(rs, cfg, f"{key}:{ab.role}", full, ab, rs.cases)
        comps.append(comp)
        favour, note = _budget_favour(full, ab, cfg)
        favours.append(favour)
        if note:
            warns.append(note)
        if comp.equivalent or comp.inferior:
            dead.append(ab.ablated_plane or ab.role)
    undecided = [c for c in comps if c.inconclusive]
    if dead:
        verdict = KILL
        rationale = (
            f"kill condition met: removing {', '.join(dead)} does not hurt the full "
            f"representation, so {'that plane carries' if len(dead) == 1 else 'those planes carry'} "
            f"no marginal contribution"
        )
    elif undecided:
        verdict = INCONCLUSIVE
        rationale = (
            f"{len(undecided)} of {len(comps)} ablations have intervals too wide to "
            f"call either way"
        )
    else:
        verdict = KEEP
        rationale = f"every ablated plane ({len(comps)}) costs measurable quality when removed"
    verdict, rationale, warns_t = _guard(verdict, rationale, comps, warns, cfg, favours)
    return Finding(key, ref, PRIOR_TWIN, statement, verdict, rationale, tuple(comps), warns_t)


def c_graph_priority_beats_controls(rs: ResultSet, cfg: EvalConfig) -> Finding:
    ref, key = "14.6", "graph_priority_beats_random_or_evaluator_only"
    statement = PLAN_STATEMENTS[ref]
    variant = rs.default_variant
    treat = rs.find("graph_priority", variant)
    controls = [
        a for a in (rs.find("random_priority", variant), rs.find("evaluator_only", variant))
        if a is not None
    ]
    if treat is None or not controls:
        missing = []
        if treat is None:
            missing.append("graph_priority")
        if not controls:
            missing.append("random_priority|evaluator_only")
        return _not_evaluable(
            key, ref, PRIOR_GRAPH_CTX, statement,
            "run carries no graph-conditioned prioritization arm with a control",
            missing,
        )
    comps, warns, favours = [], [], []
    for ctrl in controls:
        comp = _compare_arms(rs, cfg, f"{key}:{ctrl.role}", treat, ctrl, rs.cases)
        comps.append(comp)
        favour, note = _budget_favour(treat, ctrl, cfg)
        favours.append(favour)
        if note:
            warns.append(note)
    verdict, rationale = _superiority_verdict(comps)
    verdict, rationale, warns_t = _guard(verdict, rationale, comps, warns, cfg, favours)
    return Finding(key, ref, PRIOR_GRAPH_CTX, statement, verdict, rationale, tuple(comps), warns_t)


def c_gain_survives_scrubbing(rs: ResultSet, cfg: EvalConfig) -> Finding:
    ref, key = "14.7", "gain_vanishes_after_leakage_scrub"
    statement = PLAN_STATEMENTS[ref]
    if "scrubbed" not in rs.variants():
        return _not_evaluable(
            key, ref, PRIOR_TWIN, statement,
            "run has no 'scrubbed' query variant to compare against",
            ("variant:scrubbed",),
        )
    raw_variant = "raw" if "raw" in rs.variants() else rs.default_variant
    full_raw, full_scr = rs.find("full", raw_variant), rs.find("full", "scrubbed")
    base_raw = _pick_baseline(rs, raw_variant)
    base_scr = _pick_baseline(rs, "scrubbed")
    if not all((full_raw, full_scr, base_raw, base_scr)):
        return _not_evaluable(
            key, ref, PRIOR_TWIN, statement,
            "the full arm and a baseline must both appear on the raw and scrubbed variants",
            ("full/scrubbed", "baseline/scrubbed"),
        )
    if base_raw.role != base_scr.role:
        return _not_evaluable(
            key, ref, PRIOR_TWIN, statement,
            f"baseline role differs across variants ({base_raw.role} vs {base_scr.role}); "
            f"the two gains would not be comparable",
        )
    raw_comp = _compare_arms(rs, cfg, f"{key}:raw", full_raw, base_raw, rs.cases)
    scr_comp = _compare_arms(rs, cfg, f"{key}:scrubbed", full_scr, base_scr, rs.cases)
    warns, favours = [], []
    for t, b in ((full_raw, base_raw), (full_scr, base_scr)):
        favour, note = _budget_favour(t, b, cfg)
        favours.append(favour)
        if note:
            warns.append(note)
    if not raw_comp.superior:
        verdict = INCONCLUSIVE
        rationale = (
            "there is no established raw gain to scrub away "
            f"(raw diff {raw_comp.mean_diff:+.4f}, CI "
            f"[{raw_comp.ci_low:+.4f},{raw_comp.ci_high:+.4f}])"
        )
    elif scr_comp.superior:
        verdict = KEEP
        rationale = (
            f"the gain survives scrubbing: {raw_comp.mean_diff:+.4f} raw vs "
            f"{scr_comp.mean_diff:+.4f} scrubbed, both intervals clear of zero"
        )
    elif scr_comp.equivalent or scr_comp.inferior:
        verdict = KILL
        rationale = (
            f"kill condition met: the raw gain {raw_comp.mean_diff:+.4f} collapses to "
            f"{scr_comp.mean_diff:+.4f} after scrubbing "
            f"(CI [{scr_comp.ci_low:+.4f},{scr_comp.ci_high:+.4f}])"
        )
    else:
        verdict = INCONCLUSIVE
        rationale = "the scrubbed interval is too wide to say whether the gain survived"
    verdict, rationale, warns_t = _guard(
        verdict, rationale, [raw_comp, scr_comp], warns, cfg, favours
    )
    return Finding(
        key, ref, PRIOR_TWIN, statement, verdict, rationale, (raw_comp, scr_comp), warns_t
    )


def c_tokens_explain_gain(rs: ResultSet, cfg: EvalConfig) -> Finding:
    ref, key = "14.8", "extra_tokens_explain_the_gain"
    statement = PLAN_STATEMENTS[ref]
    variant = rs.default_variant
    missing = _missing(rs, ("full", "token_matched"), variant)
    if missing:
        return _not_evaluable(
            key, ref, PRIOR_GRAPH_CTX, statement,
            "run has no token-matched baseline (a baseline handed the same extra budget)",
            missing,
        )
    full, matched = rs.find("full", variant), rs.find("token_matched", variant)
    comp = _compare_arms(rs, cfg, key, full, matched, rs.cases)
    warns = []
    favour, note = _budget_favour(full, matched, cfg)
    if note:
        warns.append(note + " -- a token-matched arm whose budget is not matched is not a control")
    verdict, rationale = _equivalence_verdict(
        comp,
        "the token-matched baseline",
        kill_note="the structure adds nothing beyond the tokens --",
    )
    verdict, rationale, warns_t = _guard(verdict, rationale, [comp], warns, cfg, [favour])
    return Finding(key, ref, PRIOR_GRAPH_CTX, statement, verdict, rationale, (comp,), warns_t)


def c_cost_frontier(rs: ResultSet, cfg: EvalConfig) -> Finding:
    ref, key = "14.9", "cost_worsens_quality_cost_frontier"
    statement = PLAN_STATEMENTS[ref]
    variant = rs.default_variant
    full = rs.find("full", variant)
    base = _pick_baseline(rs, variant)
    if full is None or base is None:
        return _not_evaluable(
            key, ref, PRIOR_TWIN, statement,
            "run lacks a full arm and a cheap baseline to price against",
            ("full",) if full is None else ("code_only|bm25",),
        )
    if full.cost_units is None or base.cost_units is None or base.cost_units <= 0:
        return _not_evaluable(
            key, ref, PRIOR_TWIN, statement,
            "arms carry no cost_units, so the frontier cannot be priced",
            ("cost_units",),
        )
    comp = _compare_arms(rs, cfg, key, full, base, rs.cases)
    multiple = full.cost_units / base.cost_units
    warns = [f"cost multiple vs {base.role}: {multiple:.2f}x"]
    if multiple <= 1.0 + cfg.cost_tolerance:
        verdict = KEEP
        rationale = (
            f"the full representation is not more expensive than {base.role} "
            f"({multiple:.2f}x), so it cannot worsen the frontier"
        )
    elif comp.superior and not comp.equivalent:
        verdict = KEEP
        rationale = (
            f"costs {multiple:.2f}x more and delivers {comp.mean_diff:+.4f} "
            f"(CI [{comp.ci_low:+.4f},{comp.ci_high:+.4f}]); the frontier moves out, "
            f"whether the trade is worth it is a budget decision, not a kill"
        )
    elif comp.equivalent or comp.inferior:
        verdict = KILL
        rationale = (
            f"kill condition met: {multiple:.2f}x the cost of {base.role} for "
            f"{comp.mean_diff:+.4f} quality (CI "
            f"[{comp.ci_low:+.4f},{comp.ci_high:+.4f}]) -- strictly worse frontier"
        )
    else:
        verdict = INCONCLUSIVE
        rationale = (
            f"costs {multiple:.2f}x more and the quality interval "
            f"[{comp.ci_low:+.4f},{comp.ci_high:+.4f}] does not establish a gain"
        )
    favour, note = _budget_favour(full, base, cfg)
    if note:
        warns.append(note)
    verdict, rationale, warns_t = _guard(verdict, rationale, [comp], warns, cfg, [favour])
    return Finding(key, ref, PRIOR_TWIN, statement, verdict, rationale, (comp,), warns_t)


def c_held_out_transfer(rs: ResultSet, cfg: EvalConfig) -> Finding:
    ref, key = "14.12", "benefit_vanishes_on_held_out"
    statement = PLAN_STATEMENTS[ref]
    variant = rs.default_variant
    held = rs.group("held_out")
    in_domain = rs.group("in_domain")
    full = rs.find("full", variant)
    base = _pick_baseline(rs, variant)
    if not held or not in_domain:
        return _not_evaluable(
            key, ref, PRIOR_TWIN, statement,
            "run declares no in_domain / held_out case groups",
            ("case_groups.held_out", "case_groups.in_domain"),
        )
    if full is None or base is None:
        return _not_evaluable(
            key, ref, PRIOR_TWIN, statement,
            "run lacks a full arm or a baseline to measure transfer with",
            ("full",) if full is None else ("code_only|bm25",),
        )
    in_comp = _compare_arms(rs, cfg, f"{key}:in_domain", full, base, in_domain)
    out_comp = _compare_arms(rs, cfg, f"{key}:held_out", full, base, held)
    warns = []
    favour, note = _budget_favour(full, base, cfg)
    if note:
        warns.append(note)
    if not in_comp.superior:
        verdict = INCONCLUSIVE
        rationale = (
            "no in-domain gain was established, so there is nothing whose transfer "
            "could be tested"
        )
    elif out_comp.superior:
        verdict = KEEP
        rationale = (
            f"the gain transfers: {in_comp.mean_diff:+.4f} in-domain vs "
            f"{out_comp.mean_diff:+.4f} held-out, both clear of zero"
        )
    elif out_comp.equivalent or out_comp.inferior:
        verdict = KILL
        rationale = (
            f"kill condition met: the in-domain gain {in_comp.mean_diff:+.4f} does not "
            f"transfer ({out_comp.mean_diff:+.4f} held-out, CI "
            f"[{out_comp.ci_low:+.4f},{out_comp.ci_high:+.4f}])"
        )
    else:
        verdict = INCONCLUSIVE
        rationale = (
            f"the held-out interval [{out_comp.ci_low:+.4f},{out_comp.ci_high:+.4f}] "
            f"is too wide to judge transfer"
        )
    verdict, rationale, warns_t = _guard(
        verdict, rationale, [in_comp, out_comp], warns, cfg, [favour]
    )
    return Finding(
        key, ref, PRIOR_TWIN, statement, verdict, rationale, (in_comp, out_comp), warns_t
    )


# ------------------------------------------------------------- the register


@dataclass(frozen=True)
class Registered:
    """One plan bullet, and what this evaluator does about it.

    ``evaluator is None`` means out of scope for a retrieval result set --
    which is a *stated* position with a reason, not a silent omission.  The
    distinction matters: an omitted bullet shrinks the denominator and
    flatters the coverage; an out-of-scope bullet is counted and reported as
    ``NOT_EVALUABLE``.
    """

    plan_ref: str
    key: str
    prior: str
    evaluator: Optional[Callable[[ResultSet, "EvalConfig"], Finding]] = None
    out_of_scope_reason: str = ""

    @property
    def statement(self) -> str:
        return PLAN_STATEMENTS[self.plan_ref]

    @property
    def decidable(self) -> bool:
        return self.evaluator is not None


#: Every bullet of the plan's kill-criteria section, in plan order, with no
#: gaps.  ``plan_register.verify(register_entries())`` re-derives this list
#: from the living plan and fails on any difference -- count, order, index or
#: wording.  Adding a bullet to the plan turns that check red until this
#: register follows.
REGISTER: Tuple[Registered, ...] = (
    Registered("14.1", "full_beats_code_only_and_bm25", PRIOR_TWIN,
               c_full_beats_cheap_retrieval),
    Registered("14.2", "rewired_cross_plane_edges_equivalent", PRIOR_TWIN,
               c_rewired_edges_equivalent),
    Registered("14.3", "four_indices_equal_fusion", PRIOR_TWIN,
               c_separate_indices_equivalent),
    Registered("14.4", "plane_has_no_marginal_contribution", PRIOR_TWIN,
               c_plane_marginal_contribution),
    Registered(
        "14.5", "graph_movement_predicts_behaviour", PRIOR_TWIN,
        out_of_scope_reason=(
            "needs paired graph-delta and behavioural-outcome records; a retrieval "
            "result set contains no behavioural outcome"
        ),
    ),
    Registered("14.6", "graph_priority_beats_random_or_evaluator_only",
               PRIOR_GRAPH_CTX, c_graph_priority_beats_controls),
    Registered("14.7", "gain_vanishes_after_leakage_scrub", PRIOR_TWIN,
               c_gain_survives_scrubbing),
    Registered("14.8", "extra_tokens_explain_the_gain", PRIOR_GRAPH_CTX,
               c_tokens_explain_gain),
    Registered("14.9", "cost_worsens_quality_cost_frontier", PRIOR_TWIN,
               c_cost_frontier),
    Registered(
        "14.10", "revision_atomic_snapshot_cost", PRIOR_TWIN,
        out_of_scope_reason=(
            "needs snapshot build/maintenance cost telemetry per revision, which this "
            "format does not carry"
        ),
    ),
    Registered(
        "14.11", "embedding_precision_after_verification", PRIOR_LATENT,
        out_of_scope_reason=(
            "needs proposal-level precision and verifier cost, not ranked file lists"
        ),
    ),
    Registered("14.12", "benefit_vanishes_on_held_out", PRIOR_TWIN,
               c_held_out_transfer),
    Registered(
        "14.13", "motif_composition_beats_direct", PRIOR_GENESIS,
        out_of_scope_reason=(
            "needs generation trials with a build/repair ladder; out of scope for a "
            "retrieval measurement"
        ),
    ),
    Registered(
        "14.14", "genesis_roundtrip_predicts_buildable", PRIOR_GENESIS,
        out_of_scope_reason="needs round-trip conformance and build outcomes",
    ),
    Registered(
        "14.15", "corpus_licensing_provenance_blocks_reuse", PRIOR_CORPUS,
        out_of_scope_reason=(
            "needs per-document corpus ingestion metadata -- source repository, "
            "revision, license, temporal cutoff, extraction version and extraction "
            "cost (plan sections 5 and 9.1) -- none of which a retrieval result set "
            "carries. This criterion is not about ranking at all, so no result set "
            "of this schema can ever decide it; deciding it needs a corpus manifest "
            "audit, which is a different instrument. Recorded rather than dropped: "
            "the first version of this register omitted it entirely and shrank its "
            "own denominator by doing so"
        ),
    ),
    Registered(
        "14.16", "orchestration_evolution_transfer", PRIOR_ORCH,
        out_of_scope_reason=(
            "needs orchestration campaign results across repositories"
        ),
    ),
)

EVALUATORS: Tuple[Callable[[ResultSet, EvalConfig], Finding], ...] = tuple(
    r.evaluator for r in REGISTER if r.evaluator is not None
)

#: Kept in the historical (key, ref, prior, statement, why) shape for callers
#: that want only the undecidable bullets; derived, never hand-maintained.
OUT_OF_SCOPE: Tuple[Tuple[str, str, str, str, str], ...] = tuple(
    (r.key, r.plan_ref, r.prior, r.statement, r.out_of_scope_reason)
    for r in REGISTER if r.evaluator is None
)


def register_entries() -> Tuple[Tuple[str, str], ...]:
    """(plan_ref, statement) pairs in plan order, for the register check."""
    return tuple((r.plan_ref, r.statement) for r in REGISTER)


def evaluate(rs: ResultSet, cfg: Optional[EvalConfig] = None) -> List[Finding]:
    """Run every criterion, decidable or not, in plan order.

    ``RangeRefused`` is caught here, once, for every criterion.  A criterion
    that tries to report a comparison whose dynamic range is zero does not get
    to choose what happens next: it becomes UNDECIDABLE, named by the register
    entry that raised it.
    """
    cfg = cfg or EvalConfig()
    findings: List[Finding] = []
    for entry in REGISTER:
        if entry.evaluator is None:
            continue
        try:
            findings.append(entry.evaluator(rs, cfg))
        except RangeRefused as exc:
            findings.append(
                _undecidable(
                    entry.key, entry.plan_ref, entry.prior, entry.statement,
                    Refusal(
                        exc.refusal.reason,
                        exc.refusal.detail + (f"refused comparison: {exc.label}",),
                    ),
                )
            )
    for key, ref, prior, statement, why in OUT_OF_SCOPE:
        findings.append(_not_evaluable(key, ref, prior, statement, why))
    if rs.seeds < cfg.min_seeds:
        note = (
            f"run declares {rs.seeds} seed(s); the plan asks for {cfg.min_seeds}-10 "
            f"where stochastic variance matters"
        )
        annotated: List[Finding] = []
        for f in findings:
            if f.verdict in (NOT_EVALUABLE, UNDECIDABLE):
                annotated.append(f)
                continue
            annotated.append(
                Finding(
                    f.key, f.plan_ref, f.prior, f.statement, f.verdict, f.rationale,
                    f.comparisons, f.warnings + (note,), f.missing,
                )
            )
        findings = annotated
    findings.sort(key=lambda f: [int(p) for p in f.plan_ref.split(".")])
    return findings
