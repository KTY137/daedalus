"""test_taskset.py -- packet G3-BASE-01 acceptance tests A1/A2/A3 plus the
real-corpus measurement that answers "can Gate-3 cross-plane baselines run
today".

Fast, offline, deterministic: no model calls, no network, no filesystem
writes. The only I/O is the read path ``daedalus.eval.harness.all_tasks()``
already exercises in the rest of this repo's test suite.
"""
from __future__ import annotations

import copy
import warnings

import pytest

from daedalus.eval.gate3.contracts import FreezeError, FrozenTaskSet
from daedalus.eval.gate3.taskset import (
    REAL_CORPUS_COUNTING_RULE,
    build_frozen_taskset,
    census,
    classify_task_plane,
    filter_primary_tasks,
)
from daedalus.eval.harness import _is_primary_tier as harness_is_primary_tier
from daedalus.eval.harness import all_tasks


def _task(id_, target, must_include=None, tier="primary"):
    t = {"id": id_, "target": target, "tier": tier}
    if must_include is not None:
        t["must_include"] = must_include
    return t


# --------------------------------------------------------------------------- #
# A1 -- digest stability                                                      #
# --------------------------------------------------------------------------- #

def test_frozen_taskset_digest_is_stable_for_the_same_tasks():
    tasks = [_task("a", "pkg/mod.py", ["foo"]), _task("b", "pkg/other.py", ["bar"])]
    one = build_frozen_taskset("demo", copy.deepcopy(tasks), "count of primary tasks")
    two = build_frozen_taskset("demo", copy.deepcopy(tasks), "count of primary tasks")
    assert one.digest == two.digest


def test_frozen_taskset_digest_changes_when_a_task_changes():
    """Same task id, but the target's plane changes (py -> md): the census
    changes, so the digest must change even though task_ids is unchanged."""
    before = [_task("a", "pkg/mod.py", ["foo"])]
    after = [_task("a", "docs/mod.md", ["free text label"])]
    before_set = build_frozen_taskset("demo", before, "count of primary tasks")
    after_set = build_frozen_taskset("demo", after, "count of primary tasks")
    assert before_set.task_ids == after_set.task_ids  # same id
    assert before_set.digest != after_set.digest       # different content


def test_frozen_taskset_digest_changes_when_counting_rule_changes():
    tasks = [_task("a", "pkg/mod.py", ["foo"])]
    one = build_frozen_taskset("demo", tasks, "rule A")
    two = build_frozen_taskset("demo", tasks, "rule B")
    assert one.digest != two.digest


# --------------------------------------------------------------------------- #
# A2 -- census sums to task count                                             #
# --------------------------------------------------------------------------- #

def test_taskset_reports_label_plane_census_summing_to_task_count():
    tasks = [
        _task("a", "pkg/mod.py", ["foo"]),
        _task("b", "docs/readme.md", ["explains the thing"]),
        _task("c", "schema/user.proto", ["User"]),
        _task("d", "fixtures/rows.csv", ["42,red"]),
    ]
    fts = build_frozen_taskset("demo", tasks, "count of primary tasks")
    assert sum(fts.label_plane_census.values()) == len(fts.task_ids) == 4
    assert fts.label_plane_census == {"code": 1, "type": 1, "data": 1, "knowledge": 1}


def test_census_helper_sums_to_input_length_directly():
    tasks = [_task(str(i), "pkg/mod.py", ["x"]) for i in range(5)]
    c = census(tasks)
    assert sum(c.values()) == len(tasks)
    assert set(c) == {"code", "type", "data", "knowledge"}


# --------------------------------------------------------------------------- #
# A3 -- cross-plane refusal / acceptance                                      #
# --------------------------------------------------------------------------- #

def test_single_plane_taskset_refused_for_crossplane():
    tasks = [_task("a", "pkg/mod.py", ["foo"]), _task("b", "pkg/other.py", ["bar"])]
    fts = build_frozen_taskset("single-plane", tasks, "count of primary tasks")
    assert fts.planes_present == ("code",)
    with pytest.raises(FreezeError):
        fts.require_cross_plane()


def test_multi_plane_taskset_accepted_for_crossplane():
    tasks = [
        _task("a", "pkg/mod.py", ["foo"]),
        _task("b", "docs/readme.md", ["explains the thing"]),
    ]
    fts = build_frozen_taskset("multi-plane", tasks, "count of primary tasks")
    assert set(fts.planes_present) == {"code", "knowledge"}
    fts.require_cross_plane()  # must not raise


# --------------------------------------------------------------------------- #
# classify_task_plane: refusal semantics                                     #
# --------------------------------------------------------------------------- #

def test_classify_refuses_when_target_is_missing():
    with pytest.raises(FreezeError):
        classify_task_plane({"id": "no-target"})


def test_classify_refuses_when_target_has_no_extension():
    with pytest.raises(FreezeError):
        classify_task_plane({"id": "no-ext", "target": "Makefile"})


def test_classify_refuses_on_unknown_extension():
    with pytest.raises(FreezeError):
        classify_task_plane({"id": "weird", "target": "blob.qzx"})


def test_classify_refuses_on_ambiguous_extension_vs_label_shape():
    """.py says code, but must_include is a prose sentence, not identifiers:
    the two signals disagree, so classification refuses rather than trusting
    the extension alone (module docstring decision 2b)."""
    task = {
        "id": "ambiguous",
        "target": "pkg/mod.py",
        "must_include": ["This whole sentence is not an identifier"],
    }
    with pytest.raises(FreezeError):
        classify_task_plane(task)


def test_classify_accepts_code_plane_with_identifier_labels():
    assert classify_task_plane(
        {"id": "a", "target": "pkg/mod.py", "must_include": ["_helper", "Foo"]}
    ) == "code"


def test_classify_accepts_type_plane():
    assert classify_task_plane(
        {"id": "a", "target": "schema/user.proto", "must_include": ["User"]}
    ) == "type"


def test_classify_accepts_data_plane_without_identifier_shape_requirement():
    # data labels may be free-form (values, column names with punctuation);
    # no identifier shape is enforced for data/knowledge.
    assert classify_task_plane(
        {"id": "a", "target": "fixtures/rows.csv", "must_include": ["42, red, 3.5kg"]}
    ) == "data"


def test_classify_accepts_knowledge_plane_with_prose_labels():
    assert classify_task_plane(
        {"id": "a", "target": "docs/readme.md", "must_include": ["explains the thing"]}
    ) == "knowledge"


def test_classify_accepts_task_with_no_must_include_at_all():
    # extension alone is enough when there is nothing to contradict it.
    assert classify_task_plane({"id": "a", "target": "pkg/mod.py"}) == "code"


def test_classify_strips_symbol_suffix_before_reading_extension():
    assert classify_task_plane(
        {"id": "a", "target": "pkg/mod.py::some_function", "must_include": ["x"]}
    ) == "code"


# --------------------------------------------------------------------------- #
# quarantine exclusion: never silent                                         #
# --------------------------------------------------------------------------- #

def test_filter_primary_tasks_reports_exact_exclusion_count():
    tasks = [
        _task("a", "pkg/mod.py", ["x"], tier="primary"),
        _task("b", "pkg/mod2.py", ["y"], tier="quarantine"),
        _task("c", "pkg/mod3.py", ["z"], tier="quarantine"),
        _task("d", "pkg/mod4.py", ["w"], tier="typo-of-primary"),  # fail-closed
    ]
    primary, n_excluded = filter_primary_tasks(tasks)
    assert [t["id"] for t in primary] == ["a"]
    assert n_excluded == 3


def test_filter_primary_tasks_treats_missing_tier_as_quarantine():
    tasks = [{"id": "no-tier", "target": "pkg/mod.py", "must_include": ["x"]}]
    primary, n_excluded = filter_primary_tasks(tasks)
    assert primary == []
    assert n_excluded == 1


def test_build_frozen_taskset_excludes_quarantine_and_warns_with_the_count():
    tasks = [
        _task("a", "pkg/mod.py", ["x"], tier="primary"),
        _task("b", "pkg/mod2.py", ["y"], tier="quarantine"),
    ]
    with pytest.warns(UserWarning, match=r"excluded 1 of 2"):
        fts = build_frozen_taskset("demo", tasks, "count of primary tasks")
    assert fts.task_ids == ("a",)


def test_build_frozen_taskset_does_not_warn_when_nothing_is_excluded():
    tasks = [_task("a", "pkg/mod.py", ["x"], tier="primary")]
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        fts = build_frozen_taskset("demo", tasks, "count of primary tasks")
    assert fts.task_ids == ("a",)


def test_tier_predicate_agrees_with_harness_for_representative_values():
    """Anti-drift check for the reimplemented (not imported) tier predicate --
    see the module docstring for why it is reimplemented rather than
    importing daedalus.eval.harness._is_primary_tier directly."""
    from daedalus.eval.gate3.taskset import _is_primary_tier as ours

    for value in ("primary", "quarantine", "Primary", "PRIMARY", "", None, 0, "primary "):
        assert ours(value) == harness_is_primary_tier(value), value


# --------------------------------------------------------------------------- #
# THE MEASUREMENT THAT MATTERS MOST: the real corpus, [MEASURED]              #
# --------------------------------------------------------------------------- #

def test_real_corpus_census_is_pinned_and_reported():
    """Freezes daedalus.eval.harness.all_tasks() and pins the measured
    plane distribution, so a future change to the task corpus (a new task, a
    re-tiered mint, a plane finally represented) is visible as a test diff
    instead of silently drifting.

    RE-MEASURED 2026-09-09, after G1-EVAL-CORPUS-01. This packet's own
    expiry clause named the event: "immediately if the task corpus gains
    non-code-plane tasks (which would change the central measured finding
    below)". It has. The pin is therefore updated deliberately and the
    headline assertion is INVERTED rather than deleted, so the test still
    fails if the corpus silently drifts back.

    MEASURED on packet G3-BASE-01's base revision (retained, not deleted):
      - all_tasks() total 27; full census code=27, type/data/knowledge 0
      - primary-tier (frozen) subset 10 tasks, all "code"
      - planes_present ("code",), so require_cross_plane() REFUSED, exactly
        as packet §8 expected-failure #1 predicted.

    MEASURED 2026-09-09 on the integration of G3-BASE-01 with
    G1-EVAL-CORPUS-01:
      - all_tasks() total: 31 (14 hand-authored TASKS + 17
        persisted mint tasks, all mint tasks still tier=quarantine)
      - full census: {'code': 27, 'type': 0, 'data': 2, 'knowledge': 2}
      - primary-tier (frozen) subset: 14 tasks
      - label_plane_census on the frozen set: {'code': 10, 'type': 0, 'data': 2, 'knowledge': 2}
      - planes_present: ('code', 'data', 'knowledge')
      - therefore require_cross_plane() ADMITS this task set. The four new
        tasks carry parser-derived, plane-exclusive labels and are reported
        by the product harness as plane-unindexed rather than scored, so
        admitting the set is a corpus fact, not a claim that any arm can
        score them.

    MEASURED 2026-09-09, after G3-MINT-TEXT-01 minted the repository's own
    text (packet: docs/work-packets/G3-MINT-TEXT-01_NON_CODE_TASK_MINTING.md):
      - all_tasks() total: 62 (14 hand-authored + 48 persisted mint tasks:
        17 independent_diff and 31 independent_text_diff, all quarantine)
      - full census: {'code': 27, 'type': 0, 'data': 17, 'knowledge': 18}
      - primary-tier subset: UNCHANGED at 14, census UNCHANGED at
        {'code': 10, 'type': 0, 'data': 2, 'knowledge': 2}
      - the frozen digest is BYTE-IDENTICAL, because every one of the 31 new
        tasks is quarantined. That is the tier gate doing its job, and it is
        the reason this update is safe: 31 tasks entered the corpus and not
        one entered a number.

      MEASURED 2026-09-10, after G3-MINT-AUDIT promoted on a second witness:
        - primary tier: 14 -> 49; census {'code': 24, 'type': 0, 'data': 16,
          'knowledge': 9}; frozen digest MOVED (see the note at the assertion)
        - 35 tasks left quarantine, none by recurrence. Every one carries
          promoted_by="noise_audit": the threats MINT_CONFIRM_THRESHOLD's own
          comment names were checked and found absent, 32 of them ruled out BY
          CONSTRUCTION (their anchor file was added by the minting commit, so
          there was nothing to reformat and nothing to rename within).
        - COMPLETE SEPARATION IS BROKEN, which was the point. Before, every
          non-code primary task came from one packaged fixture. Now data holds
          14 agent_env + 2 fixture, and knowledge holds 7 agent_env + 2
          fixture. Every plane spans more than one repository, so a plane
          effect and an origin effect are no longer perfectly confounded.
        - the promoted tasks discriminate: over the 35, bm25 means 0.209 and
          separate_indices means 0.500 at budget 4000, with 14 and 17 distinct
          score values and zero errors. They are graded tasks, not the
          constants the fixture rows turned out to be.
        - still quarantined: 11 Markdown/JSON tasks whose normalizer does not
          exist yet (undecided is never promoted) and 2 whose target did not
          exist at their own minted_at_sha (unverifiable provenance).

      WHAT THE 2026-09-09 BLOCK BELOW GOT RIGHT AND WHAT TIME OVERTOOK: its
      statement that the confound "persists AT THE TIER THAT FEEDS A HEADLINE
      NUMBER" was true when written and is no longer. Its diagnosis of WHY --
      that MINT_CONFIRM_THRESHOLD assumes label sets recur and they do not --
      still stands, and is exactly why the second witness had to exist.

      WHAT THIS DOES NOT FIX, stated here so the next reader does not infer
      it: the primary tier's data and knowledge tasks are still the four
      artifact_parsed ones from the six-file fixture. The confound measured in
      docs/G3_CORPUS_IS_TWO_POPULATIONS_20260909.md -- code tasks from the
      real repository against non-code tasks from a toy -- is unchanged AT THE
      TIER THAT FEEDS A HEADLINE NUMBER. The repository-derived replacements
      exist now, but none can be promoted: minting produced ZERO
      confirmations, because no two of 400 commits yielded the same
      must_include set. MINT_CONFIRM_THRESHOLD assumes label sets recur; for
      Markdown headings and JSON keys they essentially do not.
    """
    tasks = all_tasks()
    assert len(tasks) == 62, (
        "the real task corpus size changed since this test was pinned -- "
        "update this test deliberately, do not just bump the number")

    # Full corpus (including quarantine), for transparency about what exists
    # even though it is not in the frozen set.
    full_census = census(tasks)
    assert full_census == {"code": 27, "type": 0, "data": 17, "knowledge": 18}

    primary, n_excluded = filter_primary_tasks(tasks)
    assert len(primary) == 14
    assert n_excluded == 48

    with pytest.warns(UserWarning, match=r"excluded 48 of 62"):
        fts = build_frozen_taskset(
            "gate3-real-corpus-20260906", tasks, REAL_CORPUS_COUNTING_RULE)

    assert isinstance(fts, FrozenTaskSet)
    assert len(fts.task_ids) == 14
    assert fts.label_plane_census == {"code": 10, "type": 0, "data": 2, "knowledge": 2}
    assert fts.planes_present == ("code", "data", "knowledge")

    # Pinned digest: deterministic given the frozen name/counting-rule/corpus
    # triple above. Changes only if the corpus, the counting rule text, or
    # this test's chosen name changes.
    # MOVED to d1690bf5... on 2026-09-10 when 35 tasks were promoted on a
    # noise-audit witness, and MOVED BACK the same day when that witness was
    # refuted: an independent pass showed a byte-identical COPY is reported by
    # git as an add, so "the anchor file was added, therefore T1/T2 are
    # impossible" does not hold -- and one promoted task was a pure packaging
    # move whose labels were recoverable from the copies' pre-images. The
    # promotion is reverted; the audits are retained as evidence.
    #
    # This digest is therefore the SAME value it has held since 2026-09-06.
    # The note below still stands: a digest that moves here without a
    # deliberate, defensible promotion means a quarantined task leaked into a
    # scored set.
    assert fts.digest == (
        "210e117ebac63df18eacd51ac7954df7c9084e8ba8f4aac86c65d77902056838")

    # THE HEADLINE FINDING, INVERTED BY MEASUREMENT (2026-09-09). It used to
    # read: a cross-plane comparison cannot be run today, and R3 refused. The
    # corpus packet supplied data- and knowledge-plane tasks with parser-derived
    # labels, so the refusal is gone. The assertion is kept, not deleted, so a
    # corpus that silently drifted back to one plane would fail here.
    fts.require_cross_plane()
    assert set(fts.planes_present) >= {"code", "data", "knowledge"}
    assert fts.label_plane_census["type"] == 0, (
        "the type plane is still empty: no type-plane artifact exists under the "
        "frozen extension rule, and manufacturing one to move a census would be "
        "plane laundering")
