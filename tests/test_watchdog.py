"""Tests for tools/watchdog.py -- the background docs/work watchdogs.

Every test uses a throwaway git repository; nothing spawns a model (the
spawn is monkeypatched or dry-run) and nothing touches the scheduler.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("watchdog", ROOT / "tools" / "watchdog.py")
wd = importlib.util.module_from_spec(SPEC)
sys.modules["watchdog"] = wd  # dataclasses under `from __future__ import annotations` need the module registered
SPEC.loader.exec_module(wd)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    (r / "daedalus").mkdir(parents=True)
    (r / "docs").mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    (r / "daedalus" / "old_hook.py").write_text("x = 1\n", encoding="utf-8")
    (r / "docs" / "guide.md").write_text("# guide\nsee [spec](spec.md) and daedalus/old_hook.py\n", encoding="utf-8")
    (r / "docs" / "spec.md").write_text("# spec\n", encoding="utf-8")
    (r / "README.md").write_text("readme `spec[\"fn\"](sb)` prose\n", encoding="utf-8")
    _git(r, "add", ".")
    _git(r, "commit", "-q", "-m", "init")
    return r


# --------------------------------------------------------------------------
# docs drift
# --------------------------------------------------------------------------


def test_docs_drift_is_empty_on_a_consistent_tree(repo: Path) -> None:
    assert wd.docs_drift(repo) == []


def test_docs_drift_finds_deleted_file_mentions_and_dead_links(repo: Path) -> None:
    _git(repo, "rm", "-q", "daedalus/old_hook.py", "docs/spec.md")
    _git(repo, "commit", "-q", "-m", "remove")
    kinds = {(d.kind, d.subject) for d in wd.docs_drift(repo)}
    assert ("deleted_file_mentioned", "docs/guide.md:2") in kinds
    assert ("dead_link", "docs/guide.md:2") in kinds
    # a marked mention is not drift
    (repo / "docs" / "guide.md").write_text(
        "# guide\nsee [spec](spec.md) and daedalus/old_hook.py (replaced by daedalus/hooks/, 2026-08-23)\n", encoding="utf-8"
    )
    kinds = {d.kind for d in wd.docs_drift(repo)}
    assert "deleted_file_mentioned" not in kinds and "dead_link" in kinds


def test_prose_parentheses_are_not_links(repo: Path) -> None:
    assert not [d for d in wd.docs_drift(repo) if d.kind == "dead_link"]


def test_unknown_map_head_is_not_drift(repo: Path) -> None:
    (repo / "docs" / "architecture-state.json").write_text(json.dumps({"repo_state": {"head": "unknown"}}), encoding="utf-8")
    assert not [d for d in wd.docs_drift(repo) if d.kind == "architecture_state_stale"]
    (repo / "docs" / "architecture-state.json").write_text(json.dumps({"repo_state": {"head": "deadbeef"}}), encoding="utf-8")
    assert [d for d in wd.docs_drift(repo) if d.kind == "architecture_state_stale"]


def test_docs_pass_skips_while_another_lane_commits(repo: Path, monkeypatch) -> None:
    monkeypatch.setattr(wd, "run_claude", lambda *a, **k: pytest.fail("model must not be spawned"))
    res = wd.docs_pass(repo, env={})
    assert res["skipped"].startswith("HEAD moved")  # the fixture commit is seconds old
    (repo / ".git" / "index.lock").write_text("x")
    res = wd.docs_pass(repo, env={})
    assert res["skipped"] == ".git/index.lock exists"


def test_docs_pass_spawns_only_on_drift(repo: Path, monkeypatch) -> None:
    monkeypatch.setattr(wd, "head_quiet", lambda root, now=None: (True, ""))
    calls = []
    monkeypatch.setattr(wd, "run_claude", lambda root, prompt, **k: calls.append(prompt) or wd.ModelRun(True, "done", 0.01, 3, 1.0))
    assert wd.docs_pass(repo, env={})["outcome"] == "no drift"
    assert calls == []
    _git(repo, "rm", "-q", "docs/spec.md")
    _git(repo, "commit", "-q", "-m", "remove")
    res = wd.docs_pass(repo, env={})
    assert res["outcome"] == "sweep ran" and len(calls) == 1
    assert "dead_link" in calls[0] and "git commit -F runs/watchdog/docs-commitmsg.txt --" in calls[0]
    assert (repo / wd.SWEEPS_LOG_REL).read_text().strip().endswith("turns=3")
    state = wd.load_json(repo / wd.STATE_REL)
    assert wd.model_runs_today(state) == 1


def test_a_hundred_recorded_model_runs_do_not_stop_the_next_sweep(repo: Path, monkeypatch) -> None:
    """Owner decision 2026-08-24: no self-imposed spending limit. A state that
    would have tripped both the old DAILY_MODEL_CAP and WATCHDOG_DAILY_USD
    must not stop a sweep with findings."""

    monkeypatch.setattr(wd, "head_quiet", lambda root, now=None: (True, ""))
    calls = []
    monkeypatch.setattr(wd, "run_claude", lambda root, prompt, **k: calls.append(prompt) or wd.ModelRun(True, "done", 0.9, 3, 1.0))
    day = time.strftime("%Y-%m-%d", time.gmtime())
    wd.save_json(repo / wd.STATE_REL, {"model_runs": {day: 100}, "model_spend_usd": {day: 500.0}})
    _git(repo, "rm", "-q", "docs/spec.md")
    _git(repo, "commit", "-q", "-m", "remove")
    res = wd.docs_pass(repo, env={})
    assert res["outcome"] == "sweep ran" and len(calls) == 1


def test_pause_switches(repo: Path) -> None:
    assert wd.paused(repo, env={}) == ""
    assert wd.paused(repo, env={"DAEDALUS_WATCHDOG": "off"}) == "DAEDALUS_WATCHDOG=off"
    (repo / wd.PAUSE_REL).parent.mkdir(parents=True, exist_ok=True)
    (repo / wd.PAUSE_REL).write_text("")
    assert wd.paused(repo, env={}).endswith("exists")
    assert wd.docs_pass(repo, env={})["skipped"].endswith("exists")


# --------------------------------------------------------------------------
# work health and anomalies
# --------------------------------------------------------------------------


def test_health_facts_carry_ages_and_counts(repo: Path, tmp_path: Path) -> None:
    (repo / "daedalus" / "new.py").write_text("y = 2\n", encoding="utf-8")
    facts = wd.health(repo, temp_root=tmp_path / "nothing")
    assert facts["branch"] == "main" and len(facts["head"]) == 8
    assert facts["last_commit_age_s"] is not None and facts["last_commit_age_s"] < 300
    assert facts["dirty_files"] == 1 and facts["dirty_source_files"] == 1
    assert facts["index_lock_age_s"] is None
    assert facts["last_docs_sweep_age_s"] is None
    assert facts["temp_claude_entries"] is None


def test_anomaly_rules() -> None:
    base = {"shift": {"goal": "", "until": "", "expired": False}, "last_commit_age_s": 10,
            "index_lock_age_s": None, "oldest_dirty_source_age_s": None, "dirty_source_files": 0,
            "last_docs_sweep_age_s": 60, "last_recorded_test_age_s": None, "disk_free_gb": 100.0,
            "temp_claude_entries": 10}
    assert wd.anomalies(base) == []
    ids = lambda f: [a.id for a in wd.anomalies({**base, **f})]  # noqa: E731
    assert ids({"shift": {"goal": "g", "until": "", "expired": False}, "last_commit_age_s": 4 * 3600}) == ["commit_gap"]
    assert ids({"last_commit_age_s": 4 * 3600}) == []  # no shift declared: a quiet tree is allowed
    assert ids({"shift": {"goal": "g", "until": "12:00", "expired": True}}) == ["shift_expired"]
    assert ids({"index_lock_age_s": 11 * 60}) == ["stale_index_lock"]
    assert ids({"oldest_dirty_source_age_s": 7 * 3600, "dirty_source_files": 3}) == ["dirty_source_stale"]
    assert ids({"last_docs_sweep_age_s": None}) == ["docs_sweep_stale"]
    assert ids({"dirty_source_files": 1, "last_recorded_test_age_s": 5 * 3600}) == ["tests_stale"]
    assert ids({"disk_free_gb": 2.0}) == ["disk_low"]
    assert ids({"temp_claude_entries": 999}) == ["temp_bloat"]


def test_work_pass_writes_health_notifies_once_and_reports_only_when_head_moved(repo: Path, monkeypatch, tmp_path: Path) -> None:
    toasts, vault, spawns = [], [], []
    monkeypatch.setattr(wd, "toast", lambda t, m: toasts.append(m))
    monkeypatch.setattr(wd, "vault_append", lambda root, line, now=None: vault.append(line))
    monkeypatch.setattr(wd, "run_claude", lambda root, prompt, **k: spawns.append(prompt) or wd.ModelRun(True, "report text", 0.002, 1, 2.0))
    monkeypatch.setattr(wd, "health", lambda root, now=None, temp_root=None: {
        "ts": "t", "branch": "main", "head": "abcd1234", "last_commit_age_s": 5, "last_commit_subject": "s",
        "dirty_files": 0, "dirty_source_files": 0, "oldest_dirty_source_age_s": None, "index_lock_age_s": None,
        "last_docs_sweep_age_s": None, "hook_ledger_age_s": None, "sessions_active_30m": 0,
        "last_recorded_test_age_s": None, "shift": {"goal": "", "until": "", "expired": False},
        "disk_free_gb": 50.0, "temp_claude_entries": 1})
    t0 = 1_700_000_000.0
    r1 = wd.work_pass(repo, env={}, now=t0)
    assert r1["notified"] == ["docs_sweep_stale"] and toasts and vault
    assert (repo / wd.HEALTH_MD_REL).read_text().count("docs_sweep_stale") == 1
    assert len(spawns) == 1 and "use NO tools" in spawns[0]
    assert (repo / wd.REPORT_MD_REL).read_text().endswith("report text\n")
    r2 = wd.work_pass(repo, env={}, now=t0 + 600)
    assert r2["notified"] == [] and len(toasts) == 1  # same anomaly: no re-toast
    assert len(spawns) == 1  # HEAD unchanged, gap not reached: no second report
    r3 = wd.work_pass(repo, env={}, now=t0 + 4 * 3600)
    assert r3["notified"] == ["docs_sweep_stale"]  # re-notified after RENOTIFY_S
    assert len(spawns) == 1  # still the same HEAD: no report


def test_report_prompt_is_self_contained(repo: Path) -> None:
    facts = wd.health(repo, temp_root=repo / "none")
    prompt = wd.report_prompt(repo, facts, wd.anomalies(facts))
    assert "use NO tools" in prompt and "git log -12" in prompt and facts["head"] in prompt


# --------------------------------------------------------------------------
# scheduling and registration
# --------------------------------------------------------------------------


def test_one_model_call_is_billed_once_at_the_measured_price(repo: Path, monkeypatch, tmp_path) -> None:
    """MEASURED 2026-08-24: a bare reserve/settle pair had the process guard
    bill each `claude` spawn a SECOND time at the flat $3 worst case, so every
    sweep cost $3.42 instead of $0.42 and five of them exhausted the shared
    daily ceiling -- which would have refused any other lane's model call too.

    The billing runs against a PRIVATE ledger here; a test that spends on the
    shared one would be the same defect in a smaller hat.
    """

    import json as _json

    # TWO ledgers matter here, and the test has to watch both. The explicit
    # reservation always writes to the dedicated one (own_ledger); but the
    # process guard's AUTOMATIC billing on an unguarded subprocess.run call
    # never learns about that override -- it calls plain reserve(vendor,
    # label=label) with no `led=`, which resolves to whatever DAEDALUS_
    # BUDGET_LEDGER/DEFAULT_LEDGER_PATH names. A regression that drops the
    # explicit mode would therefore bill the DEDICATED ledger correctly AND
    # bill a phantom $3 to the DEFAULT one -- invisible to a test that only
    # reads the dedicated file, which is exactly the coverage gap measured
    # while wiring `led=own_ledger(root)` into run_claude (2026-08-24): the
    # first version of this test kept passing with the double-billing defect
    # reinstated, because it never looked at the ledger the phantom charge
    # actually lands on.
    ledger_path = repo / wd.WATCHDOG_LEDGER_REL
    default_ledger_path = tmp_path / "default-ledger.json"
    monkeypatch.setenv("DAEDALUS_BUDGET_LEDGER", str(default_ledger_path))
    from daedalus import budget

    budget.reset_default_ledger()

    class _Proc:
        returncode = 0
        stdout = _json.dumps({"result": "ok", "total_cost_usd": 0.07, "num_turns": 1})
        stderr = ""

    real_run = subprocess.run

    def fake_run(argv, **kwargs):
        if isinstance(argv, (list, tuple)) and str(argv[0]).lower().endswith(("claude", "claude.exe")):
            return _Proc()
        return real_run(argv, **kwargs)

    # ORDER MATTERS AND IS THE POINT OF THE TEST. The stub goes in FIRST and the
    # process guard is installed on top, so the guard's wrapper is the thing
    # run_claude calls -- exactly as in production. Patching subprocess.run
    # after installing the guard would REPLACE the wrapper, and the test could
    # never see the double billing it exists to catch.
    budget.uninstall_process_guard()
    monkeypatch.setattr(wd.shutil, "which", lambda name: "C:/fake/claude.exe")
    monkeypatch.setattr(subprocess, "run", fake_run)
    budget.install_process_guard()
    assert subprocess.run is not fake_run, "the guard must be wrapping the stub"
    try:
        run = wd.run_claude(repo, "prompt", label="test.billing", allowed_tools="", max_turns=1)
    finally:
        budget.uninstall_process_guard()

    assert run.ok and run.cost_usd == 0.07
    data = _json.loads(ledger_path.read_text(encoding="utf-8"))
    assert round(data["spent_usd"], 6) == 0.07, data["entries"]
    assert data["calls"] == 1
    assert not data.get("open"), "a leaked reservation holds the ceiling until the period rolls over"
    labels = [e.get("label") for e in data["entries"] if e.get("kind") == "settle"]
    assert labels == ["test.billing"], labels
    # THE ONE THAT CATCHES THE REGRESSION THIS TEST EXISTS FOR: nothing may
    # ever reach the default ledger, because it is the one a dropped explicit
    # mode falls back to.
    if default_ledger_path.exists():
        default_data = _json.loads(default_ledger_path.read_text(encoding="utf-8"))
        assert default_data.get("entries", []) == [], default_data
        assert default_data.get("spent_usd", 0) == 0


def test_the_toast_carries_no_measured_text_in_its_argv(monkeypatch) -> None:
    """MEASURED 2026-08-24: an anomaly toast whose text named `%TEMP%/claude`
    was classified by budget.classify_argv as an Anthropic CLI call and
    reserved $3 of the SHARED ceiling -- for a popup. Every toast mentioning
    that path would have booked $3.

    The classifier is right to be broad; a background job putting measured text
    into an argv is what was wrong. The message goes through the environment.
    """

    from daedalus.budget import classify_argv

    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = list(argv)
        seen["env"] = kwargs.get("env") or {}
        class _P:
            returncode = 0
        return _P()

    monkeypatch.setattr(wd.os, "name", "nt")
    monkeypatch.setattr(wd.subprocess, "run", fake_run)
    wd.toast("Daedalus work watchdog", "temp_bloat: %TEMP%/claude holds 856 top-level entries")

    rendered = " ".join(seen["argv"]).lower()
    assert "claude" not in rendered, seen["argv"]
    assert "856" not in rendered, "no measured text in the argv"
    assert classify_argv(seen["argv"]) is None, "a popup must not read as a paid vendor call"
    # ... and the message still reaches PowerShell
    assert seen["env"][wd._TOAST_TEXT_ENV].endswith("856 top-level entries")
    assert seen["env"][wd._TOAST_TITLE_ENV] == "Daedalus work watchdog"
    # the old inline form WOULD have been classified, which is what this pins
    old_form = ["powershell", "-NoProfile", "-Command",
                "(New-Object -ComObject Wscript.Shell).Popup('%TEMP%/claude holds 856', 8, 'x', 48)"]
    assert classify_argv(old_form) == "anthropic_cli"


def test_the_watchdog_never_raises_the_shared_ceiling(monkeypatch) -> None:
    """The first version set DAEDALUS_BUDGET_USD for its own process, which
    raises the ceiling on the ledger every lane shares."""

    import inspect

    source = inspect.getsource(wd)
    assert 'setdefault("DAEDALUS_BUDGET_USD"' not in source
    assert 'environ["DAEDALUS_BUDGET_USD"]' not in source
    assert "os.environ[" not in source, "the watchdog must not write the environment at all"


def test_spend_is_recorded_for_observability_and_never_gates(repo: Path, monkeypatch) -> None:
    monkeypatch.setattr(wd, "head_quiet", lambda root, now=None: (True, ""))
    calls = []
    monkeypatch.setattr(wd, "run_claude",
                        lambda root, prompt, **k: calls.append(prompt) or wd.ModelRun(True, "done", 0.9, 3, 1.0))
    _git(repo, "rm", "-q", "docs/spec.md")
    _git(repo, "commit", "-q", "-m", "remove")

    assert wd.docs_pass(repo, env={})["outcome"] == "sweep ran"
    state = wd.load_json(repo / wd.STATE_REL)
    assert wd.spend_today(state) == 0.9          # the MEASURED cost, not the estimate
    # the stub never actually edits the repo, so the drift persists; the point
    # is that recorded spend does not stop the NEXT sweep from trying again
    assert wd.docs_pass(repo, env={})["outcome"] == "sweep ran"


def test_a_call_succeeds_against_an_exhausted_shared_ledger(repo: Path, monkeypatch, tmp_path) -> None:
    """The point of the dedicated ledger: the shared budget every interactive
    lane uses can read as fully spent, and the watchdog must still run.
    MEASURED 2026-08-24: the opposite used to be true in both directions --
    raising the shared ceiling let the watchdog starve other lanes, and a
    self-imposed cap on shared state let other lanes starve the watchdog."""

    import json as _json

    from daedalus import budget

    shared = tmp_path / "shared-ledger.json"
    shared.write_text(_json.dumps({
        "schema": 1, "period_key": time.strftime("%Y-%m-%d", time.gmtime()),
        "spent_usd": 999.0, "calls": 40, "open": {}, "entries": [], "envelopes": {},
    }), encoding="utf-8")
    monkeypatch.setenv("DAEDALUS_BUDGET_LEDGER", str(shared))
    budget.reset_default_ledger()

    exe = repo / "fake-claude.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(wd.shutil, "which", lambda name: str(exe))

    class _Proc:
        returncode = 0
        stdout = _json.dumps({"result": "ok", "total_cost_usd": 0.31, "num_turns": 2})
        stderr = ""

    def fake_run(argv, **kw):
        return _Proc()

    budget.uninstall_process_guard()
    monkeypatch.setattr(wd.subprocess, "run", fake_run)
    budget.install_process_guard()
    try:
        run = wd.run_claude(repo, "prompt", label="test.unlimited", allowed_tools="", max_turns=1)
    finally:
        budget.uninstall_process_guard()

    assert run.ok and run.cost_usd == 0.31, run.reason
    own = _json.loads((repo / wd.WATCHDOG_LEDGER_REL).read_text(encoding="utf-8"))
    assert own["spent_usd"] == 0.31
    shared_after = _json.loads(shared.read_text(encoding="utf-8"))
    assert shared_after["spent_usd"] == 999.0, "the shared ledger must be untouched"


def test_docs_and_work_passes_do_not_block_each_other(repo: Path) -> None:
    """MEASURED in runs/watchdog/watchdog.log: with one shared lock the docs
    sweep -- which holds it for as long as a model call takes -- skipped every
    work pass that ticked while it ran, which on aligned 15/30-minute schedules
    is every other one, all night."""

    with wd.PassLock(repo, "docs") as docs_held:
        assert docs_held
        with wd.PassLock(repo, "work") as work_held:
            assert work_held, "a running docs sweep must not skip the health measurement"
        with wd.PassLock(repo, "docs") as second_docs:
            assert not second_docs, "two docs sweeps must still not overlap"


def test_task_commands_are_per_user_minute_triggers_with_the_repo_script(repo: Path) -> None:
    cmds = wd.task_commands(repo, "install")
    assert [c[0] for c in cmds] == ["schtasks", "schtasks"]
    joined = [" ".join(c) for c in cmds]
    assert any("/MO 30" in j and "DocsWatchdog" in j and "watchdog.py\" docs" in j for j in joined)
    assert any("/MO 15" in j and "WorkWatchdog" in j and "watchdog.py\" work" in j for j in joined)
    assert all("/RL LIMITED" in j for j in joined)  # never elevated
    assert all("dangerously" not in j for j in joined)
    un = wd.task_commands(repo, "uninstall")
    assert all("/Delete" in c for c in un)


def test_watchdog_is_registered_with_spend_and_starts_centrally() -> None:
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, Effect, Wiring

    row = REGISTRY_BY_ID["tools.watchdog"]
    assert Effect.SPEND in row.effects and Effect.REPOSITORY_MUTATION in row.effects
    assert "budget.process_guard" in row.guard_contracts and row.wiring is Wiring.CENTRAL
    proc = subprocess.run([sys.executable, "tools/watchdog.py", "status"], capture_output=True, text=True, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr
    assert "model runs today" in proc.stdout


def test_run_claude_refuses_without_the_cli_and_dry_runs_without_spawning(repo: Path, monkeypatch) -> None:
    monkeypatch.setattr(wd.shutil, "which", lambda name: None)
    assert wd.run_claude(repo, "x", label="t", allowed_tools="", max_turns=1).reason == "claude CLI not on PATH"
    monkeypatch.setattr(wd.shutil, "which", lambda name: "C:/fake/claude")
    monkeypatch.setattr(wd.subprocess, "run", lambda *a, **k: pytest.fail("dry run must not spawn"))
    assert wd.run_claude(repo, "x", label="t", allowed_tools="", max_turns=1, dry=True).reason == "dry"
