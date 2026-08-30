# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
TAURI = ROOT / "apps" / "web" / "src-tauri"
WORKFLOW = ROOT / ".github" / "workflows" / "tauri-desktop.yml"


def test_tauri_desktop_has_no_parallel_frontend_or_updater() -> None:
    config = json.loads((TAURI / "tauri.conf.json").read_text(encoding="utf-8"))
    assert config["app"]["windows"] == []
    assert config["build"]["frontendDist"] == "http://127.0.0.1:8765"
    assert config["bundle"]["createUpdaterArtifacts"] is False
    assert config["bundle"]["resources"] == {"backend/": "backend/"}


def test_desktop_rust_shell_uses_loopback_and_owns_child_lifecycle() -> None:
    source = (TAURI / "src" / "lib.rs").read_text(encoding="utf-8")
    assert 'const BACKEND_ADDR: &str = "127.0.0.1:8765"' in source
    assert 'const BACKEND_URL: &str = "http://127.0.0.1:8765"' in source
    assert "port_is_busy()" in source
    assert "child.kill()" in source
    assert "WebviewWindowBuilder::new" in source


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
    tauri = json.loads((TAURI / "tauri.conf.json").read_text(encoding="utf-8"))
    cargo = (TAURI / "Cargo.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', cargo, flags=re.MULTILINE)
    assert match
    assert package["version"] == tauri["version"] == match.group(1)
