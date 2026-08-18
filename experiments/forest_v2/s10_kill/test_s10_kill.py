"""Self-test for the kill-criteria evaluator.

    python -m pytest experiments/forest_v2/s10_kill/ -q

The interesting assertions are not "the code runs".  They are:

* a constructed kill fires the criterion it was constructed to fire;
* a constructed pass does not fire anything;
* an underpowered run decides *nothing*, even though the effect is real;
* a win bought with extra budget is not reported as a win;
* equivalence is only claimed when the interval is tight, never merely
  because significance was missed.
"""
from __future__ import annotations

import json

import pytest

from . import SCHEMA_ID
from . import measured_inputs, plan_register
from .criteria import (
    EVALUATORS,
    INCONCLUSIVE,
    KEEP,
    KILL,
    NOT_EVALUABLE,
    OUT_OF_SCOPE,
    PLAN_STATEMENTS,
    REGISTER,
    UNDECIDABLE,
    EvalConfig,
    evaluate,
    register_entries,
)
from .plane_range import crosstab, fusion_arm, range_refusal
from .report import build, render, roll_up, to_json
from .schema import ResultSet, SchemaError, dump
from .stats import bootstrap_ci, compare, stable_seed
from .synth import ArmSpec, SCENARIOS, build as build_scenario, make_run

CFG = EvalConfig(resamples=2000)


def _rs(name: str, seed=None) -> ResultSet:
    return ResultSet.from_obj(build_scenario(name, seed))


def _finding(rs: ResultSet, ref: str, cfg: EvalConfig = CFG):
    for f in evaluate(rs, cfg):
        if f.plan_ref == ref:
            return f
    raise AssertionError(f"no finding for plan ref {ref}")


# --------------------------------------------------------- plan register
#
# These are the checks the first version of this slice did not have.  It
# asserted ``len(findings) == 15`` with the reason "the plan lists 15 kill
# criteria".  The plan lists sixteen.  A constant cannot notice that; only a
# comparison against the living document can.


def test_the_register_matches_the_living_plan_one_to_one():
    """Wording, order and plan_ref of every criterion, against the real plan."""
    check = plan_register.verify(register_entries())
    assert check.ok, "\n" + check.describe()
    assert check.n_registered == check.n_extracted


def test_the_register_has_no_gap_in_its_plan_indices():
    """14.15 must be 14.15.  A hand-numbered list closed the gap left by a
    missing criterion, so a reader who looked up a citation landed on a
    different bullet than the report meant."""
    section = plan_register.load_section().section
    assert [r.plan_ref for r in REGISTER] == [
        f"{section}.{i}" for i in range(1, len(REGISTER) + 1)
    ]


def test_every_registered_criterion_is_decidable_or_says_why_not():
    for r in REGISTER:
        assert r.statement, r.plan_ref
        assert r.decidable or r.out_of_scope_reason, (
            f"{r.plan_ref} is neither implemented nor explained; that is the "
            f"silent omission this register exists to prevent"
        )
    assert len(EVALUATORS) + len(OUT_OF_SCOPE) == len(REGISTER)


def test_the_corpus_licensing_criterion_is_present_and_explained():
    """The bullet that was missing entirely, pinned by content not by index."""
    matches = [r for r in REGISTER if "licensing" in r.statement]
    assert len(matches) == 1, "the corpus licensing/provenance bullet must appear once"
    got = matches[0]
    assert got.plan_ref == "14.15"
    assert not got.decidable
    assert "corpus" in got.out_of_scope_reason


# --- mutation probes: the checks above must be capable of failing ---------


def _tampered_plan(tmp_path, mutate):
    """A copy of the living plan with one edit; the real plan is never touched."""
    source = plan_register.find_plan()
    assert source is not None, "the living plan must be findable"
    before = source.read_text(encoding="utf-8")
    after = mutate(before)
    # A mutation probe that mutates nothing proves nothing: it would leave the
    # check green and read as "the check is fine".
    assert after != before, "the tamper anchor no longer matches the plan text"
    target = tmp_path / "plan.md"
    target.write_text(after, encoding="utf-8")
    return target


def test_a_reworded_plan_bullet_makes_the_register_check_red(tmp_path):
    victim = PLAN_STATEMENTS["14.3"]
    path = _tampered_plan(
        tmp_path, lambda text: text.replace(victim, "four independent indices are fine")
    )
    check = plan_register.verify(register_entries(), path)
    assert not check.ok
    assert any("wording differs" in m for m in check.mismatches)


def test_a_plan_that_gains_a_criterion_makes_the_register_check_red(tmp_path):
    # Anchored on the first bullet, which the plan holds on a single line.
    anchor = "- " + PLAN_STATEMENTS["14.1"] + ";"
    path = _tampered_plan(
        tmp_path,
        lambda text: text.replace(
            anchor, "- a seventeenth condition nobody implemented yet;\n" + anchor
        ),
    )
    check = plan_register.verify(register_entries(), path)
    assert not check.ok
    assert any("count:" in m for m in check.mismatches)


def test_a_removed_criterion_makes_the_register_check_red():
    entries = [e for e in register_entries() if e[0] != "14.9"]
    check = plan_register.verify(entries)
    assert not check.ok
    assert any("count:" in m for m in check.mismatches)
    assert any("missing, not" in m for m in check.mismatches)


def test_a_renumbered_criterion_makes_the_register_check_red():
    """The exact defect: one bullet dropped, everything after it slides up."""
    entries = [e for e in register_entries() if e[0] != "14.15"]
    section = plan_register.load_section().section
    slid = [
        (f"{section}.{i}", statement)
        for i, (_, statement) in enumerate(entries, start=1)
    ]
    check = plan_register.verify(slid)
    assert not check.ok
    # Named for the harm it causes, not only as "the wording differs":
    # a report citing 14.15 would send its reader to a different criterion.
    assert any("misfiled citation" in m for m in check.mismatches)
    assert any("plan numbers 14.16" in m for m in check.mismatches)


def test_the_extractor_refuses_a_plan_it_cannot_read(tmp_path):
    path = tmp_path / "plan.md"
    path.write_text("# not the plan\n\nnothing here\n", encoding="utf-8")
    with pytest.raises(plan_register.PlanRegisterError, match="Kill criteria"):
        plan_register.load_section(path)


# ------------------------------------------------------------------ schema


def test_schema_rejects_foreign_schema_id():
    with pytest.raises(SchemaError, match="unsupported schema"):
        ResultSet.from_obj({"schema": "something.else/1", "run_id": "x"})


def test_schema_rejects_unpaired_arm():
    obj = build_scenario("no_gain")
    victim = obj["arms"][0]["scores"][obj["primary_metric"]]
    victim.pop(obj["cases"][0])
    with pytest.raises(SchemaError, match="unpaired"):
        ResultSet.from_obj(obj)


def test_schema_rejects_scores_for_unknown_case():
    obj = build_scenario("no_gain")
    obj["arms"][0]["scores"][obj["primary_metric"]]["ghost-case"] = 1.0
    with pytest.raises(SchemaError, match="outside the run"):
        ResultSet.from_obj(obj)


def test_schema_rejects_missing_primary_metric():
    obj = build_scenario("no_gain")
    obj["primary_metric"] = "mrr"
    with pytest.raises(SchemaError, match="primary metric"):
        ResultSet.from_obj(obj)


def test_schema_rejects_unknown_role_and_plane():
    obj = build_scenario("no_gain")
    obj["arms"][0]["role"] = "vibes"
    with pytest.raises(SchemaError, match="unknown role"):
        ResultSet.from_obj(obj)
    obj["arms"][0]["role"] = "ablate:vibes"
    with pytest.raises(SchemaError, match="ablated plane"):
        ResultSet.from_obj(obj)


def test_schema_rejects_duplicate_arm_ids():
    obj = build_scenario("no_gain")
    obj["arms"][1]["arm_id"] = obj["arms"][0]["arm_id"]
    with pytest.raises(SchemaError, match="duplicate arm_id"):
        ResultSet.from_obj(obj)


def test_schema_rejects_non_numeric_score():
    obj = build_scenario("no_gain")
    metric = obj["primary_metric"]
    obj["arms"][0]["scores"][metric][obj["cases"][0]] = "high"
    with pytest.raises(SchemaError, match="not a number"):
        ResultSet.from_obj(obj)


def test_schema_rejects_group_naming_unknown_case():
    obj = build_scenario("no_gain")
    obj["case_groups"] = {"held_out": ["nope"]}
    with pytest.raises(SchemaError, match="outside the run"):
        ResultSet.from_obj(obj)


def test_ambiguous_role_lookup_is_an_error_not_a_guess():
    obj = build_scenario("no_gain")
    twin = json.loads(json.dumps(obj["arms"][0]))
    twin["arm_id"] = twin["arm_id"] + "-twin"
    obj["arms"].append(twin)
    rs = ResultSet.from_obj(obj)
    with pytest.raises(SchemaError, match="arms with role"):
        rs.find("full", "raw")


def test_schema_rejects_a_gold_plane_for_a_case_outside_the_run():
    obj = build_scenario("no_gain")
    obj["gold_planes"]["not_a_case"] = "code"
    with pytest.raises(SchemaError, match="not in the run"):
        ResultSet.from_obj(obj)


def test_schema_rejects_an_unknown_gold_plane():
    obj = build_scenario("no_gain")
    obj["gold_planes"][obj["cases"][0]] = "vibes"
    with pytest.raises(SchemaError, match="not one of"):
        ResultSet.from_obj(obj)


def test_schema_rejects_returns_that_contradict_the_declared_scope():
    """The counts win over the label, and a contradiction is not graded."""
    obj = build_scenario("no_gain")
    obj["arms"][0]["returns_planes"] = ["code"]
    obj["arms"][0]["returned_plane_counts"] = {"code": 10, "knowledge": 3}
    with pytest.raises(SchemaError, match="outside its declared returns_planes"):
        ResultSet.from_obj(obj)


def test_schema_rejects_an_unknown_retriever_mechanism():
    obj = build_scenario("no_gain")
    obj["arms"][0]["retriever"] = {
        "implementation": "x", "mechanism": "magic", "combines_planes": [],
    }
    with pytest.raises(SchemaError, match="mechanism"):
        ResultSet.from_obj(obj)


def test_schema_rejects_more_cross_plane_edges_than_edges():
    obj = build_scenario("no_gain")
    obj["corpus"]["graph"]["cross_plane_edges"] = 99999
    with pytest.raises(SchemaError, match="cross-plane edges out of"):
        ResultSet.from_obj(obj)


def test_dump_round_trips():
    rs = _rs("surviving_prior")
    again = ResultSet.from_obj(dump(rs))
    assert again.cases == rs.cases
    assert {a.arm_id for a in again.arms} == {a.arm_id for a in rs.arms}
    assert again.case_groups == rs.case_groups
    assert dump(again)["schema"] == SCHEMA_ID


# ------------------------------------------------------------------- stats


def test_bootstrap_is_deterministic_for_a_seed():
    diffs = [0.1, -0.2, 0.3, 0.05, -0.01, 0.22, 0.0, 0.4, -0.3, 0.15]
    a = bootstrap_ci(diffs, resamples=500, seed=7)
    b = bootstrap_ci(diffs, resamples=500, seed=7)
    c = bootstrap_ci(diffs, resamples=500, seed=8)
    assert a == b
    assert a != c


def test_stable_seed_does_not_depend_on_evaluation_order():
    assert stable_seed(5, "x") == stable_seed(5, "x")
    assert stable_seed(5, "x") != stable_seed(5, "y")


def test_constant_differences_give_a_point_interval():
    assert bootstrap_ci([0.25] * 12, resamples=100, seed=1) == (0.25, 0.25)


def test_states_are_separable_not_negations():
    """A tight tiny win is both superior and equivalent; a wide one is neither."""
    tight = compare("t", "a", "b", [0.5051] * 30, [0.5] * 30, resamples=200, seed=1)
    assert tight.superior and tight.equivalent
    assert not tight.inconclusive

    noisy = compare(
        "n", "a", "b",
        [0.9, 0.1, 0.8, 0.2, 0.7, 0.3, 0.95, 0.05, 0.6, 0.4],
        [0.1, 0.9, 0.2, 0.8, 0.3, 0.7, 0.05, 0.95, 0.4, 0.6],
        resamples=500, seed=2,
    )
    assert noisy.inconclusive
    assert not noisy.equivalent, "a wide interval must never be called equivalent"


def test_compare_refuses_unpaired_inputs():
    with pytest.raises(ValueError, match="unpaired"):
        compare("x", "a", "b", [0.1, 0.2], [0.1], resamples=10)


# --------------------------------------------------------------- criteria


def test_surviving_prior_kills_nothing():
    findings = evaluate(_rs("surviving_prior"), CFG)
    killed = [f.plan_ref for f in findings if f.verdict == KILL]
    assert killed == [], f"a constructed pass fired {killed}"
    decided = [
        f for f in findings if f.verdict not in (NOT_EVALUABLE, UNDECIDABLE)
    ]
    # Eight, not nine: this scenario carries no attested fusion arm, because
    # no fusion retriever exists in this program, so 14.3 is UNDECIDABLE here
    # exactly as it is on every real measurement.
    assert len(decided) == 8
    assert all(f.verdict == KEEP for f in decided)
    assert _finding(_rs("surviving_prior"), "14.3").verdict == UNDECIDABLE


@pytest.mark.parametrize(
    "scenario,ref",
    [
        ("no_gain", "14.1"),
        ("rewire_kill", "14.2"),
        ("leakage_kill", "14.7"),
        ("cost_kill", "14.9"),
        ("held_out_kill", "14.12"),
    ],
)
def test_constructed_kill_fires_its_criterion(scenario, ref):
    assert _finding(_rs(scenario), ref).verdict == KILL


def test_ablation_kill_names_the_useless_plane():
    obj = make_run(
        "ablation-kill",
        [
            ArmSpec("full", 0.15),
            ArmSpec("code_only", 0.0),
            ArmSpec("bm25", 0.0),
            ArmSpec("ablate:code", 0.02),
            ArmSpec("ablate:data", 0.15),  # removing it changes nothing
        ],
        seed=3, noise=0.01,
    )
    finding = _finding(ResultSet.from_obj(obj), "14.4")
    assert finding.verdict == KILL
    assert "data" in finding.rationale


def test_separate_indices_equivalence_fires_when_a_fusion_arm_is_attested():
    """14.3 must remain *capable* of firing, or the refusal proves nothing.

    The attestation here is synthetic and says so in its implementation
    string; the criterion copies that string into a warning so a verdict can
    never be read without it.
    """
    finding = _finding(_rs("fusion_attested_kill"), "14.3")
    assert finding.verdict == KILL
    assert any("synthetic ground truth" in w for w in finding.warnings)


def test_token_matched_baseline_explains_the_gain():
    obj = make_run(
        "tokens-explain",
        [
            ArmSpec("full", 0.15),
            ArmSpec("code_only", 0.0),
            ArmSpec("bm25", 0.0),
            ArmSpec("token_matched", 0.15),
        ],
        seed=5, noise=0.01,
    )
    finding = _finding(ResultSet.from_obj(obj), "14.8")
    assert finding.verdict == KILL
    assert "beyond the tokens" in finding.rationale


def test_missing_arms_are_reported_as_not_evaluable_not_as_a_pass():
    finding = _finding(_rs("no_gain"), "14.2")
    assert finding.verdict == NOT_EVALUABLE
    assert "rewired" in finding.missing


def test_out_of_scope_criteria_are_counted_and_say_why():
    findings = evaluate(_rs("surviving_prior"), CFG)
    out = [f for f in findings if f.verdict == NOT_EVALUABLE]
    assert len(out) == len(OUT_OF_SCOPE)
    assert all(f.rationale for f in out)
    # The count comes from the living plan, never from a literal typed here.
    # A plan that gains a kill criterion must make this fail.
    n_plan = plan_register.load_section().n_extracted
    assert len(findings) == n_plan, (
        f"the plan lists {n_plan} kill criteria and the evaluator reported "
        f"{len(findings)}; every bullet must appear, decided or not"
    )


# ------------------------------------------- can this thing ever say KILL?
#
# The synthetic scenarios prove the machinery fires.  They cannot answer the
# harder question: on the measurements this project actually has, does the
# evaluator reach a verdict, or does every path end in "not evaluable"?
# These run the real s08 numbers through it.


def _measured(name: str) -> ResultSet:
    return ResultSet.from_obj(measured_inputs.build(name))


def test_the_measured_input_reproduces_the_published_s08_marginals():
    rs = _measured("s08_graph_structure")
    hits = {a.role: round(sum(a.scores.values())) for a in rs.arms}
    assert len(rs.cases) == 600
    assert hits == {"full": 497, "rewired": 491, "code_only": 491}


def test_the_measured_input_reproduces_the_published_s08_pairing():
    """Not just the totals: the 2x2 must come back out of the per-case data."""
    rs = _measured("s08_graph_structure")
    graph = rs.find("full").scores
    rewired = rs.find("rewired").scores
    both = sum(1 for c in rs.cases if graph[c] and rewired[c])
    only_graph = sum(1 for c in rs.cases if graph[c] and not rewired[c])
    only_rewired = sum(1 for c in rs.cases if rewired[c] and not graph[c])
    neither = sum(1 for c in rs.cases if not graph[c] and not rewired[c])
    published = measured_inputs.pair("graph_rewired", "graph_code_only")
    assert (both, only_rewired, only_graph, neither) == (
        published.both, published.only_a, published.only_b, published.neither
    )


def test_142_refuses_the_s08_graph_because_it_has_no_cross_plane_edge():
    """The criterion names cross-plane edges; this graph has none.

    Until this slice, 14.2 read INCONCLUSIVE here off a real 13-rescued /
    7-lost comparison -- a number computed over 992 edges of which 0 cross a
    plane.  Neither KEEP nor KILL from that comparison means anything about
    the plan's clause, and INCONCLUSIVE was the most dangerous of the three,
    because the remedy it invites is a bigger query set.
    """
    finding = _finding(_measured("s08_graph_structure"), "14.2")
    assert finding.verdict == UNDECIDABLE
    assert finding.comparisons == ()
    assert "992 edges and 0 of them cross a plane" in finding.rationale
    assert any("code: 1984" in w for w in finding.warnings)


@pytest.mark.parametrize("run", sorted(measured_inputs.MEASURED_RUNS))
def test_142_is_undecidable_on_every_measured_run_in_the_program(run):
    """Every s08 query set -- 600, 138 and the extended 738 -- and both
    no-fusion instantiations. The refusal is a property of the corpus, so it
    cannot be escaped by picking a query set."""
    assert _finding(_measured(run), "14.2").verdict == UNDECIDABLE


@pytest.mark.parametrize("run", sorted(measured_inputs.MEASURED_RUNS))
def test_a_run_without_a_fusion_arm_refuses_to_decide_the_fusion_criterion(run):
    """s08 built no fusion retriever, so 14.3 must not be answered from it.

    The tempting shortcut is to let the nearest available arm stand in for the
    missing one; that is how a criterion gets 'decided' by a comparison nobody
    ran.  Every measured run, every query set and both no-fusion
    instantiations, so the refusal cannot be an accident of one arm choice.

    UNDECIDABLE, not NOT_EVALUABLE: a missing rewiring control is a hole this
    run could fill, while the fusion arm does not exist anywhere in the
    program to ship.
    """
    finding = _finding(_measured(run), "14.3")
    assert finding.verdict == UNDECIDABLE
    assert "no fallback to another role" in finding.rationale


def test_no_arm_of_a_measured_run_is_labelled_fusion():
    """The joint single index must never be dressed up as cross-plane fusion.

    s08 has no fusion retriever. A `fusion` or `full` label on the joint index
    would hand 14.3 a verdict from a comparison that was never run -- the
    substituted-comparator defect s08 itself had to retract.
    """
    for name in measured_inputs.MEASURED_RUNS:
        if not name.startswith("s08_routing"):
            continue
        rs = _measured(name)
        assert {a.role for a in rs.arms} == {"separate_indices", "bm25"}, name
        joint = rs.find("bm25")
        assert "NOT cross-plane fusion" in joint.notes


def test_the_retracted_s08_comparison_is_not_reused():
    """s08 withdrew the starved round-robin vs code-only table (432/0/59/109).

    A retracted measurement republished downstream is how a corrected finding
    stays wrong.
    """
    with pytest.raises(KeyError):
        measured_inputs.pair("four_plane_no_fusion", "bm25_code_only")


def test_every_measured_arm_carries_its_provenance_into_the_report():
    """Criteria select arms by role; the report must say what the label was on."""
    rs = _measured("s08_graph_structure")
    rep = build(rs, evaluate(rs, CFG), CFG)
    assert rep.arms and all(notes for _, _, notes in rep.arms)
    assert "ARMS AS LABELLED" in render(rep)
    assert all(a["notes"] for a in to_json(rep)["arms"])


def test_a_prior_cannot_reach_keep_while_its_controls_were_never_shipped():
    """Omission is not a pass.

    A run carrying only the treatment and its two cheap baselines can pass
    everything it asks and leave every criterion that might have killed the
    prior unasked.  Counting that as KEEP is the structural bias that makes an
    evaluator unable to kill anything.
    """
    obj = make_run(
        "controls-omitted",
        [ArmSpec("full", 0.15), ArmSpec("code_only", 0.0), ArmSpec("bm25", 0.0)],
        seed=21, noise=0.01,
    )
    findings = evaluate(ResultSet.from_obj(obj), CFG)
    twin = [p for p in roll_up(findings) if p.prior == "four_plane_project_twin"][0]
    assert [f.verdict for f in findings if f.plan_ref == "14.1"] == [KEEP]
    assert twin.verdict == INCONCLUSIVE
    assert "14.2" in twin.uninstrumented
    assert "never" in twin.rationale


def test_an_equivalence_kill_is_reachable_at_the_real_effect_size():
    """Not "could fire in principle" -- fires at s08's own discordance rate.

    600 paired queries cannot resolve inside the +/-0.02 margin.  Holding the
    measured 13-rescued / 7-lost / 580-tied rate and tripling the query set
    does, and 14.2 then reads EQUIVALENT, which is a KILL.  The evaluator is
    short of resolution, not incapable of a verdict.
    """
    n, wins, losses = 1800, 39, 21
    treat = [1.0] * wins + [0.0] * losses + [1.0] * (n - wins - losses)
    base = [0.0] * wins + [1.0] * losses + [1.0] * (n - wins - losses)
    comp = compare("scaled", "t", "b", treat, base, margin=0.02,
                   confidence=0.95, resamples=4000, seed=CFG.seed)
    assert comp.equivalent, comp.describe()
    assert comp.ci_high < 0.02


def test_a_fully_instrumented_run_can_still_reach_keep():
    """The guards must not make KEEP unreachable in principle.

    Fully instrumented now means one more thing than it used to: an attested
    fusion arm, gold labels in every plane, and a graph that actually has
    cross-plane edges.  No result set in this program meets that bar.
    """
    twin = [
        p for p in roll_up(evaluate(_rs("fusion_attested_keep"), CFG))
        if p.prior == "four_plane_project_twin"
    ][0]
    assert twin.verdict == KEEP
    assert twin.uninstrumented == ()
    assert twin.undecidable == ()


# ----------------------------------------------------------------- guards


def test_underpowered_run_decides_nothing():
    findings = evaluate(_rs("underpowered"), CFG)
    decided = [f for f in findings if f.verdict in (KEEP, KILL)]
    assert decided == [], "a 5-case run must not produce a verdict"
    assert any("underpowered" in w for f in findings for w in f.warnings)


def test_win_bought_with_more_budget_is_withheld():
    finding = _finding(_rs("budget_bought_win"), "14.1")
    assert finding.verdict == INCONCLUSIVE
    assert finding.comparisons[0].superior, "the raw numbers still show the win"
    assert any("larger budget" in w for w in finding.warnings)


def test_loss_on_a_smaller_budget_is_not_a_refutation():
    obj = make_run(
        "starved",
        [
            ArmSpec("full", 0.0, budget_tokens=1024.0),
            ArmSpec("code_only", 0.0, budget_tokens=8192.0),
            ArmSpec("bm25", 0.0, budget_tokens=8192.0),
        ],
        seed=6, noise=0.01,
    )
    finding = _finding(ResultSet.from_obj(obj), "14.1")
    assert finding.verdict == INCONCLUSIVE
    assert any("starvation" in w for w in finding.warnings)


def test_kill_stands_when_the_treatment_had_the_larger_budget():
    obj = make_run(
        "generous-and-still-losing",
        [
            ArmSpec("full", 0.0, budget_tokens=8192.0),
            ArmSpec("code_only", 0.0, budget_tokens=2048.0),
            ArmSpec("bm25", 0.0, budget_tokens=2048.0),
        ],
        seed=7, noise=0.01,
    )
    finding = _finding(ResultSet.from_obj(obj), "14.1")
    assert finding.verdict == KILL
    assert any("conservative" in w for w in finding.warnings)


def test_low_seed_count_is_flagged_on_every_decided_finding():
    obj = build_scenario("no_gain")
    obj["seeds"] = 1
    findings = evaluate(ResultSet.from_obj(obj), CFG)
    decided = [
        f for f in findings if f.verdict not in (NOT_EVALUABLE, UNDECIDABLE)
    ]
    assert decided
    assert all(any("seed(s)" in w for w in f.warnings) for f in decided)


# --------------------------------------------------- dynamic range
#
# The rule: before any comparison metric is reported, the gold-label plane x
# arm-reach cross-tab must show the comparison could have come out the other
# way.  Everything below is a way of failing that, and every one of them used
# to produce a number.


def test_a_gold_set_blind_to_the_distinguishing_planes_is_undecidable():
    """s08's defect in miniature: all gold labels in the code plane.

    ``full`` and ``code_only`` differ only in type/data/knowledge. With no
    gold label in any of those, the comparison cannot move in the refuting
    direction at any sample size -- and it used to report a tight interval
    and a KEEP.
    """
    finding = _finding(_rs("blind_query_set"), "14.1")
    assert finding.verdict == UNDECIDABLE
    assert finding.comparisons == ()
    assert "zero gold labels" in finding.rationale
    for plane in ("data", "knowledge", "type"):
        assert plane in finding.rationale


def test_enlarging_a_blind_query_set_does_not_buy_a_verdict():
    """The 600 -> 738 move, generalised: n grows, the observation does not.

    s08 measured the discordant counts staying *identical* while n grew 23%.
    A rule that counts cases sees a tighter interval; the rule that asks
    whether the distinguishing observation is present sees nothing new.
    """
    small = ResultSet.from_obj(
        make_run("blind-small", [ArmSpec("full", 0.15), ArmSpec("code_only", 0.0),
                                 ArmSpec("bm25", 0.0)],
                 n_cases=60, seed=7, noise=0.01, gold_planes=["code"])
    )
    big = ResultSet.from_obj(
        make_run("blind-big", [ArmSpec("full", 0.15), ArmSpec("code_only", 0.0),
                               ArmSpec("bm25", 0.0)],
                 n_cases=1800, seed=7, noise=0.01, gold_planes=["code"])
    )
    assert _finding(small, "14.1").verdict == UNDECIDABLE
    assert _finding(big, "14.1").verdict == UNDECIDABLE, (
        "a 30x larger blind query set must not become decidable"
    )


def test_a_run_with_no_declared_gold_planes_reports_no_number():
    """Unknown dynamic range is refused, not assumed adequate."""
    obj = build_scenario("fusion_attested_keep")
    obj.pop("gold_planes")
    findings = evaluate(ResultSet.from_obj(obj), CFG)
    decided = [f for f in findings if f.verdict in (KEEP, KILL, INCONCLUSIVE)]
    assert decided == [], [f.plan_ref for f in decided]
    assert all(f.comparisons == () for f in findings)
    assert any("no gold-label planes" in f.rationale for f in findings)


def test_an_arm_pinned_at_a_structural_ceiling_is_refused():
    """s02's 100% annotation ceiling, in retrieval coordinates.

    A control that scores 1.0 on every case cannot lose, so the difference
    against it measures the ceiling, not the treatment.
    """
    obj = make_run(
        "ceilinged",
        [ArmSpec("full", 0.15), ArmSpec("code_only", 0.0), ArmSpec("bm25", 0.0)],
        n_cases=40, seed=8, noise=0.01,
    )
    metric = obj["primary_metric"]
    for arm in obj["arms"]:
        if arm["role"] == "code_only":
            arm["scores"][metric] = {c: 1.0 for c in obj["cases"]}
    finding = _finding(ResultSet.from_obj(obj), "14.1")
    assert finding.verdict == UNDECIDABLE
    assert "100% ceiling" in finding.rationale


def test_an_arm_that_cannot_reach_any_gold_plane_is_refused():
    """A structural 0%: the arm's index holds none of the answers."""
    obj = make_run(
        "blind-arm",
        [
            ArmSpec("full", 0.15, returns_planes=["knowledge"]),
            ArmSpec("code_only", 0.0),
            ArmSpec("bm25", 0.0, returns_planes=["knowledge"]),
        ],
        n_cases=40, seed=9, noise=0.01, gold_planes=["code"],
    )
    finding = _finding(ResultSet.from_obj(obj), "14.1")
    assert finding.verdict == UNDECIDABLE
    assert "structural floor" in finding.rationale


def test_no_criterion_can_report_a_comparison_without_passing_the_gate(monkeypatch):
    """The gate lives in the one function every comparison goes through.

    Forcing ``range_refusal`` to refuse must silence *every* criterion. A
    criterion that still produced a number would be computing its comparison
    somewhere else.
    """
    from . import criteria as criteria_mod
    from .plane_range import Refusal

    monkeypatch.setattr(
        criteria_mod, "range_refusal",
        lambda rs, treat, base, cases: Refusal("forced refusal for the mutation probe"),
    )
    findings = evaluate(_rs("fusion_attested_keep"), CFG)
    assert all(f.comparisons == () for f in findings)
    assert all(
        f.verdict in (UNDECIDABLE, NOT_EVALUABLE) for f in findings
    ), [(f.plan_ref, f.verdict) for f in findings]


# ------------------------------------------------- the fusion label attack


def test_a_relabelled_arm_cannot_mint_a_fusion_verdict():
    """The measured attack, re-run at four depths.

    Before this slice, changing one string -- role ``bm25`` to role
    ``fusion`` -- on the real s08 frozen-600 routing run produced
    ``14.3 verdict=KILL``, with no warning anywhere in the report, for a
    comparison nobody ran.
    """
    base = measured_inputs.build("s08_routing_frozen600_union_no_fusion")

    def relabel(mutate=None):
        obj = json.loads(json.dumps(base))
        for arm in obj["arms"]:
            if arm["role"] == "bm25":
                arm["role"] = "fusion"
                if mutate:
                    mutate(arm)
        return _finding(ResultSet.from_obj(obj), "14.3")

    # 1. the bare relabel
    assert relabel().verdict == UNDECIDABLE
    # 2. relabel + a forged attestation with no measured returns
    forged = {
        "implementation": "totally_real_fusion.py::Fusion@deadbeef",
        "mechanism": "cross_plane_score_fusion",
        "combines_planes": ["code", "type", "data", "knowledge"],
    }
    f2 = relabel(lambda a: a.update(retriever=dict(forged)))
    assert f2.verdict == UNDECIDABLE
    assert "no measured per-plane return counts" in f2.rationale

    # 3. forged attestation + a single-plane return histogram
    def single_plane(arm):
        arm["retriever"] = dict(forged)
        arm["returned_plane_counts"] = {"code": 6000}

    f3 = relabel(single_plane)
    assert f3.verdict == UNDECIDABLE
    assert "single-plane retriever" in f3.rationale

    # 4. an attestation claiming fusion over one plane
    def one_plane_fusion(arm):
        arm["retriever"] = dict(forged, combines_planes=["code"])
        arm["returned_plane_counts"] = {"code": 3000, "knowledge": 3000}

    assert relabel(one_plane_fusion).verdict == UNDECIDABLE

    # 5. the realistic one, and the only depth the *mechanism* check catches:
    #    the joint index really does span four planes and really does return
    #    documents from more than one, so every other check is satisfied. It
    #    shares an IDF space; it compares no score across planes. This is the
    #    exact substitution s08 had to retract, one level up.
    def honest_looking_joint_index(arm):
        arm["retriever"] = {
            "implementation": "s08_retrievers.py::LexicalRetriever@a0c8fabd",
            "mechanism": "single_index",
            "combines_planes": ["code", "type", "data", "knowledge"],
        }
        arm["returned_plane_counts"] = {
            "code": 3000, "type": 1000, "data": 500, "knowledge": 1500,
        }

    f5 = relabel(honest_looking_joint_index)
    assert f5.verdict == UNDECIDABLE
    assert "does not compare or combine scores across planes" in f5.rationale


def test_a_missing_fusion_arm_never_falls_back_to_the_full_arm():
    """The deleted ``or rs.find("full", ...)``.

    A run carrying ``full`` and ``separate_indices`` and no fusion arm used to
    grade 14.3 as if the full arm were the fusion arm -- measured KEEP on the
    synthetic scenario, and the same path is what produced the KILL above.
    """
    rs = _rs("surviving_prior")
    assert rs.find("full", "raw") is not None
    assert rs.find("separate_indices", "raw") is not None
    assert rs.find("fusion", "raw") is None
    finding = _finding(rs, "14.3")
    assert finding.verdict == UNDECIDABLE
    assert "no fallback to another role" in finding.rationale
    assert finding.comparisons == ()


def test_the_fusion_arm_is_read_from_the_mechanism_not_the_role(monkeypatch):
    arm, refusal = fusion_arm(_rs("fusion_attested_keep"), "raw")
    assert refusal is None and arm.role == "fusion"
    assert arm.retriever.mechanism == "cross_plane_score_fusion"


# ------------------------------------------ the three refusals stay apart


def test_undecidable_is_distinct_from_inconclusive_and_not_evaluable():
    """Three different states, three different remedies.

    INCONCLUSIVE -> run more. NOT_EVALUABLE -> ship the arm. UNDECIDABLE ->
    neither helps; build a query set or a graph that contains the
    distinguishing observation. Collapsing them is how the category error
    hides, because the remedy INCONCLUSIVE invites is exactly the one that
    walks a blind run to a verdict.
    """
    assert len({UNDECIDABLE, INCONCLUSIVE, NOT_EVALUABLE}) == 3
    underpowered = _finding(_rs("underpowered"), "14.1").verdict
    missing_arm = _finding(_rs("no_gain"), "14.2").verdict
    blind = _finding(_rs("blind_query_set"), "14.1").verdict
    assert (underpowered, missing_arm, blind) == (
        INCONCLUSIVE, NOT_EVALUABLE, UNDECIDABLE
    )


def test_the_rollup_shows_undecidable_separately_from_a_missing_arm():
    findings = evaluate(_rs("intra_plane_graph"), CFG)
    twin = [p for p in roll_up(findings) if p.prior == "four_plane_project_twin"][0]
    assert "14.2" in twin.undecidable
    assert "14.2" not in twin.uninstrumented
    assert twin.verdict != KEEP
    text = render(build(_rs("intra_plane_graph"), findings, CFG))
    assert "UNDECIDABLE" in text
    assert "UNDECIDABLE on this data at any sample size: 14.2" in text


def test_undecidable_does_not_count_as_covered():
    rs = _rs("blind_query_set")
    rep = build(rs, evaluate(rs, CFG), CFG)
    counts = rep.verdict_counts
    assert counts[UNDECIDABLE] > 0
    assert rep.coverage[0] == counts[KEEP] + counts[KILL] + counts[INCONCLUSIVE]
    assert to_json(rep)["verdict_counts"][UNDECIDABLE] == counts[UNDECIDABLE]


def test_the_crosstab_is_printed_before_the_criteria():
    rs = _measured("s08_routing_extended738_union_no_fusion")
    text = render(build(rs, evaluate(rs, CFG), CFG))
    assert "GOLD-LABEL PLANE x PLANE EACH ARM CAN RETURN" in text
    assert text.index("GOLD-LABEL PLANE") < text.index("CRITERIA")
    assert "never a retrieval target" in text


# -------------------------------------------- what the program cannot ask


def test_the_type_plane_is_never_a_retrieval_target_anywhere():
    """289 documents, 27.9% of the corpus, and zero gold labels in any set.

    No criterion that names the type plane can be decided by any measurement
    this program has produced.
    """
    census = measured_inputs.program_plane_census()
    assert census["documents"]["type"] == 289
    assert census["gold_labels"]["type"] == 0
    assert measured_inputs.planes_never_a_retrieval_target() == ("type",)
    for name in measured_inputs.MEASURED_RUNS:
        ct = crosstab(_measured(name))
        assert "type" in ct.never_targeted(), name


def test_every_measured_run_decides_nothing_about_the_four_plane_prior():
    """The headline, as an assertion rather than a sentence in a report.

    On today's artifacts this evaluator decides *none* of the criteria that
    bear on the four-plane prior: the two it can reach are UNDECIDABLE and
    the rest have no arm.
    """
    for name in measured_inputs.MEASURED_RUNS:
        findings = evaluate(_measured(name), CFG)
        twin = [
            p for p in roll_up(findings) if p.prior == "four_plane_project_twin"
        ][0]
        assert twin.decided == 0, (name, twin.verdict)
        assert twin.verdict == UNDECIDABLE, name
        assert set(twin.undecidable) == {"14.2", "14.3"}, name


# ----------------------------------------------------------------- report


def test_one_kill_outranks_any_number_of_passes():
    findings = evaluate(_rs("rewire_kill"), CFG)
    twin = [p for p in roll_up(findings) if p.prior == "four_plane_project_twin"][0]
    assert twin.verdict == KILL
    assert twin.killed_by == ("14.2",)


def test_inconclusive_never_rolls_up_to_keep():
    findings = evaluate(_rs("underpowered"), CFG)
    verdicts = {p.prior: p.verdict for p in roll_up(findings)}
    assert KEEP not in verdicts.values()


def test_report_declares_itself_advisory_and_states_coverage():
    rs = _rs("fusion_attested_keep")
    rep = build(rs, evaluate(rs, CFG), CFG)
    blob = to_json(rep)
    assert blob["advisory"] is True
    # The denominator is the number of bullets in the living plan, computed --
    # the published 60% came from dividing 9 decided criteria by a register
    # that had silently lost one, and no constant here may reintroduce that.
    n_plan = plan_register.load_section().n_extracted
    assert blob["coverage"]["criteria"] == n_plan
    assert blob["coverage"]["decided"] == len(EVALUATORS)
    assert blob["coverage"]["fraction"] == pytest.approx(len(EVALUATORS) / n_plan)
    assert json.dumps(blob)  # serialisable


def test_rendered_report_is_pure_ascii():
    """Windows consoles are not UTF-8; a report that cannot print is useless."""
    for name in SCENARIOS:
        rs = _rs(name)
        text = render(build(rs, evaluate(rs, CFG), CFG))
        text.encode("ascii")
        assert "ADVISORY" in text


# -------------------------------------------------------------------- cli


def test_cli_exit_code_never_encodes_the_verdict(capsys):
    from .cli import main

    assert main(["--demo", "no_gain", "--resamples", "200"]) == 0
    assert "[KILL]" in capsys.readouterr().out, "the kill is reported in the text"


def test_cli_rejects_a_bad_input_with_a_nonzero_code(tmp_path, capsys):
    from .cli import main

    bad = tmp_path / "bad.json"
    bad.write_text('{"schema": "nope/1", "run_id": "x"}', encoding="utf-8")
    assert main([str(bad)]) == 2
    assert "input rejected" in capsys.readouterr().err


def test_cli_json_output_parses(capsys):
    from .cli import main

    assert main(["--demo", "rewire_kill", "--resamples", "200", "--json"]) == 0
    blob = json.loads(capsys.readouterr().out)
    assert blob["advisory"] is True
    assert any(f["verdict"] == KILL for f in blob["findings"])


def test_cli_reads_a_real_file(tmp_path, capsys):
    from .cli import main

    path = tmp_path / "run.json"
    path.write_text(json.dumps(build_scenario("no_gain")), encoding="utf-8")
    assert main([str(path), "--resamples", "200"]) == 0
    assert "[KILL] 14.1" in capsys.readouterr().out


def test_cli_names_the_planes_no_measurement_can_target(capsys):
    from .cli import main

    assert main(["--plane-census"]) == 0
    out = capsys.readouterr().out
    assert "type" in out and "289" in out
    assert "never be a retrieval target anywhere in the program: type" in out
