"""Indirect env-reader helpers must preserve switch identity at their call sites.

G1-GARDEN-MAP-09 (2026-09-06) selectively reintegrates the bounded semantic
fix licensed by MAP-08 from legacy evidence commit
``8bb907a633c59d4760fa396983472ac89f937b37``.  The scanner already resolves
literal, local-constant, and imported-constant environment names at direct read
sites.  This file pins the one missing shape used by the monetary ceiling:

    ENV_CEILING = "DAEDALUS_BUDGET_USD"

    def _env_float(name, default):
        raw = os.environ.get(name)
        ...

    return _env_float(ENV_CEILING, DEFAULT_CEILING_USD)

The helper is recognized structurally only when one of its own positional
parameters is actually handed to ``os.environ``.  The variable is attributed
to the call site, where the choice is made.  The existing constant/import
resolver is the only authority for indirect names; unresolved arguments remain
``dynamic_reads`` and a decoy helper cannot manufacture a switch.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from daedalus.mapping import switches as sw


ROOT = Path(__file__).resolve().parents[1]

FILES = {
    "mini/__init__.py": "",
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
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def _names(report) -> set[str]:
    return {switch.name for switch in report.env_switches}


def _line(source: str) -> int:
    return FILES["mini/conf.py"].splitlines().index(source) + 1


def test_local_constant_passed_to_env_helper_is_a_call_site_read(repo: Path) -> None:
    report = sw.analyse(repo)
    switch = next(s for s in report.env_switches if s.name == "MINI_LOCAL")
    call_line = _line("    return _env_int(ENV_LOCAL, DEFAULT_LOCAL)")
    assert {(site.module, site.line, site.via) for site in switch.sites} == {
        ("mini/conf.py", call_line, "helper")
    }


def test_imported_constant_uses_the_existing_constant_resolver(repo: Path) -> None:
    report = sw.analyse(repo)
    switch = next(s for s in report.env_switches if s.name == "MINI_IMPORTED")
    assert switch.sites[0].default_literal == "1"
    assert switch.sites[0].via == "helper"


def test_unresolvable_helper_argument_stays_dynamic_and_invents_nothing(
    repo: Path,
) -> None:
    report = sw.analyse(repo)
    assert "chosen" not in _names(report)
    unresolved_line = _line("    return _env_int(chosen, 0)")
    assert f"mini/conf.py:{unresolved_line} chosen" in report.dynamic_reads
    assert not any(entry.endswith(" name") for entry in report.dynamic_reads)


def test_decoy_helper_that_never_reads_environment_is_not_followed(repo: Path) -> None:
    report = sw.analyse(repo)
    switch = next(s for s in report.env_switches if s.name == "MINI_LOCAL")
    decoy_line = _line("    return _not_an_env_reader(ENV_LOCAL, 0)")
    assert decoy_line not in {site.line for site in switch.sites}


BUDGET_SWITCHES = ("DAEDALUS_BUDGET_USD", "DAEDALUS_BUDGET_MAX_CALLS")


def test_period_budget_switches_are_seen_as_real_reads() -> None:
    report = sw.analyse(ROOT)
    switches = {switch.name: switch for switch in report.env_switches}
    for name in BUDGET_SWITCHES:
        assert name in switches, name
        assert any(
            site.module == "daedalus/kernel/policy/ledger.py" and site.via == "helper"
            for site in switches[name].sites
        ), name


def test_period_budget_switches_are_not_reported_as_dead_documentation() -> None:
    report = sw.analyse(ROOT)
    documented_only = {
        entry.documented
        for entry in report.drift
        if entry.kind == "documented_never_read"
    }
    assert documented_only.isdisjoint(BUDGET_SWITCHES)
