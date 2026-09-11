"""Every command the UI tells a human to type must actually run.

Found 2026-09-03, and the circumstances are the point. When the API is
unreachable the cockpit shows a remedy: "Starte sie mit ``python -m ...``".
It named ``daedalus.interfaces.cli.cli``, which has never existed. The
Playwright spec that was supposed to cover that screen asserted
``daedalus.cli``, which stopped existing in an earlier move. So at the exact
moment a user has a dead backend and nothing else to go on, the product gave
a command that fails -- and the test agreed with a different failing command.

Neither could catch the other, because both were checking a STRING. This
checks the thing the string promises: that the module is importable.

Deliberately narrow: it looks only for ``python -m <module>`` in the surfaces
a human reads. Argument spelling, flags and behaviour are not its business --
the module resolving is what turns advice into something that runs.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: Where a human is told to type something.
SURFACES = (
    ROOT / "apps" / "web" / "src",
    ROOT / "vscode-agent-env" / "extension.js",
)

#: ``python -m foo.bar`` / ``python3 -m foo.bar``. A trailing dot is stripped:
#: prose ends sentences, module paths do not.
INVOCATION = re.compile(r"python3?\s+-m\s+([A-Za-z_][A-Za-z0-9_.]*)")

SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs"}


def _sources() -> list[Path]:
    found: list[Path] = []
    for surface in SURFACES:
        if surface.is_file():
            found.append(surface)
        elif surface.is_dir():
            found.extend(p for p in sorted(surface.rglob("*")) if p.suffix in SUFFIXES)
    return found


def _advertised() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    for path in _sources():
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in INVOCATION.finditer(text):
            out.append((path, match.group(1).rstrip(".")))
    return out


ADVERTISED = _advertised()


def test_the_surfaces_actually_advertise_something():
    """Guard the guard: if the scan finds nothing, the checks below are inert
    and would pass over a broken command as happily as over a good one."""
    assert ADVERTISED, "no `python -m ...` advice found -- the scan is broken, not the UI"


@pytest.mark.parametrize(
    ("path", "module"),
    ADVERTISED,
    ids=[f"{p.name}:{m}" for p, m in ADVERTISED],
)
def test_every_advertised_module_can_be_imported(path: Path, module: str):
    spec = importlib.util.find_spec(module)
    assert spec is not None, (
        f"{path.relative_to(ROOT)} tells the user to run `python -m {module}`, "
        f"and that module does not exist. Advice that fails is worse than none: "
        f"it is shown when something is already broken."
    )
