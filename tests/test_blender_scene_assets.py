from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def _run(*parts: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *parts],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_scene_pngs_and_recorded_hashes_are_privacy_safe() -> None:
    result = _run("docs/design/blender-scenes/scripts/sanitize.py", "--check")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "12 files, 0 problem(s)" in result.stdout


def test_scene_environment_manifest_matches_checked_in_assets() -> None:
    result = _run("tools/build_scene_environments.py", "--check")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "6 entries, 0 problem(s)" in result.stdout

    manifest = json.loads(
        (ROOT / "apps/web/src/shared/ui/scene/environments/manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["encoder"] == {"pillow": "10.4.0", "webp": "1.4.0"}


def test_scene_archive_is_deterministic_and_excludes_raw_logs() -> None:
    result = _run("docs/design/blender-scenes/scripts/package.py", "--check")
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["privacy_check"] == "passed"
    assert report["logs_included"] is False

    archive = ROOT / "docs" / "design" / "Daedalus-Blender-Scenes.zip"
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        assert all("logs" not in Path(name).parts for name in bundle.namelist())
        assert all("__pycache__" not in Path(name).parts for name in bundle.namelist())
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in bundle.infolist())
