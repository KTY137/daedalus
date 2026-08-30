# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0
"""Check and attest the repository's explicit first-party source watermark."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "provenance" / "source-watermark-policy.json"
DEFAULT_MANIFEST = ROOT / "provenance" / "source-watermark-manifest.json"
MANIFEST_SCHEMA = "daedalus-source-provenance-manifest/1"
UTF8_BOM = b"\xef\xbb\xbf"
CODING_COOKIE = re.compile(r"coding[:=]\s*[-\w.]+")


class ProvenanceError(RuntimeError):
    """Raised when the watermark contract cannot be applied safely."""


def _run_git(root: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout


def load_policy_bytes(data: bytes) -> dict[str, Any]:
    policy = json.loads(data.decode("utf-8"))
    if policy.get("schema") != "daedalus-source-watermark-policy/1":
        raise ProvenanceError(f"unsupported policy schema: {policy.get('schema')!r}")
    return policy


def load_policy(path: Path = DEFAULT_POLICY) -> dict[str, Any]:
    return load_policy_bytes(path.read_bytes())


def repository_paths(root: Path) -> list[str]:
    raw = _run_git(
        root,
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "-z",
    )
    return sorted(
        item.decode("utf-8", errors="strict").replace("\\", "/")
        for item in raw.split(b"\0")
        if item
    )


def index_snapshot(root: Path) -> tuple[dict[str, bytes], dict[str, str]]:
    """Return exact staged blob bytes and modes for the prospective Git tree."""

    raw = _run_git(root, "ls-files", "--stage", "-z")
    entries: list[tuple[str, str, str]] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        metadata, encoded_path = record.split(b"\t", 1)
        mode, oid, stage = metadata.decode("ascii").split()
        if stage != "0":
            path = encoded_path.decode("utf-8", errors="strict")
            raise ProvenanceError(f"unmerged index entry: {path}")
        path = encoded_path.decode("utf-8", errors="strict").replace("\\", "/")
        entries.append((path, mode, oid))

    unique_oids = list(dict.fromkeys(oid for _, _, oid in entries))
    completed = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=root,
        input=("\n".join(unique_oids) + "\n").encode("ascii"),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stream = io.BytesIO(completed.stdout)
    objects: dict[str, bytes] = {}
    for expected_oid in unique_oids:
        header = stream.readline().rstrip(b"\n").split()
        if len(header) != 3 or header[0].decode("ascii") != expected_oid:
            raise ProvenanceError(f"unexpected git cat-file response for {expected_oid}")
        if header[1] != b"blob":
            raise ProvenanceError(f"index object is not a blob: {expected_oid}")
        size = int(header[2])
        data = stream.read(size)
        if len(data) != size or stream.read(1) != b"\n":
            raise ProvenanceError(f"truncated git blob response: {expected_oid}")
        objects[expected_oid] = data

    blobs = {path: objects[oid] for path, _, oid in entries}
    modes = {path: mode for path, mode, _ in entries}
    return blobs, modes


def _is_under(path: str, prefix: str) -> bool:
    return path.startswith(prefix)


def read_repository_file(root: Path, relative: str) -> bytes:
    posix = PurePosixPath(relative)
    if posix.is_absolute() or not posix.parts or ".." in posix.parts:
        raise ProvenanceError(f"unsafe repository path: {relative!r}")
    path = root.joinpath(*posix.parts)
    if path.is_symlink():
        raise ProvenanceError(f"refusing symlink source: {relative}")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root.resolve())
    except (FileNotFoundError, ValueError) as exc:
        raise ProvenanceError(f"source escapes or is missing: {relative}") from exc
    if not resolved.is_file():
        raise ProvenanceError(f"source is not a regular file: {relative}")
    return resolved.read_bytes()


def is_candidate(path: str, policy: dict[str, Any]) -> bool:
    normalized = str(PurePosixPath(path))
    if normalized in policy["exclude"].get("paths", []):
        return False
    excludes = policy["exclude"]["prefixes"]
    if any(_is_under(normalized, prefix) for prefix in excludes):
        return False
    if normalized in policy["include"]["paths"]:
        return True
    suffix = PurePosixPath(normalized).suffix.lower()
    for prefix, extensions in policy["include"]["prefixes"].items():
        if _is_under(normalized, prefix) and suffix in extensions:
            return True
    return False


def candidate_paths(root: Path, policy: dict[str, Any]) -> list[str]:
    return [path for path in repository_paths(root) if is_candidate(path, policy)]


def index_candidate_paths(blobs: dict[str, bytes], policy: dict[str, Any]) -> list[str]:
    return sorted(path for path in blobs if is_candidate(path, policy))


def header_lines(path: str, policy: dict[str, Any], newline: str) -> list[str]:
    copyright_line = policy["copyright_header"]
    license_line = policy["license_header"]
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in {".py", ".ps1", ".sh", ".yml", ".yaml"}:
        return [f"# {copyright_line}{newline}", f"# {license_line}{newline}"]
    if suffix in {".js", ".mjs", ".rs", ".ts", ".tsx"}:
        return [f"// {copyright_line}{newline}", f"// {license_line}{newline}"]
    if suffix == ".css":
        return [
            f"/* {copyright_line}{newline}",
            f" * {license_line} */{newline}",
        ]
    if suffix == ".html":
        return [
            f"<!-- {copyright_line}{newline}",
            f"     {license_line} -->{newline}",
        ]
    raise ProvenanceError(f"no safe comment syntax configured for {path}")


def _newline_for(text: str) -> str:
    first_lf = text.find("\n")
    if first_lf > 0 and text[first_lf - 1] == "\r":
        return "\r\n"
    return "\n"


def _insertion_index(path: str, lines: Sequence[str]) -> int:
    suffix = PurePosixPath(path).suffix.lower()
    index = 0
    if lines and lines[0].startswith("#!"):
        index = 1
    if suffix == ".py":
        for candidate in range(min(2, len(lines))):
            if CODING_COOKIE.search(lines[candidate]):
                index = max(index, candidate + 1)
    if suffix == ".html" and lines:
        first = lines[0].lstrip("\ufeff").lower()
        if first.startswith("<!doctype"):
            index = 1
    if suffix == ".css" and lines and lines[0].lstrip("\ufeff").lower().startswith("@charset"):
        index = 1
    return index


def has_exact_header(path: str, data: bytes, policy: dict[str, Any]) -> bool:
    body = data[len(UTF8_BOM) :] if data.startswith(UTF8_BOM) else data
    text = body.decode("utf-8", errors="strict")
    newline = _newline_for(text)
    lines = text.splitlines(keepends=True)
    index = _insertion_index(path, lines)
    expected = header_lines(path, policy, newline)
    return lines[index : index + len(expected)] == expected


def add_header(path: str, data: bytes, policy: dict[str, Any]) -> bytes:
    bom = UTF8_BOM if data.startswith(UTF8_BOM) else b""
    body = data[len(bom) :]
    text = body.decode("utf-8", errors="strict")
    if has_exact_header(path, data, policy):
        return data
    first = text[:4096]
    if "SPDX-FileCopyrightText:" in first or "SPDX-License-Identifier:" in first:
        raise ProvenanceError(f"refusing to overwrite a different SPDX preamble: {path}")
    newline = _newline_for(text)
    lines = text.splitlines(keepends=True)
    index = _insertion_index(path, lines)
    header = header_lines(path, policy, newline)
    if index < len(lines) and lines[index].strip():
        header.append(newline)
    rendered = "".join([*lines[:index], *header, *lines[index:]])
    return bom + rendered.encode("utf-8")


def check(root: Path, policy: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for relative in candidate_paths(root, policy):
        path = root / relative
        try:
            data = read_repository_file(root, relative)
            if not has_exact_header(relative, data, policy):
                failures.append(relative)
        except (OSError, UnicodeError, ProvenanceError) as exc:
            failures.append(f"{relative}: {exc}")
    return failures


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_manifest(
    root: Path,
    policy_path: Path,
    *,
    target_ref: str,
    base_revision: str,
) -> dict[str, Any]:
    blobs, modes = index_snapshot(root)
    policy_relative = policy_path.resolve().relative_to(root.resolve()).as_posix()
    try:
        policy_bytes = blobs[policy_relative]
    except KeyError as exc:
        raise ProvenanceError(f"policy is not staged: {policy_relative}") from exc
    policy = load_policy_bytes(policy_bytes)
    candidates = index_candidate_paths(blobs, policy)
    failures: list[str] = []
    for relative in candidates:
        if modes[relative] == "120000":
            failures.append(f"refusing symlink source: {relative}")
        elif not has_exact_header(relative, blobs[relative], policy):
            failures.append(relative)
    if failures:
        raise ProvenanceError(
            "watermark check failed before manifest generation:\n" + "\n".join(failures)
        )
    files = [
        {"path": relative, "sha256": sha256_bytes(blobs[relative])}
        for relative in candidates
    ]
    required = {
        "policy": policy_relative,
        "notice": "NOTICE",
        "allowed_signers": "provenance/source-watermark-allowed-signers",
    }
    for label, relative in required.items():
        if relative not in blobs:
            raise ProvenanceError(f"{label} is not staged: {relative}")
    return {
        "schema": MANIFEST_SCHEMA,
        "target_ref": target_ref,
        "base_revision": base_revision,
        "copyright_header": policy["copyright_header"],
        "license_header": policy["license_header"],
        "license_identifier": policy["license_identifier"],
        "policy": {
            "path": policy_relative,
            "sha256": sha256_bytes(blobs[policy_relative]),
        },
        "notice": {
            "path": "NOTICE",
            "sha256": sha256_bytes(blobs["NOTICE"]),
        },
        "allowed_signers": {
            "path": "provenance/source-watermark-allowed-signers",
            "sha256": sha256_bytes(
                blobs["provenance/source-watermark-allowed-signers"]
            ),
        },
        "file_count": len(files),
        "files": files,
    }


def verify_manifest(
    root: Path,
    manifest_path: Path,
    policy_path: Path = DEFAULT_POLICY,
    *,
    expected_target_ref: str | None = None,
    expected_base_revision: str | None = None,
) -> list[str]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    if manifest.get("schema") != MANIFEST_SCHEMA:
        failures.append(f"unsupported manifest schema: {manifest.get('schema')!r}")
        return failures
    blobs, modes = index_snapshot(root)
    policy_relative = policy_path.resolve().relative_to(root.resolve()).as_posix()
    policy_item = manifest.get("policy", {})
    if policy_item.get("path") != policy_relative:
        failures.append("manifest policy path does not match requested policy")
        return failures
    try:
        policy = load_policy_bytes(blobs[policy_relative])
    except KeyError:
        failures.append(f"policy is not staged: {policy_relative}")
        return failures

    if expected_target_ref is not None and manifest.get("target_ref") != expected_target_ref:
        failures.append("manifest target_ref does not match expected target")
    base_revision = manifest.get("base_revision")
    if not isinstance(base_revision, str) or not re.fullmatch(r"[0-9a-f]{40}", base_revision):
        failures.append("manifest base_revision is not a lowercase 40-hex commit id")
    if expected_base_revision is not None and base_revision != expected_base_revision:
        failures.append("manifest base_revision does not match expected base")
    for field in ("copyright_header", "license_header", "license_identifier"):
        if manifest.get(field) != policy.get(field):
            failures.append(f"manifest {field} does not match policy")

    required = {
        "policy": policy_relative,
        "notice": "NOTICE",
        "allowed_signers": "provenance/source-watermark-allowed-signers",
    }
    for key, relative in required.items():
        item = manifest.get(key, {})
        if item.get("path") != relative:
            failures.append(f"manifest {key} path mismatch")
            continue
        if relative not in blobs:
            failures.append(f"{key} is not staged: {relative}")
            continue
        if sha256_bytes(blobs[relative]) != item.get("sha256"):
            failures.append(f"{key} digest mismatch: {relative}")

    candidates = index_candidate_paths(blobs, policy)
    for relative in candidates:
        if modes[relative] == "120000":
            failures.append(f"refusing symlink source: {relative}")
        elif not has_exact_header(relative, blobs[relative], policy):
            failures.append(f"staged source lacks watermark: {relative}")

    files = manifest.get("files")
    if not isinstance(files, list):
        failures.append("manifest files is not a list")
        return failures
    paths = [item.get("path") for item in files if isinstance(item, dict)]
    if len(paths) != len(files) or paths != candidates:
        failures.append("manifest files are incomplete, duplicated, or unsorted")
    if manifest.get("file_count") != len(candidates):
        failures.append("manifest file_count does not match policy candidates")
    for item in files:
        if not isinstance(item, dict):
            continue
        relative = item.get("path")
        if relative not in blobs:
            failures.append(f"manifest file is not staged: {relative}")
            continue
        if sha256_bytes(blobs[relative]) != item.get("sha256"):
            failures.append(f"file digest mismatch: {relative}")
    return failures


def _print_failures(label: str, failures: Iterable[str]) -> int:
    rows = list(failures)
    if not rows:
        print(f"{label}: ok")
        return 0
    print(f"{label}: failed ({len(rows)})", file=sys.stderr)
    for row in rows:
        print(f"  {row}", file=sys.stderr)
    return 1


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check")
    manifest_parser = subparsers.add_parser("render-manifest")
    manifest_parser.add_argument("--target-ref", required=True)
    manifest_parser.add_argument("--base-revision", required=True)
    verify_parser = subparsers.add_parser("verify-manifest")
    verify_parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    verify_parser.add_argument("--target-ref", required=True)
    verify_parser.add_argument("--base-revision", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve()
    policy_path = args.policy.resolve()
    policy = load_policy(policy_path)
    if args.command == "check":
        failures = check(root, policy)
        if failures:
            return _print_failures("source provenance", failures)
        print(f"source provenance: ok ({len(candidate_paths(root, policy))} files)")
        return 0
    if args.command == "render-manifest":
        manifest = build_manifest(
            root,
            policy_path,
            target_ref=args.target_ref,
            base_revision=args.base_revision,
        )
        rendered = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        )
        sys.stdout.buffer.write(rendered)
        return 0
    if args.command == "verify-manifest":
        return _print_failures(
            "source provenance manifest",
            verify_manifest(
                root,
                args.manifest.resolve(),
                policy_path,
                expected_target_ref=args.target_ref,
                expected_base_revision=args.base_revision,
            ),
        )
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
