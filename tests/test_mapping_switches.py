# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The switch inventory must classify a KNOWN repo, not just run without error.

The fixture below is a miniature repo built to contain, on purpose, every case
the classifier is supposed to separate: a dark gate, an override that only
looks dark, an inverted switch, a variable read in three modules with two
different defaults, a name the docs promise and no module reads, a name the
code reads and no doc mentions, and a near-miss pair that is the silent bug
(operator sets the documented spelling, nothing happens).

No network, no model, no vendor CLI: everything is a temp directory.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from daedalus.mapping.switches import SCHEMA, analyse


PKG_SWITCHES = '''\
"""Fixture module."""
import os
from pathlib import Path

DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_DB = Path("runs/spine.sqlite3")
_MINT_ENV = "FIXTURE_AUTO_MINT"


def mint_enabled() -> bool:
    """Turn a landed write into an eval task."""
    return os.environ.get(_MINT_ENV, "").strip().lower() in ("1", "true")


def slice_budget() -> int:
    """Token budget for distilled slice context."""
    return max(0, int(os.environ.get("FIXTURE_SLICE_TOKENS", "0")))


def db_path() -> Path:
    """Where the ledger lives."""
    env = os.environ.get("FIXTURE_DB", "").strip()
    return Path(env) if env else DEFAULT_DB


def cache_enabled() -> bool:
    """Disable the on-disk cache."""
    return os.environ.get("FIXTURE_NO_CACHE", "").strip() not in ("1", "true")


def host() -> str:
    """Ollama endpoint."""
    return os.environ.get("FIXTURE_HOST", DEFAULT_HOST)


def token() -> str:
    """Auth for the remote lane."""
    return os.environ.get("FIXTURE_RTX_TOKEN", "").strip()


def strict_home() -> str:
    """Read that must be set or the process dies."""
    return os.environ["FIXTURE_REQUIRED"]


def report(deep: bool = False, probe_remote: bool = False,
           force: bool = False, count: int = 3) -> dict:
    """Public entry point with two gates and one safety flag."""
    return {"deep": deep, "probe": probe_remote, "force": force, "count": count}


def _private(enabled: bool = False) -> bool:
    """Private helpers are not entry points."""
    return enabled
'''

PKG_OTHER = '''\
"""Second reader of the same variable, with a DIFFERENT default."""
import os

DEFAULT_HOST = "http://gpu.local:11434"


def host() -> str:
    return os.environ.get("FIXTURE_HOST", "http://127.0.0.1:11434")


def other_host() -> str:
    return os.environ.get("FIXTURE_HOST", DEFAULT_HOST)


def shared_host() -> str:
    from .switches import DEFAULT_HOST as SHARED

    return os.environ.get("FIXTURE_HOST", SHARED)


def routed(local: bool) -> str:
    """Same alias, two modules, one function -- the shape ikarus_os really has."""
    if local:
        from .switches import DEFAULT_HOST as PICK

        return os.environ.get("FIXTURE_ROUTED", PICK)
    from .alt import DEFAULT_HOST as PICK

    return os.environ.get("FIXTURE_ROUTED", PICK)


class Client:
    def __init__(self) -> None:
        self.key = os.environ.get("FIXTURE_API_KEY", "")


PROVIDERS = [{"name": "fixture", "env_key": "FIXTURE_API_KEY"}]
'''

DOCS = """\
# Fixture handbook

Set `FIXTURE_AUTO_MINT=1` to enable minting. The slice wire ships dark:
`FIXTURE_SLICE_TOKENS=0` by default.

Point the remote lane at your box:

    FIXTURE_HOST=http://gpu.local:11434
    FIXTURE_RTX_OLLAMA_TOKEN=hunter2

Server-side tuning: set `FIXTURE_NUM_PARALLEL=1` machine-wide.

`FIXTURE_API_KEY=` leaves the external lane dormant.
`FIXTURE_REQUIRED=` must be exported.
"""


@pytest.fixture(scope="module")
def report(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("switchrepo")
    pkg = root / "fixturepkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "switches.py").write_text(PKG_SWITCHES, encoding="utf-8")
    (pkg / "other.py").write_text(PKG_OTHER, encoding="utf-8")
    (pkg / "alt.py").write_text(
        'DEFAULT_HOST = "http://alt.local:11434"\n', encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "HANDBOOK.md").write_text(DOCS, encoding="utf-8")
    (root / "projects").mkdir()
    (root / "projects" / "demo.json").write_text(json.dumps({
        "name": "demo",
        "_comment": "prose, not a switch",
        "policy": {"default_deny": True, "high_risk_paths": []},
        "team": {"auto_tests": False, "auto_docs": True},
        "unread_key": False,
    }), encoding="utf-8")
    (pkg / "keys.py").write_text(
        'READS = ["default_deny", "high_risk_paths", "auto_tests", "auto_docs"]\n',
        encoding="utf-8")
    return analyse(root)


def _switch(report, name):
    for switch in report.env_switches:
        if switch.name == name:
            return switch
    raise AssertionError(f"{name} not found in {[s.name for s in report.env_switches]}")


def test_schema_and_determinism(report, tmp_path_factory):
    assert report.schema == SCHEMA
    again = analyse(report.root)
    assert again.to_dict() == report.to_dict()
    names = [s.name for s in report.env_switches]
    assert names == sorted(names)


def test_dark_gate_is_classified_dark(report):
    mint = _switch(report, "FIXTURE_AUTO_MINT")
    assert (mint.kind, mint.state, mint.default) == ("flag", "OFF", "''")
    assert mint.dark is True
    assert mint.gates.startswith("Turn a landed write")
    assert mint.sites[0].via == "environ.get"


def test_env_name_behind_a_module_constant_is_resolved(report):
    # The read is `os.environ.get(_MINT_ENV, "")`; a scanner that only matches
    # string literals reports this feature as having no switch at all.
    assert [s.line for s in _switch(report, "FIXTURE_AUTO_MINT").sites]


def test_zero_default_int_gate_is_dark(report):
    budget = _switch(report, "FIXTURE_SLICE_TOKENS")
    assert (budget.kind, budget.state, budget.default) == ("number", "OFF", "'0'")
    assert budget.dark is True


def test_override_with_a_fallback_is_not_dark(report):
    db = _switch(report, "FIXTURE_DB")
    assert db.state == "OFF"
    assert db.dark is False
    assert "conditional expression" in db.sites[0].fallback


def test_inverted_switch_is_never_dark(report):
    no_cache = _switch(report, "FIXTURE_NO_CACHE")
    assert no_cache.polarity == "disable"
    assert no_cache.state == "OFF"
    assert no_cache.dark is False


def test_real_default_reads_as_on(report):
    host = _switch(report, "FIXTURE_HOST")
    assert host.state == "ON"
    assert host.dark is False


def test_multi_default_conflict_is_reported(report):
    host = _switch(report, "FIXTURE_HOST")
    assert len(host.sites) == 4
    # Compared by VALUE, so the two spellings of 127.0.0.1 collapse and only the
    # module that really falls back somewhere else counts as a disagreement.
    assert host.conflicting_defaults == (
        "'http://127.0.0.1:11434'", "'http://gpu.local:11434'")
    assert report.counts.conflicting_env >= 1
    modules = {site.module for site in host.sites}
    assert modules == {"fixturepkg/other.py", "fixturepkg/switches.py"}


def test_default_imported_from_another_module_is_resolved(report):
    host = _switch(report, "FIXTURE_HOST")
    shared = [s for s in host.sites if s.default == "SHARED"]
    assert len(shared) == 1
    assert shared[0].default_literal == "http://127.0.0.1:11434"


def test_one_alias_bound_to_two_modules_resolves_per_line(report):
    routed = _switch(report, "FIXTURE_ROUTED")
    values = [s.default_literal for s in routed.sites]
    assert values == ["http://127.0.0.1:11434", "http://alt.local:11434"]
    assert routed.conflicting_defaults == (
        "'http://127.0.0.1:11434'", "'http://alt.local:11434'")


def test_required_read_is_not_dark(report):
    required = _switch(report, "FIXTURE_REQUIRED")
    assert required.state == "REQUIRED"
    assert required.dark is False
    assert required.sites[0].via == "environ[]"


def test_registry_declared_env_key_is_found(report):
    key = _switch(report, "FIXTURE_API_KEY")
    assert key.kind == "secret"
    assert key.dark is True
    assert {site.via for site in key.sites} == {"environ.get", "registry"}


def test_documented_but_never_read(report):
    drift = [d for d in report.drift if d.kind == "documented_never_read"]
    # FIXTURE_NUM_PARALLEL is documented tuning nothing in the package reads;
    # FIXTURE_RTX_OLLAMA_TOKEN is the documented half of the near-miss pair.
    assert [d.documented for d in drift] == [
        "FIXTURE_NUM_PARALLEL", "FIXTURE_RTX_OLLAMA_TOKEN"]
    assert all(d.doc_sites and d.code_sites == () for d in drift)


def test_read_but_never_documented(report):
    names = {d.read for d in report.drift if d.kind == "read_never_documented"}
    assert "FIXTURE_RTX_TOKEN" in names
    assert "FIXTURE_DB" in names
    assert "FIXTURE_AUTO_MINT" not in names       # documented as `NAME=1`


def test_near_miss_name_mismatch_is_the_silent_bug(report):
    mismatches = [d for d in report.drift if d.kind == "name_mismatch"]
    assert [(d.documented, d.read) for d in mismatches] == [
        ("FIXTURE_RTX_OLLAMA_TOKEN", "FIXTURE_RTX_TOKEN")]
    assert report.counts.name_mismatches == 1


def test_unrelated_names_are_not_accused_of_being_the_same_variable(report):
    pairs = {(d.documented, d.read) for d in report.drift if d.kind == "name_mismatch"}
    assert ("FIXTURE_NUM_PARALLEL", "FIXTURE_SLICE_TOKENS") not in pairs


def test_param_gates_split_from_safety_flags(report):
    params = {(p.qualname, p.param): p for p in report.param_switches}
    assert params[("report", "deep")].dark is True
    assert params[("report", "probe_remote")].dark is True
    assert params[("report", "force")].dark is False      # safety posture
    assert ("report", "count") not in params              # not a boolean
    assert ("_private", "enabled") not in params          # not an entry point
    assert all(p.default == "False" and p.state == "OFF" for p in report.param_switches)


def test_config_keys_are_classified(report):
    config = {(c.key, c.source.endswith("demo.json")): c for c in report.config_switches}
    keys = {c.key for c in report.config_switches}
    assert "team.auto_tests" in keys
    assert "policy.high_risk_paths" in keys
    assert "_comment" not in keys
    assert config[("team.auto_tests", True)].dark is True
    assert config[("policy.default_deny", True)].state == "ON"
    assert config[("unread_key", True)].read_in_code is False
    assert config[("unread_key", True)].dark is False


def test_counts_agree_with_the_listings(report):
    counts = report.counts
    assert counts.env_switches == len(report.env_switches)
    assert counts.env_sites == sum(len(s.sites) for s in report.env_switches)
    assert counts.dark_env == len(report.dark_env_switches())
    assert counts.drift == len(report.drift)
    assert counts.modules_scanned == 5
    assert report.unparsable == ()


def test_report_is_json_serialisable(report):
    text = json.dumps(report.to_dict(), sort_keys=True)
    assert json.loads(text)["schema"] == SCHEMA


def test_syntax_error_is_reported_not_raised(tmp_path: Path):
    (tmp_path / "broken.py").write_text("def (:\n", encoding="utf-8")
    result = analyse(tmp_path)
    assert result.unparsable and "broken.py" in result.unparsable[0]
    assert result.env_switches == ()


def test_this_repo_still_analyses(request):
    """Guards the real invariant: the artifact must ALWAYS exist."""
    root = Path(__file__).resolve().parents[1]
    result = analyse(root)
    assert result.counts.env_switches > 20
    assert result.counts.dark_env > 0
    assert result.unparsable == ()
    assert "OFFLOAD_SLICE_TOKENS" in {s.name for s in result.dark_env_switches()}
