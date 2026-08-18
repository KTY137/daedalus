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
    EvalConfig,
    evaluate,
    register_entries,
)
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
    decided = [f for f in findings if f.verdict != NOT_EVALUABLE]
    assert len(decided) == 9
    assert all(f.verdict == KEEP for f in decided)


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


def test_separate_indices_equivalence_fires():
    obj = make_run(
        "fusion-pointless",
        [
            ArmSpec("full", 0.15),
            ArmSpec("code_only", 0.0),
            ArmSpec("bm25", 0.0),
            ArmSpec("separate_indices", 0.15),
        ],
        seed=4, noise=0.01,
    )
    assert _finding(ResultSet.from_obj(obj), "14.3").verdict == KILL


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


def test_a_real_measurement_reaches_the_criterion_it_instruments():
    """14.2 is *asked* of the s08 data -- not skipped as unevaluable."""
    finding = _finding(_measured("s08_graph_structure"), "14.2")
    assert finding.verdict != NOT_EVALUABLE
    comp = finding.comparisons[0]
    assert comp.n == 600
    assert (comp.wins, comp.losses) == (13, 7)


def test_a_run_without_a_fusion_arm_refuses_to_decide_the_fusion_criterion():
    """s08 built no fusion retriever, so 14.3 must not be answered from it.

    The tempting shortcut is to let the nearest available arm stand in for the
    missing one; that is how a criterion gets 'decided' by a comparison nobody
    ran.
    """
    finding = _finding(_measured("s08_plane_routing"), "14.3")
    assert finding.verdict == NOT_EVALUABLE
    assert "fusion|full" in finding.missing


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
    """The guard above must not make KEEP unreachable in principle."""
    twin = [
        p for p in roll_up(evaluate(_rs("surviving_prior"), CFG))
        if p.prior == "four_plane_project_twin"
    ][0]
    assert twin.verdict == KEEP
    assert twin.uninstrumented == ()


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
    decided = [f for f in findings if f.verdict != NOT_EVALUABLE]
    assert decided
    assert all(any("seed(s)" in w for w in f.warnings) for f in decided)


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
    rs = _rs("surviving_prior")
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
