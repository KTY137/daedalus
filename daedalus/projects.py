from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

from .atomic import publish_bytes_once


ROOT = Path(__file__).resolve().parents[1]
PROJECT_DIR = ROOT / "projects"

_SAFE_NAME_RE = re.compile(r"[^a-z0-9_-]+")
_WINDOWS_RESERVED_NAMES = {
    "con", "prn", "aux", "nul",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


class ProjectRegistrationError(ValueError):
    """The caller supplied a project registration that cannot be accepted."""


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


def _registered_path(data: object) -> Path | None:
    if not isinstance(data, dict):
        return None
    raw = data.get("repo_root")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return Path(raw).expanduser().resolve(strict=False)
    except (OSError, RuntimeError):
        return None


def register_project(repo_root: object, name: object = None) -> dict[str, Any]:
    """Register an existing directory in ``projects/`` without adding policy.

    The canonical path is the identity: registering it again returns the
    existing name and performs no write. New configurations contain only the
    display/storage name and canonical repository root. Publication is an
    exclusive atomic create, so a concurrent name collision cannot overwrite
    another project's configuration.
    """
    root = _canonical_repo_root(repo_root)
    root_key = _path_key(root)

    for config_path in sorted(PROJECT_DIR.glob("*.json")):
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        existing_root = _registered_path(data)
        if existing_root is not None and _path_key(existing_root) == root_key:
            return {
                "name": config_path.stem,
                "repo_root": str(root),
                "created": False,
            }

    project_name = _safe_project_name(name, fallback=root.name, path_key=root_key)
    target = PROJECT_DIR / f"{project_name}.json"
    if target.exists() and name is None:
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
        except (OSError, json.JSONDecodeError) as exc:
            raise ProjectRegistrationError(
                f"project name '{project_name}' is already registered") from exc
        existing_root = _registered_path(existing)
        if existing_root is None or _path_key(existing_root) != root_key:
            raise ProjectRegistrationError(
                f"project name '{project_name}' is already registered")
        return {"name": project_name, "repo_root": str(root), "created": False}

    return {"name": project_name, "repo_root": str(root), "created": True}


def list_projects() -> list[str]:
    return [p.stem for p in sorted(PROJECT_DIR.glob("*.json"))]


def load_project(name: str) -> dict[str, Any]:
    path = PROJECT_DIR / f"{name}.json"
    if not path.exists():
        known = ", ".join(list_projects()) or "none"
        raise ValueError(f"unknown project '{name}'. Known projects: {known}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if "repo_root" not in data:
        raise ValueError(f"project '{name}' is missing repo_root")
    data.setdefault("name", name)
    return data


def resolve_repo_root(repo_root: str | None = None, project: str | None = None) -> str:
    if repo_root:
        return repo_root
    if project:
        return str(load_project(project)["repo_root"])
    raise ValueError("provide --repo-root or --project")
