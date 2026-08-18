"""Tests for the frozen task set: the freeze must actually bind."""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from s09_eval import gitio, taskset  # noqa: E402
from s09_eval.contract import Budget  # noqa: E402

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def frozen():
    return taskset.load(taskset.DEFAULT_PATH)


def test_frozen_set_verifies_its_own_digest(frozen):
    record, cases = frozen
    assert record["schema"] == taskset.SCHEMA
    assert len(cases) == taskset.SELECTION["case_count"]
    assert taskset.digest_of(cases) == record["digest"]


def test_digest_rejects_a_tampered_case(tmp_path, frozen):
    record, cases = frozen
    tampered = list(cases)
    tampered[0] = replace(tampered[0], gold=("some/other/file.py",))
    assert taskset.digest_of(tampered) != record["digest"]

    path = tmp_path / "tampered.json"
    payload = dict(record)
    payload["cases"] = [
        {**c, "gold": ["some/other/file.py"]} if i == 0 else c
        for i, c in enumerate(record["cases"])
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="digest mismatch"):
        taskset.load(path)


def test_every_case_has_reachable_gold_and_a_query(frozen):
    _, cases = frozen
    ids = [c.case_id for c in cases]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
    for case in cases:
        assert case.gold, f"{case.case_id} has empty gold"
        assert len(set(case.gold)) == len(case.gold)
        assert case.query_raw.strip()
        assert case.universe_size > 0
        assert case.commit != case.parent


def test_gold_paths_really_existed_in_the_pre_image_tree(frozen):
    """The claim that gold is retrievable is checked against git, not trusted."""
    _, cases = frozen
    budget = Budget()
    for case in cases[:6]:  # git-backed, so a sample keeps the suite quick
        tree = gitio.list_tree(REPO, case.parent)
        for path in case.gold:
            assert path in tree, f"{case.case_id}: gold {path} absent from parent tree"
            _, size = tree[path]
            assert budget.eligible(path, size)
        for path in case.gold_created_dropped:
            assert path not in tree or not budget.eligible(path, tree[path][1])


def test_scrub_removes_gold_tokens_and_keeps_the_rest():
    message = "fix(g0): the effect boundary rejects an undeclared sink"
    gold = ("daedalus/spine/effect_boundary.py",)
    scrubbed, removed = taskset.scrub(message, gold)
    assert "effect" in removed and "boundary" in removed
    assert "effect" not in scrubbed.split() and "boundary" not in scrubbed.split()
    assert "undeclared" in scrubbed and "rejects" in scrubbed


def test_scrub_is_total_when_the_message_is_only_the_path():
    scrubbed, removed = taskset.scrub("update runs/council/room.md", ("runs/council/room.md",))
    assert scrubbed.split() == ["update"]
    assert set(removed) == {"runs", "council", "room", "md"}


def test_scrubbed_queries_share_no_token_with_their_gold(frozen):
    """The leakage control has to hold for every frozen case, not on average."""
    from s09_eval.tokens import path_tokens, word_tokens

    _, cases = frozen
    for case in cases:
        banned = set()
        for path in case.gold:
            banned |= path_tokens(path)
        assert not (set(word_tokens(case.query_scrubbed)) & banned), case.case_id


def test_the_leak_is_large_enough_to_matter(frozen):
    """Documented property of this corpus: most messages name their file."""
    _, cases = frozen
    leaky = [c for c in cases if c.leak_tokens]
    assert len(leaky) >= len(cases) // 2, (
        "if this ever fails the corpus changed shape; re-read the README claim "
        "that the raw/scrubbed gap is the dominant effect"
    )
