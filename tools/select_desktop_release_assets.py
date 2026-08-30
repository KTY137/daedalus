"""Build and select the five distributable desktop release assets.

The Tauri macOS ``app`` artifact is a directory.  It must be archived before
the workflow-artifact upload so executable modes and symlinks are retained.
Release publication then admits exactly one asset of each expected type and
never recursively uploads an application bundle's internal files.
"""
from __future__ import annotations

import sys
import tarfile
from collections import Counter
from pathlib import Path


REQUIRED_SUFFIXES = (".exe", ".AppImage", ".deb", ".dmg", ".app.tar.gz")


def _asset_suffix(path: Path) -> str | None:
    return next(
        (suffix for suffix in REQUIRED_SUFFIXES if path.name.endswith(suffix)),
        None,
    )


def archive_macos_app(app_root: Path, archive_path: Path) -> Path:
    """Archive exactly one top-level ``.app`` bundle without overwriting."""

    if not app_root.is_dir():
        raise ValueError(f"macOS app directory does not exist: {app_root}")
    apps = tuple(
        path
        for path in sorted(app_root.iterdir(), key=lambda candidate: candidate.name)
        if path.is_dir() and not path.is_symlink() and path.name.endswith(".app")
    )
    if len(apps) != 1:
        raise ValueError(
            f"top-level .app: expected 1 directory, found {len(apps)}"
        )
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
            archive.add(apps[0], arcname=apps[0].name, recursive=True)
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
    if not args or args[0] not in {"archive-macos-app", "select"}:
        print(
            "usage: select_desktop_release_assets.py "
            "{archive-macos-app APP_DIR OUTPUT|select ARTIFACT_DIR}",
            file=sys.stderr,
        )
        return 2
    try:
        if args[0] == "archive-macos-app" and len(args) == 3:
            archive_macos_app(Path(args[1]), Path(args[2]))
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
