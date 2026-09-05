from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys

import pytest

from daedalus.orchestration.genesis.materializer import (
    KANBAN_BOARD_BLUEPRINT,
    render_project,
)
from daedalus.twin.reference_compiler import compile_reference_project


REVISION = "a" * 40
CREATED_AT = "2026-09-04T12:00:00+00:00"


def _write_project(root: Path, files: dict[str, bytes]) -> None:
    for relative, payload in files.items():
        target = root.joinpath(*PurePosixPath(relative).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)


def _run_generated_tests(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )


@pytest.mark.parametrize("target", ("web", "cli", "desktop", "mobile"))
def test_render_is_deterministic_bytes_on_safe_sorted_paths(target: str) -> None:
    first = render_project("Keep a local reading list", "Pocket Shelf", target)
    second = render_project("Keep a local reading list", "Pocket Shelf", target)

    assert first == second
    assert list(first) == sorted(first)
    assert first
    assert all(type(payload) is bytes for payload in first.values())
    assert len({path.casefold() for path in first}) == len(first)
    for raw_path in first:
        path = PurePosixPath(raw_path)
        assert raw_path == path.as_posix()
        assert not path.is_absolute()
        assert "\\" not in raw_path
        assert ":" not in raw_path
        assert all(part not in {"", ".", ".."} for part in path.parts)
    assert all(not payload.endswith(b"\r\n") for payload in first.values())


def test_normalises_stable_user_text_and_target_spelling() -> None:
    canonical = render_project("Track work", "Caf\u00e9 Board", "web")
    equivalent = render_project(" \r\nTrack work\r\n", " Cafe\u0301 Board ", " WEB ")

    assert equivalent == canonical


@pytest.mark.parametrize(
    ("prompt", "product_name", "target", "error"),
    (
        ("", "Name", "web", ValueError),
        ("Prompt", "", "web", ValueError),
        ("Prompt", "Bad\nName", "web", ValueError),
        ("Prompt", "Name", "native", ValueError),
        (None, "Name", "web", TypeError),
        ("Prompt", object(), "web", TypeError),
        ("Prompt", "Name", None, TypeError),
    ),
)
def test_invalid_inputs_refuse_before_render(
    prompt: object, product_name: object, target: object, error: type[Exception]
) -> None:
    with pytest.raises(error):
        render_project(prompt, product_name, target)  # type: ignore[arg-type]


def test_display_name_cannot_influence_paths_or_inject_html() -> None:
    hostile = "../../<script>alert('x')</script>"
    files = render_project("Keep everything local", hostile, "web")

    assert all(".." not in PurePosixPath(path).parts for path in files)
    index = files["index.html"].decode("utf-8")
    assert "<script>alert('x')</script>" not in index
    assert "&lt;script&gt;" in index
    manifest = json.loads(files["fourfold.json"])
    assert manifest["repository_id"].startswith("genesis/script-alert-x-script-web-")
    assert ".." not in manifest["repository_id"]


@pytest.mark.parametrize("target", ("web", "desktop", "mobile"))
def test_browser_targets_are_offline_localstorage_crud_pwas(target: str) -> None:
    files = render_project("Collect and complete private notes", "Local Notes", target)

    assert {
        "README.md",
        "app.js",
        "fourfold.json",
        "icons/icon-192.svg",
        "icons/icon-512.svg",
        "index.html",
        "manifest.webmanifest",
        "model.py",
        "schemas/item.schema.json",
        "server.py",
        "service-worker.js",
        "styles.css",
        "tests/test_project.py",
    } == set(files)

    app = files["app.js"].decode("utf-8")
    for operation in ("createItem", "updateItem", "deleteItem", "toggleItem"):
        assert f"function {operation}" in app
    assert "localStorage" in app
    assert "serviceWorker.register('./service-worker.js')" in app
    assert "https://" not in app

    page = files["index.html"].decode("utf-8")
    assert '<html lang="en">' in page
    assert 'name="viewport"' in page
    assert 'class="skip-link"' in page
    assert '<label for="title">' in page
    assert 'role="status" aria-live="polite"' in page
    styles = files["styles.css"].decode("utf-8")
    assert "@media (max-width: 760px)" in styles
    assert "prefers-reduced-motion" in styles

    manifest = json.loads(files["manifest.webmanifest"])
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "./"
    assert manifest["scope"] == "./"
    assert {icon["sizes"] for icon in manifest["icons"]} == {"192x192", "512x512"}

    worker = files["service-worker.js"].decode("utf-8")
    assert "cache.addAll(APP_SHELL)" in worker
    assert "url.origin !== self.location.origin" in worker
    server = files["server.py"].decode("utf-8")
    assert 'host: str = "127.0.0.1"' in server
    assert 'self.host != "127.0.0.1"' in server
    assert "requests" not in server
    assert "urllib" not in server


@pytest.mark.parametrize("target", ("web", "desktop", "mobile"))
def test_requested_search_is_materialized_in_browser_targets(target: str) -> None:
    files = render_project(
        "Keep searchable private notes",
        "Searchable Notes",
        target,
        features=("search and filter items",),
    )

    page = files["index.html"].decode("utf-8")
    source = files["app.js"].decode("utf-8")
    assert '<label for="filter">Search items</label>' in page
    assert 'id="filter" type="search"' in page
    assert "function filterItems(items, query)" in source
    assert "filterItems(state.items" in source
    assert "filterInput.addEventListener('input', render)" in source


def test_unrequested_search_is_not_exposed_and_unknown_features_refuse() -> None:
    files = render_project("Keep private notes", "Notes", "web")

    assert 'id="filter"' not in files["index.html"].decode("utf-8")
    with pytest.raises(ValueError, match="unsupported materialization features"):
        render_project(
            "Keep private notes",
            "Notes",
            "web",
            features=("synchronize with a remote calendar",),
        )


@pytest.mark.parametrize(
    ("target", "required_text"),
    (
        ("desktop", "not a native desktop application"),
        ("mobile", "not a native Android or iOS application"),
    ),
)
def test_non_web_browser_targets_are_honestly_labelled_pwa_only(
    target: str, required_text: str
) -> None:
    readme = render_project("Keep notes", "Notes", target)["README.md"].decode("utf-8")

    assert "installable PWA candidate" in readme
    assert required_text in readme
    assert "not been" in readme and "published" in readme


def test_web_candidate_generated_unittests_and_fourfold_compile(tmp_path: Path) -> None:
    files = render_project("Keep a local task board", "Task Board", "web")
    _write_project(tmp_path, files)

    completed = _run_generated_tests(tmp_path)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    compiled = compile_reference_project(
        tmp_path,
        source_revision=REVISION,
        created_at=CREATED_AT,
    )
    assert {plane.plane for plane in compiled.snapshot.planes} == {
        "code",
        "type",
        "data",
        "knowledge",
    }
    assert all(plane.status == "complete" for plane in compiled.snapshot.planes)
    manifest = json.loads(files["fourfold.json"])
    assert set(manifest["code_files"]) == {"app.js", "model.py", "server.py"}
    app_node = next(
        node for node in compiled.forest.nodes if node.id == "code:file:app.js"
    )
    assert app_node.kind == "source_file"
    assert app_node.attributes == {"language": "javascript", "path": "app.js"}
    assert compiled.file_digest_map["app.js"] == hashlib.sha256(
        files["app.js"]
    ).hexdigest()


def test_cli_candidate_is_stdlib_json_crud_and_tests_itself(tmp_path: Path) -> None:
    files = render_project("Maintain a local inventory", "Pocket Inventory", "cli")
    assert set(files) == {
        "README.md",
        "app.py",
        "fourfold.json",
        "schemas/item.schema.json",
        "tests/test_app.py",
    }
    source = files["app.py"].decode("utf-8")
    for operation in ("def add(", "def update(", "def toggle(", "def delete("):
        assert operation in source
    for forbidden in ("requests", "urllib", "socket", "subprocess", "https://"):
        assert forbidden not in source

    _write_project(tmp_path, files)
    completed = _run_generated_tests(tmp_path)
    assert completed.returncode == 0, completed.stdout + completed.stderr

    data_path = tmp_path / "private-items.json"
    added = subprocess.run(
        [
            sys.executable,
            "app.py",
            "--data",
            str(data_path),
            "add",
            "Oscilloscope",
            "--details",
            "Bench one",
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )
    assert added.returncode == 0, added.stdout + added.stderr
    assert json.loads(added.stdout) == {
        "details": "Bench one",
        "done": False,
        "id": 1,
        "title": "Oscilloscope",
    }
    assert data_path.is_file()

    compiled = compile_reference_project(
        tmp_path,
        source_revision=REVISION,
        created_at=CREATED_AT,
    )
    assert all(plane.status == "complete" for plane in compiled.snapshot.planes)


def test_cli_requested_search_filters_titles_and_details(tmp_path: Path) -> None:
    files = render_project(
        "Maintain a searchable local inventory",
        "Searchable Inventory",
        "cli",
        features=("search and filter items",),
    )
    _write_project(tmp_path, files)
    data_path = tmp_path / "inventory.json"

    for title, details in (("Scope", "Bench one"), ("Probe", "Drawer two")):
        added = subprocess.run(
            [
                sys.executable,
                "app.py",
                "--data",
                str(data_path),
                "add",
                title,
                "--details",
                details,
            ],
            cwd=tmp_path,
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
        assert added.returncode == 0, added.stdout + added.stderr

    searched = subprocess.run(
        [
            sys.executable,
            "app.py",
            "--data",
            str(data_path),
            "search",
            "drawer",
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )
    assert searched.returncode == 0, searched.stdout + searched.stderr
    assert [row["title"] for row in json.loads(searched.stdout)] == ["Probe"]


def test_generated_sources_have_no_dependency_or_external_service_manifest() -> None:
    for target in ("web", "cli", "desktop", "mobile"):
        files = render_project("A private local collection", "Local Collection", target)
        assert not {
            "package.json",
            "requirements.txt",
            "pyproject.toml",
            ".env",
            ".env.example",
        }.intersection(files)
        executable = b"\n".join(
            payload
            for path, payload in files.items()
            if path.endswith((".py", ".js")) and not path.startswith("tests/")
        ).decode("utf-8")
        assert "api_key" not in executable.lower()
        assert "google-analytics" not in executable.lower()
        assert "segment.io" not in executable.lower()
        assert "telemetry" not in executable.lower()
        assert "https://" not in executable


@pytest.mark.parametrize("target", ("web", "desktop", "mobile"))
def test_kanban_blueprint_is_deterministic_safe_fixed_column_pwa(target: str) -> None:
    features = (
        "create local cards",
        "delete local cards",
        "edit local cards",
        "move cards between fixed columns",
        "persist data locally",
        "search and filter cards",
    )
    first = render_project(
        "Build a local kanban board with search",
        "Workshop Board",
        target,
        features=features,
        blueprint=KANBAN_BOARD_BLUEPRINT,
    )
    second = render_project(
        "Build a local kanban board with search",
        "Workshop Board",
        target,
        features=tuple(reversed(features)),
        blueprint=KANBAN_BOARD_BLUEPRINT,
    )

    assert first == second
    assert list(first) == sorted(first)
    assert set(first) == {
        "README.md",
        "app.js",
        "fourfold.json",
        "icons/icon-192.svg",
        "icons/icon-512.svg",
        "index.html",
        "manifest.webmanifest",
        "model.py",
        "schemas/card.schema.json",
        "server.py",
        "service-worker.js",
        "styles.css",
        "tests/test_project.py",
    }
    assert all(type(payload) is bytes for payload in first.values())
    assert all(not payload.endswith(b"\r\n") for payload in first.values())
    assert all(
        not PurePosixPath(path).is_absolute()
        and path == PurePosixPath(path).as_posix()
        and all(part not in {"", ".", ".."} for part in PurePosixPath(path).parts)
        for path in first
    )

    app = first["app.js"].decode("utf-8")
    page = first["index.html"].decode("utf-8")
    model = first["model.py"].decode("utf-8")
    schema = json.loads(first["schemas/card.schema.json"])
    assert "const COLUMNS = Object.freeze(['backlog', 'in-progress', 'done']);" in app
    assert schema["properties"]["column"]["enum"] == [
        "backlog",
        "in-progress",
        "done",
    ]
    assert 'COLUMNS: tuple[str, ...] = ("backlog", "in-progress", "done")' in model
    for function in ("createCard", "updateCard", "deleteCard", "moveCard"):
        assert f"function {function}" in app
    assert "button('Move Back'" in app
    assert "button('Move Forward'" in app
    assert page.count('class="kanban-column"') == 3
    assert 'id="filter" type="search"' in page
    assert "dragstart" not in app.casefold()
    assert "draggable" not in app.casefold()
    assert "https://" not in app


def test_kanban_search_is_optional_and_unknown_profile_material_refuses() -> None:
    features = (
        "create local cards",
        "delete local cards",
        "edit local cards",
        "move cards between fixed columns",
        "persist data locally",
    )
    files = render_project(
        "Build a local kanban board",
        "Quiet Board",
        "web",
        features=features,
        blueprint=KANBAN_BOARD_BLUEPRINT,
    )
    assert 'id="filter"' not in files["index.html"].decode("utf-8")

    with pytest.raises(ValueError, match="does not support the CLI"):
        render_project(
            "Build a kanban board CLI",
            "Terminal Board",
            "cli",
            features=features,
            blueprint=KANBAN_BOARD_BLUEPRINT,
        )
    with pytest.raises(ValueError, match="blueprint must be one of"):
        render_project(
            "Build a local board",
            "Unknown Board",
            "web",
            features=features,
            blueprint="kanban-board-v2",
        )
    with pytest.raises(ValueError, match="unsupported kanban materialization features"):
        render_project(
            "Build a kanban board",
            "Custom Board",
            "web",
            features=(*features, "custom swimlanes"),
            blueprint=KANBAN_BOARD_BLUEPRINT,
        )


def test_kanban_generated_tests_and_fourfold_compile(tmp_path: Path) -> None:
    files = render_project(
        "Build a local kanban board with search",
        "Verified Board",
        "web",
        features=(
            "create local cards",
            "delete local cards",
            "edit local cards",
            "move cards between fixed columns",
            "persist data locally",
            "search and filter cards",
        ),
        blueprint=KANBAN_BOARD_BLUEPRINT,
    )
    _write_project(tmp_path, files)

    completed = _run_generated_tests(tmp_path)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    node = shutil.which("node")
    if node is not None:
        javascript = subprocess.run(
            [node, "--check", "app.js"],
            cwd=tmp_path,
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
        assert javascript.returncode == 0, javascript.stdout + javascript.stderr
    compiled = compile_reference_project(
        tmp_path,
        source_revision=REVISION,
        created_at=CREATED_AT,
    )
    assert {plane.plane for plane in compiled.snapshot.planes} == {
        "code",
        "type",
        "data",
        "knowledge",
    }
    assert all(plane.status == "complete" for plane in compiled.snapshot.planes)
    manifest = json.loads(files["fourfold.json"])
    assert manifest["data_files"] == ["schemas/card.schema.json"]
    assert manifest["code_files"] == ["model.py", "server.py", "app.js"]
    assert any(
        claim.get("type_name") == "Card"
        and claim.get("schema_field") == "column"
        for claim in manifest["claims"]
    )
