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
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
TAURI_DIR = ROOT / "apps" / "web" / "src-tauri"
BACKEND_DIR = TAURI_DIR / "backend"
BUILD_DIR = ROOT / "build" / "desktop-sidecar"

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
    return BACKEND_DIR


def main(argv: list[str] | None = None) -> None:
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
