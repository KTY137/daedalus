from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tarfile

import pytest

from tools.select_desktop_release_assets import (
    archive_macos_app,
    select_release_assets,
)


ROOT = Path(__file__).resolve().parents[1]
TAURI = ROOT / "apps" / "web" / "src-tauri"
WORKFLOW = ROOT / ".github" / "workflows" / "tauri-desktop.yml"


def test_tauri_desktop_has_no_parallel_frontend_or_updater() -> None:
    config = json.loads((TAURI / "tauri.conf.json").read_text(encoding="utf-8"))
    assert config["app"]["windows"] == []
    assert config["build"]["frontendDist"] == "http://127.0.0.1:8765"
    assert config["bundle"]["createUpdaterArtifacts"] is False
    assert config["bundle"]["resources"] == {"backend/": "backend/"}


def test_native_folder_picker_has_one_narrow_remote_capability() -> None:
    config = json.loads((TAURI / "tauri.conf.json").read_text(encoding="utf-8"))
    assert config["app"]["security"]["capabilities"] == ["project-folder-dialog"]

    capability = json.loads(
        (TAURI / "capabilities" / "project-folder-dialog.json").read_text(
            encoding="utf-8"
        )
    )
    assert capability["windows"] == ["main"]
    assert capability["local"] is False
    assert capability["remote"] == {"urls": ["http://127.0.0.1:8765/*"]}
    assert capability["platforms"] == ["windows", "macOS"]
    assert capability["permissions"] == ["dialog:allow-open"]


def test_desktop_rust_shell_uses_loopback_and_owns_child_lifecycle() -> None:
    source = (TAURI / "src" / "lib.rs").read_text(encoding="utf-8")
    assert 'const BACKEND_ADDR: &str = "127.0.0.1:8765"' in source
    assert 'const BACKEND_URL: &str = "http://127.0.0.1:8765"' in source
    assert "port_is_busy()" in source
    assert "getrandom::getrandom" in source
    assert '.env(DESKTOP_STARTUP_NONCE_ENV, startup_nonce)' in source
    assert "probe_authenticated_readiness" in source
    assert source.count("child.try_wait()?") >= 2
    wait_source = source.split("fn wait_until_ready", 1)[1].split("fn start_desktop", 1)[0]
    assert "TcpStream::connect_timeout" not in wait_source
    assert "child.kill()" in source
    assert "WebviewWindowBuilder::new" in source


def test_desktop_backend_readiness_is_child_nonce_bound() -> None:
    web_api = (ROOT / "daedalus" / "web_api.py").read_text(encoding="utf-8")
    smoke = (ROOT / "tools" / "smoke_tauri_sidecar.py").read_text(encoding="utf-8")
    assert 'DESKTOP_STARTUP_NONCE_ENV = "DAEDALUS_DESKTOP_STARTUP_NONCE"' in web_api
    assert 'path == "/api/desktop-ready"' in web_api
    assert 'r"[0-9a-f]{64}"' in web_api
    assert '"nonce": nonce' in web_api
    assert "DAEDALUS_DESKTOP_STARTUP_NONCE" in smoke
    assert "/api/desktop-ready" in smoke


def test_sidecar_builder_is_onedir_and_excludes_runtime_state() -> None:
    source = (ROOT / "tools" / "build_tauri_sidecar.py").read_text(encoding="utf-8")
    assert '"--onedir"' in source
    assert '"--onefile"' not in source
    data_section = source.split("DATA_PATHS = (", 1)[1].split(")\n\n\ndef build", 1)[0]
    for forbidden in ('"runs"', '"inbox"', '"outbox"', '"memory"', '"projects"', '".env"'):
        assert forbidden not in data_section


def test_pull_requests_use_one_linux_desktop_job_only() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    pr_job, remainder = workflow.split("\n  desktop-release:\n", 1)
    release_matrix, _release = remainder.split("\n  release:\n", 1)

    assert "pr-linux:" in pr_job
    assert "if: github.event_name == 'pull_request'" in pr_job
    assert "runs-on: ubuntu-22.04" in pr_job
    assert "windows-latest" not in pr_job
    assert "macos-latest" not in pr_job
    assert "Build Linux validation desktop bundle" in pr_job
    assert "daedalus-desktop-pr-linux-[arch]-[bundle]" in pr_job

    assert "if: github.event_name != 'pull_request'" in release_matrix
    for runner in ("windows-latest", "ubuntu-22.04", "macos-latest"):
        assert runner in release_matrix


def test_release_workflow_builds_three_desktop_platforms_without_updater() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    _pr_job, remainder = workflow.split("\n  desktop-release:\n", 1)
    release_matrix, _release = remainder.split("\n  release:\n", 1)

    for runner in ("windows-latest", "ubuntu-22.04", "macos-latest"):
        assert runner in release_matrix
    assert "tauri-apps/tauri-action@v1" in workflow
    assert "@tauri-apps/cli@2.11.4" in workflow
    assert "uploadUpdaterJson: false" in workflow
    assert "uploadUpdaterSignatures: false" in workflow
    assert "--prerelease" in workflow
    assert "pyinstaller==6.22.1" in workflow
    assert "select_desktop_release_assets.py select desktop-artifacts" in workflow
    assert "select_desktop_release_assets.py archive-macos-app" in workflow
    assert "Archive exactly one macOS application bundle" in release_matrix
    assert "actions/upload-artifact@v4" in release_matrix
    assert "Daedalus_${VERSION}_aarch64.app.tar.gz" in release_matrix


def test_desktop_shipping_paths_and_project_tests_are_in_both_ci_lanes() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert workflow.count('- "packaging/**"') == 2
    for test_path in (
        "tests/test_desktop_packaging.py",
        "tests/test_desktop_runtime.py",
        "tests/test_desktop_startup_nonce.py",
        "tests/test_project_registration.py",
    ):
        # Once in each event path filter and once in each build lane command.
        assert workflow.count(test_path) == 4


def test_macos_app_archive_contains_one_top_level_bundle_and_keeps_modes(
    tmp_path: Path,
) -> None:
    app_root = tmp_path / "macos"
    executable = app_root / "Daedalus.app" / "Contents" / "MacOS" / "Daedalus"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"native executable")
    executable.chmod(0o755)
    source_mode = executable.stat().st_mode & 0o777
    archive = tmp_path / "Daedalus_0.1.2_aarch64.app.tar.gz"

    assert archive_macos_app(app_root, archive) == archive

    with tarfile.open(archive, mode="r:gz") as bundle:
        members = bundle.getmembers()
    assert members
    assert {member.name.split("/", 1)[0] for member in members} == {
        "Daedalus.app"
    }
    archived_executable = next(
        member
        for member in members
        if member.name == "Daedalus.app/Contents/MacOS/Daedalus"
    )
    assert archived_executable.mode == source_mode
    if os.name != "nt":
        assert archived_executable.mode & 0o111


def test_macos_app_archive_refuses_missing_duplicate_or_existing_output(
    tmp_path: Path,
) -> None:
    app_root = tmp_path / "macos"
    app_root.mkdir()
    archive = tmp_path / "Daedalus_0.1.2_aarch64.app.tar.gz"
    with pytest.raises(
        ValueError, match="top-level \\.app: expected 1 directory, found 0"
    ):
        archive_macos_app(app_root, archive)

    (app_root / "Daedalus.app").mkdir()
    (app_root / "Other.app").mkdir()
    with pytest.raises(
        ValueError, match="top-level \\.app: expected 1 directory, found 2"
    ):
        archive_macos_app(app_root, archive)

    (app_root / "Other.app").rmdir()
    archive.write_bytes(b"do not overwrite")
    with pytest.raises(ValueError, match="archive already exists"):
        archive_macos_app(app_root, archive)
    assert archive.read_bytes() == b"do not overwrite"


def test_release_asset_selection_is_exactly_the_v010_five_asset_matrix(
    tmp_path: Path,
) -> None:
    expected = (
        tmp_path / "Daedalus_0.1.2_x64-setup.exe",
        tmp_path / "Daedalus_0.1.2_amd64.AppImage",
        tmp_path / "Daedalus_0.1.2_amd64.deb",
        tmp_path / "Daedalus_0.1.2_aarch64.dmg",
        tmp_path / "Daedalus_0.1.2_aarch64.app.tar.gz",
    )
    for path in expected:
        path.write_bytes(b"installer")
    app_internal = (
        tmp_path / "Daedalus.app" / "Contents" / "Resources" / "embedded.AppImage"
    )
    app_internal.parent.mkdir(parents=True)
    app_internal.write_bytes(b"not a release asset")

    assert select_release_assets(tmp_path) == expected


def test_release_asset_selection_refuses_missing_or_duplicate_installers(
    tmp_path: Path,
) -> None:
    for name in (
        "Daedalus.exe",
        "Daedalus.AppImage",
        "Daedalus.deb",
        "Daedalus.dmg",
    ):
        (tmp_path / name).write_bytes(b"installer")
    with pytest.raises(ValueError, match=r"\.app\.tar\.gz: expected 1, found 0"):
        select_release_assets(tmp_path)

    (tmp_path / "Daedalus.app.tar.gz").write_bytes(b"installer")
    (tmp_path / "Daedalus.dmg").unlink()
    with pytest.raises(ValueError, match=r"\.dmg: expected 1, found 0"):
        select_release_assets(tmp_path)

    (tmp_path / "Daedalus.dmg").write_bytes(b"installer")
    duplicate = tmp_path / "Other.exe"
    duplicate.write_bytes(b"duplicate")
    with pytest.raises(ValueError, match=r"\.exe: expected 1, found 2"):
        select_release_assets(tmp_path)


def test_pull_request_validation_cannot_receive_release_write_authority() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    validation, release = workflow.split("\n  release:\n", 1)

    # Both PR validation and the pre-publish platform matrix are read-only.
    # Branch-controlled build/install/test code must never inherit a
    # contents-write token or a persisted checkout credential.
    assert "pull_request:" in validation
    assert "permissions:\n  contents: read" in validation
    assert "permissions:\n      contents: read" in validation
    assert "contents: write" not in validation
    assert "GITHUB_TOKEN:" not in validation
    assert "persist-credentials: false" in validation

    # Release authority exists only after the trusted-main platform matrix
    # succeeds. The release job consumes validated workflow artifacts instead
    # of rerunning branch-controlled build hooks with a write-capable token.
    assert "if: github.event_name == 'push'" in release
    assert "needs: desktop-release" in release
    assert "permissions:\n      contents: write" in release
    assert "actions/download-artifact@v4" in release
    assert "GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in release
    assert "gh release create" in release
    for forbidden in (
        "npm ci",
        "npm run build",
        'pip install -e ".[test]"',
        "build_tauri_sidecar.py",
        "smoke_tauri_sidecar.py",
        "cargo fmt",
        "tauri-action@v1",
    ):
        assert forbidden not in release

    # PR validation, release-matrix validation and publishing all deliberately
    # avoid persisting Git credentials. The release token is scoped to the one
    # gh release command through GH_TOKEN instead.
    assert workflow.count("persist-credentials: false") == 3


def test_desktop_release_versions_are_aligned() -> None:
    package = json.loads((ROOT / "apps" / "web" / "package.json").read_text(encoding="utf-8"))
    package_lock = json.loads(
        (ROOT / "apps" / "web" / "package-lock.json").read_text(encoding="utf-8")
    )
    tauri = json.loads((TAURI / "tauri.conf.json").read_text(encoding="utf-8"))
    cargo = (TAURI / "Cargo.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', cargo, flags=re.MULTILINE)
    assert match
    cargo_lock = (TAURI / "Cargo.lock").read_text(encoding="utf-8")
    locked_package = cargo_lock.split('name = "daedalus-desktop"', 1)[1]
    locked_match = re.search(
        r'^version = "([^"]+)"$', locked_package, flags=re.MULTILINE
    )
    assert locked_match
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project_section = project.split("[project]", 1)[1].split("\n[", 1)[0]
    project_match = re.search(
        r'^version = "([^"]+)"$', project_section, flags=re.MULTILINE
    )
    assert project_match
    assert (
        package["version"]
        == package_lock["version"]
        == package_lock["packages"][""]["version"]
        == tauri["version"]
        == match.group(1)
        == locked_match.group(1)
        == project_match.group(1)
        == "0.1.2"
    )
