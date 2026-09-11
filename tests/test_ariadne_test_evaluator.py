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
import tempfile
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
        (TestCommandEvaluator(argv=("sh", "-c", "rm -rf /")), "must be exactly python -m pytest"),
        (TestCommandEvaluator(argv=("python", "x" * 500)), "must be exactly python -m pytest"),
        (TestCommandEvaluator(argv=("python", "-m", "pytest", "x" * 500)), "short, non-empty text"),
        (TestCommandEvaluator(argv=("python", "-m", "pytest"), timeout_s=0), "between 1 and"),
        (TestCommandEvaluator(argv=("python", "-m", "pytest"), timeout_s=MAX_TEST_TIMEOUT_S + 1), "between 1 and"),
        (TestCommandEvaluator(argv=("python", "-m", "pytest"), test_roots=()), "non-empty text prefixes"),
        (TestCommandEvaluator(argv=("python", "-m", "pytest"), test_roots=("../escape",)), "relative segments"),
        (TestCommandEvaluator(argv=("python", "-m", "pytest"), test_roots=("C:/abs",)), "relative to the workspace"),
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
    # A containment backend may refuse the import-time forgery before the
    # cardinality check. Both are fail-closed; never require an attack to run.
    with pytest.raises(AriadneCampaignError, match=(
        "different number of tests|the repair does not pass the test command"
    )):
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
def test_the_evaluation_workspace_is_declared_and_always_removed(tmp_path):
    """NEGATIVE EVIDENCE, retained (Cerberus rounds 3 and 4).

    Round 3 moved this workspace into the system temp directory so that the
    retained observations would not be a parent of the running arm. Round 4
    measured that a contained arm finds this campaign's own baseline
    observation regardless, by walking down from the home directory -- the
    control root is home-derived. The move bought nothing measurable and cost
    two true statements (the arm ran outside the containment root the campaign
    declares and retains) plus an unbounded temp leak, so it was reverted.

    What is pinned instead is what actually holds: the workspace sits under the
    declared campaign root, and it is gone afterwards on every path -- including
    a fault, which left the entire pinned revision on disk in every earlier
    revision of this packet."""

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
    temp_root = Path(tempfile.gettempdir())
    before = len(list(temp_root.glob("daedalus-ariadne-eval-*")))
    original = subject.command_gate
    subject.command_gate = watched
    try:
        _campaign(root, revision, campaign_id="a14-workspace")
    finally:
        subject.command_gate = original

    assert len(seen) == 3
    control = control_root(root).resolve()
    for worktree in seen:
        # Declared: the lease names this root, and the retained containment
        # evidence is true because of it.
        assert control in worktree.resolve().parents
        # Removed: the receipt is the evidence, the tree is not.
        assert not worktree.exists()
    assert len(list(temp_root.glob("daedalus-ariadne-eval-*"))) == before


@pytest.mark.slow
def test_a_fault_after_the_extraction_leaves_no_workspace_behind(tmp_path):
    """Cerberus round 4 (NEW-1): the arm's try block had no `finally`, so a
    fault between building the workspace and removing it left about 284 MiB of
    the pinned revision on disk, permanently, once per faulted arm."""

    from daedalus.spine.killswitch import control_root

    root, revision = _subject(tmp_path, TEST_SEEING)
    original = subject.command_gate

    def exploding(argv, **kwargs):
        def boom(_ctx):
            raise RuntimeError("injected fault after the revision was extracted")

        return boom

    subject.command_gate = exploding
    try:
        with pytest.raises(Exception):
            _campaign(root, revision, campaign_id="a15-fault")
    finally:
        subject.command_gate = original

    evaluations = control_root(root) / "ariadne" / "workspaces" / "evaluations"
    leftover = [p for p in evaluations.iterdir()] if evaluations.is_dir() else []
    assert leftover == [], f"a faulted arm left its workspace behind: {leftover}"


@pytest.mark.slow
def test_an_unreadable_spec_fails_the_replay_closed(tmp_path, monkeypatch):
    """Cerberus round 3 (medium 1) and round 4 (NEW-3): the branch accepted a
    null evaluator digest whenever the ExperimentSpec could not be read, because
    `None in (X, None)` is true. Absence must refuse.

    Pinned by BEHAVIOUR: the previous version of this test asserted the spelling
    of the source line, so an equivalent rewrite that reintroduced the bug would
    have passed it."""

    root, revision = _subject(tmp_path, TEST_SEEING)
    monkeypatch.setattr(subject, "_frozen_evaluator_of", lambda store, receipt: None)
    with pytest.raises(AriadneCampaignError, match="command digest"):
        _campaign(root, revision, campaign_id="a16-nospec")


@pytest.mark.slow
def test_a_change_no_test_reads_is_not_nominated(tmp_path):
    """Odysseus round 2 (O2-1a), EXECUTED: `LIMIT = 10` -> `LIMIT = 999`, a real
    behaviour change, was NOMINATED although no test read LIMIT. Nothing was
    forged: the negative control failed because the mangled file no longer
    parsed, so its failure proved the suite LOADS the file and nothing about
    whether it exercises the changed region.

    A test that ERRORED did not run. A test that FAILED ran and disagreed. Only
    the second is evidence, and demanding it means many campaigns will refuse --
    correctly, because they prove nothing."""

    root = tmp_path / "subject"
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "mod.py").write_text("LIMIT = 10\n\n\ndef add(a, b):\n    return a + b\n",
                                         encoding="utf-8")
    (root / "tests" / "test_mod.py").write_text(
        "from pkg.mod import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    }
    for argv in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "fixture"]):
        subprocess.run(["git", "-C", str(root), *argv], check=True, env=env, capture_output=True)
    KillSwitch(repo_root=root).arm(note="G1-IKARUS-49 fixture")
    revision = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()

    # `LIMIT = 10` mangles to `LIMIT = 10__ariadne_negative__`, which is a SYNTAX
    # error, so the control does not parse. That is a different situation from
    # "the suite is blind" and the campaign now says which one it met -- the
    # first version of this test used the wrong one as its demonstration
    # (Cerberus round 1 of G1-IKARUS-49, high 2).
    with pytest.raises(AriadneCampaignError, match="did not parse or collect"):
        run_campaign(
            repo_root=str(root), source_revision=revision, campaign_id="a17-uncovered",
            target_path="pkg/mod.py", before="LIMIT = 10", after="LIMIT = 999",
            timeout_s=60, evaluator=EVALUATOR,
        )


@pytest.mark.slow
def test_a_repair_that_neuters_the_suite_in_place_is_still_nominated(tmp_path):
    """NEGATIVE EVIDENCE, retained (Odysseus round 2 on the merged packet, O2-1b).

    Two lines inside the candidate -- replacing pytest's own `runtest` with a
    no-op -- neuter every assertion while the SAME tests are collected and
    "run". The counts match, the identities match, the outcomes match, pytest
    writes the report truthfully, and a wrong repair IS NOMINATED.

    This is the sharpest instance of the limit the packet states: the target
    must be a file the suite imports, so candidate code runs inside the judging
    process, and no inspection of what that process reports can tell a run from
    a performance of a run. Comparing identities closed the cases where the
    outcomes differ; it cannot close this one, and pretending otherwise would be
    the exact defect this repository blocks on.

    What still holds is the only thing that ever protected the repository: the
    receipt says the verdict is self-reported, and a nomination is not a
    promotion."""

    root, revision = _subject(tmp_path, TEST_SEEING)
    neutered = (
        "return a * 1000 + b\n"
        "import _pytest.python as _p\n"
        "_p.Function.runtest = lambda self: None\n"
    )
    receipt = run_campaign(
        repo_root=str(root), source_revision=revision, campaign_id="a18-neutered",
        target_path="pkg/mod.py", before=BEFORE, after=neutered,
        timeout_s=60, evaluator=EVALUATOR,
    )
    assert receipt["outcome"] == "nominated"  # measured, not desired

    from daedalus.spine.killswitch import control_root

    hedged = 0
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
            hedged += 1
        if isinstance(blob, dict) and blob.get("nomination_status") == "nominated":
            assert "SELF-REPORTED" in " ".join(blob.get("reasons", ()))
            hedged += 1
    assert hedged >= 4  # three arms plus the nomination


def test_an_untracked_attributes_file_cannot_choose_what_is_judged(tmp_path):
    """Odysseus round 2 (O2-2), EXECUTED: `git archive` honours
    `$GIT_DIR/info/attributes`, which is untracked, in no revision and invisible
    to `git status`. One `export-ignore` line removed the test that guarded a
    target and flipped a refusal into a nomination.

    The workspace is now compared with the revision's own tree listing, which
    does not read that file."""

    root, revision = _subject(tmp_path, TEST_SEEING)
    clean_files, _ = _extract_revision(root, revision, tmp_path / "ws-clean")
    assert clean_files == 3

    (root / ".git" / "info").mkdir(parents=True, exist_ok=True)
    (root / ".git" / "info" / "attributes").write_text(
        "tests/test_mod.py export-ignore\n", encoding="utf-8")
    porcelain = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                               capture_output=True, text=True, check=True).stdout
    assert porcelain == ""  # invisible to every ordinary check

    files, _ = _extract_revision(root, revision, tmp_path / "ws-attrs")
    assert files == 3  # the export filter cannot remove what is read by digest


def test_the_evaluator_argv_head_is_an_allowlist():
    """Cerberus round 1 of G1-IKARUS-49 (CRITICAL 2): the rule was a denylist of
    spellings, and CPython bundles short options. `python -Ic "import os;
    os.system(...)"` was admitted, and so were `-Sc`, `--command=`, `-` (the
    program on stdin), `-m pip install requests` (which writes the interpreter
    that judges every later campaign) and `--pyargs` (which runs an INSTALLED
    package's tests instead of the workspace's).

    A denylist of an option parser this module does not own cannot be closed.
    The head is an allowlist: the command IS `python -m pytest`."""

    for bad in (
        ("python", "-Ic", "import os; os.system('whoami')"),
        ("python", "-Sc", "import os"),
        ("python", "--command=import os"),
        ("python", "-"),
        ("python", "-c", "import os"),
        ("python", "-m", "pip", "install", "requests"),
        ("python", "-m", "http.server", "8000"),
        ("python", "-X", "importtime", "-m", "pytest"),
        ("pytest",),
        ("python", "-m"),
    ):
        with pytest.raises(AriadneCampaignError, match="must be exactly python -m pytest"):
            _admit_test_evaluator(TestCommandEvaluator(argv=bad))

    # The ARGUMENTS are an allowlist too. Round 1 defeated the head denylist
    # with `-Ic`; round 2 defeated the argument denylist exactly the same way,
    # one token to the right, because the loop SKIPPED any `-`-leading token it
    # did not recognise. Both bundled forms below were admitted and both are
    # honoured by the real pytest: `-pNAME` imports and EXECUTES a module
    # before conftest, and `-c<path>` reads a config file outside the workspace
    # whose `addopts` re-injects anything -- including the plugin load.
    for bad, expected in (
        (("python", "-m", "pytest", "-pevilplugin", "tests"), "only DISABLE a plugin"),
        (("python", "-m", "pytest", "-cC:/Windows/win.ini", "tests"), "by name only"),
        (("python", "-m", "pytest", "-c../../evil.ini", "tests"), "by name only"),
        (("python", "-m", "pytest", "-foo=/etc/x", "tests"), "by name only"),
        (("python", "-m", "pytest", "-Ic", "import os"), "by name only"),
        (("python", "-m", "pytest", "-o", "addopts=-pevil"), "by name only"),
        (("python", "-m", "pytest", "-W", "error"), "by name only"),
        (("python", "-m", "pytest", "-X", "dev"), "by name only"),
        (("python", "-m", "pytest", "--import-mode=importlib"), "by name only"),
        (("python", "-m", "pytest", "--basetemp=/tmp/x"), "by name only"),
        (("python", "-m", "pytest", "--pyargs", "daedalus"), "by name only"),
        (("python", "-m", "pytest", "--rootdir=/etc"), "by name only"),
        (("python", "-m", "pytest", "--tb=evil"), "unknown traceback style"),
        (("python", "-m", "pytest", "--maxfail=x"), "unusable --maxfail"),
        (("python", "-m", "pytest", "--maxfail=0"), "unusable --maxfail"),
        (("python", "-m", "pytest", "C:/Windows/Temp"), "relative to the workspace"),
        (("python", "-m", "pytest", "/etc"), "relative to the workspace"),
        (("python", "-m", "pytest", "../../.."), "no empty or relative segments"),
        (("python", "-m", "pytest", "-p", "sitecustomize"), "only DISABLE a plugin"),
        (("python", "-m", "pytest", "-p=evil"), "only DISABLE a plugin"),
        (("python", "-m", "pytest", "-pno:"), "only DISABLE a plugin"),
        # Round 3, CRITICAL 3. `@x` is NOT a path: pytest builds its parser
        # with `fromfile_prefix_chars="@"`, so argparse opens the named file
        # and splices its lines in as arguments -- before pytest sees them,
        # with no path restriction. Measured through `run_campaign`, a
        # `conftest.py` outside the workspace and in no revision was imported
        # and EXECUTED inside the contained gate in all three arms.
        (("python", "-m", "pytest", "@C:/Windows/Temp/pwn.txt"), "argument FILE"),
        (("python", "-m", "pytest", "@/etc/pwn.txt"), "argument FILE"),
        (("python", "-m", "pytest", "@//server/share/pwn.txt"), "argument FILE"),
        (("python", "-m", "pytest", "@pwn.txt"), "argument FILE"),
        # pytest has no `--plugin`; `-p` is registered short-only.
        (("python", "-m", "pytest", "--plugin=no:randomly"), "by name only"),
        (("python", "-m", "pytest", "--plugin=evil"), "by name only"),
        # `str.isdigit()` is true for these and `int()` raises on the first,
        # so without the ascii guard this escapes as a bare ValueError.
        (("python", "-m", "pytest", "--maxfail=\u00b2"), "unusable --maxfail"),
        (("python", "-m", "pytest", "--maxfail=\u0663"), "unusable --maxfail"),
        # A path token now goes through `_admit_workspace_relative` -- the same
        # primitive the revision entries use -- instead of four hand-written
        # shape checks. That is what closes the class rather than the spelling.
        (("python", "-m", "pytest", "tests/NUL"), "no Windows filesystem can hold"),
        (("python", "-m", "pytest", "tests/x:y"), "relative to the workspace"),
        (("python", "-m", "pytest", "tests/t.py::test_a"), "relative to the workspace"),
        (("python", "-m", "pytest", "tests//unit"), "no empty or relative segments"),
        # The argv IS the campaign identity: it is frozen into the
        # ExperimentSpec and its digest. So a path cannot be normalised on the
        # way through -- that would change the digest -- and the only
        # consistent rule is to refuse a spelling that is not already the
        # admitted one, saying which spelling to write (round 4, low 2).
        (("python", "-m", "pytest", "tests/unit/"), "already be in their admitted spelling"),
        (("python", "-m", "pytest", "tests\\unit"), "already be in their admitted spelling"),
    ):
        with pytest.raises(AriadneCampaignError, match=expected):
            _admit_test_evaluator(TestCommandEvaluator(argv=bad))

    # The shapes a real campaign uses still pass, including disabling the cache
    # writer so pytest does not dirty the tree it is judging, including the
    # bundled `-pno:NAME`, because refusing that would break a real command
    # while refusing nothing. `--plugin` is NOT among them: pytest has no such
    # option, and this list had pinned it as a good shape (round 3, low).
    for good in (
        ("python", "-m", "pytest", "-q", "tests"),
        ("python", "-m", "pytest", "-q", "-p", "no:cacheprovider"),
        ("python", "-m", "pytest", "-pno:cacheprovider", "tests"),
        ("python", "-m", "pytest", "--tb=short", "--maxfail=1", "tests/unit"),
        ("python", "-m", "pytest", "-x", "--no-header", "tests"),
    ):
        _admit_test_evaluator(TestCommandEvaluator(argv=good))


def test_a_revision_naming_a_windows_device_is_refused_on_every_host():
    """Cerberus round 2 (high 1), MEASURED: `_admit_workspace_relative` promised
    "no device name" in its docstring and had no such check. A tree of `NUL` and
    `ok.txt` extracted as TWO files with ONE on disk -- the write to `NUL`
    silently succeeds and stores nothing, and the counter still says two. That
    is the O2-2 shape, the workspace silently differing from the revision, at a
    smaller scale.

    Refused on every platform, not only Windows: the guarantee is that the
    workspace IS the revision on every supported host, and a name that cannot
    be materialised identically everywhere makes it false wherever it is
    admitted."""

    for name in ("NUL", "nul.txt", "sub/CON.py", "a/b/LPT9", "com1", "PRN.md", "CONIN$"):
        with pytest.raises(AriadneCampaignError, match="no Windows filesystem can hold"):
            subject._admit_workspace_relative(name, label="revision entry")
    # And names that merely LOOK like devices are still ordinary files, because
    # a false refusal makes real repositories inadmissible.
    for name in ("a/nulls.py", "console.py", "aux2/x", "tests/test_com.py", "NULL.py"):
        assert subject._admit_workspace_relative(name, label="revision entry") == name


def test_the_workspace_is_built_from_objects_not_from_git_archive(tmp_path):
    """Cerberus round 1 of G1-IKARUS-49 (CRITICAL 1): the workspace comparison
    checked NAMES. `git archive` also applies attribute-selected export AND
    smudge filters -- the latter an arbitrary shell command from an untracked
    config. The reviewer rewrote the guarding test's body while the file list
    stayed identical, and ran a command on the host on the way.

    Reading blobs by digest has no attribute, filter or end-of-line input at
    all, which is why this is now a construction rather than a check."""

    root, revision = _subject(tmp_path, TEST_SEEING)
    guard = (root / "tests" / "test_mod.py").read_text(encoding="utf-8")

    (root / ".git" / "info").mkdir(parents=True, exist_ok=True)
    (root / ".git" / "info" / "attributes").write_text(
        "tests/test_mod.py filter=neutered\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "config", "filter.neutered.smudge",
                    "sed s/assert/assert True or/"], check=True, capture_output=True)
    porcelain = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                               capture_output=True, text=True, check=True).stdout
    assert porcelain == ""  # invisible to every ordinary check

    files, _ = _extract_revision(root, revision, tmp_path / "ws")
    assert files == 3
    # The bytes are the revision's, not the filter's.
    assert (tmp_path / "ws" / "tests" / "test_mod.py").read_text(encoding="utf-8") == guard
    assert "assert True or" not in (tmp_path / "ws" / "tests" / "test_mod.py").read_text(encoding="utf-8")

    # And the export filter that removed a file entirely is equally inert.
    (root / ".git" / "info" / "attributes").write_text(
        "tests/test_mod.py export-ignore\n", encoding="utf-8")
    files_again, _ = _extract_revision(root, revision, tmp_path / "ws2")
    assert files_again == 3
    assert (tmp_path / "ws2" / "tests" / "test_mod.py").read_text(encoding="utf-8") == guard


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


def test_the_workspace_refuses_an_object_the_revision_did_not_name(tmp_path, monkeypatch):
    """The payload is bound to the digest the TREE named, not to the oid git
    echoed back (Cerberus round 2, low).

    Checking a blob against git's own echo verifies that git is self-consistent
    and nothing else. Here `cat-file --batch` answers every request with a
    different, internally consistent object -- the shape a compromised object
    store or a substituted alternate would produce -- and the extraction
    refuses instead of writing it."""

    root, revision = _subject(tmp_path, TEST_SEEING)
    payload = b"# not what the revision names\n"
    frame = b"%s blob %d\n%s\n" % (
        hashlib.sha1(b"blob %d\x00" % len(payload) + payload).hexdigest().encode("ascii"),
        len(payload), payload)
    real = subject._git_out

    def substituted(root_arg, args, *, stdin=None):
        if args and args[0] == "cat-file":
            return frame * (stdin.count(b"\n") if stdin else 1)
        return real(root_arg, args, stdin=stdin)

    monkeypatch.setattr(subject, "_git_out", substituted)
    with pytest.raises(AriadneCampaignError, match="does not match its digest"):
        _extract_revision(root, revision, tmp_path / "workspace")


def test_the_workspace_refuses_a_filesystem_that_stores_nothing(tmp_path, monkeypatch):
    """A write that silently succeeds and stores nothing (Cerberus round 2,
    high 1).

    That is what `NUL` did: the counter said two files, one was on disk, and
    nothing refused. The name check refuses the device names this module
    enumerates; this refuses whatever the enumeration misses, because a
    workspace whose file count is not the revision's file count is not the
    revision, and every later comparison rests on that count."""

    root, revision = _subject(tmp_path, TEST_SEEING)
    monkeypatch.setattr(Path, "write_bytes", lambda self, data: len(data))
    with pytest.raises(AriadneCampaignError, match="did not materialise"):
        _extract_revision(root, revision, tmp_path / "workspace")


@pytest.mark.slow
def test_a_content_sensitive_test_supplies_the_control_failure_without_executing(tmp_path):
    """NEGATIVE EVIDENCE, retained (Cerberus round 1 of this packet, high 1).

    The gate this packet added asks the negative control to contain a test that
    the baseline PASSED and that FAILED. A content-sensitive test -- a style,
    lint, census or byte-pin test that reads the source as TEXT rather than
    executing it -- supplies that failure without ever running the changed
    region. Here the suite never imports `pkg.mod` at all: it only asserts that
    no line is longer than 32 characters. The control's mutation appends
    `__ariadne_negative__`, taking the line to 36, so the test fails; the
    repair's line is 28, so it passes; and NOTHING called `add()` in any arm.

    Every new gate passes and the nomination is vacuous. This is the second
    vacuity route the packet leaves open, and the packet says so rather than
    claiming a closure: closing it needs the failing control test to be one
    that IMPORTS the target, which the baseline arm could record and this
    packet does not.

    The acceptance matrix asserted this pin before it existed (Cerberus round 2,
    high 2). It exists now, and it asserts the measured outcome."""

    root = tmp_path / "subject"
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "mod.py").write_text(MODULE, encoding="utf-8")
    # A style test. It reads the file; it never imports it.
    (root / "tests" / "test_style.py").write_text(
        "from pathlib import Path\n\n\n"
        "def test_lines_are_short():\n"
        "    source = Path(__file__).resolve().parents[1] / 'pkg' / 'mod.py'\n"
        "    for line in source.read_text(encoding='utf-8').splitlines():\n"
        "        assert len(line) <= 32, line\n",
        encoding="utf-8")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    }
    for argv in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "fixture"]):
        subprocess.run(["git", "-C", str(root), *argv], check=True, env=env, capture_output=True)
    KillSwitch(repo_root=root).arm(note="G1-IKARUS-49 content-sensitive fixture")
    revision = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()

    receipt = run_campaign(
        repo_root=str(root), source_revision=revision, campaign_id="a19-content",
        target_path="pkg/mod.py", before=BEFORE, after=AFTER,
        timeout_s=60, evaluator=EVALUATOR,
    )
    assert receipt["outcome"] == "nominated"  # measured, not desired
    arms = {trial["variant_id"]: trial["status"] for trial in receipt["trials"]}
    assert arms == {"baseline": "passed", "negative-control": "failed", "repair": "passed"}

    # The only thing that protects the reader is the hedge, so it must be on
    # every observation and on the nomination.
    from daedalus.spine.killswitch import control_root

    hedged = 0
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
            hedged += 1
        if isinstance(blob, dict) and blob.get("nomination_status") == "nominated":
            assert "SELF-REPORTED" in " ".join(blob.get("reasons", ()))
            hedged += 1
    assert hedged >= 4


def test_a_config_in_an_ancestor_cannot_reach_into_the_workspace(tmp_path):
    """Cerberus round 4 (high 1), MEASURED: pytest's rootdir discovery walks
    UPWARD out of the workspace.

    An ini file in an ANCESTOR directory becomes the configfile, and its
    `addopts` re-injects any option -- including `-p <module>`, which loads and
    executes an arbitrary module inside the judging process. That is round 2's
    CRITICAL reproduced with no hostile argv at all, so no argv rule can close
    it. `--confcutdir` closes only the conftest half; the campaign's own `-c`
    closes both, which is why the campaign appends one beside `--junitxml=`.

    This is a property test, not an enumeration: it booby-traps the
    surroundings and asserts no tripwire fires. Four review rounds established
    that an enumeration lasts exactly as long as the author's imagination."""

    outer = tmp_path / "outer"
    workspace = outer / "ws"
    (workspace / "tests").mkdir(parents=True)
    (workspace / "tests" / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8")

    # The traps: a config whose addopts loads a plugin, the plugin itself, and
    # a conftest. All OUTSIDE the workspace, all in no revision.
    marker = tmp_path / "TRIPWIRE.txt"
    payload = (
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('outside the workspace ran', encoding='utf-8')\n"
    )
    (outer / "canary.py").write_text(payload, encoding="utf-8")
    (outer / "conftest.py").write_text(payload, encoding="utf-8")
    (outer / "pytest.ini").write_text(
        "[pytest]\naddopts = -p canary\n", encoding="utf-8")

    def run(*extra: str) -> subprocess.CompletedProcess:
        if marker.exists():
            marker.unlink()
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
             *extra, "tests"],
            cwd=workspace, capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": str(outer)},
        )

    # Without the campaign's config the ancestor wins: this is the finding.
    unguarded = run()
    assert marker.exists(), (
        "the ancestor config did not fire, so this test proves nothing on this "
        f"host: {unguarded.stdout[-400:]}")

    # With it, nothing outside the workspace is read or executed.
    config = workspace / subject.TEST_CONFIG_RELATIVE
    config.write_bytes(subject.TEST_CONFIG_BODY)
    guarded = run("-c", subject.TEST_CONFIG_RELATIVE)
    assert not marker.exists(), (
        "a file outside the workspace ran despite the campaign's own config: "
        f"{guarded.stdout[-400:]}")
    assert guarded.returncode == 0, guarded.stdout[-400:]


def test_the_campaign_owns_its_config_name(tmp_path):
    """A revision that already carries that name would have its own file
    overwritten, and the fence would be whatever the revision put there."""

    assert subject.TEST_CONFIG_RELATIVE.startswith("daedalus-ariadne-")
    assert subject.TEST_CONFIG_BODY == b"[pytest]\n"  # a fence, not a config
