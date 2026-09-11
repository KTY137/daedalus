"""An ``unknown`` row must say which evidence made it unknown.

WHY A THIRD FILE. ``tests/test_mapping_reach.py`` pins one hostile mini-repo
whose counts are a fixed contract, and ``tests/test_mapping_reach_facades.py``
owns the facade-reading cases. This is a separate claim about the REASON TEXT,
so it gets its own repo, for the reason the facade file already gave.

WHAT WENT WRONG, MEASURED 2026-09-03 while verifying the facade fix against
``docs/G1_LOOSE_PARTS_SURVEY_20260903.md``. Reading the lazy-facade tables added
a third kind of weak evidence -- *named in a lazy-facade table* -- but the
``unknown`` branch still rendered the one sentence written for the two older
kinds. Fourteen ``daedalus/kernel/`` rows were therefore reported as

    imported only where the import is not evidence that anything runs it
    (a dead branch or a swallowed ImportError)

when the tree contains neither. ``daedalus/kernel/attempt_ledger.py`` has
exactly one weak edge, ``daedalus/kernel/__init__.py -> ... (lazy-facade
table)``; there is no dead branch and no swallowed import anywhere near it.

WHY THIS IS THE SAME DEFECT CLASS THE ENGINE EXISTS TO AVOID. The module
docstring's rule is that a gap is recoverable and a false accusation is not. A
reason naming a cause that is not in the code is a false accusation about
*why* -- it sends a reader hunting for a swallowed ImportError that was never
written, and it hides the real finding, which is that a facade CAN load the
module but nothing was shown to ask for it.

NOT CHANGED HERE, deliberately: the classification itself. Treating a facade
table as weak rather than real evidence is a correct call -- the table proves
the module is loadable by name, not that any caller touches that name -- and
these tests pin that call rather than relitigating it.

A REFUTED HYPOTHESIS, recorded so it is not retried: the first guess was that
``_catches_import_error`` was firing on ``daedalus/kernel/__init__.py``'s
``_load_owner``, whose handler re-raises on every path. It was not. That
handler wraps a call whose argument is a variable, so it never becomes a
statement-level weak import at all, and the predicate is not involved.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from daedalus.mapping import analyse


PYPROJECT = """\
[build-system]
requires = ["setuptools>=61"]

[project]
name = "mini"
version = "0.0.1"
dependencies = []

[project.scripts]
mini = "mini.cli:main"

[tool.setuptools]
packages = ["mini"]
"""

FILES = {
    "pyproject.toml": PYPROJECT,
    "mini/cli.py": (
        "from mini import facade\n"
        "from mini import guarded\n"
        "\n"
        "def main():\n"
        "    return facade, guarded\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    raise SystemExit(main())\n"
    ),
    "mini/__init__.py": "",
    # weak kind 1: a name in a lazy-facade table, and nothing else
    "mini/facade/__init__.py": (
        "from importlib import import_module as _import_module\n"
        "\n"
        "_OWNED = frozenset({'tabled'})\n"
        "\n"
        "def __getattr__(name):\n"
        "    if name in _OWNED:\n"
        "        return _import_module(f'{__name__}.{name}')\n"
        "    raise AttributeError(name)\n"
    ),
    "mini/facade/tabled.py": "VALUE = 1\n",
    # weak kind 2: an import written and then guarded out
    "mini/guarded/__init__.py": (
        "if False:\n"
        "    from . import deadbranch\n"
        "try:\n"
        "    from . import optional\n"
        "except ImportError:\n"
        "    optional = None\n"
    ),
    "mini/guarded/deadbranch.py": "VALUE = 2\n",
    "mini/guarded/optional.py": "VALUE = 3\n",
}


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    for rel, text in FILES.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


def _facts(report, module):
    got = report.get(module)
    assert got is not None, f"{module} missing from the report"
    return got


def test_a_facade_table_row_is_unknown_but_not_accused_of_a_guard(
    repo: Path,
) -> None:
    facts = _facts(analyse(repo), "mini/facade/tabled.py")
    assert facts.classification == "unknown", facts.reason
    assert "swallowed ImportError" not in facts.reason
    assert "dead branch" not in facts.reason
    assert "facade" in facts.reason


def test_a_guarded_import_still_says_guarded(repo: Path) -> None:
    """The original sentence must survive where it is actually true."""
    for module in ("mini/guarded/deadbranch.py", "mini/guarded/optional.py"):
        facts = _facts(analyse(repo), module)
        assert facts.classification == "unknown", facts.reason
        assert "dead branch" in facts.reason or "ImportError" in facts.reason


def test_the_evidence_list_still_names_the_importer(repo: Path) -> None:
    """The reason summarises; the evidence must stay specific."""
    facts = _facts(analyse(repo), "mini/facade/tabled.py")
    joined = " ".join(facts.evidence)
    assert "mini/facade/__init__.py" in joined
    assert "lazy-facade table" in joined


# --------------------------------------------------- the tree this was found in

KERNEL_ROWS = (
    "daedalus/kernel/attempt_ledger.py",
    "daedalus/kernel/attempt_contracts.py",
    "daedalus/kernel/promotion_fingerprint.py",
)


def test_the_kernel_facade_rows_do_not_claim_a_guard_that_is_not_there() -> None:
    """Regression pin for the real repository, not a fixture.

    Every weak edge into these rows is a lazy-facade table entry from
    ``daedalus/kernel/__init__.py``. Neither a dead branch nor a swallowed
    ImportError exists on those paths, so the reason must not name one.
    """
    report = analyse(Path(__file__).resolve().parents[1])
    for module in KERNEL_ROWS:
        facts = _facts(report, module)
        sources = [w for w in report.weak_edges if w.endswith(f"-> {module} (lazy-facade table)")]
        assert sources, f"{module}: expected a lazy-facade weak edge"
        guarded = [
            w for w in report.weak_edges
            if f"-> {module} " in w and "lazy-facade table" not in w
        ]
        assert not guarded, f"{module}: unexpected guarded edge {guarded}"
        assert "swallowed ImportError" not in facts.reason, facts.reason
