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


def test_the_module_says_what_a_green_run_does_not_prove():
    """A guarantee that reads stronger than the mechanism is this repository's
    most expensive recurring defect, so the docstring is pinned."""

    from daedalus.ariadne import campaign as subject

    text = subject.TestCommandEvaluator.__doc__ or ""
    assert "cannot pick its judge" in text
    assert "cannot weaken the judge" in text
    assert "cannot tell the difference is reported" in text
    assert sys.version_info >= (3, 12)
