"""The suite must refuse to be scored by an interpreter nobody selected.

Found by ``daedalus-84`` and reproduced here [MEASURED 2026-09-01]. The bare
``pytest`` on this machine's PATH is not this repository's interpreter::

    which pytest -> ...\\AppData\\Local\\Programs\\Python\\Python310\\Scripts\\pytest.EXE

It does not refuse and it does not reliably fail. Whether it reports green
depends on whether the test's imports happen to resolve under it, which is
incidental:

    tests/test_hooks_v2.py                     -> 155 passed, exit 0
    tests/contracts/test_gate_runner_...py     ->   5 passed, exit 0
    tests/contracts/test_work_packet_index.py  -> ModuleNotFoundError: 'tools'

Two files in the same directory disagree. ``daedalus`` declares
``dependencies = []``, so most of the tree imports anywhere a Python and
pytest exist — which makes a confident false green the normal case rather
than the exception, and makes it likeliest on exactly the narrow, targeted
runs people use before committing.

``run_gate_checks._require_pytest`` cannot catch this: that interpreter *has*
pytest. The distinguishing property is that it is a system installation.
Every interpreter that legitimately runs this suite lives in a virtual
environment; the intruder does not.

This is deliberately a mechanism and not a rule. "Always write
``python -m pytest`` with an explicit path" is a discipline, and discipline is
what failed four separate times on 2026-09-01.
"""

from __future__ import annotations

import sys


def test_the_running_interpreter_is_a_virtual_environment() -> None:
    """Refuse a result produced by a system-wide interpreter.

    ``sys.prefix != sys.base_prefix`` is true inside a venv and false for a
    system installation [MEASURED 2026-09-01 across three interpreters on this
    machine]. It names no path, so a repository-local ``.venv``, a worktree
    borrowing the primary checkout's venv, and CI's own venv all pass, while
    the PATH ``pytest`` from the system Python does not.
    """

    assert sys.prefix != sys.base_prefix, (
        "this suite is being run by a system-wide interpreter "
        f"({sys.executable}). It has pytest, so it will happily report a "
        "green result measured against an environment nobody selected: the "
        "repository declares dependencies = [], so most of the tree imports "
        "anywhere. Run it with the repository virtualenv, e.g. "
        "`.venv/Scripts/python.exe -m pytest`, and never the bare `pytest` "
        "on PATH."
    )
