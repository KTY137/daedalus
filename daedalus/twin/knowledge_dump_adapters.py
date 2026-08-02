"""Adapters for common external knowledge export shapes.

The canonical importers consume deliberately small normalized payloads.  This
module translates real-world export formats into those payloads without
changing their authority semantics:

* Atlassian Confluence REST search/page responses;
* Confluence HTML export directories represented as immutable file mappings;
* streaming MediaWiki XML or bzip2 XML dumps.

A full Wikipedia dump is far too large to become one in-memory Fourfold
KnowledgeCorpus.  The XML adapter therefore requires hard page/byte bounds and
supports title-prefix filtering.  Rejected or unselected pages make no claims.
"""
from __future__ import annotations

import bz2
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
import re
import stat
from typing import Any, BinaryIO, Mapping, Sequence
import xml.etree.ElementTree as ET

from .knowledge_sources import (
    KnowledgeCorpus,
    KnowledgeIngestError,
    combine_knowledge_corpora,
    ingest_confluence_dump,
    ingest_mediawiki_dump,
)


class KnowledgeDumpAdapterError(ValueError):
    """Raised when an external export shape is ambiguous or unsafe."""


@dataclass(frozen=True)
class MediaWikiXMLLimits:
    max_selected_pages: int = 10_000
    max_page_text_bytes: int = 4_000_000
    max_total_text_bytes: int = 256_000_000

    def __post_init__(self) -> None:
        for name, value in self.__dict__.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise KnowledgeDumpAdapterError(f"{name} must be a positive integer")


class _TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_title = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.parts.append(data)

    @property
    def title(self) -> str:
        return " ".join("".join(self.parts).split())


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise KnowledgeDumpAdapterError(f"{label} must be an object")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise KnowledgeDumpAdapterError(f"{label} must be a sequence")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise KnowledgeDumpAdapterError(f"{label} must be a non-empty string")
    return value.strip()


def _nested(payload: Mapping[str, Any], *keys: str) -> Any:
    value: Any = payload
    for key in keys:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _confluence_labels(page: Mapping[str, Any]) -> tuple[str, ...]:
    candidates = (
        _nested(page, "metadata", "labels", "results"),
        _nested(page, "labels", "results"),
        page.get("labels"),
    )
    for candidate in candidates:
        if candidate is None:
            continue
        if isinstance(candidate, Mapping):
            candidate = candidate.get("results")
        if isinstance(candidate, Sequence) and not isinstance(candidate, (str, bytes)):
            labels: set[str] = set()
            for value in candidate:
                if isinstance(value, Mapping):
                    raw = value.get("name") or value.get("label") or value.get("id")
                else:
                    raw = value
                if isinstance(raw, str) and raw.strip():
                    labels.add(raw.strip())
            return tuple(sorted(labels, key=str.casefold))
    return ()


def authority_from_confluence_labels(
    labels: Sequence[str],
    *,
    default: str = "project_documentation",
) -> str:
    """Map explicit governance labels to the small canonical authority set."""

    lowered = {label.casefold().replace("_", "-") for label in labels}
    if lowered.intersection({"adr", "accepted-architecture", "architecture-decision"}):
        return "accepted_architecture"
    if lowered.intersection({"requirement", "requirements", "normative"}):
        return "project_requirement"
    if lowered.intersection({"runbook", "operations", "operational-runbook"}):
        return "operational_runbook"
    return default


def normalize_confluence_rest_payload(
    payload: Mapping[str, Any],
    *,
    default_authority: str = "project_documentation",
    default_access_class: str = "internal",
) -> dict[str, Any]:
    """Normalize Confluence Cloud/Server REST page results.

    Supported input is either one page object or an object with ``results``.
    Every page must carry exact id, title, version and storage-format body.
    Pagination is not hidden: callers must collect every requested REST page
    before calling this pure normalizer.
    """

    root = _mapping(payload, "Confluence REST payload")
    raw_results = root.get("results")
    pages = (
        _sequence(raw_results, "Confluence REST results")
        if raw_results is not None
        else (root,)
    )
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, raw in enumerate(pages):
        page = _mapping(raw, f"Confluence page[{index}]")
        page_id = _text(str(page.get("id") or page.get("page_id") or ""), "page id")
        title = _text(page.get("title"), "page title")
        version_raw = _nested(page, "version", "number") or page.get("version")
        version = _text(str(version_raw or ""), "page version")
        body = (
            _nested(page, "body", "storage", "value")
            or page.get("body_storage")
            or _nested(page, "body", "view", "value")
        )
        body_storage = _text(body, "page storage body")
        space = (
            _nested(page, "space", "key")
            or page.get("space_key")
            or _nested(page, "space", "id")
            or "default"
        )
        space_key = _text(str(space), "space key")
        key = (page_id, version)
        if key in seen:
            raise KnowledgeDumpAdapterError(
                f"duplicate Confluence page revision: {page_id}@{version}"
            )
        seen.add(key)
        labels = _confluence_labels(page)
        normalized.append(
            {
                "page_id": page_id,
                "version": version,
                "title": title,
                "space_key": space_key,
                "body_storage": body_storage,
                "labels": list(labels),
                "authority": str(
                    page.get("authority")
                    or authority_from_confluence_labels(
                        labels, default=default_authority
                    )
                ),
                "access_class": str(
                    page.get("access_class") or default_access_class
                ),
                "raw_artifact_locator": str(
                    page.get("raw_artifact_locator") or ""
                ),
            }
        )
    return {
        "schema": "daedalus-confluence-dump/1",
        "pages": normalized,
    }


def ingest_confluence_rest_dump(
    payload: Mapping[str, Any],
    *,
    instance_id: str,
    imported_at: str,
    default_authority: str = "project_documentation",
    default_access_class: str = "internal",
    corpus_id: str | None = None,
) -> KnowledgeCorpus:
    normalized = normalize_confluence_rest_payload(
        payload,
        default_authority=default_authority,
        default_access_class=default_access_class,
    )
    return ingest_confluence_dump(
        normalized,
        instance_id=instance_id,
        imported_at=imported_at,
        default_authority=default_authority,
        default_access_class=default_access_class,
        corpus_id=corpus_id,
    )


def ingest_confluence_html_export(
    files: Mapping[str, str | bytes],
    *,
    instance_id: str,
    export_revision: str,
    imported_at: str,
    authority: str = "project_documentation",
    access_class: str = "internal",
    corpus_id: str | None = None,
    max_files: int = 20_000,
    max_total_bytes: int = 256_000_000,
) -> KnowledgeCorpus:
    """Ingest an already-read Confluence HTML export directory."""

    if not isinstance(files, Mapping):
        raise KnowledgeDumpAdapterError("Confluence HTML files must be a mapping")
    if len(files) > max_files:
        raise KnowledgeDumpAdapterError("Confluence HTML export exceeds max_files")
    pages: list[dict[str, Any]] = []
    total = 0
    casefold_paths: set[str] = set()
    for index, (raw_path, raw_value) in enumerate(
        sorted(files.items(), key=lambda item: str(item[0]).casefold())
    ):
        path = str(raw_path).replace("\\", "/").strip("/")
        if not path or path.startswith("../") or "/../" in path or not path.lower().endswith(('.html', '.htm')):
            continue
        folded = path.casefold()
        if folded in casefold_paths:
            raise KnowledgeDumpAdapterError("case-insensitive Confluence HTML path collision")
        casefold_paths.add(folded)
        data = raw_value if isinstance(raw_value, bytes) else str(raw_value).encode("utf-8")
        total += len(data)
        if total > max_total_bytes:
            raise KnowledgeDumpAdapterError("Confluence HTML export exceeds max_total_bytes")
        try:
            body = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise KnowledgeDumpAdapterError(f"Confluence HTML is not UTF-8: {path}") from exc
        parser = _TitleParser()
        parser.feed(body)
        title = parser.title or Path(path).stem
        pages.append(
            {
                "page_id": path,
                "version": export_revision,
                "title": title,
                "space_key": "html-export",
                "body_storage": body,
                "labels": [],
                "authority": authority,
                "access_class": access_class,
                "raw_artifact_locator": "",
            }
        )
    if not pages:
        raise KnowledgeDumpAdapterError("Confluence HTML export contains no HTML pages")
    return ingest_confluence_dump(
        {"schema": "daedalus-confluence-dump/1", "pages": pages},
        instance_id=instance_id,
        imported_at=imported_at,
        default_authority=authority,
        default_access_class=access_class,
        corpus_id=corpus_id,
    )


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(element: ET.Element, name: str) -> str:
    for child in element:
        if _local_name(child.tag) == name:
            return child.text or ""
    return ""


def _open_mediawiki(path: Path) -> BinaryIO:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as exc:
        raise KnowledgeDumpAdapterError(f"MediaWiki dump is missing: {path}") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise KnowledgeDumpAdapterError("MediaWiki dump must be a regular non-symlink file")
    return bz2.open(path, "rb") if path.suffix.casefold() == ".bz2" else path.open("rb")


def _reject_unsafe_xml(path: Path) -> None:
    with _open_mediawiki(path) as handle:
        prefix = handle.read(131_072).upper()
    if b"<!DOCTYPE" in prefix or b"<!ENTITY" in prefix:
        raise KnowledgeDumpAdapterError("MediaWiki XML with DTD/entities is refused")


def ingest_mediawiki_xml_dump(
    path: str | Path,
    *,
    instance_id: str,
    imported_at: str,
    authority: str = "external_reference",
    access_class: str = "public",
    corpus_id: str | None = None,
    limits: MediaWikiXMLLimits = MediaWikiXMLLimits(),
    namespace_ids: Sequence[int] = (0,),
    title_prefixes: Sequence[str] = (),
) -> KnowledgeCorpus:
    """Stream selected latest page revisions from MediaWiki XML/XML.bz2."""

    source = Path(path)
    _reject_unsafe_xml(source)
    allowed_namespaces = {int(value) for value in namespace_ids}
    prefixes = tuple(prefix.casefold() for prefix in title_prefixes if prefix.strip())
    documents = []
    selected = 0
    total_bytes = 0
    try:
        with _open_mediawiki(source) as handle:
            for event, element in ET.iterparse(handle, events=("end",)):
                if _local_name(element.tag) != "page":
                    continue
                title = _child_text(element, "title").strip()
                namespace_raw = _child_text(element, "ns").strip() or "0"
                page_id = ""
                revision_id = ""
                timestamp = ""
                text = ""
                redirect_titles: list[str] = []
                for child in element:
                    name = _local_name(child.tag)
                    if name == "id" and not page_id:
                        page_id = (child.text or "").strip()
                    elif name == "redirect":
                        target = child.attrib.get("title")
                        if target:
                            redirect_titles.append(target)
                    elif name == "revision":
                        for nested in child:
                            nested_name = _local_name(nested.tag)
                            if nested_name == "id":
                                revision_id = (nested.text or "").strip()
                            elif nested_name == "timestamp":
                                timestamp = (nested.text or "").strip()
                            elif nested_name == "text":
                                text = nested.text or ""
                try:
                    namespace_id = int(namespace_raw)
                except ValueError as exc:
                    raise KnowledgeDumpAdapterError(
                        f"invalid MediaWiki namespace id for {title!r}"
                    ) from exc
                selected_by_title = not prefixes or title.casefold().startswith(prefixes)
                if namespace_id in allowed_namespaces and selected_by_title and text:
                    encoded = text.encode("utf-8")
                    if len(encoded) > limits.max_page_text_bytes:
                        raise KnowledgeDumpAdapterError(
                            f"MediaWiki page exceeds max_page_text_bytes: {title!r}"
                        )
                    total_bytes += len(encoded)
                    if total_bytes > limits.max_total_text_bytes:
                        raise KnowledgeDumpAdapterError(
                            "MediaWiki selection exceeds max_total_text_bytes"
                        )
                    selected += 1
                    if selected > limits.max_selected_pages:
                        raise KnowledgeDumpAdapterError(
                            "MediaWiki selection exceeds max_selected_pages"
                        )
                    normalized = {
                        "schema": "daedalus-mediawiki-dump/1",
                        "pages": [
                            {
                                "page_id": _text(page_id, "MediaWiki page id"),
                                "revision_id": _text(revision_id, "MediaWiki revision id"),
                                "title": _text(title, "MediaWiki title"),
                                "wikitext": text,
                                "redirect_titles": redirect_titles,
                                "categories": [],
                                "raw_artifact_locator": "",
                                "timestamp": timestamp,
                            }
                        ],
                    }
                    page_corpus = ingest_mediawiki_dump(
                        normalized,
                        instance_id=instance_id,
                        imported_at=imported_at,
                        authority=authority,
                        access_class=access_class,
                        corpus_id=f"mediawiki-page:{page_id}@{revision_id}",
                    )
                    documents.extend(page_corpus.documents)
                element.clear()
    except ET.ParseError as exc:
        raise KnowledgeDumpAdapterError(f"MediaWiki XML parse failed: {exc}") from exc
    except KnowledgeIngestError as exc:
        raise KnowledgeDumpAdapterError(str(exc)) from exc
    if not documents:
        raise KnowledgeDumpAdapterError("MediaWiki filters selected no page revisions")
    return KnowledgeCorpus(
        corpus_id=corpus_id or f"mediawiki:{instance_id}:{source.name}",
        documents=tuple(documents),
    )


__all__ = [
    "KnowledgeDumpAdapterError",
    "MediaWikiXMLLimits",
    "authority_from_confluence_labels",
    "ingest_confluence_html_export",
    "ingest_confluence_rest_dump",
    "ingest_mediawiki_xml_dump",
    "normalize_confluence_rest_payload",
]
