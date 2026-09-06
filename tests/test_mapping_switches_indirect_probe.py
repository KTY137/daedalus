"""Bounded current-tree probe for indirect environment-reader admission.

G1-GARDEN-MAP-08 does not promote the legacy implementation.  It first asks
whether the current canonical gardening tree still has the defect that
packet/g1-map-02 measured: an environment variable chosen at a call to a helper
such as ``_env_float(ENV_CEILING, ...)`` is invisible when the helper itself
contains ``os.environ.get(name)``.

The probe is intentionally temporary.  If the current tree exhibits the blind
spot, the failing commit/blob remains evidence and this file is removed from the
live tree before packet closure.  A later implementation packet may then reuse
only the bounded semantics rather than importing the legacy mapping stack.
"""
from __future__ import annotations

from pathlib import Path

from daedalus.mapping import switches as sw


ROOT = Path(__file__).resolve().parents[1]
BUDGET_SWITCHES = frozenset({"DAEDALUS_BUDGET_USD", "DAEDALUS_BUDGET_MAX_CALLS"})


def test_env_name_passed_to_reader_helper_is_not_lost(tmp_path: Path) -> None:
    module = tmp_path / "sample.py"
    module.write_text(
        "import os\n"
        'ENV_LIMIT = "SAMPLE_LIMIT"\n'
        "DEFAULT_LIMIT = 3\n"
        "def _env_int(name, default):\n"
        "    raw = os.environ.get(name)\n"
        "    return int(raw) if raw else default\n"
        "def limit():\n"
        "    return _env_int(ENV_LIMIT, DEFAULT_LIMIT)\n",
        encoding="utf-8",
    )

    report = sw.analyse(tmp_path)
    assert "SAMPLE_LIMIT" in {switch.name for switch in report.env_switches}


def test_canonical_budget_switches_are_not_reported_as_dead_configuration() -> None:
    report = sw.analyse(ROOT)
    read_names = {switch.name for switch in report.env_switches}
    documented_only = {
        row.documented
        for row in report.drift
        if row.kind == "documented_never_read"
    }

    assert BUDGET_SWITCHES <= read_names
    assert BUDGET_SWITCHES.isdisjoint(documented_only)
