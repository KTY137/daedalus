# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The loop's RETURN path: does measurement come back and change the next pick?

The forward half of the circle (picker -> attempt) already worked. This file
covers the half that did not, and the two properties it has to have:

ATTEMPT MEMORY -- before this, ``daedalus improve`` re-selected the same
candidate forever. Measured on the real repo: five attempts recorded and
resolved as gate failures left the top five of the queue byte-identical,
because nothing consulted the ledger and the ledger had no query that could
enumerate a COMPLETED attempt anyway. Memory is a PENALTY, never a filter --
tests here pin that an attempted candidate stays in the queue and merely
sinks, because dropping it would let one transient runner failure delete real
work permanently.

INVENTORY FRESHNESS -- ``docs/FEATURE_INVENTORY.json`` is hand-written (nothing
in the repo generates it) and drives the two highest bands. Measured: it
recorded ``f40529c`` while HEAD was ``983f031``, thirty commits later. A queue
ranked confidently off a snapshot of a different tree is worse than an empty
one, so it fails CLOSED -- but loudly, and only on the revision, never on
dirtiness alone.

No model, no network, no eval run, no index build, and no git BINARY: the .git
fixtures here are written by hand precisely because the picker resolves HEAD by
reading git's on-disk files rather than spawning anything.
"""
import json

import pytest

import daedalus.spine.picker as picker
from daedalus.spine.picker import BAND_SPAN, SOURCE_BANDS, build_queue

INVENTORY = {
    "schema": "daedalus-feature-inventory/1",
    "repo_state": {"branch": "fixture", "head": "abc1234", "dirty": False},
    "areas": [
        {
            "area": "Alpha area",
            "features": [
                {"name": "alpha island", "status": "island",
                 "entrypoints": ["a/mod.py:go"], "tests": ["tests/test_a.py"],
                 "notes": "built, uncalled"},
                {"name": "beta island", "status": "island",
                 "entrypoints": [], "tests": [], "notes": ""},
                {"name": "gamma stale", "status": "stale",
                 "entrypoints": ["g/old.py"], "tests": [], "notes": "superseded"},
            ],
        },
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
    (docs / "FEATURE_INVENTORY.json").write_text(
        json.dumps(payload), encoding="utf-8")
    return tmp_path


def _git_repo_at(tmp_path, head_sha):
    """A minimal on-disk .git whose HEAD resolves to ``head_sha``."""
    git = tmp_path / ".git"
    (git / "refs" / "heads").mkdir(parents=True, exist_ok=True)
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git / "refs" / "heads" / "main").write_text(head_sha + "\n", encoding="utf-8")
    return tmp_path


def _ledger_with_attempts(tmp_path, attempts, state="gates_failed"):
    """A real SpineLedger recording one resolved attempt per (id, instruction).

    ``attempts`` items are either a task_id (instruction taken from the live
    queue, i.e. the realistic case) or an explicit ``(task_id, instruction)``
    pair, which is how the definition-fingerprint tests simulate a task whose
    instruction was rewritten while its id stayed the same.
    """
    from daedalus.spine.ledger import SpineLedger

    db = tmp_path / "spine" / "spine.sqlite3"
    db.parent.mkdir(parents=True, exist_ok=True)
    led = SpineLedger(db)
    for item in attempts:
        task_id, instruction = item if isinstance(item, tuple) else (item, None)
        if instruction is None:
            instruction = _instruction_for(tmp_path, task_id)
        intent = led.record_intent(
            picker.ATTEMPT_INTENT_KIND,
            {"task_id": task_id, "instruction": instruction},
            effect_key=f"daedalus-attempt-{task_id}")
        led.mark_completed(intent.id, effect_id="0" * 64,
                           result={"state": state})
    led.close()
    return db


def _instruction_for(tmp_path, task_id):
    """The instruction the picker itself would generate for this candidate."""
    cold = build_queue(tmp_path, limit=None, use_attempt_memory=False)
    return next(c.instruction for c in cold.candidates if c.task_id == task_id)


def _fresh(tmp_path):
    """Inventory + a matching HEAD, so freshness never masks a memory result."""
    _write_inventory(tmp_path, INVENTORY)
    _git_repo_at(tmp_path, "abc1234" + "0" * 33)
    return tmp_path


# --------------------------------------------------------------------------- #
# attempt memory                                                               #
# --------------------------------------------------------------------------- #
def test_attempt_intent_kind_has_not_drifted_from_the_writer():
    # picker mirrors the constant rather than importing it (importing attempt.py
    # would drag the worktree manager and the storage watermark into every
    # --dry-run). A copy is only acceptable while something proves it IS a copy.
    from daedalus.spine.attempt import INTENT_KIND

    assert picker.ATTEMPT_INTENT_KIND == INTENT_KIND


def test_the_defect_this_closes_same_queue_forever(tmp_path, no_eval):
    """Without memory, recorded failures change nothing -- the measured defect."""
    _fresh(tmp_path)
    cold = build_queue(tmp_path, limit=None, use_attempt_memory=False)
    ids = [c.task_id for c in cold.candidates]
    db = _ledger_with_attempts(tmp_path, ids)
    again = build_queue(tmp_path, limit=None, use_attempt_memory=False,
                        spine_db=db)
    assert [c.task_id for c in again.candidates] == ids


def test_an_attempted_candidate_sinks_but_is_never_dropped(tmp_path, no_eval):
    _fresh(tmp_path)
    cold = build_queue(tmp_path, limit=None, use_attempt_memory=False)
    assert len(cold.candidates) >= 2
    top = cold.candidates[0].task_id

    db = _ledger_with_attempts(tmp_path, [top])
    warm = build_queue(tmp_path, limit=None, spine_db=db)

    # NOT a filter: same length, the candidate merely moved.
    assert len(warm.candidates) == len(cold.candidates)
    warm_ids = [c.task_id for c in warm.candidates]
    assert top in warm_ids
    assert warm_ids[0] != top
    assert warm_ids.index(top) > 0


def test_memory_moves_to_the_band_floor_but_never_out_of_the_band(tmp_path, no_eval):
    # The stated-priority invariant is why BAND_SPAN exists. Memory is a
    # measurement and obeys it like every other measurement.
    _fresh(tmp_path)
    cold = build_queue(tmp_path, limit=None, use_attempt_memory=False)
    top = cold.candidates[0]
    db = _ledger_with_attempts(tmp_path, [top.task_id])
    warm = build_queue(tmp_path, limit=None, spine_db=db)
    moved = next(c for c in warm.candidates if c.task_id == top.task_id)

    assert moved.band == top.band
    assert moved.offset == 0.0
    floor = SOURCE_BANDS[moved.source]
    assert floor <= moved.score < floor + BAND_SPAN


def test_memory_attaches_the_evidence_that_moved_it(tmp_path, no_eval):
    _fresh(tmp_path)
    cold = build_queue(tmp_path, limit=None, use_attempt_memory=False)
    top = cold.candidates[0].task_id
    db = _ledger_with_attempts(tmp_path, [top, top])          # attempted twice
    warm = build_queue(tmp_path, limit=None, spine_db=db)
    moved = next(c for c in warm.candidates if c.task_id == top)

    assert moved.evidence["prior_attempts"] == 2
    assert moved.evidence["last_attempt_outcome"] == "gates_failed"
    assert moved.evidence["last_attempt_state"] == "COMPLETED"
    assert "already attempted 2x" in moved.reason
    assert any("attempt memory" in n for n in warm.notes)


def test_memory_still_decides_when_the_penalty_ties_at_the_band_floor(
        tmp_path, no_eval):
    """The case a penalty alone cannot express, and the reason rank() tie-breaks.

    An attempted candidate is driven to its band FLOOR -- which is exactly where
    a candidate carrying no measured evidence already sits. So the tried and the
    untried collide on score precisely when the distinction matters most.
    Fixture: "alpha island" has tests and an entrypoint (offset > 0), "beta
    island" has neither (offset 0). Attempt alpha; both are then at the floor,
    and beta must still come first.
    """
    _fresh(tmp_path)
    cold = build_queue(tmp_path, limit=None, use_attempt_memory=False)
    alpha = next(c for c in cold.candidates if "alpha" in c.task_id)
    beta = next(c for c in cold.candidates if "beta" in c.task_id)
    assert alpha.offset > 0 and beta.offset == 0        # the fixture's premise
    assert cold.candidates.index(alpha) < cold.candidates.index(beta)

    db = _ledger_with_attempts(tmp_path, [alpha.task_id])
    warm = build_queue(tmp_path, limit=None, spine_db=db)
    warm_alpha = next(c for c in warm.candidates if "alpha" in c.task_id)
    warm_beta = next(c for c in warm.candidates if "beta" in c.task_id)

    assert warm_alpha.score == warm_beta.score          # the collision is real
    assert warm.candidates.index(warm_beta) < warm.candidates.index(warm_alpha)


def test_forget_disables_memory(tmp_path, no_eval):
    _fresh(tmp_path)
    cold = build_queue(tmp_path, limit=None, use_attempt_memory=False)
    top = cold.candidates[0].task_id
    db = _ledger_with_attempts(tmp_path, [top])
    forgotten = build_queue(tmp_path, limit=None, use_attempt_memory=False,
                            spine_db=db)
    assert forgotten.candidates[0].task_id == top
    assert forgotten.sources["attempt_memory"]["read"] is False


def test_a_missing_ledger_is_an_empty_memory_not_a_failure(tmp_path, no_eval):
    _fresh(tmp_path)
    q = build_queue(tmp_path, limit=None, spine_db=tmp_path / "nope.sqlite3")
    assert q.candidates                       # still answers "what next"
    assert q.sources["attempt_memory"] == {"read": True, "tasks_remembered": 0}


def test_an_unreadable_ledger_is_reported_never_silently_forgotten(tmp_path, no_eval):
    # Degrading to "no memory" without saying so is exactly how a loop would
    # quietly go back to repeating itself.
    _fresh(tmp_path)
    junk = tmp_path / "junk.sqlite3"
    junk.write_text("this is not a database", encoding="utf-8")
    q = build_queue(tmp_path, limit=None, spine_db=junk)
    assert q.sources["attempt_memory"]["read"] is False
    assert q.sources["attempt_memory"]["error"]
    assert any("attempt memory unavailable" in n for n in q.notes)


def test_a_rewritten_instruction_does_not_inherit_the_old_attempts_memory(
        tmp_path, no_eval):
    """Lineage matched, definition did not -- so it must NOT be penalised.

    An inventory task_id hashes ``area|name|status`` only, so tests,
    entrypoints and notes -- and therefore the whole generated instruction --
    can change while the id stays byte-identical. Joining on the id alone would
    make rewritten work inherit the failures of work nobody is proposing any
    more.
    """
    _fresh(tmp_path)
    cold = build_queue(tmp_path, limit=None, use_attempt_memory=False)
    top = cold.candidates[0]

    db = _ledger_with_attempts(
        tmp_path, [(top.task_id, "an OLD instruction that has since changed")])
    warm = build_queue(tmp_path, limit=None, spine_db=db)
    same = next(c for c in warm.candidates if c.task_id == top.task_id)

    assert same.score == top.score                       # not sunk
    assert warm.candidates[0].task_id == top.task_id     # still on top
    assert same.evidence["prior_attempts"] == 1          # lineage recorded
    assert same.evidence["prior_attempts_same_instruction"] == 0
    assert any("instruction changed" in n for n in warm.notes)


def test_the_same_instruction_is_what_sinks_a_candidate(tmp_path, no_eval):
    _fresh(tmp_path)
    cold = build_queue(tmp_path, limit=None, use_attempt_memory=False)
    top = cold.candidates[0]
    db = _ledger_with_attempts(tmp_path, [(top.task_id, top.instruction)])
    warm = build_queue(tmp_path, limit=None, spine_db=db)
    sunk = next(c for c in warm.candidates if c.task_id == top.task_id)

    assert sunk.offset == 0.0
    assert sunk.evidence["prior_attempts_same_instruction"] == 1
    assert "with this exact instruction" in sunk.reason


def test_memory_has_no_window_an_old_attempt_is_still_remembered(tmp_path, no_eval):
    """A row limit would be a WINDOW: old attempts would fall out of memory and
    their tasks become selectable again. The lookup is by identity, so burying
    the attempt under many newer, unrelated ones changes nothing."""
    _fresh(tmp_path)
    cold = build_queue(tmp_path, limit=None, use_attempt_memory=False)
    top = cold.candidates[0]
    db = _ledger_with_attempts(tmp_path, [(top.task_id, top.instruction)])

    from daedalus.spine.ledger import SpineLedger
    led = SpineLedger(db)
    for i in range(600):                 # far past any plausible recent-window
        intent = led.record_intent(picker.ATTEMPT_INTENT_KIND,
                                   {"task_id": f"unrelated-{i}",
                                    "instruction": "noise"})
        led.mark_completed(intent.id, result={"state": "clean"})
    led.close()

    warm = build_queue(tmp_path, limit=None, spine_db=db)
    sunk = next(c for c in warm.candidates if c.task_id == top.task_id)
    assert sunk.offset == 0.0
    assert sunk.evidence["prior_attempts_same_instruction"] == 1


def test_ranking_a_queue_does_not_modify_the_ledger(tmp_path, no_eval):
    """--dry-run must not change the record. The normal ledger constructor
    creates the parent directory, sets journal_mode=WAL and runs migrations
    inside BEGIN IMMEDIATE -- so merely opening one to READ it rewrote the file.

    The assertion is on the DATABASE BYTES, deliberately, and not on the
    directory: SQLite creates ``-wal``/``-shm`` sidecars when a WAL database is
    opened even read-only, because the shared-memory index is how WAL reads
    work at all. That is inherent to reading this format, not a write we can
    remove -- so it is stated here rather than hidden behind a looser check.
    """
    import hashlib

    _fresh(tmp_path)
    cold = build_queue(tmp_path, limit=None, use_attempt_memory=False)
    top = cold.candidates[0]
    db = _ledger_with_attempts(tmp_path, [(top.task_id, top.instruction)])

    digest = lambda: hashlib.sha256(db.read_bytes()).hexdigest()
    before = digest()
    warm = build_queue(tmp_path, limit=None, spine_db=db)

    assert digest() == before
    # ...and the read really did happen, so this is not passing vacuously.
    assert warm.sources["attempt_memory"] == {"read": True,
                                              "tasks_remembered": 1}


def test_ranking_never_initialises_a_ledger_it_merely_reads(tmp_path, no_eval):
    """The sharper half of "the reader does not write".

    Against an already-valid ledger the normal constructor's migrations are all
    no-ops, so a bytes check cannot tell the two open modes apart. Point it at a
    file that is NOT a ledger and the difference is unmissable: the writing
    constructor would run CREATE TABLE and turn it into one. The picker must
    instead read nothing, change nothing, and SAY so.
    """
    _fresh(tmp_path)
    foreign = tmp_path / "not-a-ledger.sqlite3"
    foreign.write_bytes(b"")

    q = build_queue(tmp_path, limit=None, spine_db=foreign)

    assert foreign.stat().st_size == 0, "the picker initialised a database"
    assert q.sources["attempt_memory"]["read"] is False
    assert any("attempt memory unavailable" in n for n in q.notes)
    assert q.candidates                      # and still answered "what next"


def test_the_reader_cannot_write_even_if_asked(tmp_path):
    """Enforced by SQLite, not promised by this class -- so a future edit that
    introduces a write cannot quietly pass."""
    import sqlite3

    from daedalus.spine.ledger import SpineLedger

    db = tmp_path / "s.sqlite3"
    writer = SpineLedger(db)
    writer.record_intent(picker.ATTEMPT_INTENT_KIND, {"task_id": "t"})
    writer.close()

    reader = SpineLedger(db, read_only=True)
    assert len(reader.recent_intents(picker.ATTEMPT_INTENT_KIND)) == 1
    with pytest.raises(sqlite3.OperationalError):
        reader.record_intent(picker.ATTEMPT_INTENT_KIND, {"task_id": "nope"})
    reader.close()


def test_a_read_only_open_does_not_create_a_ledger(tmp_path):
    from daedalus.spine.ledger import SpineLedger

    missing = tmp_path / "nested" / "s.sqlite3"
    with pytest.raises(Exception):
        SpineLedger(missing, read_only=True)
    assert not missing.parent.exists()   # the normal path would have mkdir'd it


def test_memory_only_matches_the_task_it_actually_attempted(tmp_path, no_eval):
    _fresh(tmp_path)
    cold = build_queue(tmp_path, limit=None, use_attempt_memory=False)
    db = _ledger_with_attempts(
        tmp_path, [("some-task-nobody-queued", "irrelevant instruction")])
    warm = build_queue(tmp_path, limit=None, spine_db=db)
    assert [c.task_id for c in warm.candidates] == \
           [c.task_id for c in cold.candidates]
    assert all("prior_attempts" not in c.evidence for c in warm.candidates)


# --------------------------------------------------------------------------- #
# HEAD, read off disk                                                          #
# --------------------------------------------------------------------------- #
def test_head_is_read_off_disk_without_spawning_anything(tmp_path):
    sha = "a" * 40
    _git_repo_at(tmp_path, sha)
    assert picker._head_sha(tmp_path) == sha


def test_a_detached_head_holding_a_raw_sha_resolves(tmp_path):
    sha = "b" * 40
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text(sha + "\n", encoding="utf-8")
    assert picker._head_sha(tmp_path) == sha


def test_a_packed_ref_resolves(tmp_path):
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git / "packed-refs").write_text(
        "# pack-refs with: peeled fully-peeled sorted\n"
        + "c" * 40 + " refs/heads/main\n", encoding="utf-8")
    assert picker._head_sha(git.parent) == "c" * 40


def test_a_linked_worktree_resolves_through_commondir(tmp_path):
    # The shape daedalus.spine.attempt actually creates: .git is a pointer FILE
    # and refs live in the shared common dir, not beside HEAD.
    primary = tmp_path / "primary"
    (primary / ".git" / "refs" / "heads").mkdir(parents=True)
    (primary / ".git" / "refs" / "heads" / "main").write_text(
        "d" * 40 + "\n", encoding="utf-8")
    wt_git = primary / ".git" / "worktrees" / "cand"
    wt_git.mkdir(parents=True)
    (wt_git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (wt_git / "commondir").write_text("../..\n", encoding="utf-8")

    wt = tmp_path / "cand"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {wt_git}\n", encoding="utf-8")
    assert picker._head_sha(wt) == "d" * 40


def test_a_directory_that_is_not_a_repo_reads_as_unknown(tmp_path):
    assert picker._head_sha(tmp_path) is None


# --------------------------------------------------------------------------- #
# inventory freshness                                                          #
# --------------------------------------------------------------------------- #
def test_a_stale_inventory_is_withheld_loudly_not_ranked(tmp_path, no_eval):
    # The measured production case: the inventory recorded f40529c while HEAD
    # was thirty commits later, and it drives the two highest bands.
    _write_inventory(tmp_path, INVENTORY)                 # records abc1234
    _git_repo_at(tmp_path, "9" * 40)
    q = build_queue(tmp_path, limit=None)

    assert q.candidates == ()
    assert q.sources["inventory"]["suppressed"] is True
    assert q.sources["inventory"]["candidates"] == 0
    assert q.sources["inventory"]["freshness"]["fresh"] is False
    note = next(n for n in q.notes if "INVENTORY SUPPRESSED" in n)
    assert "abc1234" in note and "--stale-inventory" in note


def test_a_matching_inventory_is_ranked_normally(tmp_path, no_eval):
    _fresh(tmp_path)
    q = build_queue(tmp_path, limit=None)
    assert q.candidates
    assert q.sources["inventory"]["suppressed"] is False
    assert q.sources["inventory"]["freshness"]["fresh"] is True


def test_a_dirty_snapshot_alone_does_not_suppress(tmp_path, no_eval):
    # This repo is dirty almost all the time mid-session. Refusing to rank work
    # whenever an editor has unsaved changes would make the loop unusable for
    # exactly the person using it. Revision is the signal; dirtiness is FYI.
    payload = json.loads(json.dumps(INVENTORY))
    payload["repo_state"] = {"branch": "b", "head": "abc1234", "dirty": True}
    _write_inventory(tmp_path, payload)
    _git_repo_at(tmp_path, "abc1234" + "0" * 33)
    q = build_queue(tmp_path, limit=None)
    assert q.candidates
    assert q.sources["inventory"]["freshness"]["dirty"] is True
    assert q.sources["inventory"]["suppressed"] is False


def test_freshness_fails_open_when_there_is_no_git_to_ask(tmp_path, no_eval):
    # A tarball checkout is not evidence of staleness. "I cannot tell" must not
    # become "refuse everything".
    _write_inventory(tmp_path, INVENTORY)                 # no .git written
    q = build_queue(tmp_path, limit=None)
    assert q.candidates
    assert q.sources["inventory"]["freshness"]["fresh"] is True
    assert "failing open" in q.sources["inventory"]["freshness"]["reason"]


def test_an_inventory_with_no_recorded_revision_is_not_trusted(tmp_path, no_eval):
    payload = json.loads(json.dumps(INVENTORY))
    payload.pop("repo_state")
    _write_inventory(tmp_path, payload)
    _git_repo_at(tmp_path, "9" * 40)
    q = build_queue(tmp_path, limit=None)
    assert q.sources["inventory"]["suppressed"] is True
    assert q.candidates == ()


def test_stale_inventory_flag_re_admits_the_candidates(tmp_path, no_eval):
    _write_inventory(tmp_path, INVENTORY)
    _git_repo_at(tmp_path, "9" * 40)
    q = build_queue(tmp_path, limit=None, enforce_inventory_freshness=False)
    assert q.candidates
    assert q.sources["inventory"]["suppressed"] is False


def test_a_short_recorded_sha_matches_a_long_head_by_prefix(tmp_path, no_eval):
    # The file records a short sha; git stores a long one. Prefix comparison in
    # BOTH directions, so neither side's abbreviation causes a false "stale".
    assert picker.inventory_freshness(
        {"repo_state": {"head": "abc1234"}},
        _git_repo_at(tmp_path, "abc1234" + "0" * 33))["fresh"] is True


@pytest.mark.parametrize("recorded", ["a", "abc", "zzzzzzz", "", "  "])
def test_a_recorded_head_that_is_not_a_real_abbreviated_sha_is_refused(
        tmp_path, recorded):
    """A prefix test is only meaningful against a real abbreviation.

    Without a shape check, a recorded ``"a"`` matches roughly one HEAD in
    sixteen and the gate reports FRESH by coincidence -- a check that passes by
    accident is worse than no check, because it is believed.
    """
    _git_repo_at(tmp_path, "a" + "0" * 39)
    got = picker.inventory_freshness({"repo_state": {"head": recorded}}, tmp_path)
    assert got["fresh"] is False


def test_a_shorter_actual_head_does_not_satisfy_a_longer_recorded_one(
        tmp_path, monkeypatch):
    """The containment is one-directional: the file records an abbreviation OF
    the full sha, so only ``actual.startswith(recorded)`` can ever be true.

    ``_head_sha`` is stubbed because it will only ever return a full 40-char
    object name -- so this case cannot be built out of a real .git fixture, and
    a test that cannot construct the input it claims to check is not a check.
    """
    monkeypatch.setattr(picker, "_head_sha", lambda root: "abcdef1")
    got = picker.inventory_freshness(
        {"repo_state": {"head": "abcdef1234567890"}}, tmp_path)
    assert got["fresh"] is False


# --------------------------------------------------------------------------- #
# "the source failed" must never look like "there is no work"                  #
# --------------------------------------------------------------------------- #
def _explode(candidate, args):
    raise AssertionError("an attempt was run when none should have been")


def test_a_withheld_source_is_reported_as_degraded(tmp_path, no_eval):
    _write_inventory(tmp_path, INVENTORY)
    _git_repo_at(tmp_path, "9" * 40)
    q = build_queue(tmp_path, limit=None)
    assert q.candidates == ()
    assert q.degraded_sources == ("inventory",)
    assert q.to_dict()["degraded_sources"] == ["inventory"]


def test_a_healthy_source_is_not_degraded(tmp_path, no_eval):
    _fresh(tmp_path)
    q = build_queue(tmp_path, limit=None)
    assert q.degraded_sources == ()


def test_an_unreadable_ledger_also_counts_as_degraded(tmp_path, no_eval):
    _fresh(tmp_path)
    junk = tmp_path / "junk.sqlite3"
    junk.write_text("not a database", encoding="utf-8")
    q = build_queue(tmp_path, limit=None, spine_db=junk)
    assert "attempt_memory" in q.degraded_sources


def test_dry_run_exit_distinguishes_a_withheld_source_from_no_work(
        tmp_path, no_eval, capsys):
    """The distinction a program can branch on.

    Before this, BOTH exited 0: a healthy repo with work waiting, and a repo
    whose only source had been withheld. Automation reading that as "nothing to
    do" would go quiet exactly when something was wrong.
    """
    _write_inventory(tmp_path, INVENTORY)
    _git_repo_at(tmp_path, "9" * 40)                     # stale -> withheld
    rc = picker.main(["--dry-run", "--repo-root", str(tmp_path)],
                     attempt_fn=_explode)
    assert rc == picker.EXIT_SOURCE_UNAVAILABLE
    assert "INCOMPLETE" in capsys.readouterr().out

    _git_repo_at(tmp_path, "abc1234" + "0" * 33)         # fresh -> healthy
    assert picker.main(["--dry-run", "--repo-root", str(tmp_path)],
                       attempt_fn=_explode) == 0


def test_once_exit_distinguishes_a_withheld_source_from_no_work(
        tmp_path, no_eval, capsys):
    _write_inventory(tmp_path, INVENTORY)
    _git_repo_at(tmp_path, "9" * 40)
    rc = picker.main(["--once", "--repo-root", str(tmp_path)],
                     attempt_fn=_explode)
    assert rc == picker.EXIT_SOURCE_UNAVAILABLE
    assert "NOT evidence that there is nothing to do" in capsys.readouterr().out

    # Genuinely no work: sources healthy, inventory simply has no candidates.
    empty = tmp_path / "empty"
    empty.mkdir()
    _write_inventory(empty, {"schema": "daedalus-feature-inventory/1",
                             "repo_state": {"head": "abc1234", "dirty": False},
                             "areas": []})
    _git_repo_at(empty, "abc1234" + "0" * 33)
    assert picker.main(["--once", "--repo-root", str(empty)],
                       attempt_fn=_explode) == picker.EXIT_FAILED


def test_json_output_also_carries_the_degraded_flag(tmp_path, no_eval, capsys):
    _write_inventory(tmp_path, INVENTORY)
    _git_repo_at(tmp_path, "9" * 40)
    rc = picker.main(["--dry-run", "--json", "--repo-root", str(tmp_path)],
                     attempt_fn=_explode)
    payload = json.loads(capsys.readouterr().out)
    assert payload["degraded_sources"] == ["inventory"]
    assert rc == picker.EXIT_SOURCE_UNAVAILABLE


def test_zero_still_only_ever_means_work_is_waiting(tmp_path, no_eval):
    _fresh(tmp_path)
    rc = picker.main(["--dry-run", "--repo-root", str(tmp_path)],
                     attempt_fn=_explode)
    assert rc == 0
    assert build_queue(tmp_path, limit=None).candidates


def test_cli_exposes_forget_and_stale_inventory():
    offered = set(picker._build_parser()._option_string_actions)
    assert "--forget" in offered
    assert "--stale-inventory" in offered
