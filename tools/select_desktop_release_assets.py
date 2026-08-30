"""Build and select the five distributable desktop release assets.

The Tauri macOS ``app`` artifact is a directory.  It must be archived before
the workflow-artifact upload so executable modes and symlinks are retained.
Release publication then admits exactly one asset of each expected type and
never recursively uploads an application bundle's internal files.
"""
from __future__ import annotations

import os
import platform
import plistlib
import stat
import struct
import sys
import tarfile
from collections import Counter
from pathlib import Path

REQUIRED_SUFFIXES = (".exe", ".AppImage", ".deb", ".dmg", ".app.tar.gz")
MACOS_ARM64_TARGET = "aarch64-apple-darwin"
_ARM64_CPU_TYPE = 0x0100000C
_MACHO_64_HEADER = struct.Struct("<IiiIIIII")
_MACHO_64_MAGIC = 0xFEEDFACF
_MACHO_64_MAGIC_BYTES = b"\xcf\xfa\xed\xfe"
_MACHO_EXECUTE = 0x2
_MACHO_LOAD_COMMAND_HEADER = struct.Struct("<II")
_FAT_MACHO_MAGICS = {
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf",
    b"\xbf\xba\xfe\xca",
}


def _asset_suffix(path: Path) -> str | None:
    return next(
        (suffix for suffix in REQUIRED_SUFFIXES if path.name.endswith(suffix)),
        None,
    )


def _is_link_or_reparse(metadata: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    file_attributes = getattr(metadata, "st_file_attributes", 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(file_attributes & reparse_flag)


def _lstat_no_link(path: Path, label: str) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ValueError(f"cannot inspect {label}: {path}: {exc}") from exc
    if _is_link_or_reparse(metadata):
        raise ValueError(f"{label} must not be a symlink or reparse point: {path}")
    return metadata


def _require_directory_no_link(path: Path, label: str) -> Path:
    metadata = _lstat_no_link(path, label)
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"{label} is not one directory: {path}")
    return path


def _require_regular_file_beneath(root: Path, relative: Path, label: str) -> Path:
    """Return one regular file after refusing links in its authorized path."""

    _require_directory_no_link(root, f"{label} root")
    if relative.is_absolute() or not relative.parts or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise ValueError(f"invalid relative path for {label}: {relative}")

    current = root
    for index, part in enumerate(relative.parts):
        current = current / part
        metadata = _lstat_no_link(current, label)
        if index < len(relative.parts) - 1:
            if not stat.S_ISDIR(metadata.st_mode):
                raise ValueError(f"{label} ancestor is not one directory: {current}")
        elif not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"{label} is not one regular file: {current}")
    return current


def _top_level_macos_app(app_root: Path) -> Path:
    _require_directory_no_link(app_root, "macOS app directory")
    apps = tuple(
        path
        for path in sorted(app_root.iterdir(), key=lambda candidate: candidate.name)
        if path.name.endswith(".app")
    )
    if len(apps) != 1:
        raise ValueError(f"top-level .app: expected 1 directory, found {len(apps)}")
    return _require_directory_no_link(apps[0], "top-level macOS application")


def _require_arm64_macho(root: Path, relative: Path, label: str) -> Path:
    path = _require_regular_file_beneath(root, relative, label)
    try:
        with path.open("rb") as handle:
            header = handle.read(_MACHO_64_HEADER.size)
            file_size = os.fstat(handle.fileno()).st_size
            magic = header[:4]
            if magic in _FAT_MACHO_MAGICS:
                raise ValueError(
                    f"{label} must be a thin arm64 Mach-O, not a fat binary: {path}"
                )
            if len(header) != _MACHO_64_HEADER.size:
                raise ValueError(
                    f"{label} has a truncated 64-bit Mach-O header: {path}"
                )

            if magic != _MACHO_64_MAGIC_BYTES:
                raise ValueError(
                    f"{label} is not a little-endian 64-bit thin Mach-O executable: "
                    f"{path}"
                )

            (
                parsed_magic,
                cpu_type,
                _cpu_subtype,
                file_type,
                load_command_count,
                load_command_size,
                _flags,
                _reserved,
            ) = _MACHO_64_HEADER.unpack(header)
            if parsed_magic != _MACHO_64_MAGIC:
                raise ValueError(f"{label} has an invalid Mach-O magic: {path}")
            if cpu_type != _ARM64_CPU_TYPE:
                raise ValueError(
                    f"{label} CPU type is 0x{cpu_type:08x}, expected arm64 "
                    f"0x{_ARM64_CPU_TYPE:08x}: {path}"
                )
            if file_type != _MACHO_EXECUTE:
                raise ValueError(
                    f"{label} Mach-O file type is 0x{file_type:08x}, expected "
                    f"MH_EXECUTE 0x{_MACHO_EXECUTE:08x}: {path}"
                )
            minimum_commands_size = load_command_count * _MACHO_LOAD_COMMAND_HEADER.size
            if load_command_count == 0 or load_command_size < minimum_commands_size:
                raise ValueError(
                    f"{label} has an invalid Mach-O load-command count/size: {path}"
                )
            commands_end = _MACHO_64_HEADER.size + load_command_size
            if commands_end > file_size:
                raise ValueError(
                    f"{label} Mach-O load commands extend past end of file: {path}"
                )

            remaining = load_command_size
            for command_index in range(load_command_count):
                command_header = handle.read(_MACHO_LOAD_COMMAND_HEADER.size)
                if len(command_header) != _MACHO_LOAD_COMMAND_HEADER.size:
                    raise ValueError(
                        f"{label} has a truncated Mach-O load command "
                        f"{command_index}: {path}"
                    )
                _command, command_size = _MACHO_LOAD_COMMAND_HEADER.unpack(
                    command_header
                )
                if (
                    command_size < _MACHO_LOAD_COMMAND_HEADER.size
                    or command_size % 8 != 0
                    or command_size > remaining
                ):
                    raise ValueError(
                        f"{label} has an invalid Mach-O load command "
                        f"{command_index} size {command_size}: {path}"
                    )
                handle.seek(command_size - _MACHO_LOAD_COMMAND_HEADER.size, os.SEEK_CUR)
                remaining -= command_size
            if remaining != 0:
                raise ValueError(
                    f"{label} Mach-O load commands do not fill the declared boundary: "
                    f"{path}"
                )
    except OSError as exc:
        raise ValueError(f"cannot read {label}: {path}: {exc}") from exc
    return path


def _require_build_target(
    root: Path, relative: Path, target: str, label: str
) -> Path:
    path = _require_regular_file_beneath(root, relative, label)
    try:
        recorded = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"cannot read {label}: {path}: {exc}") from exc
    if recorded != target + "\n":
        expected = target + "\n"
        raise ValueError(
            f"{label} records {recorded!r}, expected exactly {expected!r}: {path}"
        )
    return path


def _macos_app_executable(app: Path) -> Path:
    plist_path = _require_regular_file_beneath(
        app,
        Path("Contents") / "Info.plist",
        "macOS application metadata",
    )
    try:
        metadata = plistlib.loads(plist_path.read_bytes())
    except (OSError, plistlib.InvalidFileException, ValueError) as exc:
        raise ValueError(
            f"cannot read macOS application metadata: {plist_path}: {exc}"
        ) from exc
    if not isinstance(metadata, dict):
        raise ValueError(
            f"macOS application metadata is not a dictionary: {plist_path}"
        )
    executable = metadata.get("CFBundleExecutable")
    if (
        not isinstance(executable, str)
        or not executable
        or executable in {".", ".."}
        or "/" in executable
        or "\\" in executable
        or "\x00" in executable
        or Path(executable).name != executable
    ):
        raise ValueError(
            f"invalid CFBundleExecutable in macOS application metadata: {executable!r}"
        )
    return Path("Contents") / "MacOS" / executable


def verify_macos_arm64_bundle(
    app_root: Path,
    sidecar_root: Path,
    *,
    runner_arch: str,
    rust_target: str,
    host_system: str | None = None,
    host_machine: str | None = None,
) -> tuple[Path, Path, Path]:
    """Prove the native macOS runner, app and frozen sidecar are all arm64."""

    actual_system = platform.system() if host_system is None else host_system
    actual_machine = platform.machine() if host_machine is None else host_machine
    if actual_system.casefold() != "darwin":
        raise ValueError(
            "macOS arm64 release verification requires Darwin, "
            f"got {actual_system!r}"
        )
    if runner_arch.casefold() not in {"arm64", "aarch64"}:
        raise ValueError(
            f"GitHub runner architecture must be ARM64, got {runner_arch!r}"
        )
    if actual_machine.casefold() not in {"arm64", "aarch64"}:
        raise ValueError(f"native runner machine must be arm64, got {actual_machine!r}")
    if rust_target != MACOS_ARM64_TARGET:
        raise ValueError(
            f"Rust target must be {MACOS_ARM64_TARGET}, got {rust_target!r}"
        )

    app = _top_level_macos_app(app_root)
    app_binary_relative = _macos_app_executable(app)
    bundled_backend_relative = Path("Contents") / "Resources" / "backend"

    _require_build_target(
        sidecar_root,
        Path("BUILD_TARGET"),
        rust_target,
        "source sidecar BUILD_TARGET",
    )
    _require_build_target(
        app,
        bundled_backend_relative / "BUILD_TARGET",
        rust_target,
        "bundled sidecar BUILD_TARGET",
    )
    app_binary = _require_arm64_macho(
        app, app_binary_relative, "Tauri app binary"
    )
    source_sidecar = _require_arm64_macho(
        sidecar_root, Path("daedalus-web-api"), "PyInstaller source sidecar"
    )
    bundled_sidecar = _require_arm64_macho(
        app,
        bundled_backend_relative / "daedalus-web-api",
        "bundled PyInstaller sidecar",
    )
    return app_binary, source_sidecar, bundled_sidecar


def archive_macos_app(app_root: Path, archive_path: Path) -> Path:
    """Archive exactly one top-level ``.app`` bundle without overwriting."""

    app = _top_level_macos_app(app_root)
    if not archive_path.name.endswith(".app.tar.gz"):
        raise ValueError("macOS archive must end with .app.tar.gz")
    if not archive_path.parent.is_dir():
        raise ValueError(
            f"macOS archive parent directory does not exist: {archive_path.parent}"
        )
    if archive_path.exists():
        raise ValueError(f"macOS archive already exists: {archive_path}")

    temporary = archive_path.with_name(f".{archive_path.name}.tmp")
    if temporary.exists():
        raise ValueError(f"macOS archive temporary path already exists: {temporary}")
    try:
        with tarfile.open(temporary, mode="x:gz") as archive:
            archive.add(app, arcname=app.name, recursive=True)
        temporary.replace(archive_path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return archive_path


def select_release_assets(root: Path) -> tuple[Path, ...]:
    """Return one top-level asset per suffix, or refuse the artifact set."""

    if not root.is_dir():
        raise ValueError(f"desktop artifact directory does not exist: {root}")
    assets = tuple(
        path
        for path in sorted(root.iterdir(), key=lambda candidate: candidate.name)
        if path.is_file() and _asset_suffix(path) is not None
    )
    counts = Counter(_asset_suffix(path) for path in assets)
    problems = [
        f"{suffix}: expected 1, found {counts.get(suffix, 0)}"
        for suffix in REQUIRED_SUFFIXES
        if counts.get(suffix, 0) != 1
    ]
    names = Counter(path.name for path in assets)
    duplicates = sorted(name for name, count in names.items() if count > 1)
    if duplicates:
        problems.append("duplicate release-asset names: " + ", ".join(duplicates))
    if problems:
        raise ValueError(
            "invalid validated desktop artifact set (" + "; ".join(problems) + ")"
        )
    return tuple(
        next(path for path in assets if _asset_suffix(path) == suffix)
        for suffix in REQUIRED_SUFFIXES
    )


def main(argv: list[str] | None = None) -> int:
    from daedalus.budget import process_guard_boundary_decision
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "tools.desktop_release_assets",
        REGISTRY_BY_ID["tools.desktop_release_assets"].effects,
        (process_guard_boundary_decision(),),
    )
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in {
        "archive-macos-app",
        "select",
        "verify-macos-arm64",
    }:
        print(
            "usage: select_desktop_release_assets.py "
            "{archive-macos-app APP_DIR OUTPUT|select ARTIFACT_DIR|"
            "verify-macos-arm64 APP_DIR SIDECAR_DIR RUNNER_ARCH RUST_TARGET}",
            file=sys.stderr,
        )
        return 2
    try:
        if args[0] == "archive-macos-app" and len(args) == 3:
            archive_macos_app(Path(args[1]), Path(args[2]))
            return 0
        if args[0] == "verify-macos-arm64" and len(args) == 5:
            verified = verify_macos_arm64_bundle(
                Path(args[1]),
                Path(args[2]),
                runner_arch=args[3],
                rust_target=args[4],
            )
            print("verified macOS arm64 bundle: " + ", ".join(map(str, verified)))
            return 0
        if args[0] == "select" and len(args) == 2:
            assets = select_release_assets(Path(args[1]))
        else:
            raise ValueError("invalid command arguments")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    for path in assets:
        sys.stdout.buffer.write(str(path).encode(sys.getfilesystemencoding()) + b"\0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
