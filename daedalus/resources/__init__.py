"""Packaged, read-only Daedalus defaults.

The source checkout historically loaded built-ins from repository-root
``agents/``, ``templates/`` and ``catalogue/`` directories.  Those paths do
not exist in an installed wheel.  This module is the single resolver for the
packaged copies while the root files remain a compatibility mirror.

Project-local ``.agentenv`` data is deliberately outside this package.  It is
operator state and may override these defaults only through the owning
subsystem's explicit project-root argument.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Any


class ResourceDriftError(RuntimeError):
    """A legacy checkout mirror disagrees with the packaged source of truth."""


def _resource(relative: str) -> Any:
    path = PurePosixPath(relative)
    parts = path.parts
    if path.is_absolute() or not parts or any(part in {".", ".."} for part in parts):
        raise ValueError("resource path must be package-relative without traversal")
    node = files(__package__)
    for part in parts:
        node = node.joinpath(part)
    return node


def _same_bytes(packaged: Any, legacy: Path) -> bool:
    try:
        return packaged.read_bytes() == legacy.read_bytes()
    except OSError as exc:
        raise ResourceDriftError(
            f"legacy resource mirror cannot be verified: {legacy}"
        ) from exc


def read_builtin_text(
    relative: str,
    *,
    legacy: Path | None = None,
    encoding: str = "utf-8",
) -> str:
    """Read one packaged default and verify an optional checkout mirror.

    The legacy file is a fallback only when the package data is absent.  When
    both exist, disagreement refuses instead of silently choosing a second
    configuration truth.
    """

    packaged = _resource(relative)
    if packaged.is_file():
        if legacy is not None and legacy.is_file() and not _same_bytes(packaged, legacy):
            raise ResourceDriftError(
                f"packaged resource {relative!r} differs from legacy mirror {legacy}"
            )
        return packaged.read_text(encoding=encoding)
    if legacy is not None and legacy.is_file():
        return legacy.read_text(encoding=encoding)
    raise FileNotFoundError(f"built-in resource is unavailable: {relative}")


def iter_builtin_files(
    relative: str,
    *,
    legacy: Path | None = None,
    suffix: str | None = None,
) -> tuple[Any, ...]:
    """Return sorted packaged files, with a verified legacy fallback.

    Extra legacy files are drift too: a caller must place custom roles or
    configuration in the explicit project override rather than smuggling them
    into what should be a reproducible built-in roster.
    """

    packaged_root = _resource(relative)
    packaged = tuple(
        sorted(
            (
                child
                for child in packaged_root.iterdir()
                if child.is_file() and (suffix is None or child.name.endswith(suffix))
            ),
            key=lambda child: child.name,
        )
    ) if packaged_root.is_dir() else ()

    legacy_files: tuple[Path, ...] = ()
    if legacy is not None and legacy.is_dir():
        legacy_files = tuple(
            sorted(
                (
                    child
                    for child in legacy.iterdir()
                    if child.is_file() and (suffix is None or child.name.endswith(suffix))
                ),
                key=lambda child: child.name,
            )
        )

    if packaged:
        if legacy_files:
            packaged_names = tuple(child.name for child in packaged)
            legacy_names = tuple(child.name for child in legacy_files)
            if packaged_names != legacy_names:
                raise ResourceDriftError(
                    f"packaged resource directory {relative!r} differs from legacy mirror {legacy}"
                )
            for packaged_file, legacy_file in zip(packaged, legacy_files):
                if not _same_bytes(packaged_file, legacy_file):
                    raise ResourceDriftError(
                        f"packaged resource {relative}/{packaged_file.name} differs "
                        f"from legacy mirror {legacy_file}"
                    )
        return packaged
    return legacy_files


def schema_text(name: str) -> str:
    """Read a shipped JSON Schema by direct filename, never by filesystem path."""

    if not name or name != Path(name).name or not name.endswith(".schema.json"):
        raise ValueError("schema name must be one direct .schema.json filename")
    return read_builtin_text(f"schemas/{name}")


__all__ = [
    "ResourceDriftError",
    "iter_builtin_files",
    "read_builtin_text",
    "schema_text",
]
