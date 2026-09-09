"""Pin the Type-plane probe result and the refinement that produced it.

Fast: asserts over the RETAINED probe output under
``docs/evidence/gate2-type-plane-20260909/``, not a re-walk of 1200 commits
(that takes ~40 s and shells out to git per commit). The probe itself is
re-runnable by hand and its command is in the write-up.

These numbers are load-bearing for a correction: the first version of
``docs/GATE2_CROSS_PLANE_SUPPLY_CEILING_20260909.md`` claimed that closing the
Type-plane gap would make one more criterion DECIDABLE without a second
repository. The measurement says evaluable, not decidable, and these pins are
what keep that correction from drifting back.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from experiments.forest_v2.s09_eval import probe_type_plane_supply as subject

EVIDENCE = (
    Path(__file__).resolve().parents[3]
    / "docs" / "evidence" / "gate2-type-plane-20260909"
)
RESULT = json.loads((EVIDENCE / "probe_run1.json").read_text(encoding="utf-8"))
ACCEPTANCE = json.loads((EVIDENCE / "acceptance.json").read_text(encoding="utf-8"))


def test_both_retained_runs_are_byte_identical():
    """Determinism is the precondition for pinning anything below."""
    digests = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(EVIDENCE.glob("probe_run*.json"))
    }
    assert len(digests) == 2
    assert len(set(digests.values())) == 1
    assert digests == ACCEPTANCE["sha256"]


def test_the_type_plane_is_empty_by_RULE_not_by_repository():
    """51 commits carry Type gold once schemas are labelled as Type."""
    assert RESULT["commits_with_type_gold"] == 51
    assert RESULT["type_gold_paths_total"] == 52
    assert RESULT["frozen_plane_combinations"].get("type") is None
    assert RESULT["refined_plane_combinations"]["type"] == 41


def test_the_refinement_creates_four_plane_commits_where_there_were_none():
    frozen = RESULT["frozen_plane_combinations"]
    refined = RESULT["refined_plane_combinations"]
    assert not any(len(k.split("+")) == 4 for k in frozen), frozen
    assert refined["code+data+knowledge+type"] == 7


def test_the_refinement_adds_NO_cross_plane_supply():
    """The correction. This is why 14.4 becomes evaluable, not decidable.

    Every commit that gains a Type label was already multi-plane or already
    single-plane `data`; none crosses from single-plane into cross-plane. The
    binding constraint of the supply-ceiling write-up is untouched.
    """
    assert RESULT["commits_that_become_cross_plane"] == 0


@pytest.mark.parametrize(
    "path, expected",
    [
        ("configs/schemas/effect-lease-v1.schema.json", "type"),
        ("daedalus/resources/schemas/anything.schema.json", "type"),
        # NOT captured: ordinary data, config and code keep their plane
        ("apps/web/components.json", "data"),
        ("configs/policy.json", "data"),
        ("daedalus/kernel/seals.py", "code"),
        ("docs/HANDOFF.md", "knowledge"),
        ("data/rows.csv", "data"),
    ],
)
def test_the_refinement_is_exactly_one_rule(path, expected):
    """`*.schema.json` and nothing else. A broader rule would capture ordinary
    config and quietly inflate the very census it is meant to measure."""
    assert subject.refined_plane_of(path) == expected


def test_the_frozen_rule_is_untouched():
    """The probe must not have changed the frozen taskset's plane assignment.

    Changing `plane_of` would re-cut every existing measurement and move a
    pinned digest. That is a packet with its own baseline, not a side effect.
    """
    from experiments.forest_v2.s09_eval import taskset as frozen

    assert frozen.plane_of("configs/schemas/effect-lease-v1.schema.json") == "data"
    assert "type" not in set(frozen.PLANE_BY_SUFFIX.values())
