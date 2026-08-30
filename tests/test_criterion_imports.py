# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The criterion's import surface, resolved against the base tree for real.

WHAT WAS WRONG. ``daedalus.spine.receipts`` read the criterion's imports with a
line regex over two roots -- the repository root and the criterion's own
directory -- and its own docstring listed the blind spots: ``sys.path``
insertion, ``src/`` layouts, namespace packages, dynamic ``importlib``, relative
imports inside a package. Every one of those made an import INVISIBLE, and
check 6 of the criterion seal scored invisible as "imports nothing inside the
declared write scope". That is a check which passes by not looking, and the
Gate-1 ignition slice sealed through it: MEASURED, its conformance suite does
``sys.path.insert(0, str(ROOT / "src"))`` and ``from ignition_app import
parse_event``, and ``ignition_app`` reaches ``src/ignition_app/models.py`` and
``src/ignition_app/repository.py`` -- the two files the code/type work item is
allowed to write.

WHAT IT DOES NOW. The criterion is parsed with ``ast``; its imports are resolved
against the roots the project really uses (the repository root, pytest's
prepend basedir, ``src/`` when the tree has one, every statically readable
``sys.path`` mutation in the criterion and in the ``conftest.py`` files on its
collection chain, and ``pythonpath``/``where``/``package-dir`` from the project
config); resolution is transitive for one further level; and a construct that
CANNOT be read -- an opaque ``sys.path`` insertion, a computed
``importlib.import_module``, a criterion that does not parse -- is reported as
unknowable, which refuses the seal and names the import.

EVERY CASE RUNS AGAINST A REAL GIT REPOSITORY, for the reason the sibling file
gives: the resolution lives in ``receipts`` and the tree reading lives in
``attempt``, and a unit test of either half alone passes with the wiring between
them cut.
"""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from daedalus.schemas import ResourceBudget  # noqa: E402
from daedalus.spine.attempt import (  # noqa: E402
    GateResult,
    TaskAttempt,
    TaskSpec,
)
from daedalus.spine.receipts import (  # noqa: E402
    config_import_roots,
    criterion_probe_paths,
    evaluator_assurance_detail,
    sys_path_roots,
)


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          capture_output=True, text=True)


def _write(root, rel, text):
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


@pytest.fixture()
def repo(tmp_path):
    """One base revision holding all five formerly-blind layouts at once."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "imports@example.com")
    _git(root, "config", "user.name", "imports")

    # 1. a src/ layout reached by a sys.path insertion -- the Gate-1 shape
    _write(root, "src/app/__init__.py", "from .models import Event\n")
    _write(root, "src/app/models.py", "class Event:\n    bias_voltage = 1.0\n")
    _write(root, "tests/test_srclayout.py",
           "import sys\n"
           "from pathlib import Path\n"
           "ROOT = Path(__file__).resolve().parents[1]\n"
           "sys.path.insert(0, str(ROOT / 'src'))\n"
           "from app import Event\n"
           "assert Event.bias_voltage\n")
    # 2. a relative import inside a real test package
    _write(root, "suite/__init__.py", "")
    _write(root, "suite/helpers.py", "def check(v):\n    assert v\n")
    _write(root, "suite/test_rel.py", "from .helpers import check\ncheck(1)\n")
    # 3. a namespace package: no __init__.py anywhere on the path
    _write(root, "ns/pkg/leaf.py", "VALUE = 1\n")
    _write(root, "tests/test_ns.py", "from ns.pkg.leaf import VALUE\nassert VALUE\n")
    # 4. dynamic importlib, with a literal name and with a computed one
    _write(root, "tests/test_dyn.py",
           "import importlib\n"
           "mod = importlib.import_module('src.app.models')\n"
           "assert mod.Event\n")
    _write(root, "tests/test_dyn_opaque.py",
           "import importlib, os\n"
           "mod = importlib.import_module(os.environ['WHICH'])\n"
           "assert mod\n")
    # 5. a sys.path mutation no syntax tree can evaluate
    _write(root, "tests/test_opaque_path.py",
           "import os, sys\n"
           "sys.path.insert(0, os.environ['EXTRA'])\n"
           "import mystery\n"
           "assert mystery\n")
    # a root declared only by project config, with no sys.path line anywhere
    _write(root, "pyproject.toml",
           '[tool.pytest.ini_options]\npythonpath = ["lib"]\n')
    _write(root, "lib/helper.py", "def check():\n    return True\n")
    _write(root, "tests/test_cfg.py", "from helper import check\nassert check()\n")
    # the two negatives: stdlib only, and an installed distribution
    _write(root, "tests/test_plain.py",
           "import csv, json\nfrom pathlib import Path\n"
           "assert csv and json and Path\n")
    _write(root, "tests/test_thirdparty.py", "import pytest\nassert pytest\n")
    # a root NO convention and NO config names: only the criterion's own
    # sys.path line puts it there, so this case fails the moment that reader
    # stops working -- which the src/ cases above cannot detect, because `src`
    # is a conventional root as well
    _write(root, "vendor/plugin.py", "def run():\n    return 1\n")
    _write(root, "tests/test_vendor.py",
           "import sys\n"
           "from pathlib import Path\n"
           "sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'vendor'))\n"
           "from plugin import run\n"
           "assert run() == 1\n")
    # a name the tree DOES hold, but nowhere any modelled root reaches
    _write(root, "vendor/hidden/secret.py", "TOKEN = 1\n")
    _write(root, "tests/test_hidden.py", "import secret\nassert secret.TOKEN\n")
    # a criterion that is not python at all
    _write(root, "tests/test_broken.py", "def (:\n")

    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    return root


def _base(repo):
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _attempt(repo, tmp_path, criterion, scope, **spec_kwargs):
    spec = TaskSpec(task_id="imports", instruction="i", base_revision=_base(repo),
                    target_paths=scope, gate_criterion_paths=(criterion,),
                    **spec_kwargs)
    return TaskAttempt(
        spec, runner=lambda ctx: None,
        gate=lambda ctx: GateResult(passed=True, name="g",
                                    command=("pytest", criterion)),
        repo_root=repo, ledger_path=tmp_path / "spine.sqlite3",
        artifact_dir=tmp_path / "store", mission_id="m", reap=False,
        budget=ResourceBudget(max_wall_time_s=60))


def _surface(repo, tmp_path, criterion, scope=("src/app/models.py",), **kwargs):
    """The measured surface for one criterion, looked up by its own probe key.

    Not by the raw string: the key is the host's comparison spelling, and a test
    that hard-codes one of the two spellings is a test that passes on one host.
    """
    attempt = _attempt(repo, tmp_path, criterion, scope, **kwargs)
    key = next(key for key, path in criterion_probe_paths(attempt.task)
               if path == criterion)
    return attempt._criterion_imports(_base(repo))[key]


def _verdict(repo, tmp_path, criterion, scope, **kwargs):
    attempt = _attempt(repo, tmp_path, criterion, scope, **kwargs)
    base = _base(repo)
    result = type("R", (), {"gates": GateResult(
        passed=True, name="g", command=("pytest", criterion))})()
    return evaluator_assurance_detail(
        result, attempt.task,
        criterion_present=attempt._criterion_presence(base),
        criterion_imports=attempt._criterion_imports(base))


# --------------------------------------------------------------------------- #
# 1. the five declared blind spots: each RESOLVES or REFUSES, never passes     #
#    over an empty set                                                         #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("criterion,expected", [
    # a src/ layout reached by sys.path -- and one level further, because the
    # package's __init__ is what actually pulls models.py in
    ("tests/test_srclayout.py", {"src/app/__init__.py", "src/app/models.py"}),
    ("suite/test_rel.py", {"suite/helpers.py"}),
    ("tests/test_ns.py", {"ns/pkg/leaf.py"}),
    ("tests/test_dyn.py", {"src/app/__init__.py", "src/app/models.py"}),
    ("tests/test_cfg.py", {"lib/helper.py"}),
    ("tests/test_vendor.py", {"vendor/plugin.py"}),
])
def test_a_formerly_invisible_import_now_resolves(
        repo, tmp_path, criterion, expected):
    """Each of these named NOTHING under the line regex this replaced."""
    surface = _surface(repo, tmp_path, criterion)

    assert set(surface.paths) == expected
    assert surface.unknowable == ()


@pytest.mark.parametrize("criterion,fragment", [
    ("tests/test_dyn_opaque.py", "calls importlib.import_module() with a "
                                 "module name this resolver cannot read"),
    ("tests/test_opaque_path.py", "inserts an expression this resolver cannot "
                                  "evaluate onto sys.path"),
    ("tests/test_hidden.py", "yet the base revision does contain something "
                             "named 'secret'"),
    ("tests/test_broken.py", "does not parse"),
])
def test_an_unreadable_import_surface_refuses_the_seal(
        repo, tmp_path, criterion, fragment):
    """NOT KNOWABLE IS NOT A PASS -- for this check like every other one.

    Each of these four is a construct the resolver cannot follow. The old
    behaviour was to report no imports, which the seal read as "nothing inside
    the scope" and granted. Each now returns a reason that names the construct,
    and the seal refuses on it.
    """
    surface = _surface(repo, tmp_path, criterion)
    assert any(fragment in why for why in surface.unknowable), surface.unknowable

    verdict, why = _verdict(repo, tmp_path, criterion, ("src/app/models.py",))
    assert verdict == "unverified"
    assert "import surface could not be read" in why
    assert fragment in why


@pytest.mark.parametrize("criterion", ["tests/test_plain.py",
                                       "tests/test_thirdparty.py"])
def test_an_import_that_cannot_be_in_tree_costs_nothing(
        repo, tmp_path, criterion):
    """The over-refusal this guard must NOT commit.

    ``import csv`` and ``import pytest`` resolve to no in-tree file, and neither
    can ever be satisfied by one: nothing in the tree is called ``csv.py`` or
    ``pytest/``. Treating "unresolved" as "unknowable" without that second
    question would take the seal away from every criterion that imports the
    standard library -- a guard that closes the hole by breaking the feature.
    """
    surface = _surface(repo, tmp_path, criterion)

    assert surface.paths == ()
    assert surface.unknowable == ()


# --------------------------------------------------------------------------- #
# 2. the declared conformance exception                                       #
# --------------------------------------------------------------------------- #
def test_an_undeclared_import_of_the_write_scope_refuses(repo, tmp_path):
    verdict, why = _verdict(
        repo, tmp_path, "tests/test_srclayout.py", ("src/app/models.py",))

    assert verdict == "unverified"
    assert "imports 'src/app/models.py'" in why
    assert "INSIDE the declared write scope" in why


@pytest.mark.parametrize("declaration", [
    {"gate_reads_scope": True},
    {"fail_to_pass": ("tests/test_srclayout.py::test_event",)},
])
def test_a_declared_conformance_gate_keeps_the_seal(
        repo, tmp_path, declaration):
    """The same import, the same scope, and a task that SAYS what it is.

    Both spellings live inside the task digest, so the permission cannot be
    added after the verdict; and the granted reason states the fact rather than
    hiding it behind the sentence a genuinely disjoint criterion earns.
    """
    verdict, why = _verdict(repo, tmp_path, "tests/test_srclayout.py",
                            ("src/app/models.py",), **declaration)

    assert verdict == "deterministic"
    assert "conformance test reads its own scope by declaration" in why


@pytest.mark.parametrize("scope,fragment", [
    # the criterion file itself
    (("tests/test_srclayout.py",), "is INSIDE the declared write scope"),
    # a conftest.py on its collection chain
    (("src/app/models.py", "tests/conftest.py"), "execution-influencing file"),
])
def test_the_declaration_does_not_soften_the_other_checks(
        repo, tmp_path, scope, fragment):
    """It permits ONE thing: an import of the scope. Nothing else moves.

    A conformance test may execute the code the candidate wrote. It may not be
    the code the candidate wrote, and nothing on its collection path may be
    either -- otherwise the candidate changes what the gate ASKS rather than
    what it MEASURES, and the declaration would be a way to buy back all six
    checks with one boolean.
    """
    verdict, why = _verdict(repo, tmp_path, "tests/test_srclayout.py", scope,
                            gate_reads_scope=True)

    assert verdict == "unverified"
    assert fragment in why


# --------------------------------------------------------------------------- #
# 3. the pure readers, where the reasons come from                            #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("source,roots,reasons", [
    ("import sys\nsys.path.insert(0, 'src')\n", ("src",), 0),
    ("import sys\nfrom pathlib import Path\n"
     "sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))\n",
     ("src",), 0),
    ("import os, sys\n"
     "sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))\n",
     ("lib",), 0),
    ("import sys\nsys.path.append('a')\nsys.path.extend(['b', 'c'])\n",
     ("a", "b", "c"), 0),
    # a read is not a mutation
    ("import sys\nif 'src' not in sys.path:\n    pass\n", (), 0),
    # and the three shapes that cannot be evaluated
    ("import os, sys\nsys.path.insert(0, os.environ['X'])\n", (), 1),
    ("import sys\nsys.path = compute()\n", (), 1),
    ("import sys\nsys.path.extend(compute())\n", (), 1),
])
def test_sys_path_roots_reads_what_it_can_and_names_what_it_cannot(
        source, roots, reasons):
    found, why = sys_path_roots(source, "tests/test_gate.py")

    assert found == roots
    assert len(why) == reasons


@pytest.mark.parametrize("text,roots,reasons", [
    ('[tool.pytest.ini_options]\npythonpath = ["src", "lib"]\n',
     ("src", "lib"), 0),
    ("[pytest]\npythonpath = src lib\n", ("src", "lib"), 0),
    ('[tool.setuptools.packages.find]\nwhere = ["src"]\n', ("src",), 0),
    # a TOML inline table is read permissively: an extra root resolves nothing,
    # while refusing every src-layout pyproject would make the commonest layout
    # there is permanently unknowable
    ('[tool.setuptools]\npackage-dir = {"" = "src"}\n', ("src",), 0),
    ('pythonpath = [os.environ["X"]]\n', (), 1),
])
def test_config_import_roots_reads_what_it_can_and_names_what_it_cannot(
        text, roots, reasons):
    found, why = config_import_roots("pyproject.toml", text)

    assert found == roots
    assert len(why) == reasons


def test_a_conftest_on_the_chain_puts_its_root_on_the_path(repo, tmp_path):
    """A criterion with no import machinery of its own still reaches the code.

    ``conftest.py`` runs before the test module is imported, so a ``sys.path``
    insertion there is exactly as load-bearing as one in the criterion. Reading
    only the criterion's own lines would miss it, and missing it is a grant.
    """
    _write(repo, "tests/conftest.py",
           "import sys\n"
           "from pathlib import Path\n"
           "sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))\n")
    _write(repo, "tests/test_via_conftest.py", "from app import Event\nassert Event\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "conftest puts src on the path")

    surface = _surface(repo, tmp_path, "tests/test_via_conftest.py")

    assert set(surface.paths) == {"src/app/__init__.py", "src/app/models.py"}
    assert surface.unknowable == ()
