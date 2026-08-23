"""The evaluator-assurance seal, and the three bindings that hold a set together.

WHAT WAS WRONG. ``daedalus.spine.receipts.evaluator_assurance`` granted a gate
verdict the word ``deterministic`` whenever the task's declared
``gate_criterion_paths`` did not appear, as raw strings, in its declared
``target_paths``. Raw strings, so every one of ``tests/../tests/test_gate.py``,
``.//tests/test_gate.py`` and ``Tests/Test_Gate.py`` compared "disjoint" from a
scope containing ``tests/test_gate.py`` -- while containment happily let the
candidate write that exact file. A candidate could therefore overwrite the test
that judged it with ``print('PASS')`` and mint a ``deterministic``/``passed``
EvidencePacket, which is a packet the promotion path accepts. A criterion naming
a file that does not exist, and a task that declared no write scope at all, both
read as sealed too.

THE TESTS RUN THE REAL PATH. Every case below goes through a real
:class:`~daedalus.spine.attempt.TaskAttempt` against a real git repository,
because the two halves of this fix live in two modules -- the tree measurement
in ``attempt.py``, the judgement in ``receipts.py`` -- and a unit test of either
half alone would pass with the wiring between them cut. That failure mode is
not hypothetical: the first version of the presence probe pinned git to the
attempt's own worktree admin directory, which ``_cleanup`` had already removed,
so every criterion read as absent and every seal correctly refused. Only the
end-to-end run caught it.
"""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from daedalus.schemas import ResourceBudget, ResourceUsage  # noqa: E402
from daedalus.spine.attempt import (  # noqa: E402
    GateResult,
    TaskAttempt,
    TaskSpec,
)
from daedalus.spine.receipts import (  # noqa: E402
    AttemptContractSet,
    METERED_INPUT_REASON,
    UNMETERED_SPEND_REASON,
    adapter_identity,
    canonicalise_attempt,
    evaluator_assurance_detail,
)

#: What a gate that really runs the criterion records as its command.
GATE_COMMAND = ("python", "-m", "pytest", "tests/test_gate.py")


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path):
    """A base revision holding a regular criterion file AND a symlink one."""
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir(parents=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "assurance@example.com")
    _git(root, "config", "user.name", "assurance")
    (root / "src" / "foo.py").write_text("def answer():\n    return 0\n")
    # A second subject, in the same directory, that NOTHING on the criterion's
    # import surface reaches. It exists because ``src/foo.py`` is not a
    # genuinely disjoint write scope and never was: ``tests/test_gate.py``
    # imports it through the ``sys.path`` insertion below, and until the import
    # resolver could see through that insertion the tests here read "disjoint"
    # off a blind spot instead of off the tree.
    (root / "src" / "other.py").write_text("NOTE = 'not on any import path'\n")
    (root / "tests" / "test_gate.py").write_text(
        "import pathlib, sys\n"
        "sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src'))\n"
        "from foo import answer\n"
        "assert answer() == 42, 'criterion FAILS'\n")
    # A sibling the criterion's execution never touches, and a criterion whose
    # judging code lives in an in-tree module beside it. Both are base-revision
    # facts, so the import resolver has something real to confirm against.
    (root / "tests" / "test_other.py").write_text("assert True\n")
    (root / "tests" / "helpers.py").write_text(
        "def check(v):\n    assert v == 42, 'helper FAILS'\n")
    (root / "tests" / "test_helped.py").write_text(
        "import pathlib, sys\n"
        "sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src'))\n"
        "from helpers import check\n"
        "from foo import answer\n"
        "check(answer())\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    # A symlink tree entry, written straight into the index so the fixture does
    # not depend on the host filesystem allowing one. Its blob content is the
    # path it points at -- a path INSIDE the candidate's write scope, which is
    # the whole reason a symlink criterion seals nothing.
    blob = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"], cwd=root,
        input="../src/foo.py", capture_output=True, text=True,
        check=True).stdout.strip()
    _git(root, "update-index", "--add", "--cacheinfo", "120000", blob,
         "tests/link_gate.py")
    _git(root, "commit", "-q", "-m", "a symlink that looks like a criterion")
    return root


def _base(repo):
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _cheat(ctx):
    """Rewrite the criterion instead of fixing the code it judges."""
    (ctx.worktree / "tests" / "test_gate.py").write_text("assert True\n")
    return {"note": "rewrote the criterion"}


def _honest(ctx):
    (ctx.worktree / "src" / "foo.py").write_text("def answer():\n    return 42\n")
    return {"note": "fixed the code"}


def _honest_other(ctx):
    """Write the subject the criterion does NOT import."""
    (ctx.worktree / "src" / "other.py").write_text("NOTE = 'edited'\n")
    return {"note": "edited a file no criterion imports"}


def _green_gate(ctx):
    return GateResult(passed=True, name="probe-gate", command=GATE_COMMAND,
                      returncode=0, output="green\n", duration_s=0.1)


def tmp_path_for(repo):
    """A scratch directory beside the fixture repo, for tests without tmp_path."""
    scratch = Path(repo).parent / "scratch"
    scratch.mkdir(exist_ok=True)
    return scratch


def _run(repo, tmp_path, label, *, target_paths, criterion,
         runner=_cheat, gate=_green_gate, gate_reads_scope=False, **kwargs):
    spec = TaskSpec(task_id=f"assurance-{label}", instruction="make it green",
                    base_revision=_base(repo), target_paths=target_paths,
                    gate_criterion_paths=criterion, gate_timeout_s=60.0,
                    gate_reads_scope=gate_reads_scope)
    attempt = TaskAttempt(spec, runner=runner, gate=gate, repo_root=repo,
                          ledger_path=tmp_path / f"spine-{label}.sqlite3",
                          artifact_dir=tmp_path / f"store-{label}",
                          mission_id=f"mission-{label}", reap=False,
                          budget=ResourceBudget(max_wall_time_s=120), **kwargs)
    result = attempt.run()
    return attempt, result, result.contract_set()


def _assurance(contracts):
    return contracts.evidence.items[0].assurance


def _why(contracts):
    reasons = [r for r in contracts.policy.reasons
               if r.startswith("evaluator assurance")]
    assert reasons, "the derivation must record WHY, not just the verdict"
    return reasons[0]


# --------------------------------------------------------------------------- #
# 1. the spelling attacks                                                      #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("label,criterion,expected_reason", [
    # These two are the SAME path as the write target on every host, so the
    # scope comparison is what must catch them. The reason is asserted, not just
    # the verdict: the base-revision presence check would also refuse these
    # spellings (git cannot resolve `tests/..` either), so a test that only read
    # the verdict would still pass with the normalisation deleted -- measured,
    # not guessed. Pinning the sentence is what makes this test fail when the
    # guard it is named after is the one that goes away.
    ("dotdot", "tests/../tests/test_gate.py", "INSIDE the declared write scope"),
    ("dotslash", ".//tests/test_gate.py", "INSIDE the declared write scope"),
    # On a case-insensitive host this is one file with the write target and the
    # scope check refuses it; on a case-sensitive host it is a different file
    # that the base tree does not contain, and the presence check refuses it.
    # Two guards, one outcome, so only the outcome is portable.
    ("case", "Tests/Test_Gate.py", None),
])
def test_a_respelled_criterion_inside_the_write_scope_is_not_sealed(
        repo, tmp_path, label, criterion, expected_reason):
    """The three spellings that all name the file the candidate may write.

    Each one used to read ``deterministic`` while the candidate overwrote the
    criterion with a trivially passing file, producing a green packet the
    promotion path accepts.
    """
    _, result, contracts = _run(
        repo, tmp_path, label,
        target_paths=("tests/test_gate.py",), criterion=(criterion,))

    assert result.state == "clean"
    assert result.gates.passed
    assert list(result.artifact.changed_paths) == ["tests/test_gate.py"]
    assert _assurance(contracts) == "unverified"
    assert contracts.evidence.evaluation_status == "inconclusive"
    assert contracts.receipt.outcome == "inconclusive"
    if expected_reason:
        assert expected_reason in _why(contracts)


def test_a_criterion_that_is_not_in_the_base_tree_seals_nothing(repo, tmp_path):
    _, _, contracts = _run(
        repo, tmp_path, "ghost",
        target_paths=("tests/test_gate.py",), criterion=("z.txt",))

    assert _assurance(contracts) == "unverified"
    assert "not a regular file in the base revision tree" in _why(contracts)


def test_a_symlink_criterion_seals_nothing(repo, tmp_path):
    """A symlink is a blob whose bytes are a path, and that path is writable.

    ``tests/link_gate.py`` points at ``src/foo.py``, which the task declares as
    its write scope -- so the candidate changes what the criterion says by
    writing a file it is allowed to write. A bare existence check passes this;
    reading the tree ENTRY's mode is what refuses it.
    """
    _, _, contracts = _run(
        repo, tmp_path, "symlink", runner=_honest,
        target_paths=("src/foo.py",), criterion=("tests/link_gate.py",))

    assert _assurance(contracts) == "unverified"
    assert "not a regular file in the base revision tree" in _why(contracts)


def test_an_empty_write_scope_seals_nothing(repo, tmp_path):
    """No target_paths means containment was never armed (finding 2).

    ``canonicalise_attempt`` refuses an unbounded write scope before it ever
    reaches the evidence packet, so the assurance is asserted directly here --
    the refusal and the seal are two independent guards and this test is about
    the second one.
    """
    task = TaskSpec(task_id="unarmed", instruction="i", base_revision="0" * 40,
                    target_paths=(), gate_criterion_paths=("tests/test_gate.py",))
    result = type("R", (), {"gates": GateResult(passed=True, name="g",
                                                command=GATE_COMMAND)})()

    verdict, why = evaluator_assurance_detail(
        result, task, criterion_present={"tests/test_gate.py": True})

    assert verdict == "unverified"
    assert "NO target_paths" in why


# --------------------------------------------------------------------------- #
# 1b. the criterion FILE was never the criterion                               #
#                                                                              #
# Checks 1-4 above all measure the criterion as a BLOB. A candidate that never  #
# touches that blob still changes what it DOES by writing a file python or      #
# pytest loads on the way to it -- a conftest.py beside it, a root config, an   #
# __init__.py on its package path -- or by rewriting an in-tree module the      #
# criterion imports. Every case below leaves the criterion byte-identical and   #
# still must not read `deterministic`.                                          #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("label,in_scope", [
    # beside the criterion: fixtures, hooks, assertion rewriting, collect_ignore
    ("conftest", "tests/conftest.py"),
    # the criterion's own package path
    ("pkginit", "tests/__init__.py"),
    # the repository root, which no "is the criterion inside the scope" test
    # can see, because the criterion is not inside a file
    ("pyproject", "pyproject.toml"),
    ("pytestini", "pytest.ini"),
    ("setupcfg", "setup.cfg"),
    ("toxini", "tox.ini"),
    # executed by CPython before anything the criterion says
    ("sitecustomize", "sitecustomize.py"),
    ("pth", "tests/evil.pth"),
])
def test_an_execution_influencing_file_in_scope_breaks_the_seal(
        repo, tmp_path, label, in_scope):
    """The write scope reaches the criterion's execution, not its bytes."""
    _, result, contracts = _run(
        repo, tmp_path, f"influence-{label}", runner=_honest_other,
        target_paths=("src/other.py", in_scope),
        criterion=("tests/test_gate.py",))

    assert result.state == "clean", result.error
    assert list(result.artifact.changed_paths) == ["src/other.py"]
    assert _assurance(contracts) == "unverified"
    # The reason NAMES the file, because a receipt whose refusal cannot be
    # triaged back to one declaration is a refusal nobody can act on.
    why = _why(contracts)
    assert repr(in_scope) in why
    assert "execution-influencing file" in why


def test_a_sibling_that_influences_nothing_still_seals(repo, tmp_path):
    """The guard above must refuse a mechanism, not a directory.

    ``tests/test_other.py`` sits beside the criterion and is nonetheless loaded
    by nothing on the criterion's path. Refusing it too would make the seal
    unreachable for any task whose scope touches the test tree at all, which is
    a guard that closes the hole by breaking the feature.
    """
    _, _, contracts = _run(
        repo, tmp_path, "sibling-neutral", runner=_honest_other,
        target_paths=("src/other.py", "tests/test_other.py"),
        criterion=("tests/test_gate.py",))

    assert _assurance(contracts) == "deterministic"


def test_an_in_tree_module_the_criterion_imports_breaks_the_seal(
        repo, tmp_path):
    """The criterion's judging code moved into a file the candidate may write.

    ``tests/test_helped.py`` does ``from helpers import check`` and
    ``tests/helpers.py`` holds the assertion. The criterion file is untouched
    and present in the base tree, the gate names it, and the verdict is still
    worth nothing: ``check`` is candidate-authored.
    """
    def gate(ctx):
        return GateResult(passed=True, name="probe-gate", returncode=0,
                          command=("pytest", "tests/test_helped.py"),
                          output="green\n", duration_s=0.1)

    def runner(ctx):
        (ctx.worktree / "tests" / "helpers.py").write_text(
            "def check(v):\n    return True\n", encoding="utf-8")

    _, result, contracts = _run(
        repo, tmp_path, "import-in-scope", runner=runner, gate=gate,
        target_paths=("tests/helpers.py",),
        criterion=("tests/test_helped.py",))

    assert result.state == "clean", result.error
    assert _assurance(contracts) == "unverified"
    why = _why(contracts)
    assert "imports 'tests/helpers.py'" in why
    assert "INSIDE the declared write scope" in why


def test_a_sys_path_insertion_no_longer_hides_an_import_of_the_scope(
        repo, tmp_path):
    """THE TEST THIS CHANGE REVERSES, and the finding it records.

    It used to read ``test_an_import_that_resolves_to_nothing_in_the_tree_does_
    not_refuse`` and it asserted ``deterministic``: ``tests/test_gate.py``
    reaches ``src/foo.py`` -- the file the task declares as its write scope --
    through ``sys.path.insert(0, ROOT / 'src')``, the line regex could not
    resolve it, and "resolved to nothing" was scored as "imports nothing inside
    the scope". The criterion's assertion runs ``answer()``, which the candidate
    wrote, so that ``deterministic`` was a false grant produced by not looking.

    The same fixture, the same declaration, and now the refusal names the file.
    """
    _, _, contracts = _run(
        repo, tmp_path, "import-via-syspath", runner=_honest,
        target_paths=("src/foo.py",), criterion=("tests/test_gate.py",))

    assert _assurance(contracts) == "unverified"
    why = _why(contracts)
    assert "imports 'src/foo.py'" in why
    assert "INSIDE the declared write scope" in why


def test_the_same_import_seals_when_the_task_declares_it_a_conformance_test(
        repo, tmp_path):
    """A FAIL_TO_PASS test imports the code under test BY DESIGN.

    Refusing every criterion that reaches its own subject would leave the seal
    available only to criteria that judge nothing, so the import of the scope is
    allowed -- when the task SAYS SO, in a field inside its own digest. The
    reason then records how much of what judged the candidate the candidate
    wrote, instead of a sentence that cannot tell the two situations apart.
    """
    _, _, contracts = _run(
        repo, tmp_path, "import-declared", runner=_honest,
        target_paths=("src/foo.py",), criterion=("tests/test_gate.py",),
        gate_reads_scope=True)

    assert _assurance(contracts) == "deterministic"
    assert "conformance test reads its own scope by declaration" in _why(contracts)


def test_unmeasured_imports_do_not_grant_the_seal():
    """Not knowable is not a pass, for this check like every other one here."""
    task = TaskSpec(task_id="unmeasured", instruction="i",
                    base_revision="0" * 40, target_paths=("src/foo.py",),
                    gate_criterion_paths=("tests/test_gate.py",))
    result = type("R", (), {"gates": GateResult(passed=True, name="g",
                                                command=GATE_COMMAND)})()

    verdict, why = evaluator_assurance_detail(
        result, task, criterion_present={"tests/test_gate.py": True})

    assert verdict == "unverified"
    assert "were not resolved against the base revision tree" in why


@pytest.mark.parametrize("source,expected", [
    ("from helpers import check\n", "tests/helpers.py"),
    ("import helpers\n", "tests/helpers.py"),
    ("from . import helpers\n", "tests/helpers.py"),
    ("from .helpers import check\n", "tests/helpers.py"),
    ("from tests.helpers import check\n", "tests/helpers.py"),
    # the src/ layout, which the line regex this replaced could not see at all
    ("from foo import answer\n", "src/foo.py"),
    # and the same module reached by a dynamic call with a literal name
    ("import importlib\nimportlib.import_module('foo')\n", "src/foo.py"),
])
def test_the_import_reader_names_the_files_an_import_would_execute(
        repo, source, expected):
    """The resolver reads the tree, so the fixture repo is the input.

    The predecessor of this test asserted over a pure ``(source, criterion)``
    function and therefore could only ever check the two roots that function
    guessed. Everything below resolves against the real base revision, which is
    what makes ``src/foo.py`` an answer at all.
    """
    from daedalus.spine.attempt import GateResult, TaskAttempt, TaskSpec
    from daedalus.spine.receipts import import_surface_plan, resolve_import_plan

    base = _base(repo)
    criterion = "tests/test_gate.py"
    spec = TaskSpec(task_id="reader", instruction="i", base_revision=base,
                    target_paths=("src/foo.py",),
                    gate_criterion_paths=(criterion,))
    attempt = TaskAttempt(
        spec, runner=lambda ctx: None,
        gate=lambda ctx: GateResult(passed=True, name="g", command=()),
        repo_root=repo, ledger_path=tmp_path_for(repo) / "reader.sqlite3",
        artifact_dir=tmp_path_for(repo) / "reader-store",
        mission_id="reader", reap=False)
    listings = {}
    roots, _reasons = attempt._import_roots(base, criterion, source, listings)
    plan = import_surface_plan(source, criterion, roots=roots,
                               package_root=attempt._owning_root(criterion, roots),
                               package="")
    surface = resolve_import_plan(
        plan, attempt._tree_kinds(base, plan.probes, listings))

    assert expected in [path for _key, path, _root in surface.files]


# --------------------------------------------------------------------------- #
# 2. the seal still works when it is honestly earned                           #
# --------------------------------------------------------------------------- #
def test_a_genuinely_disjoint_criterion_still_reads_deterministic(repo, tmp_path):
    """GENUINELY disjoint, which ``src/foo.py`` never was.

    ``src/other.py`` is on no import path of ``tests/test_gate.py``, so the
    resolver walks the criterion's whole surface -- ``src/foo.py`` included --
    and still finds nothing inside the scope. That is the seal earned by
    measurement rather than by a gap in the measurement.
    """
    _, result, contracts = _run(
        repo, tmp_path, "honest", runner=_honest_other,
        target_paths=("src/other.py",), criterion=("tests/test_gate.py",))

    assert result.state == "clean"
    assert _assurance(contracts) == "deterministic"
    assert contracts.evidence.evaluation_status == "passed"
    assert contracts.receipt.outcome == "passed"


def test_the_gate1_node_id_shape_still_reads_deterministic(repo, tmp_path):
    """``daedalus.ignition.gate1.code_type_gate``'s exact shape.

    An INJECTED gate callable, so the task declares no ``gate_argv`` at all,
    and a recorded command naming the criterion as a pytest node id rather than
    as a bare path. The Gate-1 ignition slice is the only production producer of
    ``gate_criterion_paths``, so a hardening that took its seal away would have
    closed the hole by breaking the feature.
    """
    def node_id_gate(ctx):
        return GateResult(
            passed=True, name="ignition-code-type",
            command=("python", "-m", "pytest",
                     "tests/test_gate.py::test_type_exposes_the_renamed_field"),
            returncode=0, output="1 passed\n", duration_s=0.1)

    _, _, contracts = _run(
        repo, tmp_path, "nodeid", runner=_honest_other, gate=node_id_gate,
        target_paths=("src/other.py",), criterion=("tests/test_gate.py",))

    assert _assurance(contracts) == "deterministic"


def test_a_gate_that_never_names_the_criterion_seals_nothing(repo, tmp_path):
    def elsewhere_gate(ctx):
        return GateResult(passed=True, name="probe-gate",
                          command=("python", "-m", "pytest", "tests/other.py"),
                          returncode=0, output="green\n", duration_s=0.1)

    _, _, contracts = _run(
        repo, tmp_path, "unread", runner=_honest_other, gate=elsewhere_gate,
        target_paths=("src/other.py",), criterion=("tests/test_gate.py",))

    assert _assurance(contracts) == "unverified"
    assert "never names" in _why(contracts)


def test_an_unknowable_gate_command_does_not_grant_the_seal(repo, tmp_path):
    def silent_gate(ctx):
        return GateResult(passed=True, name="probe-gate", command=(),
                          returncode=0, output="green\n", duration_s=0.1)

    _, _, contracts = _run(
        repo, tmp_path, "silent", runner=_honest_other, gate=silent_gate,
        target_paths=("src/other.py",), criterion=("tests/test_gate.py",))

    assert _assurance(contracts) == "unverified"
    assert "not knowable" in _why(contracts)


@pytest.mark.parametrize("criterion,command,mentioned", [
    # A bare `in` test grants the seal for `a.py` whenever any argument holds
    # `data.py`, and a false grant here IS a false `deterministic`.
    ("a.py", ("python", "-m", "pytest", "data.py"), False),
    ("a.py", ("python", "-m", "pytest", "a.py"), True),
    ("tests/test_gate.py", ("pytest", "tests/xtest_gate.py"), False),
    ("tests/test_gate.py", ("pytest", "tests/test_gate.py::test_x"), True),
    # A gate invoked with an absolute path into the worktree names the same
    # file, even though an absolute DECLARATION has no normal form.
    ("tests/test_gate.py", ("pytest", "C:/wt/tests/test_gate.py"), True),
    ("tests/test_gate.py", ("pytest", "--rootdir=. tests/test_gate.py"), True),
])
def test_the_gate_command_is_matched_on_path_boundaries(
        criterion, command, mentioned):
    from daedalus.spine.receipts import _gate_mentions

    assert _gate_mentions(criterion, command) is mentioned


@pytest.mark.parametrize("criterion", ["../outside.py", "C:/tmp/test_gate.py",
                                       "/etc/passwd"])
def test_a_criterion_that_escapes_the_tree_is_refused_outright(criterion):
    """TWO guards now, and the outer one fires first.

    The declaration is refused where it is WRITTEN (``TaskSpec.__post_init__``),
    so no such spec reaches the seal, the digest, the picker's pre-check, or a
    runner's ``paths`` argument at all. The seal keeps its own refusal for the
    duck-typed task objects it is documented to accept, asserted below -- a
    guard that only holds because another guard holds is a guard that
    disappears the first time the outer one moves.
    """
    from daedalus.spine.attempt import TaskSpecInvalid

    with pytest.raises(TaskSpecInvalid) as refusal:
        TaskSpec(task_id="escape", instruction="i", base_revision="0" * 40,
                 target_paths=("src/foo.py",), gate_criterion_paths=(criterion,))
    assert repr(criterion) in str(refusal.value)

    task = type("T", (), {"gate_criterion_paths": (criterion,),
                          "target_paths": ("src/foo.py",),
                          "gate_argv": (), "fail_to_pass": (),
                          "pass_to_pass": (), "gate_reads_scope": False})()
    result = type("R", (), {"gates": GateResult(passed=True, name="g",
                                                command=GATE_COMMAND)})()

    verdict, why = evaluator_assurance_detail(result, task, criterion_present={})

    assert verdict == "unverified"
    assert "no normal form inside the tree" in why


# --------------------------------------------------------------------------- #
# 3. the set's own bindings                                                    #
# --------------------------------------------------------------------------- #
def test_a_swapped_contract_refuses_to_reconstruct(repo, tmp_path):
    """Two attempts' parts do not recombine into one plausible record.

    Each contract's own ``from_dict`` validates that contract in isolation, so
    a shuffled row is five well-formed contracts that do not belong together --
    exactly what ``read_contract_set`` would hand a promotion path.
    """
    _, first, _ = _run(repo, tmp_path, "bind-a", runner=_honest,
                       target_paths=("src/foo.py",),
                       criterion=("tests/test_gate.py",))
    _, second, _ = _run(repo, tmp_path, "bind-b", runner=_honest,
                        target_paths=("src/foo.py",),
                        criterion=("tests/test_gate.py",))

    assert AttemptContractSet.from_dict(first.contracts).complete

    swapped = dict(first.contracts)
    swapped["evidence"] = second.contracts["evidence"]
    with pytest.raises(ValueError, match="not internally bound"):
        AttemptContractSet.from_dict(swapped)

    swapped = dict(first.contracts)
    swapped["policy"] = second.contracts["policy"]
    with pytest.raises(ValueError, match="not internally bound"):
        AttemptContractSet.from_dict(swapped)

    swapped = dict(first.contracts)
    swapped["receipt"] = second.contracts["receipt"]
    with pytest.raises(ValueError, match="not internally bound"):
        AttemptContractSet.from_dict(swapped)


def test_a_partial_set_still_reconstructs(repo, tmp_path):
    """The mint legitimately returns fewer than five contracts and a reason."""
    assert AttemptContractSet.from_dict({"error": "refused"}).error == "refused"


# --------------------------------------------------------------------------- #
# 4. one policy text per chain                                                 #
# --------------------------------------------------------------------------- #
def test_a_mission_policy_digest_that_disagrees_refuses_the_projection(
        repo, tmp_path):
    attempt, result, contracts = _run(
        repo, tmp_path, "policy", runner=_honest,
        target_paths=("src/foo.py",), criterion=("tests/test_gate.py",))
    assert contracts.complete

    locator, error = attempt._persist_gate_output(
        result.gates, result.base_revision, result.finished_ts)
    assert locator, error

    def _project(mission_policy_sha256):
        return canonicalise_attempt(
            result, task=attempt.task, mission_id=attempt.mission_id,
            attempt_id=attempt.attempt_id, base_revision=result.base_revision,
            adapter_id=adapter_identity(attempt._runner),
            evidence_locator=locator, budget=attempt.budget,
            usage=ResourceUsage(wall_time_ms=1), created_at=result.finished_ts,
            boundary_receipt=attempt._boundary_receipt,
            mission_policy_sha256=mission_policy_sha256)

    from daedalus.spine.effect_boundary import registry_sha256

    agreeing = _project(registry_sha256())
    assert agreeing.complete
    # The policy TEXT digest is carried in the attempt contract itself, so a
    # reader holding only this record can still name the policy it decided
    # under instead of trusting that two contracts agreed at mint time.
    assert registry_sha256() in agreeing.attempt.provenance.input_digests

    disagreeing = _project("c" * 64)
    assert not disagreeing.complete
    assert disagreeing.evidence is None
    assert "policy digest disagreement" in disagreeing.error


# --------------------------------------------------------------------------- #
# 5. the covariate the runner already produced                                 #
# --------------------------------------------------------------------------- #
def test_shed_telemetry_reaches_the_receipt_from_the_live_runner(repo, tmp_path):
    """The producer and the consumer were both live and nothing joined them.

    ``daedalus.providers.ollama`` writes these rows into
    ``report.handoff["shed_telemetry"]``; ``canonicalise_attempt`` has taken a
    ``shed_telemetry`` argument since it was written; ``_canonicalise`` never
    passed one. This asserts the join, through the runner's real return shape.
    """
    def telemetry_runner(ctx):
        (ctx.worktree / "src" / "foo.py").write_text("def answer():\n    return 42\n")
        return {"report": {"handoff": {"shed_telemetry": [
            {"rel": "src/foo.py", "brief_shed": True,
             "est_in": 9_000, "brief_bytes": 0},
            {"rel": "src/bar.py", "brief_shed": False,
             "est_in": 1_200, "brief_bytes": 640},
        ]}}}

    _, _, contracts = _run(
        repo, tmp_path, "shed", runner=telemetry_runner,
        target_paths=("src/foo.py",), criterion=("tests/test_gate.py",))

    assert [row["rel"] for row in contracts.shed_telemetry] == \
        ["src/foo.py", "src/bar.py"]
    assert contracts.receipt.usage.est_input_tokens == 10_200
    # NOT input_tokens: an estimate must never occupy the measurement's field.
    assert contracts.receipt.usage.input_tokens == 0
    assert METERED_INPUT_REASON in contracts.policy.reasons
    assert UNMETERED_SPEND_REASON not in contracts.policy.reasons


def test_a_runner_that_reports_nothing_leaves_the_record_unchanged(repo, tmp_path):
    _, _, contracts = _run(
        repo, tmp_path, "bare", runner=_honest,
        target_paths=("src/foo.py",), criterion=("tests/test_gate.py",))

    assert contracts.shed_telemetry == ()
    assert contracts.receipt.usage.est_input_tokens == 0
    assert UNMETERED_SPEND_REASON in contracts.policy.reasons
    assert METERED_INPUT_REASON not in contracts.policy.reasons


def test_an_under_reported_estimate_is_named_and_not_averaged_away(repo, tmp_path):
    """A row that did not shed its brief had a full-file prompt built for it.

    ``est_in`` of 0 there is a missing estimate, not a measured zero, and the
    sum still looks like a total -- so the shortfall gets its own line inside
    the PolicyDecision digest rather than disappearing.
    """
    def short_runner(ctx):
        (ctx.worktree / "src" / "foo.py").write_text("def answer():\n    return 42\n")
        return {"report": {"handoff": {"shed_telemetry": [
            {"rel": "src/foo.py", "brief_shed": False,
             "est_in": 0, "brief_bytes": 640},
            {"rel": "src/bar.py", "brief_shed": False,
             "est_in": 1_200, "brief_bytes": 640},
        ]}}}

    _, _, contracts = _run(
        repo, tmp_path, "under", runner=short_runner,
        target_paths=("src/foo.py",), criterion=("tests/test_gate.py",))

    under = [r for r in contracts.policy.reasons if "UNDER-REPORTS" in r]
    assert under, contracts.policy.reasons
    assert "1 of 2" in under[0]


def test_an_estimate_still_counts_against_a_token_ceiling(repo, tmp_path):
    """A bound that ignores the only number anyone has is not a bound.

    The local lane reports an estimate and no measurement. Moving the estimate
    out of ``input_tokens`` must not take the token ceiling with it -- but the
    two describe ONE prompt, so they are maxed, never summed.
    """
    budget = ResourceBudget(max_tokens=10_000)

    assert budget.violations(ResourceUsage(est_input_tokens=9_000)) == ()
    assert budget.violations(ResourceUsage(est_input_tokens=10_001))
    # The larger of the two wins, whichever one it is.
    assert budget.violations(
        ResourceUsage(input_tokens=9_000, est_input_tokens=10_500))
    assert budget.violations(
        ResourceUsage(input_tokens=10_500, est_input_tokens=9_000))
    # Maxed, not summed: one prompt counted twice would trip on 6k + 6k.
    assert budget.violations(
        ResourceUsage(input_tokens=6_000, est_input_tokens=6_000)) == ()
