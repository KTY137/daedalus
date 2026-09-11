"""Every `python -m …` the cockpit prints must name a module that exists.

WHY THIS TEST EXISTS. The cockpit's backend-down screen tells the reader how
to start the server. On 2026-09-03 that line read
``python -m daedalus.interfaces.cli.cli web`` — a module path that had never
existed. The layout refactor moved ``daedalus/cli.py`` into
``daedalus/interfaces/cli/entry.py`` and rewrote the string to a plausible
neighbour of the real target, and nothing noticed: the one browser test that
reads that line asserted the OLD string, so it went red for the wrong reason
and said nothing about the new one being wrong too.

A command printed at the moment everything else has failed is the last thing
between the reader and a dead end. This test reads the module path out of the
shipped frontend sources and imports it, so a rename that misses a
user-facing string fails here rather than in someone's terminal.

It deliberately checks the MODULE, not the whole command line: the flags
belong to the CLI's own argument tests, and importing is enough to prove the
path resolves.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WEB_SRC = ROOT / "apps" / "web" / "src"

#: `python -m some.dotted.path`, the shape a reader is told to type.
COMMAND = re.compile(r"python\s+-m\s+([A-Za-z_][\w.]*)")


def _named_modules() -> list[tuple[str, str]]:
    """Every module a shipped frontend source tells the reader to run."""
    found: list[tuple[str, str]] = []
    for path in sorted(WEB_SRC.rglob("*")):
        if path.suffix not in {".ts", ".tsx"} or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in COMMAND.finditer(text):
            module = match.group(1)
            # Only this repository's own modules are ours to guarantee.
            if module == "daedalus" or module.startswith("daedalus."):
                found.append((str(path.relative_to(ROOT)).replace("\\", "/"), module))
    return found


def test_the_cockpit_names_at_least_one_command() -> None:
    """A guard on the guard: if the regex or the tree moves, this test must
    not quietly start proving nothing."""
    assert _named_modules(), (
        "no `python -m daedalus…` command found in apps/web/src — either the "
        "cockpit stopped telling the reader how to start the backend, or this "
        "test no longer looks where those strings live"
    )


@pytest.mark.parametrize("where,module", _named_modules(), ids=lambda v: v)
def test_every_command_the_cockpit_prints_resolves(where: str, module: str) -> None:
    assert importlib.util.find_spec(module) is not None, (
        f"{where} tells the reader to run `python -m {module}`, which does not "
        f"exist. Fix the string, not this test."
    )
