"""The spend cap is only a cap if something installs it.

`daedalus/budget.py` was built, measured, and had ZERO callers -- which is the
single most repeated defect in this repo. Tonight alone: a containment module
committed with eleven measured properties and no caller; a semantic route listed
as a present feature while being unwired AND broken; a vector index whose only
writer sat behind an environment variable nothing sets. A guard that is not
reached is not a guard, and it is worse than an absent one because it reads as
protection on the shelf.

So this file is about the WIRING, not the mechanism. `tests/test_budget.py`
proves the ceiling works when called. These tests prove something calls it, and
that installing it did not break every ordinary subprocess in the product --
which is the failure that would get the cap ripped out within the hour, leaving
no cap at all.
"""
from __future__ import annotations

import ast
import inspect
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from daedalus import budget


@pytest.fixture(autouse=True)
def _uninstalled():
    """Every test starts from a clean interpreter and leaves one behind.

    The guard replaces module globals; a leaked install would silently change
    the behaviour of every later test in the session.
    """
    budget.uninstall_process_guard()
    yield
    budget.uninstall_process_guard()


def test_the_cli_entry_point_installs_the_guard():
    """Structural, read off the CLI's own source.

    Asserted on the AST rather than by grepping text, because the comment
    explaining WHY the guard is installed contains the words that a text search
    would match -- and a test that matches its own explanation stays green after
    the code it describes is deleted. That has happened four times in this repo.
    """
    from daedalus import cli

    tree = ast.parse(textwrap.dedent(inspect.getsource(cli.main)))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "install_process_guard"]
    assert calls, "daedalus.cli.main does not install the spend guard"


def test_the_guard_is_installed_BEFORE_any_subcommand_dispatch():
    """Order is the whole property. A cap installed after dispatch is a cap
    installed after the spending."""
    from daedalus import cli

    tree = ast.parse(textwrap.dedent(inspect.getsource(cli.main)))
    fn = tree.body[0]
    install_line = None
    first_dispatch_line = None
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "install_process_guard"):
            install_line = node.lineno
        if isinstance(node, ast.If) and first_dispatch_line is None:
            # the `if cmd == "doctor": ...` chain
            test = node.test
            if (isinstance(test, ast.Compare)
                    and isinstance(test.left, ast.Name) and test.left.id == "cmd"):
                first_dispatch_line = node.lineno
    assert install_line is not None
    assert first_dispatch_line is not None, "could not find the dispatch chain"
    assert install_line < first_dispatch_line, (
        f"the guard installs at line {install_line} but dispatch begins at "
        f"{first_dispatch_line} -- a subcommand could spend first")


def test_installing_it_does_NOT_break_an_ordinary_subprocess():
    """The allow side, and the reason the cap survives contact with the product.

    The guard replaces subprocess.run globally. If a non-vendor spawn were
    charged, refused, or mangled, every git and pytest call in this repo would
    break -- and the fix somebody reaches for at 3am is to delete the guard.
    """
    budget.install_process_guard()
    proc = subprocess.run([sys.executable, "-c", "print('ordinary')"],
                          capture_output=True, text=True)
    assert proc.returncode == 0
    assert proc.stdout.strip() == "ordinary"

    git = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                         cwd=str(Path(__file__).resolve().parents[1]),
                         capture_output=True, text=True)
    assert git.returncode == 0, git.stderr


def test_the_guard_is_idempotent_and_reversible():
    """`main()` may run more than once in a test session, and a double install
    that wrapped the wrapper would charge twice for one call."""
    real = subprocess.run
    budget.install_process_guard()
    once = subprocess.run
    budget.install_process_guard()
    assert subprocess.run is once, "installing twice re-wrapped the wrapper"
    budget.uninstall_process_guard()
    assert subprocess.run is real, "uninstall did not restore the original"


def test_a_vendor_spawn_IS_intercepted_when_installed(monkeypatch, tmp_path):
    """Without this the three tests above would all pass with a guard that
    classifies nothing and charges nobody."""
    monkeypatch.setenv("DAEDALUS_BUDGET_LEDGER", str(tmp_path / "ledger.json"))
    seen: list = []
    real_reserve = budget.reserve

    def spy(vendor, **kw):
        seen.append(vendor)
        return real_reserve(vendor, **kw)

    monkeypatch.setattr(budget, "reserve", spy)
    budget.install_process_guard()
    # A vendor argv the classifier recognises; the binary need not exist -- the
    # reservation happens BEFORE the spawn, which is the property under test.
    try:
        subprocess.run(["claude", "-p", "--output-format", "json"],
                       capture_output=True)
    except (FileNotFoundError, OSError):
        pass
    assert seen, "a recognised vendor spawn was not reserved"
