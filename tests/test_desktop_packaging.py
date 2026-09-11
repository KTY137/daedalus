from __future__ import annotations

import json
import os
import plistlib
import re
import shutil
import stat
import struct
import subprocess
import tarfile
import textwrap
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.daedalus_desktop_sidecar import (
    DESKTOP_PROJECT_COMMENT,
    DESKTOP_PROJECT_SCHEMA,
    prepare_runtime,
)
from tools.build_tauri_sidecar import (
    BUNDLE_FILES_NAME,
    BUNDLE_ID_NAME,
    DESKTOP_PYINSTALLER_EXCLUDES,
    assert_no_accelerator_runtime_payload,
    bundle_files,
    bundle_identity,
)
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
PINNED_TAURI_ACTION = (
    "tauri-apps/tauri-action@1deb371b0cd8bd54025b384f1cd735e725c4060f"
)
from tools.smoke_packaged_resources import _wheel_web_file_closure
PINNED_UPLOAD_ACTION = (
    "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"
)
PINNED_DOWNLOAD_ACTION = (
    "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093"
)
PINNED_WORKFLOW_ACTIONS = {
    "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
    "actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020",
    "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
    "astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9",
    "dtolnay/rust-toolchain@6bed0761d98439e5a578e2877258200ad565ba87",
    PINNED_TAURI_ACTION,
    PINNED_UPLOAD_ACTION,
    PINNED_DOWNLOAD_ACTION,
}


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
    assert config["productName"] == "Daedalus"
    assert config["identifier"] == "dev.daedalus.desktop"
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
    assert 'env!("DAEDALUS_BACKEND_BUNDLE_ID")' in source
    assert "backend-generations" in source
    assert "verify_resource_identity" in source
    assert "copy_plain_file_new" in source
    assert ".create_new(true)" in source
    assert "append_startup_error" in source
    assert "failed to build Daedalus desktop application" not in source

    startup = source.split("fn start_desktop_inner", 1)[1].split(
        "fn start_desktop(", 1
    )[0]
    assert startup.index("wait_until_ready") < startup.index(
        "activate_backend"
    ) < startup.index("WebviewWindowBuilder::new") < startup.index("app.manage")
    setup = source.split("fn start_desktop(", 1)[1].split(
        "fn request_backend_shutdown", 1
    )[0]
    assert "append_startup_error" in setup
    assert "Err(error) =>" in setup
    assert "std::process::exit(1)" in setup
    assert "return Err(error)" not in setup


def test_desktop_backend_readiness_is_child_nonce_bound() -> None:
    web_api = (ROOT / "daedalus" / "interfaces" / "http" / "web_api.py").read_text(encoding="utf-8")
    http_server = (
        ROOT / "daedalus" / "interfaces" / "http" / "server.py"
    ).read_text(encoding="utf-8")
    http_read = (
        ROOT / "daedalus" / "interfaces" / "http" / "read.py"
    ).read_text(encoding="utf-8")
    smoke = (ROOT / "tools" / "smoke_tauri_sidecar.py").read_text(encoding="utf-8")
    sidecar = (ROOT / "scripts" / "daedalus_desktop_sidecar.py").read_text(
        encoding="utf-8"
    )
    # The bind-admission owner defines the env var and enforces the nonce
    # format; ``web_api`` is now only the facade that re-exports it.  Audit
    # both halves, so neither dropping the validation at the owner nor cutting
    # the facade loose onto a literal of its own can pass unnoticed.
    assert 'DESKTOP_STARTUP_NONCE_ENV = "DAEDALUS_DESKTOP_STARTUP_NONCE"' in http_server
    assert 'r"[0-9a-f]{64}"' in http_server
    assert (
        "DESKTOP_STARTUP_NONCE_ENV = http_server.DESKTOP_STARTUP_NONCE_ENV" in web_api
    )
    assert 'path == "/api/desktop-ready"' in http_read
    assert '"nonce": nonce' in http_read
    assert "DAEDALUS_DESKTOP_STARTUP_NONCE" in smoke
    assert "/api/desktop-ready" in smoke
    assert "multiprocessing.freeze_support()" in sidecar


def test_sidecar_builder_is_onedir_and_excludes_runtime_state() -> None:
    source = (ROOT / "tools" / "build_tauri_sidecar.py").read_text(encoding="utf-8")
    assert '"--onedir"' in source
    assert '"--onefile"' not in source
    data_section = source.split("DATA_PATHS = (", 1)[1].split(")\n\n\ndef build", 1)[0]
    for forbidden in ('"runs"', '"inbox"', '"outbox"', '"memory"', '"projects"', '".env"'):
        assert forbidden not in data_section
    assert "bundle_identity(BACKEND_DIR)" in source
    assert 'BUNDLE_ID_NAME = "BUNDLE_ID"' in source
    assert 'BUNDLE_FILES_NAME = "BUNDLE_FILES"' in source
    assert "bundle_files(BACKEND_DIR)" in source
    assert "BUNDLE_FILES_NAME).write_bytes" in source


def test_release_native_host_is_compiled_against_the_bundled_backend_identity() -> None:
    build_rs = (TAURI / "build.rs").read_text(encoding="utf-8")
    assert 'const BUNDLE_ID_PATH: &str = "backend/BUNDLE_ID"' in build_rs
    assert 'const BUNDLE_FILES_PATH: &str = "backend/BUNDLE_FILES"' in build_rs
    assert "cargo:rerun-if-changed={BUNDLE_ID_PATH}" in build_rs
    assert "cargo:rerun-if-changed={BUNDLE_FILES_PATH}" in build_rs
    assert "cargo:rustc-env=DAEDALUS_BACKEND_BUNDLE_ID" in build_rs
    assert 'env::var("PROFILE").as_deref() != Ok("release")' in build_rs
    assert "is required for a release build" in build_rs
    assert "trim_end_matches" in build_rs


def test_desktop_rust_crate_keeps_the_windows_gnu_unit_harness_runnable() -> None:
    cargo = (TAURI / "Cargo.toml").read_text(encoding="utf-8")
    build_rs = (TAURI / "build.rs").read_text(encoding="utf-8")
    library = (TAURI / "src" / "lib.rs").read_text(encoding="utf-8")

    assert 'crate-type = ["rlib"]' in cargo
    assert 'env::var("CARGO_CFG_TARGET_ENV").as_deref() == Ok("gnu")' in build_rs
    assert 'println!("cargo:rustc-link-arg={}", resource.display())' in build_rs
    assert "#[cfg(not(test))]\n    let builder = builder.plugin(tauri_plugin_dialog::init());" in library


def test_sidecar_bundle_identity_is_deterministic_and_binds_paths_and_bytes(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "backend"
    (bundle / "_internal").mkdir(parents=True)
    (bundle / "daedalus-web-api.exe").write_bytes(b"launcher")
    payload = bundle / "_internal" / "payload.bin"
    payload.write_bytes(b"payload")

    first = bundle_identity(bundle)
    assert re.fullmatch(r"[0-9a-f]{64}", first)
    manifest = "".join(f"{relative}\n" for relative, _ in bundle_files(bundle))
    (bundle / BUNDLE_FILES_NAME).write_text(manifest, encoding="utf-8")
    (bundle / BUNDLE_ID_NAME).write_text(first + "\n", encoding="ascii")
    assert bundle_identity(bundle) == first

    payload.write_bytes(b"changed")
    assert bundle_identity(bundle) != first
    payload.write_bytes(b"payload")
    payload.rename(bundle / "_internal" / "renamed.bin")
    assert bundle_identity(bundle) != first


def test_sidecar_bundle_identity_matches_the_cross_language_golden_vector(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "backend"
    bundle.mkdir()
    (bundle / "payload.bin").write_bytes(b"payload")

    assert bundle_identity(bundle) == (
        "fa93401a3e96f55a3931a789d1ded6702c98c28a46f2d082de10a5b5143e2783"
    )


def test_sidecar_bundle_identity_refuses_links(tmp_path: Path) -> None:
    bundle = tmp_path / "backend"
    bundle.mkdir()
    target = bundle / "payload"
    target.write_bytes(b"payload")
    link = bundle / "link"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("this host does not permit test symlinks")

    with pytest.raises(ValueError, match="contains a link"):
        bundle_identity(bundle)


@pytest.mark.skipif(
    os.name == "nt" or not hasattr(os, "mkfifo"),
    reason="FIFO fixture is POSIX-only",
)
def test_sidecar_bundle_identity_refuses_special_entries(tmp_path: Path) -> None:
    bundle = tmp_path / "backend"
    bundle.mkdir()
    os.mkfifo(bundle / "pipe")

    with pytest.raises(ValueError, match="contains a special entry"):
        bundle_identity(bundle)


def test_sidecar_bundle_identity_refuses_packaged_mutable_state(tmp_path: Path) -> None:
    bundle = tmp_path / "backend"
    (bundle / "_internal" / "projects").mkdir(parents=True)

    with pytest.raises(ValueError, match="contains mutable state"):
        bundle_identity(bundle)


@pytest.mark.skipif(os.name != "nt", reason="Windows path aliases are case-insensitive")
def test_sidecar_bundle_identity_refuses_windows_case_alias_of_mutable_state(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "backend"
    (bundle / "_INTERNAL" / "CONFIG").mkdir(parents=True)
    (bundle / "_INTERNAL" / "CONFIG" / "runtime.json").write_text(
        "{}", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="contains mutable state"):
        bundle_identity(bundle)


def test_migrated_desktop_self_project_rebinds_to_the_new_generation(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "backend-generations" / "next" / "_internal"
    project_file = runtime / "projects" / "daedalus.json"
    project_file.parent.mkdir(parents=True)
    project_file.write_text(
        json.dumps(
            {
                "name": "daedalus",
                "repo_root": str(tmp_path / "backend" / "_internal"),
                "center": ["daedalus", "apps/web/src"],
                "custom_operator_field": "preserve",
                "_desktop_comment": DESKTOP_PROJECT_COMMENT,
            }
        ),
        encoding="utf-8",
    )
    other_project = runtime / "projects" / "operator.json"
    other_bytes = b'{"name":"operator","repo_root":"D:/work"}\n'
    other_project.write_bytes(other_bytes)

    assert prepare_runtime(runtime) == runtime.resolve()

    migrated = json.loads(project_file.read_text(encoding="utf-8"))
    assert migrated["repo_root"] == str(runtime.resolve())
    assert migrated["custom_operator_field"] == "preserve"
    assert migrated["_desktop_schema"] == DESKTOP_PROJECT_SCHEMA
    assert other_project.read_bytes() == other_bytes


def test_user_owned_daedalus_project_is_never_rewritten(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    project_file = runtime / "projects" / "daedalus.json"
    project_file.parent.mkdir(parents=True)
    original = b'{"name":"daedalus","repo_root":"D:/operator-owned"}\n'
    project_file.write_bytes(original)

    prepare_runtime(runtime)

    assert project_file.read_bytes() == original


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
    assert workflow.count(PINNED_TAURI_ACTION) == 2
    package = json.loads(
        (ROOT / "apps" / "web" / "package.json").read_text(encoding="utf-8")
    )
    assert package["devDependencies"]["@tauri-apps/cli"] == "2.11.4"
    assert "uploadUpdaterJson: false" in workflow
    assert "uploadUpdaterSignatures: false" in workflow
    assert "--prerelease" in workflow
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'desktop-build = ["pyinstaller==6.22.1"]' in project
    assert (
        'select_desktop_release_assets.py select desktop-artifacts "$VERSION"'
        in workflow
    )
    assert "select_desktop_release_assets.py archive-macos-app" in workflow
    assert "Archive exactly one macOS application bundle" in release_matrix
    assert PINNED_UPLOAD_ACTION in release_matrix
    assert "Daedalus_${VERSION}_aarch64.app.tar.gz" in release_matrix
    assert "Verify macOS arm64 bundle architecture" in release_matrix
    assert "select_desktop_release_assets.py verify-macos-arm64" in release_matrix
    assert '"$RUNNER_ARCH"' in release_matrix
    assert '"${{ matrix.target }}"' in release_matrix
    assert release_matrix.index("Build desktop bundles") < release_matrix.index(
        "Verify macOS arm64 bundle architecture"
    ) < release_matrix.index("Archive exactly one macOS application bundle")


def test_desktop_build_explicitly_excludes_opt_in_gpu_research_runtimes() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    validation, _publisher = workflow.split("\n  release:\n", 1)
    install = "uv sync --locked --extra test --extra desktop-build --no-extra gpu"
    release_install = (
        "uv sync --locked --extra test --extra release-build --no-extra gpu"
    )
    assert validation.count(install) == 2
    assert validation.count(release_install) == 1
    for forbidden in ('".[gpu]"', "--all-extras", "pip install -e"):
        assert forbidden not in validation

    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'desktop-build = ["pyinstaller==6.22.1"]' in project
    assert (
        'release-build = ["build==1.6.0", "setuptools==84.0.0"]' in project
    )
    assert 'requires = ["setuptools==84.0.0"]' in project
    assert "dependencies = []" in project

    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    assert 'name = "pyinstaller"\nversion = "6.22.1"' in lock
    assert 'name = "build"\nversion = "1.6.0"' in lock

    build_source = (ROOT / "tools" / "build_tauri_sidecar.py").read_text(
        encoding="utf-8"
    )
    assert set(DESKTOP_PYINSTALLER_EXCLUDES) == {
        "cuda",
        "cupy",
        "cupy_backends",
        "cupyx",
        "newton",
        "nvidia",
        "torch",
        "triton",
        "warp",
    }
    assert 'cmd.extend(["--exclude-module", module])' in build_source
    assert "assert_no_accelerator_runtime_payload(frozen)" in build_source


def test_desktop_workflow_uses_only_immutable_actions_and_locked_toolchains() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    actions = re.findall(
        r"^\s*(?:-\s+)?uses:\s+([^\s#]+)", workflow, flags=re.MULTILINE
    )

    assert actions
    assert set(actions) == PINNED_WORKFLOW_ACTIONS
    assert all(re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", action) for action in actions)
    assert workflow.count('toolchain: "1.97.1"') == 2
    assert workflow.count('version: "0.11.26"') == 3
    assert workflow.count("npm exec -- tauri icon") == 2
    assert workflow.count("tauriScript: npm exec tauri") == 2
    assert "npm install --global" not in workflow

    package = json.loads(
        (ROOT / "apps" / "web" / "package.json").read_text(encoding="utf-8")
    )
    package_lock = json.loads(
        (ROOT / "apps" / "web" / "package-lock.json").read_text(
            encoding="utf-8"
        )
    )
    assert package["devDependencies"]["@tauri-apps/cli"] == "2.11.4"
    assert package_lock["packages"][""]["devDependencies"]["@tauri-apps/cli"] == (
        "2.11.4"
    )
    locked_cli = package_lock["packages"]["node_modules/@tauri-apps/cli"]
    assert locked_cli["version"] == "2.11.4"
    assert locked_cli["integrity"].startswith("sha512-")


def test_packaged_resource_smoke_enters_the_canonical_effect_boundary() -> None:
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID

    smoke_source = (ROOT / "tools" / "smoke_packaged_resources.py").read_text(
        encoding="utf-8"
    )
    row = REGISTRY_BY_ID["tools.packaged_resources_smoke"]
    assert row.target == "tools.smoke_packaged_resources:main"
    assert row.wiring.value == "central"
    assert 'begin_effect(\n        "tools.packaged_resources_smoke"' in smoke_source
    assert smoke_source.index("begin_effect(") < smoke_source.index("init_result =")


def test_packaged_resource_smoke_rejects_stale_unreachable_vite_chunks(
    tmp_path: Path,
) -> None:
    wheel = tmp_path / "fixture.whl"
    prefix = "daedalus/resources/web_dist/"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            prefix + "index.html",
            '<script src="/assets/index-current123.js"></script>',
        )
        archive.writestr(
            prefix + "assets/index-current123.js",
            'import("./lazy-current456.js")',
        )
        archive.writestr(prefix + "assets/lazy-current456.js", "export default 1")
        archive.writestr(prefix + "assets/index-stale999.js", "export default 2")

    with zipfile.ZipFile(wheel) as archive:
        reachable, orphaned = _wheel_web_file_closure(archive)

    assert reachable == (
        "assets/index-current123.js",
        "assets/lazy-current456.js",
        "index.html",
    )
    assert orphaned == ("assets/index-stale999.js",)


def test_desktop_payload_guard_refuses_accelerator_modules_and_native_libraries(
    tmp_path: Path,
) -> None:
    safe = tmp_path / "safe"
    (safe / "_internal" / "daedalus").mkdir(parents=True)
    (safe / "_internal" / "daedalus" / "accelerators.py").write_text(
        "research recipe only\n", encoding="utf-8"
    )
    assert_no_accelerator_runtime_payload(safe)

    torch = safe / "_internal" / "torch" / "__init__.py"
    torch.parent.mkdir()
    torch.write_text("", encoding="utf-8")
    with pytest.raises(SystemExit, match="opt-in accelerator runtime payloads"):
        assert_no_accelerator_runtime_payload(safe)
    torch.unlink()
    torch.parent.rmdir()

    cudart = safe / "_internal" / "cudart64_12.dll"
    cudart.write_bytes(b"cuda runtime")
    with pytest.raises(SystemExit, match="cudart64_12.dll"):
        assert_no_accelerator_runtime_payload(safe)


@pytest.mark.parametrize(
    "filename",
    (
        "libcudart.so.12",
        "libcublas.so.12",
        "libtorch_cuda.so",
        "libnvJitLink.so.12",
        "libnccl.so.2",
        "libcuda.so.1",
        "libcupti.so.12",
        "libnvshmem_host.so.3",
        "nvblas64_12.dll",
        "nvperf_host.dll",
        "nvtx.cp313-win_amd64.pyd",
        "cutensor.cp313-win_amd64.pyd",
        "c10_cuda.dll",
        "caffe2_nvrtc.dll",
    ),
)
def test_desktop_payload_guard_normalizes_native_library_prefixes(
    tmp_path: Path, filename: str
) -> None:
    internal = tmp_path / "backend" / "_internal"
    internal.mkdir(parents=True)
    (internal / filename).write_bytes(b"accelerator runtime")

    with pytest.raises(SystemExit, match=re.escape(filename)):
        assert_no_accelerator_runtime_payload(tmp_path / "backend")


def test_desktop_payload_guard_checks_root_level_native_extensions(
    tmp_path: Path,
) -> None:
    backend = tmp_path / "backend"
    backend.mkdir()
    filename = "torch_cuda.dll"
    (backend / filename).write_bytes(b"accelerator runtime")

    with pytest.raises(SystemExit, match=re.escape(filename)):
        assert_no_accelerator_runtime_payload(backend)


@pytest.mark.parametrize(
    "module", ("torch", "nvidia", "cuda", "cupy", "newton", "warp", "triton")
)
def test_desktop_payload_guard_checks_every_internal_path_component(
    tmp_path: Path, module: str
) -> None:
    payload = tmp_path / "backend" / "_internal" / "vendor" / module / "data.bin"
    payload.parent.mkdir(parents=True)
    payload.write_bytes(b"accelerator runtime")

    with pytest.raises(SystemExit, match=re.escape(f"vendor/{module}/data.bin")):
        assert_no_accelerator_runtime_payload(tmp_path / "backend")


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


def _write_release_asset_matrix(root: Path, version: str = "0.1.6") -> tuple[Path, ...]:
    assets = tuple(
        root / name
        for name in (
            f"Daedalus_{version}_x64-setup.exe",
            f"Daedalus_{version}_amd64.AppImage",
            f"Daedalus_{version}_amd64.deb",
            f"Daedalus_{version}_aarch64.dmg",
            f"Daedalus_{version}_aarch64.app.tar.gz",
        )
    )
    for path in assets:
        path.write_bytes(b"installer")
    return assets


def test_release_asset_selection_is_exactly_the_version_bound_five_asset_matrix(
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

    assert select_release_assets(tmp_path, "0.1.3") == expected


def test_release_asset_selection_refuses_empty_or_non_regular_assets(
    tmp_path: Path,
) -> None:
    assets = _write_release_asset_matrix(tmp_path)
    assets[1].write_bytes(b"")
    with pytest.raises(ValueError, match="desktop release asset is empty"):
        select_release_assets(tmp_path, "0.1.6")

    assets[1].write_bytes(b"installer")
    assets[2].unlink()
    assets[2].mkdir()
    with pytest.raises(ValueError, match="desktop release asset is not a regular file"):
        select_release_assets(tmp_path, "0.1.6")


def test_release_asset_selection_refuses_a_linked_asset(tmp_path: Path) -> None:
    assets = _write_release_asset_matrix(tmp_path)
    external = tmp_path / "external-installer"
    external.write_bytes(b"external")
    assets[0].unlink()
    try:
        assets[0].symlink_to(external)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"host cannot create test symlink: {exc}")

    with pytest.raises(ValueError, match="symlink or reparse point"):
        select_release_assets(tmp_path, "0.1.6")


def test_release_asset_selection_refuses_a_linked_root(tmp_path: Path) -> None:
    actual_root = tmp_path / "actual"
    actual_root.mkdir()
    _write_release_asset_matrix(actual_root)
    linked_root = tmp_path / "linked"
    try:
        linked_root.symlink_to(actual_root, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"host cannot create test symlink: {exc}")

    with pytest.raises(ValueError, match="symlink or reparse point"):
        select_release_assets(linked_root, "0.1.6")


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
        select_release_assets(tmp_path, "0.1.3")

    (tmp_path / "Daedalus.app.tar.gz").write_bytes(b"installer")
    (tmp_path / "Daedalus.dmg").unlink()
    with pytest.raises(ValueError, match=r"\.dmg: expected 1, found 0"):
        select_release_assets(tmp_path, "0.1.3")

    (tmp_path / "Daedalus.dmg").write_bytes(b"installer")
    duplicate = tmp_path / "Other.exe"
    duplicate.write_bytes(b"duplicate")
    with pytest.raises(ValueError, match=r"\.exe: expected 1, found 2"):
        select_release_assets(tmp_path, "0.1.3")


def test_release_asset_selection_refuses_a_complete_wrong_version_matrix(
    tmp_path: Path,
) -> None:
    for name in (
        "Daedalus_0.1.4_x64-setup.exe",
        "Daedalus_0.1.4_amd64.AppImage",
        "Daedalus_0.1.4_amd64.deb",
        "Daedalus_0.1.4_aarch64.dmg",
        "Daedalus_0.1.4_aarch64.app.tar.gz",
    ):
        (tmp_path / name).write_bytes(b"installer")
    with pytest.raises(ValueError, match="wrong-version assets"):
        select_release_assets(tmp_path, "0.1.6")


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
    # and the independent full-product acceptance job succeed. The release job
    # consumes validated workflow artifacts instead of rerunning
    # branch-controlled build hooks with a write-capable token.
    assert "if: github.event_name == 'push'" in release
    assert "needs:\n      - desktop-release\n      - release-acceptance" in release
    assert "permissions:\n      contents: write" in release
    assert PINNED_DOWNLOAD_ACTION in release
    assert "GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in release
    assert "PYTHONPATH:" not in release
    assert "gh release create" in release

    selection = release.split(
        "      - name: Select validated release assets without release authority\n",
        1,
    )[1].split("      - name: Publish prerelease\n", 1)[0]
    publish = release.split("      - name: Publish prerelease\n", 1)[1]
    assert "GH_TOKEN:" not in selection
    assert "select_desktop_release_assets.py select" in selection
    assert 'echo "asset_list=$asset_list" >> "$GITHUB_OUTPUT"' in selection
    assert "GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in publish
    assert "mapfile -d '' assets < \"$ASSET_LIST\"" in publish
    assert 'SHORT_SHA="${GITHUB_SHA:0:7}"' in publish
    assert 'TAG="desktop-v${VERSION}-g${SHORT_SHA}"' in publish
    assert "set -euo pipefail" in publish
    assert '[[ ! "$GITHUB_SHA" =~ ^[0-9a-fA-F]{40}$ ]]' in publish
    assert 'LATEST_MAIN_SHA="$(gh api "repos/$GITHUB_REPOSITORY/git/ref/heads/main"' in publish
    assert '[[ "$LATEST_MAIN_SHA" != "$GITHUB_SHA" ]]' in publish
    assert publish.index('LATEST_MAIN_SHA="$(gh api') < publish.index(
        'gh api --method POST "repos/$GITHUB_REPOSITORY/git/refs"'
    )
    assert 'gh api --method POST "repos/$GITHUB_REPOSITORY/git/refs"' in publish
    assert '--raw-field "ref=$TAG_REF"' in publish
    assert '--raw-field "sha=$GITHUB_SHA"' in publish
    assert 'BOUND_SHA="$(gh api "repos/$GITHUB_REPOSITORY/git/ref/tags/$TAG"' in publish
    assert '[[ "$BOUND_SHA" != "$GITHUB_SHA" ]]' in publish
    assert publish.index("# immutable-tag-claim:start") < publish.index("gh release create")
    assert "if gh api" not in publish
    assert ">/dev/null 2>&1" not in publish
    assert '--verify-tag' in publish
    assert '--target' not in publish
    assert (
        '--title "Daedalus v${VERSION} — Autonomous Super Assistant Evolver (ASAE)"'
        in publish
    )

    token_steps = [
        step
        for step in re.split(r"\n(?=      - name:)", release)
        if "GH_TOKEN:" in step
    ]
    assert len(token_steps) == 2
    for step in token_steps:
        assert "shell: bash" in step
        assert "gh " in step
        assert "python" not in step.casefold()
        assert "tools/" not in step
        assert "PYTHONPATH:" not in step

    for forbidden in (
        "npm ci",
        "npm run build",
        'pip install -e ".[test]"',
        "build_tauri_sidecar.py",
        "smoke_tauri_sidecar.py",
        "cargo fmt",
        "cargo test",
        "tauri-apps/tauri-action@",
    ):
        assert forbidden not in release

    # PR validation, release-matrix validation, release acceptance and
    # publishing all deliberately avoid persisting Git credentials. The
    # release token is scoped to the one gh release command through GH_TOKEN.
    assert workflow.count("persist-credentials: false") == 4


def _release_test_bash() -> str:
    candidates: list[str] = []
    if os.name == "nt":
        for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if root:
                candidates.append(str(Path(root) / "Git" / "bin" / "bash.exe"))
                candidates.append(str(Path(root) / "Git" / "usr" / "bin" / "bash.exe"))
    discovered = shutil.which("bash")
    if discovered:
        candidates.append(discovered)
    for candidate in candidates:
        if not Path(candidate).is_file():
            continue
        probe = subprocess.run([candidate, "--version"], capture_output=True, text=True, check=False)
        if probe.returncode == 0:
            return candidate
    pytest.skip("A POSIX bash is required for the semantic release-tag test")


@pytest.mark.parametrize(
    ("mode", "succeeds"),
    [
        pytest.param("forbidden", False, id="403"),
        pytest.param("server", False, id="500"),
        pytest.param("existing", False, id="existing-tag"),
        pytest.param("superseded", False, id="superseded-main"),
        pytest.param("race", False, id="post-create-race"),
        pytest.param("success", True, id="success"),
    ],
)
def test_release_tag_claim_is_atomic_exact_and_fail_closed(mode: str, succeeds: bool) -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    claim = workflow.split("# immutable-tag-claim:start\n", 1)[1].split(
        "# immutable-tag-claim:end",
        1,
    )[0]
    claim = textwrap.dedent(claim)
    fake_gh = r'''
gh() {
  if [[ "${1:-}" != "api" ]]; then
    echo "unexpected gh command: $*" >&2
    return 90
  fi
  if [[ "${2:-}" == "--method" ]]; then
    [[ "${3:-}" == "POST" ]] || return 91
    [[ "${4:-}" == "repos/$GITHUB_REPOSITORY/git/refs" ]] || return 92
    [[ "${5:-}" == "--raw-field" && "${6:-}" == "ref=refs/tags/$TAG" ]] || return 93
    [[ "${7:-}" == "--raw-field" && "${8:-}" == "sha=$GITHUB_SHA" ]] || return 94
    case "$FAKE_GH_MODE" in
      forbidden) echo "HTTP 403" >&2; return 22 ;;
      server) echo "HTTP 500" >&2; return 23 ;;
      existing) echo "HTTP 422: Reference already exists" >&2; return 24 ;;
      race|success) return 0 ;;
      *) return 95 ;;
    esac
  fi
  if [[ "${2:-}" == "repos/$GITHUB_REPOSITORY/git/ref/heads/main" ]]; then
    [[ "${3:-}" == "--jq" && "${4:-}" == ".object.sha" ]] || return 96
    if [[ "$FAKE_GH_MODE" == "superseded" ]]; then
      echo "ffffffffffffffffffffffffffffffffffffffff"
    else
      echo "$GITHUB_SHA"
    fi
    return 0
  fi
  [[ "${2:-}" == "repos/$GITHUB_REPOSITORY/git/ref/tags/$TAG" ]] || return 96
  [[ "${3:-}" == "--jq" && "${4:-}" == ".object.sha" ]] || return 97
  case "$FAKE_GH_MODE" in
    race) echo "ffffffffffffffffffffffffffffffffffffffff" ;;
    success) echo "$GITHUB_SHA" ;;
    *) return 98 ;;
  esac
}
'''
    full_sha = "0123456789abcdef0123456789abcdef01234567"
    completed = subprocess.run(
        [_release_test_bash(), "-euo", "pipefail", "-c", fake_gh + "\n" + claim],
        env={
            **os.environ,
            "FAKE_GH_MODE": mode,
            "GITHUB_REPOSITORY": "owner/daedalus",
            "GITHUB_SHA": full_sha,
            "TAG": "desktop-v0.1.6-g0123456",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    if succeeds:
        assert completed.returncode == 0, completed.stderr
    else:
        assert completed.returncode != 0, completed.stdout


def test_release_acceptance_is_a_non_pr_hard_gate_with_retained_receipts() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    _before, remainder = workflow.split("\n  release-acceptance:\n", 1)
    acceptance, publisher = remainder.split("\n  release:\n", 1)

    assert "if: github.event_name != 'pull_request'" in acceptance
    assert "runs-on: ubuntu-24.04" in acceptance
    assert "timeout-minutes: 90" in acceptance
    assert "permissions:\n      contents: read" in acceptance
    assert "python -m pytest -q -n auto --dist loadfile" in acceptance
    assert "--junitxml=release-evidence/python-full.xml" in acceptance

    for surface in (
        "tests/kernel/test_genesis_contracts.py",
        "tests/kernel/test_genesis_effect_lease.py",
        "tests/orchestration/test_genesis_materializer.py",
        "tests/orchestration/test_genesis_service.py",
        "tests/interfaces/test_genesis_cli.py",
        "tests/interfaces/test_http_genesis.py",
        "tests/interfaces/test_http_response_disconnect.py",
        "tests/interfaces/test_desktop_settings_owner.py",
        "tests/interfaces/test_web_distribution.py",
        "tests/twin/test_fourfold_read_projection.py",
        "tests/test_ariadne_campaign_v0.py",
        "tests/test_ikarus_project_grounding.py",
        "tests/test_effect_boundary.py",
        "tests/test_cli_effect_boundary.py",
        "tests/test_kernel_contracts_have_producers.py",
    ):
        assert surface in acceptance

    for command in (
        "npm run test:app",
        "npm run test:motion",
        "npx tsc --noEmit",
        "npm run build",
        "npm audit --omit=dev --json",
        "npx playwright install --with-deps chromium --only-shell",
        "python -m tools.gui_check --json",
        "python -m build --no-isolation --sdist --wheel --outdir release-dist",
        "python -I tools/smoke_packaged_resources.py",
    ):
        assert command in acceptance

    pinned_images = re.findall(
        r"(?:docker\.io/library/python|registry\.access\.redhat\.com/ubi9/python-312)"
        r"@sha256:[0-9a-f]{64}",
        acceptance,
    )
    assert len(pinned_images) == 2
    assert len(set(pinned_images)) == 2
    live_test = (
        "tests/test_linux_oci_containment.py::"
        "test_live_linux_container_writes_workspace_but_not_root_and_has_no_network"
    )
    assert acceptance.count(live_test) == 2
    assert acceptance.count('DAEDALUS_RUN_LINUX_OCI_INTEGRATION: "1"') == 2
    assert '"skipped": 0' in acceptance
    assert 'for slug, family, receipt_name in (' in acceptance
    for receipt in (
        "podman-debian.xml",
        "podman-debian-receipt.json",
        "podman-rhel.xml",
        "podman-rhel-receipt.json",
    ):
        assert receipt in acceptance
    assert "if: always()" in acceptance
    assert PINNED_UPLOAD_ACTION in acceptance
    assert "release-evidence/" in acceptance

    assert "needs:\n      - desktop-release\n      - release-acceptance" in publisher


def test_native_rust_tests_gate_each_desktop_bundle() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    validation, publisher = workflow.split("\n  release:\n", 1)
    pr_linux, release_matrix = validation.split("\n  desktop-release:\n", 1)
    command = (
        "cargo test --manifest-path apps/web/src-tauri/Cargo.toml "
        "--lib --locked"
    )

    assert workflow.count(command) == 2
    for build_job in (pr_linux, release_matrix):
        assert build_job.index("Generate desktop icons") < build_job.index(command)
        assert build_job.index(command) < build_job.index(PINNED_TAURI_ACTION)
    assert command not in publisher


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
    uv_lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    locked_project = uv_lock.split('name = "daedalus"', 1)[1]
    uv_match = re.search(
        r'^version = "([^"]+)"$', locked_project, flags=re.MULTILINE
    )
    assert uv_match
    assert (
        package["version"]
        == package_lock["version"]
        == package_lock["packages"][""]["version"]
        == tauri["version"]
        == match.group(1)
        == locked_match.group(1)
        == project_match.group(1)
        == uv_match.group(1)
    )
    assert re.fullmatch(
        r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)",
        package["version"],
    )


def test_desktop_release_workflow_reads_the_canonical_python_version() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    # Artifact naming and publication must read the same authored version.
    # The mirrored npm/Tauri/Cargo/lock values are independently checked above.
    assert workflow.count("tomllib.load(handle)['project']['version']") == 2
    assert "json.loads(Path('apps/web/src-tauri/tauri.conf.json')" not in workflow
    assert 'NOTES="Daedalus v${VERSION}"' in workflow
    assert "Daedalus v0.1.6" not in workflow
