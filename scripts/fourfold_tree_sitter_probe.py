#!/usr/bin/env python3
"""Run bounded Tree-sitter structural extraction over a pinned repository slice.

The report is staged parser evidence only. It neither publishes a Forest nor
promotes syntax observations into verified cross-plane Fourfold bindings.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from daedalus.spine.envelope import canonical_sha
from daedalus.twin.extractors import SourceArtifact, detect_language, parse_artifact

_PARSE_LANGUAGES = frozenset({"rust", "java", "cpp", "c-cpp-header", "root-macro"})


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
    parser.add_argument("--max-files", type=int, default=1_500)
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

    candidates: list[tuple[str, str, str, tuple[str, ...], bytes]] = []
    for path in paths:
        detection = detect_language(path)
        if detection is None or detection.language_id not in _PARSE_LANGUAGES:
            continue
        candidate = root / path
        if not candidate.is_file():
            continue
        content = candidate.read_bytes()
        candidates.append((
            path,
            detection.language_id,
            detection.artifact_kind,
            detection.framework_hints,
            content,
        ))
    candidates = candidates[: args.max_files]

    bundle_members = [
        {
            "path": path,
            "language": language,
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
        }
        for path, language, _kind, _frameworks, content in candidates
    ]
    source_bundle_sha256 = canonical_sha({
        "schema": "daedalus-tree-sitter-probe-bundle/1",
        "repository_id": args.repository_id,
        "source_revision": args.source_revision,
        "members": bundle_members,
    })

    statuses: Counter[str] = Counter()
    files_by_language: Counter[str] = Counter()
    symbols_by_kind: Counter[str] = Counter()
    diagnostics_by_code: Counter[str] = Counter()
    total_symbols = 0
    total_nodes = 0
    error_nodes = 0
    failed_files: list[dict[str, object]] = []
    report_digests: list[str] = []

    for path, language, artifact_kind, framework_hints, content in candidates:
        artifact = SourceArtifact(
            repository_id=args.repository_id,
            source_revision=args.source_revision,
            path=path,
            content_sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            language_id=language,
            artifact_kind=artifact_kind,
            framework_hints=framework_hints,
        )
        report = parse_artifact(
            artifact,
            content,
            source_bundle_sha256=source_bundle_sha256,
        )
        statuses[report.result.status] += 1
        files_by_language[language] += 1
        total_symbols += len(report.symbols)
        total_nodes += report.total_nodes
        error_nodes += report.error_nodes
        report_digests.append(report.report_sha256)
        for symbol in report.symbols:
            symbols_by_kind[symbol.kind] += 1
        for diagnostic in report.result.diagnostics:
            diagnostics_by_code[diagnostic.code] += 1
        if report.result.status in {"partial", "failed"} and len(failed_files) < 100:
            failed_files.append({
                "path": path,
                "language": language,
                "status": report.result.status,
                "error_nodes": report.error_nodes,
                "diagnostics": [
                    {"code": item.code, "severity": item.severity, "message": item.message}
                    for item in report.result.diagnostics
                ],
            })

    report = {
        "schema": "daedalus-tree-sitter-repository-probe/1",
        "repository_id": args.repository_id,
        "source_revision": args.source_revision,
        "scope_prefixes": list(prefixes),
        "eligible_files": len(candidates),
        "max_files": args.max_files,
        "source_bundle_sha256": source_bundle_sha256,
        "files_by_language": dict(sorted(files_by_language.items())),
        "statuses": dict(sorted(statuses.items())),
        "total_syntax_nodes": total_nodes,
        "total_structural_symbols": total_symbols,
        "error_nodes": error_nodes,
        "symbols_by_kind": dict(sorted(symbols_by_kind.items())),
        "diagnostics_by_code": dict(sorted(diagnostics_by_code.items())),
        "non_complete_files": failed_files,
        "reports_digest": canonical_sha(sorted(report_digests)),
        "assurance": "structural-parser-evidence-only",
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
