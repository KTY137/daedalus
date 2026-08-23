"""Guards for the cross-plane corpus.

Every test here asserts a *behaviour* of the artifact or of the builder, not
the presence of a word in a source file.  That distinction has cost this
repository twice already: a guard that scanned source text for "any"
occurrence of something was satisfied by an unrelated occurrence and stayed
green through the exact change it existed to catch.  So: no ``in
source_text`` assertions.  A guard here goes red because the corpus changed
shape, not because a docstring was reworded.

Each of these was mutation-tested -- the guard was disabled, the named test
was watched go red, and the guard was restored -- before it was committed.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from s09_eval import taskset, taskset_xplane  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
XPATH = HERE / "taskset_xplane.json"
OLD_PATH = HERE / "taskset.json"

#: The digest slice s07 pins the FIRST corpus by. Written out here so that a
#: rebuild of that corpus fails this file rather than silently invalidating
#: every number published against it.
OLD_DIGEST = (
    "sha256:c3ef36f19ebaaf953ef8c26615295dfe7e845a89ec68b50ffb5c933df96d8c33"
)

#: The one rename-dominated commit in this history: 249 of its 309 diff
#: entries are R100 renames under ``runs/audit_swarm/``.
RENAME_DOMINATED = "946db82afb24e0cebeeb7f5af686fb633f246cd5"

#: Two commits with the work-packet seam shape: a document, its machine-
#: readable contract, the implementation, and the workflow, all in one commit.
SEAM_COMMITS = (
    "4d67a5623",
    "824b1ec93",
)


@pytest.fixture(scope="module")
def loaded():
    return taskset_xplane.load(XPATH)


@pytest.fixture(scope="module")
def record(loaded):
    return loaded[0]


@pytest.fixture(scope="module")
def cases(loaded):
    return loaded[1]


# ------------------------------------------------ the first corpus is intact
def test_the_first_corpus_is_byte_reachable_and_unchanged():
    """The old task set must survive this slice untouched.

    Slice s07 vendors it by content. If it is rebuilt, renumbered, or
    re-frozen, every number measured against it becomes unverifiable at once.
    This test loads it through its OWN loader, which recomputes the digest
    from the cases, so a silent edit to the case list fails here.
    """
    old_record, old_cases = taskset.load(OLD_PATH)
    assert old_record["schema"] == "forest_v2.s09.taskset/2"
    assert old_record["digest"] == OLD_DIGEST
    assert taskset.digest_of(old_cases) == OLD_DIGEST
    assert len(old_cases) == 20
    assert [c.case_id for c in old_cases] == [f"c{i:02d}" for i in range(20)]


def test_the_two_corpora_are_separate_artifacts(record, cases):
    """Additive means additive: two files, two schemas, two digests."""
    old_record, _ = taskset.load(OLD_PATH)
    assert record["schema"] != old_record["schema"]
    assert record["digest"] != old_record["digest"]
    assert XPATH != OLD_PATH
    assert taskset_xplane.DEFAULT_PATH.name != taskset.DEFAULT_PATH.name
    # case ids cannot collide, so a mixed analysis cannot silently merge them
    assert {c.case_id[0] for c in cases} == {"x"}


# --------------------------------------------------------- frozen by digest
def test_load_verifies_the_digest_over_the_cases(record, cases):
    assert taskset_xplane.digest_of(cases) == record["digest"]


def test_load_refuses_a_tampered_case(tmp_path):
    """A corpus that can be edited after the fact is not frozen."""
    doc = json.loads(XPATH.read_text(encoding="utf-8"))
    doc["cases"][0]["gold"] = list(doc["cases"][0]["gold"]) + ["README.md"]
    victim = tmp_path / "tampered.json"
    victim.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="digest mismatch"):
        taskset_xplane.load(victim)


def test_load_refuses_a_foreign_schema(tmp_path):
    doc = json.loads(XPATH.read_text(encoding="utf-8"))
    doc["schema"] = "forest_v2.s09.taskset/2"
    victim = tmp_path / "wrong_schema.json"
    victim.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="schema"):
        taskset_xplane.load(victim)


# --------------------------------------------- a rule must be able to reject
def test_every_selection_rule_rejects_at_least_one_commit(record):
    """A rule that cannot reject anything is not a rule.

    Asserted against the artifact's own rejection ledger, so it stays true of
    the corpus that actually shipped rather than of the code that built it.
    """
    reasons = record["census"]["rejection_reasons"]
    for rule in taskset_xplane.SELECTION_RULES:
        assert reasons.get(rule, 0) >= 1, f"rule {rule!r} rejected nothing"


def test_a_branch_that_never_fires_is_not_listed_as_a_rule(record):
    """``parent_tree_unreadable`` fires zero times here and says so.

    It is kept as an I/O guard and kept OUT of the rule list, because a
    never-firing branch presented as a safeguard is how a corpus acquires the
    appearance of rigour it does not have.
    """
    assert "parent_tree_unreadable" not in taskset_xplane.SELECTION_RULES
    assert "parent_tree_unreadable" in record["structural_guards_that_are_not_rules"]
    assert record["census"]["rejection_reasons"].get("parent_tree_unreadable", 0) == 0


def test_dropped_rules_record_their_measured_zero(record):
    dropped = record["rules_dropped_because_they_reject_nothing"]
    assert dropped, "the rules that were tried and removed must stay on record"
    for name, detail in dropped.items():
        assert detail["measured_rejections"] == 0, name


# ------------------------------------------------------- the denominator
def test_census_buckets_add_up(record):
    """Considered = rejected + admissible; admissible = accepted + unsampled.

    The first corpus recorded 35 considered / 20 accepted / 15 rejected and
    had no counter at all for the commits it never looked at. Four buckets
    that close is the fix.
    """
    census = record["census"]
    assert (
        census["commits_rejected_by_rule"] + census["commits_admissible"]
        == census["commits_considered"]
    )
    assert (
        census["commits_accepted"] + census["commits_admissible_but_not_sampled"]
        == census["commits_admissible"]
    )
    assert census["buckets_sum_to_considered"] is True


def test_rejections_carry_a_reason_each(record):
    reasons = record["census"]["rejection_reasons"]
    assert sum(reasons.values()) == record["census"]["commits_rejected_by_rule"]
    for rule in reasons:
        assert rule in taskset_xplane.RULE_REASONS, f"{rule} has no recorded reason"


def test_supply_chain_closes(record):
    """Raw cross-plane supply minus each rule's take equals what is left."""
    chain = record["supply_chain"]
    remaining = chain["cross_plane_before_any_rule"]
    for step in chain["steps"]:
        remaining -= step["cross_plane_removed"]
        assert step["cross_plane_remaining"] == remaining
    assert remaining == chain["cross_plane_admissible"]
    assert chain["chain_closes"] is True


# ------------------------------------------------------------ the contaminants
def test_the_rename_dominated_commit_is_absent_and_accounted_for(record, cases):
    """Excluded by rule, and the rule says which commit it took.

    Not excluded by hand: no commit sha appears in the selection code.
    """
    assert RENAME_DOMINATED not in {c.commit for c in cases}
    step = next(
        s for s in record["supply_chain"]["steps"] if s["rule"] == "rename_dominated_diff"
    )
    assert RENAME_DOMINATED in step["commits"]


def test_no_case_carries_more_gold_than_the_largest_cutoff(record, cases):
    """Recall@k cannot reach 1 above k, for any retriever including a perfect one."""
    max_k = max(record["universe_rule"]["cutoffs"])
    assert max_k == taskset_xplane.SELECTION["max_gold_paths"]
    over = [(c.case_id, len(c.gold)) for c in cases if len(c.gold) > max_k]
    assert over == []


def test_the_cap_reports_what_it_cost(record):
    """The cap is allowed to cost something; it is not allowed to hide it."""
    cost = record["cap_cost"]
    assert cost["commits_excluded"] >= 1
    assert cost["cross_plane_commits_excluded"] >= 1
    assert (
        cost["cross_plane_supply_after_cap"]
        == cost["cross_plane_supply_before_cap"] - cost["cross_plane_commits_excluded"]
    )
    assert len(cost["excluded"]) == cost["commits_excluded"]


# ------------------------------------------------------ composition targets
def test_the_corpus_meets_the_size_and_composition_targets(record, cases):
    """The three targets this corpus exists to hit, asserted on the artifact.

    n>=60 comes from power, not taste: at the observed per-case reciprocal-
    rank spread, n=20 cannot resolve an effect below about 0.15 MRR against a
    base of 0.1168.
    """
    comp = record["plane_composition"]
    assert len(cases) >= 60
    assert comp["cases_total"] == len(cases)
    assert comp["cases_spanning_more_than_one_plane"] >= 20
    assert comp["cases_touching_the_knowledge_plane"] >= 15


def test_plane_composition_is_recomputable_from_the_cases(record, cases):
    """The declared composition is not allowed to be prose about the cases."""
    comp = record["plane_composition"]
    multi = sum(1 for c in cases if len(c.gold_planes) > 1)
    knowledge = sum(1 for c in cases if "knowledge" in c.gold_planes)
    slots = sum(len(c.gold) for c in cases)
    assert comp["cases_spanning_more_than_one_plane"] == multi
    assert comp["cases_touching_the_knowledge_plane"] == knowledge
    assert comp["gold_paths_total"] == slots
    combos = {}
    for case in cases:
        key = "+".join(case.gold_planes) or "(none)"
        combos[key] = combos.get(key, 0) + 1
    assert comp["cases_by_plane_combination"] == combos


def test_each_case_declares_the_planes_its_own_gold_spans(cases):
    for case in cases:
        assert case.gold_planes == taskset_xplane.twin_planes(case.gold)


# ----------------------------------------------------------- the Type plane
def test_the_type_plane_has_no_gold_slot_anywhere(record, cases):
    """Declared unrepresentable, and measurably empty.

    Not papered over by counting a ``.py`` file that happens to carry
    annotations: the retrievable unit is the file, so such a case would score
    a retriever for finding code.

    Checked twice on purpose. Reading only the frozen record proves the
    artifact is clean but says nothing about the labeller: mutation testing
    showed that a builder rewritten to relabel every ``.py`` as ``type`` left
    this test green, because the record it read had been frozen before the
    change. The second loop runs the live labeller over the corpus's own
    paths, so the claim "this corpus cannot name the Type plane" is asserted
    against the code that would name it.
    """
    assert record["plane_composition"]["type_plane_representable"] is False
    assert record["plane_composition"]["type_plane_gold_slots"] == 0
    for case in cases:
        assert "type" not in case.gold_planes
        for path in case.gold:
            assert taskset.plane_of(path) != "type"
    for case in cases:
        assert "type" not in taskset_xplane.twin_planes(case.gold), case.case_id


def test_presentation_paths_cannot_make_a_case_cross_plane():
    """``.html``/``.css`` are gold, but they are not a Project-Twin plane.

    Counting them would inflate this history's cross-plane supply from 61
    commits to 70.
    """
    assert taskset_xplane.twin_planes(["a/x.py", "a/x.html", "a/y.css"]) == ("code",)
    assert taskset_xplane.twin_planes(["a/x.html"]) == ()
    assert taskset_xplane.twin_planes(["a/x.py", "docs/y.md"]) == ("code", "knowledge")


# ------------------------------------------------------------- the seam shape
def test_seam_detection_needs_one_artifact_in_two_planes():
    """A shared stem across planes, not merely two files in one commit.

    Two files changing together because somebody ran a formatter satisfies
    "multi-plane" and is not cross-plane evidence; the seam label exists to
    tell those apart.
    """
    seam = taskset_xplane.seam_stems(
        ["docs/work-packets/G0.md", "docs/work-packets/G0.json", "daedalus/g0.py"]
    )
    assert seam == ("g0",)
    # same two planes, unrelated artifacts -> no seam
    assert taskset_xplane.seam_stems(["daedalus/router.py", "docs/HANDOFF.md"]) == ()
    # same stem but same plane -> no seam
    assert taskset_xplane.seam_stems(["a/router.py", "b/router.py"]) == ()


def test_the_known_work_packet_seams_are_in_the_corpus_and_labelled(cases):
    by_prefix = {c.commit[:9]: c for c in cases}
    for prefix in SEAM_COMMITS:
        assert prefix in by_prefix, f"seam commit {prefix} missing from the corpus"
        case = by_prefix[prefix]
        assert case.seam_stems, f"seam commit {prefix} was not labelled as a seam"
        assert len(case.gold_planes) >= 3


# --------------------------------------------------- gold before retriever
def test_building_the_corpus_imports_no_retriever_and_no_scorer():
    """Gold is derived before anything is pointed at it -- checked, not promised.

    Asserted on the import graph of a fresh interpreter. A ``from . import
    retrievers`` added to the builder turns this red; a reworded docstring
    does not.
    """
    probe = (
        "import sys, json\n"
        f"sys.path.insert(0, r'{HERE.parent}')\n"
        "import s09_eval.taskset_xplane\n"
        "leaked = sorted(m for m in sys.modules if any(\n"
        "    part in m for part in ('retriev', 'metrics', 'harness', 'stats')))\n"
        "print(json.dumps(leaked))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr
    leaked = json.loads(proc.stdout.strip().splitlines()[-1])
    assert leaked == [], f"the task-set builder pulled in {leaked}"


def test_the_anchor_and_the_rule_are_recorded_in_the_artifact(record):
    assert record["anchor_commit"] == taskset_xplane.ANCHOR
    assert len(record["anchor_commit"]) == 40
    assert record["selection"]["anchor"] == taskset_xplane.ANCHOR
    assert record["selection_rules_in_order"] == list(taskset_xplane.SELECTION_RULES)


# ---------------------------------------- independent reconstruction of gold
def _git(*args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(REPO), *args], capture_output=True, check=False
    )
    if proc.returncode != 0:
        pytest.skip(f"git unavailable or object missing: {args}")
    return proc.stdout.decode("utf-8", "replace")


def test_gold_is_reconstructible_from_raw_git_without_this_package(cases):
    """Rebuild three cases' gold from ``git`` directly and compare.

    This is the property that made the first corpus survive an independent
    reconstruction when nine sibling slices did not: the gold is a function of
    the history and the stated rule, so anyone with the repository can
    recompute it without trusting a line of this package.
    """
    budget = taskset_xplane.Budget()
    sample = [cases[0], cases[len(cases) // 2], cases[-1]]
    for case in sample:
        tree_raw = _git("ls-tree", "-r", "-l", case.parent)
        parent_tree = {}
        for line in tree_raw.splitlines():
            meta, _, path = line.partition("\t")
            parts = meta.split()
            if len(parts) < 4 or parts[1] != "blob" or parts[3] == "-":
                continue
            parent_tree[path] = int(parts[3])
        changed = [
            line.strip()
            for line in _git(
                "show", "--no-merges", "--pretty=format:", "--name-only", case.commit
            ).splitlines()
            if line.strip()
        ]
        expected = tuple(
            sorted(
                p
                for p in changed
                if p in parent_tree and budget.eligible(p, parent_tree[p])
            )
        )
        assert case.gold == expected, case.case_id
        for path in case.gold:
            assert path in parent_tree, f"{case.case_id}: {path} not in the pre-image"


# --------------------------------------------------------- the control arm
def test_the_control_stratum_is_matched_on_gold_set_size(record, cases):
    """A single-file control would confound plane-span with gold-set size.

    Cross-plane cases are multi-file by construction, so the control is drawn
    only from single-plane commits that are also multi-file.
    """
    control = [c for c in cases if c.stratum == "single_plane_control"]
    cross = [c for c in cases if c.stratum == "cross_plane"]
    assert control and cross
    floor = record["selection"]["control_min_gold_paths"]
    assert min(len(c.gold) for c in control) >= floor
    assert min(len(c.gold) for c in cross) >= 2
    for case in control:
        assert len(case.gold_planes) == 1
    for case in cross:
        assert len(case.gold_planes) >= 2


def test_every_cross_plane_commit_in_history_was_taken(record):
    """Supply, not a quota, is the ceiling on the cross-plane stratum."""
    supply = record["census"]["supply"]
    assert supply["cross_plane_unused"] == 0
    assert supply["cross_plane_accepted"] == supply["cross_plane_admissible"]


def test_case_order_is_a_deterministic_function_of_the_commit_sha(cases):
    keys = [taskset_xplane._order_key(c.commit) for c in cases]
    assert keys == sorted(keys)
    assert [c.case_id for c in cases] == [f"x{i:02d}" for i in range(len(cases))]


def test_scrubbed_queries_drop_exactly_the_recorded_leak_tokens(cases):
    for case in cases:
        scrubbed, removed = taskset.scrub(case.query_raw, case.gold)
        assert scrubbed == case.query_scrubbed, case.case_id
        assert tuple(removed) == case.leak_tokens, case.case_id


def test_the_readme_table_is_pinned_to_the_artifact(record):
    """Every figure quoted in the README's composition table, pinned here.

    Deliberately dumb, and the same convention ``test_published_numbers``
    already applies to the first corpus: if one of these goes red, either the
    artifact was regenerated and the README is now lying, or the README was
    edited and the artifact disagrees. Both are the failure this exists to
    catch.
    """
    comp = record["plane_composition"]
    census = record["census"]
    assert comp["cases_total"] == 88
    assert comp["gold_paths_total"] == 475
    assert comp["cases_spanning_more_than_one_plane"] == 58
    assert comp["cases_spanning_three_planes"] == 13
    assert comp["cases_touching_the_knowledge_plane"] == 45
    assert comp["cases_with_a_cross_plane_stem_seam"] == 5
    assert comp["cases_matching_the_gate1_python_markdown_csv_shape"] == 0
    assert comp["presentation_slots_not_counted_as_plane_span"] == 13
    assert comp["gold_slots_by_plane"] == {
        "code": 313, "knowledge": 78, "data": 71, "presentation": 13
    }
    assert comp["cases_by_plane_combination"] == {
        "code": 28, "code+knowledge": 22, "code+data": 14,
        "code+data+knowledge": 13, "data+knowledge": 9, "data": 1, "knowledge": 1,
    }
    assert census["commits_considered"] == 1457
    assert census["commits_rejected_by_rule"] == 691
    assert census["commits_admissible"] == 766
    assert census["commits_admissible_but_not_sampled"] == 678
    assert census["commits_accepted"] == 88
    assert census["rejection_reasons"] == {
        "no_retrievable_gold_in_pre_image": 687,
        "gold_exceeds_largest_cutoff": 3,
        "rename_dominated_diff": 1,
    }
    assert census["supply"]["cross_plane_admissible"] == 58
    assert census["supply"]["single_plane_control_accepted"] == 30
    assert record["supply_chain"]["cross_plane_before_any_rule"] == 61
    assert record["cap_cost"]["tri_plane_commits_excluded"] == 2
    assert record["digest"] == (
        "sha256:0148e7f0e3744c40420cc90e31ee0f306930f7ac9e341289d8e5ac247e6c6386"
    )


def test_dropped_paths_are_split_by_cause_not_lumped_together(cases):
    """The first corpus's ``gold_created_dropped`` merged two causes under one
    misleading name. Here the two are separate fields and cannot overlap."""
    for case in cases:
        assert not (set(case.gold_dropped_created) & set(case.gold_dropped_ineligible))
        assert not (set(case.gold_dropped_created) & set(case.gold))
        assert not (set(case.gold_dropped_ineligible) & set(case.gold))
