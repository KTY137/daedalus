"""End-to-end smoke test for the frozen desktop backend."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import struct
import sys
import tempfile
import time
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
SCENE_IDS = ("porcelain", "graphite", "daylight", "dusk", "studio", "techno-forest")


def executable_name() -> str:
    return "daedalus-web-api.exe" if sys.platform == "win32" else "daedalus-web-api"


def _verify_scene_assets(runtime: Path, base_url: str = "http://127.0.0.1:8765") -> None:
    """Prove the frozen HTTP server returns the actual six packaged GLBs."""
    scene_root = runtime / "_internal" / "apps" / "web" / "dist" / "scenes"
    manifest_path = scene_root / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit("frozen cockpit scene manifest is missing")
    expected_manifest = manifest_path.read_bytes()
    with urlopen(f"{base_url}/scenes/manifest.json", timeout=5.0) as response:
        served_manifest = response.read(len(expected_manifest) + 1)
    if served_manifest != expected_manifest:
        raise SystemExit("served scene manifest differs from the packaged file")
    scenes = json.loads(served_manifest).get("scenes", {})
    if set(scenes) != set(SCENE_IDS):
        raise SystemExit("packaged scene manifest must contain all six Blender scenes")
    for scene_id in SCENE_IDS:
        asset_url = f"/scenes/{scene_id}.glb"
        if scenes[scene_id].get("url") != asset_url:
            raise SystemExit(f"unexpected packaged scene URL: {scene_id}")
        expected = (scene_root / f"{scene_id}.glb").read_bytes()
        with urlopen(f"{base_url}{asset_url}", timeout=5.0) as response:
            served = response.read(len(expected) + 1)
        if served != expected:
            raise SystemExit(f"served GLB differs from the packaged file: {scene_id}")
        if len(served) < 12 or struct.unpack("<4sII", served[:12]) != (b"glTF", 2, len(served)):
            raise SystemExit(f"packaged scene is not a complete GLB v2: {scene_id}")
    print(f"Frozen cockpit served all {len(SCENE_IDS)} Blender scenes with exact packaged bytes.")


def smoke(backend: Path, timeout_s: float = 25.0, port: int = 8765) -> None:
    if not 1 <= port <= 65535:
        raise SystemExit("smoke port must be between 1 and 65535")
    base_url = f"http://127.0.0.1:{port}"
    source = backend.resolve()
    if not (source / "_internal").is_dir():
        raise SystemExit(f"missing PyInstaller _internal directory: {source}")

    with tempfile.TemporaryDirectory(prefix="daedalus-desktop-smoke-") as td:
        runtime = Path(td) / "backend"
        shutil.copytree(source, runtime)
        exe = runtime / executable_name()
        if not exe.is_file():
            raise SystemExit(f"missing frozen backend executable: {exe}")

        startup_nonce = secrets.token_hex(32)
        child_env = os.environ.copy()
        child_env["DAEDALUS_DESKTOP_STARTUP_NONCE"] = startup_nonce
        proc = subprocess.Popen(
            [str(exe), "--host", "127.0.0.1", "--port", str(port)],
            cwd=runtime,
            env=child_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + timeout_s
            projects_payload = b""
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    raise SystemExit(
                        f"desktop backend exited early with code {proc.returncode}"
                    )
                try:
                    with urlopen(
                        f"{base_url}/api/projects", timeout=1.0
                    ) as response:
                        projects_payload = response.read()
                    break
                except OSError:
                    time.sleep(0.25)
            else:
                raise SystemExit(
                    "desktop backend did not become reachable within the smoke budget"
                )

            payload = json.loads(projects_payload)
            names = {str(row.get("name")) for row in payload.get("projects", [])}
            if "daedalus" not in names:
                raise SystemExit(
                    f"desktop self-project missing from /api/projects: {payload!r}"
                )

            with urlopen(
                f"{base_url}/api/desktop-ready", timeout=3.0
            ) as response:
                ready = json.loads(response.read())
            if ready != {
                "schema": "daedalus-desktop-startup/1",
                "ready": True,
                "nonce": startup_nonce,
            }:
                raise SystemExit(f"desktop startup nonce mismatch: {ready!r}")

            with urlopen(f"{base_url}/", timeout=3.0) as response:
                html = response.read().decode("utf-8", errors="replace")
            if 'id="root"' not in html:
                raise SystemExit(
                    "backend did not serve the built cockpit root document"
                )

            _verify_scene_assets(runtime, base_url)

            runtime_project = runtime / "_internal" / "projects" / "daedalus.json"
            if not runtime_project.is_file():
                raise SystemExit("desktop runtime project seed was not persisted")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5.0)


def main(argv: list[str] | None = None) -> None:
    from daedalus.budget import process_guard_boundary_decision
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "tools.desktop_sidecar_smoke",
        REGISTRY_BY_ID["tools.desktop_sidecar_smoke"].effects,
        (process_guard_boundary_decision(),),
    )
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--backend",
        default=str(ROOT / "apps" / "web" / "src-tauri" / "backend"),
    )
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    smoke(Path(args.backend), port=args.port)


if __name__ == "__main__":
    main()
