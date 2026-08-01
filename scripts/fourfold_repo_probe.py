#!/usr/bin/env python3
"""Produce a bounded, deterministic polyglot source-discovery report.

This is a benchmark probe, not a Fourfold compiler. It establishes repository
shape and adapter demand without upgrading suffix detection into semantic facts.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from daedalus.twin.extractors import detect_language


def tracked_paths(root: Path) -> tuple[str, ...]:
    completed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return tuple(sorted(item.decode("utf-8") for item in completed.stdout.split(b"\0") if item))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--repository-id", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--include-prefix", action="append", default=[])
    parser.add_argument("--max-files", type=int, default=100_000)
    parser.add_argument("--max-total-bytes", type=int, default=2_000_000_000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    root = args.root.resolve()
    prefixes = tuple(sorted({prefix.strip("/") + "/" for prefix in args.include_prefix if prefix.strip("/")}))
    paths = tracked_paths(root)
    if prefixes:
        paths = tuple(path for path in paths if any(path == prefix[:-1] or path.startswith(prefix) for prefix in prefixes))

    counts: Counter[str] = Counter()
    bytes_by_language: Counter[str] = Counter()
    total_bytes = 0
    supported_files = 0
    skipped_missing = 0
    digest = hashlib.sha256()

    for path in paths:
        detection = detect_language(path)
        if detection is None:
            continue
        candidate = root / path
        if not candidate.is_file():
            skipped_missing += 1
            continue
        size = candidate.stat().st_size
        supported_files += 1
        total_bytes += size
        if supported_files > args.max_files:
            raise SystemExit(f"supported file limit exceeded: {supported_files} > {args.max_files}")
        if total_bytes > args.max_total_bytes:
            raise SystemExit(f"supported byte limit exceeded: {total_bytes} > {args.max_total_bytes}")
        counts[detection.language_id] += 1
        bytes_by_language[detection.language_id] += size
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(size).encode("ascii"))
        digest.update(b"\0")
        digest.update(detection.language_id.encode("ascii"))
        digest.update(b"\n")

    report = {
        "schema": "daedalus-polyglot-repository-probe/1",
        "repository_id": args.repository_id,
        "source_revision": args.source_revision,
        "scope_prefixes": list(prefixes),
        "tracked_paths_in_scope": len(paths),
        "supported_files": supported_files,
        "supported_bytes": total_bytes,
        "skipped_missing": skipped_missing,
        "files_by_language": dict(sorted(counts.items())),
        "bytes_by_language": dict(sorted(bytes_by_language.items())),
        "shape_digest": digest.hexdigest(),
        "assurance": "discovery-only",
    }
    encoded = json.dumps(report, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        sys.stdout.write(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
