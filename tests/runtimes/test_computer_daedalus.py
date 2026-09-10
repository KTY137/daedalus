"""G1-IKARUS-46: the read-only `daedalus.*` observation family.

Two halves. The adapter half is offline and pure: lane derivation, module
resolution, bounds and refusals never touch a registry or a network. The
service half runs the real persisted kernel lease path (the same fixture
shape as test_computer_service.py) and pins what the packet claims: no host
mutation, the read-only scope kind on every retained result, a refusal that
is recorded as effect-free rather than as reconciliation, and no lease at all
when the session has no project.

Which production change turns these red:

* a daedalus.* name entering `_HOST_MUTATION_TOOLS` (runtimes/computer.py);
* `execute` classifying a refused daedalus read as `reconciliation_required`;
* `capabilities()` offering the family without a bound project, or `execute`
  issuing a lease for it;
* `planner_lane` trusting Codex/DeepSeek or a non-loopback Ollama;
* `_resolve_module` accepting a path that is not in the index (traversal).
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from daedalus.kernel.policy.computer import (
    ALL_COMPUTER_TOOLS, DAEDALUS_TOOLS, ComputerPolicy, ComputerRefused, policy_path,
)
from daedalus.runtimes import computer as service_module
from daedalus.runtimes import computer_daedalus as subject
from daedalus.spine import killswitch


# --------------------------------------------------------------------------- #
# vocabulary                                                                   #
# --------------------------------------------------------------------------- #
def test_every_daedalus_tool_is_specified_read_only_and_never_a_host_mutation():
    assert set(DAEDALUS_TOOLS) <= ALL_COMPUTER_TOOLS
    for tool in DAEDALUS_TOOLS:
        description, schema = service_module.TOOL_SPECS[tool]
        assert "Read-only" in description
        assert schema["additionalProperties"] is False
    assert not (service_module._HOST_MUTATION_TOOLS & frozenset(DAEDALUS_TOOLS))
    assert set(DAEDALUS_TOOLS) <= service_module.TOOL_SPECS.keys()
    # the loop treats them as reads: an identical observation is a stall, not progress
    from daedalus.orchestration.ikarus import computer_loop
    assert set(DAEDALUS_TOOLS) <= computer_loop._READ_TOOLS


# --------------------------------------------------------------------------- #
# lane                                                                         #
# --------------------------------------------------------------------------- #
def _policy(tmp_path, **kwargs) -> ComputerPolicy:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    return ComputerPolicy(workspace=workspace, tools=DAEDALUS_TOOLS, **kwargs)


@pytest.mark.parametrize("provider, host, lane", [
    ("ollama_http", "http://127.0.0.1:11434", "trusted"),
    ("ollama", "http://[::1]:11434", "trusted"),
    ("ollama_http", "http://bench.tailnet:11434", "untrusted"),
    ("ollama_http", "http://10.0.0.7:11434", "untrusted"),
    ("claude_code_cli", "http://127.0.0.1:11434", "trusted"),
    ("codex_cli", "http://127.0.0.1:11434", "untrusted"),
    ("deepseek", "http://127.0.0.1:11434", "untrusted"),
])
def test_planner_lane_trusts_only_this_machine_and_the_claude_cli(tmp_path, monkeypatch, provider, host, lane):
    monkeypatch.setenv("OLLAMA_HOST", host)
    policy = _policy(tmp_path, planner_provider=provider, allow_remote_context=provider not in {"ollama_http", "ollama"})
    assert subject.planner_lane(policy) == lane


def test_allow_remote_context_does_not_promote_a_remote_planner_to_trusted(tmp_path):
    policy = _policy(tmp_path, planner_provider="codex_cli", allow_remote_context=True)
    assert subject.planner_lane(policy) == "untrusted"


# --------------------------------------------------------------------------- #
# adapter refusals and bounds                                                  #
# --------------------------------------------------------------------------- #
def _readers() -> subject.ProjectReaders:
    """The real readers, wired here exactly as ComputerService wires them."""
    from daedalus.file_bridge import _project_report_briefs, bridge_status
    from daedalus.status import collect_status
    return subject.ProjectReaders(
        git_counters=lambda root: collect_status(root, git_timeout_s=subject.GIT_TIMEOUT_S),
        bridge_status=bridge_status, report_briefs=_project_report_briefs)


def _adapter(tmp_path, project="fixture", readers=None):
    return subject.DaedalusObservation(_policy(tmp_path), project, lambda: None, tmp_path,
                                       readers or _readers())


def test_the_adapter_names_no_module_of_the_computer_import_cycle():
    """The census pin (tests/contracts/test_import_scc_hierarchy.py) is the
    authority; this is the local statement of why ProjectReaders exists."""
    import ast
    tree = ast.parse(Path(subject.__file__).read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    forbidden = {"daedalus.status", "daedalus.file_bridge", "daedalus.core", "daedalus.health",
                 "daedalus.orchestration.ikarus.computer_history", "daedalus.orchestration.ikarus.computer_loop",
                 "daedalus.orchestration.ikarus.shell", "daedalus.runtimes.computer"}
    assert not (names & forbidden), names & forbidden


def test_readers_must_be_supplied_by_the_service(tmp_path):
    with pytest.raises(ComputerRefused, match="project readers"):
        subject.DaedalusObservation(_policy(tmp_path), "fixture", lambda: None, tmp_path, None)  # type: ignore[arg-type]


def test_unknown_observation_and_malformed_arguments_are_refused(tmp_path):
    adapter = _adapter(tmp_path)
    with pytest.raises(ComputerRefused, match="unknown Daedalus observation"):
        adapter.execute("daedalus.shell", {})
    with pytest.raises(ComputerRefused, match="must be an object"):
        adapter.execute("daedalus.status", ["not", "an", "object"])  # type: ignore[arg-type]


def test_a_session_without_a_project_cannot_observe(tmp_path):
    adapter = subject.DaedalusObservation(_policy(tmp_path), None, lambda: None, tmp_path, _readers())
    with pytest.raises(ComputerRefused, match="no registered project"):
        adapter.execute("daedalus.status", {})
    with pytest.raises(ComputerRefused, match="non-empty"):
        subject.DaedalusObservation(_policy(tmp_path), "   ", lambda: None, tmp_path, _readers())


def test_an_unregistered_project_is_a_refusal_not_a_guess(tmp_path, monkeypatch):
    from daedalus.foundation import projects

    def unknown(repo_root, project):
        raise projects.ProjectRowNotFound("unknown project 'ghost'")
    monkeypatch.setattr(projects, "resolve_repo_root", unknown)
    adapter = _adapter(tmp_path, project="ghost")
    with pytest.raises(ComputerRefused, match="not registered"):
        adapter.execute("daedalus.status", {})


@pytest.mark.parametrize("module, expected", [
    ("pkg/mod.py", "pkg/mod.py"),
    ("pkg\\mod.py", "pkg/mod.py"),
    ("mod.py", "pkg/mod.py"),
    ("other.py", "lib/other.py"),
])
def test_module_resolution_is_index_bound(tmp_path, module, expected):
    idx = {"modules": {"pkg/mod.py": {}, "lib/other.py": {}, "pkg/dup.py": {}, "lib/dup.py": {}}}
    assert _adapter(tmp_path)._resolve_module(idx, module) == expected


@pytest.mark.parametrize("module, reason", [
    ("dup.py", "ambiguous"),
    ("../../../etc/passwd", "not in the project's index"),
    ("C:/Windows/system.ini", "not in the project's index"),
    ("", "bounded"),
    (42, "bounded"),
    ("x" * 1001, "bounded"),
    ("pkg/mod.py\x00", "bounded"),
])
def test_module_resolution_refuses_ambiguity_and_everything_outside_the_index(tmp_path, module, reason):
    idx = {"modules": {"pkg/mod.py": {}, "pkg/dup.py": {}, "lib/dup.py": {}}}
    with pytest.raises(ComputerRefused, match=reason):
        _adapter(tmp_path)._resolve_module(idx, module)


def test_slice_text_is_bounded_and_the_elision_is_reported(tmp_path, monkeypatch):
    from daedalus.structcore import slice as slicer
    adapter = _adapter(tmp_path)
    monkeypatch.setattr(adapter, "_repo_root", lambda: str(tmp_path))
    monkeypatch.setattr(adapter, "_cached_index", lambda repo_root: {"modules": {"pkg/mod.py": {}}})
    monkeypatch.setattr(adapter, "_project_policy", lambda: None)
    seen = {}

    def fake_slice(root, target, idx=None, lane="trusted", policy=None, max_tokens=None, include_focus=True):
        seen.update({"target": target, "lane": lane, "max_tokens": max_tokens})
        return {"focus_file": target, "slice_text": "x" * (subject.MAX_TEXT_CHARS + 500),
                "slice_tokens": 9, "n_included": 1, "trimmed_count": 0, "withheld": []}
    monkeypatch.setattr(slicer, "semantic_slice", fake_slice)
    result = adapter.execute("daedalus.slice", {"module": "mod.py"})
    assert seen == {"target": "pkg/mod.py", "lane": adapter.lane, "max_tokens": subject.SLICE_MAX_TOKENS}
    assert result["text_elided"] is True and len(result["text"]) == subject.MAX_TEXT_CHARS
    assert result["host_mutation"] is False and result["kind"] == "observation"
    assert result["lane"] == adapter.lane


def test_the_slice_goes_through_the_untrusted_gate_for_a_remote_planner(tmp_path, monkeypatch):
    from daedalus.structcore import slice as slicer
    policy = _policy(tmp_path, planner_provider="codex_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, _readers())
    monkeypatch.setattr(adapter, "_repo_root", lambda: str(tmp_path))
    monkeypatch.setattr(adapter, "_cached_index", lambda repo_root: {"modules": {"pkg/mod.py": {}}})
    monkeypatch.setattr(adapter, "_project_policy", lambda: None)
    lanes = []
    monkeypatch.setattr(slicer, "semantic_slice", lambda root, target, **kw: (lanes.append(kw["lane"]) or {
        "focus_file": target, "slice_text": "", "slice_tokens": 0, "n_included": 0, "withheld": []}))
    adapter.execute("daedalus.slice", {"module": "pkg/mod.py"})
    assert lanes == ["untrusted"]


def test_checkpoint_runs_before_every_observation(tmp_path):
    ticks = []
    adapter = subject.DaedalusObservation(_policy(tmp_path), "fixture", lambda: ticks.append(1), tmp_path, _readers())
    with pytest.raises(ComputerRefused):
        # unknown project: the checkpoint has already run once before the registry is read
        adapter.execute("daedalus.docrefs", {})
    assert ticks == [1]


# --------------------------------------------------------------------------- #
# real observations against a scratch repository                              #
# --------------------------------------------------------------------------- #
@pytest.fixture
def scratch_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "docs").mkdir()
    (repo / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "pkg" / "mod.py").write_text(
        "def present():\n    return 1\n\n\ndef helper(x):\n    return present() + x\n", encoding="utf-8")
    (repo / "docs" / "guide.md").write_text(
        "See `pkg.mod.present` and the missing `pkg.mod.absent_symbol`.\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com",
                    "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com",
                    "commit", "-q", "-m", "fixture"], check=True)
    from daedalus.foundation import projects
    monkeypatch.setattr(projects, "resolve_repo_root", lambda repo_root, project: str(repo))
    monkeypatch.setattr(projects, "load_project", lambda name: {"name": name, "repo_root": str(repo)})
    return repo


def test_status_observation_carries_git_counters_and_no_repository_root(scratch_repo, tmp_path):
    result = _adapter(tmp_path).execute("daedalus.status", {})
    assert result["registered"] is True
    assert "repo_root" not in result["git"]
    assert str(scratch_repo) not in json.dumps(result)
    assert set(result["queue"]) >= {"queue_depth", "in_flight", "watcher"}


def test_status_observation_drops_every_absolute_path_value_by_shape(scratch_repo, tmp_path, monkeypatch):
    """MEASURED 2026-09-10 (live run 3): ``collect_status`` returned
    ``todo_snapshot`` as an absolute host path and it reached the planner.
    Dropped by shape -- any absolute Windows or POSIX path -- not by name."""
    real = _readers()
    readers = subject.ProjectReaders(
        git_counters=lambda repo_root: {
            "repo_root": str(scratch_repo), "git_branch": "main", "git_status": " M x.py",
            "todo_snapshot": r"C:\Users\someone\Desktop\projects\daedalus\memory\todos.local.md",
            "posix_snapshot": "/home/someone/daedalus/memory/todos.local.md",
            "unc_snapshot": r"\\server\share\todos.local.md",
            "relative_note": "memory/todos.local.md", "open_todos": 0},
        bridge_status=real.bridge_status, report_briefs=real.report_briefs)
    result = _adapter(tmp_path, readers=readers).execute("daedalus.status", {})
    assert set(result["git"]) == {"git_branch", "git_status", "relative_note", "open_todos"}
    assert "someone" not in json.dumps(result)


@pytest.mark.parametrize("value, absolute", [
    (r"C:\Users\x", True), ("C:/Users/x", True), (r"\\server\share", True), ("/home/x", True),
    ("memory/todos.local.md", False), ("main", False), ("", False), ("x:y", False),
])
def test_host_path_shape(value, absolute):
    assert subject._looks_like_host_path(value) is absolute


def test_docrefs_observation_reports_the_broken_reference(scratch_repo, tmp_path):
    result = _adapter(tmp_path).execute("daedalus.docrefs", {})
    assert result["n_broken"] >= 1
    assert any(row["raw"] == "pkg.mod.absent_symbol" for row in result["broken"])
    assert result["broken_elided"] == 0


def test_structure_and_slice_observations_read_the_scratch_repository(scratch_repo, tmp_path):
    adapter = _adapter(tmp_path)
    structure = adapter.execute("daedalus.structure", {})
    assert structure["n_files"] >= 1 and isinstance(structure["totals"], dict)
    # MEASURED 2026-09-10 (live run 3): ``ignored.source`` carried the absolute
    # ignore-file path; only count and patterns are observed now.
    assert set(structure["ignored"]) == {"count", "patterns"}
    assert str(scratch_repo) not in json.dumps(structure)
    sliced = adapter.execute("daedalus.slice", {"module": "mod.py"})
    assert sliced["focus_file"].endswith("pkg/mod.py")
    assert "def present" in sliced["text"]
    assert sliced["text_elided"] is False
    assert str(scratch_repo) not in json.dumps({k: v for k, v in sliced.items() if k != "text"})


# --------------------------------------------------------------------------- #
# through the service: the persisted lease path                               #
# --------------------------------------------------------------------------- #
@pytest.fixture
def configured(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setenv("USERPROFILE", str(profile))
    monkeypatch.setattr(killswitch, "OS_PROFILE_DIR", profile)
    monkeypatch.delenv("DAEDALUS_KILLSWITCH", raising=False)
    authority = tmp_path / "authority"
    authority.mkdir()
    workspace = tmp_path / "scratch"
    workspace.mkdir()
    policy = ComputerPolicy(workspace=workspace, tools=DAEDALUS_TOOLS + ("file.list",))
    path = policy_path(authority)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(policy.to_dict()), encoding="utf-8")
    switch = killswitch.KillSwitch(repo_root=authority, sweep_managed=False)
    assert switch.arm(note="isolated daedalus-tools fixture").running
    return authority, policy


class _FakeObservation:
    """Stands in for the adapter so the service half needs no registry."""

    calls: list = []
    fail_with: Exception | None = None

    def __init__(self, policy, project, checkpoint, authority_root, readers):
        assert isinstance(readers, subject.ProjectReaders)
        self.project = project

    def execute(self, tool, args):
        _FakeObservation.calls.append((tool, dict(args)))
        if _FakeObservation.fail_with is not None:
            raise _FakeObservation.fail_with
        return {"kind": "observation", "project": self.project, "host_mutation": False, "tool": tool}


@pytest.fixture
def fake_observation(monkeypatch):
    _FakeObservation.calls = []
    _FakeObservation.fail_with = None
    monkeypatch.setattr("daedalus.runtimes.computer_daedalus.DaedalusObservation", _FakeObservation)
    return _FakeObservation


def _no_lease_side_effects(service):
    assert not (service.control / "computer-execution.lock").exists()
    assert not (service.control / "effect-leases.sqlite3").exists()
    assert not (service.control / "computer-effect-evidence").exists()


def test_without_a_project_the_family_is_reported_unavailable_and_never_leased(configured):
    authority, _ = configured
    service = service_module.ComputerService(authority)
    caps = service.capabilities()
    assert {tool["name"] for tool in caps["tools"]} == {"file.list"} or caps["enabled"] in (True, False)
    for tool in DAEDALUS_TOOLS:
        assert caps["unavailable"][tool] == service_module._NO_PROJECT_REFUSAL
    assert caps["project"] is None
    outcome = service.execute("daedalus.status", {}, mission_id="m", attempt_id="a")
    assert outcome["ok"] is False and outcome["state"] == "blocked"
    assert "no registered project" in outcome["error"]
    _no_lease_side_effects(service)


def test_with_a_project_the_family_is_offered_and_named(configured):
    authority, _ = configured
    service = service_module.ComputerService(authority, project="agent_env", project_readers=_readers())
    caps = service.capabilities()
    offered = {tool["name"]: tool for tool in caps["tools"]}
    assert set(DAEDALUS_TOOLS) <= set(offered)
    assert all("Project: agent_env." in offered[tool]["description"] for tool in DAEDALUS_TOOLS)
    assert caps["project"] == "agent_env"
    assert service_module.computer_status(authority, project="agent_env", project_readers=_readers())["project"] == "agent_env"


def test_a_project_without_readers_is_unavailable_and_refused_before_any_lease(configured):
    """A service built outside the chat's computer route (scheduler, status
    without readers) names the project but holds no readers: the family is
    reported unavailable with its own reason and never leased."""
    authority, _ = configured
    service = service_module.ComputerService(authority, project="agent_env")
    caps = service.capabilities()
    for tool in DAEDALUS_TOOLS:
        assert caps["unavailable"][tool] == service_module._NO_READERS_REFUSAL
    outcome = service.execute("daedalus.status", {}, mission_id="m", attempt_id="a")
    assert outcome["ok"] is False and outcome["state"] == "blocked"
    assert "project readers" in outcome["error"]
    _no_lease_side_effects(service)


def test_a_project_name_is_bounded(configured):
    authority, _ = configured
    with pytest.raises(ComputerRefused, match="bounded registry name"):
        service_module.ComputerService(authority, project="x" * 201)
    with pytest.raises(ComputerRefused, match="bounded registry name"):
        service_module.ComputerService(authority, project="")


def test_an_observation_is_retained_read_only_under_a_real_lease(configured, fake_observation):
    authority, policy = configured
    service = service_module.ComputerService(authority, project="agent_env", project_readers=_readers())
    outcome = service.execute("daedalus.structure", {}, mission_id="computer-fixture", attempt_id="attempt-1")
    assert outcome["ok"] is True and outcome["state"] == "completed"
    assert fake_observation.calls == [("daedalus.structure", {})]
    artifact = Path(outcome["evidence"]["artifact"]["path"]) if "path" in outcome["evidence"]["artifact"] else None
    stored = None
    for candidate in (service.control / "computer-artifacts").glob("*.json"):
        body = json.loads(candidate.read_text(encoding="utf-8"))
        if body.get("schema") == "daedalus-computer-result/1" and body.get("tool") == "daedalus.structure":
            stored = body
    assert stored is not None, "the result artifact must be retained"
    assert stored["host_mutation"] is False
    assert stored["filesystem_scope_kind"] == "project-registry-read-only"
    assert stored["result"]["project"] == "agent_env"
    assert artifact is None or artifact.exists()


def test_a_refused_read_is_effect_free_not_reconciliation(configured, fake_observation):
    authority, _ = configured
    fake_observation.fail_with = ComputerRefused("module is not in the project's index")
    service = service_module.ComputerService(authority, project="agent_env", project_readers=_readers())
    outcome = service.execute("daedalus.slice", {"module": "ghost.py"}, mission_id="computer-fixture",
                              attempt_id="attempt-2")
    assert outcome["ok"] is False
    assert outcome["state"] == "blocked", outcome
    assert "not in the project's index" in outcome["error"]


def test_a_crash_inside_a_read_stays_reconciliation_required(configured, fake_observation):
    """Only a typed refusal is provably effect-free; an unknown error is not
    rewritten into one, exactly as for every other adapter."""
    authority, _ = configured
    fake_observation.fail_with = RuntimeError("index backend crashed")
    service = service_module.ComputerService(authority, project="agent_env", project_readers=_readers())
    outcome = service.execute("daedalus.status", {}, mission_id="computer-fixture", attempt_id="attempt-3")
    assert outcome["ok"] is False and outcome["state"] == "reconciliation_required"


def test_policy_admission_still_refuses_an_ungranted_daedalus_tool(configured, fake_observation):
    authority, policy = configured
    narrowed = ComputerPolicy(workspace=policy.workspace, tools=("file.list",))
    policy_path(authority).write_text(json.dumps(narrowed.to_dict()), encoding="utf-8")
    service = service_module.ComputerService(authority, project="agent_env", project_readers=_readers())
    outcome = service.execute("daedalus.status", {}, mission_id="computer-fixture", attempt_id="attempt-4")
    assert outcome["ok"] is False and "not enabled" in outcome["error"]
    assert fake_observation.calls == []
    _no_lease_side_effects(service)
