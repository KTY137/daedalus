"""The OUTCOME POLICY: does the ledger's RESULT change the next pick, or only
the prose?

Attempt memory shipped sinking every attempted candidate by the same amount. A
cross-vendor review named the weakness precisely: "die Memory-Logik senkt jedes
identische Reattempt gleich, unabhaengig vom Outcome; das Outcome erscheint nur
im Text." A candidate whose gates PASSED (a patch is waiting on a human) was
sunk exactly as hard as one whose gates FAILED and as one whose worktree never
came up -- and the difference lived only in ``reason``, which nothing sorts by.

The tests here are built around CONTRASTS, because a policy that cannot be shown
to change an order is unfalsifiable. Every contrast is run in BOTH directions --
the same two candidates with their outcomes swapped -- so a passing assertion
cannot be an accident of task_id ordering.

The band invariant is not negotiable and is re-pinned here: an outcome may move
a candidate inside its band and never out of it, and memory is a PENALTY, never
a filter. No model, no network, no git binary.
"""
import json

import pytest

import daedalus.spine.picker as picker
from daedalus.spine.picker import (
    BAND_SPAN,
    OUTCOME_POLICY,
    SOURCE_BANDS,
    UNKNOWN_OUTCOME,
    build_queue,
    outcome_policy,
)

# Two islands that are IDENTICAL as measurements -- same test count, same
# entrypoint count, therefore the same band offset -- and differ only in name,
# which is what gives them distinct task_ids. Any ordering between them is
# therefore attributable to memory alone. A third, untried island sits lower so
# "sank below untried work" is observable.
TWINS = {
    "schema": "daedalus-feature-inventory/1",
    "repo_state": {"branch": "fixture", "head": "abc1234", "dirty": False},
    "areas": [
        {
            "area": "Twin area",
            "features": [
                {"name": "twin one", "status": "island",
                 "entrypoints": ["one/mod.py:go", "one/other.py:go"],
                 "tests": ["tests/test_one_a.py", "tests/test_one_b.py",
                           "tests/test_one_c.py"],
                 "notes": "built, uncalled"},
                {"name": "twin two", "status": "island",
                 "entrypoints": ["two/mod.py:go", "two/other.py:go"],
                 "tests": ["tests/test_two_a.py", "tests/test_two_b.py",
                           "tests/test_two_c.py"],
                 "notes": "built, uncalled"},
                {"name": "lesser island", "status": "island",
                 "entrypoints": ["l/mod.py:go"], "tests": ["tests/test_l.py"],
                 "notes": "one test only"},
                # Two islands with NO measured evidence at all, so both sit on
                # the band floor before memory speaks. The floor is where a
                # fully-sunk candidate also lands, so these are the only
                # fixtures on which a tie-break can actually be observed.
                {"name": "bare one", "status": "island",
                 "entrypoints": [], "tests": [], "notes": ""},
                {"name": "bare two", "status": "island",
                 "entrypoints": [], "tests": [], "notes": ""},
            ],
        },
    ],
}


@pytest.fixture
def no_eval(monkeypatch):
    """Keep the cheap eval source hermetic (never read the repo's baseline)."""
    monkeypatch.setattr(picker, "_load_baseline", lambda: ({}, None))
    return monkeypatch


@pytest.fixture
def repo(tmp_path):
    """An inventory whose recorded head matches a hand-written on-disk HEAD."""
    docs = tmp_path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "FEATURE_INVENTORY.json").write_text(json.dumps(TWINS),
                                                 encoding="utf-8")
    git = tmp_path / ".git"
    (git / "refs" / "heads").mkdir(parents=True, exist_ok=True)
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git / "refs" / "heads" / "main").write_text("abc1234" + "0" * 33 + "\n",
                                                 encoding="utf-8")
    return tmp_path


def _cold(repo):
    """The queue with memory switched off -- the measurement, unremembered."""
    return build_queue(repo, limit=None, use_attempt_memory=False)


def _by_name(queue, fragment):
    return next(c for c in queue.candidates if fragment in c.task_id)


def _ledger(repo, attempts, *, resolve=True):
    """Record one attempt per ``(candidate, outcome)`` pair, using the exact
    instruction the picker itself generates -- the realistic case, and the only
    one the instruction fingerprint will match.

    ``resolve=False`` leaves the intent OPEN, which is how an attempt still IN
    FLIGHT looks to the reader.
    """
    from daedalus.spine.ledger import SpineLedger

    db = repo / "spine" / "spine.sqlite3"
    db.parent.mkdir(parents=True, exist_ok=True)
    led = SpineLedger(db)
    for i, (cand, outcome) in enumerate(attempts):
        intent = led.record_intent(
            picker.ATTEMPT_INTENT_KIND,
            {"task_id": cand.task_id, "instruction": cand.instruction},
            effect_key=f"daedalus-attempt-{cand.task_id}-{i}")
        if resolve:
            led.mark_completed(intent.id, effect_id=f"{i:064d}",
                               result={"state": outcome})
    led.close()
    return db


def _warm(repo, attempts, *, resolve=True):
    return build_queue(repo, limit=None,
                       spine_db=_ledger(repo, attempts, resolve=resolve))


# --------------------------------------------------------------------------- #
# the premise: the twins really are indistinguishable before memory speaks     #
# --------------------------------------------------------------------------- #
def test_the_twins_are_identical_measurements(repo, no_eval):
    """Every contrast below rests on this. If the twins ever stop being equal
    on evidence, those tests would be measuring the fixture, not the policy."""
    cold = _cold(repo)
    one, two = _by_name(cold, "twin-one"), _by_name(cold, "twin-two")

    assert one.score == two.score
    assert one.source == two.source
    assert one.offset > 0                      # room to sink, in both directions
    assert _by_name(cold, "lesser").offset < one.offset


# --------------------------------------------------------------------------- #
# THE CONTRAST -- the whole point of the policy                                #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("first,second", [("one", "two"), ("two", "one")])
def test_two_identical_candidates_are_ordered_by_their_outcome(
        repo, no_eval, first, second):
    """The contrasting check the policy would be unfalsifiable without.

    Two candidates identical in every measured respect. One's last attempt ended
    ``no_change`` (the runner proposed nothing -- says almost nothing), the
    other's ended ``gates_failed`` (a diff existed and the gates refused it --
    real evidence about this task). The mild outcome must rank FIRST, on SCORE
    and not merely in the reason text.

    Run in both directions, so the result cannot be an artifact of which
    task_id happens to sort first.
    """
    cold = _cold(repo)
    mild, harsh = _by_name(cold, f"twin-{first}"), _by_name(cold, f"twin-{second}")
    assert mild.score == harsh.score           # equal before memory speaks

    warm = _warm(repo, [(mild, "no_change"), (harsh, "gates_failed")])
    w_mild, w_harsh = (_by_name(warm, f"twin-{first}"),
                       _by_name(warm, f"twin-{second}"))

    assert w_mild.score > w_harsh.score, "the outcome did not reach the score"
    ids = [c.task_id for c in warm.candidates]
    assert ids.index(w_mild.task_id) < ids.index(w_harsh.task_id)


@pytest.mark.parametrize("first,second", [("one", "two"), ("two", "one")])
def test_at_the_band_floor_clean_is_picked_after_gates_failed(
        repo, no_eval, first, second):
    """The distinction the SCORE cannot carry, and the tie-break that does.

    ``clean`` and ``gates_failed`` both belong at the band floor, and there is
    nothing below a floor that does not leave the band. So the last ordering is
    a severity tie-break in rank(): a ``clean`` attempt has a patch waiting on a
    human and more model time cannot advance it, while ``gates_failed`` can
    still move. Both directions again.
    """
    cold = _cold(repo)
    failed, done = _by_name(cold, f"twin-{first}"), _by_name(cold, f"twin-{second}")

    warm = _warm(repo, [(failed, "gates_failed"), (done, "clean")])
    w_failed, w_done = (_by_name(warm, f"twin-{first}"),
                        _by_name(warm, f"twin-{second}"))

    assert w_failed.score == w_done.score       # the collision is real
    assert w_failed.offset == 0.0 and w_done.offset == 0.0
    ids = [c.task_id for c in warm.candidates]
    assert ids.index(w_failed.task_id) < ids.index(w_done.task_id)


@pytest.mark.parametrize("first,second", [("one", "two"), ("two", "one")])
def test_severity_outranks_the_attempt_count(repo, no_eval, first, second):
    """A task tried ONCE and returned ``clean`` is a worse next pick than one
    tried THREE times whose worktree never built -- the second taught us
    nothing at all. Pins that severity is checked BEFORE ``prior_attempts``,
    which would order these the other way round.

    Deliberately run on the BARE islands: they carry no measured evidence, so
    both land on the band floor and the scores genuinely tie. On the twins the
    mild outcome's ceiling leaves it above the floor and the comparison is
    settled by score before any tie-break is consulted -- which would make this
    test pass while asserting nothing about the tie-break at all.
    """
    cold = _cold(repo)
    done, broken = _by_name(cold, f"bare-{first}"), _by_name(cold, f"bare-{second}")
    assert done.offset == 0.0 and broken.offset == 0.0

    warm = _warm(repo, [(done, "clean")] + [(broken, "worktree_failed")] * 3)
    w_done, w_broken = (_by_name(warm, f"bare-{first}"),
                        _by_name(warm, f"bare-{second}"))

    assert w_done.score == w_broken.score, "no tie -- the tie-break never ran"
    assert w_broken.evidence["prior_attempts"] == 3
    assert w_done.evidence["prior_attempts"] == 1
    ids = [c.task_id for c in warm.candidates]
    assert ids.index(w_broken.task_id) < ids.index(w_done.task_id)


# --------------------------------------------------------------------------- #
# the band invariant, re-pinned against the graded policy                      #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("outcome", sorted(OUTCOME_POLICY))
def test_no_outcome_can_move_a_candidate_out_of_its_band(repo, no_eval, outcome):
    """The stated priority is not memory's to overrule -- for EVERY outcome,
    including the mild ones a graded policy introduces."""
    cold = _cold(repo)
    top = _by_name(cold, "twin-one")

    warm = _warm(repo, [(top, outcome)])
    moved = _by_name(warm, "twin-one")

    floor = SOURCE_BANDS[moved.source]
    assert moved.band == top.band
    assert floor <= moved.score <= floor + BAND_SPAN
    assert 0.0 <= moved.offset <= BAND_SPAN


@pytest.mark.parametrize("outcome", sorted(OUTCOME_POLICY))
def test_memory_never_promotes_a_candidate(repo, no_eval, outcome):
    """A ceiling can only lower. Pinned for the LESSER island, whose measured
    offset already sits below every mild outcome's ceiling -- the case where a
    naive `offset = ceiling` assignment would silently promote it."""
    cold = _cold(repo)
    lesser = _by_name(cold, "lesser")

    warm = _warm(repo, [(lesser, outcome)])
    moved = _by_name(warm, "lesser")

    assert moved.score <= lesser.score


@pytest.mark.parametrize("outcome", sorted(OUTCOME_POLICY))
def test_no_outcome_removes_work_from_the_queue(repo, no_eval, outcome):
    """A penalty, never a filter -- at every residual, including 0.0. One
    transient failure must not delete real work forever."""
    cold = _cold(repo)
    top = _by_name(cold, "twin-one")

    warm = _warm(repo, [(top, outcome)])

    assert len(warm.candidates) == len(cold.candidates)
    assert top.task_id in [c.task_id for c in warm.candidates]


# --------------------------------------------------------------------------- #
# the policy table itself                                                      #
# --------------------------------------------------------------------------- #
def test_every_attempt_state_the_writer_can_produce_is_classified():
    """The drift check. attempt.py owns the state vocabulary; an unclassified
    state would fall silently through to UNKNOWN_OUTCOME and be sunk to the
    floor without anyone having argued for it. (It found one: the brief named
    six states, ATTEMPT_STATES has seven -- ``storage_unavailable``.)"""
    from daedalus.spine.attempt import ATTEMPT_STATES

    assert set(OUTCOME_POLICY) == set(ATTEMPT_STATES)


def test_the_policy_is_internally_well_formed():
    for name, policy in OUTCOME_POLICY.items():
        assert policy.outcome == name, "the key and the row disagree"
        assert 0.0 <= policy.residual <= 1.0
        assert 0.0 <= policy.severity <= 1.0
        assert policy.meaning.strip() and policy.verdict.strip(), (
            f"{name} carries a number with no argument attached")


def test_the_policy_is_ordered_the_way_its_prose_claims():
    """The two axes, as assertions. Evidence about the TASK sinks harder than
    evidence about the MACHINE; a finished patch sinks hardest of all."""
    r = {k: v.residual for k, v in OUTCOME_POLICY.items()}
    s = {k: v.severity for k, v in OUTCOME_POLICY.items()}

    # what the model produced, hardest first
    assert r["clean"] == r["gates_failed"] == 0.0
    assert r["reconciliation_required"] == 0.0
    assert r["clean"] < r["no_change"] < r["runner_failed"]
    # infrastructure barely moves the work
    assert r["runner_failed"] < r["worktree_failed"] <= r["cancelled"]
    assert r["cancelled"] < r["storage_unavailable"] < 1.0
    # at the floor, a finished patch is the last thing to pick up again
    assert s["clean"] > s["gates_failed"] > s["no_change"] > s["runner_failed"]
    assert s["reconciliation_required"] == 1.0
    assert UNKNOWN_OUTCOME.severity > s["clean"]
    assert UNKNOWN_OUTCOME.residual == 0.0


def test_an_unknown_or_missing_outcome_fails_closed():
    assert outcome_policy(None) is UNKNOWN_OUTCOME
    assert outcome_policy("") is UNKNOWN_OUTCOME
    assert outcome_policy("   ") is UNKNOWN_OUTCOME
    assert outcome_policy("a_state_nobody_has_argued_about") is UNKNOWN_OUTCOME
    assert outcome_policy("clean") is OUTCOME_POLICY["clean"]
    # ...and failing closed means the FLAT behaviour this policy replaced,
    # never a softer one.
    assert UNKNOWN_OUTCOME.ceiling(1) == 0.0


def test_an_in_flight_attempt_is_sunk_as_hard_as_a_finished_one(repo, no_eval):
    """The safety edge of failing closed. An intent recorded but not resolved is
    a run still HOLDING this task; re-picking it races that run in the same
    worktree branch. It must sink like a completed attempt, not float on a
    missing result."""
    cold = _cold(repo)
    top = _by_name(cold, "twin-one")

    warm = _warm(repo, [(top, None)], resolve=False)
    moved = _by_name(warm, "twin-one")

    assert moved.evidence["last_attempt_outcome"] is None
    assert moved.offset == 0.0
    assert moved.evidence["memory_outcome_severity"] == UNKNOWN_OUTCOME.severity


# --------------------------------------------------------------------------- #
# compounding                                                                  #
# --------------------------------------------------------------------------- #
def test_repeats_of_a_mild_outcome_compound(repo, no_eval):
    """One worktree failure is an accident; five in a row is a broken task.
    Without compounding, an outcome judged harmless would let the loop re-pick a
    candidate it can never even check out -- the original defect, reintroduced
    through the mild end of the policy."""
    cold = _cold(repo)
    top = _by_name(cold, "twin-one")

    once = _by_name(_warm(repo, [(top, "worktree_failed")]), "twin-one")
    five = _by_name(_warm(repo, [(top, "worktree_failed")] * 5), "twin-one")

    assert five.evidence["memory_offset_ceiling"] < \
           once.evidence["memory_offset_ceiling"]
    assert five.score < once.score
    # ...and still never a filter, and still inside the band.
    assert five.offset > 0.0
    assert five.score > SOURCE_BANDS[five.source]


def test_compounding_counts_the_instruction_not_the_task_id(repo, no_eval):
    """Compounding rides on the same-instruction fingerprint that memory itself
    uses, so attempts at a REWRITTEN instruction cannot deepen the sink on work
    nobody is proposing any more."""
    cold = _cold(repo)
    top = _by_name(cold, "twin-one")
    policy = OUTCOME_POLICY["no_change"]

    warm = _warm(repo, [(top, "no_change")] * 2)
    moved = _by_name(warm, "twin-one")

    assert moved.evidence["prior_attempts_same_instruction"] == 2
    assert moved.evidence["memory_offset_ceiling"] == policy.ceiling(2)


# --------------------------------------------------------------------------- #
# the evidence trail                                                           #
# --------------------------------------------------------------------------- #
def test_the_score_carries_the_argument_that_produced_it(repo, no_eval):
    """NO TASK WITHOUT EVIDENCE applies to the memory penalty too: a human must
    be able to re-derive the number and refuse the policy behind it."""
    cold = _cold(repo)
    top = _by_name(cold, "twin-one")
    policy = OUTCOME_POLICY["no_change"]

    warm = _warm(repo, [(top, "no_change")])
    moved = _by_name(warm, "twin-one")

    ev = moved.evidence
    assert ev["last_attempt_outcome"] == "no_change"
    assert ev["memory_outcome_residual"] == policy.residual
    assert ev["memory_outcome_severity"] == policy.severity
    assert ev["memory_offset_ceiling"] == policy.ceiling(1)
    assert ev["memory_offset_before"] == top.offset
    assert ev["memory_policy"] == policy.verdict
    # re-derivable: the score is exactly band + min(before, ceiling)
    assert moved.score == round(
        SOURCE_BANDS[moved.source] + min(top.offset, policy.ceiling(1)), 4)
    assert policy.meaning in moved.reason


def test_the_note_names_the_outcomes_it_acted_on(repo, no_eval):
    """An operator reading --dry-run sees WHICH outcomes moved the queue, not
    just how many candidates moved."""
    cold = _cold(repo)
    one, two = _by_name(cold, "twin-one"), _by_name(cold, "twin-two")

    warm = _warm(repo, [(one, "clean"), (two, "no_change")])
    note = next(n for n in warm.notes if n.startswith("attempt memory:"))

    assert "1x clean" in note and "1x no_change" in note


def test_a_candidate_already_below_its_ceiling_is_reported_as_held(repo, no_eval):
    """"Memory moved N candidates" must not be a claim about work that did not
    move. The lesser island sits below `cancelled`'s ceiling already."""
    cold = _cold(repo)
    lesser = _by_name(cold, "lesser")

    warm = _warm(repo, [(lesser, "cancelled")])
    moved = _by_name(warm, "lesser")

    assert moved.score == lesser.score          # genuinely unmoved
    note = next(n for n in warm.notes if n.startswith("attempt memory:"))
    assert "0 sank" in note and "1 already stood at or below it" in note
