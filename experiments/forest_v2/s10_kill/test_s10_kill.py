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
from .criteria import (
    INCONCLUSIVE,
    KEEP,
    KILL,
    NOT_EVALUABLE,
    OUT_OF_SCOPE,
    EvalConfig,
    evaluate,
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


def test_six_criteria_are_always_out_of_scope_and_say_why():
    findings = evaluate(_rs("surviving_prior"), CFG)
    out = [f for f in findings if f.verdict == NOT_EVALUABLE]
    assert len(out) == len(OUT_OF_SCOPE)
    assert all(f.rationale for f in out)
    assert len(findings) == 15, "the plan lists 15 kill criteria; all must appear"


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
    assert blob["coverage"] == {"decided": 9, "criteria": 15}
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
