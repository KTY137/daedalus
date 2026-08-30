from __future__ import annotations

import json
import os
import plistlib
import re
import stat
import struct
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.select_desktop_release_assets import (
    _is_link_or_reparse,
    archive_macos_app,
    select_release_assets,
    verify_macos_arm64_bundle,
)

ROOT = Path(__file__).resolve().parents[1]
TAURI = ROOT / "apps" / "web" / "src-tauri"
WORKFLOW = ROOT / ".github" / "workflows" / "tauri-desktop.yml"
ARM64_CPU_TYPE = 0x0100000C
X86_64_CPU_TYPE = 0x01000007
MH_MAGIC_64 = 0xFEEDFACF
MH_EXECUTE = 0x2
MH_DYLIB = 0x6
LC_UUID = 0x1B


def _macho_bytes(
    cpu_type: int = ARM64_CPU_TYPE,
    *,
    file_type: int = MH_EXECUTE,
    magic: int = MH_MAGIC_64,
) -> bytes:
    command = struct.pack("<II16s", LC_UUID, 24, b"\x00" * 16)
    return struct.pack(
        "<IiiIIIII",
        magic,
        cpu_type,
        0,
        file_type,
        1,
        len(command),
        0,
        0,
    ) + command


def _write_macho(
    path: Path,
    cpu_type: int = ARM64_CPU_TYPE,
    *,
    file_type: int = MH_EXECUTE,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_macho_bytes(cpu_type, file_type=file_type))


def _arm64_bundle_fixture(tmp_path: Path) -> tuple[Path, Path, tuple[Path, ...]]:
    app_root = tmp_path / "macos"
    app = app_root / "Daedalus.app"
    app_binary = app / "Contents" / "MacOS" / "daedalus-desktop"
    metadata = app / "Contents" / "Info.plist"
    metadata.parent.mkdir(parents=True, exist_ok=True)
    metadata.write_bytes(
        plistlib.dumps({"CFBundleExecutable": app_binary.name}, fmt=plistlib.FMT_BINARY)
    )
    source_backend = tmp_path / "backend"
    source_sidecar = source_backend / "daedalus-web-api"
    bundled_backend = app / "Contents" / "Resources" / "backend"
    bundled_sidecar = bundled_backend / "daedalus-web-api"
    for binary in (app_binary, source_sidecar, bundled_sidecar):
        _write_macho(binary)
    for marker in (source_backend / "BUILD_TARGET", bundled_backend / "BUILD_TARGET"):
        marker.write_text("aarch64-apple-darwin\n", encoding="utf-8")
    return app_root, source_backend, (app_binary, source_sidecar, bundled_sidecar)


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
    lifecycle_source = source.split("fn readiness_poll_with", 1)[1].split(
        "fn readiness_poll(", 1
    )[0]
    assert lifecycle_source.count("child_status()?") == 2
    concrete_poll = source.split("fn readiness_poll(", 1)[1].split(
        "fn wait_until_ready", 1
    )[0]
    assert "child.try_wait()?" in concrete_poll
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
    assert "Verify macOS arm64 bundle architecture" in release_matrix
    assert "select_desktop_release_assets.py verify-macos-arm64" in release_matrix
    assert '"$RUNNER_ARCH"' in release_matrix
    assert '"${{ matrix.target }}"' in release_matrix
    assert release_matrix.index("Build desktop bundles") < release_matrix.index(
        "Verify macOS arm64 bundle architecture"
    ) < release_matrix.index("Archive exactly one macOS application bundle")


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
    archive = tmp_path / "Daedalus_0.1.3_aarch64.app.tar.gz"

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


def test_macos_arm64_bundle_verification_binds_runner_target_app_and_sidecar(
    tmp_path: Path,
) -> None:
    app_root, source_backend, binaries = _arm64_bundle_fixture(tmp_path)

    assert verify_macos_arm64_bundle(
        app_root,
        source_backend,
        runner_arch="ARM64",
        rust_target="aarch64-apple-darwin",
        host_system="Darwin",
        host_machine="arm64",
    ) == binaries


@pytest.mark.parametrize(
    ("runner_arch", "host_system", "host_machine", "rust_target", "message"),
    (
        ("X64", "Darwin", "arm64", "aarch64-apple-darwin", "runner architecture"),
        ("ARM64", "Linux", "arm64", "aarch64-apple-darwin", "requires Darwin"),
        ("ARM64", "Darwin", "x86_64", "aarch64-apple-darwin", "runner machine"),
        ("ARM64", "Darwin", "arm64", "x86_64-apple-darwin", "Rust target"),
    ),
)
def test_macos_arm64_bundle_verification_refuses_wrong_execution_context(
    tmp_path: Path,
    runner_arch: str,
    host_system: str,
    host_machine: str,
    rust_target: str,
    message: str,
) -> None:
    app_root, source_backend, _ = _arm64_bundle_fixture(tmp_path)

    with pytest.raises(ValueError, match=message):
        verify_macos_arm64_bundle(
            app_root,
            source_backend,
            runner_arch=runner_arch,
            rust_target=rust_target,
            host_system=host_system,
            host_machine=host_machine,
        )


@pytest.mark.parametrize(
    ("binary_index", "label"),
    (
        (0, "Tauri app binary"),
        (1, "PyInstaller source sidecar"),
        (2, "bundled PyInstaller sidecar"),
    ),
)
def test_macos_arm64_bundle_verification_refuses_any_non_arm64_binary(
    tmp_path: Path, binary_index: int, label: str
) -> None:
    app_root, source_backend, binaries = _arm64_bundle_fixture(tmp_path)
    _write_macho(binaries[binary_index], X86_64_CPU_TYPE)

    with pytest.raises(ValueError, match=label):
        verify_macos_arm64_bundle(
            app_root,
            source_backend,
            runner_arch="ARM64",
            rust_target="aarch64-apple-darwin",
            host_system="Darwin",
            host_machine="arm64",
        )


def test_macos_arm64_bundle_verification_refuses_fat_binary_and_target_drift(
    tmp_path: Path,
) -> None:
    app_root, source_backend, binaries = _arm64_bundle_fixture(tmp_path)
    binaries[0].write_bytes(b"\xca\xfe\xba\xbe" + b"\x00" * 12)
    with pytest.raises(ValueError, match="thin arm64 Mach-O"):
        verify_macos_arm64_bundle(
            app_root,
            source_backend,
            runner_arch="ARM64",
            rust_target="aarch64-apple-darwin",
            host_system="Darwin",
            host_machine="arm64",
        )

    _write_macho(binaries[0])
    (source_backend / "BUILD_TARGET").write_text(
        "x86_64-apple-darwin\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="source sidecar BUILD_TARGET"):
        verify_macos_arm64_bundle(
            app_root,
            source_backend,
            runner_arch="ARM64",
            rust_target="aarch64-apple-darwin",
            host_system="Darwin",
            host_machine="arm64",
        )


def test_macos_arm64_bundle_verification_recognizes_windows_reparse_metadata() -> None:
    metadata = SimpleNamespace(
        st_mode=stat.S_IFDIR,
        st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT,
    )
    assert _is_link_or_reparse(metadata)


@pytest.mark.parametrize(
    "linked_component",
    (
        "app_root",
        "app",
        "contents",
        "macos",
        "app_binary",
        "resources",
        "bundled_backend",
        "bundled_sidecar",
        "source_root",
        "source_sidecar",
    ),
)
def test_macos_arm64_bundle_verification_refuses_symlink_ancestors(
    tmp_path: Path, linked_component: str
) -> None:
    app_root, source_backend, binaries = _arm64_bundle_fixture(tmp_path)
    app = app_root / "Daedalus.app"
    components = {
        "app_root": (app_root, True),
        "app": (app, True),
        "contents": (app / "Contents", True),
        "macos": (app / "Contents" / "MacOS", True),
        "app_binary": (binaries[0], False),
        "resources": (app / "Contents" / "Resources", True),
        "bundled_backend": (app / "Contents" / "Resources" / "backend", True),
        "bundled_sidecar": (binaries[2], False),
        "source_root": (source_backend, True),
        "source_sidecar": (binaries[1], False),
    }
    linked, is_directory = components[linked_component]
    external = tmp_path / f"external-{linked_component}"
    linked.rename(external)
    try:
        linked.symlink_to(external, target_is_directory=is_directory)
    except OSError as exc:
        pytest.skip(f"host cannot create test symlink: {exc}")

    with pytest.raises(ValueError, match="symlink or reparse point"):
        verify_macos_arm64_bundle(
            app_root,
            source_backend,
            runner_arch="ARM64",
            rust_target="aarch64-apple-darwin",
            host_system="Darwin",
            host_machine="arm64",
        )
    assert all(path.exists() for path in binaries)


def test_macos_arm64_bundle_verification_refuses_truncated_macho_header(
    tmp_path: Path,
) -> None:
    app_root, source_backend, binaries = _arm64_bundle_fixture(tmp_path)
    binaries[0].write_bytes(b"\xcf\xfa\xed\xfe" + ARM64_CPU_TYPE.to_bytes(4, "little"))

    with pytest.raises(ValueError, match="truncated 64-bit Mach-O header"):
        verify_macos_arm64_bundle(
            app_root,
            source_backend,
            runner_arch="ARM64",
            rust_target="aarch64-apple-darwin",
            host_system="Darwin",
            host_machine="arm64",
        )


def test_macos_arm64_bundle_verification_refuses_non_executable_macho(
    tmp_path: Path,
) -> None:
    app_root, source_backend, binaries = _arm64_bundle_fixture(tmp_path)
    _write_macho(binaries[0], file_type=MH_DYLIB)

    with pytest.raises(ValueError, match="MH_EXECUTE"):
        verify_macos_arm64_bundle(
            app_root,
            source_backend,
            runner_arch="ARM64",
            rust_target="aarch64-apple-darwin",
            host_system="Darwin",
            host_machine="arm64",
        )


def test_macos_arm64_bundle_verification_refuses_swapped_macho_header(
    tmp_path: Path,
) -> None:
    app_root, source_backend, binaries = _arm64_bundle_fixture(tmp_path)
    command = struct.pack(">II16s", LC_UUID, 24, b"\x00" * 16)
    binaries[0].write_bytes(
        struct.pack(
            ">IiiIIIII",
            MH_MAGIC_64,
            ARM64_CPU_TYPE,
            0,
            MH_EXECUTE,
            1,
            len(command),
            0,
            0,
        )
        + command
    )

    with pytest.raises(ValueError, match="little-endian"):
        verify_macos_arm64_bundle(
            app_root,
            source_backend,
            runner_arch="ARM64",
            rust_target="aarch64-apple-darwin",
            host_system="Darwin",
            host_machine="arm64",
        )


@pytest.mark.parametrize(
    "magic",
    (
        b"\xca\xfe\xba\xbe",
        b"\xbe\xba\xfe\xca",
        b"\xca\xfe\xba\xbf",
        b"\xbf\xba\xfe\xca",
    ),
)
def test_macos_arm64_bundle_verification_refuses_every_fat_macho_magic(
    tmp_path: Path, magic: bytes
) -> None:
    app_root, source_backend, binaries = _arm64_bundle_fixture(tmp_path)
    binaries[0].write_bytes(magic + b"\x00" * 28)

    with pytest.raises(ValueError, match="thin arm64 Mach-O"):
        verify_macos_arm64_bundle(
            app_root,
            source_backend,
            runner_arch="ARM64",
            rust_target="aarch64-apple-darwin",
            host_system="Darwin",
            host_machine="arm64",
        )


@pytest.mark.parametrize("boundary_case", ("past_eof", "unfilled", "zero_commands"))
def test_macos_arm64_bundle_verification_refuses_invalid_load_command_boundary(
    tmp_path: Path, boundary_case: str
) -> None:
    app_root, source_backend, binaries = _arm64_bundle_fixture(tmp_path)
    command = struct.pack("<II16s", LC_UUID, 24, b"\x00" * 16)
    if boundary_case == "past_eof":
        command_count, command_size, payload = 1, len(command) + 8, command
        message = "extend past end of file"
    elif boundary_case == "unfilled":
        command_count, command_size, payload = (
            1,
            len(command) + 8,
            command + b"\x00" * 8,
        )
        message = "do not fill the declared boundary"
    else:
        command_count, command_size, payload = 0, 0, b""
        message = "load-command count/size"
    header = struct.pack(
        "<IiiIIIII",
        MH_MAGIC_64,
        ARM64_CPU_TYPE,
        0,
        MH_EXECUTE,
        command_count,
        command_size,
        0,
        0,
    )
    binaries[0].write_bytes(header + payload)

    with pytest.raises(ValueError, match=message):
        verify_macos_arm64_bundle(
            app_root,
            source_backend,
            runner_arch="ARM64",
            rust_target="aarch64-apple-darwin",
            host_system="Darwin",
            host_machine="arm64",
        )


def test_macos_app_archive_refuses_missing_duplicate_or_existing_output(
    tmp_path: Path,
) -> None:
    app_root = tmp_path / "macos"
    app_root.mkdir()
    archive = tmp_path / "Daedalus_0.1.3_aarch64.app.tar.gz"
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
        tmp_path / "Daedalus_0.1.3_x64-setup.exe",
        tmp_path / "Daedalus_0.1.3_amd64.AppImage",
        tmp_path / "Daedalus_0.1.3_amd64.deb",
        tmp_path / "Daedalus_0.1.3_aarch64.dmg",
        tmp_path / "Daedalus_0.1.3_aarch64.app.tar.gz",
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
    assert "PYTHONPATH: ${{ github.workspace }}" in release
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
        == "0.1.3"
    )
