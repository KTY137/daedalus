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
        "_desktop_comment": (
            "Generated once by the Tauri desktop sidecar. The repository root is "
            "the writable packaged runtime, not the source checkout."
        ),
    }


def prepare_runtime(root: Path | None = None) -> Path:
    """Create desktop-owned runtime dirs and a self-project seed, without overwrite."""
    runtime = (root or bundled_root()).resolve()
    for relative in ("projects", "runs", "inbox", "outbox", "memory"):
        (runtime / relative).mkdir(parents=True, exist_ok=True)

    project_file = runtime / "projects" / "daedalus.json"
    if not project_file.exists():
        project_file.write_text(
            json.dumps(_desktop_project(runtime), indent=2) + "\n",
            encoding="utf-8",
        )
    return runtime


def main(argv: list[str] | None = None) -> None:
    runtime = prepare_runtime()
    os.chdir(runtime)

    # Import after the runtime exists. Existing modules derive their canonical
    # roots from __file__, which PyInstaller places below this writable mirror.
    from daedalus.web_api import main as web_main

    web_main(argv)


if __name__ == "__main__":
    main()
