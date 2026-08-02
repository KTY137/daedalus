"""Deterministic ingestion contracts for external knowledge dumps.

The records in this module are a *non-authoritative overlay*.  They preserve
source identity, revision, access class and byte-level provenance so that
Confluence, Obsidian, MediaWiki and normalized document exports can be
correlated with a revision-bound :class:`FourfoldSnapshot` without silently
turning prose into verified project facts.

No connector performs network I/O here.  Callers export or fetch content behind
Daedalus' effect boundary and pass immutable bytes/records into these pure
normalizers.
"""
from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import hashlib
import re
from pathlib import PurePosixPath
from typing import Any, ClassVar, Mapping, Sequence

from ..spine.envelope import canonical_sha

SOURCE_SYSTEMS = frozenset({"confluence", "obsidian", "mediawiki", "normalized"})
AUTHORITY_CLASSES = frozenset(
    {
        "accepted_architecture",
        "project_requirement",
        "project_documentation",
        "repository_documentation",
        "operational_runbook",
        "personal_note",
        "external_reference",
        "generated_summary",
    }
)
PROJECT_AUTHORITY_CLASSES = frozenset(
    {
        "accepted_architecture",
        "project_requirement",
        "project_documentation",
        "repository_documentation",
        "operational_runbook",
    }
)
ACCESS_CLASSES = frozenset({"public", "internal", "restricted", "private"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:[.:#/][A-Za-z_][A-Za-z0-9_]*)+")
_BACKTICK_RE = re.compile(r"`([^`\n]+)`")
_MD_LINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)")
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|([^\]]+))?\]\]")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9`])")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_MEDIAWIKI_HEADING_RE = re.compile(r"^(={2,6})\s*(.+?)\s*\1\s*$")
_SAFE_KEY_RE = re.compile(r"[^a-zA-Z0-9._/-]+")


class KnowledgeIngestError(ValueError):
    """Raised when a knowledge dump is malformed or exceeds a hard boundary."""


def _text(value: Any, name: str, *, max_length: int = 200_000) -> str:
    if not isinstance(value, str):
        raise KnowledgeIngestError(f"{name} must be a string")
    result = value.strip()
    if not result:
        raise KnowledgeIngestError(f"{name} must not be empty")
    if "\x00" in result:
        raise KnowledgeIngestError(f"{name} contains a NUL byte")
    if len(result) > max_length:
        raise KnowledgeIngestError(f"{name} exceeds maximum length")
    return result


def _optional_text(value: Any, name: str, *, max_length: int = 200_000) -> str:
    if value in (None, ""):
        return ""
    return _text(value, name, max_length=max_length)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(value: Any, name: str) -> str:
    result = _text(value, name, max_length=64).lower()
    if not _SHA256_RE.fullmatch(result):
        raise KnowledgeIngestError(f"{name} must be lowercase sha256")
    return result


def _safe_key(value: Any, name: str) -> str:
    text = _text(value, name, max_length=1000).replace("\\", "/")
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts:
        raise KnowledgeIngestError(f"{name} must be a bounded relative key")
    normalized = path.as_posix()
    if normalized in {"", "."}:
        raise KnowledgeIngestError(f"{name} must not resolve to root")
    return normalized


def _stable_slug(value: str) -> str:
    lowered = _SAFE_KEY_RE.sub("-", value.strip().lower()).strip("-./")
    return lowered or hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _metadata(value: Mapping[str, Any] | None) -> tuple[tuple[str, str], ...]:
    if value is None:
        return ()
    if not isinstance(value, Mapping):
        raise KnowledgeIngestError("metadata must be an object")
    rows: list[tuple[str, str]] = []
    for key, item in value.items():
        k = _text(str(key), "metadata key", max_length=200)
        if isinstance(item, (str, int, float, bool)) or item is None:
            v = "" if item is None else str(item)
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
            v = ",".join(sorted(str(part) for part in item))
        else:
            raise KnowledgeIngestError(f"metadata[{k!r}] is not scalar")
        rows.append((k, v))
    if len({key for key, _ in rows}) != len(rows):
        raise KnowledgeIngestError("metadata keys must be unique")
    return tuple(sorted(rows))


def _aliases(values: Sequence[Any] | None) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes)):
        values = (values,)
    result = tuple(
        sorted(
            {
                _text(value, "alias", max_length=300)
                for value in values
                if isinstance(value, str) and value.strip()
            },
            key=str.casefold,
        )
    )
    return result


def _source_id(system: str, instance: str, item_key: str, revision: str) -> str:
    return f"{system}:{_stable_slug(instance)}:{_stable_slug(item_key)}@{_stable_slug(revision)}"


@dataclass(frozen=True)
class KnowledgeSource:
    """Exact origin of one imported document revision."""

    source_system: str
    source_instance: str
    source_item_key: str
    source_revision: str
    authority: str
    access_class: str
    imported_at: str
    content_sha256: str
    raw_artifact_locator: str = ""
    metadata: tuple[tuple[str, str], ...] = ()

    SCHEMA: ClassVar[str] = "daedalus-knowledge-source/1"

    def __post_init__(self) -> None:
        if self.source_system not in SOURCE_SYSTEMS:
            raise KnowledgeIngestError(
                f"source_system must be one of {sorted(SOURCE_SYSTEMS)}"
            )
        object.__setattr__(
            self, "source_instance", _text(self.source_instance, "source_instance", max_length=500)
        )
        object.__setattr__(
            self, "source_item_key", _safe_key(self.source_item_key, "source_item_key")
        )
        object.__setattr__(
            self, "source_revision", _text(self.source_revision, "source_revision", max_length=500)
        )
        if self.authority not in AUTHORITY_CLASSES:
            raise KnowledgeIngestError(
                f"authority must be one of {sorted(AUTHORITY_CLASSES)}"
            )
        if self.access_class not in ACCESS_CLASSES:
            raise KnowledgeIngestError(
                f"access_class must be one of {sorted(ACCESS_CLASSES)}"
            )
        object.__setattr__(self, "imported_at", _text(self.imported_at, "imported_at", max_length=100))
        object.__setattr__(
            self, "content_sha256", _sha256(self.content_sha256, "content_sha256")
        )
        if self.raw_artifact_locator:
            object.__setattr__(
                self,
                "raw_artifact_locator",
                _text(self.raw_artifact_locator, "raw_artifact_locator", max_length=2000),
            )
        if isinstance(self.metadata, Mapping):
            normalized_metadata = _metadata(self.metadata)
        else:
            rows = tuple((str(key), str(value)) for key, value in self.metadata)
            if len({key for key, _ in rows}) != len(rows):
                raise KnowledgeIngestError("metadata keys must be unique")
            normalized_metadata = tuple(
                sorted(
                    (
                        _text(key, "metadata key", max_length=200),
                        _optional_text(value, f"metadata[{key!r}]", max_length=5000),
                    )
                    for key, value in rows
                )
            )
        object.__setattr__(self, "metadata", normalized_metadata)

    @property
    def source_id(self) -> str:
        return _source_id(
            self.source_system,
            self.source_instance,
            self.source_item_key,
            self.source_revision,
        )

    @property
    def project_authoritative(self) -> bool:
        return self.authority in PROJECT_AUTHORITY_CLASSES

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "source_system": self.source_system,
            "source_instance": self.source_instance,
            "source_item_key": self.source_item_key,
            "source_revision": self.source_revision,
            "authority": self.authority,
            "access_class": self.access_class,
            "imported_at": self.imported_at,
            "content_sha256": self.content_sha256,
            "raw_artifact_locator": self.raw_artifact_locator,
            "metadata": [{"key": key, "value": value} for key, value in self.metadata],
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class KnowledgeSection:
    section_id: str
    heading_path: tuple[str, ...]
    ordinal: int
    line_start: int
    line_end: int
    text: str
    links: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "section_id", _text(self.section_id, "section_id", max_length=1000))
        object.__setattr__(
            self,
            "heading_path",
            tuple(_text(item, "heading", max_length=500) for item in self.heading_path),
        )
        if self.ordinal < 0 or self.line_start < 1 or self.line_end < self.line_start:
            raise KnowledgeIngestError("section ordinal/span is invalid")
        object.__setattr__(self, "text", _text(self.text, "section.text"))
        object.__setattr__(
            self,
            "links",
            tuple(sorted({_text(item, "section link", max_length=2000) for item in self.links})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "heading_path": list(self.heading_path),
            "ordinal": self.ordinal,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "text": self.text,
            "links": list(self.links),
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class KnowledgeClaim:
    claim_id: str
    document_id: str
    section_id: str
    ordinal: int
    line_start: int
    line_end: int
    text: str
    identifiers: tuple[str, ...]
    links: tuple[str, ...]
    source_sha256: str

    def __post_init__(self) -> None:
        for name in ("claim_id", "document_id", "section_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name, max_length=1500))
        if self.ordinal < 0 or self.line_start < 1 or self.line_end < self.line_start:
            raise KnowledgeIngestError("claim ordinal/span is invalid")
        object.__setattr__(self, "text", _text(self.text, "claim.text", max_length=20_000))
        object.__setattr__(
            self,
            "identifiers",
            tuple(sorted({_text(item, "identifier", max_length=1000) for item in self.identifiers})),
        )
        object.__setattr__(
            self,
            "links",
            tuple(sorted({_text(item, "claim link", max_length=2000) for item in self.links})),
        )
        object.__setattr__(self, "source_sha256", _sha256(self.source_sha256, "source_sha256"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "document_id": self.document_id,
            "section_id": self.section_id,
            "ordinal": self.ordinal,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "text": self.text,
            "identifiers": list(self.identifiers),
            "links": list(self.links),
            "source_sha256": self.source_sha256,
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class KnowledgeDocument:
    document_id: str
    source: KnowledgeSource
    title: str
    document_key: str
    aliases: tuple[str, ...]
    sections: tuple[KnowledgeSection, ...]
    claims: tuple[KnowledgeClaim, ...]

    SCHEMA: ClassVar[str] = "daedalus-knowledge-document/1"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "document_id", _text(self.document_id, "document_id", max_length=1500)
        )
        if not isinstance(self.source, KnowledgeSource):
            raise KnowledgeIngestError("source must be KnowledgeSource")
        object.__setattr__(self, "title", _text(self.title, "title", max_length=1000))
        object.__setattr__(self, "document_key", _safe_key(self.document_key, "document_key"))
        object.__setattr__(self, "aliases", _aliases(self.aliases))
        object.__setattr__(
            self, "sections", tuple(sorted(self.sections, key=lambda item: item.ordinal))
        )
        object.__setattr__(
            self, "claims", tuple(sorted(self.claims, key=lambda item: item.ordinal))
        )
        if len({section.section_id for section in self.sections}) != len(self.sections):
            raise KnowledgeIngestError("section ids must be unique")
        if len({claim.claim_id for claim in self.claims}) != len(self.claims):
            raise KnowledgeIngestError("claim ids must be unique")
        section_ids = {section.section_id for section in self.sections}
        for claim in self.claims:
            if claim.document_id != self.document_id or claim.section_id not in section_ids:
                raise KnowledgeIngestError("claim must belong to this document and section")
            if claim.source_sha256 != self.source.content_sha256:
                raise KnowledgeIngestError("claim source digest must match document source")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "document_id": self.document_id,
            "source": self.source.to_dict(),
            "title": self.title,
            "document_key": self.document_key,
            "aliases": list(self.aliases),
            "sections": [section.to_dict() for section in self.sections],
            "claims": [claim.to_dict() for claim in self.claims],
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class KnowledgeCorpus:
    corpus_id: str
    documents: tuple[KnowledgeDocument, ...]

    SCHEMA: ClassVar[str] = "daedalus-knowledge-corpus/1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "corpus_id", _text(self.corpus_id, "corpus_id", max_length=500))
        by_id: dict[str, KnowledgeDocument] = {}
        source_ids: set[str] = set()
        for document in self.documents:
            if not isinstance(document, KnowledgeDocument):
                raise KnowledgeIngestError("documents must contain KnowledgeDocument records")
            if document.document_id in by_id:
                raise KnowledgeIngestError("document ids must be unique")
            if document.source.source_id in source_ids:
                raise KnowledgeIngestError("source document revisions must be unique")
            by_id[document.document_id] = document
            source_ids.add(document.source.source_id)
        object.__setattr__(
            self, "documents", tuple(sorted(by_id.values(), key=lambda item: item.document_id))
        )

    @property
    def claims(self) -> tuple[KnowledgeClaim, ...]:
        return tuple(
            claim
            for document in self.documents
            for claim in document.claims
        )

    @property
    def document_map(self) -> Mapping[str, KnowledgeDocument]:
        return {document.document_id: document for document in self.documents}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "corpus_id": self.corpus_id,
            "documents": [document.to_dict() for document in self.documents],
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


class _BlockHTMLParser(HTMLParser):
    _BLOCK_TAGS = frozenset({"p", "li", "pre", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str, tuple[str, ...]]] = []
        self._tag = ""
        self._parts: list[str] = []
        self._links: list[str] = []
        self._href = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lower = tag.lower()
        if lower in self._BLOCK_TAGS:
            self._flush()
            self._tag = lower
        if lower == "a":
            self._href = next((value or "" for key, value in attrs if key.lower() == "href"), "")
        if lower == "code" and self._tag:
            self._parts.append("`")

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if lower == "a" and self._href:
            self._links.append(self._href)
            self._href = ""
        if lower == "code" and self._tag:
            self._parts.append("`")
        if lower == self._tag:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._tag:
            self._parts.append(data)

    def _flush(self) -> None:
        text = " ".join("".join(self._parts).split())
        if self._tag and text:
            self.blocks.append((self._tag, text, tuple(sorted(set(self._links)))))
        self._tag = ""
        self._parts = []
        self._links = []


def _frontmatter(text: str) -> tuple[dict[str, Any], str, int]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text, 0
    try:
        end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration:
        return {}, text, 0
    meta: dict[str, Any] = {}
    for line in lines[1:end]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip()
        if value.startswith("[") and value.endswith("]"):
            meta[key] = [part.strip(" '\"") for part in value[1:-1].split(",") if part.strip()]
        elif value:
            meta[key] = value.strip("'\"")
    return meta, "\n".join(lines[end + 1 :]), end + 1


def _claim_fragments(text: str) -> tuple[str, ...]:
    compact = " ".join(text.split())
    if not compact:
        return ()
    fragments = tuple(part.strip() for part in _SENTENCE_SPLIT_RE.split(compact) if part.strip())
    return fragments or (compact,)


def _extract_identifiers(text: str) -> tuple[str, ...]:
    values = set(_BACKTICK_RE.findall(text))
    values.update(_IDENTIFIER_RE.findall(text))
    return tuple(sorted(value.strip() for value in values if value.strip()))


def _extract_links(text: str) -> tuple[str, ...]:
    values = {target.strip() for _, target in _MD_LINK_RE.findall(text)}
    values.update(target.strip() for target, _ in _WIKILINK_RE.findall(text))
    return tuple(sorted(value for value in values if value))


def _build_document(
    *,
    system: str,
    instance: str,
    item_key: str,
    revision: str,
    title: str,
    raw_text: str,
    imported_at: str,
    source_bytes: bytes | None = None,
    authority: str,
    access_class: str,
    aliases: Sequence[str] = (),
    metadata: Mapping[str, Any] | None = None,
    raw_artifact_locator: str = "",
    line_offset: int = 0,
) -> KnowledgeDocument:
    content_bytes = source_bytes if source_bytes is not None else raw_text.encode("utf-8")
    content_sha = _sha256_bytes(content_bytes)
    source = KnowledgeSource(
        source_system=system,
        source_instance=instance,
        source_item_key=item_key,
        source_revision=revision,
        authority=authority,
        access_class=access_class,
        imported_at=imported_at,
        content_sha256=content_sha,
        raw_artifact_locator=raw_artifact_locator,
        metadata=_metadata(metadata),
    )
    document_id = f"knowledge:document:{source.source_id}"
    sections: list[KnowledgeSection] = []
    claims: list[KnowledgeClaim] = []
    heading_stack: list[str] = []
    current_lines: list[tuple[int, str]] = []
    current_links: set[str] = set()

    def flush() -> None:
        if not current_lines:
            return
        text = "\n".join(part for _, part in current_lines).strip()
        if not text:
            current_lines.clear()
            current_links.clear()
            return
        ordinal = len(sections)
        section_id = f"{document_id}#section-{ordinal}"
        section = KnowledgeSection(
            section_id=section_id,
            heading_path=tuple(heading_stack),
            ordinal=ordinal,
            line_start=current_lines[0][0],
            line_end=current_lines[-1][0],
            text=text,
            links=tuple(sorted(current_links)),
        )
        sections.append(section)
        for fragment in _claim_fragments(text):
            claim_ordinal = len(claims)
            claims.append(
                KnowledgeClaim(
                    claim_id=f"{document_id}#claim-{claim_ordinal}",
                    document_id=document_id,
                    section_id=section_id,
                    ordinal=claim_ordinal,
                    line_start=section.line_start,
                    line_end=section.line_end,
                    text=fragment,
                    identifiers=_extract_identifiers(fragment),
                    links=_extract_links(fragment),
                    source_sha256=content_sha,
                )
            )
        current_lines.clear()
        current_links.clear()

    in_fence = False
    for index, line in enumerate(raw_text.splitlines(), start=1 + line_offset):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        heading = _HEADING_RE.match(line)
        if heading:
            flush()
            level = len(heading.group(1))
            heading_stack[:] = heading_stack[: level - 1]
            heading_stack.append(heading.group(2).strip())
            continue
        if not stripped:
            flush()
            continue
        current_lines.append((index, stripped.lstrip("-*+ ").strip()))
        current_links.update(_extract_links(stripped))
    flush()
    if not sections:
        raise KnowledgeIngestError(f"knowledge document {item_key!r} contains no claims")
    return KnowledgeDocument(
        document_id=document_id,
        source=source,
        title=title,
        document_key=item_key,
        aliases=_aliases(aliases),
        sections=tuple(sections),
        claims=tuple(claims),
    )


def ingest_obsidian_vault(
    files: Mapping[str, str | bytes],
    *,
    vault_id: str,
    source_revision: str,
    imported_at: str,
    authority: str = "personal_note",
    access_class: str = "private",
    corpus_id: str | None = None,
    max_files: int = 20_000,
    max_total_bytes: int = 100_000_000,
) -> KnowledgeCorpus:
    """Normalize an already-exported Obsidian vault without network effects."""

    if not isinstance(files, Mapping):
        raise KnowledgeIngestError("files must be a mapping")
    if len(files) > max_files:
        raise KnowledgeIngestError("vault exceeds max_files")
    total = 0
    documents: list[KnowledgeDocument] = []
    seen_casefold: set[str] = set()
    for raw_path, value in sorted(files.items(), key=lambda item: str(item[0]).casefold()):
        path = _safe_key(raw_path, "obsidian path")
        if not path.lower().endswith(".md"):
            continue
        folded = path.casefold()
        if folded in seen_casefold:
            raise KnowledgeIngestError("case-insensitive Obsidian path collision")
        seen_casefold.add(folded)
        data = value if isinstance(value, bytes) else str(value).encode("utf-8")
        total += len(data)
        if total > max_total_bytes:
            raise KnowledgeIngestError("vault exceeds max_total_bytes")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise KnowledgeIngestError(f"Obsidian file is not UTF-8: {path}") from exc
        meta, body, offset = _frontmatter(text)
        aliases_value = meta.get("aliases", ())
        if isinstance(aliases_value, str):
            aliases_value = (aliases_value,)
        title = str(meta.get("title") or PurePosixPath(path).stem)
        documents.append(
            _build_document(
                system="obsidian",
                instance=vault_id,
                item_key=path,
                revision=source_revision,
                title=title,
                raw_text=body,
                imported_at=imported_at,
                source_bytes=data,
                authority=authority,
                access_class=access_class,
                aliases=tuple(aliases_value),
                metadata=meta,
                line_offset=offset,
            )
        )
    return KnowledgeCorpus(
        corpus_id=corpus_id or f"obsidian:{_stable_slug(vault_id)}@{_stable_slug(source_revision)}",
        documents=tuple(documents),
    )


def ingest_confluence_dump(
    payload: Mapping[str, Any],
    *,
    instance_id: str,
    imported_at: str,
    default_authority: str = "project_documentation",
    default_access_class: str = "internal",
    corpus_id: str | None = None,
) -> KnowledgeCorpus:
    """Normalize a bounded JSON export of Confluence pages.

    Expected schema::

        {
          "schema": "daedalus-confluence-dump/1",
          "pages": [{
            "page_id": "123", "version": 7, "title": "...",
            "space_key": "ENG", "body_storage": "<p>...</p>",
            "labels": ["..."], "authority": "project_documentation"
          }]
        }
    """

    if payload.get("schema") != "daedalus-confluence-dump/1":
        raise KnowledgeIngestError("unsupported Confluence dump schema")
    pages = payload.get("pages")
    if isinstance(pages, (str, bytes)) or not isinstance(pages, Sequence):
        raise KnowledgeIngestError("Confluence pages must be a sequence")
    documents: list[KnowledgeDocument] = []
    for index, page in enumerate(pages):
        if not isinstance(page, Mapping):
            raise KnowledgeIngestError(f"Confluence page {index} must be an object")
        page_id = _text(str(page.get("page_id", "")), "page_id", max_length=200)
        version = _text(str(page.get("version", "")), "version", max_length=100)
        title = _text(page.get("title"), "title", max_length=1000)
        space = _text(str(page.get("space_key", "default")), "space_key", max_length=200)
        body_storage = _text(page.get("body_storage"), "body_storage")
        parser = _BlockHTMLParser()
        parser.feed(body_storage)
        lines: list[str] = []
        for tag, text, links in parser.blocks:
            if tag.startswith("h") and len(tag) == 2 and tag[1].isdigit():
                lines.append(f"{'#' * min(int(tag[1]), 6)} {text}")
            else:
                suffix = " " + " ".join(f"[source]({link})" for link in links) if links else ""
                lines.append(text + suffix)
                lines.append("")
        normalized = "\n".join(lines).strip()
        if not normalized:
            raise KnowledgeIngestError(f"Confluence page {page_id} contains no textual blocks")
        labels = page.get("labels", ())
        aliases = tuple(labels) if isinstance(labels, Sequence) and not isinstance(labels, (str, bytes)) else ()
        item_key = f"{space}/{page_id}"
        documents.append(
            _build_document(
                system="confluence",
                instance=instance_id,
                item_key=item_key,
                revision=version,
                title=title,
                raw_text=normalized,
                imported_at=imported_at,
                source_bytes=body_storage.encode("utf-8"),
                authority=str(page.get("authority") or default_authority),
                access_class=str(page.get("access_class") or default_access_class),
                aliases=aliases,
                metadata={
                    "space_key": space,
                    "page_id": page_id,
                    "version": version,
                    "labels": aliases,
                },
                raw_artifact_locator=str(page.get("raw_artifact_locator") or ""),
            )
        )
    return KnowledgeCorpus(
        corpus_id=corpus_id or f"confluence:{_stable_slug(instance_id)}",
        documents=tuple(documents),
    )


def _mediawiki_to_markdown(wikitext: str) -> str:
    output: list[str] = []
    in_nowiki = False
    for line in wikitext.splitlines():
        stripped = line.strip()
        if "<nowiki>" in stripped:
            in_nowiki = True
        if "</nowiki>" in stripped:
            in_nowiki = False
            continue
        if in_nowiki:
            continue
        heading = _MEDIAWIKI_HEADING_RE.match(stripped)
        if heading:
            level = max(1, min(6, len(heading.group(1)) - 1))
            output.append(f"{'#' * level} {heading.group(2).strip()}")
            continue
        line = re.sub(
            r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|([^\]]+))?\]\]",
            lambda match: f"[{match.group(2) or match.group(1)}](mediawiki:{match.group(1).strip()})",
            line,
        )
        line = re.sub(r"\{\{[^{}]*\}\}", "", line)
        line = re.sub(r"'{2,5}", "", line)
        output.append(line)
    return "\n".join(output)


def ingest_mediawiki_dump(
    payload: Mapping[str, Any],
    *,
    instance_id: str,
    imported_at: str,
    authority: str = "external_reference",
    access_class: str = "public",
    corpus_id: str | None = None,
) -> KnowledgeCorpus:
    """Normalize a bounded JSON projection of MediaWiki page revisions."""

    if payload.get("schema") != "daedalus-mediawiki-dump/1":
        raise KnowledgeIngestError("unsupported MediaWiki dump schema")
    pages = payload.get("pages")
    if isinstance(pages, (str, bytes)) or not isinstance(pages, Sequence):
        raise KnowledgeIngestError("MediaWiki pages must be a sequence")
    documents: list[KnowledgeDocument] = []
    for index, page in enumerate(pages):
        if not isinstance(page, Mapping):
            raise KnowledgeIngestError(f"MediaWiki page {index} must be an object")
        page_id = _text(str(page.get("page_id", "")), "page_id", max_length=200)
        revision_id = _text(str(page.get("revision_id", "")), "revision_id", max_length=200)
        title = _text(page.get("title"), "title", max_length=1000)
        wikitext = _text(page.get("wikitext"), "wikitext")
        documents.append(
            _build_document(
                system="mediawiki",
                instance=instance_id,
                item_key=f"page/{page_id}",
                revision=revision_id,
                title=title,
                raw_text=_mediawiki_to_markdown(wikitext),
                imported_at=imported_at,
                source_bytes=wikitext.encode("utf-8"),
                authority=authority,
                access_class=access_class,
                aliases=tuple(page.get("redirect_titles") or ()),
                metadata={
                    "page_id": page_id,
                    "revision_id": revision_id,
                    "categories": tuple(page.get("categories") or ()),
                },
                raw_artifact_locator=str(page.get("raw_artifact_locator") or ""),
            )
        )
    return KnowledgeCorpus(
        corpus_id=corpus_id or f"mediawiki:{_stable_slug(instance_id)}",
        documents=tuple(documents),
    )


def combine_knowledge_corpora(
    corpus_id: str,
    *corpora: KnowledgeCorpus,
) -> KnowledgeCorpus:
    """Combine corpora while preserving every source revision independently."""

    return KnowledgeCorpus(
        corpus_id=corpus_id,
        documents=tuple(document for corpus in corpora for document in corpus.documents),
    )


__all__ = [
    "ACCESS_CLASSES",
    "AUTHORITY_CLASSES",
    "PROJECT_AUTHORITY_CLASSES",
    "KnowledgeClaim",
    "KnowledgeCorpus",
    "KnowledgeDocument",
    "KnowledgeIngestError",
    "KnowledgeSection",
    "KnowledgeSource",
    "combine_knowledge_corpora",
    "ingest_confluence_dump",
    "ingest_mediawiki_dump",
    "ingest_obsidian_vault",
]
