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
                                    "ignore_patterns_withheld": 0}
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
                                    "ignore_patterns_withheld": 2}


def test_slice_withheld_rows_name_the_rule_never_the_file(tmp_path, monkeypatch):
    """Cerberus round 3 (H2): the withheld rows enumerated exactly the files the
    project keeps from the vendor; only role and rule travel, plus the count,
    and the slicer's own breadcrumb lines are scrubbed to the same shape."""
    from daedalus.structcore import slice as slicer
    _project_with_policy(monkeypatch, deny=["tct_app/devices/"])
    policy = _policy(tmp_path, planner_provider="codex_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, _gated_readers("", []))
    monkeypatch.setattr(adapter, "_cached_index", lambda repo_root: {"modules": {"pkg/mod.py": {}}})
    monkeypatch.setattr(slicer, "semantic_slice", lambda root, target, **kw: {
        "focus_file": target, "slice_tokens": 3, "n_included": 1,
        "slice_text": ("def present():\n    return 1\n\n# ===== WITHHELD (egress gate) =====\n"
                       "# tct_app/devices/iseg.py  (egress policy: tct_app/devices/)  [neighbor]\n"
                       "# configs/secrets/lab.yaml  (secret path)  [neighbor]\n"),
        "withheld": [{"file": "tct_app/devices/iseg.py", "role": "neighbor", "rule": "egress policy: tct_app/devices/"},
                     {"file": "configs/secrets/lab.yaml", "role": "neighbor", "rule": "secret path"}]})
    sliced = adapter.execute("daedalus.slice", {"module": "pkg/mod.py"})
    assert sliced["withheld"] == [{"role": "neighbor", "rule": "egress policy: tct_app/devices/"},
                                  {"role": "neighbor", "rule": "secret path"}]
    assert sliced["withheld_count"] == 2
    assert "iseg" not in json.dumps(sliced) and "lab.yaml" not in json.dumps(sliced)
    assert "# <withheld>  (secret path)  [neighbor]" in sliced["text"]
    assert "# ===== WITHHELD (egress gate) =====" in sliced["text"]


def test_slice_gate_rules_never_quote_the_marker_they_fired_on(tmp_path, monkeypatch):
    """Odysseus round 3 (D6): ``content matches sensitive marker /CODENAME/`` in a
    withheld row or in the focus refusal line disclosed the codename itself."""
    from daedalus.structcore import slice as slicer
    _project_with_policy(monkeypatch, deny=[], deny_content=[r"ODYSSEUSCHIMERA"])
    policy = _policy(tmp_path, planner_provider="codex_cli", allow_remote_context=True)
    adapter = subject.DaedalusObservation(policy, "fixture", lambda: None, tmp_path, _gated_readers("", []))
    monkeypatch.setattr(adapter, "_cached_index", lambda repo_root: {"modules": {"tests/test_two.py": {}}})
    monkeypatch.setattr(slicer, "semantic_slice", lambda root, target, **kw: {
        "focus_file": target, "slice_tokens": 0, "n_included": 0,
        "slice_text": "# ===== WITHHELD: tests/test_two.py (content matches sensitive marker /ODYSSEUSCHIMERA/) =====\n",
        "withheld": [{"file": "tests/test_two.py", "role": "focus",
                      "rule": "content matches sensitive marker /ODYSSEUSCHIMERA/"}]})
    sliced = adapter.execute("daedalus.slice", {"module": "tests/test_two.py"})
    assert sliced["withheld"] == [{"role": "focus", "rule": "content matches sensitive marker /<marker>/"}]
    assert sliced["text"] == "# ===== WITHHELD: <withheld> (content matches sensitive marker /<marker>/) =====\n"
    assert "ODYSSEUSCHIMERA" not in json.dumps({k: v for k, v in sliced.items() if k != "focus_file"})


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
    assert set(structure["ignored"]) == {"count", "n_files_scanned", "ignore_patterns", "ignore_patterns_withheld"}
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
