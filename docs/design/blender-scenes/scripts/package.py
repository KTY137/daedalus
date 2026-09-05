"""Build or verify the deterministic, privacy-safe Blender scene archive."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

from sanitize import contains_private_path, inspect_png

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = ROOT.parent / "Daedalus-Blender-Scenes.zip"
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def included_files() -> list[Path]:
    return [
        path
        for path in sorted(ROOT.rglob("*"))
        if path.is_file()
        and "__pycache__" not in path.parts
        and "logs" not in path.relative_to(ROOT).parts
        and path.suffix != ".blend1"
    ]


def validate_sources(paths: list[Path]) -> None:
    report = json.loads((ROOT / "verification.json").read_text(encoding="utf-8"))
    if not report.get("all_passed") or len(report.get("scenes", [])) != 6:
        raise RuntimeError("verification.json does not record six passing scenes")
    for path in paths:
        data = path.read_bytes()
        if contains_private_path(data):
            raise RuntimeError(f"private absolute path in {path.relative_to(ROOT)}")
        if path.suffix.lower() == ".png":
            private_chunks, private_path = inspect_png(path)
            if private_chunks or private_path:
                raise RuntimeError(f"unsanitized metadata in {path.relative_to(ROOT)}")


def write_archive(target: Path, paths: list[Path]) -> None:
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in paths:
            name = (Path("blender-scenes") / path.relative_to(ROOT)).as_posix()
            info = zipfile.ZipInfo(name, date_time=ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)


def validate_archive(path: Path, expected_names: list[str]) -> dict[str, object]:
    with zipfile.ZipFile(path) as bundle:
        if bundle.testzip() is not None:
            raise RuntimeError("archive CRC verification failed")
        names = bundle.namelist()
        if names != expected_names:
            raise RuntimeError("archive member list differs from the source set")
        for info in bundle.infolist():
            if info.date_time != ZIP_TIMESTAMP:
                raise RuntimeError(f"non-deterministic timestamp on {info.filename}")
            if contains_private_path(bundle.read(info)):
                raise RuntimeError(f"private absolute path in archive member {info.filename}")
    return {
        "archive": str(path),
        "bytes": path.stat().st_size,
        "files": len(expected_names),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "crc_check": "passed",
        "privacy_check": "passed",
        "logs_included": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify the tracked archive without writing")
    args = parser.parse_args()
    paths = included_files()
    validate_sources(paths)
    names = [(Path("blender-scenes") / path.relative_to(ROOT)).as_posix() for path in paths]
    if args.check:
        if not ARCHIVE.is_file():
            print(f"missing {ARCHIVE}", file=sys.stderr)
            return 1
        with tempfile.TemporaryDirectory(prefix="daedalus-scene-archive-") as directory:
            expected = Path(directory) / ARCHIVE.name
            write_archive(expected, paths)
            if expected.read_bytes() != ARCHIVE.read_bytes():
                print("scene archive differs from deterministic rebuild", file=sys.stderr)
                return 1
        result = validate_archive(ARCHIVE, names)
    else:
        temporary = ARCHIVE.with_name(f".{ARCHIVE.name}.building")
        write_archive(temporary, paths)
        validate_archive(temporary, names)
        os.replace(temporary, ARCHIVE)
        result = validate_archive(ARCHIVE, names)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
