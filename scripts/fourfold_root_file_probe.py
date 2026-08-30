#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Run bounded read-only ROOT metadata extraction on a pinned repository slice."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from daedalus.spine.envelope import canonical_sha
from daedalus.twin.extractors import (
    SourceArtifact,
    detect_language,
    inspect_root_artifact,
)


def tracked_paths(root: Path) -> tuple[str, ...]:
    completed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return tuple(
        sorted(item.decode("utf-8") for item in completed.stdout.split(b"\0") if item)
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--repository-id", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--include-prefix", action="append", default=[])
    parser.add_argument("--max-files", type=int, default=100)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.max_files <= 0:
        raise SystemExit("--max-files must be positive")
    root = args.root.resolve()
    prefixes = tuple(
        sorted({
            prefix.strip("/") + "/"
            for prefix in args.include_prefix
            if prefix.strip("/")
        })
    )
    paths = tracked_paths(root)
    if prefixes:
        paths = tuple(
            path
            for path in paths
            if any(path == prefix[:-1] or path.startswith(prefix) for prefix in prefixes)
        )

    candidates: list[tuple[str, tuple[str, ...], bytes]] = []
    for path in paths:
        detection = detect_language(path)
        if detection is None or detection.language_id != "root-binary":
            continue
        candidate = root / path
        if not candidate.is_file():
            continue
        candidates.append((path, detection.framework_hints, candidate.read_bytes()))
    candidates = candidates[: args.max_files]

    source_bundle_sha256 = canonical_sha({
        "schema": "daedalus-root-probe-bundle/1",
        "repository_id": args.repository_id,
        "source_revision": args.source_revision,
        "members": [
            {
                "path": path,
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
            }
            for path, _frameworks, content in candidates
        ],
    })

    statuses: Counter[str] = Counter()
    object_kinds: Counter[str] = Counter()
    classnames: Counter[str] = Counter()
    diagnostics: Counter[str] = Counter()
    total_objects = 0
    total_fields = 0
    report_digests: list[str] = []
    non_complete: list[dict[str, object]] = []

    for path, framework_hints, content in candidates:
        artifact = SourceArtifact(
            repository_id=args.repository_id,
            source_revision=args.source_revision,
            path=path,
            content_sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            language_id="root-binary",
            artifact_kind="binary",
            framework_hints=framework_hints,
        )
        report = inspect_root_artifact(
            artifact,
            content,
            source_bundle_sha256=source_bundle_sha256,
        )
        statuses[report.result.status] += 1
        total_objects += len(report.objects)
        total_fields += report.total_fields
        report_digests.append(report.report_sha256)
        for record in report.objects:
            object_kinds[record.kind] += 1
            classnames[record.classname] += 1
        for diagnostic in report.result.diagnostics:
            diagnostics[diagnostic.code] += 1
        if report.result.status != "complete":
            non_complete.append({
                "path": path,
                "status": report.result.status,
                "diagnostics": [
                    {
                        "code": item.code,
                        "severity": item.severity,
                        "message": item.message,
                    }
                    for item in report.result.diagnostics
                ],
            })

    output = {
        "schema": "daedalus-root-repository-probe/1",
        "repository_id": args.repository_id,
        "source_revision": args.source_revision,
        "scope_prefixes": list(prefixes),
        "root_files": len(candidates),
        "source_bundle_sha256": source_bundle_sha256,
        "statuses": dict(sorted(statuses.items())),
        "total_objects": total_objects,
        "total_fields": total_fields,
        "object_kinds": dict(sorted(object_kinds.items())),
        "classnames": dict(sorted(classnames.items())),
        "diagnostics_by_code": dict(sorted(diagnostics.items())),
        "non_complete_files": non_complete,
        "reports_digest": canonical_sha(sorted(report_digests)),
        "assurance": "root-metadata-evidence-only",
    }
    encoded = json.dumps(output, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        sys.stdout.write(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
