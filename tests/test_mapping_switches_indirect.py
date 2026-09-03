"""An env var name passed to a helper is still a read of that variable.

WHY (G1-MAP-05, 2026-09-03). The switch scanner resolves
``os.environ.get(SOME_CONST)`` -- it collects module constants and looks the
name up. It does not resolve the shape this repository actually uses for its
most important switches:

    ENV_CEILING = "DAEDALUS_BUDGET_USD"

    def _env_float(name, default):
        raw = os.environ.get(name)          # <- name is a PARAMETER
        ...

    return _env_float(ENV_CEILING, DEFAULT_CEILING_USD)

The read is inside a helper, and the helper takes the variable name as an
argument. The scanner sees ``os.environ.get(name)`` with an unresolvable Name,
files it under dynamic reads, and never learns that DAEDALUS_BUDGET_USD is read
at all.

WHAT THAT COST. ``.env.example`` documents DAEDALUS_BUDGET_USD under "Spend
ceiling for one activation period", so the name is documented and -- as far as
the scanner could tell -- read by nothing. The drift gate therefore reported it
as *"documented, but no code reads it any more"*: dead configuration. It is not
dead. It is the $5.00 period monetary ceiling that master plan §4.1 and
amendment Revisions 9 and 10 are entirely about, read at
``daedalus/kernel/policy/ledger.py:657``. The same applied to
DAEDALUS_BUDGET_MAX_CALLS via ``_env_int(ENV_MAX_CALLS, ...)``, whose constant
is imported from ``daedalus/kernel/policy/pricing.py``.

An instrument that tells an operator the spend ceiling is dead configuration is
worse than one that says nothing, so this is the same defect class as the
reachability engine's facade blindness: a scanner that cannot read an
indirection the codebase uses everywhere.

THE RULE, and its limits. A function is an env-reader when one of its own
parameters is handed to ``os.environ.get`` / ``os.getenv``. At a call to such a
function, the first argument is resolved through the existing constant resolver
-- which already follows imports -- and a resolvable string becomes a real read,
attributed to the CALL SITE, because that is where the choice of variable is
made. An argument that does not resolve stays a dynamic read, exactly as before:
this widens what can be proven, never what is guessed.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from daedalus.mapping import switches as sw


ROOT = Path(__file__).resolve().parents[1]

FILES = {
    "mini/__init__.py": "",
    # the constant that travels: defined here, used in the sibling
    "mini/names.py": 'ENV_IMPORTED = "MINI_IMPORTED"\n',
    "mini/conf.py": (
        "import os\n"
        "from mini.names import ENV_IMPORTED\n"
        "\n"
        'ENV_LOCAL = "MINI_LOCAL"\n'
        "DEFAULT_LOCAL = 3\n"
        "\n"
        "\n"
        "def _env_int(name, default):\n"
        "    raw = os.environ.get(name)\n"
        "    return int(raw) if raw else default\n"
        "\n"
        "\n"
        "def _not_an_env_reader(name, default):\n"
        "    return f'{name}={default}'\n"
        "\n"
        "\n"
        "def local_ceiling():\n"
        "    return _env_int(ENV_LOCAL, DEFAULT_LOCAL)\n"
        "\n"
        "\n"
        "def imported_ceiling():\n"
        "    return _env_int(ENV_IMPORTED, 1)\n"
        "\n"
        "\n"
        "def unresolvable(chosen):\n"
        "    return _env_int(chosen, 0)\n"
        "\n"
        "\n"
        "def decoy():\n"
        "    return _not_an_env_reader(ENV_LOCAL, 0)\n"
    ),
}


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    for rel, text in FILES.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


def _names(report) -> set[str]:
    return {s.name for s in report.env_switches}


def test_a_local_constant_passed_to_an_env_helper_is_a_read(repo: Path) -> None:
    assert "MINI_LOCAL" in _names(sw.analyse(repo))


def test_an_imported_constant_passed_to_an_env_helper_is_a_read(
    repo: Path,
) -> None:
    """The resolver already follows imports; the helper hop is what was new."""
    assert "MINI_IMPORTED" in _names(sw.analyse(repo))


def test_the_read_is_attributed_to_the_call_site(repo: Path) -> None:
    """The call site is where the variable is chosen, not the helper body."""
    report = sw.analyse(repo)
    switch = next(s for s in report.env_switches if s.name == "MINI_LOCAL")
    modules = {site.module for site in switch.sites}
    assert "mini/conf.py" in modules


def test_an_unresolvable_argument_invents_nothing(repo: Path) -> None:
    """`unresolvable(chosen)` must not manufacture a switch named 'chosen'."""
    assert "chosen" not in _names(sw.analyse(repo))


def test_a_helper_that_does_not_read_the_environment_is_not_followed(
    repo: Path,
) -> None:
    """`decoy()` passes ENV_LOCAL to a formatter. That is not a read.

    Without this the rule would turn every function taking a name-shaped
    constant into an environment read.
    """
    report = sw.analyse(repo)
    switch = next(s for s in report.env_switches if s.name == "MINI_LOCAL")
    lines = {site.line for site in switch.sites}
    decoy_line = FILES["mini/conf.py"].splitlines().index(
        "    return _not_an_env_reader(ENV_LOCAL, 0)") + 1
    assert decoy_line not in lines


# --------------------------------------------------- the tree this was found in

BUDGET_SWITCHES = ("DAEDALUS_BUDGET_USD", "DAEDALUS_BUDGET_MAX_CALLS")


def test_the_period_spend_ceiling_is_seen_as_read() -> None:
    """Regression pin against the real repository.

    These two are documented in .env.example and are the monetary axis of
    master plan §4.1. Reporting them as read by nothing is the instrument
    calling the spend ceiling dead configuration.
    """
    report = sw.analyse(ROOT)
    names = {s.name for s in report.env_switches}
    for name in BUDGET_SWITCHES:
        assert name in names, name


def test_the_spend_ceiling_is_not_reported_as_documented_never_read() -> None:
    report = sw.analyse(ROOT)
    doc_only = {
        entry.documented for entry in report.drift
        if entry.kind == "documented_never_read"
    }
    for name in BUDGET_SWITCHES:
        assert name not in doc_only, (
            f"{name} is read at a call site the scanner can resolve; "
            f"reporting it as dead configuration is a false accusation about "
            f"the monetary ceiling"
        )
