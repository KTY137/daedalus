# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Tests for daedalus.spine.picker.

Two properties carry this file. First, ORDER IS REPRODUCIBLE: the same inputs
must produce the same queue, byte for byte, or "measurement picks the next
task" is unfalsifiable. Second, NOTHING RUNS UNLESS ASKED: the dry-run tests
inject an attempt function that raises, so "no attempt happened" is proved by
the absence of an exception rather than assumed.

Every source is fed a fixture. No model, no network, no eval run, no index
build, and no git.
"""
import json

import pytest

import daedalus.spine.picker as picker
from daedalus.spine.picker import (
    BAND_SPAN,
    SOURCE_BANDS,
    Candidate,
    NoEvidence,
    build_queue,
    eval_baseline_candidates,
    eval_gate_candidates,
    hotspot_candidates,
    inventory_candidates,
    load_inventory,
    rank,
    render_queue,
    review_packet,
)


# --------------------------------------------------------------------------- #
# fixtures                                                                     #
# --------------------------------------------------------------------------- #
INVENTORY = {
    "schema": "daedalus-feature-inventory/1",
    "repo_state": {"branch": "fixture", "head": "abc1234", "dirty": False},
    "islands": ["prose island one", "prose island two"],
    "stale": ["prose stale one"],
    "areas": [
        {
            "area": "Alpha area",
            "features": [
                {"name": "Wired thing", "status": "wired",
                 "entrypoints": ["daedalus/wired.py"], "tests": ["tests/a.py"]},
                {"name": "Tested island", "status": "island",
                 "entrypoints": ["daedalus/tested_island.py"],
                 "tests": ["tests/test_tested_island.py"],
                 "notes": "built, nothing calls it"},
                {"name": "Bare island", "status": "island",
                 "entrypoints": ["daedalus/bare_island.py"],
                 "tests": [], "notes": ""},
            ],
        },
        {
            "area": "Beta area",
            "features": [
                {"name": "Rich island", "status": "island",
                 "entrypoints": ["daedalus/rich.py", "python -m daedalus.rich"],
                 "tests": ["tests/t1.py", "tests/t2.py", "tests/t3.py"],
                 "notes": "three test files"},
                {"name": "Old build output", "status": "stale",
                 "entrypoints": ["build/lib/", "build/bdist/"],
                 "tests": [], "notes": "packaged copies"},
                {"name": "Planned thing", "status": "planned"},
            ],
        },
    ],
}

BASELINE = {
    "schema": 1,
    "tasks": {
        "task_full": {"recall": 1.0, "tier": "primary",
                      "label_provenance": "hand_reachable"},
        "task_half": {"recall": 0.5, "tier": "primary",
                      "label_provenance": "independent_diff"},
        "task_low": {"recall": 0.25, "tier": "quarantine",
                     "label_provenance": "temporal_churn"},
    },
}

GATE_RESULT = {
    "passed": False,
    "regressions": [
        {"id": "slice_semantic_slice", "baseline_recall": 1.0,
         "current_recall": 0.6, "missed": ["extract_units"]},
    ],
    "errored_primary": [
        {"id": "web_api_file", "target": "daedalus/web_api.py",
         "error": "FileNotFoundError: gone"},
    ],
    "errored_quarantine": [{"id": "minted_1", "error": "whatever"}],
}

INDEX = {
    "hotspots": [
        {"module": "daedalus/big.py", "score": 200.0, "loc": 900,
         "long_functions": 6, "guard_count": 4, "cc_max": 22, "churn": 5000},
        {"module": "daedalus/mid.py", "score": 100.0, "loc": 400,
         "long_functions": 2, "guard_count": 1, "cc_max": 9, "churn": 900},
        {"module": "daedalus/small.py", "score": 10.0, "loc": 80,
         "long_functions": 0, "guard_count": 0, "cc_max": 3, "churn": 20},
    ],
}


@pytest.fixture
def no_eval(monkeypatch):
    """Keep the cheap eval source hermetic (never read the repo's baseline)."""
    monkeypatch.setattr(picker, "_load_baseline", lambda: ({}, None))
    return monkeypatch


def _write_inventory(tmp_path, payload):
    docs = tmp_path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    path = docs / "FEATURE_INVENTORY.json"
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")
    return tmp_path


class Boom(Exception):
    pass


def _explode(candidate, args):
    raise Boom("an attempt was run when none should have been")


# --------------------------------------------------------------------------- #
# every candidate carries evidence                                             #
# --------------------------------------------------------------------------- #
def test_every_candidate_carries_a_reason_a_score_and_evidence():
    inv, _ = inventory_candidates(INVENTORY)
    ev, _ = eval_baseline_candidates(BASELINE)
    gate, _ = eval_gate_candidates(GATE_RESULT)
    hot, _ = hotspot_candidates(INDEX)
    everything = list(inv) + list(ev) + list(gate) + list(hot)
    assert everything, "fixtures should produce candidates from every source"
    for c in everything:
        assert isinstance(c, Candidate)
        assert c.reason.strip(), c.task_id
        assert isinstance(c.score, float) and c.score > 0, c.task_id
        assert c.evidence, c.task_id
        # The evidence must name where the number came from, so a reviewer can
        # go and check it rather than trusting the score.
        assert c.evidence.get("measurement"), c.task_id
        assert c.instruction.strip(), c.task_id


def test_candidate_without_evidence_is_refused_not_silently_dropped():
    with pytest.raises(NoEvidence):
        picker._candidate(task_id="x", source="hotspot", instruction="do it",
                          reason="because", band_offset=1.0, evidence={})
    with pytest.raises(NoEvidence):
        picker._candidate(task_id="x", source="hotspot", instruction="do it",
                          reason="   ", band_offset=1.0, evidence={"a": 1})
    with pytest.raises(NoEvidence):
        picker._candidate(task_id="x", source="made_up", instruction="do it",
                          reason="because", band_offset=1.0, evidence={"a": 1})


def test_measured_offset_can_never_cross_a_band():
    # The prior must not be overridable by a measurement; that is the whole
    # reason band and offset are separate numbers.
    gaps = sorted(SOURCE_BANDS.values())
    smallest_gap = min(b - a for a, b in zip(gaps, gaps[1:]))
    assert BAND_SPAN < smallest_gap
    c = picker._candidate(task_id="x", source="hotspot", instruction="i",
                          reason="r", band_offset=10_000.0, evidence={"a": 1})
    assert c.score == SOURCE_BANDS["hotspot"] + BAND_SPAN
    c2 = picker._candidate(task_id="x", source="hotspot", instruction="i",
                           reason="r", band_offset=-5.0, evidence={"a": 1})
    assert c2.score == SOURCE_BANDS["hotspot"]


# --------------------------------------------------------------------------- #
# ranking determinism                                                          #
# --------------------------------------------------------------------------- #
def test_ranking_is_deterministic_for_a_fixed_inventory(no_eval, tmp_path):
    _write_inventory(tmp_path, INVENTORY)
    runs = [build_queue(tmp_path, limit=None) for _ in range(5)]
    ids = [[c.task_id for c in q.candidates] for q in runs]
    assert all(row == ids[0] for row in ids)
    scores = [[c.score for c in q.candidates] for q in runs]
    assert all(row == scores[0] for row in scores)
    # Rendered output is the operator-facing artifact; it must be stable too.
    rendered = [render_queue(q) for q in runs]
    assert all(r == rendered[0] for r in rendered)


def test_ranking_is_insensitive_to_input_order():
    inv, _ = inventory_candidates(INVENTORY)
    ev, _ = eval_baseline_candidates(BASELINE)
    hot, _ = hotspot_candidates(INDEX)
    forward = rank(list(inv) + list(ev) + list(hot))
    backward = rank(list(hot) + list(ev) + list(inv))
    shuffled = rank(list(ev) + list(inv)[::-1] + list(hot))
    assert [c.task_id for c in forward] == [c.task_id for c in backward]
    assert [c.task_id for c in forward] == [c.task_id for c in shuffled]


def test_ties_break_on_task_id_not_on_arrival():
    a = picker._candidate(task_id="zzz", source="hotspot", instruction="i",
                          reason="r", band_offset=5.0, evidence={"m": 1})
    b = picker._candidate(task_id="aaa", source="hotspot", instruction="i",
                          reason="r", band_offset=5.0, evidence={"m": 1})
    assert a.score == b.score
    assert [c.task_id for c in rank([a, b])] == ["aaa", "zzz"]
    assert [c.task_id for c in rank([b, a])] == ["aaa", "zzz"]


def test_source_priority_order_holds_across_sources(no_eval, tmp_path):
    _write_inventory(tmp_path, INVENTORY)
    q = build_queue(tmp_path, limit=None, baseline=BASELINE)
    seen = [c.source for c in q.candidates]
    order = {"inventory_island": 0, "inventory_stale": 1, "eval_miss": 2,
             "hotspot": 3}
    ranks = [order[s] for s in seen]
    assert ranks == sorted(ranks), seen


def test_more_tested_island_outranks_less_tested_island():
    inv, _ = inventory_candidates(INVENTORY)
    by_name = {c.task_id.split("-")[1]: c for c in inv
               if c.source == "inventory_island"}
    assert by_name["rich"].score > by_name["tested"].score
    assert by_name["tested"].score > by_name["bare"].score
    assert by_name["rich"].evidence["n_tests"] == 3
    assert by_name["bare"].evidence["n_tests"] == 0


def test_limit_truncates_the_ranked_queue_not_the_sources(no_eval, tmp_path):
    _write_inventory(tmp_path, INVENTORY)
    full = build_queue(tmp_path, limit=None)
    short = build_queue(tmp_path, limit=2)
    assert len(short) == 2
    assert [c.task_id for c in short.candidates] == \
        [c.task_id for c in full.candidates[:2]]
    assert short.sources["inventory"]["candidates"] == \
        full.sources["inventory"]["candidates"]


# --------------------------------------------------------------------------- #
# degradation                                                                  #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("payload", [
    "",                       # empty file
    "not json at all",        # unparseable
    "[1, 2, 3]",              # valid JSON, wrong shape
    "{}",                     # object with no areas
    '{"areas": "nope"}',      # areas is not a list
    '{"areas": [null, 7]}',   # areas holds junk
    '{"areas": [{"features": "nope"}]}',
    '{"areas": [{"features": [{"status": "island"}]}]}',   # unnamed feature
])
def test_malformed_inventory_degrades_to_an_empty_queue(no_eval, tmp_path,
                                                        payload):
    _write_inventory(tmp_path, payload)
    q = build_queue(tmp_path, limit=None)
    assert q.candidates == ()
    assert q.top is None
    # An empty queue must still say WHY it is empty.
    assert q.sources["inventory"]["candidates"] == 0
    render_queue(q)  # must not raise


def test_missing_inventory_file_is_an_empty_inventory_not_a_crash(no_eval,
                                                                  tmp_path):
    assert load_inventory(repo_root=tmp_path) == {}
    q = build_queue(tmp_path, limit=None)
    assert q.candidates == ()


def test_prose_arrays_are_never_queued_but_the_discrepancy_is_reported():
    candidates, notes = inventory_candidates(INVENTORY)
    # 2 prose islands vs 3 structured; 1 prose stale vs 1 structured.
    assert len([c for c in candidates if c.source == "inventory_island"]) == 3
    assert len([c for c in candidates if c.source == "inventory_stale"]) == 1
    joined = " ".join(notes)
    assert "prose 'islands'" in joined
    assert "prose 'stale'" not in joined      # those counts agree


def test_a_broken_eval_baseline_does_not_empty_the_queue(monkeypatch, tmp_path):
    _write_inventory(tmp_path, INVENTORY)
    monkeypatch.setattr(picker, "_load_baseline",
                        lambda: ({}, "RuntimeError: eval is on fire"))
    q = build_queue(tmp_path, limit=None)
    assert q.candidates, "inventory work must survive a broken eval"
    assert any("eval is on fire" in n for n in q.notes)


# --------------------------------------------------------------------------- #
# eval + hotspot sources                                                       #
# --------------------------------------------------------------------------- #
def test_cheap_eval_source_queues_only_recorded_misses_and_says_so():
    candidates, notes = eval_baseline_candidates(BASELINE)
    ids = {c.evidence["recall"] for c in candidates}
    assert ids == {0.5, 0.25}          # the 1.0 task is not work
    worst = max(candidates, key=lambda c: c.score)
    assert worst.evidence["recall"] == 0.25
    joined = " ".join(notes)
    assert "not 'the eval passes now'" in joined
    for c in candidates:
        assert "stored, not a fresh run" in c.evidence["measurement"]


def test_eval_gate_source_queues_regressions_and_unmeasurable_primaries():
    candidates, notes = eval_gate_candidates(GATE_RESULT)
    by_kind = {c.task_id.split("-")[1]: c for c in candidates}
    assert set(by_kind) == {"regression", "errored"}
    assert by_kind["regression"].evidence["delta"] == pytest.approx(-0.4)
    # A task that cannot be measured at all tops its band -- no number is worse
    # than a low number.
    assert by_kind["errored"].score == SOURCE_BANDS["eval_miss"] + BAND_SPAN
    assert by_kind["errored"].score > by_kind["regression"].score
    # Quarantine debris must never become work.
    assert not any("minted_1" in c.task_id for c in candidates)
    assert any("FAILED" in n for n in notes)


def test_hotspots_rank_by_measured_score_share():
    candidates, _ = hotspot_candidates(INDEX)
    assert [c.evidence["module"] for c in candidates] == \
        ["daedalus/big.py", "daedalus/mid.py", "daedalus/small.py"]
    top, mid = candidates[0], candidates[1]
    assert top.score == SOURCE_BANDS["hotspot"] + BAND_SPAN
    assert mid.offset == pytest.approx(BAND_SPAN * 0.5)
    assert top.evidence["churn"] == 5000


def test_hotspots_degrade_when_the_index_carries_no_ranking():
    for idx in ({}, {"hotspots": []}, {"hotspots": [{"module": "a",
                                                     "score": 0}]}):
        candidates, notes = hotspot_candidates(idx)
        assert candidates == ()
        assert notes


def test_expensive_sources_are_off_by_default(no_eval, tmp_path, monkeypatch):
    _write_inventory(tmp_path, INVENTORY)

    def _boom(*a, **k):
        raise AssertionError("an opt-in source ran without being asked")

    monkeypatch.setattr(picker, "_run_eval_gate", _boom)
    monkeypatch.setattr(picker, "_load_index", _boom)
    q = build_queue(tmp_path, limit=None)
    assert q.sources["eval_gate"]["ran"] is False
    assert q.sources["hotspots"]["ran"] is False
    assert "opt-in" in q.sources["eval_gate"]["reason"]
    assert "opt-in" in q.sources["hotspots"]["reason"]


def test_opt_in_sources_are_consulted_when_asked(no_eval, tmp_path,
                                                 monkeypatch):
    _write_inventory(tmp_path, INVENTORY)
    monkeypatch.setattr(picker, "_run_eval_gate", lambda: (GATE_RESULT, None))
    monkeypatch.setattr(picker, "_load_index", lambda root: (INDEX, None))
    q = build_queue(tmp_path, limit=None, include_eval=True,
                    include_hotspots=True)
    sources = {c.source for c in q.candidates}
    assert {"inventory_island", "inventory_stale", "eval_miss",
            "hotspot"} <= sources
    assert q.sources["eval_gate"]["ran"] is True
    assert q.sources["hotspots"]["candidates"] == 3


def test_a_failing_opt_in_source_is_reported_not_raised(no_eval, tmp_path,
                                                        monkeypatch):
    _write_inventory(tmp_path, INVENTORY)
    monkeypatch.setattr(picker, "_run_eval_gate", lambda: (None, "Boom: x"))
    monkeypatch.setattr(picker, "_load_index", lambda root: (None, "Boom: y"))
    q = build_queue(tmp_path, limit=None, include_eval=True,
                    include_hotspots=True)
    assert q.candidates
    assert any("Boom: x" in n for n in q.notes)
    assert any("Boom: y" in n for n in q.notes)


# --------------------------------------------------------------------------- #
# TaskSpec compatibility                                                       #
# --------------------------------------------------------------------------- #
def test_candidates_convert_to_a_real_taskspec_carrying_the_evidence():
    from daedalus.spine.attempt import TaskSpec

    inv, _ = inventory_candidates(INVENTORY)
    c = rank(inv)[0]
    spec = c.to_task_spec(base_revision="deadbeef")
    assert isinstance(spec, TaskSpec)
    assert spec.task_id == c.task_id
    assert spec.instruction == c.instruction
    assert spec.base_revision == "deadbeef"
    assert spec.gate_paths == c.gate_paths
    assert spec.metadata["picker_reason"] == c.reason
    assert spec.metadata["picker_score"] == c.score
    assert spec.metadata["picker_evidence"]["measurement"]
    # The spec must digest -- metadata that cannot be canonicalised would blow
    # up inside the attempt, after the intent was recorded.
    assert len(spec.digest) == 64


def test_island_gate_paths_come_from_the_recorded_tests():
    inv, _ = inventory_candidates(INVENTORY)
    by_name = {c.task_id.split("-")[1]: c for c in inv}
    assert by_name["rich"].gate_paths == ("tests/t1.py", "tests/t2.py",
                                          "tests/t3.py")
    # No recorded tests -> no subset -> the whole suite is the gate.
    assert by_name["bare"].gate_paths == ()


# --------------------------------------------------------------------------- #
# the review packet                                                            #
# --------------------------------------------------------------------------- #
class FakeGate:
    passed = False
    name = "pytest"
    command = ("python", "-m", "pytest", "-q")
    returncode = 1
    output = "collected 3 items\nE   assert 1 == 2\n1 failed, 2 passed\n"
    duration_s = 12.5
    cancelled = False
    timed_out = False


class FakeArtifact:
    diff_sha256 = "f" * 64
    byte_length = 42
    changed_paths = ("daedalus/tested_island.py", "tests/test_tested_island.py")
    diff = ("--- a/daedalus/tested_island.py\n"
            "+++ b/daedalus/tested_island.py\n"
            "@@ -1 +1,2 @@\n"
            "+from daedalus.cli import wire_me\n")


class FakeResult:
    state = "gates_failed"
    task_id = "island-tested-island-abc123"
    branch = "daedalus-attempt-island-tested-island-abc123"
    base_revision = "0123456789abcdef"
    intent_id = 7
    duration_s = 30.2
    worktree_path = r"C:\tmp\wt"
    worktree_removed = True
    cleanup_error = None
    ledger_error = None
    error = "gate 'pytest' failed (exit 1)"
    artifact_path = r"C:\tmp\patches\ffff.patch"
    artifact = FakeArtifact()
    gates = FakeGate()


def test_review_packet_contains_the_diff_and_the_gate_verdict():
    inv, _ = inventory_candidates(INVENTORY)
    candidate = rank(inv)[0]
    packet = review_packet(candidate, FakeResult())

    # the diff, verbatim
    assert "+from daedalus.cli import wire_me" in packet
    assert "--- a/daedalus/tested_island.py" in packet
    assert FakeArtifact.diff_sha256 in packet
    assert "daedalus/tested_island.py" in packet

    # the gate verdict, and the evidence behind it
    assert "GATE: FAIL" in packet
    assert "exit=1" in packet
    assert "1 failed, 2 passed" in packet
    assert "python -m pytest -q" in packet

    # why this task was chosen, with its measurement
    assert candidate.task_id in packet
    assert candidate.reason in packet
    assert "n_tests" in packet

    # and the human's next step, stated as the human's
    assert "NOTHING HAS BEEN APPLIED" in packet
    assert "discard" in packet
    assert FakeResult.artifact_path in packet
    assert "Promotion is a human decision." in packet


def test_review_packet_reports_a_passing_gate_as_evidence_not_permission():
    class Passing(FakeResult):
        state = "clean"
        gates = type("G", (FakeGate,), {"passed": True, "returncode": 0})()

    inv, _ = inventory_candidates(INVENTORY)
    packet = review_packet(rank(inv)[0], Passing())
    assert "GATE: PASS" in packet
    assert "EVIDENCE, not permission" in packet


def test_review_packet_does_not_offer_a_reaped_branch_for_inspection():
    class Reaped(FakeResult):
        reaped = ({
            "branch": FakeResult.branch,
            "action": "deleted",
            "reason": "candidate branch held no unique work",
        },)

    inv, _ = inventory_candidates(INVENTORY)
    packet = review_packet(rank(inv)[0], Reaped())

    assert "git diff" not in packet
    assert f"git apply --index {FakeResult.artifact_path}" in packet


def test_review_packet_handles_an_attempt_that_produced_no_patch():
    class NoPatch(FakeResult):
        state = "no_change"
        artifact = None
        artifact_path = None
        gates = None

    inv, _ = inventory_candidates(INVENTORY)
    packet = review_packet(rank(inv)[0], NoPatch())
    assert "DIFF: none" in packet
    assert "GATE: not run" in packet
    assert "nothing to apply" in packet
    assert "git apply" not in packet


def test_an_empty_patch_never_offers_an_apply_command():
    # An empty diff is still captured, hashed and persisted; offering
    # 'git apply <empty>' would let "the runner did nothing" read as a change.
    class Empty(FakeResult):
        state = "no_change"
        artifact = type("A", (FakeArtifact,), {
            "diff": "", "diff_bytes": b"", "byte_length": 0,
            "changed_paths": (),
            "diff_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e46"
                           "49b934ca495991b7852b855"})()
        gates = None

    inv, _ = inventory_candidates(INVENTORY)
    packet = review_packet(rank(inv)[0], Empty())
    assert "DIFF: EMPTY" in packet
    assert "nothing to promote" in packet
    assert "nothing to apply" in packet
    assert "git apply" not in packet
    assert "git diff" not in packet


def test_review_packet_truncates_a_huge_diff_and_says_it_did():
    class Huge(FakeResult):
        artifact = type("A", (FakeArtifact,), {"diff": "x" * 5000})()

    inv, _ = inventory_candidates(INVENTORY)
    packet = review_packet(rank(inv)[0], Huge(), diff_limit=100)
    assert "truncated for display" in packet
    assert "the full patch is the artifact" in packet


# --------------------------------------------------------------------------- #
# the CLI                                                                      #
# --------------------------------------------------------------------------- #
def test_dry_run_performs_no_attempt(no_eval, tmp_path, capsys):
    _write_inventory(tmp_path, INVENTORY)
    code = picker.main(["--dry-run", "--limit", "5",
                        "--repo-root", str(tmp_path)],
                       attempt_fn=_explode)
    assert code == 0
    out = capsys.readouterr().out
    assert "ranked work queue" in out
    assert "nothing has been run" in out


def test_bare_invocation_defaults_to_the_dry_run(no_eval, tmp_path, capsys):
    _write_inventory(tmp_path, INVENTORY)
    code = picker.main(["--repo-root", str(tmp_path)], attempt_fn=_explode)
    assert code == 0
    assert "ranked work queue" in capsys.readouterr().out


def test_json_output_performs_no_attempt_either(no_eval, tmp_path, capsys):
    _write_inventory(tmp_path, INVENTORY)
    code = picker.main(["--json", "--repo-root", str(tmp_path)],
                       attempt_fn=_explode)
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["candidates"]
    for row in payload["candidates"]:
        assert row["reason"] and row["evidence"] and row["score"]


def test_once_attempts_exactly_one_candidate_and_prints_the_packet(
        no_eval, tmp_path, capsys):
    _write_inventory(tmp_path, INVENTORY)
    calls = []

    def _fake(candidate, args):
        calls.append(candidate)
        return FakeResult()

    code = picker.main(["--once", "--repo-root", str(tmp_path)],
                       attempt_fn=_fake)
    out = capsys.readouterr().out
    assert len(calls) == 1
    # It attempted the TOP of the queue, not an arbitrary one.
    expected = build_queue(tmp_path, limit=None).top
    assert calls[0].task_id == expected.task_id
    assert "HUMAN REVIEW PACKET" in out
    assert "+from daedalus.cli import wire_me" in out
    assert "GATE: FAIL" in out
    # A failed gate is a real outcome, but it must not exit 0.
    assert code == picker.EXIT_FAILED


@pytest.mark.parametrize("state,expected", [
    ("clean", picker.EXIT_CANDIDATE),
    ("no_change", picker.EXIT_NO_CHANGE),
    ("gates_failed", picker.EXIT_FAILED),
    ("runner_failed", picker.EXIT_FAILED),
    ("worktree_failed", picker.EXIT_FAILED),
    ("storage_unavailable", picker.EXIT_FAILED),
    ("cancelled", picker.EXIT_FAILED),
    ("some_future_state", picker.EXIT_FAILED),
])
def test_exit_code_says_zero_only_when_a_patch_is_waiting(no_eval, tmp_path,
                                                          capsys, state,
                                                          expected):
    _write_inventory(tmp_path, INVENTORY)
    result = type("R", (FakeResult,), {"state": state})()
    code = picker.main(["--once", "--repo-root", str(tmp_path)],
                       attempt_fn=lambda c, a: result)
    capsys.readouterr()
    assert code == expected
    # An unknown state must never be optimistic.
    assert picker.EXIT_CANDIDATE == 0


def test_once_on_an_empty_queue_runs_nothing_and_fails_loudly(no_eval,
                                                              tmp_path,
                                                              capsys):
    _write_inventory(tmp_path, "{}")
    code = picker.main(["--once", "--repo-root", str(tmp_path)],
                       attempt_fn=_explode)
    assert code == 1
    assert "nothing was run" in capsys.readouterr().out


def test_once_without_live_says_the_runner_is_advisory(no_eval, tmp_path,
                                                       capsys):
    _write_inventory(tmp_path, INVENTORY)
    picker.main(["--once", "--repo-root", str(tmp_path)],
                attempt_fn=lambda c, a: FakeResult())
    assert "ADVISORY" in capsys.readouterr().out


def test_cli_help_states_that_nothing_is_applied():
    parser = picker._build_parser()
    text = parser.format_help()
    assert "NEVER applies anything" in text
    assert "human" in text.lower()
    # Structural, not textual: no flag named anything like apply/promote/merge
    # is offered, whatever the prose around it says.
    offered = set(parser._option_string_actions)
    for forbidden in ("--apply", "--promote", "--merge", "--commit", "--push"):
        assert forbidden not in offered
    assert "There is no --apply flag" in text


def _mission_probe(monkeypatch, tmp_path, *, head):
    """Run ``_default_attempt`` with every process spawn poisoned, and return
    the ``mission_id`` it handed to ``run_attempt``.

    Nothing here is allowed to spawn: `subprocess.run` and `subprocess.Popen`
    both raise, so a picker that resolved HEAD with a child process fails loudly
    instead of quietly passing a textual guard.
    """
    import subprocess as _sp
    import types

    from daedalus.spine import attempt as attempt_mod

    def _no_spawn(*a, **k):
        raise AssertionError(f"the picker spawned a process: {a[:1]}")

    monkeypatch.setattr(_sp, "run", _no_spawn)
    monkeypatch.setattr(_sp, "Popen", _no_spawn)
    monkeypatch.setattr(picker, "_head_sha", lambda root: head)
    monkeypatch.setattr(picker, "resolve_spine_db_path",
                        lambda root: (tmp_path / "spine.sqlite3", None))
    monkeypatch.setattr(attempt_mod, "offload_runner", lambda **k: object())
    seen: dict = {}

    def _fake_run_attempt(spec, **kwargs):
        seen.update(kwargs)
        return types.SimpleNamespace(state="no_change")

    monkeypatch.setattr(attempt_mod, "run_attempt", _fake_run_attempt)
    candidate = Candidate(
        task_id="probe-task", source="inventory",
        instruction="do the measured thing", reason="because it was measured",
        score=1.0, gate_timeout_s=60.0)
    args = types.SimpleNamespace(
        repo_root=str(tmp_path), live=False, artifact_dir=None,
        keep_worktree=False)
    picker._default_attempt(candidate, args)
    return seen.get("mission_id")


def test_the_mission_revision_is_read_off_disk_and_never_spawned(monkeypatch, tmp_path):
    """464f666e minted the per-candidate MissionContract from a spawned
    ``git rev-parse HEAD``, breaking the structural guard below to avoid an
    import. The revision now comes from ``_head_sha``, which reads git's own
    files. Poison every spawn and check the mission is still minted."""
    head = "a" * 40
    assert _mission_probe(monkeypatch, tmp_path, head=head) == "mission-probe-task"


def test_an_unknown_revision_means_no_mission_rather_than_a_spawn(monkeypatch, tmp_path):
    """``_head_sha`` returns None when it cannot tell -- an unrecognised
    ``.git``, a directory that is not a checkout. The mission is optional here
    by design, so that must fall back to no mission (``run_attempt``'s
    task-derived default), never to reaching for a child process."""
    assert _mission_probe(monkeypatch, tmp_path, head=None) is None


def test_there_is_no_apply_path_in_this_module():
    # Structural, not a promise in a docstring: the picker spawns no process
    # at all, so it cannot run a git verb that writes the primary checkout --
    # the 'git apply' string it prints is advice to a human, and there is
    # nothing here that could execute it.
    with open(picker.__file__, "r", encoding="utf-8") as fh:
        text = fh.read()
    assert "subprocess" not in text
    assert "os.system" not in text
    assert "shutil" not in text
    # ...and it writes no file either: the only open() is read-only.
    assert 'open(path, "r"' in text
    for forbidden in ('open(path, "w"', ".write_text(", ".write_bytes(",
                      "os.remove", "os.unlink"):
        assert forbidden not in text, forbidden


def test_daedalus_cli_dispatches_improve():
    from pathlib import Path as _Path
    cli_source = _Path(picker.__file__).resolve().parents[1] / "cli.py"
    text = cli_source.read_text(encoding="utf-8")
    assert 'elif cmd == "improve":' in text
    assert "from .spine.picker import main" in text
    assert "daedalus improve" in text          # documented in the usage banner
