"""End-to-end smoke test for the frozen desktop backend."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]


def executable_name() -> str:
    return "daedalus-web-api.exe" if sys.platform == "win32" else "daedalus-web-api"


def smoke(backend: Path, timeout_s: float = 25.0) -> None:
    source = backend.resolve()
    if not (source / "_internal").is_dir():
        raise SystemExit(f"missing PyInstaller _internal directory: {source}")

    with tempfile.TemporaryDirectory(prefix="daedalus-desktop-smoke-") as td:
        runtime = Path(td) / "backend"
        shutil.copytree(source, runtime)
        exe = runtime / executable_name()
        if not exe.is_file():
            raise SystemExit(f"missing frozen backend executable: {exe}")

        startup_nonce = "d" * 64
        child_env = os.environ.copy()
        child_env["DAEDALUS_DESKTOP_STARTUP_NONCE"] = startup_nonce
        proc = subprocess.Popen(
            [str(exe), "--host", "127.0.0.1", "--port", "8765"],
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
                        "http://127.0.0.1:8765/api/projects", timeout=1.0
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
                "http://127.0.0.1:8765/api/desktop-ready", timeout=3.0
            ) as response:
                ready = json.loads(response.read())
            if ready != {
                "schema": "daedalus-desktop-startup/1",
                "ready": True,
                "nonce": startup_nonce,
            }:
                raise SystemExit(f"desktop startup nonce mismatch: {ready!r}")

            with urlopen("http://127.0.0.1:8765/", timeout=3.0) as response:
                html = response.read().decode("utf-8", errors="replace")
            if 'id="root"' not in html:
                raise SystemExit(
                    "backend did not serve the built cockpit root document"
                )

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
    args = parser.parse_args(argv)
    smoke(Path(args.backend))


if __name__ == "__main__":
    main()
