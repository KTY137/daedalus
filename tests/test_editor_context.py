from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from daedalus import editor_context, projects


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


@pytest.fixture()
def registered_project(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "docs").mkdir()
    (repo / "src" / "main.py").write_text(
        "def greet(name):\n    return f'hello {name}'\n", encoding="utf-8")
    (repo / "docs" / "guide.md").write_text(
        "# Guide\n\nAttach this paragraph.\n", encoding="utf-8")
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Daedalus Test")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")

    registry = tmp_path / "projects"
    registry.mkdir()
    (registry / "sample.json").write_text(json.dumps({
        "name": "sample",
        "repo_root": str(repo),
        "policy": {"allow": ["docs/"]},
    }), encoding="utf-8")
    monkeypatch.setattr(projects, "PROJECT_DIR", registry)
    monkeypatch.setenv(
        "DAEDALUS_EDITOR_CONTEXT_DIR", str(tmp_path / "editor-artifacts"))
    return repo, _git(repo, "rev-parse", "HEAD")


def test_context_is_project_bound_content_addressed_and_public_projection_hides_text(
        registered_project):
    _repo, revision = registered_project
    view = editor_context.create_context(
        project="sample", source="vscode", path="src/main.py",
        selection="return f'hello {name}'",
        range={"start_line": 2, "start_column": 5,
               "end_line": 2, "end_column": 27},
        base_revision=revision,
    )

    assert view["context_ref"].startswith(editor_context.CONTEXT_PREFIX)
    assert view["base_revision"] == revision
    assert view["path"] == "src/main.py"
    assert view["selection_chars"] > 0
    assert view["revision_state"] == "base_revision"
    assert "selection" not in view
    assert str(registered_project[0]) not in json.dumps(view)
    assert editor_context.get_context(view["context_ref"]) == view


@pytest.mark.parametrize("path", ["../outside.py", "/etc/passwd", r"C:\outside.py"])
def test_context_refuses_absolute_and_traversing_paths(registered_project, path):
    with pytest.raises(editor_context.EditorContextRefused):
        editor_context.create_context(
            project="sample", source="vscode", path=path, selection="")


def test_context_refuses_stale_revision_and_spoofed_selection(registered_project):
    with pytest.raises(editor_context.EditorContextRefused, match="stale"):
        editor_context.create_context(
            project="sample", source="vscode", path="src/main.py",
            selection="return", base_revision="0" * 40)
    with pytest.raises(editor_context.EditorContextRefused, match="does not match"):
        editor_context.create_context(
            project="sample", source="vscode", path="src/main.py",
            selection="this was never in the file")

    with pytest.raises(editor_context.EditorContextRefused, match="does not match"):
        editor_context.create_context(
            project="sample", source="vscode", path="src/main.py",
            selection="return f'hello {name}'",
            range={"start_line": 1, "start_column": 1,
                   "end_line": 1, "end_column": 4})


def test_dirty_selection_is_labelled_and_pinned_to_exact_file_bytes(
        registered_project):
    repo, _revision = registered_project
    path = repo / "src" / "main.py"
    path.write_text(
        "def greet(name):\n    return f'hello there {name}'\n", encoding="utf-8")
    view = editor_context.create_context(
        project="sample", source="vscode", path="src/main.py",
        selection="return f'hello there {name}'")

    assert view["revision_state"] == "working_tree"
    first = editor_context.materialize_capsule(
        [view["context_ref"]], project="sample", lane="trusted")
    assert first["accepted"][0]["revision_state"] == "working_tree"

    path.write_text(
        "def greet(name):\n    return f'changed again {name}'\n", encoding="utf-8")
    stale = editor_context.materialize_capsule(
        [view["context_ref"]], project="sample", lane="trusted")
    assert stale["accepted"] == []
    assert "changed after" in stale["rejected"][0]["reason"]


def test_context_refuses_secret_floor_before_artifact_creation(registered_project):
    repo, _revision = registered_project
    secret = repo / "src" / "settings.py"
    secret.write_text('api_key = "abcdefghijklmnop"\n', encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "secret fixture")

    with pytest.raises(editor_context.EditorContextRefused, match="secret floor"):
        editor_context.create_context(
            project="sample", source="vscode", path="src/settings.py",
            selection='api_key = "abcdefghijklmnop"')


def test_context_refuses_secret_in_diagnostic_summary(registered_project):
    with pytest.raises(editor_context.EditorContextRefused, match="secret floor"):
        editor_context.create_context(
            project="sample", source="vscode", path="src/main.py",
            selection="return f'hello {name}'",
            diagnostics=[{"message": 'api_key = "abcdefghijklmnop"'}])


def test_capsule_reports_untrusted_egress_refusals_without_silent_truncation(
        registered_project):
    source = editor_context.create_context(
        project="sample", source="vscode", path="src/main.py",
        selection="return f'hello {name}'")
    docs = editor_context.create_context(
        project="sample", source="vscode", path="docs/guide.md",
        selection="Attach this paragraph.")

    capsule = editor_context.materialize_capsule(
        [source["context_ref"], docs["context_ref"]],
        project="sample", lane="untrusted")

    assert capsule["capsule_ref"].startswith(editor_context.CAPSULE_PREFIX)
    assert [row["path"] for row in capsule["accepted"]] == ["docs/guide.md"]
    assert capsule["rejected"][0]["context_ref"] == source["context_ref"]
    assert "Attach this paragraph." in capsule["text"]
    assert "hello" not in capsule["text"]


def test_editor_session_is_token_bound_capability_limited_and_navigation_only(
        registered_project):
    registry = editor_context.EditorSessionRegistry()
    created = registry.create(
        project="sample", adapter="vscode", capabilities=["reveal_location"])

    with pytest.raises(editor_context.UnknownEditorSession):
        registry.events(created["session_id"], "wrong-token")
    with pytest.raises(editor_context.EditorContextRefused, match="not declared"):
        registry.command(
            created["session_id"], created["session_token"], "open_diff",
            {"path": "src/main.py"})

    event = registry.command(
        created["session_id"], created["session_token"], "reveal_location",
        {"path": "src/main.py", "line": 2})
    assert event["payload"]["path"] == "src/main.py"
    assert registry.events(
        created["session_id"], created["session_token"], after=0) == [event]
