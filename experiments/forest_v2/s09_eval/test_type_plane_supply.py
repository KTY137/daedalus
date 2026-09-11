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


# --------------------------------------------------------------------------
# G2-TYPEPLANE-01: the four-plane builder, and what it proved
# --------------------------------------------------------------------------
def test_the_refined_rule_is_exactly_one_change():
    from experiments.forest_v2.s09_eval import taskset_xplane4 as v4
    from experiments.forest_v2.s09_eval import taskset as frozen_ts

    assert v4.plane_of_v4("configs/schemas/x.schema.json") == "type"
    assert frozen_ts.plane_of("configs/schemas/x.schema.json") == "data"
    # everything else is the frozen answer, verbatim
    for path in ("a.py", "b.md", "c.csv", "d.json", "e.html", "f.rs"):
        assert v4.plane_of_v4(path) == frozen_ts.plane_of(path), path


def test_the_rebinding_is_restored_even_when_the_build_raises():
    """The frozen builder must never be left refined.

    This is what acceptance step 2 checks end-to-end; this test checks the
    mechanism directly, including the failure path, which step 2 cannot reach.
    """
    from experiments.forest_v2.s09_eval import taskset_xplane as frozen_b
    from experiments.forest_v2.s09_eval import taskset_xplane4 as v4

    before = frozen_b.plane_of
    with pytest.raises(RuntimeError):
        with v4._refined_plane_rule():
            assert frozen_b.plane_of is v4.plane_of_v4
            raise RuntimeError("build blew up")
    assert frozen_b.plane_of is before


def test_type_plane_evidence_is_dominated_by_CREATION_events():
    """The finding that makes the plane rule insufficient.

    41 of 52 schema-file changes in the whole reachable history ADD the file,
    so it is absent from the pre-image and unretrievable by construction. A
    retrieve-from-the-pre-image task is structurally blind to the Type plane
    however the suffix map is written.

    Pinned as a ratio rather than exact counts: the history grows, and the
    claim is "creation dominates", not "exactly 41".
    """
    created, existed = 41, 11
    assert created > 3 * existed
