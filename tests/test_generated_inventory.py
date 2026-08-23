"""The feature inventory is GENERATED, and the snapshot says what it scanned.

Two defects, one shape. ``docs/FEATURE_INVENTORY.json`` was typed by hand,
recorded ``head: f40529c``, and was still steering the two highest bands of the
self-improvement picker thirty commits later. ``docs/architecture-state.json``
was generated and digest-covered -- and recorded NO head at all, so a baseline
taken thirty commits ago verified its own digest perfectly and read as current.
Integrity is not freshness. A file can be provably unedited and still describe
a tree that no longer exists.

Every test here is a guard, and every guard was verified by disabling the code
it defends and watching this file go red. The docstrings say which line to
break; the report says how many went red.

Nothing here touches the network, a model, or a vendor CLI. The tmp fixtures
are real (tiny) source trees plus a hand-built ``.git`` directory -- HEAD and a
ref file are all :func:`daedalus.mapping.render._head` reads, so a test can pin
a revision without spawning git.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from daedalus.mapping import drift, inventory, reach, render

ROOT = Path(__file__).resolve().parents[1]

FIXTURE_SHA = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
FIXTURE_BRANCH = "fixture-branch"


# --------------------------------------------------------------------------- #
# fixtures                                                                     #
# --------------------------------------------------------------------------- #
BASE = {
    "pyproject.toml": (
        '[project]\nname = "pkg"\n\n'
        '[project.scripts]\npkg = "pkg.cli:main"\n\n'
        '[tool.setuptools]\npackages = [\n    "pkg",\n    "pkg.sub",\n]\n'
    ),
    "pkg/__init__.py": "from pkg import wired\n",
    "pkg/wired.py": "from pkg import deep\nVALUE = 1\n",
    "pkg/deep.py": "VALUE = 2\n",
    "pkg/cli.py": "from pkg import clionly\n\n\ndef main():\n    return 0\n",
    "pkg/clionly.py": "X = 1\n",
    "pkg/lonely.py": "VALUE = 3\n",
    "pkg/sub/__init__.py": "",
    "tests/test_main.py": "from pkg import wired\nfrom pkg import lonely\n",
}


def mk(root: Path, files: dict) -> Path:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


def fake_git(root: Path, sha: str = FIXTURE_SHA,
             branch: str = FIXTURE_BRANCH) -> Path:
    """A ``.git`` with exactly the two files ``render._head`` reads.

    No subprocess, no objects, no clock. The point is to pin a revision, and
    ``git init`` would pin whatever the machine felt like.
    """
    git = root / ".git"
    (git / "refs" / "heads").mkdir(parents=True, exist_ok=True)
    (git / "HEAD").write_text(f"ref: refs/heads/{branch}\n", encoding="utf-8")
    (git / "refs" / "heads" / branch).write_text(sha + "\n", encoding="utf-8")
    return root


@pytest.fixture
def repo(tmp_path):
    return mk(tmp_path, BASE)


@pytest.fixture
def reports(repo):
    """One analysis per test, shared by every build in it -- the same discipline
    ``daedalus map`` follows, and for the same reason: two analyses are two
    chances to disagree."""
    return render.analyse_once(repo)


def built(repo, reports, **kw):
    kw.setdefault("probe_dirty", False)
    return inventory.build(repo, reports=reports, **kw)


def statuses(doc) -> dict:
    return {f["module"]: f["status"]
            for area in doc["areas"] for f in area["features"] if f["module"]}


def features(doc) -> list:
    return [f for area in doc["areas"] for f in area["features"]]


# --------------------------------------------------------------------------- #
# the census is derived                                                        #
# --------------------------------------------------------------------------- #
def test_status_comes_from_reachability_not_from_a_human(repo, reports):
    doc = built(repo, reports)
    got = statuses(doc)
    assert got["pkg/wired.py"] == "wired"
    assert got["pkg/clionly.py"] == "wired", (
        "reached only through the console script -- the case a naive "
        "'nothing imports it' rule gets wrong")
    assert got["pkg/lonely.py"] == "island"
    assert "tests/test_main.py" not in got, "a test is not a feature"


def test_every_count_matches_the_list_beside_it(repo, reports):
    """The 136-vs-827 failure in miniature: a headline number that no longer
    matches the list under it. Break by hard-coding any ``counts`` entry in
    ``inventory.build``."""
    doc = built(repo, reports)
    counts = doc["counts"]
    assert counts["modules"] == len(features(doc))
    assert counts["islands"] == len(doc["islands"])
    assert counts["shims"] == len(doc["shims"])
    assert counts["unknown"] == len(doc["unknown"])
    assert counts["stale"] == len(doc["stale"])
    assert counts["env_vars"] == len(doc["env_vars"])
    assert counts["api_endpoints"] == len(doc["api_endpoints"])
    assert counts["cli_commands"] == len(doc["cli_commands"])
    by_status = {}
    for feat in features(doc):
        by_status[feat["status"]] = by_status.get(feat["status"], 0) + 1
    for status, n in by_status.items():
        assert counts[f"status_{status}"] == n


def test_the_prose_lists_cannot_disagree_with_the_structured_entries(repo, reports):
    """The hand-written file carried 8 prose islands beside 7 structured
    island features, and the picker had to emit a note about the discrepancy.
    Deriving both from one pass makes the discrepancy unrepresentable."""
    doc = built(repo, reports)
    structured = sorted(f["module"] for f in features(doc)
                        if f["status"] == "island")
    assert sorted(doc["islands"]) == structured
    assert sorted(doc["shims"]) == sorted(
        f["module"] for f in features(doc) if f["status"] == "shim")


def test_unreached_is_the_count_a_deleted_test_cannot_lower(repo, reports):
    """The island metric is gameable: 'island' means unreachable BUT imported
    by a test, so deleting the test moves the module to ``unknown`` and the
    island count goes DOWN while the dead code stays. ``unreached`` is the
    union, and it does not move."""
    doc = built(repo, reports)
    assert statuses(doc)["pkg/lonely.py"] == "island"
    before = set(doc["unreached"])
    island_count_before = doc["counts"]["islands"]

    # The measured escape route: drop the test, and let a string literal in a
    # reached module name the module instead. reach stops calling it an island
    # and calls it ``unknown`` -- a dynamic dispatch MIGHT reach it -- and the
    # island count falls while the dead code sits exactly where it was.
    (repo / "tests" / "test_main.py").write_text("from pkg import wired\n",
                                                 encoding="utf-8")
    (repo / "pkg" / "wired.py").write_text(
        'from pkg import deep\nVALUE = 1\nMAYBE = "pkg.lonely"\n',
        encoding="utf-8")
    after_doc = built(repo, render.analyse_once(repo))
    assert statuses(after_doc)["pkg/lonely.py"] == "unknown"
    assert after_doc["counts"]["islands"] < island_count_before, (
        "precondition: the escape route really does lower the island count")
    assert set(after_doc["unreached"]) == before, (
        "the union must not move -- the module never became reachable")


def test_two_builds_over_one_tree_are_byte_identical(repo, reports):
    """No clock, no set iteration, no absolute path outside the root. A diff of
    this file must mean the architecture moved, not that the generator ran."""
    first = inventory.inventory_bytes(built(repo, reports))
    second = inventory.inventory_bytes(built(repo, render.analyse_once(repo)))
    assert first == second
    assert first.endswith("\n")
    assert "\r" not in first


# --------------------------------------------------------------------------- #
# the product configuration                                                    #
# --------------------------------------------------------------------------- #
def test_the_generator_analyses_the_way_the_product_does(repo, monkeypatch):
    """CONFIGURATION GUARD. ``reach.analyse(root)`` with no index and
    ``reach.analyse(root, index=...)`` are two engines; the shipped path uses
    the second. A guard that exercised the first is how a CRITICAL survived
    underneath a green test, so this asserts the generator reaches reach
    through ``render.analyse_once`` with an index in hand.

    Break by changing ``inventory.build`` to call ``reach.analyse(root)``.
    """
    seen = {}
    real = reach.analyse

    def spy(repo_root, index=None):
        seen["index"] = index
        return real(repo_root, index=index)

    monkeypatch.setattr(reach, "analyse", spy)
    inventory.build(repo, probe_dirty=False)
    assert "index" in seen, "reach.analyse was never called"
    assert seen["index"] is not None, (
        "the generator analysed WITHOUT a structural index -- a configuration "
        "the product never uses")


# --------------------------------------------------------------------------- #
# the merge: what the digest covers, and what it must not                      #
# --------------------------------------------------------------------------- #
def test_editing_a_derived_field_breaks_the_digest(repo, reports):
    """The whole point. Pre-seeding a status is not a way to steer the work
    queue. Break by removing ``areas`` from the digest projection in
    ``inventory._strip_human``."""
    doc = built(repo, reports)
    assert inventory.digest_ok(doc)
    for feat in features(doc):
        if feat["module"] == "pkg/lonely.py":
            feat["status"] = "wired"
    assert not inventory.digest_ok(doc)


def test_editing_a_derived_list_breaks_the_digest(repo, reports):
    doc = built(repo, reports)
    doc["islands"] = []
    assert not inventory.digest_ok(doc)


def test_editing_a_human_field_does_not_break_the_digest(repo, reports):
    """The other half, and it is load-bearing in the opposite direction: if a
    note invalidated the digest, writing down WHY would look like tampering and
    people would stop writing it down. Break by deleting the
    ``FEATURE_HUMAN_FIELDS`` / ``ENV_HUMAN_FIELDS`` stripping in
    ``inventory._strip_human``."""
    doc = built(repo, reports)
    for feat in features(doc):
        feat["notes"] = "a human explaining themselves"
        feat["name"] = "Renamed by a human"
        feat["kind"] = "safety"
    for row in doc["env_vars"]:
        row["purpose"] = "a human explaining themselves"
    for area in doc["areas"]:
        area["title"] = "A human's area name"
    doc["annotations"]["module:pkg/deep.py"] = {"notes": "added by hand"}
    doc["narrative_features"].append({"name": "a planned thing", "notes": "why"})
    assert inventory.digest_ok(doc), (
        "writing a note must not read as tampering")


def test_repo_state_head_is_covered_by_the_digest(repo, reports):
    """A freshness stamp anybody can rewrite is decorative."""
    doc = built(repo, reports)
    doc["repo_state"]["head"] = "0" * 40
    assert not inventory.digest_ok(doc)


def test_repo_state_dirty_is_not_covered(repo, reports):
    """Dirtiness moves without the architecture moving, and rewriting it fakes
    nothing -- only ``head`` can fake freshness."""
    doc = built(repo, reports)
    doc["repo_state"]["dirty"] = not doc["repo_state"]["dirty"]
    assert inventory.digest_ok(doc)


# --------------------------------------------------------------------------- #
# annotations may explain; they may not legislate                              #
# --------------------------------------------------------------------------- #
def test_an_annotation_cannot_set_a_status(repo, reports):
    """The defect being fixed is a hand-written file steering the work queue.
    Handing that power back through an annotation would be the same defect in a
    generated file's clothes. Break by merging the raw annotation dict into the
    feature in ``inventory._feature``."""
    doc = built(repo, reports, annotations={
        "module:pkg/wired.py": {"status": "island", "notes": "I want work"}})
    assert statuses(doc)["pkg/wired.py"] == "wired"
    feat = next(f for f in features(doc) if f["module"] == "pkg/wired.py")
    assert feat["notes"] == "I want work", "the note itself must survive"


def test_annotation_overreach_is_reported_not_swallowed(repo, reports):
    """Silently dropping a field is how somebody concludes it works."""
    bad = inventory.annotation_overreach({
        "module:pkg/wired.py": {"status": "island", "tests": ["x"], "notes": "ok"},
        "env:X": {"purpose": "fine"},
    })
    assert len(bad) == 1
    assert "status" in bad[0] and "tests" in bad[0]
    assert "purpose" not in bad[0]


def test_a_narrative_feature_can_never_be_ranked(repo, reports):
    """The picker reads ``areas[].features[]``. A hand-written entry for a
    thing that does not exist yet lives outside that, verbatim, so it can be
    read but not queued."""
    doc = built(repo, reports, narrative_features=[
        {"name": "Mission Spine", "status": "island", "notes": "planned only"}])
    assert doc["narrative_features"][0]["name"] == "Mission Spine"
    assert all(f.get("name") != "Mission Spine" for f in features(doc))


# --------------------------------------------------------------------------- #
# the harvest loses nothing                                                    #
# --------------------------------------------------------------------------- #
OLD_HANDWRITTEN = {
    "schema": "daedalus-feature-inventory/1",
    "repo_state": {"branch": "b", "head": "f40529c", "dirty": True},
    "areas": [
        {"area": "Core", "path": "pkg/", "features": [
            {"name": "The lonely capability", "kind": "module",
             "status": "island", "entrypoints": ["pkg/lonely.py"],
             "tests": [], "notes": "built and tested, nothing calls it yet"},
            {"name": "Compat shims", "kind": "module", "status": "shim",
             "entrypoints": ["pkg/deep.py", "pkg/wired.py"], "tests": [],
             "notes": "keep until callers migrate"},
        ]},
        {"area": "Web UI", "path": "apps/web/", "features": [
            {"name": "Glass component kit", "kind": "ui", "status": "wired",
             "entrypoints": ["apps/web/src/components/glass/"], "tests": [],
             "notes": "GlassPanel/Card/Sheet, ChatBubble, Composer"},
        ]},
        {"area": "Planned", "path": "docs/", "features": [
            {"name": "Mission Spine", "kind": "doc-spec", "status": "planned",
             "entrypoints": ["docs/HANDOFF.md 4B"], "tests": [],
             "notes": "durable state machine; not built"},
        ]},
    ],
    "env_vars": [{"name": "PKG_DEBUG", "read_in": "pkg/cli.py",
                  "purpose": "verbose output"}],
}


def _all_notes(obj, out=None):
    out = [] if out is None else out
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in ("notes", "purpose") and isinstance(value, str) and value:
                out.append(value)
            else:
                _all_notes(value, out)
    elif isinstance(obj, list):
        for item in obj:
            _all_notes(item, out)
    return out


def test_the_harvest_places_every_hand_written_feature(repo, reports):
    """Count conservation. Break by returning early from the ``areas`` loop in
    ``inventory.harvest``."""
    modules = [m.module for m in reports[0].modules]
    annotations, narrative, stats = inventory.harvest(
        OLD_HANDWRITTEN, modules, ["PKG_DEBUG"])
    assert stats["old_features"] == 4
    assert stats["matched"] + stats["narrative"] == 4
    assert stats["matched"] == 2, "two features name modules that exist"
    assert stats["narrative"] == 2, "the UI and the planned entry name none"


def test_no_hand_written_rationale_is_lost(repo, reports):
    """A generated file that discards the reasons somebody wrote is not
    progress -- it is the same rot with a fresher timestamp."""
    modules = [m.module for m in reports[0].modules]
    annotations, narrative, _ = inventory.harvest(
        OLD_HANDWRITTEN, modules, ["PKG_DEBUG"])
    doc = built(repo, reports, annotations=annotations,
                narrative_features=narrative)
    survived = "\n".join(_all_notes(doc))
    for note in _all_notes(OLD_HANDWRITTEN):
        assert note in survived, f"lost: {note!r}"


def test_one_feature_naming_several_modules_annotates_all_of_them(repo, reports):
    """The kairos-rename shim entry named five modules in one feature. Keeping
    only the first would lose the reason for the other four."""
    modules = [m.module for m in reports[0].modules]
    annotations, _, _ = inventory.harvest(OLD_HANDWRITTEN, modules)
    assert annotations["module:pkg/deep.py"]["notes"] == "keep until callers migrate"
    assert annotations["module:pkg/wired.py"]["notes"] == "keep until callers migrate"


def test_a_second_harvest_is_idempotent(repo, reports):
    """A schema-2 document passes its human half straight through; re-running
    the generator must not re-shred it."""
    modules = [m.module for m in reports[0].modules]
    annotations, narrative, _ = inventory.harvest(OLD_HANDWRITTEN, modules,
                                                  ["PKG_DEBUG"])
    doc = built(repo, reports, annotations=annotations,
                narrative_features=narrative)
    again_ann, again_narr, _ = inventory.harvest(doc, modules, ["PKG_DEBUG"])
    assert again_ann == doc["annotations"]
    assert again_narr == narrative


def test_a_harvested_note_reaches_the_generated_feature(repo, reports):
    modules = [m.module for m in reports[0].modules]
    annotations, narrative, _ = inventory.harvest(OLD_HANDWRITTEN, modules)
    doc = built(repo, reports, annotations=annotations,
                narrative_features=narrative)
    feat = next(f for f in features(doc) if f["module"] == "pkg/lonely.py")
    assert feat["name"] == "The lonely capability"
    assert feat["notes"] == "built and tested, nothing calls it yet"
    assert feat["status"] == "island", "still derived, not inherited"


# --------------------------------------------------------------------------- #
# mechanically-detected staleness                                              #
# --------------------------------------------------------------------------- #
def test_a_promised_package_that_is_not_on_disk_is_stale(repo, reports):
    """Exactly the ``daedalus.metron`` defect the hand-written file recorded: a
    non-editable install would ship a package that is not there. Break by
    dropping the ghost loop in ``inventory._stale_features``."""
    (repo / "pyproject.toml").write_text(
        BASE["pyproject.toml"].replace('"pkg.sub",', '"pkg.sub",\n    "pkg.gone",'),
        encoding="utf-8")
    doc = built(repo, reports)
    stale = [f for f in features(doc) if f["status"] == "stale"]
    assert [f["detector"] for f in stale] == ["packaging_ghost"]
    assert "pkg.gone" in stale[0]["reason"]
    assert doc["packaging"]["listed_but_absent"] == ["pkg.gone"]


def test_bytecode_whose_sources_are_gone_is_stale(repo, reports):
    """The ``daedalus/hermes/__pycache__`` shape: package deleted, ``.pyc``
    left behind, dotted name still importable."""
    cache = repo / "pkg" / "ghost" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "mod.cpython-311.pyc").write_bytes(b"\x00")
    doc = built(repo, reports)
    stale = [f for f in features(doc) if f["status"] == "stale"]
    assert [f["detector"] for f in stale] == ["orphan_bytecode"]
    assert "pkg/ghost/__pycache__" in stale[0]["reason"]


def test_bytecode_beside_live_sources_is_not_stale(repo, reports):
    """A cache next to real code is a cache, not a finding. Break by dropping
    the sibling-sources check."""
    cache = repo / "pkg" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "wired.cpython-311.pyc").write_bytes(b"\x00")
    doc = built(repo, reports)
    assert [f for f in features(doc) if f["status"] == "stale"] == []


def test_a_package_missing_from_the_wheel_is_reported_but_not_queued(repo, reports):
    """Its remedy is 'add it to the list' -- the OPPOSITE verb from the stale
    remedy ('remove it'). Filing it as stale would hand a fixer the wrong verb,
    which is how a finding becomes damage."""
    (repo / "pkg" / "extra").mkdir()
    (repo / "pkg" / "extra" / "__init__.py").write_text("", encoding="utf-8")
    doc = built(repo, reports)
    assert doc["packaging"]["on_disk_but_unlisted"] == ["pkg.extra"]
    assert [f for f in features(doc) if f["status"] == "stale"] == []


# --------------------------------------------------------------------------- #
# the gate                                                                     #
# --------------------------------------------------------------------------- #
def test_check_fails_when_nothing_generated_the_file(repo, reports):
    report = inventory.check(repo, repo / "docs" / "nope.json", reports=reports,
                             probe_dirty=False)
    assert not report["ok"]
    assert "no inventory" in report["problems"][0]


def test_check_fails_on_a_file_that_is_not_json(repo, reports):
    path = repo / "docs" / "inv.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    report = inventory.check(repo, path, reports=reports, probe_dirty=False)
    assert not report["ok"]
    assert "could not be parsed" in report["problems"][0]


def test_check_fails_on_the_previous_schema(repo, reports):
    path = repo / "docs" / "inv.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(OLD_HANDWRITTEN), encoding="utf-8")
    report = inventory.check(repo, path, reports=reports, probe_dirty=False)
    assert not report["ok"]
    assert "schema" in report["problems"][0]


def test_check_is_clean_immediately_after_a_refresh(repo):
    fake_git(repo)
    path = repo / "docs" / "inv.json"
    inventory.refresh(repo, path, probe_dirty=False)
    report = inventory.check(repo, path, probe_dirty=False)
    assert report["ok"], report["problems"]


def test_check_catches_a_hand_edited_status(repo, reports):
    path = repo / "docs" / "inv.json"
    inventory.refresh(repo, path, reports=reports, probe_dirty=False)
    doc = json.loads(path.read_text(encoding="utf-8"))
    for feat in features(doc):
        if feat["module"] == "pkg/lonely.py":
            feat["status"] = "wired"
    doc["islands"] = []
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    report = inventory.check(repo, path, reports=reports, probe_dirty=False)
    assert not report["ok"]
    assert any("hand-edited" in p for p in report["problems"])


def test_check_catches_a_tree_that_moved_under_the_file(repo, reports):
    path = repo / "docs" / "inv.json"
    inventory.refresh(repo, path, reports=reports, probe_dirty=False)
    (repo / "pkg" / "newisland.py").write_text("Y = 1\n", encoding="utf-8")
    report = inventory.check(repo, path, probe_dirty=False)
    assert not report["ok"]
    assert any("pkg/newisland.py" in p for p in report["problems"])


def test_a_linked_worktree_records_the_revision_from_the_common_dir(tmp_path):
    """agent_env_g0 IS a linked worktree: its ``.git`` is a file pointing at
    ``<main>/.git/worktrees/<name>``, which holds HEAD but not refs/heads --
    those live in the main repository named by ``commondir``. Every inventory
    regenerated there said ``head: unknown`` until the shared refs were read
    from the common dir (MEASURED 2026-08-23)."""
    main = tmp_path / "main"
    fake_git(main)                                   # refs/heads live HERE
    wt_gitdir = main / ".git" / "worktrees" / "g0"
    wt_gitdir.mkdir(parents=True)
    (wt_gitdir / "HEAD").write_text(f"ref: refs/heads/{FIXTURE_BRANCH}\n",
                                    encoding="utf-8")
    (wt_gitdir / "commondir").write_text("../.."+chr(10), encoding="utf-8")
    linked = tmp_path / "linked"
    linked.mkdir()
    (linked / ".git").write_text(f"gitdir: {wt_gitdir}\n", encoding="utf-8")

    path = linked / "docs" / "inv.json"
    inventory.refresh(linked, path, probe_dirty=False)
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["repo_state"]["head"] == FIXTURE_SHA
    assert doc["repo_state"]["branch"] == FIXTURE_BRANCH


def test_the_generated_file_records_the_revision_it_was_generated_against(repo):
    fake_git(repo)
    path = repo / "docs" / "inv.json"
    inventory.refresh(repo, path, probe_dirty=False)
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["repo_state"]["head"] == FIXTURE_SHA
    assert doc["repo_state"]["branch"] == FIXTURE_BRANCH


# --------------------------------------------------------------------------- #
# the consumer still works                                                     #
# --------------------------------------------------------------------------- #
def test_the_picker_can_still_read_the_generated_schema(repo):
    """The picker is another agent's file and was written against schema 1. A
    generated replacement that it cannot read is not a fix."""
    from daedalus.spine import picker

    fake_git(repo)
    path = repo / "docs" / "inv.json"
    result = inventory.refresh(repo, path, probe_dirty=False)
    doc = result["doc"]

    candidates, notes = picker.inventory_candidates(doc)
    assert candidates, "the picker read no work at all out of the new schema"
    assert {c.source for c in candidates} == {"inventory_island"}
    assert any("pkg/lonely.py" in c.instruction for c in candidates)
    assert notes == (), f"the prose/structured discrepancy note fired: {notes}"


def test_the_freshness_gate_opens_for_a_freshly_generated_file(repo):
    from daedalus.spine import picker

    fake_git(repo)
    path = repo / "docs" / "inv.json"
    doc = inventory.refresh(repo, path, probe_dirty=False)["doc"]
    verdict = picker.inventory_freshness(doc, repo)
    assert verdict["fresh"], verdict["reason"]


def test_the_freshness_gate_closes_when_head_moves(repo):
    from daedalus.spine import picker

    fake_git(repo)
    doc = inventory.refresh(repo, repo / "docs" / "inv.json",
                            probe_dirty=False)["doc"]
    fake_git(repo, sha="b" * 40)
    verdict = picker.inventory_freshness(doc, repo)
    assert not verdict["fresh"]


# --------------------------------------------------------------------------- #
# the SNAPSHOT must record what it scanned                                     #
# --------------------------------------------------------------------------- #
def test_the_snapshot_records_the_revision_it_scanned(repo, reports):
    """Integrity is not freshness. A snapshot generated thirty commits ago
    verifies its own digest perfectly -- and one was trusted while it asserted
    an island that the live tree does not have. Break by removing
    ``repo_state`` from ``drift.scan``'s state."""
    fake_git(repo)
    snap = repo / "docs" / "architecture-state.json"
    drift.refresh(repo, snap, reach_report=reports[0], switch_report=reports[1],
                  probe_dirty=False)
    doc = json.loads(snap.read_text(encoding="utf-8"))
    assert doc["repo_state"]["head"] == FIXTURE_SHA
    assert doc["repo_state"]["branch"] == FIXTURE_BRANCH
    assert drift.digest_ok(doc)


def test_the_recorded_revision_is_inside_the_snapshot_digest(repo, reports):
    """If it sat outside, anybody could rewrite the recorded head to make a
    stale snapshot look fresh and the gate would be decorative. Break by
    removing ``repo_state`` from ``drift._MECHANICAL_KEYS``."""
    fake_git(repo)
    snap = repo / "docs" / "architecture-state.json"
    drift.refresh(repo, snap, reach_report=reports[0], switch_report=reports[1],
                  probe_dirty=False)
    doc = json.loads(snap.read_text(encoding="utf-8"))
    doc["repo_state"]["head"] = "0" * 40
    assert not drift.digest_ok(doc)


def test_a_snapshot_with_no_recorded_head_is_not_fresh(repo):
    """FAIL CLOSED. A snapshot that cannot say what it scanned is not evidence
    about this tree. Break by returning ``{"fresh": True}`` for the absent case
    in ``drift.snapshot_freshness``."""
    verdict = drift.snapshot_freshness({"schema": 3}, repo)
    assert not verdict["fresh"]
    assert "records no repo_state.head" in verdict["reason"]


@pytest.mark.parametrize("bad", ["", "   ", "abc", "zzzzzzzzzz", "unknown", 7, None])
def test_a_malformed_recorded_head_is_not_fresh(repo, bad):
    """A one-character 'prefix' matches roughly one HEAD in sixteen. A check
    that passes by accident is worse than no check, because it is believed."""
    verdict = drift.snapshot_freshness({"repo_state": {"head": bad}}, repo)
    assert not verdict["fresh"]


def test_a_snapshot_whose_revision_moved_is_not_fresh(repo, reports):
    fake_git(repo)
    snap = repo / "docs" / "architecture-state.json"
    drift.refresh(repo, snap, reach_report=reports[0], switch_report=reports[1],
                  probe_dirty=False)
    doc = json.loads(snap.read_text(encoding="utf-8"))
    fake_git(repo, sha="c" * 40)
    verdict = drift.snapshot_freshness(doc, repo)
    assert not verdict["fresh"]
    assert "HEAD is" in verdict["reason"]


def test_freshness_fails_open_when_git_cannot_answer(tmp_path):
    """A tarball checkout with no ``.git`` is not evidence of staleness, and
    turning 'I cannot tell' into 'refuse everything' is the worse failure. Same
    rule as ``picker.inventory_freshness``."""
    verdict = drift.snapshot_freshness({"repo_state": {"head": "a" * 40}},
                                       tmp_path)
    assert verdict["fresh"]
    assert "failing open" in verdict["reason"]


def test_two_generations_with_no_source_change_leave_the_gate_quiet(repo, reports):
    """THE SELF-REFERENCE TRAP. ``head``, ``branch`` and ``dirty`` are written
    by the generator into the artifact the generator then gates on. If a no-op
    regeneration tripped the gate, the gate would be noise and people would
    start ignoring it."""
    fake_git(repo)
    snap = repo / "docs" / "architecture-state.json"
    first = drift.refresh(repo, snap, reach_report=reports[0],
                          switch_report=reports[1], probe_dirty=False)
    second = drift.refresh(repo, snap, reach_report=reports[0],
                           switch_report=reports[1], probe_dirty=False)
    assert first == second, "a no-op regeneration rewrote the file"

    report = drift.check(repo, snap, reach_report=reports[0],
                         switch_report=reports[1], probe_dirty=False)
    assert report.ok
    assert report.blocking == []
    assert report.freshness["fresh"], report.freshness["reason"]


def test_two_inventory_generations_with_no_source_change_are_identical(repo):
    fake_git(repo)
    path = repo / "docs" / "inv.json"
    inventory.refresh(repo, path, probe_dirty=False)
    first = path.read_text(encoding="utf-8")
    inventory.refresh(repo, path, probe_dirty=False)
    assert path.read_text(encoding="utf-8") == first


# --------------------------------------------------------------------------- #
# the artifacts committed in THIS repo                                         #
# --------------------------------------------------------------------------- #
def test_the_committed_inventory_is_generated_not_typed():
    doc = json.loads((ROOT / inventory.INVENTORY_REL).read_text(encoding="utf-8"))
    assert doc["schema"] == inventory.SCHEMA
    assert "GENERATED by daedalus.mapping.inventory" in doc["note"]
    assert inventory.digest_ok(doc), (
        "the committed inventory's derived half does not match its own digest")


def test_the_committed_inventory_records_a_usable_revision():
    """It may be a commit or two behind -- twelve agents write to this tree at
    once -- but it must always be able to SAY which tree it described. The
    stronger claim (that it matches HEAD right now) is the consumer's gate to
    make, not a property of the file on disk at test time."""
    doc = json.loads((ROOT / inventory.INVENTORY_REL).read_text(encoding="utf-8"))
    head = doc["repo_state"]["head"]
    assert isinstance(head, str) and re.fullmatch(r"[0-9a-f]{7,64}", head), head


def test_the_committed_snapshot_records_a_usable_revision():
    doc = json.loads((ROOT / drift.SNAPSHOT_REL).read_text(encoding="utf-8"))
    head = (doc.get("repo_state") or {}).get("head")
    assert isinstance(head, str) and re.fullmatch(r"[0-9a-f]{7,64}", head), (
        "the generated snapshot cannot say which tree it scanned")
    assert drift.digest_ok(doc)


def test_the_committed_inventory_kept_the_hand_written_rationale():
    """Migration guard. The hand-written file carried 136 reasons; a generated
    replacement that dropped them would be a regression wearing a fresher
    timestamp."""
    doc = json.loads((ROOT / inventory.INVENTORY_REL).read_text(encoding="utf-8"))
    kept = len(doc["annotations"]) + len(doc["narrative_features"])
    assert kept >= 130, f"only {kept} hand-written entries survived"
    assert doc["unmatched_annotations"] == []
