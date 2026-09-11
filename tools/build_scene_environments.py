#!/usr/bin/env python3
"""Turn the Blender scene renders into the cockpit's environment assets.

Source of truth: ``docs/design/blender-scenes/renders/<id>.png`` plus the
sidecar ``<id>.json`` Blender wrote next to it (G1-UI-11). A missing final
render falls back to ``drafts/<id>.png`` and is marked ``quality: draft`` so
the Theme Studio can say so instead of passing a 24-sample preview off as the
finished picture.

Output: ``apps/web/src/shared/ui/scene/environments/`` with one full-size WebP
and one thumbnail per scene, and ``manifest.json`` binding every output to its
source bytes (SHA-256), Blender version, sample count and resolution. The
manifest is what the app imports for provenance; the images are imported by
Vite and hashed into the bundle like every other asset.

Nothing here is an effect on project state: it reads design documents and
writes frontend source assets. Re-running on unchanged inputs rewrites
identical bytes (Pillow's WebP encoder is deterministic for a fixed input and
libwebp version), so a diff after a re-run means a render actually changed.

Usage:
    python tools/build_scene_environments.py            # (re)build
    python tools/build_scene_environments.py --check    # verify manifest vs. files
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
# Launched as ``python tools/build_scene_environments.py`` Python puts only
# ``tools/`` on sys.path; bind the repository root so the canonical effect
# boundary imports. Same convention as the other portable tool rows.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCENES_DIR = ROOT / "docs" / "design" / "blender-scenes"
OUT_DIR = ROOT / "apps" / "web" / "src" / "shared" / "ui" / "scene" / "environments"
MANIFEST = OUT_DIR / "manifest.json"

# Same ids and order as docs/design/blender-scenes/scripts/build.py::SCENES and
# apps/web/src/shared/ui/scene/environments.ts. The registry in the app is the
# consumer; this list only says which renders to look for.
SCENE_IDS = ("porcelain", "graphite", "daylight", "dusk", "studio", "techno-forest")

FULL_WIDTH = 1600
THUMB_WIDTH = 480
FULL_QUALITY = 82
THUMB_QUALITY = 78


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def locate(scene_id: str) -> tuple[Path, Path | None, str]:
    """Final render first, draft second. Returns (png, sidecar json, quality)."""
    for folder, quality in (("renders", "final"), ("drafts", "draft")):
        png = SCENES_DIR / folder / f"{scene_id}.png"
        if png.is_file():
            sidecar = png.with_suffix(".json")
            return png, (sidecar if sidecar.is_file() else None), quality
    raise FileNotFoundError(f"no render for scene '{scene_id}' under {SCENES_DIR}")


def encode(source: Any, target: Path, width: int, quality: int, image_module: Any) -> dict:
    image = source
    if image.width > width:
        height = round(image.height * width / image.width)
        image = image.resize((width, height), image_module.Resampling.LANCZOS)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, format="WEBP", quality=quality, method=6)
    return {
        "file": target.name,
        "width": image.width,
        "height": image.height,
        "bytes": target.stat().st_size,
        "sha256": sha256(target),
    }


def build() -> dict:
    try:
        from PIL import Image, features
    except ImportError:  # pragma: no cover - environment-specific
        print("Pillow is required for generation: install daedalus[design-build]", file=sys.stderr)
        raise SystemExit(2)
    entries = []
    for scene_id in SCENE_IDS:
        png, sidecar, quality = locate(scene_id)
        meta = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar else {}
        with Image.open(png) as opened:
            # Renders are RGBA with an opaque alpha channel; WebP keeps the
            # channel and costs bytes for nothing, so flatten explicitly.
            rgb = opened.convert("RGB")
            source_resolution = [opened.width, opened.height]
            full = encode(rgb, OUT_DIR / f"{scene_id}.webp", FULL_WIDTH, FULL_QUALITY, Image)
            thumb = encode(rgb, OUT_DIR / f"{scene_id}.thumb.webp", THUMB_WIDTH, THUMB_QUALITY, Image)
        entries.append({
            "id": scene_id,
            "title": meta.get("title", scene_id),
            "quality": quality,
            "source": rel(png),
            "sourceSha256": sha256(png),
            "sourceResolution": list(meta.get("resolution", source_resolution)),
            "blender": meta.get("blender"),
            "samples": meta.get("samples_max"),
            "seed": meta.get("seed"),
            "blend": (SCENES_DIR / meta["blend"]).relative_to(ROOT).as_posix() if meta.get("blend") else None,
            "image": full,
            "thumb": thumb,
        })
    manifest = {
        "kind": "daedalus-scene-environments",
        "version": 1,
        "generator": rel(Path(__file__).resolve()),
        "encoder": {"pillow": Image.__version__, "webp": features.version("webp")},
        "environments": entries,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def check() -> int:
    if not MANIFEST.is_file():
        print(f"missing {rel(MANIFEST)}", file=sys.stderr)
        return 1
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    failures = []
    seen = set()
    for entry in manifest.get("environments", []):
        seen.add(entry["id"])
        for key in ("image", "thumb"):
            path = OUT_DIR / entry[key]["file"]
            if not path.is_file():
                failures.append(f"{entry['id']}: {key} file missing ({path.name})")
            elif sha256(path) != entry[key]["sha256"]:
                failures.append(f"{entry['id']}: {key} bytes differ from manifest")
        source = ROOT / entry["source"]
        if not source.is_file():
            failures.append(f"{entry['id']}: source render missing ({entry['source']})")
        elif sha256(source) != entry["sourceSha256"]:
            failures.append(f"{entry['id']}: source render changed since the manifest was written; re-run the build")
    missing = [scene_id for scene_id in SCENE_IDS if scene_id not in seen]
    if missing:
        failures.append(f"manifest lacks scenes: {', '.join(missing)}")
    for line in failures:
        print(line, file=sys.stderr)
    print(f"scene environments: {len(seen)} entries, {len(failures)} problem(s)")
    return 1 if failures else 0


def main() -> int:
    # Registered door ``tools.scene_environments_build`` in
    # daedalus/spine/effect_boundary.py: the boundary comes before argument
    # parsing so that ``--check`` (read-only) cannot hide the write this tool
    # can perform. The process guard is the real, idempotent spend net.
    from daedalus.budget import process_guard_boundary_decision
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "tools.scene_environments_build",
        REGISTRY_BY_ID["tools.scene_environments_build"].effects,
        (process_guard_boundary_decision(),),
    )
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="verify the manifest against the files without writing")
    args = parser.parse_args()
    if args.check:
        return check()
    manifest = build()
    for entry in manifest["environments"]:
        print(f"{entry['id']:14} {entry['quality']:5} {entry['image']['width']}x{entry['image']['height']} "
              f"{entry['image']['bytes']:>7} B  thumb {entry['thumb']['bytes']:>6} B  <- {entry['source']}")
    print(f"wrote {rel(MANIFEST)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
