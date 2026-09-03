"""Desktop entrypoint for the packaged Daedalus backend.

The Tauri shell copies the frozen backend into the user's app-data directory
before launching it. PyInstaller's ``sys._MEIPASS`` therefore becomes a
writable, persistent mini-repository containing the canonical Daedalus package
and the cockpit assets. Existing Daedalus path contracts keep working without
a second storage/control plane: ``runs/``, ``inbox/``, ``outbox/``, ``.env`` and
the canonical spine are created under that same root.

No provider credentials are bundled. Users may create ``.env`` in this runtime
root; the existing server-side loader continues to redact secret values.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any

DESKTOP_PROJECT_SCHEMA = "daedalus-desktop-self-project/1"
DESKTOP_PROJECT_COMMENT = (
    "Generated once by the Tauri desktop sidecar. The repository root is "
    "the writable packaged runtime, not the source checkout."
)


def bundled_root() -> Path:
    """Return the root that mirrors the repository inside the frozen app."""
    frozen = getattr(sys, "_MEIPASS", None)
    if frozen:
        return Path(frozen).resolve()
    return Path(__file__).resolve().parents[1]


def _desktop_project(root: Path) -> dict[str, Any]:
    return {
        "name": "daedalus",
        "repo_root": str(root),
        "center": ["daedalus", "apps/web/src"],
        "ignore": ["@tests"],
        "default_branch": "main",
        "policy": {
            "deny": [".env", "configs/secrets", "runs/", "inbox/", "outbox/"],
            "allow": ["daedalus/", "apps/web/src/", "docs/", ".md"],
        },
        "_desktop_schema": DESKTOP_PROJECT_SCHEMA,
        "_desktop_comment": DESKTOP_PROJECT_COMMENT,
    }


def _prepare_desktop_project(project_file: Path, runtime: Path) -> None:
    """Seed or relocate only the sidecar-owned self-project record."""

    from daedalus.atomic import write_text_atomic

    if not project_file.exists():
        payload = _desktop_project(runtime)
    else:
        try:
            existing = json.loads(project_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(existing, dict) or not (
            existing.get("_desktop_schema") == DESKTOP_PROJECT_SCHEMA
            or existing.get("_desktop_comment") == DESKTOP_PROJECT_COMMENT
        ):
            return
        payload = dict(existing)
        payload["repo_root"] = str(runtime)
        payload["_desktop_schema"] = DESKTOP_PROJECT_SCHEMA
        payload["_desktop_comment"] = DESKTOP_PROJECT_COMMENT
        if payload == existing:
            return

    write_text_atomic(
        project_file,
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
        newline="",
    )


def prepare_runtime(root: Path | None = None) -> Path:
    """Create desktop-owned runtime dirs and a self-project seed, without overwrite."""
    runtime = (root or bundled_root()).resolve()
    for relative in ("projects", "runs", "inbox", "outbox", "memory", "config"):
        (runtime / relative).mkdir(parents=True, exist_ok=True)

    project_file = runtime / "projects" / "daedalus.json"
    _prepare_desktop_project(project_file, runtime)
    return runtime


def main(argv: list[str] | None = None) -> None:
    runtime = prepare_runtime()
    os.chdir(runtime)

    # Load the existing desktop .env before connection settings are applied so
    # operator-owned trust lists and provider secrets remain part of the same
    # process environment. Desktop connection settings intentionally override
    # only their managed OLLAMA_* transport/model values afterwards.
    from daedalus.foundation.env import load_env

    load_env(runtime / ".env")

    # Apply desktop connection settings BEFORE importing the web API. Modules
    # that read OLLAMA_* at import time then see the same endpoint as Ikarus.
    from daedalus.desktop_runtime import (
        DesktopRuntimeManager,
        install_tunnel_egress_policy,
        install_web_integration,
    )

    manager = DesktopRuntimeManager(runtime)
    install_tunnel_egress_policy()

    # One control plane only: extend the existing authenticated/loopback server
    # instead of starting a second settings/service server beside it.
    from daedalus.interfaces.http import web_api

    install_web_integration(web_api, manager)
    manager.bootstrap()
    web_api.main(argv)


if __name__ == "__main__":
    # Frozen Windows multiprocessing children re-enter this executable with
    # ``--multiprocessing-fork``. Dispatch them before our web-API argparse sees
    # those private arguments.
    import multiprocessing

    multiprocessing.freeze_support()
    main()
