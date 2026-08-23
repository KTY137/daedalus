"""A governance verdict is bounded to the REVISION it was measured at.

FINDING F8 (measured 2026-08-22, agent_env_g0 HEAD 898ac110). ``loop.py``
compared the governance payload's ``repo_root`` against the loop's checkout
(``_same_checkout``) and stopped there. ``gov_head`` was read, published beside
``source_revision`` in the report -- and never compared to it. So a
discrimination verdict measured at an OLDER HEAD of this very checkout still
unlocked promotion for code the gate had never seen. The gate's own claim is
"has the test gate been shown to catch planted defects at THIS revision?"
(``daedalus/core.py::_gov_discrimination``); outside that revision the claim
does not carry.

Narrowing only, exactly like the checkout check: a mismatch -- or a revision
nobody can read -- locks promotion and says so in the report. It can never
unlock it.

THE SEALED HALF. The same defect lives in ``_governance_verdict`` inside
``daedalus/kairos/_gated_writes_legacy.py.src``, which is pinned by blob sha
and owned by another lane. Its fix rides in
``docs/decisions-pending/gated_writes_lease_handdown.patch``;
``test_the_sealed_write_path_fix_is_pending_and_applies`` keeps that patch
honest until an owner applies it, and turns into a behavioural assertion the
moment it lands. It landed 2026-08-23 (pin e7acc630); the patch now lives under
``docs/decisions-taken/2026-08-23/``.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from daedalus.loop import LoopBounds, LoopDriver, _same_revision

REPO_ROOT = Path(__file__).resolve().parents[1]
PENDING_PATCH = REPO_ROOT / "docs" / "decisions-pending" / "gated_writes_lease_handdown.patch"
#: Where the patch went the day it landed (2026-08-23); kept so the test can
#: still name the hunk it once guarded.
TAKEN_PATCH = REPO_ROOT / "docs" / "decisions-taken" / "2026-08-23" / "gated_writes_lease_handdown.patch"
SEALED_SRC = REPO_ROOT / "daedalus" / "kairos" / "_gated_writes_legacy.py.src"


def _git_head(repo_root: str) -> str:
    proc = subprocess.run(["git", "-C", repo_root, "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True)
    return proc.stdout.strip().lower()


def _run(driver, gov):
    with mock.patch("daedalus.core.get_governance", return_value=gov):
        with mock.patch.object(LoopDriver, "_pick",
                               return_value=(None, [], "nothing admissible")):
            return driver.run()


def _driver(tmp_path, monkeypatch):
    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(tmp_path / "killswitch"))
    d = LoopDriver(str(REPO_ROOT), bounds=LoopBounds(max_iterations=1),
                   runs_dir=tmp_path)
    d.switch.arm(note="test")
    return d


# --------------------------------------------------------------------------- #
# the comparison                                                               #
# --------------------------------------------------------------------------- #
def test_a_verdict_from_an_older_head_of_this_checkout_locks_promotion(
        tmp_path, monkeypatch):
    driver = _driver(tmp_path, monkeypatch)
    stale = {
        "promotion_allowed": True,      # a PASS -- measured at another revision
        "verdict": "the gate has demonstrated discrimination at this revision",
        "state": "working",
        "head": "d" * 40,               # not this loop's HEAD
        "repo_root": str(REPO_ROOT),    # ...but the SAME checkout: the path
                                        # check above cannot see this at all
    }
    report = _run(driver, stale)
    assert report.promotion_allowed is False
    assert report.mode == "nominating_locked"
    assert report.governance_head == "d" * 40
    assert report.source_revision == _git_head(str(REPO_ROOT))
    # AND IT SAYS WHY, with both revisions, because "promotion is locked" with
    # no reason is what sends an operator looking for a broken loop.
    note = next((n for n in report.notes
                 if "GOVERNANCE IS ABOUT ANOTHER REVISION" in n), "")
    assert note, report.notes
    assert "d" * 40 in note and report.source_revision in note
    # NOT confused with the other-checkout case: that note is about WHERE, this
    # one is about WHEN, and reporting one fact as two problems is its own bug.
    assert not any("GOVERNANCE IS ABOUT ANOTHER CHECKOUT" in n
                   for n in report.notes)


def test_a_verdict_at_this_head_is_left_alone(tmp_path, monkeypatch):
    """The ALLOW half. A check that locks promotion unconditionally passes
    every refusal test above and makes the gate meaningless."""
    driver = _driver(tmp_path, monkeypatch)
    ours = {
        "promotion_allowed": True,
        "verdict": "the gate has demonstrated discrimination at this revision",
        "state": "working",
        "head": _git_head(str(REPO_ROOT)),
        "repo_root": str(REPO_ROOT),
    }
    report = _run(driver, ours)
    assert report.promotion_allowed is True
    assert report.mode == "nominating"
    assert not any("ANOTHER REVISION" in n for n in report.notes)


def test_a_verdict_with_no_revision_locks_promotion(tmp_path, monkeypatch):
    """Unknown is not a match. A verdict that cannot be tied to a revision
    cannot be shown to be about this one, and promotion is the one decision
    where 'probably the same tree' is not good enough."""
    driver = _driver(tmp_path, monkeypatch)
    report = _run(driver, {"promotion_allowed": True, "state": "working",
                           "verdict": "fine", "head": "",
                           "repo_root": str(REPO_ROOT)})
    assert report.promotion_allowed is False
    assert any("ANOTHER REVISION" in n for n in report.notes)


def test_the_checkout_mismatch_still_reports_as_a_checkout_problem(
        tmp_path, monkeypatch):
    """Regression guard for the note logic: a verdict from ANOTHER repository
    keeps its own explanation and does not get the revision note as well."""
    driver = _driver(tmp_path, monkeypatch)
    report = _run(driver, {
        "promotion_allowed": True, "state": "working", "verdict": "fine",
        "head": "d" * 40, "repo_root": str(tmp_path / "elsewhere")})
    assert report.promotion_allowed is False
    assert any("GOVERNANCE IS ABOUT ANOTHER CHECKOUT" in n for n in report.notes)
    assert not any("ANOTHER REVISION" in n for n in report.notes)


@pytest.mark.parametrize("a,b,same", [
    ("a" * 40, "a" * 40, True),
    ("A" * 40, "a" * 40, True),          # case is not identity
    ("abc1234" + "d" * 33, "abc1234", True),   # abbreviation of the same commit
    ("a" * 40, "b" * 40, False),
    ("", "a" * 40, False),               # unknown is not a match
    ("a" * 40, "", False),
    ("abc", "abc", False),               # too short to identify anything
])
def test_same_revision_compares_commits_not_strings(a, b, same):
    assert _same_revision(a, b) is same


# --------------------------------------------------------------------------- #
# the sealed write path                                                        #
# --------------------------------------------------------------------------- #
def _git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def test_the_sealed_write_path_fix_is_pending_and_applies(tmp_path):
    """``gated_writes`` has the same defect and is sealed, so its fix is a
    pending patch. This test refuses to let that patch rot: it applies it to a
    scratch copy of the sealed source, checks the result really contains the
    check, and recomputes the blob pin the patch tells an owner to paste into
    ``gated_writes.py``. A hunk edited without recomputing the pin fails here
    rather than at import time in production."""
    if not PENDING_PATCH.exists():          # applied and retired: assert instead
        assert "_wave_source_revision" in SEALED_SRC.read_text(encoding="utf-8")
        return
    text = PENDING_PATCH.read_text(encoding="utf-8")
    if "_wave_source_revision" in SEALED_SRC.read_text(encoding="utf-8"):
        return                              # landed; the patch is history now
    if shutil.which("git") is None:
        pytest.skip("git is not available to apply the pending patch")
    work = tmp_path / "daedalus" / "kairos"
    work.mkdir(parents=True)
    shutil.copyfile(SEALED_SRC, work / SEALED_SRC.name)
    proc = subprocess.run(["git", "apply", "-p1",
                           str(PENDING_PATCH)],
                          cwd=str(tmp_path), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    patched = (work / SEALED_SRC.name).read_bytes()
    body = patched.decode("utf-8")
    assert "def _same_revision" in body and "def _wave_source_revision" in body
    assert "_wave_source_revision(root)" in body
    # THE PIN, RECOMPUTED. The patch's own instructions carry this number; if
    # it is wrong the module refuses to import ("retained gated-write source
    # integrity mismatch"), which is a bad place to discover a typo.
    pin = _git_blob_sha1(patched)
    assert pin in text, (
        f"the pending patch tells the owner to set a pin that is not the sha1 "
        f"of its own output; recompute with `git hash-object` (measured {pin})")
