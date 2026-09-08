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

    MEASURED on packet G3-BASE-01's base revision:
      - all_tasks() total: 27 (10 hand-authored TASKS + 17 persisted mint
        tasks, all mint tasks currently tier=quarantine)
      - every task in the corpus targets a .py or .tsx file with
        identifier-shaped must_include labels -> classify_task_plane finds
        "code" for all 27, with zero refusals
      - primary-tier (frozen) subset: 10 tasks, all "code"
      - planes_present on the frozen set: ("code",) -- exactly one plane
      - therefore require_cross_plane() REFUSES this task set for any
        cross-plane comparison. That refusal is the correct, expected
        result predicted by packet §8 expected-failure #1, not a bug to
        route around.
    """
    tasks = all_tasks()
    assert len(tasks) == 27, (
        "the real task corpus size changed since this test was pinned -- "
        "update this test deliberately, do not just bump the number")

    # Full corpus (including quarantine), for transparency about what exists
    # even though it is not in the frozen set.
    full_census = census(tasks)
    assert full_census == {"code": 27, "type": 0, "data": 0, "knowledge": 0}

    primary, n_excluded = filter_primary_tasks(tasks)
    assert len(primary) == 10
    assert n_excluded == 17

    with pytest.warns(UserWarning, match=r"excluded 17 of 27"):
        fts = build_frozen_taskset(
            "gate3-real-corpus-20260906", tasks, REAL_CORPUS_COUNTING_RULE)

    assert isinstance(fts, FrozenTaskSet)
    assert len(fts.task_ids) == 10
    assert fts.label_plane_census == {"code": 10, "type": 0, "data": 0, "knowledge": 0}
    assert fts.planes_present == ("code",)

    # Pinned digest: deterministic given the frozen name/counting-rule/corpus
    # triple above. Changes only if the corpus, the counting rule text, or
    # this test's chosen name changes.
    assert fts.digest == (
        "1404e1d27283e6e9462303e25831f41653513416e8b5b6d204cee76515ca4c90")

    # The headline finding: a cross-plane comparison cannot be run today.
    with pytest.raises(FreezeError, match="single-plane label set"):
        fts.require_cross_plane()
