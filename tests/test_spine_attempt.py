"""Tests for daedalus.spine.attempt.

The load-bearing assertion in this file is not the happy path: it is
``assert_primary_untouched``, called after EVERY scenario. An attempt that can
dirty the developer's working tree is worse than an attempt that does nothing.
Every runner and gate here is injected, so nothing touches a model or a network.
"""
import dataclasses
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

import daedalus.spine.attempt as attempt_mod
from daedalus.spine.attempt import (
    INTENT_KIND,
    STATE_CANCELLED,
    STATE_CLEAN,
    STATE_GATES_FAILED,
    STATE_NO_CHANGE,
    STATE_RUNNER_FAILED,
    STATE_STORAGE_UNAVAILABLE,
    STATE_WORKTREE_FAILED,
    GateResult,
    PrimaryCheckoutWrite,
    RunnerContext,
    TaskAttempt,
    TaskSpec,
    command_gate,
    pytest_gate_argv,
)
from daedalus.spine.ledger import STATE_COMPLETED, STATE_FAILED, SpineLedger
from daedalus.storage import StorageUnavailable


# --------------------------------------------------------------------------- #
# fixtures                                                                     #
# --------------------------------------------------------------------------- #
@pytest.fixture
def worktree_root(tmp_path, monkeypatch):
    root = tmp_path / "wt_root"
    monkeypatch.setenv("DAEDALUS_WORKTREE_ROOT", str(root))
    return root


@pytest.fixture
def repo(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    def run_git(*args):
        subprocess.run(["git", *args], cwd=repo_path, check=True,
                       capture_output=True)

    run_git("init")
    run_git("config", "user.name", "Test User")
    run_git("config", "user.email", "test@example.com")
    (repo_path / "seed.txt").write_text("seed\n")
    run_git("add", "seed.txt")
    run_git("commit", "-m", "seed")
    return repo_path


@pytest.fixture
def ledger(tmp_path):
    led = SpineLedger(tmp_path / "spine" / "spine.sqlite3")
    try:
        yield led
    finally:
        led.close()


def _git_out(repo_path, *args):
    return subprocess.run(["git", *args], cwd=repo_path, check=True,
                          capture_output=True, text=True).stdout


def head_of(repo_path):
    return _git_out(repo_path, "rev-parse", "HEAD").strip()


def assert_primary_untouched(repo_path, head_before):
    """The primary checkout must be byte-identical to how we found it.

    Working tree clean, HEAD unmoved, and the seed file untouched. A branch ref
    and a worktree registration in .git ARE expected -- that is how
    ``git worktree add -b`` makes the effect findable after a crash -- and
    neither shows up in any of these three checks.
    """
    assert _git_out(repo_path, "status", "--porcelain").strip() == ""
    assert head_of(repo_path) == head_before
    assert (repo_path / "seed.txt").read_text() == "seed\n"


def spec(**kw):
    base = dict(task_id="demo-task", instruction="add a widget")
    base.update(kw)
    return TaskSpec(**base)


def writing_runner(files):
    """A runner that writes ``files`` (rel path -> text) into the worktree."""
    calls = []

    def _runner(ctx: RunnerContext):
        calls.append(ctx)
        for rel, text in files.items():
            target = Path(ctx.worktree) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        return {"wrote": sorted(files)}

    _runner.calls = calls
    return _runner


def gate_returning(result):
    calls = []

    def _gate(ctx: RunnerContext):
        calls.append(ctx)
        return result

    _gate.calls = calls
    return _gate


def passing_gate():
    return gate_returning(GateResult(passed=True, name="fake", output="1 passed"))


# --------------------------------------------------------------------------- #
# happy path                                                                   #
# --------------------------------------------------------------------------- #
def test_happy_path_artifact_and_primary_untouched(repo, worktree_root, ledger):
    head = head_of(repo)
    runner = writing_runner({"widget.txt": "hello\n", "pkg/mod.py": "x = 1\n"})
    gate = passing_gate()

    result = TaskAttempt(spec(), runner=runner, gate=gate, repo_root=repo,
                         ledger=ledger).run()

    assert result.state == STATE_CLEAN
    assert result.ok is True
    art = result.artifact
    assert art is not None
    assert art.changed_paths == ("pkg/mod.py", "widget.txt")
    assert art.base_revision == head
    assert art.diff_sha256 == hashlib.sha256(art.diff_bytes).hexdigest()
    assert "widget.txt" in art.diff and "hello" in art.diff
    assert art.is_empty is False
    # the runner ran inside the worktree, which is outside the repo
    ctx = runner.calls[0]
    assert Path(ctx.worktree).resolve() != repo.resolve()
    assert repo.resolve() not in Path(ctx.worktree).resolve().parents
    # gate saw the same worktree
    assert gate.calls[0].worktree == ctx.worktree
    # cleanup happened and was not swallowed
    assert result.worktree_removed is True
    assert result.cleanup_error is None
    assert not Path(result.worktree_path).exists()

    assert_primary_untouched(repo, head)
    assert not (repo / "widget.txt").exists()


def test_diff_digest_is_stable_across_attempts(repo, worktree_root, ledger):
    head = head_of(repo)
    files = {"widget.txt": "hello\n"}

    first = TaskAttempt(spec(), runner=writing_runner(files), gate=passing_gate(),
                        repo_root=repo, ledger=ledger).run()
    second = TaskAttempt(spec(), runner=writing_runner(files), gate=passing_gate(),
                         repo_root=repo, ledger=ledger).run()

    assert first.state == second.state == STATE_CLEAN
    assert first.branch != second.branch  # retry nonce keeps branches distinct
    assert first.artifact.diff_sha256 == second.artifact.diff_sha256
    assert_primary_untouched(repo, head)


def test_ledger_has_no_open_intents_after_a_completed_attempt(repo, worktree_root,
                                                              ledger):
    head = head_of(repo)
    result = TaskAttempt(spec(), runner=writing_runner({"a.txt": "a\n"}),
                         gate=passing_gate(), repo_root=repo, ledger=ledger).run()

    assert result.intent_id is not None
    assert result.ledger_error is None
    assert ledger.open_intents() == []
    intent = ledger.get(result.intent_id)
    assert intent.state == STATE_COMPLETED
    assert intent.effect_id == result.artifact.diff_sha256
    assert intent.result["state"] == STATE_CLEAN
    assert_primary_untouched(repo, head)


def test_effect_key_is_findable_in_the_world_WHILE_the_intent_is_open(
        repo, worktree_root, ledger):
    """The crash window, tested at the only moment it exists.

    The effect key closes the window between "intent recorded" and "intent
    resolved": crash in there and recovery asks `git branch --list <key>`. So
    the property has to hold DURING the attempt, which is what this checks --
    from inside the runner, while the intent is still INTENDED.

    It deliberately no longer asserts the branch survives a completed run.
    Once the intent is resolved the window is shut, recovery never looks the
    key up again, and the ref is pure leak -- one per attempt in the shared
    .git, forever. See the reaping tests below.
    """
    seen = {}

    def runner(ctx):
        # Mid-attempt: the effect exists in the world and the intent is open.
        seen["branches"] = _git_out(repo, "branch", "--list", ctx.branch)
        open_now = ledger.open_intents(INTENT_KIND)
        seen["open_intent_effect_keys"] = [i.effect_key for i in open_now]
        (ctx.worktree / "a.txt").write_text("a\n", encoding="utf-8")

    head = head_of(repo)
    at = TaskAttempt(spec(), runner=runner, gate=passing_gate(),
                     repo_root=repo, ledger=ledger)
    result = at.run()

    assert result.effect_key == result.branch == at.branch
    assert result.effect_key in seen["branches"], (
        "the effect key was NOT findable in the world during the attempt -- "
        "the crash window is open")
    assert result.effect_key in seen["open_intent_effect_keys"], (
        "recovery could not have joined the open intent to the branch")

    found = ledger.resolve_by_effect(result.effect_key)
    assert [i.id for i in found] == [result.intent_id]
    assert_primary_untouched(repo, head)


def test_a_resolved_attempt_reaps_its_branch_and_reports_it(
        repo, worktree_root, ledger):
    # `git worktree add -b` writes a ref into the SHARED .git that nothing
    # removed. Reaping happens strictly AFTER resolution, so it cannot reopen
    # the crash window above.
    head = head_of(repo)
    at = TaskAttempt(spec(), runner=writing_runner({"a.txt": "a\n"}),
                     gate=passing_gate(), repo_root=repo, ledger=ledger)
    result = at.run()

    assert result.state == STATE_CLEAN
    assert result.reap_error is None
    assert result.branch not in _git_out(repo, "branch", "--list", result.branch)
    deleted = [r for r in result.reaped if r.get("action") == "deleted"]
    assert [r.get("branch") for r in deleted] == [result.branch]
    # The ledger still answers "did this attempt happen?" -- the durable record
    # is the ledger's, not the ref's.
    assert [i.id for i in ledger.resolve_by_effect(result.effect_key)] == \
           [result.intent_id]
    assert_primary_untouched(repo, head)


def test_reaping_is_provably_lossless_and_can_be_turned_off(
        repo, worktree_root, ledger):
    head = head_of(repo)
    at = TaskAttempt(spec(), runner=writing_runner({"a.txt": "a\n"}),
                     gate=passing_gate(), repo_root=repo, ledger=ledger,
                     reap=False)
    result = at.run()

    assert result.reaped == ()
    assert result.branch in _git_out(repo, "branch", "--list", result.branch), (
        "reap=False still deleted the branch")
    assert_primary_untouched(repo, head)


def test_keeping_the_worktree_reaps_nothing(repo, worktree_root, ledger):
    # The manager's own precondition: a branch whose worktree has NOT been
    # through cleanup is still live, and must not be reaped even by default.
    head = head_of(repo)
    at = TaskAttempt(spec(), runner=writing_runner({"a.txt": "a\n"}),
                     gate=passing_gate(), repo_root=repo, ledger=ledger,
                     keep_worktree=True)
    result = at.run()

    assert result.branch in _git_out(repo, "branch", "--list", result.branch)
    assert not [r for r in result.reaped if r.get("action") == "deleted"]
    assert_primary_untouched(repo, head)


# --------------------------------------------------------------------------- #
# failure states                                                               #
# --------------------------------------------------------------------------- #
def test_gates_failed_retains_raw_output(repo, worktree_root, ledger):
    head = head_of(repo)
    raw = "=== FAILURES ===\nE   assert 1 == 2\n" + ("noise\n" * 50)
    gate = gate_returning(GateResult(passed=False, name="fake", returncode=1,
                                     command=("py", "-m", "pytest"), output=raw))

    result = TaskAttempt(spec(), runner=writing_runner({"a.txt": "a\n"}),
                         gate=gate, repo_root=repo, ledger=ledger).run()

    assert result.state == STATE_GATES_FAILED
    assert result.ok is False
    assert result.gates.output == raw          # raw output retained verbatim
    assert result.gates.returncode == 1
    assert result.artifact is not None         # a rejected candidate is a candidate
    # a produced artifact COMPLETES the intent; the gate verdict is a judgement
    # about the effect, not the effect
    intent = ledger.get(result.intent_id)
    assert intent.state == STATE_COMPLETED
    assert intent.effect_id == result.artifact.diff_sha256
    assert intent.result["gates"]["passed"] is False
    assert "assert 1 == 2" in intent.result["gates"]["output_tail"]
    assert ledger.open_intents() == []

    assert_primary_untouched(repo, head)
    assert not (repo / "a.txt").exists()


def test_runner_raising_yields_runner_failed_and_marks_intent_failed(
        repo, worktree_root, ledger):
    head = head_of(repo)
    gate = passing_gate()

    def boom(ctx):
        raise ValueError("model went sideways")

    result = TaskAttempt(spec(), runner=boom, gate=gate, repo_root=repo,
                         ledger=ledger).run()

    assert result.state == STATE_RUNNER_FAILED
    assert "ValueError: model went sideways" in result.error
    assert result.artifact is None
    assert gate.calls == []                    # gates never ran
    intent = ledger.get(result.intent_id)
    assert intent.state == STATE_FAILED
    assert "runner_failed" in intent.error
    assert ledger.open_intents() == []
    assert result.worktree_removed is True

    assert_primary_untouched(repo, head)


def test_storage_unavailable_short_circuits_before_any_worktree(
        repo, worktree_root, ledger, monkeypatch):
    head = head_of(repo)
    consulted = []

    def refusing(path, min_free_gib=None):
        consulted.append(path)
        raise StorageUnavailable("storage_unavailable: test volume full")

    monkeypatch.setattr(attempt_mod, "require_storage", refusing)
    runner = writing_runner({"a.txt": "a\n"})
    gate = passing_gate()

    at = TaskAttempt(spec(), runner=runner, gate=gate, repo_root=repo,
                     ledger=ledger)
    result = at.run()

    assert result.state == STATE_STORAGE_UNAVAILABLE
    assert "storage_unavailable" in result.error
    assert consulted, "the watermark must actually be consulted"
    # nothing was recorded and nothing was created
    assert result.intent_id is None
    assert ledger.open_intents() == []
    assert ledger.get(1) is None
    assert runner.calls == [] and gate.calls == []
    assert not (worktree_root / at.branch).exists()
    assert at.branch not in _git_out(repo, "worktree", "list")
    assert at.branch not in _git_out(repo, "branch", "--list")

    assert_primary_untouched(repo, head)


def test_worktree_failure_is_a_state_and_marks_intent_failed(
        repo, worktree_root, ledger, monkeypatch):
    head = head_of(repo)

    class BrokenManager:
        def __init__(self, root):
            self.worktree_root = root

        def create_worktree(self, base_commit, branch_name):
            raise RuntimeError("git worktree add exploded")

        def cleanup_worktree(self, path):  # pragma: no cover - never reached
            raise AssertionError("cleanup must not run without a worktree")

    runner = writing_runner({"a.txt": "a\n"})
    result = TaskAttempt(spec(), runner=runner, gate=passing_gate(),
                         repo_root=repo, ledger=ledger,
                         worktree_manager=BrokenManager(worktree_root)).run()

    assert result.state == STATE_WORKTREE_FAILED
    assert "git worktree add exploded" in result.error
    assert runner.calls == []
    assert result.artifact is None
    intent = ledger.get(result.intent_id)
    assert intent.state == STATE_FAILED       # intent recorded, then closed
    assert ledger.open_intents() == []

    assert_primary_untouched(repo, head)


def test_no_change_is_not_reported_as_clean(repo, worktree_root, ledger):
    head = head_of(repo)
    gate = passing_gate()

    def idle_runner(ctx):
        return "did nothing"

    result = TaskAttempt(spec(), runner=idle_runner, gate=gate, repo_root=repo,
                         ledger=ledger).run()

    assert result.state == STATE_NO_CHANGE
    assert result.ok is False
    assert result.artifact is not None and result.artifact.is_empty
    assert result.artifact.changed_paths == ()
    assert gate.calls == [], "gates on an unmodified tree are a vacuous pass"
    assert ledger.get(result.intent_id).state == STATE_COMPLETED
    assert_primary_untouched(repo, head)


def test_cleanup_failure_is_reported_not_swallowed(repo, worktree_root, ledger,
                                                   monkeypatch):
    head = head_of(repo)
    from daedalus.kairos.worktree import GitWorktreeManager

    manager = GitWorktreeManager(repo)
    leaked = {}

    def failing_cleanup(path):
        leaked["path"] = Path(path)
        raise RuntimeError("permission denied removing worktree")

    monkeypatch.setattr(manager, "cleanup_worktree", failing_cleanup)

    result = TaskAttempt(spec(), runner=writing_runner({"a.txt": "a\n"}),
                         gate=passing_gate(), repo_root=repo, ledger=ledger,
                         worktree_manager=manager).run()

    assert result.state == STATE_CLEAN          # the candidate is still valid
    assert result.worktree_removed is False
    assert "permission denied removing worktree" in result.cleanup_error
    assert ledger.get(result.intent_id).result["cleanup_error"]
    assert leaked["path"].exists()              # the leak is real, and reported

    assert_primary_untouched(repo, head)
    GitWorktreeManager(repo).cleanup_worktree(leaked["path"])


# --------------------------------------------------------------------------- #
# cancellation                                                                 #
# --------------------------------------------------------------------------- #
def test_cancel_before_any_effect_records_nothing(repo, worktree_root, ledger):
    head = head_of(repo)
    runner = writing_runner({"a.txt": "a\n"})

    at = TaskAttempt(spec(), runner=runner, gate=passing_gate(), repo_root=repo,
                     ledger=ledger, cancel=lambda: True)
    result = at.run()

    assert result.state == STATE_CANCELLED
    assert result.intent_id is None
    assert runner.calls == []
    assert ledger.open_intents() == []
    assert not (worktree_root / at.branch).exists()
    assert_primary_untouched(repo, head)


def test_cancel_after_capture_keeps_the_artifact_and_completes_the_intent(
        repo, worktree_root, ledger):
    head = head_of(repo)
    fired = {"v": False}
    gate = passing_gate()

    def runner(ctx):
        (Path(ctx.worktree) / "a.txt").write_text("a\n")
        fired["v"] = True                       # cancel only from here on
        return None

    result = TaskAttempt(spec(), runner=runner, gate=gate, repo_root=repo,
                         ledger=ledger, cancel=lambda: fired["v"]).run()

    assert result.state == STATE_CANCELLED
    assert result.artifact is not None and not result.artifact.is_empty
    assert gate.calls == []
    intent = ledger.get(result.intent_id)
    assert intent.state == STATE_COMPLETED
    assert intent.effect_id == result.artifact.diff_sha256
    assert_primary_untouched(repo, head)


def test_threading_event_is_accepted_as_a_cancel_token(repo, worktree_root,
                                                       ledger):
    import threading

    head = head_of(repo)
    ev = threading.Event()
    ev.set()
    runner = writing_runner({"a.txt": "a\n"})

    result = TaskAttempt(spec(), runner=runner, gate=passing_gate(),
                         repo_root=repo, ledger=ledger, cancel=ev).run()

    assert result.state == STATE_CANCELLED
    assert runner.calls == []
    assert_primary_untouched(repo, head)


# --------------------------------------------------------------------------- #
# the no-primary-write property, structurally                                  #
# --------------------------------------------------------------------------- #
def test_git_choke_point_refuses_mutating_verbs_in_the_primary_checkout(repo):
    head = head_of(repo)
    for args in (["checkout", "."], ["reset", "--hard"], ["apply", "p.patch"],
                 ["add", "-A"], ["commit", "-m", "x"], ["stash"],
                 ["cherry-pick", "HEAD"], ["merge", "other"]):
        with pytest.raises(PrimaryCheckoutWrite):
            attempt_mod._git(args, cwd=repo, repo_root=repo)

    # ...including from a subdirectory of the primary checkout
    sub = repo / "pkg"
    sub.mkdir()
    with pytest.raises(PrimaryCheckoutWrite):
        attempt_mod._git(["checkout", "."], cwd=sub, repo_root=repo)

    # reads are still allowed, and nothing above executed
    out = attempt_mod._git(["rev-parse", "HEAD"], cwd=repo, repo_root=repo)
    assert out.stdout.decode().strip() == head
    assert _git_out(repo, "status", "--porcelain").strip() == ""


def test_all_git_goes_through_the_single_choke_point():
    src = Path(attempt_mod.__file__).read_text(encoding="utf-8")
    # exactly one subprocess call in the module, inside _git; adding a second
    # would route around the primary-checkout guard
    assert src.count("subprocess.run(") == 1
    assert "subprocess.Popen" not in src
    assert "os.system" not in src


def test_runner_context_cannot_name_the_primary_checkout():
    names = {f.name for f in dataclasses.fields(RunnerContext)}
    assert "worktree" in names
    assert not any("repo" in n for n in names)
    assert not hasattr(RunnerContext(worktree=Path("."), branch="b",
                                     base_revision="0" * 40, task=spec(),
                                     is_cancelled=lambda: False), "repo_root")


def test_module_exposes_no_apply_path():
    exported = set(attempt_mod.__all__)
    forbidden = {"apply", "apply_patch", "promote", "land", "commit",
                 "merge_candidate"}
    assert exported.isdisjoint(forbidden)
    for name in forbidden:
        assert not hasattr(attempt_mod, name)
    assert not hasattr(TaskAttempt, "apply")
    assert not hasattr(TaskAttempt, "promote")


# --------------------------------------------------------------------------- #
# misc contracts                                                               #
# --------------------------------------------------------------------------- #
def test_runner_is_required_and_never_implicit():
    with pytest.raises(ValueError) as e:
        TaskAttempt(spec(), runner=None)
    assert "explicit runner" in str(e.value)


def test_task_digest_is_stable_and_content_derived():
    assert spec().digest == spec().digest
    assert spec().digest != spec(instruction="something else").digest


def test_default_gate_argv_targets_the_requested_subset():
    argv = pytest_gate_argv(["tests/test_a.py", "tests/test_b.py"])
    assert argv[1:3] == ("-m", "pytest")
    assert "tests/test_a.py" in argv and "tests/test_b.py" in argv
    assert "-p" in argv and "no:cacheprovider" in argv


def _command_gate_context(worktree, *, is_cancelled=lambda: False):
    return RunnerContext(
        worktree=worktree,
        branch="gate-test",
        base_revision="0" * 40,
        task=spec(),
        is_cancelled=is_cancelled,
    )


def test_command_gate_runs_arbitrary_argv_in_worktree_and_records_evidence(
        tmp_path):
    worktree = tmp_path / "candidate"
    worktree.mkdir()
    (worktree / "where.txt").write_text("inside\n", encoding="utf-8")
    argv = (
        sys.executable,
        "-c",
        "from pathlib import Path; "
        "print(Path.cwd().name); "
        "print(Path('where.txt').read_text().strip())",
    )

    verdict = command_gate(
        argv, executes_candidate=False, name="python-build", poll_s=0.01
    )(_command_gate_context(worktree))

    assert verdict.passed is True, verdict.output
    assert verdict.command == argv
    assert verdict.name == "python-build"
    assert verdict.returncode == 0
    assert verdict.output.splitlines() == ["candidate", "inside"]
    assert verdict.summary()["command"] == list(argv)
    assert verdict.summary()["output_sha256"] == verdict.output_sha256
    assert verdict.containment is not None
    assert verdict.containment.requested is False
    assert verdict.containment.executes_candidate is False
    assert verdict.containment.contained is False


@pytest.mark.parametrize(
    ("program", "expected_returncode", "expected_output"),
    [
        ("print('not green'); raise SystemExit(7)", 7, "not green"),
        ("pass", 0, "NO output"),
    ],
)
def test_command_gate_rejects_nonzero_and_empty_green(
        tmp_path, program, expected_returncode, expected_output):
    worktree = tmp_path / "candidate"
    worktree.mkdir()

    verdict = command_gate(
        (sys.executable, "-c", program),
        executes_candidate=False,
        poll_s=0.01,
    )(_command_gate_context(worktree))

    assert verdict.passed is False
    assert verdict.returncode == expected_returncode
    assert expected_output in verdict.output


class _PendingGateProcess:
    """Deterministic process double for cancel/deadline polling."""

    def __init__(self, argv, *, cwd, stdout, stderr):
        self.argv = tuple(argv)
        self.cwd = cwd
        self._returncode = None
        stdout.write(b"gate started\n")
        stdout.flush()

    def poll(self):
        return self._returncode

    @property
    def returncode(self):
        return self._returncode

    def cancel(self):
        self._returncode = 137

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


@pytest.mark.parametrize(
    ("cancelled", "timeout_s", "expected_field"),
    [
        (True, 60.0, "cancelled"),
        (False, -1.0, "timed_out"),
    ],
)
def test_command_gate_preserves_cancel_and_timeout_semantics(
        tmp_path, monkeypatch, cancelled, timeout_s, expected_field):
    from daedalus.spine import cancel as cancel_mod

    monkeypatch.setattr(cancel_mod, "ManagedProcess", _PendingGateProcess)
    worktree = tmp_path / "candidate"
    worktree.mkdir()

    verdict = command_gate(
        ("builder", "--check"),
        executes_candidate=False,
        timeout_s=timeout_s,
        poll_s=0,
    )(_command_gate_context(worktree, is_cancelled=lambda: cancelled))

    assert verdict.passed is False
    assert getattr(verdict, expected_field) is True
    assert verdict.returncode == 137
    assert verdict.command == ("builder", "--check")


def test_command_gate_records_effective_containment_attestation(
        tmp_path, monkeypatch):
    from daedalus.spine.containment import ContainmentAttestation

    attestation = ContainmentAttestation(
        requested=True,
        executes_candidate=True,
        contained=True,
        platform=sys.platform,
        mechanism="test-low-integrity",
        token_integrity_sid="S-1-16-4096",
        worktree_label="S-1-16-4096",
        inherited_handle_count=1,
    )

    class _ContainedProcess:
        returncode = 0

        def __init__(self):
            self.attestation = attestation

        def poll(self):
            return 0

        def cancel(self):
            raise AssertionError("completed child must not be cancelled")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    class _Log:
        def close(self):
            return None

    seen = {}

    def _contained(argv, worktree, out_path, tmpdir):
        seen["argv"] = tuple(argv)
        seen["worktree"] = worktree
        out_path.write_text("contained build passed\n", encoding="utf-8")
        return _ContainedProcess(), _Log()

    monkeypatch.setattr(attempt_mod, "_contained_gate_child", _contained)
    worktree = tmp_path / "candidate"
    worktree.mkdir()
    argv = ("npm", "run", "build")

    verdict = command_gate(argv)(_command_gate_context(worktree))

    assert verdict.passed is True
    assert verdict.command == argv
    assert seen == {"argv": argv, "worktree": worktree}
    assert verdict.containment is attestation
    block = verdict.summary()["containment"]
    assert block["requested"] is True
    assert block["executes_candidate"] is True
    assert block["contained"] is True
    assert block["mechanism"] == "test-low-integrity"
    assert block["inherited_handle_count"] == 1


def test_pytest_gate_is_a_thin_command_gate_wrapper(monkeypatch):
    sentinel = object()
    calls = []

    def _command_gate(argv, **kwargs):
        calls.append((argv, kwargs))
        return sentinel

    monkeypatch.setattr(attempt_mod, "command_gate", _command_gate)

    result = attempt_mod.pytest_gate(
        ["tests/test_a.py"],
        timeout_s=12,
        poll_s=0.5,
        name="suite",
        executes_candidate=False,
    )

    assert result is sentinel
    assert calls == [(
        pytest_gate_argv(["tests/test_a.py"]),
        {
            "timeout_s": 12,
            "poll_s": 0.5,
            "name": "suite",
            "executes_candidate": False,
        },
    )]


def test_gate_selection_wires_correctness_gate_when_fail_to_pass_is_set(
        monkeypatch, repo, worktree_root):
    """No explicit gate=, no gate_argv: fail_to_pass/pass_to_pass on the
    TaskSpec must select daedalus.eval.correctness.correctness_gate, called
    with a minimal task dict built from exactly those fields plus
    base_revision/correctness_before_state -- never re-derived, never
    silently ignored. Imported lazily inside __init__ (see the comment
    there), so it is monkeypatched on the SOURCE module, not attempt_mod.
    """
    import daedalus.eval.correctness as correctness_mod

    sentinel = object()
    calls = []

    def _correctness_gate(task, repo_root, **kwargs):
        calls.append((task, repo_root, kwargs))
        return sentinel

    monkeypatch.setattr(correctness_mod, "correctness_gate", _correctness_gate)

    task = spec(
        base_revision="deadbeef",
        fail_to_pass=("tests/test_a.py::test_x",),
        pass_to_pass=("tests/test_b.py::test_y",),
        correctness_before_state={"verified": True, "base_revision": "deadbeef",
                                  "selection_digest": "abc123"},
        gate_timeout_s=42.0,
    )
    at = TaskAttempt(task, runner=writing_runner({"a.txt": "a\n"}), repo_root=repo)

    assert at._gate is sentinel
    assert len(calls) == 1
    called_task, called_repo_root, called_kwargs = calls[0]
    assert called_task == {
        "id": "demo-task",
        "base_revision": "deadbeef",
        "fail_to_pass": ["tests/test_a.py::test_x"],
        "pass_to_pass": ["tests/test_b.py::test_y"],
        "before_state": {"verified": True, "base_revision": "deadbeef",
                         "selection_digest": "abc123"},
    }
    assert called_repo_root == Path(repo).resolve()
    assert called_kwargs == {"timeout_s": 42.0}


def test_gate_argv_still_wins_over_fail_to_pass_when_both_are_set(
        monkeypatch, repo, worktree_root):
    """Precedence is explicit gate > gate_argv > correctness > pytest_gate --
    a TaskSpec that (perhaps by accident) carries both gate_argv and
    fail_to_pass gets the explicit command, never a silent correctness
    substitution."""
    import daedalus.eval.correctness as correctness_mod

    correctness_calls = []

    def _correctness_gate(*a, **k):
        correctness_calls.append(1)
        return object()

    monkeypatch.setattr(correctness_mod, "correctness_gate", _correctness_gate)

    sentinel = object()
    command_calls = []

    def _command_gate(argv, **kwargs):
        command_calls.append((argv, kwargs))
        return sentinel

    monkeypatch.setattr(attempt_mod, "command_gate", _command_gate)

    task = spec(gate_argv=("echo", "hi"),
               fail_to_pass=("tests/test_a.py::test_x",))
    at = TaskAttempt(task, runner=writing_runner({"a.txt": "a\n"}), repo_root=repo)

    assert at._gate is sentinel
    assert command_calls and command_calls[0][0] == ("echo", "hi")
    assert correctness_calls == []


def test_absent_fail_to_pass_leaves_the_plain_pytest_gate_untouched(
        monkeypatch, repo, worktree_root):
    """The regression check: a TaskSpec that never mentions fail_to_pass/
    pass_to_pass (every candidate before this feature existed, and every one
    after it that does not opt in) must select pytest_gate(gate_paths) exactly
    as before -- correctness_gate must not even be consulted."""
    import daedalus.eval.correctness as correctness_mod

    def _must_not_be_called(*a, **k):
        raise AssertionError("correctness_gate must not be consulted when "
                             "fail_to_pass/pass_to_pass are both empty")

    monkeypatch.setattr(correctness_mod, "correctness_gate", _must_not_be_called)

    sentinel = object()
    calls = []

    def _pytest_gate(paths, **kwargs):
        calls.append((paths, kwargs))
        return sentinel

    monkeypatch.setattr(attempt_mod, "pytest_gate", _pytest_gate)

    task = spec(gate_paths=("tests/test_a.py",))
    at = TaskAttempt(task, runner=writing_runner({"a.txt": "a\n"}), repo_root=repo)

    assert at._gate is sentinel
    assert calls == [(("tests/test_a.py",), {})]


def test_gate_returning_a_bare_bool_is_accepted_and_says_so(repo, worktree_root,
                                                            ledger):
    head = head_of(repo)
    result = TaskAttempt(spec(), runner=writing_runner({"a.txt": "a\n"}),
                         gate=lambda ctx: True, repo_root=repo,
                         ledger=ledger).run()
    assert result.state == STATE_CLEAN
    assert result.gates.passed is True
    assert "no output" in result.gates.output
    assert_primary_untouched(repo, head)


def test_a_raising_gate_fails_closed(repo, worktree_root, ledger):
    head = head_of(repo)

    def exploding_gate(ctx):
        raise RuntimeError("pytest could not start")

    result = TaskAttempt(spec(), runner=writing_runner({"a.txt": "a\n"}),
                         gate=exploding_gate, repo_root=repo, ledger=ledger).run()

    assert result.state == STATE_GATES_FAILED
    assert "pytest could not start" in result.gates.output
    assert_primary_untouched(repo, head)


def test_result_to_dict_is_json_safe_and_omits_the_full_gate_log(
        repo, worktree_root, ledger):
    import json

    head = head_of(repo)
    raw = "x" * (attempt_mod.GATE_OUTPUT_TAIL_CHARS + 500)
    result = TaskAttempt(spec(), runner=writing_runner({"a.txt": "a\n"}),
                         gate=gate_returning(GateResult(passed=True, output=raw)),
                         repo_root=repo, ledger=ledger).run()

    payload = json.loads(json.dumps(result.to_dict()))
    assert payload["state"] == STATE_CLEAN
    assert payload["gates"]["output_truncated"] is True
    assert len(payload["gates"]["output_tail"]) == attempt_mod.GATE_OUTPUT_TAIL_CHARS
    assert payload["gates"]["output_sha256"] == result.gates.output_sha256
    assert payload["artifact"]["diff_sha256"] == result.artifact.diff_sha256
    assert_primary_untouched(repo, head)


def test_artifact_is_persisted_only_when_a_directory_is_given(
        repo, worktree_root, ledger, tmp_path):
    head = head_of(repo)
    out_dir = tmp_path / "patches"

    off = TaskAttempt(spec(), runner=writing_runner({"a.txt": "a\n"}),
                      gate=passing_gate(), repo_root=repo, ledger=ledger).run()
    assert off.artifact_path is None
    assert not out_dir.exists()

    on = TaskAttempt(spec(), runner=writing_runner({"a.txt": "a\n"}),
                     gate=passing_gate(), repo_root=repo, ledger=ledger,
                     artifact_dir=out_dir).run()
    assert on.artifact_path is not None
    written = Path(on.artifact_path)
    assert written.read_bytes() == on.artifact.diff_bytes
    assert written.name == f"{on.artifact.diff_sha256}.patch"
    assert repo.resolve() not in written.resolve().parents

    assert_primary_untouched(repo, head)
