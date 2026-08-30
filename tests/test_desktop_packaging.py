from __future__ import annotations

import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
TAURI = ROOT / "apps" / "web" / "src-tauri"


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


def test_release_workflow_builds_three_desktop_platforms_without_updater() -> None:
    workflow = (ROOT / ".github" / "workflows" / "tauri-desktop.yml").read_text(
        encoding="utf-8"
    )
    for runner in ("windows-latest", "ubuntu-22.04", "macos-latest"):
        assert runner in workflow
    assert "tauri-apps/tauri-action@v1" in workflow
    assert "@tauri-apps/cli@2.11.4" in workflow
    assert "uploadUpdaterJson: false" in workflow
    assert "uploadUpdaterSignatures: false" in workflow
    assert "prerelease: true" in workflow
    assert "pyinstaller==6.22.1" in workflow


def test_desktop_release_versions_are_aligned() -> None:
    package = json.loads((ROOT / "apps" / "web" / "package.json").read_text(encoding="utf-8"))
    tauri = json.loads((TAURI / "tauri.conf.json").read_text(encoding="utf-8"))
    cargo = (TAURI / "Cargo.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', cargo, flags=re.MULTILINE)
    assert match
    assert package["version"] == tauri["version"] == match.group(1)
