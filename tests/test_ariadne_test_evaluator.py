"""G1-IKARUS-48: the campaign evaluator that runs the project's tests.

The exact-match evaluator proves an edit landed. It proves nothing about whether
the project still works, which is why no receipt written by it may be called
self-improvement. This suite pins what the test-running evaluator adds, and --
just as important -- what it refuses to conclude:

* a green suite that SEES the file nominates (A1);
* a suite that passes on the negative control does NOT nominate, because it
  cannot see the file at all (A2);
* a suite that is already red does NOT nominate, because nothing can be
  attributed to the change (A3);
* a target inside a declared test root is refused before the runner: when tests
  are the judge, the candidate may not be a test (A4);
* the command comes from the caller and the workspace is the pinned revision
  with exactly one file replaced (A5);
* the default is unchanged: without an evaluator the frozen exact-match path
  runs exactly as before (A6);
* every refusal of the evaluator record happens before the repository is
  observed (A7).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from daedalus.ariadne.campaign import (
    MAX_TEST_TIMEOUT_S,
    AriadneCampaignError,
    TestCommandEvaluator,
    _admit_test_evaluator,
    _extract_revision,
    run_campaign,
)
from daedalus.ariadne import campaign as subject
from daedalus.spine.killswitch import KillSwitch

MODULE = "def add(a, b):\n    return a + b\n"
TEST_SEEING = "from pkg.mod import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"
TEST_BLIND = "def test_unrelated():\n    assert True\n"
TEST_RED = "from pkg.mod import add\n\n\ndef test_add():\n    assert add(2, 3) == 6\n"
BEFORE = "return a + b"
AFTER = "return a + b  # repaired"
EVALUATOR = TestCommandEvaluator(
    argv=("python", "-m", "pytest", "-q", "-p", "no:cacheprovider"), timeout_s=120
)


def _subject(tmp_path: Path, test_body: str) -> tuple[Path, str]:
    """A real Git repository with a module and a suite, and an armed kill switch."""

    root = tmp_path / "subject"
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "mod.py").write_text(MODULE, encoding="utf-8")
    (root / "tests" / "test_mod.py").write_text(test_body, encoding="utf-8")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    }
    for argv in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "fixture"]):
        subprocess.run(["git", "-C", str(root), *argv], check=True, env=env, capture_output=True)
    KillSwitch(repo_root=root).arm(note="G1-IKARUS-48 fixture subject")
    revision = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    return root, revision


def _campaign(root: Path, revision: str, *, campaign_id: str, target: str = "pkg/mod.py",
              evaluator: TestCommandEvaluator | None = EVALUATOR) -> dict:
    return run_campaign(
        repo_root=str(root), source_revision=revision, campaign_id=campaign_id,
        target_path=target, before=BEFORE, after=AFTER, timeout_s=60, evaluator=evaluator,
    )


# --------------------------------------------------------------------------- A1
@pytest.mark.slow
def test_a_suite_that_sees_the_file_nominates(tmp_path):
    """MEASURED end to end: three contained arms, a real pytest run in each."""

    root, revision = _subject(tmp_path, TEST_SEEING)
    receipt = _campaign(root, revision, campaign_id="a1-green")
    arms = {trial["variant_id"]: trial["status"] for trial in receipt["trials"]}
    assert arms == {"baseline": "passed", "negative-control": "failed", "repair": "passed"}
    assert receipt["outcome"] == "nominated"
    assert receipt["metric_names"] == ["tests_pass"]
    assert all(trial["metrics"] == {"tests_pass": 1 if trial["status"] == "passed" else 0}
               for trial in receipt["trials"])
    # The nomination says what was proven, and it is not "improvement".
    reasons = " ".join(receipt["nomination_reasons"]) if "nomination_reasons" in receipt else ""
    assert "improve" not in json.dumps(receipt).lower() or not reasons
    # Nothing was applied: the subject's tracked tree is untouched.
    porcelain = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
                               capture_output=True, text=True, check=True).stdout
    assert porcelain == ""
    assert (root / "pkg" / "mod.py").read_text(encoding="utf-8") == MODULE


# --------------------------------------------------------------------------- A2
@pytest.mark.slow
def test_a_suite_blind_to_the_file_nominates_nothing(tmp_path):
    """The negative control exists to FAIL. When it passes, the suite cannot see
    this file, and a passing repair would prove nothing."""

    root, revision = _subject(tmp_path, TEST_BLIND)
    with pytest.raises(AriadneCampaignError, match="cannot see this file"):
        _campaign(root, revision, campaign_id="a2-blind")


# --------------------------------------------------------------------------- A3
@pytest.mark.slow
def test_an_already_red_suite_nominates_nothing(tmp_path):
    """A red baseline means no verdict about the change can be attributed."""

    root, revision = _subject(tmp_path, TEST_RED)
    with pytest.raises(AriadneCampaignError, match="already fails on the unmodified revision"):
        _campaign(root, revision, campaign_id="a3-red")


# --------------------------------------------------------------------------- A4
def test_a_target_inside_a_test_root_is_refused_before_the_runner(tmp_path):
    """Section 8.1's rule, applied to the project's own suite: a candidate may
    not be a test when tests are the judge. Refused before anything is read."""

    root, revision = _subject(tmp_path, TEST_SEEING)
    with pytest.raises(AriadneCampaignError, match="inside a declared test root"):
        _campaign(root, revision, campaign_id="a4-test", target="tests/test_mod.py")
    # The same target is admissible when the exact-match evaluator judges.
    with pytest.raises(AriadneCampaignError, match="before text must occur"):
        _campaign(root, revision, campaign_id="a4-exact", target="tests/test_mod.py", evaluator=None)


# --------------------------------------------------------------------------- A5
def test_the_workspace_is_the_pinned_revision_not_the_working_tree(tmp_path):
    """`git archive` reads the REVISION, so a dirty checkout cannot leak into a
    trial, and two extractions are byte-identical."""

    root, revision = _subject(tmp_path, TEST_SEEING)
    (root / "pkg" / "mod.py").write_text("def add(a, b):\n    return 'dirty'\n", encoding="utf-8")
    (root / "untracked.py").write_text("# never committed\n", encoding="utf-8")

    def digest(directory: Path) -> str:
        digestor = hashlib.sha256()
        for path in sorted(p for p in directory.rglob("*") if p.is_file()):
            digestor.update(path.relative_to(directory).as_posix().encode("utf-8"))
            digestor.update(hashlib.sha256(path.read_bytes()).digest())
        return digestor.hexdigest()

    first_files, first_bytes = _extract_revision(root, revision, tmp_path / "ws-a")
    second_files, _ = _extract_revision(root, revision, tmp_path / "ws-b")
    assert (first_files, second_files) == (3, 3) and first_bytes > 0
    assert digest(tmp_path / "ws-a") == digest(tmp_path / "ws-b")
    assert (tmp_path / "ws-a" / "pkg" / "mod.py").read_text(encoding="utf-8") == MODULE
    assert not (tmp_path / "ws-a" / "untracked.py").exists()
    assert not (tmp_path / "ws-a" / ".git").exists()


# --------------------------------------------------------------------------- A6
def test_the_default_is_the_unchanged_exact_match_evaluator(tmp_path):
    """No caller changes behaviour by upgrading: without an evaluator the frozen
    path runs, with its own metric name and its own arm shape."""

    root, revision = _subject(tmp_path, TEST_SEEING)
    receipt = _campaign(root, revision, campaign_id="a6-default", evaluator=None)
    arms = {trial["variant_id"]: trial["status"] for trial in receipt["trials"]}
    assert arms == {"baseline": "failed", "negative-control": "failed", "repair": "passed"}
    assert receipt["metric_names"] == ["exact_match"]
    assert receipt["outcome"] == "nominated"


# --------------------------------------------------------------------------- A7
def test_every_evaluator_refusal_precedes_the_repository(tmp_path):
    """The evaluator record is admitted before anything is observed, so a bad
    command cannot reach a repository read."""

    for bad, expected in (
        (TestCommandEvaluator(argv=()), "1-32 text arguments"),
        (TestCommandEvaluator(argv=("sh", "-c", "rm -rf /")), "must start with 'python'"),
        (TestCommandEvaluator(argv=("python", "x" * 500)), "short, non-empty text"),
        (TestCommandEvaluator(argv=("python",), timeout_s=0), "between 1 and"),
        (TestCommandEvaluator(argv=("python",), timeout_s=MAX_TEST_TIMEOUT_S + 1), "between 1 and"),
        (TestCommandEvaluator(argv=("python",), test_roots=()), "non-empty text prefixes"),
        (TestCommandEvaluator(argv=("python",), test_roots=("../escape",)), "relative segments"),
        (TestCommandEvaluator(argv=("python",), test_roots=("C:/abs",)), "relative to the workspace"),
    ):
        with pytest.raises(AriadneCampaignError, match=expected):
            _admit_test_evaluator(bad)
    with pytest.raises(AriadneCampaignError, match="must be a TestCommandEvaluator"):
        _admit_test_evaluator("python -m pytest")
    # The digest changes with every field, so a frozen spec pins the whole command.
    first = TestCommandEvaluator(argv=("python", "-m", "pytest")).digest
    assert first != TestCommandEvaluator(argv=("python", "-m", "pytest", "-q")).digest
    assert first != TestCommandEvaluator(argv=("python", "-m", "pytest"), timeout_s=99).digest
    assert first != TestCommandEvaluator(argv=("python", "-m", "pytest"), test_roots=("t/",)).digest
    assert first == TestCommandEvaluator(argv=("python", "-m", "pytest")).digest


def test_a_session_configuring_target_is_refused_at_any_depth(tmp_path):
    """Cerberus round 1 (CRITICAL 2), EXECUTED: a candidate whose target was
    `conftest.py` installed a collection hook that skipped every item. The arms
    still read baseline-passed / control-failed / repair-passed and the campaign
    NOMINATED a candidate whose winning arm ran zero assertions. Refusing test
    roots was never enough: the files that CONFIGURE a session decide the
    verdict without being tests."""

    root, revision = _subject(tmp_path, TEST_SEEING)
    for target in ("conftest.py", "pkg/conftest.py", "deep/nested/conftest.py",
                   "pytest.ini", "pyproject.toml", "setup.cfg", "setup.py", "tox.ini",
                   "sitecustomize.py", "usercustomize.py", "pkg/anything.pth"):
        with pytest.raises(AriadneCampaignError, match="configures the test session"):
            _campaign(root, revision, campaign_id="a8-config", target=target)
    # The same names are admissible when the exact-match evaluator judges: it
    # never executes them, so they are ordinary files there.
    with pytest.raises(Exception, match="unavailable|before text must occur"):
        _campaign(root, revision, campaign_id="a8-exact", target="conftest.py", evaluator=None)


def test_a_suite_that_executed_nothing_cannot_pass(tmp_path):
    """The second half of the same repair: an exit code cannot tell "the tests
    passed" from "no test ran", so the campaign reads the counts from a report
    it appends itself."""

    from daedalus.ariadne.campaign import _read_test_report

    report = tmp_path / "report.xml"
    report.write_text('<testsuites><testsuite tests="7" failures="0" errors="0" skipped="7"/></testsuites>',
                      encoding="utf-8")
    counts = _read_test_report(report)
    assert counts["tests"] == 7 and counts["skipped"] == 7
    assert counts["executed"] == 0  # everything was skipped: nothing was proven

    report.write_text('<testsuite tests="4" failures="1" errors="0" skipped="1"/>', encoding="utf-8")
    assert _read_test_report(report) == {"tests": 4, "failures": 1, "errors": 0,
                                         "skipped": 1, "executed": 3}


def test_the_report_is_hostile_input_and_is_bounded(tmp_path):
    """The report is written by a process the candidate influenced. A doctype, an
    entity declaration, a missing file, unreadable XML and an oversized file are
    all refusals, not crashes."""

    from daedalus.ariadne.campaign import MAX_TEST_REPORT_BYTES, _read_test_report

    report = tmp_path / "report.xml"
    with pytest.raises(AriadneCampaignError, match="wrote no report"):
        _read_test_report(report)
    report.write_bytes(b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "aa">]><testsuite tests="1"/>')
    with pytest.raises(AriadneCampaignError, match="doctype or an XML entity"):
        _read_test_report(report)
    report.write_bytes(b"<testsuite tests='1'")
    with pytest.raises(AriadneCampaignError, match="not readable XML"):
        _read_test_report(report)
    report.write_bytes(b"<testsuite tests='x'/>")
    with pytest.raises(AriadneCampaignError, match="non-numeric count"):
        _read_test_report(report)
    report.write_bytes(b"<testsuite/>" + b" " * (MAX_TEST_REPORT_BYTES + 1))
    with pytest.raises(AriadneCampaignError, match="exceeds its bound"):
        _read_test_report(report)


def test_the_observation_retains_counts_and_never_the_output(tmp_path):
    """Cerberus round 1 (CRITICAL 1), EXECUTED: the retained observation carried
    the operator's API key, because the contained child inherits the environment
    and the candidate printed it. The output is no longer retained at all."""

    root, revision = _subject(tmp_path, TEST_SEEING)
    receipt = _campaign(root, revision, campaign_id="a9-noleak")
    payload = json.dumps(receipt)
    assert "sk-ant" not in payload and "ANTHROPIC" not in payload
    from daedalus.spine.killswitch import control_root
    control = control_root(root)
    hits = []
    for path in control.rglob("*"):
        if not path.is_file():
            continue
        try:
            blob = json.loads(path.read_bytes().decode("utf-8"))
        except (ValueError, UnicodeDecodeError, OSError):
            continue
        if isinstance(blob, dict) and str(blob.get("schema", "")).startswith(
                "daedalus-ariadne-test-evaluator-observation"):
            hits.append(blob)
    assert hits, "the campaign wrote no test observation"
    for blob in hits:
        assert blob["output"] == ""  # the text stays in the gate's scratch
        assert len(blob["output_sha256"]) == 64  # the digest still binds what the gate saw
        assert set(blob["report"]) >= {"tests", "failures", "errors", "skipped", "executed"}
        assert "sk-ant" not in json.dumps(blob)


def test_the_campaign_identity_binds_its_judge(tmp_path):
    """Cerberus round 1 (high 1), EXECUTED: the replay key excluded the
    evaluator, so a second run that asked for the test suite was handed the
    exact-match run's nomination and ran nothing."""

    root, revision = _subject(tmp_path, TEST_SEEING)
    exact = _campaign(root, revision, campaign_id="a10-identity", evaluator=None)
    assert exact["metric_names"] == ["exact_match"]
    with pytest.raises(Exception) as caught:
        _campaign(root, revision, campaign_id="a10-identity")
    # A different judge is a different campaign, and the conflict says so
    # rather than returning the other judge's receipt.
    assert "exact_match" not in str(caught.value)


@pytest.mark.slow
def test_a_forged_report_with_inflated_counts_is_refused(tmp_path):
    """Cerberus round 2 (CRITICAL), EXECUTED by the reviewer: the JUnit report
    the count-rule reads lives in the workspace the candidate's own code runs
    in. A repair that wrote the report itself, claiming 41 tests, and exited
    zero before pytest finished, was NOMINATED.

    The repair arm must now execute exactly as many tests as the baseline, and
    a forger cannot read the baseline's count off its own arm. What this test
    does NOT claim: that a forger who counts the suite itself and reports that
    number is caught. It is not, and `verdict_is_self_reported` says so on
    every observation."""

    root, revision = _subject(tmp_path, TEST_SEEING)
    forged = (
        "return a + b\n\n"
        "import os as _o, pathlib as _p\n"
        "_p.Path('daedalus-ariadne-report.xml').write_text(\n"
        "    '<testsuite name=\"pytest\" tests=\"41\" failures=\"0\" errors=\"0\" skipped=\"0\"/>')\n"
        "_o._exit(0)\n"
    )
    with pytest.raises(AriadneCampaignError, match="different number of tests"):
        run_campaign(
            repo_root=str(root), source_revision=revision, campaign_id="a11-forge",
            target_path="pkg/mod.py", before=BEFORE, after=forged, timeout_s=60,
            evaluator=EVALUATOR,
        )


def test_every_observation_says_the_verdict_is_self_reported(tmp_path):
    """The receipt must not let a reader assume an independent evaluator. The
    counts come from a process that ran candidate code."""

    root, revision = _subject(tmp_path, TEST_SEEING)
    _campaign(root, revision, campaign_id="a12-selfreport")
    from daedalus.spine.killswitch import control_root

    seen = 0
    for path in control_root(root).rglob("*"):
        if not path.is_file():
            continue
        try:
            blob = json.loads(path.read_bytes().decode("utf-8"))
        except (ValueError, UnicodeDecodeError, OSError):
            continue
        if isinstance(blob, dict) and str(blob.get("schema", "")).startswith(
                "daedalus-ariadne-test-evaluator-observation"):
            assert blob["verdict_is_self_reported"] is True
            assert blob["child_environment"] == "inherited-except-denylist"
            assert blob["child_network"] == "unrestricted"
            seen += 1
    assert seen >= 3  # one per arm


@pytest.mark.slow
def test_the_nomination_a_human_reads_says_the_verdict_is_self_reported(tmp_path):
    """Cerberus round 3 (high 2): `verdict_is_self_reported` lived on the
    observation, in the docstring and in the packet -- everywhere except the one
    artifact a human reads at the promotion gate. The nomination said "passed
    the frozen project test command" flatly, for runs that never executed a
    test."""

    root, revision = _subject(tmp_path, TEST_SEEING)
    from daedalus.spine.killswitch import control_root

    receipt = _campaign(root, revision, campaign_id="a13-hedge")
    assert receipt["outcome"] == "nominated"
    # The nomination is its own artifact: this is the one a human reads.
    nominations = []
    for path in control_root(root).rglob("*"):
        if not path.is_file():
            continue
        try:
            blob = json.loads(path.read_bytes().decode("utf-8"))
        except (ValueError, UnicodeDecodeError, OSError):
            continue
        if isinstance(blob, dict) and blob.get("nomination_status") == "nominated":
            nominations.append(blob)
    assert nominations, "the campaign wrote no nomination receipt"
    for nomination in nominations:
        reasons = " ".join(nomination.get("reasons", ()))
        assert "SELF-REPORTED" in reasons
        assert "not an independent measurement" in reasons


@pytest.mark.slow
def test_the_evaluation_workspace_is_not_under_the_retained_evidence(tmp_path):
    """Cerberus round 3 (high 1, Forge C): the arm's working directory was a
    descendant of the control root, so a candidate could walk up and read the
    BASELINE arm's retained observation -- the very count the equality rule
    expects it not to know. The reviewer's A/B differed in nothing else.

    Reads are still not fenced, so this raises the cost rather than closing the
    class; what it removes is the one-directory-away version."""

    from daedalus.spine.killswitch import control_root

    seen: list[Path] = []
    real_gate = subject.command_gate

    def watched(argv, **kwargs):
        runner = real_gate(argv, **kwargs)

        def wrapped(ctx):
            seen.append(Path(ctx.worktree))
            return runner(ctx)

        return wrapped

    root, revision = _subject(tmp_path, TEST_SEEING)
    original = subject.command_gate
    subject.command_gate = watched
    try:
        _campaign(root, revision, campaign_id="a14-workspace")
    finally:
        subject.command_gate = original

    assert len(seen) == 3
    control = control_root(root).resolve()
    for worktree in seen:
        assert control not in worktree.resolve().parents


def test_an_unreadable_spec_fails_the_replay_closed(tmp_path):
    """Cerberus round 3 (medium 1): `None in (EVALUATOR_SHA256, None)` accepted
    an observation whose evaluator digest was null whenever the spec could not
    be read. Absence must refuse, not pass."""

    source = Path(subject.__file__).read_text(encoding="utf-8")
    assert "(EVALUATOR_SHA256,) if spec_frozen_evaluator is None" in source
    assert "None in" not in source.split("def _require_campaign_inner_effect_terminals")[1][:4000]


def test_the_module_says_what_a_green_run_does_not_prove():
    """A guarantee that reads stronger than the mechanism is this repository's
    most expensive recurring defect, so the docstring is pinned."""

    from daedalus.ariadne import campaign as subject

    # Collapsed, because a pinned sentence must not depend on where the line
    # wrapped: the round-2 assertion below failed for exactly that reason.
    text = " ".join((subject.TestCommandEvaluator.__doc__ or "").split())
    assert "cannot pick its judge" in text
    assert "cannot tell the difference is reported" in text
    # Cerberus round 1 refuted the round-0 wording "cannot weaken the judge":
    # the overwritten file MUST influence the run, or the negative control could
    # never fail. What the mechanism actually guarantees is narrower, and the
    # docstring now says the narrower thing plus the hole that was proven.
    assert "cannot weaken the judge" not in text
    assert "cannot rewrite the TEST FILES or the session configuration" in text
    assert "It is NOT true that" in text and "conftest.py" in text
    # And it does not claim a sandbox it does not have.
    assert "NOT a sandbox claim" in text
    assert "DENYLIST" in text and "no network fence" in text
    # Round 2: the verdict is a self-report from a process that ran candidate
    # code, and the docstring must say so where a reader cannot miss it.
    assert "NOT PROOF AGAINST A HOSTILE GENERATOR" in text
    assert "SELF-REPORT" in text and "verdict_is_self_reported" in text
    assert "nomination is not promotion" in text
    assert sys.version_info >= (3, 12)
