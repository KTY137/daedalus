"""`read_inlined_context` is the enforcement point, and nothing tested it.

FOUND BY MEASUREMENT, not by reading. A mutation run over
`daedalus/sensitivity.py` seeded 62 defects; 15 survived, and EIGHT of those
sit inside this one function -- the function whose own docstring calls itself
"this is the enforcement point". The reason is one grep: it is called by
`providers/ollama.py:590` and `providers/deepseek.py:68`, and before this file
NO TEST ANYWHERE IN THE REPO MENTIONED IT.

The survivors are not cosmetic. They include:

  * `allow_sensitive: bool = False` -> `True`   -- the fail-CLOSED default
    becomes fail-OPEN, so a caller that forgets the argument inlines everything
  * `if not allow_sensitive and ...` -> `if allow_sensitive and ...`, in BOTH
    the path check and the content check -- the guard fires exactly when it
    should not
  * `and` -> `or` in both places -- the trusted lane starts skipping and the
    untrusted lane starts inlining

Any one of them silently sends sensitive source to an external provider. This
is the same class of defect as the egress breach this repo already paid for,
where a comment asserting locality was doing the security work.

WHAT THESE TESTS ARE ABOUT: the two lanes must behave DIFFERENTLY, and the
difference must be in the direction that fails closed. A test that only checks
the untrusted lane skips would stay green against a function that skips
everything always -- which is why every refusal here is paired with the
corresponding allow.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from daedalus.sensitivity import read_inlined_context

SECRET = "AKIAIOSFODNN7EXAMPLE"          # AWS-shaped, the classifier's own shape
ORDINARY = "def add(a, b):\n    return a + b\n"


@pytest.fixture
def tree(tmp_path):
    """One ordinary file, one sensitive by NAME, one sensitive by CONTENT.

    Three files rather than two because the function has two independent
    checks -- path and content -- and a single fixture would let one guard
    cover for the other's removal.
    """
    (tmp_path / "ordinary.py").write_text(ORDINARY, encoding="utf-8")
    # Path-sensitive but NOT secret, so the path guard is isolated from the
    # floor. A `.env` carrying a credential trips BOTH, and a test where two
    # guards cover one file cannot tell you which one fired -- the first version
    # of this fixture used `TOKEN=abc123` and did exactly that.
    (tmp_path / ".env").write_text("EDITOR=vim\n", encoding="utf-8")
    (tmp_path / "innocent_name.py").write_text(
        f'AWS_KEY = "{SECRET}"\n', encoding="utf-8")
    return tmp_path


def _read(tree, names, **kw):
    return read_inlined_context([str(n) for n in names], str(tree), 100_000, **kw)


# --------------------------------------------------------------------------- #
# the default, which is the whole ballgame                                     #
# --------------------------------------------------------------------------- #
def test_the_DEFAULT_is_fail_closed():
    """A caller that forgets the argument must get the SAFE behaviour.

    `allow_sensitive` defaults to False. Flipping that default is one of the
    surviving mutants, and it is the worst of them: every existing call site
    that relies on the default would begin inlining secrets, with no diff at
    the call site to notice.
    """
    sig = inspect.signature(read_inlined_context)
    assert sig.parameters["allow_sensitive"].default is False


def test_the_default_actually_skips_a_secret(tree):
    """Not just the signature -- the behaviour, with the argument omitted."""
    text, skipped = _read(tree, ["innocent_name.py"])
    assert SECRET not in text
    assert "innocent_name.py" in skipped


# --------------------------------------------------------------------------- #
# path-based refusal, with its allow                                           #
# --------------------------------------------------------------------------- #
def test_a_sensitive_PATH_is_skipped_on_the_untrusted_lane(tree):
    text, skipped = _read(tree, [".env"], allow_sensitive=False)
    assert text == ""
    assert ".env" in skipped


def test_dotenv_is_refused_on_EVERY_lane_by_the_floors_path_channel(tree):
    """`.env` is not merely source-sensitive, it is floor-sensitive BY PATH.

    Measured while writing this file: `.env` is refused on the trusted lane too,
    and it is refused even with a completely innocuous body (`EDITOR=vim`). That
    is the floor's path channel, and it is correct -- but it means `.env` cannot
    be used to test the lane DIFFERENCE, because it never crosses either way.
    """
    for lane in (True, False):
        text, skipped = _read(tree, [".env"], allow_sensitive=lane)
        assert text == "", f"lane allow_sensitive={lane}"
        assert ".env" in skipped


def test_ordinary_SOURCE_is_the_thing_the_lanes_disagree_about(tree):
    """The allow side. Without it, a function that skipped everything always
    would pass every refusal test in this file while breaking the local lane
    that the whole distilled-context feature depends on.

    `ordinary.py` is the right specimen: `classify_data` calls it sensitive by
    path (source is withheld from an untrusted provider) while the floor does
    not touch it (there is no credential in it). Exactly one guard covers it,
    so the test can attribute what it sees.
    """
    text, skipped = _read(tree, ["ordinary.py"], allow_sensitive=True)
    assert "def add" in text
    assert skipped == []


# --------------------------------------------------------------------------- #
# content-based refusal, with its allow -- a SEPARATE guard                    #
# --------------------------------------------------------------------------- #
def test_a_secret_in_a_file_the_PATH_check_lets_through_is_still_skipped(tree):
    """The check the path guard cannot make -- and it needs a `.md` to reach.

    The first version of this test used a secret in an innocently-named `.py`
    and the content-check mutant SURVIVED it, because source is path-sensitive
    already: the path guard caught the file first and the content guard was
    never executed. The test was covering a line it never ran.

    A markdown file is the only shape in this fixture that passes the path
    check, so it is the only way to exercise the content check at all. That is
    a fact about the policy, and it is also why the `.md` allow-listing is worth
    watching: prose crosses the untrusted lane, and the CONTENT check is the
    only thing standing between a leaked key and an external provider.
    """
    leaky = tree / "leaky_prose.md"
    leaky.write_text(f"# Setup\n\nUse `{SECRET}` as the key.\n", encoding="utf-8")
    text, skipped = _read(tree, ["leaky_prose.md"], allow_sensitive=False)
    assert SECRET not in text, "a secret crossed the untrusted lane inside prose"
    assert "leaky_prose.md" in skipped


def test_the_secret_floor_holds_on_the_TRUSTED_lane_TOO(tree):
    """`allow_sensitive=True` is a statement about SOURCE, never credentials.

    This module documents the floor as "the UNCONDITIONAL secret floor -- runs
    in EVERY lane, no bypass", and a local model has no more need of a live key
    than a remote one. Before it was wired here, the trusted lane inlined it.
    """
    leaky = tree / "leaky_prose.md"
    leaky.write_text(f"# Setup\n\nUse `{SECRET}` as the key.\n", encoding="utf-8")
    text, skipped = _read(tree, ["leaky_prose.md"], allow_sensitive=True)
    assert SECRET not in text, "the floor was bypassed by the trusted lane"
    assert "leaky_prose.md" in skipped


def test_ORDINARY_markdown_still_crosses_both_lanes(tree):
    """The allow side for the floor: it must refuse secrets, not prose."""
    ok = tree / "fine.md"
    ok.write_text("# Notes\n\nnothing secret here\n", encoding="utf-8")
    for lane in (True, False):
        text, skipped = _read(tree, ["fine.md"], allow_sensitive=lane)
        assert "nothing secret here" in text, f"lane allow_sensitive={lane}"
        assert skipped == []


def test_a_PROJECT_POLICY_can_withhold_content_the_floor_does_not_know(tree):
    """What the lane-dependent content check is actually FOR, after the floor.

    Once the unconditional floor is wired, it catches every credential shape the
    repo knows -- so the content check below it survives mutation against any
    fixture built from those shapes. It is not dead code: it is the seam where a
    PROJECT states its own sensitive content, which the floor cannot know.

    Without this test the check reads as redundant, somebody deletes it as
    cleanup, and per-project confidentiality quietly stops working. That is the
    same shape as every other finding tonight -- a capability that exists,
    is not exercised, and is therefore indistinguishable from absent.
    """
    import dataclasses
    import re

    from daedalus.sensitivity import DEFAULT_POLICY

    # deny_content holds COMPILED patterns, not strings -- the field is searched
    # with `pat.search(text)`. Passing a bare string raises AttributeError deep
    # inside classify_data, which is how I found this out.
    proj = dataclasses.replace(
        DEFAULT_POLICY,
        deny_content=tuple(DEFAULT_POLICY.deny_content)
        + (re.compile(r"PROJECT-CONFIDENTIAL"),))
    doc = tree / "design.md"
    doc.write_text("# Design\n\nPROJECT-CONFIDENTIAL: the unreleased plan.\n",
                   encoding="utf-8")

    shut, shut_skipped = _read(tree, ["design.md"],
                               allow_sensitive=False, policy=proj)
    assert "unreleased plan" not in shut
    assert "design.md" in shut_skipped

    # and the lane still matters: the local model may read the project's own
    # confidential prose, which is the entire reason the check is lane-dependent
    # rather than part of the floor.
    open_, open_skipped = _read(tree, ["design.md"],
                                allow_sensitive=True, policy=proj)
    assert "unreleased plan" in open_
    assert open_skipped == []


def test_a_secret_in_an_INNOCENTLY_NAMED_source_file_is_skipped(tree):
    """Kept as well, because it is the case a reader expects to see -- but
    note it is the PATH guard that stops this one, not the content guard."""
    text, skipped = _read(tree, ["innocent_name.py"], allow_sensitive=False)
    assert SECRET not in text
    assert "innocent_name.py" in skipped


# --------------------------------------------------------------------------- #
# the lanes must DIFFER -- the property a single-lane test cannot see          #
# --------------------------------------------------------------------------- #
def test_the_two_lanes_do_not_agree(tree):
    """The one assertion that catches every `and`/`or` and `not` mutation.

    Each of those makes the two lanes behave the SAME as each other -- either
    both skipping or both inlining. Checking one lane in isolation cannot
    distinguish that from correct behaviour; comparing them can.

    THE CONTROL IS A `.md` FILE, and that is a measured fact about the policy
    rather than a convenience. Written naively this test used `ordinary.py` as
    the "survives both lanes" control and went red, because SOURCE IS WITHHELD
    FROM THE UNTRUSTED LANE ENTIRELY. Measured on the real classifier:

        ordinary.py  sensitive=True     notes.md   sensitive=False
        data.json    sensitive=True     README.md  sensitive=False
        notes.txt    sensitive=True
        app.tsx      sensitive=True

    So `.md` is the ONLY one of those that crosses. See the companion finding
    in the markdown-node work: `.md` is in GENERIC_ALLOW_SUBSTRINGS while
    `.markdown` and `.mdx` are not, and once documents are indexed that makes
    design docs and the council transcript egressable on the untrusted lane,
    floor-gated only. This test records the policy; it does not endorse it, and
    it goes red the day somebody changes it -- which is the point.
    """
    (tree / "notes.md").write_text("# Notes\nnothing secret here\n", encoding="utf-8")
    names = ["notes.md", "ordinary.py"]
    open_text, open_skipped = _read(tree, names, allow_sensitive=True)
    shut_text, shut_skipped = _read(tree, names, allow_sensitive=False)

    # SOURCE is the thing the lanes disagree about; the floor is not involved
    # in either file, so any difference here is attributable to the lane alone.
    assert shut_skipped == ["ordinary.py"]
    assert open_skipped == []
    assert "def add" in open_text and "def add" not in shut_text
    # the markdown survives BOTH lanes -- otherwise "they differ" could be
    # satisfied by a function that simply refuses everything when shut
    assert "nothing secret here" in open_text
    assert "nothing secret here" in shut_text


def test_SOURCE_is_withheld_from_the_untrusted_lane_entirely(tree):
    """Pinned separately because it surprised me and it will surprise the next
    reader: an ordinary .py with no secret in it does not cross."""
    text, skipped = _read(tree, ["ordinary.py"], allow_sensitive=False)
    assert text == ""
    assert "ordinary.py" in skipped
    open_text, _ = _read(tree, ["ordinary.py"], allow_sensitive=True)
    assert "def add" in open_text


# --------------------------------------------------------------------------- #
# the budget, and the failure mode of exhausting it                            #
# --------------------------------------------------------------------------- #
def test_a_file_that_does_not_fit_is_SKIPPED_not_silently_truncated_away(tree):
    """A caller must be able to tell "withheld" from "there was nothing".

    When the remaining budget cannot even hold the header, the file is reported
    in `skipped`. Dropping it without saying so is the same defect as a
    suppressed source rendering as an empty queue.
    """
    big = tree / "big.py"
    big.write_text("x = 1\n" * 5000, encoding="utf-8")
    text, skipped = read_inlined_context(
        ["big.py", "ordinary.py"], str(tree), 200, allow_sensitive=True)
    assert len(text) <= 200
    assert skipped, "a file was dropped for budget without being reported"


def test_the_budget_is_never_exceeded(tree):
    for cap in (0, 1, 50, 120):
        text, _ = read_inlined_context(
            ["ordinary.py"], str(tree), cap, allow_sensitive=True)
        assert len(text) <= cap, f"cap {cap} produced {len(text)} chars"


def test_an_unreadable_file_is_reported_not_swallowed(tree):
    text, skipped = _read(tree, ["does_not_exist.py"], allow_sensitive=True)
    assert text == ""
    assert "does_not_exist.py" in skipped


def test_a_secret_is_never_partially_inlined_by_the_budget(tree):
    """Truncation must not become a bypass.

    The content check runs on the WHOLE file before any slicing, so a secret
    cannot survive by sitting past the budget boundary -- but if the order were
    ever reversed, a large sensitive file would leak its head. Pinned here
    because the ordering is invisible at the call site.
    """
    leaky = tree / "leaky.py"
    leaky.write_text("# padding\n" * 500 + f'KEY = "{SECRET}"\n', encoding="utf-8")
    text, skipped = read_inlined_context(
        ["leaky.py"], str(tree), 300, allow_sensitive=False)
    assert text == ""
    assert "leaky.py" in skipped
