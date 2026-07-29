"""markdown — DOCUMENTS as a StructCore node kind (a second PARSER, not a
second architecture).

``forest.py`` already promises this extension point verbatim: "Symbols, build
targets, documents, schemas, runtime spans, and domain entities can be added as
new node kinds and relation layers without changing this contract."  This module
is the parser half of that promise for Markdown.

THE DEFECT THIS EXISTS TO FIX (measured). ``build_index`` knew 19 programming
languages and zero document formats.  Asked to plan context for a task specified
entirely in a 3592-line Markdown architecture document, the planner selected
three TypeScript files -- the specification was not merely ranked low, it was
structurally invisible.  A distiller cannot distil what it does not index.

THE ANALOGY, STATED ONCE
------------------------
=====================  ======================================================
code                   document
=====================  ======================================================
module -> class -> fn  H1 -> H2 -> H3   (heading levels are a real tree)
a function             a SECTION: heading + body up to the next heading of
                       EQUAL OR HIGHER level (so an H2 contains its H3s,
                       exactly as a Python function contains its nested defs)
``import x``           an intra-repo link ``[text](path)`` / ``(path#anchor)``
a signature            the heading line
a body                 prose  -> dropped by the skeleton, and SAID SO
=====================  ======================================================

Off-repo URLs (``https://``, ``mailto:``) are deliberately NOT edges.  An edge
asserts a relation between two nodes in THIS forest; a link to the outside world
has no second node, so it is carried as an attribute and counted, never faked
into an edge that points at nothing.

WHAT THIS PARSER REFUSES TO DO
------------------------------
* It does not guess.  A link that does not resolve to a file actually present in
  the file set is DROPPED and COUNTED, never bound to a near-match.  Same rule
  ``index.py`` already applies to non-Python imports.
* It does not produce a "distilled" view larger than its input.  ``document_
  skeleton`` guarantees ``len(result) <= len(text)`` by construction, degrading
  through a fixed ladder and finally returning the raw document with
  ``distilled=False`` rather than shipping a lie.  (The same invariant
  ``tests/test_room_wiring.py::test_no_file_is_ever_inlined_larger_than_its_own_body``
  pins for code.)
* It does not run over anything the egress gate has not cleared.  This module
  never reads a file; callers pass text they have already gated.  See
  ``slice.py``, where every emitted document goes through the identical
  ``sensitivity.slice_egress_rule`` call as a source file.
"""
from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from urllib.parse import unquote

# Bump when the MEANING of a parse changes (new heading form, different section
# boundary, changed link resolution). Mirrors ``perfile.ANALYSIS_VERSION``'s
# role; carried in the index so a stale consumer is detectable rather than
# silently wrong.
DOCUMENT_PARSE_VERSION = "1"

MAX_HEADING_LEVEL = 6

# THE DISCRIMINATOR. A document lives in ``index["modules"]`` alongside source
# files -- it genuinely is a file in the repo, it genuinely participates in the
# link graph, and every consumer that joins on ``modules`` (the DSS hierarchy,
# the lexical seed, the slice scope boundary) needs it there or the planner
# stays blind to it, which is the whole defect. What it must NEVER do is
# masquerade as code, so its entry carries ``kind: "document"`` and every
# code-only consumer filters on exactly this key. Absence means source file, so
# an index built without documents is byte-identical to before.
DOCUMENT_KIND = "document"


def is_document(attributes) -> bool:
    """True if a ``modules`` entry describes a document rather than source."""
    try:
        return attributes.get("kind") == DOCUMENT_KIND
    except AttributeError:
        return False


def code_modules(index) -> dict:
    """``index["modules"]`` with documents removed.

    The single helper every code-only consumer inside structcore uses, so
    "documents are not code" is expressed once instead of re-derived at each
    site (``score_modules``, ``graph._graph_nodes``, ``churn.temporal_misses``).
    """
    modules = index.get("modules") or {}
    return {rel: attrs for rel, attrs in modules.items() if not is_document(attrs)}


def document_modules(index) -> dict:
    """``index["modules"]`` restricted to documents."""
    modules = index.get("modules") or {}
    return {rel: attrs for rel, attrs in modules.items() if is_document(attrs)}


# --------------------------------------------------------------------------- #
# Data                                                                          #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class DocSection:
    """One section: a heading plus its body, up to the next heading of equal or
    higher level.  The document analogue of ``parse.CodeUnit`` -- and DELIBERATELY
    field-compatible with it (``module``/``name``/``line``/``end_line``/``loc``/
    ``source``/``language``) so a document can be handed to code that already
    accepts units (``graph.build_resolver``, ``slice``'s symbol lookup) without
    those call sites growing a type switch.

    ``level`` 0 is the PREAMBLE -- the text before the first heading, i.e. the
    analogue of module-level code.  A document with no headings at all has
    exactly one section, which is the honest answer rather than zero.
    """

    module: str                    # rel path of the document
    name: str                      # heading text (the "signature")
    line: int                      # 1-based
    end_line: int
    loc: int
    source: str
    level: int = 0
    anchor: str = ""
    path: tuple[str, ...] = ()     # ancestor heading titles, outermost first
    language: str = "markdown"

    @property
    def document(self) -> str:
        return self.module


@dataclass(frozen=True)
class DocLink:
    """One link occurrence. ``href`` is the raw destination as written."""

    href: str
    line: int
    kind: str                      # "path" | "external" | "anchor"
    path: str = ""                 # link path, document-relative, before resolution
    anchor: str = ""


@dataclass(frozen=True)
class DocumentParse:
    document: str
    title: str
    sections: tuple[DocSection, ...] = ()
    links: tuple[DocLink, ...] = ()
    loc: int = 0
    n_chars: int = 0

    @property
    def headings(self) -> tuple[DocSection, ...]:
        return tuple(s for s in self.sections if s.level > 0)

    @property
    def max_depth(self) -> int:
        return max((s.level for s in self.sections), default=0)

    @property
    def external_links(self) -> tuple[str, ...]:
        return tuple(l.href for l in self.links if l.kind == "external")

    @property
    def path_links(self) -> tuple[DocLink, ...]:
        return tuple(l for l in self.links if l.kind == "path")


# --------------------------------------------------------------------------- #
# Lexing: fences, front matter, headings                                        #
# --------------------------------------------------------------------------- #
# CommonMark: 1-6 '#' at up to 3 columns of indent, then EITHER end-of-line OR
# whitespace. The whitespace requirement is load-bearing -- "#hashtag" and
# "#!/bin/sh" are NOT headings, and treating them as one fabricates structure.
_ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
# A closing sequence of '#'s is decoration, not part of the title.
_ATX_CLOSE = re.compile(r"[ \t]+#+[ \t]*$")
_SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_FRONT_MATTER = re.compile(r"^(---|\+\+\+)[ \t]*$")
# Lines that can never be a setext heading's TEXT. Without this, a table
# separator or a list item followed by a '---' rule becomes a fabricated H2.
_NOT_SETEXT_TEXT = re.compile(r"^ {0,3}(?:[-*+][ \t]|\d+[.)][ \t]|>|\||#)")

_INLINE_CODE = re.compile(r"`+[^`\n]*`+")
# Inline link, image-excluded. The (?<!\\!) guard keeps "![alt](img.png)" out:
# an image is an asset reference, not a document-to-document relation.
_INLINE_LINK = re.compile(
    r"(?<!!)\[(?:[^\[\]]|\\.)*\]\([ \t]*"
    r"(<[^<>\n]*>|[^()\s]*)"
    r"(?:[ \t]+(?:\"[^\"\n]*\"|'[^'\n]*'|\([^()\n]*\)))?[ \t]*\)"
)
# Reference DEFINITION: "[label]: dest".  Definitions are counted as links of the
# document because that is what they are -- a declared destination.  Matching
# every reference USAGE back to its label is deliberately not attempted: it would
# double-count the same destination and buys no new edge.
_REF_DEF = re.compile(r"^ {0,3}\[[^\]\n]+\]:[ \t]*(<[^<>\n]*>|\S+)")
# Bare autolink <https://...>; carried so external link COUNTS are honest.
_AUTOLINK = re.compile(r"<([A-Za-z][A-Za-z0-9+.\-]*:[^<>\s]*)>")

_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")
_SLUG_STRIP = re.compile(r"[^a-z0-9 _\-]")
# Inline markdown that GitHub strips before slugging a heading.
_MD_LINK_TEXT = re.compile(r"\[([^\]\n]*)\]\([^)\n]*\)")
_MD_EMPHASIS = re.compile(r"[*_~`]")


def _strip_front_matter(lines: list[str]) -> int:
    """Index of the first content line, skipping YAML/TOML front matter."""
    if not lines:
        return 0
    opener = _FRONT_MATTER.match(lines[0])
    if not opener:
        return 0
    marker = opener.group(1)
    for i in range(1, len(lines)):
        if lines[i].rstrip() == marker or (marker == "---" and lines[i].rstrip() == "..."):
            return i + 1
    # Unterminated front matter: treat the '---' as a thematic rule and parse the
    # whole file, rather than swallowing the document silently.
    return 0


def slugify(title: str) -> str:
    """GitHub-style anchor slug for a heading (no de-duplication)."""
    text = _MD_LINK_TEXT.sub(r"\1", title)
    text = _MD_EMPHASIS.sub("", text).strip().lower()
    text = _SLUG_STRIP.sub("", text)
    return re.sub(r"[ \t]+", "-", text).strip("-")


def _headings(lines: list[str], start: int) -> list[tuple[int, int, str]]:
    """(line_index, level, title) for every heading, in document order.

    Fenced code is skipped: a '#' comment inside a ``` block is Python, not an
    H1, and indexing it would put shell/Python comments into the heading tree.
    """
    out: list[tuple[int, int, str]] = []
    fence: tuple[str, int] | None = None
    for i in range(start, len(lines)):
        raw = lines[i]
        fence_hit = _FENCE.match(raw)
        if fence is not None:
            if fence_hit:
                char, length = fence
                got = fence_hit.group(1)
                if got[0] == char and len(got) >= length and not fence_hit.group(2).strip():
                    fence = None
            continue
        if fence_hit:
            fence = (fence_hit.group(1)[0], len(fence_hit.group(1)))
            continue
        atx = _ATX.match(raw)
        if atx:
            title = _ATX_CLOSE.sub("", (atx.group(2) or "")).strip()
            out.append((i, len(atx.group(1)), title))
            continue
        setext = _SETEXT.match(raw)
        if setext and i > start:
            prev = lines[i - 1]
            if prev.strip() and not _NOT_SETEXT_TEXT.match(prev) and not _SETEXT.match(prev):
                # The heading is the PREVIOUS line; if it was already claimed by
                # an ATX match this rule does not fire (ATX is checked first and
                # would have consumed it).
                if not out or out[-1][0] != i - 1:
                    out.append((i - 1, 1 if setext.group(1)[0] == "=" else 2, prev.strip()))
    return out


def _dedup_anchors(titles: list[str]) -> list[str]:
    """GitHub's duplicate-anchor rule: first wins, later ones get -1, -2, ..."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for title in titles:
        base = slugify(title)
        n = seen.get(base, 0)
        seen[base] = n + 1
        out.append(base if n == 0 else f"{base}-{n}")
    return out


# --------------------------------------------------------------------------- #
# Links                                                                         #
# --------------------------------------------------------------------------- #
def _classify(href: str) -> DocLink | None:
    """Classify one raw destination. Returns None for something that is not a
    link at all (empty destination)."""
    dest = href.strip()
    if dest.startswith("<") and dest.endswith(">"):
        dest = dest[1:-1].strip()
    if not dest:
        return None
    if dest.startswith("#"):
        return DocLink(href, 0, "anchor", anchor=dest[1:])
    # Protocol-relative //host/x and any scheme (http:, mailto:, ftp:) leave the
    # repo. A Windows drive letter ("C:/x") also matches _SCHEME -- and an
    # absolute local path is not an intra-repo relation either, so classifying it
    # as external is correct, not a bug.
    if dest.startswith("//") or _SCHEME.match(dest):
        return DocLink(href, 0, "external")
    path, _, anchor = dest.partition("#")
    path = path.split("?", 1)[0]
    if not path:
        return DocLink(href, 0, "anchor", anchor=anchor)
    try:
        path = unquote(path)
    except Exception:                                   # pragma: no cover
        pass
    return DocLink(href, 0, "path", path=path, anchor=anchor)


def _link_lines(lines: list[str], start: int):
    """Yield (line_index, destination) for every link outside a code fence."""
    fence: tuple[str, int] | None = None
    for i in range(start, len(lines)):
        raw = lines[i]
        fence_hit = _FENCE.match(raw)
        if fence is not None:
            if fence_hit:
                char, length = fence
                got = fence_hit.group(1)
                if got[0] == char and len(got) >= length and not fence_hit.group(2).strip():
                    fence = None
            continue
        if fence_hit:
            fence = (fence_hit.group(1)[0], len(fence_hit.group(1)))
            continue
        # Strip inline code spans: `[x](y)` inside backticks is a rendering of a
        # link, not a link.
        stripped = _INLINE_CODE.sub("", raw)
        for m in _INLINE_LINK.finditer(stripped):
            yield i, m.group(1)
        ref = _REF_DEF.match(stripped)
        if ref:
            yield i, ref.group(1)
        for m in _AUTOLINK.finditer(stripped):
            yield i, m.group(1)


def resolve_link(document: str, link_path: str, known_files) -> str | None:
    """Resolve a document-relative link path to a rel path in the file set.

    Returns None when it cannot be resolved -- an unresolved link is DROPPED and
    counted, never guessed onto a near-match. ``known_files`` is a set/mapping of
    rel paths (POSIX, repo-relative).
    """
    if not link_path:
        return None
    raw = link_path.replace("\\", "/")
    if raw.startswith("/"):
        # Root-relative inside the repo (a docs-site convention).
        candidate = posixpath.normpath(raw.lstrip("/"))
    else:
        base = posixpath.dirname(document)
        candidate = posixpath.normpath(posixpath.join(base, raw) if base else raw)
    if candidate in ("", ".") or candidate.startswith(".."):
        return None                      # escapes the repo -> not our node
    if candidate in known_files:
        return candidate
    # Windows checks out paths case-insensitively, so a doc may spell a link in a
    # case the file set does not use. Mirrors ``graph._resolve_node``'s fallback.
    lowered = {str(f).lower(): str(f) for f in sorted(known_files)}
    return lowered.get(candidate.lower())


# --------------------------------------------------------------------------- #
# Parse                                                                         #
# --------------------------------------------------------------------------- #
def parse_document(document: str, text: str) -> DocumentParse:
    """Parse one Markdown document into sections (the hierarchy) and links."""
    lines = text.splitlines()
    start = _strip_front_matter(lines)
    heads = _headings(lines, start)
    anchors = _dedup_anchors([title for _, _, title in heads])

    sections: list[DocSection] = []

    def _slice(a: int, b: int) -> str:
        return "\n".join(lines[a:b])

    first = heads[0][0] if heads else len(lines)
    if start < first and _slice(start, first).strip():
        sections.append(DocSection(
            module=document, name="(preamble)", line=start + 1, end_line=first,
            loc=first - start, source=_slice(start, first), level=0, anchor="",
            path=(),
        ))

    stack: list[tuple[int, str]] = []
    for n, (idx, level, title) in enumerate(heads):
        while stack and stack[-1][0] >= level:
            stack.pop()
        # A section runs to the next heading of EQUAL OR HIGHER level, so an H2
        # contains its H3s -- the same containment a Python function has over its
        # nested defs (``_units_from_tree`` emits both).
        end = len(lines)
        for later_idx, later_level, _ in heads[n + 1:]:
            if later_level <= level:
                end = later_idx
                break
        sections.append(DocSection(
            module=document, name=title or f"(untitled h{level})",
            line=idx + 1, end_line=end, loc=end - idx,
            source=_slice(idx, end), level=level, anchor=anchors[n],
            path=tuple(t for _, t in stack),
        ))
        stack.append((level, title))

    links: list[DocLink] = []
    for i, dest in _link_lines(lines, start):
        link = _classify(dest)
        if link is not None:
            links.append(DocLink(link.href, i + 1, link.kind, link.path, link.anchor))

    title = next((t for _, lvl, t in heads if lvl == 1 and t), "")
    if not title:
        title = next((t for _, _, t in heads if t), "")
    if not title:
        title = posixpath.basename(document)

    return DocumentParse(
        document=document, title=title, sections=tuple(sections),
        links=tuple(links), loc=len(lines), n_chars=len(text),
    )


def internal_links(parse: DocumentParse, known_files) -> tuple[list[str], int]:
    """(resolved rel targets, unresolved count). Sorted, de-duplicated, self
    excluded -- a document linking to itself is not an edge."""
    resolved: set[str] = set()
    unresolved = 0
    for link in parse.path_links:
        target = resolve_link(parse.document, link.path, known_files)
        if target is None:
            unresolved += 1
        elif target != parse.document:
            resolved.add(target)
    return sorted(resolved), unresolved


# --------------------------------------------------------------------------- #
# The honest slice: keep the heading tree, drop the prose, SAY WHAT WAS DROPPED  #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class DocSkeleton:
    """A distilled document view, plus the receipt for what it cost.

    ``distilled`` False means the raw document was returned because no skeleton
    of it was SMALLER than the document itself (a short README, a doc that is
    nothing but headings). Returning the raw text there is the honest outcome:
    the alternative is a "distillation" that grows the prompt, which this repo
    has already measured as a lie and pinned with a test.
    """

    text: str
    distilled: bool
    kept_headings: int
    total_headings: int
    kept_lines: int
    total_lines: int
    raw_chars: int
    dropped_chars: int
    degraded: str = "full"          # full | no_annotations | truncated | raw

    def to_dict(self) -> dict:
        return {
            "distilled": self.distilled,
            "kept_headings": self.kept_headings,
            "total_headings": self.total_headings,
            "kept_lines": self.kept_lines,
            "total_lines": self.total_lines,
            "raw_chars": self.raw_chars,
            "dropped_chars": self.dropped_chars,
            "degraded": self.degraded,
        }


# A document with no headings has no tree to keep, so the outline degenerates to
# a header and a receipt -- true, and useless to the model reading it. Mirroring
# ``slice._skeleton``'s own fallback for an unparseable file, a bounded head
# excerpt is emitted instead, and labelled as an excerpt so it is never mistaken
# for the whole document.
_HEADLESS_EXCERPT_LINES = 12


def _render(document: str, parse: DocumentParse, heads: list[DocSection],
            limit: int | None, annotate: bool) -> str:
    shown = heads if limit is None else heads[:limit]
    out = [f"# {document}  (document skeleton: heading tree kept, prose dropped)"]
    if parse.title:
        out.append(f"#   title: {parse.title[:120]}")
    for s in shown:
        pad = "  " * s.level
        head = f"{'#' * s.level} {s.name}"[:150]
        if annotate:
            out.append(f"  {pad}{head}   # :{s.line} ({s.loc} lines)")
        else:
            out.append(f"  {pad}{head}")
    if limit is not None and len(heads) > limit:
        out.append(f"    ... {len(heads) - limit} more headings omitted to stay "
                   f"smaller than the raw document")
    excerpt = 0
    if not heads:
        body = [l for l in (parse.sections[0].source.splitlines()
                            if parse.sections else []) if l.strip()]
        for line in body[:_HEADLESS_EXCERPT_LINES]:
            out.append(f"    {line[:120]}")
        excerpt = min(len(body), _HEADLESS_EXCERPT_LINES)
    kept_lines = len(out)
    dropped = max(0, parse.loc - len(shown) - excerpt)
    pct = round(100 * dropped / parse.loc) if parse.loc else 0
    detail = (f"{len(shown)} of {len(heads)} headings kept" if heads
              else f"no headings in this document; first {excerpt} lines shown")
    out.append(
        f"# ===== PROSE DROPPED: {detail}; "
        f"{dropped} of {parse.loc} lines ({pct}%) of body text not shown "
        f"(skeleton is {kept_lines + 1} lines) ====="
    )
    return "\n".join(out)


def document_skeleton(document: str, text: str, *,
                      parse: DocumentParse | None = None,
                      max_chars: int | None = None) -> DocSkeleton:
    """Signature-level digest of a document: the heading tree, prose dropped.

    HARD INVARIANT, tested: ``len(result.text) <= len(text)``, and
    ``<= max_chars`` when one is given. A distilled view larger than its own
    source is not a distillation. The ladder is fixed and deterministic:

      1. heading tree with per-heading provenance (``:line (N lines)``);
      2. the same tree without annotations;
      3. the tree truncated to the first N headings, saying how many were
         omitted (N halved until it fits, so the outcome is a function of the
         input, not of a search order);
      4. the raw document, with ``distilled=False``.

    Every rung says what it dropped. There is no rung that drops silently.
    """
    parse = parse or parse_document(document, text)
    heads = list(parse.headings)
    cap = len(text) if max_chars is None else min(len(text), max_chars)
    total_lines = parse.loc

    def _fits(rendered: str) -> bool:
        return len(rendered) <= cap

    for degraded, annotate in (("full", True), ("no_annotations", False)):
        rendered = _render(document, parse, heads, None, annotate)
        if _fits(rendered):
            return DocSkeleton(
                text=rendered, distilled=True, kept_headings=len(heads),
                total_headings=len(heads), kept_lines=rendered.count("\n") + 1,
                total_lines=total_lines, raw_chars=len(text),
                dropped_chars=len(text) - len(rendered), degraded=degraded,
            )

    limit = len(heads) // 2
    while limit > 0:
        rendered = _render(document, parse, heads, limit, False)
        if _fits(rendered):
            return DocSkeleton(
                text=rendered, distilled=True, kept_headings=limit,
                total_headings=len(heads), kept_lines=rendered.count("\n") + 1,
                total_lines=total_lines, raw_chars=len(text),
                dropped_chars=len(text) - len(rendered), degraded="truncated",
            )
        limit //= 2

    # Nothing describes this document more cheaply than the document. Say so --
    # and distinguish "returned whole" from "returned whole but clipped to fit a
    # caller's hard cap", because those are different claims about completeness.
    if max_chars is None or len(text) <= max_chars:
        return DocSkeleton(
            text=text, distilled=False, kept_headings=0,
            total_headings=len(heads), kept_lines=total_lines,
            total_lines=total_lines, raw_chars=len(text), dropped_chars=0,
            degraded="raw",
        )
    body = text[:max_chars]
    return DocSkeleton(
        text=body, distilled=False, kept_headings=0, total_headings=len(heads),
        kept_lines=body.count("\n") + 1, total_lines=total_lines,
        raw_chars=len(text), dropped_chars=len(text) - len(body),
        degraded="raw_truncated",
    )
