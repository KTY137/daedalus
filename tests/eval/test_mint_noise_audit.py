"""The second promotion witness: the named threats, checked instead of waited out.

``MINT_CONFIRM_THRESHOLD``'s comment justifies itself by naming three ways a
single mint could be noise, and predicts the threshold stays "low enough to
actually accumulate ... instead of never firing". Measured 2026-09-10: zero
confirmations across 400 first-parent commits and all 48 stored tasks. The gate
never opens, so it never validates anything either.

THE SHAPE OF THESE FIXTURES IS ITSELF A LESSON. Every commit here touches an
ANCHOR and a separate LABEL SOURCE, because that is what mint produces: labels
never come from the anchor (``_mint_from_diffs``: "never the anchor's own";
``_mint_from_text_diffs``: ``cross_file -= with_labels[anchor]``). The first
version of this file used one file as both, which encoded the same
misconception the audit itself had -- and is why these tests stayed green while
the audit inspected the one file in the commit that supplied no labels at all.
"""
from __future__ import annotations

import subprocess

import pytest

from daedalus.eval import mint


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True,
                   capture_output=True)


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    return root


def _commit(root, files, msg="c"):
    """Commit a mapping of {relative path: text} and return the new SHA."""
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", msg)
    out = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


# --------------------------------------------------------------------------- #
# T1 -- the reformat-only touch                                                #
# --------------------------------------------------------------------------- #

def test_t1_fires_when_only_the_docstring_moved(repo):
    """The exact threat the comment names. Same code, different docstring: the
    bytes changed and the structure did not, so a label from it is noise."""
    _commit(repo, {"anchor.py": "a = 1\n",
                   "src.py": 'def f():\n    """old words"""\n    return 1\n'})
    sha = _commit(repo, {"anchor.py": "a = 2\n",
                         "src.py": 'def f():\n    """other words"""\n    return 1\n'})
    task = {"minted_at_sha": sha, "target": "anchor.py", "must_include": ["f"]}
    audit = mint.audit_noise_threats(task, repo)
    assert audit["t1_cosmetic"] == "fired", audit
    assert audit["verdict"] == "fired"
    assert mint.promotion_witness({**task, "noise_audit": audit}) is None


def test_t1_is_clean_when_the_structure_really_changed(repo):
    _commit(repo, {"anchor.py": "a = 1\n", "src.py": "def f():\n    return 1\n"})
    sha = _commit(repo, {"anchor.py": "a = 2\n", "src.py": "def f():\n    return 2\n"})
    task = {"minted_at_sha": sha, "target": "anchor.py", "must_include": ["f"]}
    audit = mint.audit_noise_threats(task, repo)
    assert audit["t1_cosmetic"] == "clean", audit
    assert audit["verdict"] == "clean"
    assert mint.promotion_witness({**task, "noise_audit": audit}) == "noise_audit"


def test_a_genuinely_new_label_source_is_impossible_not_unknown(repo):
    """A label source added by the commit has no prior version to reformat or
    rename within -- provided it is not a COPY, which the next test covers."""
    _commit(repo, {"anchor.py": "a = 1\n"})
    sha = _commit(repo, {"anchor.py": "a = 2\n",
                         "new.py": "def g():\n    return 1\n"})
    task = {"minted_at_sha": sha, "target": "anchor.py", "must_include": ["g"]}
    audit = mint.audit_noise_threats(task, repo)
    assert audit["t1_cosmetic"] == "impossible"
    assert audit["t2_rename_roundtrip"] == "impossible"
    assert audit["verdict"] == "clean"


# --------------------------------------------------------------------------- #
# T2 -- the rename, and the COPY that git calls an add                         #
# --------------------------------------------------------------------------- #

def test_t2_fires_when_a_label_source_is_a_byte_identical_copy(repo):
    """THE DEFECT THAT REVERTED A 35-TASK PROMOTION.

    Git reports a byte-identical copy of an existing file as an ADD unless copy
    detection is on. The first audit concluded from "added" that nothing
    existed to rename -- while the file sat in the parent tree under another
    name. One promoted task was a pure packaging move whose label sources were
    56/57 ``C100``; it received the strongest verdict in the vocabulary.
    """
    _commit(repo, {"anchor.py": "a = 1\n",
                   "old/thing.py": "def carried():\n    return 41 + 1\n"})
    body = (repo / "old" / "thing.py").read_text(encoding="utf-8")
    sha = _commit(repo, {"anchor.py": "a = 2\n", "new/thing.py": body})
    task = {"minted_at_sha": sha, "target": "anchor.py",
            "must_include": ["carried"]}
    audit = mint.audit_noise_threats(task, repo)
    assert audit["t2_rename_roundtrip"] == "fired", audit
    assert audit["verdict"] == "fired"
    assert mint.promotion_witness({**task, "noise_audit": audit}) is None


def test_t2_fires_when_a_label_is_an_old_symbol_renamed(repo):
    """The symbol-granularity case: new name, byte-identical body."""
    _commit(repo, {"anchor.py": "a = 1\n",
                   "src.py": "def old_name():\n    return 41 + 1\n"})
    sha = _commit(repo, {"anchor.py": "a = 2\n",
                         "src.py": "def new_name():\n    return 41 + 1\n"})
    task = {"minted_at_sha": sha, "target": "anchor.py",
            "must_include": ["new_name"]}
    audit = mint.audit_noise_threats(task, repo)
    assert audit["t2_rename_roundtrip"] == "fired", audit
    assert audit["verdict"] == "fired"


def test_t2_is_clean_for_a_genuinely_new_symbol(repo):
    _commit(repo, {"anchor.py": "a = 1\n",
                   "src.py": "def old_name():\n    return 41 + 1\n"})
    sha = _commit(repo, {"anchor.py": "a = 2\n",
                         "src.py": "def old_name():\n    return 41 + 1\n\n\n"
                                   "def fresh():\n    return 'x'\n"})
    task = {"minted_at_sha": sha, "target": "anchor.py", "must_include": ["fresh"]}
    audit = mint.audit_noise_threats(task, repo)
    assert audit["t2_rename_roundtrip"] == "clean", audit


# --------------------------------------------------------------------------- #
# T3 -- the generated-file regen                                               #
# --------------------------------------------------------------------------- #

def test_t3_fires_on_a_generated_anchor_without_touching_git():
    for rel in ("dist/app.min.js", "build/out.py", "src/thing_pb2.py",
                "runs/x/report.py", "uv.lock"):
        audit = mint.audit_noise_threats(
            {"minted_at_sha": "0" * 40, "target": rel, "must_include": ["a"]},
            ".")
        assert audit["t3_generated"] == "fired", rel
        assert audit["verdict"] == "fired"


def test_t3_fires_when_only_the_LABEL_SOURCE_is_generated(repo):
    """A hand-written anchor with labels harvested out of ``dist/`` is a
    generated-file regen wearing a clean path. Checking the anchor alone missed
    it entirely."""
    _commit(repo, {"anchor.py": "a = 1\n"})
    sha = _commit(repo, {"anchor.py": "a = 2\n",
                         "dist/bundle.py": "def generated_thing():\n    return 1\n"})
    task = {"minted_at_sha": sha, "target": "anchor.py",
            "must_include": ["generated_thing"]}
    audit = mint.audit_noise_threats(task, repo)
    assert audit["t3_generated"] == "fired", audit
    assert audit["verdict"] == "fired"


# --------------------------------------------------------------------------- #
# aggregation across several label sources                                     #
# --------------------------------------------------------------------------- #

def test_one_dirty_source_among_clean_ones_decides(repo):
    """A threat seen ANYWHERE among the label sources decides the task. The
    other aggregation -- letting a clean file vouch for its neighbours -- would
    let one honest source certify a commit's worth of unchecked ones."""
    _commit(repo, {"anchor.py": "a = 1\n",
                   "good.py": "def g():\n    return 1\n",
                   "bad.py": 'def b():\n    """x"""\n    return 2\n'})
    sha = _commit(repo, {"anchor.py": "a = 2\n",
                         "good.py": "def g():\n    return 99\n",
                         "bad.py": 'def b():\n    """y"""\n    return 2\n'})
    task = {"minted_at_sha": sha, "target": "anchor.py", "must_include": ["g"]}
    audit = mint.audit_noise_threats(task, repo)
    assert audit["t1_cosmetic"] == "fired", audit
    assert audit["verdict"] == "fired"


def test_an_undecidable_source_outranks_a_clean_one(repo):
    """Absence of a check is not absence of a threat."""
    _commit(repo, {"anchor.py": "a = 1\n",
                   "good.py": "def g():\n    return 1\n",
                   "notes.md": "# h\n\nbody\n"})
    sha = _commit(repo, {"anchor.py": "a = 2\n",
                         "good.py": "def g():\n    return 99\n",
                         "notes.md": "# h\n\nbody changed\n"})
    task = {"minted_at_sha": sha, "target": "anchor.py", "must_include": ["g"]}
    audit = mint.audit_noise_threats(task, repo)
    assert audit["t1_cosmetic"] == "undecided", audit
    assert audit["verdict"] == "undecided"
    assert mint.promotion_witness({**task, "noise_audit": audit}) is None


# --------------------------------------------------------------------------- #
# the refusals -- what must NOT be treated as evidence                         #
# --------------------------------------------------------------------------- #

def test_undecided_is_never_promoted(repo):
    """Markdown and JSON have no normalizer here. This is the single most
    tempting place to blur "unchecked" into "clean": 11 stored tasks would
    become promotable by one wrong default."""
    _commit(repo, {"anchor.md": "# Anchor\n", "d.md": "# A\n\ntext\n"})
    sha = _commit(repo, {"anchor.md": "# Anchor 2\n", "d.md": "# A\n\nchanged\n"})
    task = {"minted_at_sha": sha, "target": "anchor.md", "must_include": ["A"]}
    audit = mint.audit_noise_threats(task, repo)
    assert audit["t1_cosmetic"] == "undecided"
    assert audit["verdict"] == "undecided"
    assert mint.promotion_witness({**task, "noise_audit": audit}) is None


def test_a_target_absent_at_its_own_mint_sha_is_unverifiable(repo):
    """Two stored tasks are exactly this. Their labels may be fine; what is
    missing is the ability to CHECK, and that must be visible rather than
    indistinguishable from a passing audit."""
    sha = _commit(repo, {"m.py": "def f():\n    return 1\n"})
    task = {"minted_at_sha": sha, "target": "never_existed.py",
            "must_include": ["f"]}
    audit = mint.audit_noise_threats(task, repo)
    assert audit["verdict"] == "unverifiable_provenance"
    assert mint.promotion_witness({**task, "noise_audit": audit}) is None


def test_a_commit_with_no_other_touched_file_is_undecided(repo):
    """Mint cannot take a label from the anchor, so a single-file commit has no
    label source at all. Auditing it as clean would certify a task that could
    not have been minted the way its provenance says it was."""
    _commit(repo, {"solo.py": "def f():\n    return 1\n"})
    sha = _commit(repo, {"solo.py": "def f():\n    return 2\n"})
    task = {"minted_at_sha": sha, "target": "solo.py", "must_include": ["f"]}
    audit = mint.audit_noise_threats(task, repo)
    assert audit["verdict"] == "undecided", audit
    assert mint.promotion_witness({**task, "noise_audit": audit}) is None


def test_a_stale_audit_version_does_not_promote():
    """An audit produced under different rules is not evidence about today's.
    Without this, bumping NOISE_AUDIT_VERSION would silently keep honouring
    every audit it was bumped to invalidate."""
    task = {"confirmations": 0, "noise_audit": {
        "version": mint.NOISE_AUDIT_VERSION - 1, "verdict": "clean"}}
    assert mint.promotion_witness(task) is None


def test_an_audit_without_a_version_does_not_promote():
    task = {"confirmations": 0, "noise_audit": {"verdict": "clean"}}
    assert mint.promotion_witness(task) is None


# --------------------------------------------------------------------------- #
# the two witnesses stay distinguishable                                       #
# --------------------------------------------------------------------------- #

def test_recurrence_still_works_and_is_named_as_itself():
    task = {"confirmations": mint.MINT_CONFIRM_THRESHOLD}
    assert mint.promotion_witness(task) == "recurrence"


def test_recurrence_wins_when_both_apply():
    """Deterministic precedence, so a task's recorded witness cannot depend on
    evaluation order."""
    task = {"confirmations": mint.MINT_CONFIRM_THRESHOLD,
            "noise_audit": {"version": mint.NOISE_AUDIT_VERSION,
                            "verdict": "clean"}}
    assert mint.promotion_witness(task) == "recurrence"


def test_no_witness_is_the_default():
    assert mint.promotion_witness({}) is None
    assert mint.promotion_witness({"confirmations": 2}) is None


def test_a_fired_t3_outranks_undecided_through_the_MAIN_aggregation(repo):
    """The surviving mutant from the 2026-09-10 adversarial pass.

    The commit that added the T3-precedence fix pinned it only in the
    early-return branch. A mutation that inverted the SAME ordering in the main
    aggregation survived all 13 tests. Bounded severity -- neither `fired` nor
    `undecided` promotes, so nothing could leak into primary -- but it would
    record a KNOWN generated artifact as an unknown, which is exactly the
    distinction this module says decides the corpus.

    Reaches the main path: real sources exist, T1/T2 are undecided (Markdown),
    and T3 fires from a label source under ``dist/``.
    """
    # The label source must be MODIFIED, not added: an added file makes T1
    # "impossible" (nothing existed to reformat), which is correct and would
    # not exercise the undecided-vs-fired ordering this test exists for.
    _commit(repo, {"anchor.py": "a = 1\n",
                   "dist/notes.md": "# Generated\n\nbody\n"})
    sha = _commit(repo, {"anchor.py": "a = 2\n",
                         "dist/notes.md": "# Generated\n\nbody changed\n"})
    task = {"minted_at_sha": sha, "target": "anchor.py",
            "must_include": ["Generated"]}
    audit = mint.audit_noise_threats(task, repo)
    assert audit["t1_cosmetic"] == "undecided", audit
    assert audit["t3_generated"] == "fired", audit
    assert audit["verdict"] == "fired", (
        "an undecidable T1 outranked a FIRED T3: a known threat was recorded "
        "as an unknown one")
