"""A declared path means one thing to every reader of it, or there is no task.

WHAT WAS WRONG. ``TaskSpec.target_paths`` took any string at construction.
``C:/evil``, ``../outside``, ``.//src/foo.py`` and ``src/foo.py`` spelled twice
all built a perfectly valid spec, and the only thing that ever refused an
unusable declaration was the containment gate at the far end of a finished
attempt. Everything in between read the raw text: the picker's policy
pre-check, ``offload_runner``'s ``paths`` argument (which OPENS them), the
receipt's ``writable_paths``, and the task digest itself -- so the effect key of
``src/foo.py`` and of ``.//src/foo.py`` differed while the two named one file,
and an operator was shown a boundary that bounded nothing.

WHAT IT DOES NOW. ``TaskSpec.__post_init__`` settles both declared path tuples
into the same normal form the seal and ``containment_escapes`` compare in, and
refuses -- with :class:`TaskSpecInvalid`, a ``ValueError`` -- an entry that is
absolute, drive-lettered, root-escaping, empty, or a second spelling of an entry
already declared. Directories survive, because a declared directory is a
legitimate scope both halves already read as covering what is under it.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from daedalus.spine.attempt import TaskSpec, TaskSpecInvalid  # noqa: E402
from daedalus.spine.receipts import containment_escapes  # noqa: E402


@pytest.mark.parametrize("field", ["target_paths", "gate_criterion_paths"])
@pytest.mark.parametrize("declaration,fragment", [
    ("C:/evil", "no normal form inside the tree"),
    ("/etc/passwd", "no normal form inside the tree"),
    ("../outside", "no normal form inside the tree"),
    ("src/../../outside", "no normal form inside the tree"),
    ("", "is empty"),
    ("   ", "is empty"),
    (".", "no normal form inside the tree"),
])
def test_a_declaration_that_names_no_location_refuses_the_task(
        field, declaration, fragment):
    """Refused where it is WRITTEN, not four readers later."""
    with pytest.raises(TaskSpecInvalid) as refusal:
        TaskSpec(task_id="bad", instruction="i", **{field: (declaration,)})

    assert field in str(refusal.value)
    assert fragment in str(refusal.value)


@pytest.mark.parametrize("field", ["target_paths", "gate_criterion_paths"])
@pytest.mark.parametrize("pair", [
    ("src/foo.py", ".//src/foo.py"),
    ("src/foo.py", "src/../src/foo.py"),
    ("src/foo.py", "src\\foo.py"),
])
def test_one_location_declared_twice_refuses_the_task(field, pair):
    """Two spellings of one file are not two declarations.

    Left standing, they make the digest a function of typing rather than of
    location, and they let a reader that de-duplicates and one that does not
    disagree about how wide the scope is.
    """
    with pytest.raises(TaskSpecInvalid) as refusal:
        TaskSpec(task_id="dupe", instruction="i", **{field: pair})

    assert "spelled twice" in str(refusal.value)


@pytest.mark.parametrize("raw,settled", [
    (".//src/foo.py", "src/foo.py"),
    ("src/../src/foo.py", "src/foo.py"),
    ("src\\foo.py", "src/foo.py"),
    ("./tests", "tests"),
    # a directory is a legitimate declaration and stays one
    ("tests", "tests"),
    ("tests/", "tests"),
])
def test_a_usable_declaration_is_stored_in_the_normal_form(raw, settled):
    spec = TaskSpec(task_id="ok", instruction="i", target_paths=(raw,),
                    gate_criterion_paths=(raw,))

    assert spec.target_paths == (settled,)
    assert spec.gate_criterion_paths == (settled,)


def test_the_digest_follows_the_location_and_not_the_spelling():
    """The effect key names WHAT is written, not how it was typed."""
    typed = TaskSpec(task_id="t", instruction="i", target_paths=(".//src/foo.py",))
    plain = TaskSpec(task_id="t", instruction="i", target_paths=("src/foo.py",))

    assert typed.body()["target_paths"] == ["src/foo.py"]
    assert typed.digest == plain.digest


def test_the_declaration_the_containment_gate_reads_is_the_stored_one():
    """The two halves of one field, asserted as one statement.

    ``containment_escapes`` used to be the only reader that refused an unusable
    declaration. It still refuses one -- it must, because it accepts raw
    sequences from callers that are not TaskSpecs -- but a spec can no longer
    hand it one, and what it does get is already in its own comparison form.
    """
    spec = TaskSpec(task_id="t", instruction="i", target_paths=(".//src",))

    escaped, error = containment_escapes(("src/foo.py",), spec.target_paths)

    assert escaped == () and error is None


def test_the_conformance_declaration_is_inside_the_task_digest():
    """A permission that could be granted afterwards would be no permission."""
    plain = TaskSpec(task_id="t", instruction="i", target_paths=("src/foo.py",),
                     gate_criterion_paths=("tests/test_gate.py",))
    declared = TaskSpec(task_id="t", instruction="i", target_paths=("src/foo.py",),
                        gate_criterion_paths=("tests/test_gate.py",),
                        gate_reads_scope=True)

    assert "gate_reads_scope" not in plain.body()
    assert declared.body()["gate_reads_scope"] is True
    assert plain.digest != declared.digest


@pytest.mark.parametrize("declared,expected,fragment", [
    (False, "unverified", "imports 'src/ignition_app/models.py'"),
    (True, "deterministic",
     "conformance test reads its own scope by declaration"),
])
def test_the_gate1_code_type_shape_seals_only_when_it_declares(
        tmp_path, declared, expected, fragment):
    """The Gate-1 decision, against the real ignition fixture.

    MEASURED: the conformance suite does ``sys.path.insert(0, str(ROOT /
    'src'))`` and ``from ignition_app import parse_event``; ``ignition_app``'s
    package reaches ``src/ignition_app/models.py`` and ``repository.py``, which
    ARE the code/type work item's ``target_paths``. The slice used to seal
    because the line regex could not see through the insertion -- a vacuous
    pass. It now seals because ``daedalus.ignition.gate1`` declares the code/
    type gate a conformance test of its own scope, and the receipt says so.
    """
    from daedalus.ignition import checks as ignition_checks
    from daedalus.ignition.gate1 import DEFAULT_FIXTURE, prepare_ignition_repo
    from daedalus.orchestration.execution import compose_task_attempt
    from daedalus.spine.attempt import GateResult
    from daedalus.spine.receipts import evaluator_assurance_detail

    repo, base = prepare_ignition_repo(DEFAULT_FIXTURE, tmp_path / "target")
    criterion = ignition_checks.CONFORMANCE_TEST_PATH
    command = ("python", "-m", "pytest", *ignition_checks.CODE_TYPE_NODE_IDS)
    spec = TaskSpec(
        task_id="wi-code-type", instruction="rename", base_revision=base,
        target_paths=("src/ignition_app/models.py",
                      "src/ignition_app/repository.py"),
        gate_criterion_paths=(criterion,), gate_reads_scope=declared)
    attempt = compose_task_attempt(
        spec, runner=lambda ctx: None,
        gate=lambda ctx: GateResult(passed=True, name="ignition-code-type",
                                    command=command),
        repo_root=repo, ledger_path=tmp_path / "spine.sqlite3",
        artifact_dir=tmp_path / "store", mission_id="m", reap=False)
    result = type("R", (), {"gates": GateResult(
        passed=True, name="ignition-code-type", command=command)})()

    verdict, why = evaluator_assurance_detail(
        result, spec,
        criterion_present=attempt._criterion_presence(base),
        criterion_imports=attempt._criterion_imports(base))

    assert verdict == expected
    assert fragment in why


def test_the_gate1_source_still_makes_the_declaration():
    """A tripwire on the one production producer of ``gate_criterion_paths``.

    The test above proves the SHAPE seals when it declares. This proves the
    slice still declares -- dropping the line would flip the Gate-1 packet to
    ``unverified`` at the next run and nothing else in this file would notice.
    """
    import inspect

    from daedalus.ignition import gate1

    assert "gate_reads_scope=bool(" in inspect.getsource(gate1)
