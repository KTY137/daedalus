"""Offline CLI for provenance-preserving knowledge ingestion and correlation.

The command performs no network access. Confluence/MediaWiki content must
already be exported; remote fetching belongs behind the Daedalus effect
boundary. Invoke with ``python -m daedalus.twin.knowledge_pipeline``.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Any, Callable, Sequence

from ..spine.envelope import canonical_json
from ._reference_common import ReferenceCompileError, read_file, safe_relpath
from .contracts import parse_fourfold_snapshot
from .knowledge_access import KnowledgeAccessPolicy, build_access_scoped_context
from .knowledge_correlation import CorrelationPolicy, correlate_knowledge
from .knowledge_dump_adapters import (
    MediaWikiXMLLimits,
    ingest_confluence_rest_dump,
    ingest_mediawiki_xml_dump,
)
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
    """Stable user-facing refusal from the local pipeline."""


def _absolute_without_resolving(path: Path) -> Path:
    """Return an absolute spelling without following the final symlink."""

    expanded = path.expanduser()
    return expanded if expanded.is_absolute() else Path.cwd() / expanded


def _read_regular(path: Path, *, max_bytes: int = DEFAULT_JSON_LIMIT) -> bytes:
    candidate = _absolute_without_resolving(path)
    try:
        before_lstat = candidate.lstat()
    except FileNotFoundError as exc:
        raise KnowledgePipelineError(f"input is missing: {candidate}") from exc
    if stat.S_ISLNK(before_lstat.st_mode):
        raise KnowledgePipelineError(f"input must not be a symbolic link: {candidate}")
    if not stat.S_ISREG(before_lstat.st_mode):
        raise KnowledgePipelineError(f"input is not a regular file: {candidate}")
    before = candidate.stat()
    if before.st_size > max_bytes:
        raise KnowledgePipelineError(
            f"input exceeds byte limit: {candidate} ({before.st_size} > {max_bytes})"
        )
    data = candidate.read_bytes()
    after_lstat = candidate.lstat()
    after = candidate.stat()
    if stat.S_ISLNK(after_lstat.st_mode):
        raise KnowledgePipelineError(f"input became a symbolic link: {candidate}")
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity_before != identity_after or len(data) != after.st_size:
        raise KnowledgePipelineError(f"input changed while being read: {candidate}")
    return data


def _write_atomic(path: Path, text: str, *, force: bool) -> Path:
    """Atomically replace the named directory entry without following it.

    ``Path.resolve()`` is intentionally forbidden here: resolving an existing
    output symlink before the check would turn ``--force`` into an overwrite of
    the symlink target. ``os.replace`` replaces the final directory entry itself.
    """

    target = _absolute_without_resolving(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target_stat = target.lstat()
    except FileNotFoundError:
        target_stat = None
    if target_stat is not None:
        if stat.S_ISLNK(target_stat.st_mode):
            if not force:
                raise KnowledgePipelineError(
                    f"output is a symbolic link (pass --force to replace the link itself): {target}"
                )
        elif not force:
            raise KnowledgePipelineError(
                f"output already exists (pass --force to replace): {target}"
            )
        elif not stat.S_ISREG(target_stat.st_mode):
            raise KnowledgePipelineError(f"output is not a regular file: {target}")
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
    return target


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
    return parse_knowledge_corpus_json(
        _read_regular(Path(path)), f"knowledge corpus {path}"
    )


def _load_forest(path: str):
    return parse_knowledge_forest_json(
        _read_regular(Path(path)), f"knowledge forest {path}"
    )


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
            rel = safe_relpath(
                candidate.relative_to(root).as_posix(), "Obsidian Markdown path"
            )
            data = read_file(root, rel, max_bytes=max_file_bytes)
        except (ReferenceCompileError, ValueError) as exc:
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


def _emit(value: Any, args: argparse.Namespace, **summary: Any) -> int:
    text = value if isinstance(value, str) else canonical_json(value)
    target = _write_atomic(Path(args.output), text, force=args.force)
    print(canonical_json({"output": str(target), **summary}))
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
        args,
        schema=corpus.SCHEMA,
        corpus_sha256=corpus.digest,
        documents=len(corpus.documents),
        claims=len(corpus.claims),
    )


def _ingest_confluence(args: argparse.Namespace) -> int:
    payload = _load_json(args.input, "Confluence dump")
    if not isinstance(payload, dict):
        raise KnowledgePipelineError("Confluence dump must be an object")
    importer: Callable[..., Any] = (
        ingest_confluence_rest_dump if args.shape == "rest" else ingest_confluence_dump
    )
    if args.shape == "rest":
        corpus = importer(
            payload,
            instance_id=args.instance_id,
            imported_at=args.imported_at,
            default_authority=args.authority,
            default_access_class=args.access_class,
            corpus_id=args.corpus_id,
        )
    else:
        corpus = importer(
            payload,
            instance_id=args.instance_id,
            imported_at=args.imported_at,
            default_authority=args.authority,
            default_access_class=args.access_class,
            corpus_id=args.corpus_id,
        )
    return _emit(
        knowledge_corpus_json(corpus),
        args,
        schema=corpus.SCHEMA,
        corpus_sha256=corpus.digest,
        documents=len(corpus.documents),
        claims=len(corpus.claims),
    )


def _ingest_mediawiki(args: argparse.Namespace) -> int:
    if args.shape == "xml":
        corpus = ingest_mediawiki_xml_dump(
            args.input,
            instance_id=args.instance_id,
            imported_at=args.imported_at,
            authority=args.authority,
            access_class=args.access_class,
            corpus_id=args.corpus_id,
            limits=MediaWikiXMLLimits(
                max_selected_pages=args.max_selected_pages,
                max_page_text_bytes=args.max_page_text_bytes,
                max_total_text_bytes=args.max_total_bytes,
            ),
            namespace_ids=tuple(args.namespace),
            title_prefixes=tuple(args.title_prefix),
        )
    else:
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
        args,
        schema=corpus.SCHEMA,
        corpus_sha256=corpus.digest,
        documents=len(corpus.documents),
        claims=len(corpus.claims),
    )


def _combine(args: argparse.Namespace) -> int:
    corpora = tuple(_load_corpus(path) for path in args.input)
    corpus = combine_knowledge_corpora(args.corpus_id, *corpora)
    return _emit(
        knowledge_corpus_json(corpus),
        args,
        schema=corpus.SCHEMA,
        corpus_sha256=corpus.digest,
        documents=len(corpus.documents),
        claims=len(corpus.claims),
        inputs=len(corpora),
    )


def _correlate(args: argparse.Namespace) -> int:
    result = correlate_knowledge(
        snapshot=_load_snapshot(args.snapshot),
        forest=_load_forest(args.forest),
        corpus=_load_corpus(args.corpus),
        policy=CorrelationPolicy(
            min_proposal_score=args.min_score,
            max_proposals_per_claim=args.max_proposals_per_claim,
        ),
    )
    return _emit(
        result.to_dict(),
        args,
        schema=result.SCHEMA,
        result_sha256=result.digest,
        proposals=len(result.proposals),
        contradictions=len(result.contradictions),
        unresolved=len(result.unresolved),
    )


def _context(args: argparse.Namespace) -> int:
    snapshot = _load_snapshot(args.snapshot)
    forest = _load_forest(args.forest)
    corpus = _load_corpus(args.corpus)
    correlation_policy = CorrelationPolicy(
        min_proposal_score=args.min_score,
        max_proposals_per_claim=args.max_proposals_per_claim,
        max_context_bundles=args.max_context_bundles,
        external_background_in_context=not args.exclude_external_background,
    )
    result = correlate_knowledge(
        snapshot=snapshot,
        forest=forest,
        corpus=corpus,
        policy=correlation_policy,
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
        correlation_policy=correlation_policy,
    )
    return _emit(
        context.to_dict(),
        args,
        schema=context.SCHEMA,
        context_sha256=context.digest,
        bundles=len(context.capsule.bundles),
        withheld_claims=len(context.withheld_claim_sha256s),
    )


def _add_output(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", required=True)
    parser.add_argument("--force", action="store_true")


def _add_policy(
    parser: argparse.ArgumentParser,
    *,
    authority: str,
    access_class: str,
) -> None:
    parser.add_argument("--authority", choices=sorted(AUTHORITY_CLASSES), default=authority)
    parser.add_argument("--access-class", choices=sorted(ACCESS_CLASSES), default=access_class)
    parser.add_argument("--corpus-id")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m daedalus.twin.knowledge_pipeline",
        description="Offline external knowledge ingestion and Fourfold correlation.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    obsidian = sub.add_parser("ingest-obsidian")
    obsidian.add_argument("--root", required=True)
    obsidian.add_argument("--vault-id", required=True)
    obsidian.add_argument("--source-revision", required=True)
    obsidian.add_argument("--imported-at", required=True)
    obsidian.add_argument("--max-files", type=int, default=20_000)
    obsidian.add_argument("--max-file-bytes", type=int, default=DEFAULT_MARKDOWN_FILE_LIMIT)
    obsidian.add_argument("--max-total-bytes", type=int, default=100_000_000)
    _add_policy(obsidian, authority="personal_note", access_class="private")
    _add_output(obsidian)
    obsidian.set_defaults(handler=_ingest_obsidian)

    confluence = sub.add_parser("ingest-confluence")
    confluence.add_argument("--input", required=True)
    confluence.add_argument("--shape", choices=("normalized", "rest"), default="normalized")
    confluence.add_argument("--instance-id", required=True)
    confluence.add_argument("--imported-at", required=True)
    _add_policy(confluence, authority="project_documentation", access_class="internal")
    _add_output(confluence)
    confluence.set_defaults(handler=_ingest_confluence)

    mediawiki = sub.add_parser("ingest-mediawiki")
    mediawiki.add_argument("--input", required=True)
    mediawiki.add_argument("--shape", choices=("normalized", "xml"), default="normalized")
    mediawiki.add_argument("--instance-id", required=True)
    mediawiki.add_argument("--imported-at", required=True)
    mediawiki.add_argument("--namespace", action="append", type=int, default=[0])
    mediawiki.add_argument("--title-prefix", action="append", default=[])
    mediawiki.add_argument("--max-selected-pages", type=int, default=10_000)
    mediawiki.add_argument("--max-page-text-bytes", type=int, default=4_000_000)
    mediawiki.add_argument("--max-total-bytes", type=int, default=256_000_000)
    _add_policy(mediawiki, authority="external_reference", access_class="public")
    _add_output(mediawiki)
    mediawiki.set_defaults(handler=_ingest_mediawiki)

    combine = sub.add_parser("combine")
    combine.add_argument("--input", action="append", required=True)
    combine.add_argument("--corpus-id", required=True)
    _add_output(combine)
    combine.set_defaults(handler=_combine)

    for name, handler in (("correlate", _correlate), ("context", _context)):
        command = sub.add_parser(name)
        command.add_argument("--snapshot", required=True)
        command.add_argument("--forest", required=True)
        command.add_argument("--corpus", required=True)
        command.add_argument("--min-score", type=float, default=0.58)
        command.add_argument("--max-proposals-per-claim", type=int, default=12)
        if name == "context":
            command.add_argument("--objective", required=True)
            command.add_argument("--anchor", action="append", required=True)
            command.add_argument(
                "--allow-access",
                action="append",
                choices=sorted(ACCESS_CLASSES),
                default=None,
            )
            command.add_argument("--exclude-external-background", action="store_true")
            command.add_argument("--max-context-bundles", type=int, default=24)
        _add_output(command)
        command.set_defaults(handler=handler)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["KnowledgePipelineError", "build_parser", "main"]
