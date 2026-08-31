"""Build the Daedalus Python backend as a Tauri resource.

PyInstaller is intentionally used in *onedir* mode. Tauri owns the outer
installer while the Python runtime stays a single-process child whose lifecycle
the Rust shell can terminate reliably. ``onefile`` would introduce a bootloader
parent/child topology and an extraction directory that is unsuitable for
persistent Daedalus state.

Run after ``npm run build`` so the frozen backend contains the exact cockpit
assets that will ship.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
TAURI_DIR = ROOT / "apps" / "web" / "src-tauri"
BACKEND_DIR = TAURI_DIR / "backend"
BUILD_DIR = ROOT / "build" / "desktop-sidecar"
BUNDLE_ID_NAME = "BUNDLE_ID"
BUNDLE_FILES_NAME = "BUNDLE_FILES"
BUNDLED_MUTABLE_STATE_PATHS = (
    "_internal/config",
    "_internal/inbox",
    "_internal/memory",
    "_internal/outbox",
    "_internal/projects",
    "_internal/runs",
    "_internal/.env",
)


def _bundle_path_component_equal(left: str, right: str) -> bool:
    """Match path components with the semantics of the build host."""

    return os.path.normcase(left) == os.path.normcase(right)


def _bundle_path_is_or_is_under(relative: str, parent: str) -> bool:
    relative_parts = relative.split("/")
    parent_parts = parent.split("/")
    return len(relative_parts) >= len(parent_parts) and all(
        _bundle_path_component_equal(left, right)
        for left, right in zip(relative_parts, parent_parts)
    )


def _is_bundle_metadata_path(relative: str) -> bool:
    return "/" not in relative and any(
        _bundle_path_component_equal(relative, name)
        for name in (BUNDLE_ID_NAME, BUNDLE_FILES_NAME)
    )

# Static, non-secret project material needed by the self-project and UI. Runtime
# state (runs/inbox/outbox/memory/projects/.env) is deliberately NOT bundled.
DATA_PATHS = (
    ("daedalus", "daedalus"),
    ("apps/web/dist", "apps/web/dist"),
    ("apps/web/src", "apps/web/src"),
    ("agents", "agents"),
    ("catalogue", "catalogue"),
    ("configs", "configs"),
    ("docs", "docs"),
    ("funnels", "funnels"),
    ("templates", "templates"),
    (".agentenv", ".agentenv"),
    (".daedalusignore", "."),
    ("README.md", "."),
    ("pyproject.toml", "."),
)


def bundle_files(root: Path) -> list[tuple[str, Path]]:
    """Return the validated immutable files in a backend tree.

    Bundle metadata is excluded. Links and mutable state are refused because a
    packaged backend must be a closed artifact, not a reference to builder-host
    or runtime state.
    """

    root_metadata = root.lstat()
    root_attributes = getattr(root_metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)
    if (
        stat.S_ISLNK(root_metadata.st_mode)
        or root_attributes & reparse_flag
        or not stat.S_ISDIR(root_metadata.st_mode)
    ):
        raise ValueError(f"desktop backend bundle root is not a plain directory: {root}")

    files: list[tuple[str, Path]] = []

    def collect(directory: Path) -> None:
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                relative = path.relative_to(root).as_posix()
                if "\r" in relative or "\n" in relative:
                    raise ValueError(
                        f"desktop backend bundle path cannot be represented in its manifest: {path}"
                    )
                if any(
                    _bundle_path_is_or_is_under(relative, state)
                    for state in BUNDLED_MUTABLE_STATE_PATHS
                ):
                    raise ValueError(
                        f"desktop backend bundle contains mutable state: {relative}"
                    )
                metadata = entry.stat(follow_symlinks=False)
                attributes = getattr(metadata, "st_file_attributes", 0)
                if entry.is_symlink() or attributes & reparse_flag:
                    raise ValueError(f"desktop backend bundle contains a link: {path}")
                if stat.S_ISDIR(metadata.st_mode):
                    collect(path)
                elif stat.S_ISREG(metadata.st_mode):
                    if not _is_bundle_metadata_path(relative):
                        files.append((relative, path))
                else:
                    raise ValueError(
                        f"desktop backend bundle contains a special entry: {path}"
                    )

    collect(root)
    files.sort(key=lambda item: item[0])
    return files


def bundle_identity(root: Path) -> str:
    """Return a deterministic identity for one complete backend tree.

    Paths and bytes are both framed into the digest, so renaming a file cannot
    collide with changing another file's contents. Bundle metadata is excluded,
    which makes writing and then re-checking it stable.
    """

    digest = hashlib.sha256(b"daedalus-backend-bundle-v1\0")
    for relative, path in bundle_files(root):
        encoded_path = relative.encode("utf-8")
        size = path.stat().st_size
        digest.update(len(encoded_path).to_bytes(8, "big"))
        digest.update(encoded_path)
        digest.update(size.to_bytes(8, "big"))
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    return digest.hexdigest()


def build(target: str) -> Path:
    dist_index = ROOT / "apps" / "web" / "dist" / "index.html"
    if not dist_index.is_file():
        raise SystemExit(
            "apps/web/dist/index.html is missing; run `npm run build` in apps/web first"
        )

    missing = [src for src, _ in DATA_PATHS if not (ROOT / src).exists()]
    if missing:
        raise SystemExit(f"desktop sidecar data inputs are missing: {', '.join(missing)}")

    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    if BACKEND_DIR.exists():
        shutil.rmtree(BACKEND_DIR)
    BUILD_DIR.mkdir(parents=True)
    BACKEND_DIR.mkdir(parents=True)

    dist_path = BUILD_DIR / "dist"
    work_path = BUILD_DIR / "work"
    spec_path = BUILD_DIR / "spec"

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--noupx",
        "--name",
        "daedalus-web-api",
        "--distpath",
        str(dist_path),
        "--workpath",
        str(work_path),
        "--specpath",
        str(spec_path),
        "--paths",
        str(ROOT),
        "--collect-submodules",
        "daedalus",
    ]
    for source, destination in DATA_PATHS:
        cmd.extend(["--add-data", f"{ROOT / source}:{destination}"])
    cmd.append(str(ROOT / "scripts" / "daedalus_desktop_sidecar.py"))

    subprocess.run(cmd, cwd=ROOT, check=True)

    frozen = dist_path / "daedalus-web-api"
    executable = frozen / (
        "daedalus-web-api.exe" if sys.platform == "win32" else "daedalus-web-api"
    )
    internal = frozen / "_internal"
    if not executable.is_file() or not internal.is_dir():
        raise SystemExit(f"unexpected PyInstaller onedir layout under {frozen}")

    shutil.copytree(frozen, BACKEND_DIR, dirs_exist_ok=True)
    (BACKEND_DIR / "BUILD_TARGET").write_text(target + "\n", encoding="utf-8")
    manifest = "".join(f"{relative}\n" for relative, _ in bundle_files(BACKEND_DIR))
    (BACKEND_DIR / BUNDLE_FILES_NAME).write_bytes(manifest.encode("utf-8"))
    identity = bundle_identity(BACKEND_DIR)
    (BACKEND_DIR / BUNDLE_ID_NAME).write_bytes((identity + "\n").encode("ascii"))
    return BACKEND_DIR


def main(argv: list[str] | None = None) -> None:
    from daedalus.budget import process_guard_boundary_decision
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "tools.desktop_sidecar_build",
        REGISTRY_BY_ID["tools.desktop_sidecar_build"].effects,
        (process_guard_boundary_decision(),),
    )
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--target",
        required=True,
        help="Rust target triple recorded with the native PyInstaller build",
    )
    args = parser.parse_args(argv)
    out = build(args.target)
    print(out)


if __name__ == "__main__":
    main()
