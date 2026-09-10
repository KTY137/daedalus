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


@pytest.mark.parametrize("provider, host, declared, lane, leaves", [
    ("ollama_http", "http://127.0.0.1:11434", "", "trusted", False),
    ("ollama", "http://[::1]:11434", "", "trusted", False),
    ("ollama_http", "127.5.5.5:11434", "", "trusted", False),
    ("ollama_http", "http://100.119.126.9:11434", "", "untrusted", True),
    ("ollama_http", "http://100.119.126.9:11434", "100.119.126.9", "trusted", True),
    ("ollama_http", "http://0.0.0.0:11434", "", "untrusted", True),
    ("ollama_http", "http://localhost:11434", "", "untrusted", True),
    ("claude_code_cli", "http://127.0.0.1:11434", "", "trusted", True),
    ("codex_cli", "http://127.0.0.1:11434", "", "untrusted", True),
])
def test_leaving_the_machine_is_physics_and_the_lane_is_consent(tmp_path, monkeypatch, provider, host,
                                                                declared, lane, leaves):
    """Cerberus round 4 (H3): an owner-declared DAEDALUS_TRUSTED_HOSTS address is
    a TRUSTED lane (consent: only the floor filters) and still LEAVES the
    machine (physics). The two questions have two predicates."""
    monkeypatch.setenv("OLLAMA_HOST", host)
    monkeypatch.setenv("DAEDALUS_TRUSTED_HOSTS", declared)
    policy = _policy(tmp_path, planner_provider=provider, allow_remote_context=True)
    assert subject.planner_lane(policy) == lane
    assert subject.planner_leaves_machine(policy) is leaves
    assert subject.planner_host(policy) == (host if provider in ("ollama_http", "ollama") else None)


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
def test_module_resolution_is_index_bound(tmp_path, monkeypatch, module, expected):
    idx = {"modules": {"pkg/mod.py": {}, "lib/other.py": {}, "pkg/dup.py": {}, "lib/dup.py": {}}}
    adapter = _adapter(tmp_path)
    monkeypatch.setattr(adapter, "_project_policy", lambda: None)
    assert adapter._resolve_module(idx, module) == expected


@pytest.mark.parametrize("module, reason", [
    ("dup.py", "ambiguous"),
    ("../../../etc/passwd", "not in the project's index"),
    ("C:/Windows/system.ini", "not in the project's index"),
    ("", "bounded"),
    (42, "bounded"),
    ("x" * 1001, "bounded"),
    ("pkg/mod.py\x00", "bounded"),
])
def test_module_resolution_refuses_ambiguity_and_everything_outside_the_index(tmp_path, monkeypatch, module, reason):
    idx = {"modules": {"pkg/mod.py": {}, "pkg/dup.py": {}, "lib/dup.py": {}}}
    adapter = _adapter(tmp_path)
    monkeypatch.setattr(adapter, "_project_policy", lambda: None)
    with pytest.raises(ComputerRefused, match=reason):
        adapter._resolve_module(idx, module)


def test_an_ambiguous_module_names_only_the_candidates_the_gate_admits(tmp_path, monkeypatch):
    """Cerberus round 4 (H4): the ambiguity refusal listed raw indexed paths and
    reaches the planner's history like any result -- on the untrusted lane a
    model-chosen basename enumerated exactly the paths ``daedalus.structure``
    withholds. Candidates go through the same gate; the rest is a count."""
    _project_with_policy(monkeypatch, deny=["tct_app/devices/"])
    policy = _policy(tmp_path, planner_provider="codex_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, _gated_readers("", []))
    idx = {"modules": {"lib/laser.py": {}, "tct_app/devices/laser.py": {}, "vendor/acme/laser.py": {}}}
    # One admitted candidate among withheld ones resolves silently (Odysseus
    # round 7, D27): "ambiguous" with one name would reveal the withheld rest.
    assert adapter._resolve_module(idx, "laser.py") == "lib/laser.py"
    # No count either (Odysseus round 6, D22): two withheld files sharing a
    # basename answer exactly like a miss.
    with pytest.raises(ComputerRefused) as refused:
        adapter._resolve_module({"modules": {"tct_app/devices/laser.py": {}, "vendor/acme/laser.py": {}}}, "laser.py")
    assert str(refused.value) == subject._MODULE_UNAVAILABLE
    # The trusted lane sees the same list its structure rows would show.
    trusted = subject.DaedalusObservation(_policy(tmp_path, planner_provider="claude_code_cli",
                                                  allow_remote_context=True),
                                          "fixture", lambda: None, tmp_path, _gated_readers("", []))
    with pytest.raises(ComputerRefused, match="lib/laser.py, tct_app/devices/laser.py, vendor/acme/laser.py"):
        trusted._resolve_module(idx, "laser.py")


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
    _project_with_policy(monkeypatch, deny=[])
    policy = _policy(tmp_path, planner_provider="codex_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, _readers())
    monkeypatch.setattr(adapter, "_repo_root", lambda: str(tmp_path))
    monkeypatch.setattr(adapter, "_cached_index", lambda repo_root: {"modules": {"pkg/mod.py": {}}})
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
    assert set(result["git"]) == {"git_branch", "git_status", "relative_note", "open_todos",
                                  "git_status_withheld", "fields_withheld"}
    assert result["git"]["fields_withheld"] == 3
    assert "someone" not in json.dumps(result)


# --------------------------------------------------------------------------- #
# the egress gate on every observation (Cerberus 2026-09-10, CRITICAL 1)       #
# --------------------------------------------------------------------------- #
def _project_with_policy(monkeypatch, deny, deny_content=()):
    """A registry row whose policy denies ``deny`` paths and ``deny_content`` words."""
    from daedalus.foundation import projects
    config = {"name": "fixture", "repo_root": "unused",
              "policy": {"deny": list(deny), "deny_content": list(deny_content),
                         "allow": ["pkg/", "docs/", "lib/", ".md"]}}
    monkeypatch.setattr(projects, "load_project", lambda name: config)
    monkeypatch.setattr(projects, "resolve_repo_root", lambda repo_root, project: "unused")


def _gated_readers(git_status: str, briefs: list) -> subject.ProjectReaders:
    return subject.ProjectReaders(
        git_counters=lambda root: {"git_branch": "main", "git_status": git_status, "open_todos": 0},
        bridge_status=lambda project: {"queue_depth": 0, "in_flight": 0, "unread_count": 0,
                                       "reports_total": 0, "watcher": {"state": "none"}},
        report_briefs=lambda project: list(briefs))


GIT_STATUS = " M pkg/mod.py\n?? configs/secrets/lab.yaml\n?? .env\nR  lib/old.py -> lib/new.py\n M tct_app/devices/iseg.py"
BRIEFS = [{"name": "a.report.json", "summary": "renamed the parser", "project": "fixture"},
          {"name": "b.report.json", "summary": "touched the iseg driver", "project": "fixture"},
          {"name": "c.report.json", "summary": "wrote configs/secrets/lab.yaml", "project": "fixture"}]


def test_status_lines_go_through_the_project_gate_on_the_untrusted_lane(tmp_path, monkeypatch):
    _project_with_policy(monkeypatch, deny=["configs/secrets", "tct_app/devices/"], deny_content=[r"\biseg\b"])
    policy = _policy(tmp_path, planner_provider="codex_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path,
                                          _gated_readers(GIT_STATUS, BRIEFS))
    git = adapter.execute("daedalus.status", {})["git"]
    lines = git["git_status"].splitlines()
    assert lines == [" M pkg/mod.py", "R  lib/old.py -> lib/new.py"], lines
    assert git["git_status_withheld"] == 3  # secrets path, .env (floor), devices path
    assert "iseg" not in json.dumps(git) and "secrets" not in json.dumps(git) and ".env" not in json.dumps(git)


def test_status_lines_keep_the_project_paths_but_floor_secrets_on_the_trusted_lane(tmp_path, monkeypatch):
    _project_with_policy(monkeypatch, deny=["configs/secrets"], deny_content=[r"\biseg\b"])
    policy = _policy(tmp_path, planner_provider="claude_code_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path,
                                          _gated_readers(GIT_STATUS, BRIEFS))
    git = adapter.execute("daedalus.status", {})["git"]
    # the trusted lane applies only the unconditional secret floor: ``.env``
    # and the secrets directory stay out, the project's own deny list does not apply
    assert ".env" not in git["git_status"]
    assert " M tct_app/devices/iseg.py" in git["git_status"]
    assert git["git_status_withheld"] >= 1


def test_task_reports_go_through_the_content_gate(tmp_path, monkeypatch):
    _project_with_policy(monkeypatch, deny=["configs/secrets"], deny_content=[r"\biseg\b"])
    policy = _policy(tmp_path, planner_provider="deepseek", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path,
                                          _gated_readers(GIT_STATUS, BRIEFS))
    tasks = adapter.execute("daedalus.tasks", {})
    # the content gate is the project's deny_content markers (plus the floor);
    # a summary that merely NAMES a path is text, not that path's bytes
    assert [row["name"] for row in tasks["reports"]] == ["a.report.json", "c.report.json"]
    assert tasks["reports_withheld"] == 1
    assert "iseg" not in json.dumps(tasks)


def test_structure_rows_go_through_the_path_gate(tmp_path, monkeypatch):
    _project_with_policy(monkeypatch, deny=["tct_app/devices/"], deny_content=[r"\biseg\b"])
    from daedalus.structcore import report as report_module
    policy = _policy(tmp_path, planner_provider="codex_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path,
                                          _gated_readers("", []))
    monkeypatch.setattr(adapter, "_cached_index", lambda repo_root: {"modules": {}})
    monkeypatch.setattr(report_module, "structure_summary", lambda idx, **kw: {
        "n_files": 3, "ignored": {"count": 1, "n_files_scanned": 4, "ignore_patterns": ["@tests"],
                                  "source": "C:/abs/.daedalusignore", "sample": ["secret/x.py"]},
        "languages": {"python": 3}, "totals": {"unit_clusters": 2},
        "hotspots": [{"module": "pkg/mod.py", "score": 1.0, "future_field": "C:/abs/leak"},
                     {"module": "tct_app/devices/iseg.py", "score": 9.0}],
        "clones": [{"name": "iseg", "count": 2, "loc": 4, "sites": [{"module": "pkg/mod.py", "line": 1}]},
                   {"name": "helper", "count": 2, "loc": 4,
                    "sites": [{"module": "pkg/mod.py", "line": 1}, {"module": "tct_app/devices/x.py", "line": 2}]}],
        "fan_in": [{"module": "pkg/mod.py", "count": 3}, {"module": "tct_app/devices/x.py", "count": 1}]})
    structure = adapter.execute("daedalus.structure", {})
    assert [row["module"] for row in structure["hotspots"]] == ["pkg/mod.py"]
    assert structure["hotspots_withheld"] == 1
    # Cerberus N4: rows are projected to an allow-listed key set, so a field a
    # producer adds later cannot join the prompt; N7: the real ignore keys.
    assert "future_field" not in structure["hotspots"][0]
    assert structure["ignored"] == {"count": 1, "n_files_scanned": 4, "ignore_patterns": ["@tests"],
                                    "ignore_patterns_withheld": 0, "ignore_patterns_elided": 0, "fields_withheld": 0}
    assert "secret/x.py" not in json.dumps(structure)
    assert [row["name"] for row in structure["clones"]] == ["helper"]
    assert structure["clones"][0]["sites"] == [{"module": "pkg/mod.py", "line": 1}]
    assert structure["clones"][0]["sites_withheld"] == 1
    assert structure["clones_withheld"] == 1
    assert [row["module"] for row in structure["fan_in"]] == ["pkg/mod.py"]
    assert structure["fan_in_withheld"] == 1
    assert "C:/abs" not in json.dumps(structure) and "iseg" not in json.dumps(structure)


def test_docrefs_rows_go_through_the_gate_and_errors_are_a_count(tmp_path, monkeypatch):
    _project_with_policy(monkeypatch, deny=["tct_app/devices/"], deny_content=[r"\biseg\b"])
    from daedalus.spine import docrefs as docrefs_module
    policy = _policy(tmp_path, planner_provider="codex_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path,
                                          _gated_readers("", []))

    class Report:
        def to_dict(self):
            return {"n_resolving": 5, "n_broken": 3, "n_skipped": 0, "files_scanned": 2,
                    "broken": [{"doc_path": "docs/a.md", "line": 1, "raw": "pkg.mod.absent", "module_path": "pkg/mod.py", "symbol": "absent"},
                               {"doc_path": "docs/a.md", "line": 2, "raw": "tct_app.devices.iseg.reset", "module_path": "tct_app/devices/iseg.py", "symbol": "reset"},
                               {"doc_path": "docs/b.md", "line": 3, "raw": "iseg voltage", "module_path": "", "symbol": ""}],
                    "errors": ["C:\\Users\\someone\\repo\\docs\\broken.md: PermissionError: denied"]}
    monkeypatch.setattr(docrefs_module, "scan", lambda repo_root: Report())
    result = adapter.execute("daedalus.docrefs", {})
    assert [row["raw"] for row in result["broken"]] == ["pkg.mod.absent"]
    assert result["broken_withheld"] == 2
    assert result["errors_count"] == 1 and "errors" not in result
    assert "someone" not in json.dumps(result) and "iseg" not in json.dumps(result)


@pytest.mark.parametrize("text, embedded", [
    ("failed: PermissionError: 'C:\\Users\\x\\repo\\docs\\a.md'", True),
    ("see /home/x/repo/docs", True), ("(/Users/x/y)", True), (r"\\server\share\x", True),
    # Odysseus round 2 (D3): the spellings the root-name list missed
    ("file:///home/kty/projects/daedalus/x.md", True), ("//nas01/team/plans/x.md", True),
    ("~/projects/daedalus/x.py", True), ("/usr/local/lib/python3.12/site-packages/daedalus/x.py", True),
    ("/data/corpus/x", True), ("/workspace/x/y", True), ("/proc/self/environ", True),
    ("%USERPROFILE%\\Desktop\\x.md", True), ("$HOME/x/y", True), ("read C:/Users/x/y.md", True),
    # Cerberus round 3 (d): the shapes the two-segment rule and the root list missed
    ("${HOME}/lab/driver.py", True), ("$env:USERPROFILE\\Desktop\\x", True), ("C:temp\\x", True),
    ("smb://nas01/share/x", True), ("open /etc failed", True), ("could not read /tmp", True),
    ("cd /src && make", True), ("https://example.com/a/b", True), ("see [guide](/docs/guide.md)", True),
    # Odysseus round 3 (D7): tilde-user, non-ASCII first segment, bare UNC host, drive after a word
    ("~kty/projects/x.py", True), ("/дом/kty/secret.txt", True), ("share \\\\nas01 down", True),
    ("checkoutC:\\Users\\x", True), ("/Program Files/App/config.ini", True),
    ("renamed the parser", False), ("ratio 1:2 and a/b", False), ("C:", False), ("x/etc/y", False),
    ("pkg/mod.py", False), ("docs/a.md -> docs/b.md", False), ("50/50", False),
    ("M  src/app.ts", False), ("2026/09/10", False), ("and/or", False), ("n/a", False),
])
def test_embedded_host_paths_are_detected(text, embedded):
    assert subject._mentions_host_path(text) is embedded


def test_ignore_patterns_are_gated_and_counted(tmp_path, monkeypatch):
    """Cerberus round 3 (H1): ignore patterns name the trees a project withholds."""
    _project_with_policy(monkeypatch, deny=[], deny_content=[r"acme_hv"])
    from daedalus.structcore import report as report_module
    policy = _policy(tmp_path, planner_provider="codex_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, _gated_readers("", []))
    monkeypatch.setattr(adapter, "_cached_index", lambda repo_root: {"modules": {}})
    monkeypatch.setattr(report_module, "structure_summary", lambda idx, **kw: {
        "n_files": 1, "ignored": {"count": 2, "n_files_scanned": 3,
                                  "ignore_patterns": ["@tests", "vendor/acme_hv/", "C:/abs/leak/"]},
        "languages": {}, "totals": {}, "hotspots": [], "clones": [], "fan_in": []})
    structure = adapter.execute("daedalus.structure", {})
    assert structure["ignored"] == {"count": 2, "n_files_scanned": 3, "ignore_patterns": ["@tests"],
                                    "ignore_patterns_withheld": 2, "ignore_patterns_elided": 0, "fields_withheld": 0}


def _real_rules(adapter, lane="untrusted"):
    """The rule strings ``slice_egress_rule`` really returns for the fixture
    policy -- the round-3 test pinned an invented ``egress policy: …`` string
    the gate never emits, which is how D9 stayed green (Odysseus round 4)."""
    from daedalus.sensitivity import slice_egress_rule
    project = adapter._project_policy()
    return {
        "deny": slice_egress_rule("tct_app/devices/iseg.py", "x = 1", lane=lane, policy=project),
        "default": slice_egress_rule("internal/roadmap q4.py", "x = 1", lane=lane, policy=project),
        "secret": slice_egress_rule("deploy/id_rsa", "x = 1", lane=lane, policy=project),
        "marker": slice_egress_rule("pkg/notes.py", "the ODYSSEUSCHIMERA rig", lane=lane, policy=project),
    }


def test_slice_withheld_rows_name_a_rule_class_never_the_file_fragment_or_marker(tmp_path, monkeypatch):
    """Cerberus round 3 (H2) and Odysseus round 4 (D9/D12): the gate's real rule
    strings are ``<path>: denylisted path fragment '<fragment>'``, ``<path>: path
    not on the external allow-list (default-deny)``, ``secret path marker
    '<fragment>'`` and ``content matches sensitive marker /<pattern>/`` -- each
    names the withheld path, the project's deny fragment or the marker. Only a
    fixed class travels, in the rows and in the rebuilt breadcrumb block, and a
    file name with spaces or a CRLF line cannot slip past a regex."""
    from daedalus.structcore import slice as slicer
    _project_with_policy(monkeypatch, deny=["tct_app/devices/"], deny_content=[r"ODYSSEUSCHIMERA"])
    policy = _policy(tmp_path, planner_provider="codex_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, _gated_readers("", []))
    rules = _real_rules(adapter)
    assert "tct_app/devices/" in rules["deny"] and "roadmap q4" in rules["default"]
    assert "ODYSSEUSCHIMERA" in rules["marker"] and rules["secret"].startswith("secret path marker")
    monkeypatch.setattr(adapter, "_cached_index", lambda repo_root: {"modules": {"pkg/mod.py": {}}})
    monkeypatch.setattr(slicer, "semantic_slice", lambda root, target, **kw: {
        "focus_file": target, "slice_tokens": 3, "n_included": 1, "trimmed_count": 2,
        "slice_text": ("def present():\n    return 1\n\n# ===== WITHHELD (egress gate) =====\n"
                       f"# tct_app/devices/iseg.py  ({rules['deny']})  [dependency]\r\n"
                       f"# internal/roadmap q4.py  ({rules['default']})  [neighbor]\n"
                       f"# deploy/id_rsa  ({rules['secret']})  [neighbor]\n"
                       f"# pkg/notes.py  ({rules['marker']})  [importer]\n"
                       "# ===== CONTEXT TRIMMED: dropped 2 of 5 neighbors to fit budget ====="),
        "withheld": [{"file": "tct_app/devices/iseg.py", "role": "dependency", "rule": rules["deny"]},
                     {"file": "internal/roadmap q4.py", "role": "neighbor", "rule": rules["default"]},
                     {"file": "deploy/id_rsa", "role": "neighbor", "rule": rules["secret"]},
                     {"file": "pkg/notes.py", "role": "importer", "rule": rules["marker"]}]})
    sliced = adapter.execute("daedalus.slice", {"module": "pkg/mod.py"})
    assert sliced["withheld"] == [{"role": "dependency", "rule": "denylisted_path"},
                                  {"role": "neighbor", "rule": "default_deny"},
                                  {"role": "neighbor", "rule": "secret_path"},
                                  {"role": "importer", "rule": "deny_content"}]
    assert sliced["withheld_count"] == 4 and sliced["focus_file"] == "pkg/mod.py"
    dumped = json.dumps(sliced)
    for secret in ("iseg", "tct_app", "devices", "roadmap", "id_rsa", "deploy", "notes.py", "ODYSSEUSCHIMERA", "\\r"):
        assert secret not in dumped, secret
    assert sliced["text"] == ("def present():\n    return 1\n\n# ===== WITHHELD (egress gate) =====\n"
                              "# <withheld>  (denylisted_path)  [dependency]\n"
                              "# <withheld>  (default_deny)  [neighbor]\n"
                              "# <withheld>  (secret_path)  [neighbor]\n"
                              "# <withheld>  (deny_content)  [importer]\n"
                              "# ===== CONTEXT TRIMMED: dropped 2 of 5 neighbors to fit budget =====")


def test_a_withheld_focus_discloses_neither_its_path_nor_its_rule_text(tmp_path, monkeypatch):
    """Cerberus round 4 (H4 corollary): a basename resolves to its full indexed
    path, which on the untrusted lane may be the very directory the project
    withholds -- ``focus_file`` and the refusal line are gated too."""
    from daedalus.structcore import slice as slicer
    _project_with_policy(monkeypatch, deny=["tct_app/devices/"])
    policy = _policy(tmp_path, planner_provider="codex_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, _gated_readers("", []))
    monkeypatch.setattr(adapter, "_cached_index", lambda repo_root: {"modules": {"tct_app/devices/iseg.py": {},
                                                                                  "pkg/mod.py": {}}})
    # A withheld PATH never reaches the slicer, by basename or by exact path,
    # and the refusal is the one a miss gets (Odysseus round 5, D18).
    for module in ("iseg.py", "tct_app/devices/iseg.py", "nothere.py"):
        with pytest.raises(ComputerRefused, match="not available to this planner"):
            adapter.execute("daedalus.slice", {"module": module})
    # An admitted path whose CONTENT the floor withholds is the case the
    # slicer's focus refusal exists for: the rule travels as a class only.
    rule = "secret content: private key block"
    monkeypatch.setattr(slicer, "semantic_slice", lambda root, target, **kw: {
        "focus_file": target, "slice_tokens": 9, "n_included": 0,
        "slice_text": (f"# ===== WITHHELD: {target} ({rule}) =====\n"
                       "# focus file withheld by the egress gate (lane=untrusted); slice refused (fail-closed)."),
        "withheld": [{"file": target, "role": "focus", "rule": rule}]})
    sliced = adapter.execute("daedalus.slice", {"module": "mod.py"})
    assert sliced["focus_file"] == "pkg/mod.py"
    assert sliced["withheld"] == [{"role": "focus", "rule": "secret_content"}]
    assert sliced["text"] == ("# ===== WITHHELD: <withheld> (secret_content) =====\n"
                              "# focus file withheld by the egress gate (lane=untrusted); slice refused (fail-closed).")
    assert "private key" not in json.dumps(sliced) and "iseg" not in json.dumps(sliced)


def test_the_real_slicer_hands_no_withheld_path_or_fragment_to_the_planner(tmp_path, monkeypatch):
    """Odysseus round 4 (D9), end to end: the REAL index and the REAL slicer on
    a repository whose focus imports a denylisted module. The dependency is
    withheld by the real gate and neither its path, its directory nor the deny
    fragment appears anywhere in the observation."""
    import subprocess
    repo = tmp_path / "repo"
    for rel, body in {
        "pkg/__init__.py": "",
        "pkg/mod.py": "from tct_app.devices import iseg\n\n\ndef present():\n    return iseg.read()\n",
        "tct_app/__init__.py": "",
        "tct_app/devices/__init__.py": "",
        "tct_app/devices/iseg.py": "def read():\n    return 1\n",
    }.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(body, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com", "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com",
                    "commit", "-q", "-m", "fixture"], check=True)
    from daedalus.foundation import projects
    from daedalus.structcore import index as index_module
    monkeypatch.setenv("DAEDALUS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(index_module, "_INDEX_CACHE", {}, raising=False)
    config = {"name": "fixture", "repo_root": str(repo),
              "policy": {"deny": ["tct_app/devices/"], "deny_content": [], "allow": ["pkg/", ".md"]}}
    monkeypatch.setattr(projects, "load_project", lambda name: config)
    monkeypatch.setattr(projects, "resolve_repo_root", lambda repo_root, project: str(repo))
    policy = _policy(tmp_path, planner_provider="codex_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, _readers())
    sliced = adapter.execute("daedalus.slice", {"module": "pkg/mod.py"})
    assert sliced["lane"] == "untrusted" and sliced["focus_file"] == "pkg/mod.py"
    assert sliced["withheld"] == [{"role": "dependency", "rule": "denylisted_path"}], sliced
    assert sliced["withheld_count"] == 1
    dumped = json.dumps(sliced)
    assert "def present" in sliced["text"] and "# <withheld>  (denylisted_path)  [dependency]" in sliced["text"]
    # The focus SOURCE still names its import (``from tct_app.devices import
    # iseg`` is the focus file's own admitted text); the withheld module's
    # PATH, its directory and the project's deny fragment are never added.
    for secret in ("iseg.py", "devices/", "tct_app/", "denylisted path fragment"):
        assert secret not in dumped, secret
    assert dumped.count("iseg") == dumped.count("import iseg") + dumped.count("iseg.read()")


def test_status_gates_every_value_shape_in_git_and_queue(tmp_path, monkeypatch):
    """Odysseus round 4 (D10/D11): the status gate looked at str values only, so
    a list, a dict, a set, a Path, an exception, bytes or a dict KEY carrying a
    host path or a deny word reached the planner untouched."""
    from pathlib import PurePath
    _project_with_policy(monkeypatch, deny=[], deny_content=[r"iseg"])
    policy = _policy(tmp_path, planner_provider="codex_cli", allow_remote_context=True)
    hostile = {
        "git_branch": "main", "git_status": "", "open_todos": 3,
        "todo_list": ["C:\\Users\\someone\\memory\\todos.md"],
        "worktrees": {"j": "C:\\Users\\someone\\memory\\t.md"},
        "marker_set": {"touched the iseg driver"},
        "path_obj": PurePath("C:/Users/someone/t.md"),
        "error": OSError("C:\\Users\\someone\\t.md"),
        "raw": b"C:\\Users\\someone\\t.md",
        "keyed": {"C:\\Users\\someone\\t.md": 1},
        "nested": [[{"deep": ("fine", "the iseg driver")}]],
        "flag": True, "ratio": 0.5, "nothing": None,
    }
    readers = subject.ProjectReaders(
        git_counters=lambda root: dict(hostile),
        bridge_status=lambda project: {"queue_depth": ["C:\\Users\\someone\\q"], "in_flight": 0,
                                       "unread_count": 0, "reports_total": 0, "watcher": {"state": "iseg"}},
        report_briefs=lambda project: [])
    # Untrusted lane: every host-path shape AND every deny_content hit is
    # withheld, and a str scalar is default-denied like any non-allow-listed
    # path (the round-3 behaviour, unchanged).
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, readers)
    status = adapter.execute("daedalus.status", {})
    assert set(status["git"]) == {"git_status", "open_todos", "flag", "ratio", "nothing",
                                  "git_status_withheld", "fields_withheld"}
    assert status["git"]["fields_withheld"] == 9
    assert status["queue"] == {"in_flight": 0, "unread_count": 0, "reports_total": 0, "fields_withheld": 2}
    dumped = json.dumps(status)
    assert "someone" not in dumped and "iseg" not in dumped
    # Trusted lane: only the floor and the host-path shapes withhold -- in every
    # container shape -- and the deny word passes exactly as for the Voice.
    trusted = subject.DaedalusObservation(_policy(tmp_path, planner_provider="claude_code_cli",
                                                  allow_remote_context=True),
                                          "fixture", lambda: None, tmp_path, readers)
    status = trusted.execute("daedalus.status", {})
    assert set(status["git"]) == {"git_branch", "git_status", "open_todos", "flag", "ratio", "nothing",
                                  "marker_set", "nested", "git_status_withheld", "fields_withheld"}
    assert status["git"]["fields_withheld"] == 6
    assert status["queue"] == {"in_flight": 0, "unread_count": 0, "reports_total": 0, "watcher": "iseg",
                               "fields_withheld": 1}
    assert "someone" not in json.dumps(status)


def test_a_set_is_gated_on_the_text_json_renders_for_it(tmp_path, monkeypatch):
    """Odysseus round 5 (D14): a set has no JSON form, so ``default=str`` emits
    the whole container from element ``repr()``s -- a ``Path`` inside a set was
    gated on its ``str()`` and rendered with its repr. Gated on the rendering."""
    from pathlib import PureWindowsPath
    _project_with_policy(monkeypatch, deny=[])
    policy = _policy(tmp_path, planner_provider="claude_code_cli", allow_remote_context=True)
    readers = subject.ProjectReaders(
        git_counters=lambda root: {"git_branch": "main", "git_status": "", "open_todos": 0,
                                   "roots": {PureWindowsPath("C:/Users/someone/SECRET")},
                                   "labels": {"fine", "also fine"}},
        bridge_status=lambda project: {"queue_depth": 0, "in_flight": 0, "unread_count": 0,
                                       "reports_total": 0, "watcher": {"state": "none"}},
        report_briefs=lambda project: [])
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, readers)
    status = adapter.execute("daedalus.status", {})
    assert "roots" not in status["git"] and status["git"]["fields_withheld"] == 1
    assert "someone" not in json.dumps(status) and "SECRET" not in json.dumps(status)
    assert "labels" in status["git"]


def test_the_gate_and_the_emitter_share_one_renderer(tmp_path, monkeypatch):
    """Cerberus round 6 (low): a separate decode pass before gating let a
    non-dict Mapping with its own repr be gated on its items and emitted as
    its repr. One renderer now: gated text == emitted text, for a Mapping
    subclass, bytes, a bytearray and a set of Paths alike."""
    from collections.abc import Mapping as ABCMapping
    from pathlib import PureWindowsPath

    class Sneaky(ABCMapping):
        def __init__(self):
            self._d = {"k": "safe"}

        def __getitem__(self, key):
            return self._d[key]

        def __iter__(self):
            return iter(self._d)

        def __len__(self):
            return 1

        def __repr__(self):
            return "Sneaky(root=C:/Users/someone/hidden.pem)"

    _project_with_policy(monkeypatch, deny=[])
    policy = _policy(tmp_path, planner_provider="claude_code_cli", allow_remote_context=True)
    readers = subject.ProjectReaders(
        git_counters=lambda root: {"git_branch": "main", "git_status": "", "open_todos": 0,
                                   "sneaky": Sneaky(), "raw": b"plain bytes", "arr": bytearray(b"C:\\Users\\someone"),
                                   "paths": {PureWindowsPath("C:/Users/someone/x")}},
        bridge_status=lambda project: {"queue_depth": 0, "in_flight": 0, "unread_count": 0,
                                       "reports_total": 0, "watcher": {"state": "none"}},
        report_briefs=lambda project: [])
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, readers)
    status = adapter.execute("daedalus.status", {})
    assert set(status["git"]) == {"git_branch", "git_status", "open_todos", "raw", "git_status_withheld", "fields_withheld"}
    assert status["git"]["raw"] == "plain bytes" and status["git"]["fields_withheld"] == 3
    assert "someone" not in json.dumps(status)
    for value in (Sneaky(), b"x", bytearray(b"y"), {PureWindowsPath("C:/a")}, [{"n": (1, b"z")}]):
        assert subject._strings_in(value) == subject._rendered_strings(json.loads(subject._render(value)))


def test_clone_rows_are_rendered_once_and_gated_in_every_field(tmp_path, monkeypatch):
    """Odysseus round 7 (D24): the clone rows were copied raw from the
    producer, so the emitter rendered a second time (a stateful ``__str__``
    slipped through) and ``count``/``loc`` were never gated."""
    from daedalus.structcore import report as report_module

    class Shifty:
        def __init__(self):
            self.calls = 0

        def __str__(self):
            self.calls += 1
            return "benign_clone" if self.calls == 1 else "C:\\Users\\victim\\secrets\\id_rsa"

    _project_with_policy(monkeypatch, deny=[])
    policy = _policy(tmp_path, planner_provider="claude_code_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, _gated_readers("", []))
    monkeypatch.setattr(adapter, "_cached_index", lambda repo_root: {"modules": {}})
    monkeypatch.setattr(report_module, "structure_summary", lambda idx, **kw: {
        "n_files": 3, "languages": {}, "totals": {}, "hotspots": [], "fan_in": [],
        "clones": [{"name": Shifty(), "language": "python", "count": 2, "loc": 7, "safety": "low",
                    "sites": [{"module": "pkg/a.py", "line": 1}]},
                   {"name": "fine", "language": "python", "count": "C:\\Users\\victim\\.ssh\\id_ed25519", "loc": 7,
                    "sites": [{"module": "pkg/b.py", "line": 2}]}],
        "ignored": {"count": 0, "n_files_scanned": 3, "ignore_patterns": []}})
    structure = adapter.execute("daedalus.structure", {})
    assert [clone["name"] for clone in structure["clones"]] == ["benign_clone"]
    assert structure["clones_withheld"] == 1
    assert "victim" not in json.dumps(structure)


def test_registry_refusals_name_the_class_never_the_message(tmp_path, monkeypatch):
    """Odysseus round 7 (D25), Cerberus round 7 (L3): the two registry
    producers still interpolated the exception message, which carries the
    registry file's host path, into a refusal the planner's history sees."""
    from daedalus.foundation import projects
    boom = PermissionError(13, "Permission denied", "C:\\Users\\victim\\projects\\fixture.json")
    monkeypatch.setattr(projects, "resolve_repo_root", lambda repo_root, project: (_ for _ in ()).throw(boom))
    monkeypatch.setattr(projects, "load_project", lambda name: (_ for _ in ()).throw(boom))
    policy = _policy(tmp_path, planner_provider="claude_code_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, _gated_readers("", []))
    with pytest.raises(ComputerRefused) as refused:
        adapter._repo_root()
    assert str(refused.value) == "project is not registered or unreadable: PermissionError"
    with pytest.raises(ComputerRefused) as refused:
        adapter._project_policy()
    assert str(refused.value) == "project policy is unavailable: PermissionError"
    monkeypatch.setattr(projects, "load_project", lambda name: {"name": name, "policy": {"deny": 17}})
    with pytest.raises(ComputerRefused, match="project policy is unavailable: ") as refused:
        adapter._project_policy()
    assert "victim" not in str(refused.value)


def test_absolute_host_paths_inside_the_slice_text_are_redacted_and_counted(tmp_path, monkeypatch):
    """Odysseus round 7 (D26): the slice TEXT is source, and a string literal
    holding an absolute path left with it on every lane while the module
    promised no host path reaches the planner. Redacted span by span."""
    from daedalus.structcore import slice as slicer
    _project_with_policy(monkeypatch, deny=[])
    policy = _policy(tmp_path, planner_provider="codex_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, _gated_readers("", []))
    monkeypatch.setattr(adapter, "_cached_index", lambda repo_root: {"modules": {"pkg/mod.py": {}}})
    body = ('CACHE = "C:\\Users\\victim\\AppData\\Local\\daedalus\\cache"\n'
            'SOCKET = "/home/victim/run/daedalus.sock"\nPLAIN = "relative/path.txt"\n'
            'UNC = "\\\\nas01\\share\\victim.txt"\n')
    monkeypatch.setattr(slicer, "semantic_slice", lambda root, target, **kw: {
        "focus_file": target, "slice_tokens": 9, "n_included": 1, "slice_text": body, "withheld": []})
    sliced = adapter.execute("daedalus.slice", {"module": "pkg/mod.py"})
    assert "victim" not in json.dumps(sliced)
    assert sliced["text_host_paths_redacted"] == 3
    assert sliced["text"] == ('CACHE = "<host-path>"\nSOCKET = "<host-path>"\nPLAIN = "relative/path.txt"\n'
                              'UNC = "<host-path>"\n')


def test_a_slash_after_any_non_path_character_is_a_host_path(tmp_path, monkeypatch):
    """Odysseus round 8 (D29, major): the POSIX alternative accepted only a
    fixed list of characters before the slash, so ``{/home/…``, ``|/home/…``,
    ``*/home/…``, ``&/home/…`` and ``@/home/…`` were neither detected nor
    redacted -- and passed the row gate on the untrusted lane."""
    for text in ('f"{os.sep}/home/administrator/.ssh/known_hosts"', 'PIPE = "cat|/home/administrator/.bashrc"',
                 'STAR = "*/home/administrator/x"', 'AMP = "&/home/victim/x"', 'AT = "@/home/victim/x"',
                 'build failed {/home/administrator/.ssh/known_hosts}'):
        assert subject._mentions_host_path(text), text
        redacted, count = subject._redact_host_paths(text)
        assert count >= 1 and "administrator" not in redacted and "victim" not in redacted, redacted
    for clean in ("a/b/c.py", "50/50", "1:2", "http://", "and/or", "x = a // b"):
        assert not subject._mentions_host_path(clean), clean
    _project_with_policy(monkeypatch, deny=[])
    policy = _policy(tmp_path, planner_provider="codex_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, _gated_readers("", []))
    assert adapter._admit_text("build failed {/home/administrator/.ssh/known_hosts}") is False


def test_a_quoted_path_with_spaces_is_redacted_to_its_closing_quote(tmp_path, monkeypatch):
    """Odysseus round 8 (D28): the token stopped at the first space, so
    ``C:\\Program Files\\LabIP\\Kowalski\\x`` leaked every later segment."""
    text = ('WIN_SPACE = "C:\\Program Files\\LabIP\\Kowalski\\driver.py"\n'
            "USER = 'C:\\Users\\First Last\\secret.key'\n"
            'PLAIN = "relative/path.txt"; unquoted C:\\Program Files\\x tail\n')
    redacted, count = subject._redact_host_paths(text)
    assert "Kowalski" not in redacted and "First Last" not in redacted
    # An unquoted path with spaces is redacted whole as well (round 9, D31).
    assert redacted.startswith('WIN_SPACE = "<host-path>"\nUSER = \'<host-path>\'\nPLAIN = "relative/path.txt"; unquoted <host-path> tail')
    # The quote rule is load-bearing where the last segment carries no
    # separator: only the closing quote says where the path ends (M58).
    quoted_tail, quoted_count = subject._redact_host_paths('NAME = "C:\\Users\\First Last"\n')
    assert quoted_tail == 'NAME = "<host-path>"\n' and quoted_count == 1
    assert count == 3


def test_an_unquoted_path_continues_across_a_separator_free_word(tmp_path, monkeypatch):
    """Odysseus round 9 (D31): ``C:\\Users\\First Last\\secret.key`` in prose or a
    docstring was redacted to the first space; the surname survived. The path
    continues while a run within the lookahead still carries a separator, so
    ONE separator-free run in the middle is bridged (Cerberus round 10, F1)."""
    text = ("# owner home is C:\\Users\\First Last\\projects\\daedalus\\notes.txt today\n"
            "#:   ``C:\\Program Files\\nodejs\\npx.cmd``  -- an absolute path\n"
            "cat /home/first last/x.txt done\n")
    redacted, count = subject._redact_host_paths(text)
    assert "First Last" not in redacted and "Last" not in redacted and "nodejs" not in redacted
    assert "first last" not in redacted
    assert redacted == ("# owner home is <host-path> today\n#:   ``<host-path>``  -- an absolute path\n"
                        "cat <host-path> done\n")
    assert count == 3
    # A separator-free word INSIDE the path (a two-word first name) stopped the
    # walk in round 9 and leaked the whole tail (Cerberus round 10, F1).
    middle, middle_count = subject._redact_host_paths(
        "path C:\\Users\\Jean Luc Picard\\Desktop\\secret.txt end\n")
    assert middle == "path <host-path> end\n" and middle_count == 1


def test_the_tail_of_an_unquoted_path_after_two_separator_free_words(tmp_path, monkeypatch):
    """NEGATIVE EVIDENCE, retained on purpose (Cerberus round 10, F1): the
    lookahead bridges ONE separator-free run. An unquoted path that ENDS in a
    separator-free run, or whose tail needs two bridges, keeps that run. The
    alternative -- walking to the end of the line -- would swallow the prose
    after every path, so this residue is named in the packet rather than
    closed. The marker and the count still say a redaction happened."""
    trailing, trailing_count = subject._redact_host_paths("see C:\\Users\\First Last\n")
    assert trailing == "see <host-path> Last\n" and trailing_count == 1
    two, _ = subject._redact_host_paths("at C:\\Users\\Jean Luc van Picard\\x.txt end\n")
    assert two.startswith("at <host-path> ")
    # A quote or a backtick closes the token whatever the segments look like.
    for spelling in ('"C:\\Users\\First Last" end', "'C:\\Users\\First Last' end",
                     "``C:\\Users\\First Last`` end"):
        closed, closed_count = subject._redact_host_paths(spelling)
        assert "Last" not in closed and closed_count == 1


def test_a_backtick_is_a_quote_and_never_ends_a_path_token(tmp_path, monkeypatch):
    """Cerberus round 10 (F2): round 9 made the backtick a token END, so a
    backtick inside a path left the remainder raw where round 8 had redacted
    it. As a QUOTE it closes a markdown code span -- the producer-reachable
    case is a docstring in this repository -- and no longer cuts a token."""
    inside, inside_count = subject._redact_host_paths("C:\\Users\\me`\\secrets\\id_rsa\n")
    assert inside == "<host-path>\n" and inside_count == 1
    assert not subject._mentions_host_path(inside)
    span, span_count = subject._redact_host_paths(
        "# `C:\\Program Files` inside a JSON string, the strict parser refuses the WHOLE\n")
    assert span == "# `<host-path>` inside a JSON string, the strict parser refuses the WHOLE\n"
    assert span_count == 1
    # An opening quote whose partner never arrives must not redact LESS than
    # the same text without the quote: both branches use one walk.
    for opener in ("`", '"', "'"):
        unclosed, unclosed_count = subject._redact_host_paths(f"{opener}C:\\Users\\First Last\\k.pem tail\n")
        assert unclosed == f"{opener}<host-path> tail\n" and unclosed_count == 1


def test_a_withheld_field_of_an_unknown_shape_still_rebuilds_the_block(tmp_path, monkeypatch):
    """Odysseus round 9 (D32): ``isinstance(withheld, list)`` failed open for a
    tuple or a dict, and the slicer's own breadcrumbs travelled."""
    from daedalus.structcore import slice as slicer
    _project_with_policy(monkeypatch, deny=["tct_app/devices/"])
    policy = _policy(tmp_path, planner_provider="codex_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, _gated_readers("", []))
    monkeypatch.setattr(adapter, "_cached_index", lambda repo_root: {"modules": {"pkg/mod.py": {}}})
    text = ("x = 1\n# ===== WITHHELD (egress gate) =====\n"
            "# tct_app/devices/iseg.py  (tct_app/devices/iseg.py: denylisted path fragment 'tct_app/devices/')  [context]")
    for shape in (({"file": "tct_app/devices/iseg.py", "role": "context", "rule": "x"},),
                  {"file": "tct_app/devices/iseg.py", "role": "context", "rule": "x"}):
        monkeypatch.setattr(slicer, "semantic_slice", lambda root, target, **kw: {
            "focus_file": target, "slice_tokens": 3, "n_included": 1, "slice_text": text, "withheld": shape})
        sliced = adapter.execute("daedalus.slice", {"module": "pkg/mod.py"})
        assert "iseg" not in json.dumps(sliced) and sliced["withheld_count"] >= 1


def test_a_withheld_element_of_an_unreadable_shape_is_counted_not_dropped(tmp_path, monkeypatch):
    """Cerberus round 11 (F-B): a list whose ELEMENTS are not Mappings filtered
    to nothing, so no rebuild fired, the slicer's raw block passed, and the
    payload said ``withheld_count: 0`` while carrying the file name and the
    rule. That is the output lying about what it withheld."""
    from daedalus.structcore import slice as slicer
    _project_with_policy(monkeypatch, deny=["tct_app/devices/"])
    policy = _policy(tmp_path, planner_provider="codex_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, _gated_readers("", []))
    monkeypatch.setattr(adapter, "_cached_index", lambda repo_root: {"modules": {"pkg/mod.py": {}}})
    text = ("x = 1\n# ===== WITHHELD (egress gate) =====\n"
            "# tct_app/devices/iseg.py  (denylisted path fragment 'tct_app/devices/')  [context]")
    monkeypatch.setattr(slicer, "semantic_slice", lambda root, target, **kw: {
        "focus_file": target, "slice_tokens": 3, "n_included": 1, "slice_text": text,
        "withheld": ["tct_app/devices/iseg.py", 7]})
    sliced = adapter.execute("daedalus.slice", {"module": "pkg/mod.py"})
    assert "iseg" not in json.dumps(sliced) and "devices" not in json.dumps(sliced)
    assert sliced["withheld_count"] == 2  # what the payload claims matches what it dropped


def test_a_diverged_withheld_block_is_dropped_even_when_the_text_was_bounded(tmp_path, monkeypatch):
    """Cerberus round 11 (F-A): round 10 excepted the bounded case on the
    assumption that truncation takes the slicer's breadcrumbs with it. A
    divergent block need not be last, so the file name, the project's own deny
    fragment and the rule text travelled. Withheld-looking lines never travel
    when the pinned header is absent, bounded or not."""
    from daedalus.structcore import slice as slicer
    _project_with_policy(monkeypatch, deny=["tct_app/devices/"])
    policy = _policy(tmp_path, planner_provider="codex_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, _gated_readers("", []))
    monkeypatch.setattr(adapter, "_cached_index", lambda repo_root: {"modules": {"pkg/mod.py": {}}})
    row = {"file": "tct_app/devices/iseg.py", "role": "context", "rule": "denylisted path fragment"}
    diverged = ("x = 1\n#### WITHHELD BLOCK v2 ####\n"
                "# tct_app/devices/iseg.py  (denylisted path fragment 'tct_app/devices/')  [context]\n"
                "y = 2\n" + "z = 3\n" * 40000)
    monkeypatch.setattr(slicer, "semantic_slice", lambda root, target, **kw: {
        "focus_file": target, "slice_tokens": 3, "n_included": 1, "slice_text": diverged, "withheld": [row]})
    sliced = adapter.execute("daedalus.slice", {"module": "pkg/mod.py"})
    payload = json.dumps(sliced)
    assert sliced["text_elided"] is True  # the bound fired: this is the excepted path
    assert "iseg" not in payload and "denylisted path fragment" not in payload
    assert "x = 1" in sliced["text"] and "y = 2" in sliced["text"]  # ordinary slice text survives
    assert sliced["withheld_count"] == 1 and "unreadable withheld line" in sliced["text"]


def test_a_withheld_block_under_a_diverged_header_never_travels(tmp_path, monkeypatch):
    """Cerberus round 10 (F3) and round 11 (F-A): the rebuild was conditional on
    the header spelling pinned here, so a slicer reporting withheld files under
    a DIFFERENT header passed its raw tail -- its own breadcrumbs -- through.
    Round 10 withheld the whole text and excepted the bounded case; round 11
    replaced both with one rule: a withheld-looking line never travels when the
    pinned header is absent, and ordinary slice text does."""
    from daedalus.structcore import slice as slicer
    _project_with_policy(monkeypatch, deny=["tct_app/devices/"])
    policy = _policy(tmp_path, planner_provider="codex_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, _gated_readers("", []))
    monkeypatch.setattr(adapter, "_cached_index", lambda repo_root: {"modules": {"pkg/mod.py": {}}})
    row = {"file": "tct_app/devices/iseg.py", "role": "context", "rule": "denylisted path fragment"}
    diverged = ("x = 1\n#### WITHHELD BLOCK v2 ####\n# tct_app/devices/iseg.py  (denylisted path fragment)")
    monkeypatch.setattr(slicer, "semantic_slice", lambda root, target, **kw: {
        "focus_file": target, "slice_tokens": 3, "n_included": 1, "slice_text": diverged, "withheld": [row]})
    sliced = adapter.execute("daedalus.slice", {"module": "pkg/mod.py"})
    payload = json.dumps(sliced)
    assert "iseg" not in payload and "denylisted path fragment" not in payload
    assert "x = 1" in sliced["text"]  # ordinary slice text is not collateral
    assert sliced["withheld_count"] == 1 and "unreadable withheld line" in sliced["text"]
    assert subject._WITHHELD_HEADER in sliced["text"]  # the gated block is there instead


def test_a_failure_while_consuming_a_payload_is_a_class_only_refusal(tmp_path, monkeypatch):
    """Odysseus round 9 (D33): ``_produce`` wrapped production, not consumption;
    a Mapping whose ``.get`` raises escaped ``execute`` with its message."""
    from daedalus.structcore import report as report_module

    class Hostile(dict):
        def get(self, key, default=None):
            raise RuntimeError("host path C:\\Users\\secret in the message")

    _project_with_policy(monkeypatch, deny=[])
    policy = _policy(tmp_path, planner_provider="claude_code_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, _gated_readers("", []))
    monkeypatch.setattr(adapter, "_cached_index", lambda repo_root: {"modules": {}})
    monkeypatch.setattr(report_module, "structure_summary", lambda idx, **kw: Hostile())
    with pytest.raises(ComputerRefused) as refused:
        adapter.execute("daedalus.structure", {})
    assert str(refused.value) == "observation failed (daedalus.structure): RuntimeError"


def test_a_non_list_producer_field_is_withheld_not_crashed_on(tmp_path, monkeypatch):
    """Odysseus round 8 (D30): ``sites=None`` or ``hotspots=5`` raised out of the
    observation instead of being withheld."""
    from daedalus.structcore import report as report_module
    _project_with_policy(monkeypatch, deny=[])
    policy = _policy(tmp_path, planner_provider="claude_code_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, _gated_readers("", []))
    monkeypatch.setattr(adapter, "_cached_index", lambda repo_root: {"modules": {}})
    monkeypatch.setattr(report_module, "structure_summary", lambda idx, **kw: {
        "n_files": 3, "languages": {}, "totals": {}, "hotspots": 5, "fan_in": None,
        "clones": [{"name": "c", "language": "python", "count": 2, "loc": 7, "sites": None},
                   {"name": "d", "language": "python", "count": 2, "loc": 7, "sites": [{"module": "pkg/a.py", "line": 1}]}],
        "ignored": {"count": 0, "n_files_scanned": 3, "ignore_patterns": "not-a-list"}})
    structure = adapter.execute("daedalus.structure", {})
    assert structure["hotspots"] == [] and structure["hotspots_withheld"] == 1
    assert structure["fan_in"] == [] and structure["fan_in_withheld"] == 1
    assert [c["name"] for c in structure["clones"]] == ["d"] and structure["clones_withheld"] == 1
    assert structure["ignored"]["ignore_patterns"] == []
    monkeypatch.setattr(report_module, "structure_summary", lambda idx, **kw: {"clones": 7, "ignored": {}})
    structure = adapter.execute("daedalus.structure", {})
    assert structure["clones"] == [] and structure["clones_withheld"] == 1


def test_one_admitted_candidate_resolves_without_naming_ambiguity(tmp_path, monkeypatch):
    """Odysseus round 7 (D27): "ambiguous; name one of: pkg/mod.py" with ONE
    admitted name told the planner a withheld second exists."""
    _project_with_policy(monkeypatch, deny=["tct_app/devices/"])
    policy = _policy(tmp_path, planner_provider="codex_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, _gated_readers("", []))
    idx = {"modules": {"pkg/mod.py": {}, "tct_app/devices/mod.py": {}}}
    assert adapter._resolve_module(idx, "mod.py") == "pkg/mod.py"
    with pytest.raises(ComputerRefused, match="name one of: lib/x.py, pkg/x.py"):
        adapter._resolve_module({"modules": {"pkg/x.py": {}, "lib/x.py": {}, "tct_app/devices/x.py": {}}}, "x.py")


def test_row_keys_from_a_producer_are_gated_when_no_projection_is_given(tmp_path, monkeypatch):
    """Cerberus round 7 (L1): without ``keep_keys`` the producer chose the key
    names; a key whose text is a host path was emitted ungated."""
    _project_with_policy(monkeypatch, deny=[])
    policy = _policy(tmp_path, planner_provider="claude_code_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, _gated_readers("", []))
    kept, withheld = adapter._admit_rows([{"C:\\Users\\victim\\SECRET\\key.pem": "x", "name": "a"},
                                          {"name": "b", "note": "fine"}], (), ("name",))
    assert kept == [{"name": "b", "note": "fine"}] and withheld == 1


def test_what_is_emitted_is_the_rendering_that_was_gated(tmp_path, monkeypatch):
    """Odysseus round 6 (D20): the value was rendered twice -- once to gate,
    once to emit -- so an object whose ``str()`` changes between calls was
    admitted as "benign" and emitted as a host path. Rendered once."""
    class Shifty:
        def __init__(self):
            self.calls = 0

        def __str__(self):
            self.calls += 1
            return "benign" if self.calls == 1 else "C:\\Users\\victim\\secret.key"

    _project_with_policy(monkeypatch, deny=[])
    policy = _policy(tmp_path, planner_provider="claude_code_cli", allow_remote_context=True)
    readers = subject.ProjectReaders(
        git_counters=lambda root: {"git_branch": "main", "git_status": "", "open_todos": 0, "shifty": Shifty()},
        bridge_status=lambda project: {"queue_depth": 0, "in_flight": 0, "unread_count": 0,
                                       "reports_total": 0, "watcher": {"state": "none"}},
        report_briefs=lambda project: [{"name": "a.report.json", "summary": "ok", "phase": Shifty()}])
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, readers)
    status = adapter.execute("daedalus.status", {})
    assert status["git"]["shifty"] == "benign"
    tasks = adapter.execute("daedalus.tasks", {})
    assert tasks["reports"][0]["phase"] == "benign"
    assert "victim" not in json.dumps(status) + json.dumps(tasks)


def test_a_reader_or_producer_failure_names_its_class_never_its_message(tmp_path, monkeypatch):
    """Odysseus round 6 (D21): a raising reader escaped ``execute`` with its
    message intact -- a PermissionError carries the absolute path -- and the
    service put that text into the planner's history. Every reader and
    producer failure is now a refusal naming the class only, provably before
    any effect."""
    from daedalus.spine import docrefs as docrefs_module
    from daedalus.structcore import report as report_module
    from daedalus.structcore import slice as slicer
    _project_with_policy(monkeypatch, deny=[])
    policy = _policy(tmp_path, planner_provider="claude_code_cli", allow_remote_context=True)
    boom = PermissionError("[Errno 13] Permission denied: 'C:\\Users\\victim\\OUTBOX\\x.json'")

    def raising(*args, **kwargs):
        raise boom
    readers = subject.ProjectReaders(git_counters=raising, bridge_status=raising, report_briefs=raising)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, readers)
    for tool in ("daedalus.status", "daedalus.tasks"):
        with pytest.raises(ComputerRefused) as refused:
            adapter.execute(tool, {})
        assert "PermissionError" in str(refused.value) and "victim" not in str(refused.value)
    shaped = subject.ProjectReaders(git_counters=lambda root: ["not", "a", "mapping"],
                                    bridge_status=lambda project: "nope", report_briefs=lambda project: 17)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, shaped)
    with pytest.raises(ComputerRefused, match="git counters"):
        adapter.execute("daedalus.status", {})
    with pytest.raises(ComputerRefused, match="TypeError"):
        adapter.execute("daedalus.tasks", {})
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, _gated_readers("", []))
    monkeypatch.setattr(adapter, "_cached_index", lambda repo_root: {"modules": {"pkg/mod.py": {}}})
    monkeypatch.setattr(report_module, "structure_summary", raising)
    monkeypatch.setattr(docrefs_module, "scan", raising)
    monkeypatch.setattr(slicer, "semantic_slice", raising)
    for tool, args in (("daedalus.structure", {}), ("daedalus.docrefs", {}), ("daedalus.slice", {"module": "pkg/mod.py"})):
        with pytest.raises(ComputerRefused) as refused:
            adapter.execute(tool, args)
        assert "PermissionError" in str(refused.value) and "victim" not in str(refused.value)


def test_counters_are_gated_like_every_other_value(tmp_path, monkeypatch):
    """Odysseus round 6 (D23): ``n_files``, ``languages``, ``totals``, the
    docrefs and slice counters passed ungated. A producer that put a path
    there would have handed it on."""
    from daedalus.structcore import report as report_module
    _project_with_policy(monkeypatch, deny=[])
    policy = _policy(tmp_path, planner_provider="claude_code_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, _gated_readers("", []))
    monkeypatch.setattr(adapter, "_cached_index", lambda repo_root: {"modules": {}})
    monkeypatch.setattr(report_module, "structure_summary", lambda idx, **kw: {
        "n_files": "C:\\Users\\victim\\n", "languages": {"python": {"files": 2}}, "totals": {"loc": 5},
        "hotspots": [], "fan_in": [], "clones": [],
        "ignored": {"count": 1, "n_files_scanned": "/home/victim/x", "ignore_patterns": []}})
    structure = adapter.execute("daedalus.structure", {})
    assert "n_files" not in structure and structure["fields_withheld"] == 1
    assert structure["languages"] == {"python": {"files": 2}} and structure["totals"] == {"loc": 5}
    assert structure["ignored"]["count"] == 1 and "n_files_scanned" not in structure["ignored"]
    assert structure["ignored"]["fields_withheld"] == 1
    assert "victim" not in json.dumps(structure)


def test_an_unrenderable_value_is_withheld_and_counted_not_crashed_on(tmp_path, monkeypatch):
    """Odysseus round 5 (D16): NaN, a non-string dict key and an object whose
    ``str()`` raises made ``_json_safe`` raise out of the observation."""
    class Explodes:
        def __str__(self):
            raise RuntimeError("no")

    _project_with_policy(monkeypatch, deny=[])
    policy = _policy(tmp_path, planner_provider="claude_code_cli", allow_remote_context=True)
    readers = subject.ProjectReaders(
        git_counters=lambda root: {"git_branch": "main", "git_status": "", "open_todos": 0,
                                   "ratio": float("nan"), "inf": float("inf"), "keyed": {1.5: "x", (1, 2): "y"},
                                   "boom": Explodes()},
        bridge_status=lambda project: {"queue_depth": float("nan"), "in_flight": 0, "unread_count": 0,
                                       "reports_total": 0, "watcher": {"state": "none"}},
        report_briefs=lambda project: [{"name": "a.report.json", "summary": "ok", "phase": float("nan")},
                                       {"name": "b.report.json", "summary": "fine"}])
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, readers)
    status = adapter.execute("daedalus.status", {})
    assert set(status["git"]) == {"git_branch", "git_status", "open_todos", "git_status_withheld", "fields_withheld"}
    assert status["git"]["fields_withheld"] == 4
    assert status["queue"]["fields_withheld"] == 1 and "queue_depth" not in status["queue"]
    tasks = adapter.execute("daedalus.tasks", {})
    assert [row["name"] for row in tasks["reports"]] == ["b.report.json"] and tasks["reports_withheld"] == 1


def test_a_unique_hit_the_gate_withholds_answers_like_a_miss(tmp_path, monkeypatch):
    """Odysseus round 5 (D18): a basename resolving uniquely into a denied
    directory said "<withheld>" while a miss said "not in the index" -- one bit
    per guess confirming that a withheld file exists. Both now say the same."""
    _project_with_policy(monkeypatch, deny=["tct_app/devices/"])
    policy = _policy(tmp_path, planner_provider="codex_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, _gated_readers("", []))
    idx = {"modules": {"tct_app/devices/iseg.py": {}, "pkg/mod.py": {}}}
    with pytest.raises(ComputerRefused) as hit:
        adapter._resolve_module(idx, "iseg.py")
    with pytest.raises(ComputerRefused) as miss:
        adapter._resolve_module(idx, "nothere.py")
    assert str(hit.value) == str(miss.value) == subject._MODULE_UNAVAILABLE
    assert adapter._resolve_module(idx, "mod.py") == "pkg/mod.py"


def test_the_focus_gate_holds_even_if_resolution_admitted_a_withheld_path(tmp_path, monkeypatch):
    """Defence in depth behind D18 (mutation M37): should resolution ever hand
    a withheld path to the slicer, the observation still does not name it."""
    from daedalus.structcore import slice as slicer
    _project_with_policy(monkeypatch, deny=["tct_app/devices/"])
    policy = _policy(tmp_path, planner_provider="codex_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, _gated_readers("", []))
    monkeypatch.setattr(adapter, "_cached_index", lambda repo_root: {"modules": {}})
    monkeypatch.setattr(adapter, "_resolve_module", lambda idx, module: "tct_app/devices/iseg.py")
    monkeypatch.setattr(slicer, "semantic_slice", lambda root, target, **kw: {
        "focus_file": target, "slice_tokens": 1, "n_included": 1, "slice_text": "x = 1\n", "withheld": []})
    sliced = adapter.execute("daedalus.slice", {"module": "iseg.py"})
    assert sliced["focus_file"] == "<withheld>"
    assert "iseg" not in json.dumps(sliced) and "tct_app" not in json.dumps(sliced)


def test_a_focus_file_containing_the_header_literal_keeps_its_text(tmp_path, monkeypatch):
    """Odysseus round 5 (D15): the rebuild split at the FIRST occurrence of the
    slicer's header, so a focus file containing the literal (this adapter does)
    lost everything after it while claiming completeness. Without withheld rows
    nothing is rebuilt; with rows the slicer's block is the LAST occurrence."""
    from daedalus.structcore import slice as slicer
    _project_with_policy(monkeypatch, deny=["tct_app/devices/"])
    policy = _policy(tmp_path, planner_provider="codex_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, _gated_readers("", []))
    rule = _real_rules(adapter)["deny"]
    body = ('HEADER = "# ===== WITHHELD (egress gate) ====="\n'
            "# ===== WITHHELD (egress gate) =====\n# not/a/breadcrumb.py  (fake)  [neighbor]\nLEGIT_TAIL = 1\n")
    monkeypatch.setattr(adapter, "_cached_index", lambda repo_root: {"modules": {"pkg/mod.py": {}}})
    monkeypatch.setattr(slicer, "semantic_slice", lambda root, target, **kw: {
        "focus_file": target, "slice_tokens": 9, "n_included": 1, "slice_text": body, "withheld": []})
    clean = adapter.execute("daedalus.slice", {"module": "pkg/mod.py"})
    assert clean["text"] == body and clean["withheld"] == []
    monkeypatch.setattr(slicer, "semantic_slice", lambda root, target, **kw: {
        "focus_file": target, "slice_tokens": 9, "n_included": 1,
        "slice_text": body + f"\n# ===== WITHHELD (egress gate) =====\n# tct_app/devices/iseg.py  ({rule})  [dependency]",
        "withheld": [{"file": "tct_app/devices/iseg.py", "role": "dependency", "rule": rule}]})
    sliced = adapter.execute("daedalus.slice", {"module": "pkg/mod.py"})
    assert sliced["text"] == body + "\n# ===== WITHHELD (egress gate) =====\n# <withheld>  (denylisted_path)  [dependency]"
    assert "iseg" not in json.dumps(sliced)


def test_tasks_gate_every_brief_before_the_bound_and_count_the_elision(tmp_path, monkeypatch):
    """Odysseus round 5 (D19): ``[-TOP:]`` ran before the gate, so withheld
    rows consumed the bound, and no elision was reported."""
    _project_with_policy(monkeypatch, deny=[], deny_content=[r"iseg"])
    policy = _policy(tmp_path, planner_provider="codex_cli", allow_remote_context=True)
    briefs = [{"name": f"old{i}.report.json", "summary": "fine"} for i in range(3)]
    briefs += [{"name": f"r{i}.report.json", "summary": "touched the iseg driver"} for i in range(subject.TOP)]
    briefs += [{"name": f"new{i}.report.json", "summary": "fine"} for i in range(subject.TOP)]
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, _gated_readers("", briefs))
    tasks = adapter.execute("daedalus.tasks", {})
    assert [row["name"] for row in tasks["reports"]] == [f"new{i}.report.json" for i in range(subject.TOP)]
    assert tasks["reports_withheld"] == subject.TOP and tasks["reports_elided"] == 3


def test_structure_counts_the_admitted_rows_the_top_bound_drops(tmp_path, monkeypatch):
    """Odysseus round 4 (D13): ``[:TOP]`` truncated silently; a short list read
    as a complete one. The dropped admitted rows are counted apart from the
    gate's refusals."""
    from daedalus.structcore import report as report_module
    _project_with_policy(monkeypatch, deny=["tct_app/devices/"])
    policy = _policy(tmp_path, planner_provider="codex_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, _gated_readers("", []))
    monkeypatch.setattr(adapter, "_cached_index", lambda repo_root: {"modules": {}})
    many = subject.TOP + 2
    monkeypatch.setattr(report_module, "structure_summary", lambda idx, **kw: {
        "n_files": many + 1, "languages": {}, "totals": {},
        "hotspots": [{"module": f"pkg/h{i}.py", "score": i} for i in range(many)]
                    + [{"module": "tct_app/devices/x.py", "score": 99}],
        "fan_in": [{"module": f"pkg/f{i}.py", "count": i} for i in range(many)],
        "clones": [], "ignored": {"count": 0, "n_files_scanned": 1, "ignore_patterns": [f"@p{i}" for i in range(many)]}})
    structure = adapter.execute("daedalus.structure", {})
    assert len(structure["hotspots"]) == subject.TOP
    assert structure["hotspots_withheld"] == 1 and structure["hotspots_elided"] == 2
    assert structure["fan_in_withheld"] == 0 and structure["fan_in_elided"] == 2
    assert structure["clones_elided"] == 0
    assert structure["ignored"]["ignore_patterns_withheld"] == 0 and structure["ignored"]["ignore_patterns_elided"] == 2


def test_slice_gate_rules_never_quote_the_marker_they_fired_on(tmp_path, monkeypatch):
    """Odysseus round 3 (D6): ``content matches sensitive marker /CODENAME/`` in a
    withheld row or in the focus refusal line disclosed the codename itself."""
    from daedalus.structcore import slice as slicer
    _project_with_policy(monkeypatch, deny=[], deny_content=[r"ODYSSEUSCHIMERA"])
    policy = _policy(tmp_path, planner_provider="codex_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, _gated_readers("", []))
    monkeypatch.setattr(adapter, "_cached_index", lambda repo_root: {"modules": {"pkg/two.py": {}}})
    monkeypatch.setattr(slicer, "semantic_slice", lambda root, target, **kw: {
        "focus_file": target, "slice_tokens": 0, "n_included": 0,
        "slice_text": "# ===== WITHHELD: pkg/two.py (content matches sensitive marker /ODYSSEUSCHIMERA/) =====\n",
        "withheld": [{"file": "pkg/two.py", "role": "focus",
                      "rule": "content matches sensitive marker /ODYSSEUSCHIMERA/"}]})
    sliced = adapter.execute("daedalus.slice", {"module": "pkg/two.py"})
    assert sliced["withheld"] == [{"role": "focus", "rule": "deny_content"}]
    assert sliced["text"] == ("# ===== WITHHELD: <withheld> (deny_content) =====\n"
                              "# focus file withheld by the egress gate (lane=untrusted); slice refused (fail-closed).")
    assert "ODYSSEUSCHIMERA" not in json.dumps(sliced)


def test_nested_strings_in_a_kept_field_are_gated(tmp_path, monkeypatch):
    """Cerberus round 3 (b): a kept key holding a list or dict of strings is gated."""
    _project_with_policy(monkeypatch, deny=[], deny_content=[r"ODYSSEUSCHIMERA"])
    policy = _policy(tmp_path, planner_provider="codex_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, _gated_readers("", []))
    kept, withheld = adapter._admit_rows(
        [{"doc_path": "docs/a.md", "extra": ["fine", {"deep": "ODYSSEUSCHIMERA"}]},
         {"doc_path": "docs/b.md", "extra": ["fine", {"deep": "C:\\Users\\x\\y"}]},
         {"doc_path": "docs/c.md", "extra": ["fine"]}],
        ("doc_path",), (), keep_keys=("doc_path", "extra"))
    assert [row["doc_path"] for row in kept] == ["docs/c.md"]
    assert withheld == 2


def test_kept_fields_outside_the_text_keys_are_gated_too(tmp_path, monkeypatch):
    """Odysseus round 2 (D1): a task brief's ``phase`` (kept, not a text key)
    carried an absolute host path to the planner through the real service."""
    _project_with_policy(monkeypatch, deny=[], deny_content=[r"\bODYSSEUSCHIMERA\b"])
    policy = _policy(tmp_path, planner_provider="codex_cli", allow_remote_context=True)
    briefs = [{"name": "ok.report.json", "summary": "finished", "phase": "done"},
              {"name": "path.report.json", "summary": "finished",
               "phase": "failed reading C:\\Users\\someone\\Desktop\\projects\\daedalus\\memory\\todos.local.md"},
              {"name": "code.report.json", "summary": "finished", "phase": "ODYSSEUSCHIMERA-42"}]
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, _gated_readers("", briefs))
    tasks = adapter.execute("daedalus.tasks", {})
    assert [row["name"] for row in tasks["reports"]] == ["ok.report.json"]
    assert tasks["reports_withheld"] == 2
    assert "someone" not in json.dumps(tasks) and "ODYSSEUSCHIMERA" not in json.dumps(tasks)


def test_deny_content_applies_to_the_path_itself(tmp_path, monkeypatch):
    """Odysseus round 2 (D2): a codename INSIDE an allow-listed module path or
    doc path passed, because classify_data applies deny_content to text only."""
    _project_with_policy(monkeypatch, deny=[], deny_content=[r"ODYSSEUSCHIMERA"])
    from daedalus.spine import docrefs as docrefs_module
    from daedalus.structcore import report as report_module
    policy = _policy(tmp_path, planner_provider="codex_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, _gated_readers("", []))
    monkeypatch.setattr(adapter, "_cached_index", lambda repo_root: {"modules": {}})
    monkeypatch.setattr(report_module, "structure_summary", lambda idx, **kw: {
        "n_files": 2, "ignored": {}, "languages": {}, "totals": {},
        "hotspots": [{"module": "pkg/test_odysseuschimera.py", "score": 1.0}, {"module": "pkg/plain.py", "score": 1.0}],
        "clones": [], "fan_in": [{"module": "pkg/ODYSSEUSCHIMERA_core.py", "count": 3}]})
    structure = adapter.execute("daedalus.structure", {})
    assert [row["module"] for row in structure["hotspots"]] == ["pkg/plain.py"]
    assert structure["fan_in"] == [] and structure["fan_in_withheld"] == 1

    class Report:
        def to_dict(self):
            return {"n_resolving": 1, "n_broken": 1, "n_skipped": 0, "files_scanned": 1,
                    "broken": [{"doc_path": "docs/ODYSSEUSCHIMERA-plan.md", "line": 1, "raw": "pkg.x", "module_path": "", "symbol": "x"}],
                    "errors": []}
    monkeypatch.setattr(docrefs_module, "scan", lambda repo_root: Report())
    result = adapter.execute("daedalus.docrefs", {})
    assert result["broken"] == [] and result["broken_withheld"] == 1
    assert "ODYSSEUSCHIMERA" not in json.dumps(structure) + json.dumps(result)


def test_a_task_summary_with_an_embedded_host_path_is_withheld(tmp_path, monkeypatch):
    """Odysseus 2026-09-10 (defect 3): `report_brief` can carry an error text
    that embeds the absolute project path; the whole-value shape check missed it."""
    _project_with_policy(monkeypatch, deny=[])
    policy = _policy(tmp_path, planner_provider="claude_code_cli", allow_remote_context=True)
    briefs = [{"name": "ok.report.json", "summary": "finished"},
              {"name": "bad.report.json",
               "summary": "PermissionError: [Errno 13] Permission denied: 'C:\\\\Users\\\\someone\\\\repo\\\\docs\\\\handoff.md'"}]
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, _gated_readers("", briefs))
    tasks = adapter.execute("daedalus.tasks", {})
    assert [row["name"] for row in tasks["reports"]] == ["ok.report.json"]
    assert tasks["reports_withheld"] == 1
    assert "someone" not in json.dumps(tasks)


def test_the_real_adapter_through_the_real_lease_creates_no_cache_and_launches_no_pool(
        scratch_repo, tmp_path, monkeypatch):
    """Odysseus 2026-09-10 (defect 1): the service half used to substitute a
    fake adapter, so the cache write under the profile was invisible. This
    runs the REAL adapter under the REAL persisted lease: a fresh
    DAEDALUS_CACHE_DIR must stay empty and the retained result must say
    host_mutation False truthfully."""
    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setenv("USERPROFILE", str(profile))
    monkeypatch.setattr(killswitch, "OS_PROFILE_DIR", profile)
    monkeypatch.delenv("DAEDALUS_KILLSWITCH", raising=False)
    cache_dir = tmp_path / "structcore-cache"
    monkeypatch.setenv("DAEDALUS_CACHE_DIR", str(cache_dir))
    from daedalus.structcore import index as index_module
    monkeypatch.setattr(index_module, "_INDEX_CACHE", {}, raising=False)
    # Cerberus N2: the name promises "launches no pool" -- pinned directly. A
    # pool or a churn ``git log`` inside the observation fails the test here.
    import concurrent.futures as futures

    def no_pool(*args, **kwargs):
        raise AssertionError("a process pool was created inside a read-only observation")
    monkeypatch.setattr(futures, "ProcessPoolExecutor", no_pool)
    monkeypatch.setattr(index_module, "git_churn",
                        lambda root: (_ for _ in ()).throw(AssertionError("git log ran inside a read-only observation")))
    authority = tmp_path / "authority"
    authority.mkdir()
    workspace = tmp_path / "scratch"
    workspace.mkdir()
    policy = ComputerPolicy(workspace=workspace, tools=DAEDALUS_TOOLS, planner_provider="claude_code_cli",
                            allow_remote_context=True)
    path = policy_path(authority)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(policy.to_dict()), encoding="utf-8")
    switch = killswitch.KillSwitch(repo_root=authority, sweep_managed=False)
    assert switch.arm(note="real-adapter effect-freeness fixture").running
    service = service_module.ComputerService(authority, project="fixture", project_readers=_readers())
    for tool in ("daedalus.status", "daedalus.structure", "daedalus.slice", "daedalus.docrefs"):
        args = {"module": "mod.py"} if tool == "daedalus.slice" else {}
        outcome = service.execute(tool, args, mission_id="computer-real", attempt_id=f"attempt-{tool}")
        assert outcome["ok"] is True, (tool, outcome)
    assert not cache_dir.exists() or not any(cache_dir.rglob("*")), list(cache_dir.rglob("*"))
    stored = [json.loads(p.read_text(encoding="utf-8")) for p in (service.control / "computer-artifacts").glob("*.json")]
    results = [b for b in stored if b.get("schema") == "daedalus-computer-result/1"]
    assert {b["tool"] for b in results} == {"daedalus.status", "daedalus.structure", "daedalus.slice", "daedalus.docrefs"}
    assert all(b["host_mutation"] is False and b["filesystem_scope_kind"] == "project-registry-read-only" for b in results)
    assert str(scratch_repo) not in json.dumps([b["result"] for b in results])


def test_dispatch_refuses_the_family_directly_without_a_project_or_readers(configured):
    """Odysseus 2026-09-10 (mutation M14): the `_dispatch` copies of the two
    refusals are defense in depth behind admission; pinned directly."""
    authority, _ = configured
    with pytest.raises(ComputerRefused, match="no registered project"):
        service_module.ComputerService(authority)._dispatch("daedalus.status", {})
    with pytest.raises(ComputerRefused, match="project readers"):
        service_module.ComputerService(authority, project="agent_env")._dispatch("daedalus.status", {})


def test_rows_without_a_path_or_a_text_are_withheld_not_passed(tmp_path, monkeypatch):
    """Cerberus N3: `_admit_rows` must be fail-closed for a row the gate never sees."""
    _project_with_policy(monkeypatch, deny=[])
    adapter = _adapter(tmp_path, readers=_gated_readers("", []))
    kept, withheld = adapter._admit_rows([{"line": 3}, {"doc_path": "docs/a.md", "line": 1}],
                                         ("doc_path",), ("raw",), keep_keys=("doc_path", "line"))
    assert kept == [{"doc_path": "docs/a.md", "line": 1}]
    assert withheld == 1


def test_the_project_policy_is_re_read_on_every_call(tmp_path, monkeypatch):
    """Cerberus N5: a project row tightened mid-mission takes effect on the next call."""
    from daedalus.foundation import projects
    monkeypatch.setattr(projects, "resolve_repo_root", lambda repo_root, project: "unused")
    rows = {"policy": {"deny": [], "deny_content": [], "allow": ["pkg/"]}}
    monkeypatch.setattr(projects, "load_project", lambda name: {"name": name, **rows})
    policy = _policy(tmp_path, planner_provider="codex_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path,
                                          _gated_readers(" M pkg/mod.py", []))
    assert adapter.execute("daedalus.status", {})["git"]["git_status"] == " M pkg/mod.py"
    rows["policy"] = {"deny": ["pkg/"], "deny_content": [], "allow": ["pkg/"]}
    assert adapter.execute("daedalus.status", {})["git"]["git_status"] == ""


def test_the_index_is_built_effect_free(tmp_path, monkeypatch):
    from daedalus.structcore import index as index_module
    seen = {}

    def fake_cached_index(repo_root, **kwargs):
        seen.update(kwargs)
        return {"modules": {}}
    monkeypatch.setattr(index_module, "cached_index", fake_cached_index)
    adapter = _adapter(tmp_path)
    monkeypatch.setattr(adapter, "_repo_root", lambda: str(tmp_path))
    adapter._cached_index(str(tmp_path))
    assert seen == {"effect_free": True}


def test_a_project_whose_policy_row_cannot_load_is_refused_not_generic(tmp_path, monkeypatch):
    from daedalus.foundation import projects
    monkeypatch.setattr(projects, "resolve_repo_root", lambda repo_root, project: str(tmp_path))

    def broken(name):
        raise projects.ProjectRegistryUnavailable("row unreadable")
    monkeypatch.setattr(projects, "load_project", broken)
    adapter = _adapter(tmp_path, readers=_gated_readers(" M x.py", []))
    with pytest.raises(ComputerRefused, match="project policy is unavailable"):
        adapter.execute("daedalus.status", {})


def test_the_lane_is_derived_per_call_not_at_construction(tmp_path, monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    adapter = _adapter(tmp_path)
    assert adapter.lane == "trusted"
    monkeypatch.setenv("OLLAMA_HOST", "http://bench.tailnet:11434")
    assert adapter.lane == "untrusted"


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
    # ignore-file path; only the counts and the ignore PATTERNS are observed
    # now, under the key the index really emits (Cerberus N7).
    assert set(structure["ignored"]) == {"count", "n_files_scanned", "ignore_patterns", "ignore_patterns_withheld",
                                         "ignore_patterns_elided", "fields_withheld"}
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
