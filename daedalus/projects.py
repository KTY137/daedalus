from __future__ import annotations

import json
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROJECT_DIR = ROOT / "projects"


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


def _registered_repo_root(raw: Any) -> str:
    """Resolve a project-file repo root without making it host-specific.

    Absolute paths remain byte-for-byte compatible, including Windows paths
    read while Daedalus is running on POSIX. Relative paths are deliberately
    anchored to this Daedalus checkout rather than the process CWD, so a
    self-project can use ``\"repo_root\": \".\"`` and work from a CLI, service,
    test runner, or CI checkout launched from any directory.
    """
    text = str(raw)
    expanded = str(Path(text).expanduser())
    if (
        Path(expanded).is_absolute()
        or PureWindowsPath(expanded).is_absolute()
        or PurePosixPath(expanded).is_absolute()
    ):
        return expanded
    return str((ROOT / expanded).resolve())


def resolve_repo_root(repo_root: str | None = None, project: str | None = None) -> str:
    if repo_root:
        # Explicit caller input remains exactly that caller's authority. Only
        # registered project paths get checkout-relative portability semantics.
        return repo_root
    if project:
        return _registered_repo_root(load_project(project)["repo_root"])
    raise ValueError("provide --repo-root or --project")
