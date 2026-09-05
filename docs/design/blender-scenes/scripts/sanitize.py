#!/usr/bin/env python3
"""Strip private PNG metadata while preserving the rendered pixel stream."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import sys
import zlib

ROOT = Path(__file__).resolve().parent.parent
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PRIVATE_CHUNKS = frozenset({b"tEXt", b"zTXt", b"iTXt", b"eXIf"})
PRIVATE_PATH_PATTERNS = (
    re.compile(rb"[A-Za-z]:[\\/]" + b"Users" + rb"[\\/][^\\/\x00\r\n]+[\\/]", re.IGNORECASE),
    re.compile(b"/" + b"Users" + rb"/[^/\x00\r\n]+/"),
    re.compile(b"/" + b"home" + rb"/[^/\x00\r\n]+/"),
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def png_chunks(data: bytes) -> list[tuple[bytes, bytes, bytes]]:
    """Return validated ``(kind, payload, encoded_chunk)`` tuples."""
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("not a PNG")
    chunks: list[tuple[bytes, bytes, bytes]] = []
    offset = len(PNG_SIGNATURE)
    saw_iend = False
    while offset < len(data):
        if len(data) - offset < 12:
            raise ValueError("truncated PNG chunk")
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        end = offset + 12 + length
        if end > len(data):
            raise ValueError("PNG chunk exceeds file boundary")
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", data[offset + 8 + length : end])[0]
        actual_crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise ValueError(f"invalid {kind!r} CRC")
        chunks.append((kind, payload, data[offset:end]))
        offset = end
        if kind == b"IEND":
            saw_iend = True
            break
    if not saw_iend:
        raise ValueError("PNG has no IEND chunk")
    if offset != len(data):
        raise ValueError("bytes follow PNG IEND chunk")
    return chunks


def contains_private_path(data: bytes) -> bool:
    return any(pattern.search(data) is not None for pattern in PRIVATE_PATH_PATTERNS)


def inspect_png(path: Path) -> tuple[list[bytes], bool]:
    chunks = png_chunks(path.read_bytes())
    private_chunks = [kind for kind, _payload, _encoded in chunks if kind in PRIVATE_CHUNKS]
    private_path = any(contains_private_path(payload) for _kind, payload, _encoded in chunks)
    return private_chunks, private_path


def sanitize_png(path: Path) -> list[str]:
    original = path.read_bytes()
    chunks = png_chunks(original)
    idat_before = sha256_bytes(b"".join(payload for kind, payload, _encoded in chunks if kind == b"IDAT"))
    removed = [kind.decode("ascii") for kind, _payload, _encoded in chunks if kind in PRIVATE_CHUNKS]
    sanitized = PNG_SIGNATURE + b"".join(
        encoded for kind, _payload, encoded in chunks if kind not in PRIVATE_CHUNKS
    )
    sanitized_chunks = png_chunks(sanitized)
    idat_after = sha256_bytes(
        b"".join(payload for kind, payload, _encoded in sanitized_chunks if kind == b"IDAT")
    )
    if idat_before != idat_after:
        raise RuntimeError(f"pixel stream changed while sanitizing {path}")
    if contains_private_path(sanitized):
        raise RuntimeError(f"private absolute path remains in {path}")
    if sanitized != original:
        temporary = path.with_name(f".{path.name}.sanitizing")
        temporary.write_bytes(sanitized)
        os.replace(temporary, path)
    return removed


def source_pngs() -> list[Path]:
    return sorted((*((ROOT / "renders").glob("*.png")), *((ROOT / "drafts").glob("*.png"))))


def refresh_verification(paths: list[Path]) -> None:
    report_path = ROOT / "verification.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    by_id = {scene["id"]: scene for scene in report["scenes"]}
    for path in paths:
        if path.parent.name != "renders":
            continue
        scene = by_id[path.stem]
        scene["render_bytes"] = path.stat().st_size
        scene["render_sha256"] = sha256_bytes(path.read_bytes())
    report["png_metadata"] = {
        "policy": "Textual and EXIF chunks stripped; compressed IDAT pixel streams preserved byte-for-byte.",
        "files_checked": len(paths),
        "private_chunks": 0,
        "private_absolute_paths": 0,
    }
    temporary = report_path.with_name(f".{report_path.name}.sanitizing")
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, report_path)


def check(paths: list[Path]) -> int:
    failures: list[str] = []
    for path in paths:
        private_chunks, private_path = inspect_png(path)
        if private_chunks:
            failures.append(f"{path.relative_to(ROOT)}: private chunks {private_chunks!r}")
        if private_path:
            failures.append(f"{path.relative_to(ROOT)}: private absolute path")
    report = json.loads((ROOT / "verification.json").read_text(encoding="utf-8"))
    by_id = {scene["id"]: scene for scene in report.get("scenes", [])}
    for path in paths:
        if path.parent.name != "renders":
            continue
        scene = by_id.get(path.stem)
        if scene is None:
            failures.append(f"{path.relative_to(ROOT)}: absent from verification.json")
        elif scene.get("render_bytes") != path.stat().st_size or scene.get("render_sha256") != sha256_bytes(path.read_bytes()):
            failures.append(f"{path.relative_to(ROOT)}: verification.json digest differs")
    for failure in failures:
        print(failure, file=sys.stderr)
    print(f"scene PNG privacy: {len(paths)} files, {len(failures)} problem(s)")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify without writing")
    args = parser.parse_args()
    paths = source_pngs()
    if len(paths) != 12:
        print(f"expected 12 scene PNGs, found {len(paths)}", file=sys.stderr)
        return 1
    if args.check:
        return check(paths)
    removed: dict[str, list[str]] = {}
    for path in paths:
        removed[path.relative_to(ROOT).as_posix()] = sanitize_png(path)
    refresh_verification(paths)
    print(json.dumps({"files": len(paths), "removed_chunks": removed}, indent=2))
    return check(paths)


if __name__ == "__main__":
    sys.exit(main())
