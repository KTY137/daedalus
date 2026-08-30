# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

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


def test_things_can_still_SUBCLASS_Popen_while_the_guard_is_installed():
    """The regression this test exists for, and it broke the CLI outright.

    The first version of the guard replaced `subprocess.Popen` with a plain
    function. asyncio derives a class from it at import time:

        class Popen(subprocess.Popen):
        TypeError: function() argument 'code' must be code, not str

    So `daedalus web` -- which reaches asyncio through context_plan ->
    memory.embeddings -> adapters -- died with a traceback instead of refusing
    a non-loopback bind, and the guard test that caught it was a WEB test, not
    a budget one. The budget test only exercised `subprocess.run`.

    Asserted three ways, because a class that merely exists is not enough:
    it must be derivable, `isinstance` must still work, and a real import of
    asyncio must succeed in a fresh interpreter with the guard installed.
    """
    budget.install_process_guard()
    assert isinstance(subprocess.Popen, type), "Popen is no longer a class"

    class Derived(subprocess.Popen):                 # must not raise
        pass

    proc = subprocess.Popen([sys.executable, "-c", "pass"],
                            stdout=subprocess.PIPE)
    proc.communicate()
    assert isinstance(proc, subprocess.Popen)

    # ...and end to end, in a child that installs the guard and THEN imports
    # asyncio, which is the exact order the CLI produces.
    probe = subprocess.run(
        [sys.executable, "-c",
         "from daedalus.budget import install_process_guard;"
         "install_process_guard();"
         "import asyncio;"
         "print('asyncio ok')"],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True, text=True, timeout=120)
    assert probe.returncode == 0, probe.stderr[-800:]
    assert "asyncio ok" in probe.stdout


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


def test_uninstall_never_resurrects_a_mock_that_was_active_during_install():
    """The 2026-08-23 full-suite cascade, pinned. A test mocks subprocess.run,
    the code under test installs the guard around the MOCK, the mock's context
    exits and puts the real function back -- and uninstall must not write the
    remembered mock over it. 400 red tests and 119 refused kill-switch arms
    came from exactly that sequence."""
    from unittest import mock

    real_run = subprocess.run
    budget.uninstall_process_guard()            # start from a clean interpreter
    with mock.patch("subprocess.run", side_effect=lambda *a, **k: "fake") as fake:
        budget.install_process_guard()          # wraps the mock, as ikarus_os did
        assert subprocess.run is not fake
    assert subprocess.run is real_run, "mock.patch put the real function back"
    left = budget.uninstall_process_guard()
    assert subprocess.run is real_run, "uninstall must not resurrect the mock"
    assert "subprocess.run" in left
    assert budget._INSTALLED == {}
    # and a clean install/uninstall round-trip still restores the original
    budget.install_process_guard()
    assert subprocess.run is not real_run
    assert budget.uninstall_process_guard() == []
    assert subprocess.run is real_run


def test_installing_over_a_mocked_popen_neither_breaks_nor_wraps_the_mock():
    """``mock.patch("subprocess.Popen")`` leaves a MagicMock instance in the
    slot. Installing the net over it used to raise ``AttributeError: __name__``
    (subclassing a mock, then reading its ``__name__``), which ikarus_os turned
    into a refusal of every vendor call in the test. Now the mock is left as
    found, install succeeds, and uninstall hands the slot back unchanged."""
    from unittest import mock

    budget.uninstall_process_guard()
    with mock.patch("subprocess.Popen") as fake:
        budget.install_process_guard()
        assert subprocess.Popen is fake
        assert subprocess.run is not budget._INSTALLED["subprocess.run"][0]
        # unwrapped means (mock, mock): uninstall finds its own record and
        # has nothing to report -- the slot is handed back as it was found
        assert budget.uninstall_process_guard() == []
        assert subprocess.Popen is fake
    assert budget._INSTALLED == {}
