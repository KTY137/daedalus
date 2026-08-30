# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path
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


def resolve_repo_root(repo_root: str | None = None, project: str | None = None) -> str:
    if repo_root:
        return repo_root
    if project:
        return str(load_project(project)["repo_root"])
    raise ValueError("provide --repo-root or --project")
