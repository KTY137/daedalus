"""Local, offline CLI for knowledge dump ingestion and Fourfold correlation.

This command intentionally performs no network access.  Confluence and
MediaWiki content must already be exported.  The module is invokable with
``python -m daedalus.twin.knowledge_pipeline`` while the unified Daedalus CLI
and its effect-leased connector path are designed separately.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Any, Sequence

from ..spine.envelope import canonical_json
from ._reference_common import ReferenceCompileError, read_file, safe_relpath
from .contracts import parse_fourfold_snapshot
from .knowledge_access import KnowledgeAccessPolicy, build_access_scoped_context
from .knowledge_correlation import CorrelationPolicy, correlate_knowledge
from .knowledge_sources import (
    ACCESS_CLASSES,
    AUTHORITY_CLASSES,
    combine_knowledge_corpora,
    ingest_confluence_dump,
    ingest_mediawiki_dump,
    ingest_obsidian_vault,
)
from .knowledge_wire import (
    KnowledgeWireError,
    knowledge_corpus_json,
    parse_knowledge_corpus_json,
    parse_knowledge_forest_json,
    strict_json,
)


DEFAULT_JSON_LIMIT = 512_000_000
DEFAULT_MARKDOWN_FILE_LIMIT = 32_000_000


class KnowledgePipelineError(RuntimeError):
    """Stable user-facing error for the offline pipeline."""


def _read_regular(path: Path, *, max_bytes: int = DEFAULT_JSON_LIMIT) -> bytes:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as exc:
        raise KnowledgePipelineError(f"input is missing: {path}") from exc
    if stat.S_ISLNK(mode):
        raise KnowledgePipelineError(f"input must not be a symbolic link: {path}")
    if not stat.S_ISREG(mode):
        raise KnowledgePipelineError(f"input is not a regular file: {path}")
    before = path.stat()
    if before.st_size > max_bytes:
        raise KnowledgePipelineError(
            f"input exceeds byte limit: {path} ({before.st_size} > {max_bytes})"
        )
    data = path.read_bytes()
    after = path.stat()
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity_before != identity_after or len(data) != after.st_size:
        raise KnowledgePipelineError(f"input changed while being read: {path}")
    return data


def _write_atomic(path: Path, text: str, *, force: bool) -> None:
    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not force:
        raise KnowledgePipelineError(
            f"output already exists (pass --force to replace): {target}"
        )
    if target.exists() and target.is_symlink():
        raise KnowledgePipelineError(f"output must not be a symbolic link: {target}")
    fd, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
    )
    tmp = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()


def _load_json(path: str, label: str) -> Any:
    return strict_json(_read_regular(Path(path)), label)


def _load_snapshot(path: str):
    payload = _load_json(path, "Fourfold snapshot")
    if not isinstance(payload, dict):
        raise KnowledgePipelineError("Fourfold snapshot must be an object")
    try:
        return parse_fourfold_snapshot(payload)
    except ValueError as exc:
        raise KnowledgePipelineError(f"invalid Fourfold snapshot: {exc}") from exc


def _load_corpus(path: str):
    try:
        return parse_knowledge_corpus_json(
            _read_regular(Path(path)), f"knowledge corpus {path}"
        )
    except KnowledgeWireError as exc:
        raise KnowledgePipelineError(str(exc)) from exc


def _load_forest(path: str):
    try:
        return parse_knowledge_forest_json(
            _read_regular(Path(path)), f"knowledge forest {path}"
        )
    except KnowledgeWireError as exc:
        raise KnowledgePipelineError(str(exc)) from exc


def _obsidian_files(
    root_value: str,
    *,
    max_files: int,
    max_file_bytes: int,
    max_total_bytes: int,
) -> dict[str, bytes]:
    root = Path(root_value).resolve()
    if not root.is_dir():
        raise KnowledgePipelineError(f"Obsidian root is not a directory: {root}")
    rows: dict[str, bytes] = {}
    total = 0
    for candidate in sorted(root.rglob("*.md"), key=lambda item: item.as_posix().casefold()):
        try:
            rel = candidate.relative_to(root).as_posix()
        except ValueError as exc:
            raise KnowledgePipelineError("Obsidian path escaped the vault root") from exc
        try:
            rel = safe_relpath(rel, "Obsidian Markdown path")
            data = read_file(root, rel, max_bytes=max_file_bytes)
        except ReferenceCompileError as exc:
            raise KnowledgePipelineError(str(exc)) from exc
        rows[rel] = data
        total += len(data)
        if len(rows) > max_files:
            raise KnowledgePipelineError("Obsidian vault exceeds max_files")
        if total > max_total_bytes:
            raise KnowledgePipelineError("Obsidian vault exceeds max_total_bytes")
    if not rows:
        raise KnowledgePipelineError("Obsidian vault contains no Markdown files")
    return rows


def _emit(value: Any, output: str, *, force: bool, summary: dict[str, Any]) -> int:
    text = value if isinstance(value, str) else canonical_json(value)
    _write_atomic(Path(output), text, force=force)
    print(canonical_json({"output": str(Path(output).resolve()), **summary}))
    return 0


def _ingest_obsidian(args: argparse.Namespace) -> int:
    corpus = ingest_obsidian_vault(
        _obsidian_files(
            args.root,
            max_files=args.max_files,
            max_file_bytes=args.max_file_bytes,
            max_total_bytes=args.max_total_bytes,
        ),
        vault_id=args.vault_id,
        source_revision=args.source_revision,
        imported_at=args.imported_at,
        authority=args.authority,
        access_class=args.access_class,
        corpus_id=args.corpus_id,
        max_files=args.max_files,
        max_total_bytes=args.max_total_bytes,
    )
    return _emit(
        knowledge_corpus_json(corpus),
        args.output,
        force=args.force,
        summary={
            "schema": corpus.SCHEMA,
            "corpus_sha256": corpus.digest,
            "documents": len(corpus.documents),
            "claims": len(corpus.claims),
        },
    )


def _ingest_confluence(args: argparse.Namespace) -> int:
    payload = _load_json(args.input, "Confluence dump")
    if not isinstance(payload, dict):
        raise KnowledgePipelineError("Confluence dump must be an object")
    corpus = ingest_confluence_dump(
        payload,
        instance_id=args.instance_id,
        imported_at=args.imported_at,
        default_authority=args.authority,
        default_access_class=args.access_class,
        corpus_id=args.corpus_id,
    )
    return _emit(
        knowledge_corpus_json(corpus),
        args.output,
        force=args.force,
        summary={
            "schema": corpus.SCHEMA,
            "corpus_sha256": corpus.digest,
            "documents": len(corpus.documents),
            "claims": len(corpus.claims),
        },
    )


def _ingest_mediawiki(args: argparse.Namespace) -> int:
    payload = _load_json(args.input, "MediaWiki dump")
    if not isinstance(payload, dict):
        raise KnowledgePipelineError("MediaWiki dump must be an object")
    corpus = ingest_mediawiki_dump(
        payload,
        instance_id=args.instance_id,
        imported_at=args.imported_at,
        authority=args.authority,
        access_class=args.access_class,
        corpus_id=args.corpus_id,
    )
    return _emit(
        knowledge_corpus_json(corpus),
        args.output,
        force=args.force,
        summary={
            "schema": corpus.SCHEMA,
            "corpus_sha256": corpus.digest,
            "documents": len(corpus.documents),
            "claims": len(corpus.claims),
        },
    )


def _combine(args: argparse.Namespace) -> int:
    corpora = tuple(_load_corpus(path) for path in args.input)
    corpus = combine_knowledge_corpora(args.corpus_id, *corpora)
    return _emit(
        knowledge_corpus_json(corpus),
        args.output,
        force=args.force,
        summary={
            "schema": corpus.SCHEMA,
            "corpus_sha256": corpus.digest,
            "documents": len(corpus.documents),
            "claims": len(corpus.claims),
            "inputs": len(corpora),
        },
    )


def _correlate(args: argparse.Namespace) -> int:
    snapshot = _load_snapshot(args.snapshot)
    forest = _load_forest(args.forest)
    corpus = _load_corpus(args.corpus)
    result = correlate_knowledge(
        snapshot=snapshot,
        forest=forest,
        corpus=corpus,
        policy=CorrelationPolicy(
            min_proposal_score=args.min_score,
            max_proposals_per_claim=args.max_proposals_per_claim,
        ),
    )
    return _emit(
        result.to_dict(),
        args.output,
        force=args.force,
        summary={
            "schema": result.SCHEMA,
            "result_sha256": result.digest,
            "proposals": len(result.proposals),
            "contradictions": len(result.contradictions),
            "unresolved": len(result.unresolved),
        },
    )


def _context(args: argparse.Namespace) -> int:
    snapshot = _load_snapshot(args.snapshot)
    forest = _load_forest(args.forest)
    corpus = _load_corpus(args.corpus)
    result = correlate_knowledge(
        snapshot=snapshot,
        forest=forest,
        corpus=corpus,
        policy=CorrelationPolicy(
            min_proposal_score=args.min_score,
            max_proposals_per_claim=args.max_proposals_per_claim,
            max_context_bundles=args.max_context_bundles,
        ),
    )
    context = build_access_scoped_context(
        result,
        snapshot=snapshot,
        corpus=corpus,
        objective=args.objective,
        anchor_node_ids=tuple(args.anchor),
        access_policy=KnowledgeAccessPolicy(
            allowed_access_classes=tuple(args.allow_access),
            include_external_background=not args.exclude_external_background,
            max_context_bundles=args.max_context_bundles,
        ),
        correlation_policy=CorrelationPolicy(
            min_proposal_score=args.min_score,
            max_proposals_per_claim=args.max_proposals_per_claim,
            max_context_bundles=args.max_context_bundles,
            external_background_in_context=not args.exclude_external_background,
        ),
    )
    return _emit(
        context.to_dict(),
        args.output,
        force=args.force,
        summary={
            "schema": context.SCHEMA,
            "context_sha256": context.digest,
            "bundles": len(context.capsule.bundles),
            "withheld_claims": len(context.withheld_claim_sha256s),
        },
    )


def _add_output(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", required=True)
    parser.add_argument("--force", action="store_true")


def _add_import_policy(
    parser: argparse.ArgumentParser,
    *,
    default_authority: str,
    default_access: str,
) -> None:
    parser.add_argument("--authority", choices=sorted(AUTHORITY_CLASSES), default=default_authority)
    parser.add_argument("--access-class", choices=sorted(ACCESS_CLASSES), default=default_access)
    parser.add_argument("--corpus-id")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m daedalus.twin.knowledge_pipeline",
        description="Offline, provenance-preserving external knowledge ingestion and correlation.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    obsidian = sub.add_parser("ingest-obsidian", help="ingest a local Obsidian vault")
    obsidian.add_argument("--root", required=True)
    obsidian.add_argument("--vault-id", required=True)
    obsidian.add_argument("--source-revision", required=True)
    obsidian.add_argument("--imported-at", required=True)
    obsidian.add_argument("--max-files", type=int, default=20_000)
    obsidian.add_argument("--max-file-bytes", type=int, default=DEFAULT_MARKDOWN_FILE_LIMIT)
    obsidian.add_argument("--max-total-bytes", type=int, default=100_000_000)
    _add_import_policy(obsidian, default_authority="personal_note", default_access="private")
    _add_output(obsidian)
    obsidian.set_defaults(handler=_ingest_obsidian)

    confluence = sub.add_parser("ingest-confluence", help="ingest a normalized Confluence JSON dump")
    confluence.add_argument("--input", required=True)
    confluence.add_argument("--instance-id", required=True)
    confluence.add_argument("--imported-at", required=True)
    _add_import_policy(confluence, default_authority="project_documentation", default_access="internal")
    _add_output(confluence)
    confluence.set_defaults(handler=_ingest_confluence)

    mediawiki = sub.add_parser("ingest-mediawiki", help="ingest a normalized MediaWiki JSON dump")
    mediawiki.add_argument("--input", required=True)
    mediawiki.add_argument("--instance-id", required=True)
    mediawiki.add_argument("--imported-at", required=True)
    _add_import_policy(mediawiki, default_authority="external_reference", default_access="public")
    _add_output(mediawiki)
    mediawiki.set_defaults(handler=_ingest_mediawiki)

    combine = sub.add_parser("combine", help="combine canonical knowledge corpora")
    combine.add_argument("--input", action="append", required=True)
    combine.add_argument("--corpus-id", required=True)
    _add_output(combine)
    combine.set_defaults(handler=_combine)

    correlate = sub.add_parser("correlate", help="correlate one corpus with an exact Fourfold snapshot")
    correlate.add_argument("--snapshot", required=True)
    correlate.add_argument("--forest", required=True)
    correlate.add_argument("--corpus", required=True)
    correlate.add_argument("--min-score", type=float, default=0.58)
    correlate.add_argument("--max-proposals-per-claim", type=int, default=12)
    _add_output(correlate)
    correlate.set_defaults(handler=_correlate)

    context = sub.add_parser("context", help="build access-scoped context from local artifacts")
    context.add_argument("--snapshot", required=True)
    context.add_argument("--forest", required=True)
    context.add_argument("--corpus", required=True)
    context.add_argument("--objective", required=True)
    context.add_argument("--anchor", action="append", required=True)
    context.add_argument(
        "--allow-access",
        action="append",
        choices=sorted(ACCESS_CLASSES),
        default=None,
    )
    context.add_argument("--exclude-external-background", action="store_true")
    context.add_argument("--min-score", type=float, default=0.58)
    context.add_argument("--max-proposals-per-claim", type=int, default=12)
    context.add_argument("--max-context-bundles", type=int, default=24)
    _add_output(context)
    context.set_defaults(handler=_context)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if getattr(args, "allow_access", None) is None:
        args.allow_access = ["public", "internal"]
    try:
        return int(args.handler(args))
    except (
        KnowledgePipelineError,
        KnowledgeWireError,
        ReferenceCompileError,
        ValueError,
    ) as exc:
        print(f"knowledge pipeline refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - exercised by isolated CLI tests
    raise SystemExit(main())


__all__ = [
    "KnowledgePipelineError",
    "build_parser",
    "main",
]
