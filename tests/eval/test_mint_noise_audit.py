"""The second promotion witness: the named threats, checked instead of waited out.

``MINT_CONFIRM_THRESHOLD``'s comment justifies itself by naming three ways a
single mint could be noise, and predicts the threshold stays "low enough to
actually accumulate ... instead of never firing". Measured 2026-09-10: zero
confirmations across 400 first-parent commits and all 48 stored tasks. The gate
never opens, so it never validates anything either.

These tests pin the direct check that replaces the proxy, and -- more
importantly -- pin the places it must REFUSE to help.
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


def _commit(root, rel, text, msg="c"):
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
    before = 'def f():\n    """old words"""\n    return 1\n'
    after = 'def f():\n    """entirely different words"""\n    return 1\n'
    _commit(repo, "m.py", before)
    sha = _commit(repo, "m.py", after)
    task = {"minted_at_sha": sha, "target": "m.py", "must_include": ["f"]}
    audit = mint.audit_noise_threats(task, repo)
    assert audit["t1_cosmetic"] == "fired", audit
    assert audit["verdict"] == "fired"
    assert mint.promotion_witness({**task, "noise_audit": audit}) is None


def test_t1_is_clean_when_the_structure_really_changed(repo):
    _commit(repo, "m.py", "def f():\n    return 1\n")
    sha = _commit(repo, "m.py", "def f():\n    return 2\n")
    task = {"minted_at_sha": sha, "target": "m.py", "must_include": ["f"]}
    audit = mint.audit_noise_threats(task, repo)
    assert audit["t1_cosmetic"] == "clean", audit
    assert audit["verdict"] == "clean"
    assert mint.promotion_witness({**task, "noise_audit": audit}) == "noise_audit"


def test_a_newly_added_file_makes_t1_and_t2_impossible_not_unknown(repo):
    """32 of the 48 stored tasks land here, so the distinction decides the
    corpus. You cannot reformat, or rename within, a file that did not exist:
    the threats are ruled out BY CONSTRUCTION, which is stronger evidence than
    an inspection that happened to find nothing.
    """
    _commit(repo, "other.py", "x = 1\n")
    sha = _commit(repo, "new.py", "def g():\n    return 1\n")
    task = {"minted_at_sha": sha, "target": "new.py", "must_include": ["g"]}
    audit = mint.audit_noise_threats(task, repo)
    assert audit["t1_cosmetic"] == "impossible"
    assert audit["t2_rename_roundtrip"] == "impossible"
    assert audit["verdict"] == "clean"


# --------------------------------------------------------------------------- #
# T2 -- the rename that round-trips                                            #
# --------------------------------------------------------------------------- #

def test_t2_fires_when_a_label_is_an_old_symbol_renamed(repo):
    """A rename produces a brand-new "changed symbol" whose body is not new at
    all. Scoring recall against it measures the rename, not the slicer."""
    _commit(repo, "m.py", "def old_name():\n    return 41 + 1\n")
    sha = _commit(repo, "m.py", "def new_name():\n    return 41 + 1\n")
    task = {"minted_at_sha": sha, "target": "m.py", "must_include": ["new_name"]}
    audit = mint.audit_noise_threats(task, repo)
    assert audit["t2_rename_roundtrip"] == "fired", audit
    assert audit["verdict"] == "fired"


def test_t2_is_clean_for_a_genuinely_new_symbol(repo):
    _commit(repo, "m.py", "def old_name():\n    return 41 + 1\n")
    sha = _commit(repo, "m.py",
                  "def old_name():\n    return 41 + 1\n\n\ndef fresh():\n    return 'x'\n")
    task = {"minted_at_sha": sha, "target": "m.py", "must_include": ["fresh"]}
    audit = mint.audit_noise_threats(task, repo)
    assert audit["t2_rename_roundtrip"] == "clean", audit


# --------------------------------------------------------------------------- #
# T3 -- the generated-file regen                                               #
# --------------------------------------------------------------------------- #

def test_t3_fires_on_a_generated_path_without_touching_git():
    for rel in ("dist/app.min.js", "build/out.py", "src/thing_pb2.py",
                "runs/x/report.py", "uv.lock"):
        audit = mint.audit_noise_threats(
            {"minted_at_sha": "0" * 40, "target": rel, "must_include": ["a"]},
            ".")
        assert audit["t3_generated"] == "fired", rel
        assert audit["verdict"] == "fired"


# --------------------------------------------------------------------------- #
# the refusals -- what must NOT be treated as evidence                         #
# --------------------------------------------------------------------------- #

def test_undecided_is_never_promoted(repo):
    """Markdown and JSON have no normalizer here. Absence of a check is not
    absence of a threat, and this is the single most tempting place to blur
    them: 11 stored tasks would become promotable by one wrong default."""
    _commit(repo, "d.md", "# A\n\ntext\n")
    sha = _commit(repo, "d.md", "# A\n\ntext changed\n")
    task = {"minted_at_sha": sha, "target": "d.md", "must_include": ["A"]}
    audit = mint.audit_noise_threats(task, repo)
    assert audit["t1_cosmetic"] == "undecided"
    assert audit["verdict"] == "undecided"
    assert mint.promotion_witness({**task, "noise_audit": audit}) is None


def test_a_target_absent_at_its_own_mint_sha_is_unverifiable(repo):
    """Two stored tasks are exactly this. Their labels may be fine; what is
    missing is the ability to CHECK, and that must be visible rather than
    indistinguishable from a passing audit."""
    sha = _commit(repo, "m.py", "def f():\n    return 1\n")
    task = {"minted_at_sha": sha, "target": "never_existed.py",
            "must_include": ["f"]}
    audit = mint.audit_noise_threats(task, repo)
    assert audit["verdict"] == "unverifiable_provenance"
    assert mint.promotion_witness({**task, "noise_audit": audit}) is None


def test_a_stale_audit_version_does_not_promote():
    """An audit produced under different rules is not evidence about today's.
    Without the version check, bumping NOISE_AUDIT_VERSION would silently keep
    honouring every audit it was bumped to invalidate."""
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
    """The original rule is unchanged in meaning. The point of returning a KIND
    rather than a boolean is that a consumer can still ask for only this one."""
    task = {"confirmations": mint.MINT_CONFIRM_THRESHOLD}
    assert mint.promotion_witness(task) == "recurrence"


def test_recurrence_wins_when_both_apply():
    """Deterministic precedence, so the recorded kind of a task cannot depend
    on evaluation order."""
    task = {"confirmations": mint.MINT_CONFIRM_THRESHOLD,
            "noise_audit": {"version": mint.NOISE_AUDIT_VERSION,
                            "verdict": "clean"}}
    assert mint.promotion_witness(task) == "recurrence"


def test_no_witness_is_the_default():
    assert mint.promotion_witness({}) is None
    assert mint.promotion_witness({"confirmations": 2}) is None
