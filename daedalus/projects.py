from __future__ import annotations

import hashlib
import json
import ntpath
import os
import posixpath
import re
import unicodedata
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable

from .atomic import (
    ExclusiveFileLock,
    FileLockUnavailable,
    publish_bytes_once,
    write_text_atomic,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT_DIR = ROOT / "projects"
PROJECT_REGISTRY_LOCK_TIMEOUT_S = 5.0

_SAFE_NAME_RE = re.compile(r"[^a-z0-9_-]+")
_WINDOWS_RESERVED_NAMES = {
    "con", "prn", "aux", "nul",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


class ProjectRegistrationError(ValueError):
    """The caller supplied a project registration that cannot be accepted."""


class ProjectRegistryUnavailable(RuntimeError):
    """The project registry cannot safely serialize a write right now."""


class ProjectRowUpdateError(ValueError):
    """A requested project-row update is not a valid row operation."""


class ProjectRowNotFound(ProjectRowUpdateError):
    """The requested direct project-registry row does not exist."""


def _canonical_repo_root(repo_root: object) -> Path:
    if not isinstance(repo_root, (str, os.PathLike)) or isinstance(repo_root, bytes):
        raise ProjectRegistrationError("repo_root must be a directory path")
    path_text = os.fspath(repo_root)
    if not isinstance(path_text, str):
        raise ProjectRegistrationError("repo_root must be a directory path")
    raw = path_text.strip()
    if not raw:
        raise ProjectRegistrationError("repo_root is required")
    try:
        resolved = Path(raw).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ProjectRegistrationError(f"repo_root does not exist: {raw}") from exc
    if not resolved.is_dir():
        raise ProjectRegistrationError(f"repo_root is not a directory: {raw}")
    return resolved


def _path_key(path: Path) -> str:
    """Comparable canonical path text, including Windows case semantics."""
    return os.path.normcase(str(path.resolve(strict=False)))


def _safe_project_name(value: object, *, fallback: str, path_key: str) -> str:
    if value is not None and not isinstance(value, str):
        raise ProjectRegistrationError("name must be a string")
    source = value if isinstance(value, str) else fallback
    raw = unicodedata.normalize("NFKC", source).strip()
    if value is not None and (
        not raw or raw in {".", ".."} or "/" in raw or "\\" in raw
    ):
        raise ProjectRegistrationError("name must not be empty or contain path traversal")
    slug = _SAFE_NAME_RE.sub("-", raw.lower()).strip("-_")
    if not slug:
        if value is not None:
            raise ProjectRegistrationError("name must contain a letter or number")
        slug = f"project-{hashlib.sha256(path_key.encode('utf-8')).hexdigest()[:10]}"
    if slug in _WINDOWS_RESERVED_NAMES:
        slug = f"project-{slug}"
    return slug[:64].rstrip("-_")


def _registered_root_key(data: object) -> str | None:
    """Return a CWD-independent identity for an absolute registered root.

    Native paths resolve symlinks using the host's path semantics. Absolute
    paths from the other supported path family remain valid stale rows and get
    a stable lexical key; a Linux host must not reinterpret ``C:\\repo`` under
    its current directory, nor may Windows do that to ``/srv/repo``.
    Relative legacy values cannot name one canonical root and fail closed.
    """
    if not isinstance(data, dict):
        return None
    raw = data.get("repo_root")
    if not isinstance(raw, str) or not raw.strip():
        return None
    # A NUL cannot occur in a valid native path.  PurePath accepts it as
    # lexical text, though, so reject it before the foreign-platform fallback
    # can accidentally turn an unusable value into a registry identity.
    if "\x00" in raw:
        return None
    try:
        native = Path(raw)
        if native.is_absolute():
            return _path_key(native)
    except (OSError, RuntimeError, ValueError):
        return None
    windows = PureWindowsPath(raw)
    if windows.is_absolute():
        return "foreign-windows:" + ntpath.normcase(ntpath.normpath(str(windows)))
    posix = PurePosixPath(raw)
    if posix.is_absolute():
        return "foreign-posix:" + posixpath.normpath(str(posix))
    return None


def _registry_lock_path() -> Path:
    """Fixed lock identity beside the registry, derived at call time for tests."""
    return PROJECT_DIR / ".registry.lock"


def _register_project_locked(root: Path, root_key: str,
                             project_name: str,
                             explicit_name: bool) -> dict[str, Any]:
    """Re-scan, decide, and publish while the registry lock is held."""
    root_matches: list[Path] = []
    for config_path in sorted(PROJECT_DIR.glob("*.json")):
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProjectRegistryUnavailable(
                f"project registry row '{config_path.name}' cannot be verified"
            ) from exc
        existing_root_key = _registered_root_key(data)
        if existing_root_key is None:
            raise ProjectRegistryUnavailable(
                f"project registry row '{config_path.name}' has no valid repo_root"
            )
        if existing_root_key == root_key:
            root_matches.append(config_path)

    if len(root_matches) > 1:
        names = ", ".join(path.stem for path in root_matches)
        raise ProjectRegistryUnavailable(
            f"project registry has ambiguous canonical-root identity: {names}"
        )
    if root_matches:
        return {
            "name": root_matches[0].stem,
            "repo_root": str(root),
            "created": False,
        }

    target = PROJECT_DIR / f"{project_name}.json"
    if target.exists() and not explicit_name:
        digest = hashlib.sha256(root_key.encode("utf-8")).hexdigest()[:10]
        project_name = f"{project_name[:53].rstrip('-_')}-{digest}"
        target = PROJECT_DIR / f"{project_name}.json"

    payload = {"name": project_name, "repo_root": str(root)}
    encoded = (
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    if not publish_bytes_once(target, encoded):
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProjectRegistryUnavailable(
                f"project registry row '{target.name}' cannot be verified"
            ) from exc
        existing_root_key = _registered_root_key(existing)
        if existing_root_key is None:
            raise ProjectRegistryUnavailable(
                f"project registry row '{target.name}' has no valid repo_root"
            )
        if existing_root_key != root_key:
            raise ProjectRegistrationError(
                f"project name '{project_name}' is already registered")
        return {"name": project_name, "repo_root": str(root), "created": False}

    return {"name": project_name, "repo_root": str(root), "created": True}


def register_project(repo_root: object, name: object = None) -> dict[str, Any]:
    """Register an existing directory in ``projects/`` without adding policy.

    The canonical path is the identity: registering it again returns the
    existing name and performs no registry-row write. New configurations
    contain only the display/storage name and canonical repository root.
    Publication is an exclusive atomic create, so a concurrent name collision
    cannot overwrite another project's configuration. One OS-held registry
    lock makes the cross-filename canonical-root identity check and publication
    a transaction.
    """
    root = _canonical_repo_root(repo_root)
    root_key = _path_key(root)
    project_name = _safe_project_name(name, fallback=root.name, path_key=root_key)
    try:
        with ExclusiveFileLock(
            _registry_lock_path(),
            timeout_s=PROJECT_REGISTRY_LOCK_TIMEOUT_S,
            label="project registry lock",
        ):
            return _register_project_locked(
                root, root_key, project_name, explicit_name=name is not None
            )
    except FileLockUnavailable as exc:
        raise ProjectRegistryUnavailable(
            f"project registry is temporarily unavailable: {exc}"
        ) from exc


def _project_row_name(project: object) -> str:
    """Validate one exact registry stem without turning aliases into paths."""
    if not isinstance(project, str):
        raise ProjectRowUpdateError("project must be a string")
    if (
        not project
        or not project.strip()
        or project in {".", ".."}
        or "/" in project
        or "\\" in project
        or "\x00" in project
    ):
        raise ProjectRowUpdateError(
            "project must name one direct existing registry row"
        )
    return project


def _load_project_row_for_rewrite_locked(
    project: str,
) -> tuple[Path, dict[str, Any]]:
    """Resolve and verify an existing row while the registry lock is held."""
    try:
        matches = [
            path
            for path in sorted(PROJECT_DIR.glob("*.json"))
            if path.stem == project
        ]
    except OSError as exc:
        raise ProjectRegistryUnavailable(
            "project registry rows cannot be enumerated"
        ) from exc

    if not matches:
        raise ProjectRowNotFound(f"unknown project '{project}'")
    if len(matches) != 1:
        raise ProjectRegistryUnavailable(
            f"project registry row '{project}' is ambiguous"
        )

    target = matches[0]
    try:
        if target.is_symlink():
            raise ProjectRegistryUnavailable(
                f"project registry row '{target.name}' is not a direct file"
            )
        data = json.loads(target.read_text(encoding="utf-8"))
    except ProjectRegistryUnavailable:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectRegistryUnavailable(
            f"project registry row '{target.name}' cannot be verified"
        ) from exc

    if not isinstance(data, dict) or _registered_root_key(data) is None:
        raise ProjectRegistryUnavailable(
            f"project registry row '{target.name}' has no valid repo_root"
        )
    return target, data


def rewrite_project_team(
    project: object,
    mutate: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    """Atomically mutate only ``team`` in one existing project row.

    The fixed registry lock is shared with :func:`register_project`, making
    target resolution, read, mutation, and atomic replacement one bounded
    transaction.  The callback receives only the nested team object, so the
    registry identity and unrelated root fields are outside its write scope.
    Lock-free readers see the complete old row or the complete new row.
    """
    project_name = _project_row_name(project)
    if not callable(mutate):
        raise ProjectRowUpdateError("project team mutator must be callable")

    try:
        with ExclusiveFileLock(
            _registry_lock_path(),
            timeout_s=PROJECT_REGISTRY_LOCK_TIMEOUT_S,
            label="project registry lock",
        ):
            target, data = _load_project_row_for_rewrite_locked(project_name)
            if "team" not in data:
                team = {}
                data["team"] = team
            else:
                team = data["team"]
            if not isinstance(team, dict):
                raise ProjectRegistryUnavailable(
                    f"project registry row '{target.name}' has invalid team data"
                )

            mutate(team)
            try:
                encoded = json.dumps(data, indent=2) + "\n"
            except (TypeError, ValueError) as exc:
                raise ProjectRowUpdateError(
                    "project team update is not JSON serializable"
                ) from exc
            try:
                write_text_atomic(target, encoded, encoding="utf-8")
            except OSError as exc:
                raise ProjectRegistryUnavailable(
                    f"project registry row '{target.name}' could not be replaced"
                ) from exc
            return data
    except FileLockUnavailable as exc:
        raise ProjectRegistryUnavailable(
            f"project registry is temporarily unavailable: {exc}"
        ) from exc


def list_projects() -> list[str]:
    return [p.stem for p in sorted(PROJECT_DIR.glob("*.json"))]


def load_project(name: str) -> dict[str, Any]:
    project_name = _project_row_name(name)
    path = PROJECT_DIR / f"{project_name}.json"
    if not path.exists():
        known = ", ".join(list_projects()) or "none"
        raise ProjectRowNotFound(
            f"unknown project '{project_name}'. Known projects: {known}"
        )
    if path.is_symlink():
        raise ProjectRegistryUnavailable(
            f"project registry row '{path.name}' is not a direct file"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if "repo_root" not in data:
        raise ValueError(f"project '{project_name}' is missing repo_root")
    data.setdefault("name", project_name)
    return data


def resolve_registered_project_root(project: object) -> str:
    """Resolve one exact registry row to an available native directory.

    This is the authorization seam for callers which are about to expose a
    checkout to an effectful local service.  Request text names a registry
    row, never a filesystem path.  Foreign-platform and stale rows remain
    valid inventory, but cannot be reinterpreted as relative host paths.

    The first enumeration avoids creating registry lock state for
    unknown/invalid input.  The row read under the canonical registry lock
    binds the returned root to one complete row as observed by cooperating
    writers.
    """
    project_name = _project_row_name(project)
    try:
        known_projects = list_projects()
    except OSError as exc:
        raise ProjectRegistryUnavailable(
            "project registry rows cannot be enumerated"
        ) from exc
    if project_name not in known_projects:
        known = ", ".join(known_projects) or "none"
        raise ProjectRowNotFound(
            f"unknown project '{project_name}'. Known projects: {known}"
        )
    try:
        with ExclusiveFileLock(
            _registry_lock_path(),
            timeout_s=PROJECT_REGISTRY_LOCK_TIMEOUT_S,
            label="project registry lock",
        ):
            _, data = _load_project_row_for_rewrite_locked(project_name)
            raw_root = data.get("repo_root")
            if not isinstance(raw_root, str):
                raise ProjectRegistryUnavailable(
                    f"project registry row '{project_name}.json' has no valid repo_root"
                )
            native_path = Path(raw_root)
            if not native_path.is_absolute():
                raise ProjectRegistrationError(
                    f"registered project '{project_name}' is unavailable: "
                    "registered repo_root is not absolute on this host"
                )
            try:
                root = _canonical_repo_root(raw_root)
            except ProjectRegistrationError as exc:
                raise ProjectRegistrationError(
                    f"registered project '{project_name}' is unavailable: {exc}"
                ) from exc

            if _registered_root_key(data) != _path_key(root):
                raise ProjectRegistryUnavailable(
                    f"project registry row '{project_name}.json' changed root identity"
                )
            return str(root)
    except FileLockUnavailable as exc:
        raise ProjectRegistryUnavailable(
            f"project registry is temporarily unavailable: {exc}"
        ) from exc


def resolve_repo_root(repo_root: str | None = None, project: str | None = None) -> str:
    if repo_root:
        return repo_root
    if project:
        return str(load_project(project)["repo_root"])
    raise ValueError("provide --repo-root or --project")
