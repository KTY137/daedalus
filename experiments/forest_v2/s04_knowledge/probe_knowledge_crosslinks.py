"""EXPERIMENT probe: how much of the Knowledge plane actually resolves?

Slice s04 of the Forest v2 pre-study, under the same frozen frame as
``probe_call_resolution.py`` and ``probe_cross_module_resolution.py``: stdlib
only, no imports of repository code, no writes, no network, no subprocess; one
JSON object on stdout.

The Knowledge plane (master plan §5) holds "documentation, ADRs, issues,
concepts, claims, wiki links".  Gate 2 promises *knowledge crosslinks*.  This
probe measures the precondition nobody has measured yet: of the crosslinks the
prose already contains, how many still point at something that exists?  A
knowledge plane whose edges are mostly dead cannot be a retrieval substrate,
and the dead fraction must be known BEFORE a crosslinker is built, so the later
work cannot grade its own homework.

Three edge classes are extracted, each with its own resolution rule:

1. **link** — inline ``[text](target)`` and reference definitions.  Targets
   split into ``external`` (http/https/mailto — unverifiable offline, and so
   excluded from the resolved/dead ratio rather than counted as resolved),
   ``anchor`` (``#slug``, resolved against the headings of the containing
   file) and ``path`` (resolved relative to the containing file, then against
   the repository root).
2. **code_ref** — ``path.py:line`` inside inline code spans.  A path that
   exists is only half a resolution: the line number is checked against the
   file's actual length, so a reference that survived the file but not the
   edit is reported as ``line_out_of_range`` — a dead anchor, not a hit.
   Bare basenames (``picker.py:939``) are resolved by unique basename match;
   a basename matching several files is reported ``ambiguous``, never
   silently resolved.
3. **concept_anchor** — headings define anchors (GitHub slug rule); wiki links
   ``[[Note]]`` resolve against markdown file stems and heading titles.

Precision rule, applied to all classes: fenced code blocks are stripped before
extraction (documentation *about* wiki links contains ``[[Note]]`` examples
that are not edges).  Links and wiki links are additionally taken only from
outside inline code spans, while code refs are taken only from inside them —
that is the form they actually occur in.  The count of refs dropped by fence
stripping is reported, so the filter's effect is visible instead of assumed.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SKIP_DIRS = frozenset(
    {".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache",
     ".pytest_cache", ".ruff_cache", "vault", "site-packages"}
)

# [text](target) — target stops at whitespace or the closing paren.
LINK_RE = re.compile(r"\[(?P<text>[^\]\n]*)\]\((?P<target>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
# [label]: target   (reference-style definition)
REFDEF_RE = re.compile(r"^\s{0,3}\[(?P<label>[^\]\n]+)\]:\s+(?P<target>\S+)", re.MULTILINE)
WIKI_RE = re.compile(r"\[\[(?P<target>[^\]\n|]+)(?:\|[^\]\n]*)?\]\]")
HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*#*\s*$", re.MULTILINE)
INLINE_CODE_RE = re.compile(r"`+([^`\n]+)`+")
# path.py:123 — extension-bearing path followed by a line number.
CODE_REF_RE = re.compile(
    r"^(?P<path>[A-Za-z0-9_][A-Za-z0-9_./-]*\.(?:py|md|json|jsonl|toml|yml|yaml|txt|cfg|ini))"
    r":(?P<line>\d+)$"
)
EXTERNAL_RE = re.compile(r"^(?:https?|mailto|ftp|tel):", re.IGNORECASE)
FENCE_RE = re.compile(r"^\s{0,3}(?P<fence>```+|~~~+)")


def strip_fences(text: str) -> tuple[str, int]:
    """Blank out fenced code blocks, preserving line numbering.

    Returns the masked text and the number of lines removed, so the filter's
    reach is reported rather than trusted.
    """
    out: list[str] = []
    fence: str | None = None
    removed = 0
    for line in text.splitlines():
        match = FENCE_RE.match(line)
        if fence is None:
            if match:
                fence = match.group("fence")[:3]
                out.append("")
                removed += 1
                continue
            out.append(line)
        else:
            out.append("")
            removed += 1
            if match and match.group("fence")[:3] == fence:
                fence = None
    return "\n".join(out), removed


def slugify(title: str) -> str:
    """GitHub-flavoured heading slug: lowercase, drop punctuation, space->dash."""
    text = title.strip().lower()
    text = re.sub(r"[`*_~\[\]()]", "", text)
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    # GitHub replaces EACH whitespace character with a hyphen; it does not
    # collapse runs.  "Budgets & Limits" -> "budgets--limits".  Collapsing
    # here would mint false dead anchors against real headings.
    text = re.sub(r"\s", "-", text.strip())
    return text.strip("-")


def mask_inline_code(text: str) -> str:
    """Replace inline code spans with spaces of equal length."""
    return INLINE_CODE_RE.sub(lambda m: " " * len(m.group(0)), text)


def iter_markdown(root: Path) -> list[Path]:
    found: list[Path] = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except (OSError, PermissionError):
            continue
        for entry in entries:
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir():
                    if entry.name not in SKIP_DIRS:
                        stack.append(entry)
                elif entry.suffix.lower() == ".md":
                    found.append(entry)
            except OSError:
                continue
    return sorted(found)


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def build_corpus_index(root: Path) -> dict:
    """Index every file once: line counts, basenames, heading anchors, stems."""
    line_counts: dict[str, int] = {}
    basenames: dict[str, list[str]] = {}
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except (OSError, PermissionError):
            continue
        for entry in entries:
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir():
                    if entry.name not in SKIP_DIRS:
                        stack.append(entry)
                    continue
            except OSError:
                continue
            rel = entry.relative_to(root).as_posix()
            line_counts[rel] = -1  # existence known; length filled lazily
            basenames.setdefault(entry.name, []).append(rel)
    return {"line_counts": line_counts, "basenames": basenames}


def count_lines(root: Path, rel: str, cache: dict[str, int]) -> int:
    cached = cache.get(rel, -1)
    if cached >= 0:
        return cached
    try:
        with (root / rel).open("rb") as handle:
            total = sum(1 for _ in handle)
    except OSError:
        total = 0
    cache[rel] = total
    return total


def probe(root: Path) -> dict:
    root = root.resolve()
    index = build_corpus_index(root)
    existing: dict[str, int] = index["line_counts"]
    basenames: dict[str, list[str]] = index["basenames"]

    md_files = iter_markdown(root)
    md_rel = [p.relative_to(root).as_posix() for p in md_files]
    md_stems = {Path(r).stem.lower() for r in md_rel}

    # Pass 1: heading anchors per file, plus the global concept-title set.
    anchors: dict[str, set[str]] = {}
    heading_titles: set[str] = set()
    heading_total = 0
    bodies: dict[str, str] = {}
    for path, rel in zip(md_files, md_rel):
        raw = _read(path)
        if raw is None:
            continue
        masked, _ = strip_fences(raw)
        bodies[rel] = masked
        file_anchors: set[str] = set()
        for match in HEADING_RE.finditer(masked):
            title = match.group("title").strip()
            heading_total += 1
            heading_titles.add(title.lower())
            slug = slugify(title)
            if slug:
                file_anchors.add(slug)
        anchors[rel] = file_anchors

    totals = {
        "markdown_files": len(md_rel),
        "unreadable_files": len(md_rel) - len(bodies),
        "fenced_lines_masked": 0,
        "headings": heading_total,
        # link class
        "link_total": 0,
        "link_external": 0,
        "link_path_resolved": 0,
        "link_path_dead": 0,
        "link_anchor_resolved": 0,
        "link_anchor_dead": 0,
        # code_ref class
        "code_ref_total": 0,
        "code_ref_resolved": 0,
        "code_ref_suffix_resolved": 0,
        "code_ref_line_out_of_range": 0,
        "code_ref_ambiguous": 0,
        "code_ref_dead_path": 0,
        # wiki class (prose notes)
        "wiki_total": 0,
        "wiki_resolved": 0,
        "wiki_dead": 0,
        # typed [[code:PATH]] wiki links — a knowledge->code plane edge
        "wiki_code_target_total": 0,
        "wiki_code_target_resolved": 0,
        "wiki_code_target_dead": 0,
        # precision accounting
        "refs_dropped_by_fence_filter": 0,
    }
    dead_examples: dict[str, list[str]] = {
        "link_path_dead": [],
        "link_anchor_dead": [],
        "code_ref_line_out_of_range": [],
        "code_ref_dead_path": [],
        "code_ref_ambiguous": [],
        "code_ref_suffix_resolved": [],
        "wiki_dead": [],
        "wiki_code_target_dead": [],
    }

    def note(bucket: str, value: str) -> None:
        if len(dead_examples[bucket]) < 12:
            dead_examples[bucket].append(value)

    for path, rel in zip(md_files, md_rel):
        raw = _read(path)
        if raw is None:
            continue
        masked, removed = strip_fences(raw)
        totals["fenced_lines_masked"] += removed
        # How many candidate refs did the fence filter remove?
        for regex in (LINK_RE, WIKI_RE):
            totals["refs_dropped_by_fence_filter"] += len(
                regex.findall(raw)
            ) - len(regex.findall(masked))

        prose = mask_inline_code(masked)
        here = (root / rel).parent

        # --- links -------------------------------------------------------
        targets = [m.group("target") for m in LINK_RE.finditer(prose)]
        targets += [m.group("target") for m in REFDEF_RE.finditer(prose)]
        for target in targets:
            totals["link_total"] += 1
            if EXTERNAL_RE.match(target):
                totals["link_external"] += 1
                continue
            if target.startswith("#"):
                slug = target[1:].lower()
                if slug in anchors.get(rel, set()):
                    totals["link_anchor_resolved"] += 1
                else:
                    totals["link_anchor_dead"] += 1
                    note("link_anchor_dead", f"{rel} -> {target}")
                continue
            path_part, _, anchor_part = target.partition("#")
            if not path_part:
                totals["link_path_dead"] += 1
                note("link_path_dead", f"{rel} -> {target}")
                continue
            candidate = (here / path_part).resolve()
            try:
                cand_rel = candidate.relative_to(root).as_posix()
            except ValueError:
                cand_rel = ""
            hit = cand_rel in existing if cand_rel else False
            if not hit:
                alt = path_part.lstrip("./")
                hit = alt in existing
                cand_rel = alt if hit else cand_rel
            if not hit and candidate.is_dir():
                hit = True
            if hit:
                if anchor_part and cand_rel.endswith(".md"):
                    if anchor_part.lower() in anchors.get(cand_rel, set()):
                        totals["link_anchor_resolved"] += 1
                    else:
                        totals["link_anchor_dead"] += 1
                        note("link_anchor_dead", f"{rel} -> {target}")
                else:
                    totals["link_path_resolved"] += 1
            else:
                totals["link_path_dead"] += 1
                note("link_path_dead", f"{rel} -> {target}")

        # --- wiki links --------------------------------------------------
        for match in WIKI_RE.finditer(prose):
            target = match.group("target").strip()
            # [[code:PATH]] is a typed knowledge->code edge, not a note link;
            # resolving it against note stems would call a live edge dead.
            prefix, sep, payload = target.partition(":")
            if sep and prefix.lower() == "code":
                totals["wiki_code_target_total"] += 1
                if payload.strip() in existing:
                    totals["wiki_code_target_resolved"] += 1
                else:
                    totals["wiki_code_target_dead"] += 1
                    note("wiki_code_target_dead", f"{rel} -> [[{target}]]")
                continue
            totals["wiki_total"] += 1
            stem = Path(target).stem.lower()
            if stem in md_stems or target.lower() in heading_titles:
                totals["wiki_resolved"] += 1
            else:
                totals["wiki_dead"] += 1
                note("wiki_dead", f"{rel} -> [[{target}]]")

        # --- code refs (inside inline code spans only) --------------------
        for span in INLINE_CODE_RE.finditer(masked):
            content = span.group(1).strip()
            match = CODE_REF_RE.match(content)
            if not match:
                continue
            totals["code_ref_total"] += 1
            ref_path = match.group("path")
            ref_line = int(match.group("line"))
            resolved_rel = ""
            by_suffix = False
            if ref_path in existing:
                resolved_rel = ref_path
            else:
                relative_try = (here / ref_path).resolve()
                try:
                    cand = relative_try.relative_to(root).as_posix()
                except ValueError:
                    cand = ""
                if cand and cand in existing:
                    resolved_rel = cand
                elif "/" not in ref_path:
                    matches = basenames.get(ref_path, [])
                    if len(matches) == 1:
                        resolved_rel = matches[0]
                    elif len(matches) > 1:
                        totals["code_ref_ambiguous"] += 1
                        note("code_ref_ambiguous",
                             f"{rel} -> {content} ({len(matches)} candidates)")
                        continue
                else:
                    # Package-relative prose ("spine/attempt.py" for
                    # "daedalus/spine/attempt.py").  Reported in its own
                    # bucket: a unique suffix match is a weaker claim than an
                    # exact path, so the strict rate never absorbs it.
                    suffix = "/" + ref_path
                    matches = [r for r in existing if r.endswith(suffix)]
                    if len(matches) == 1:
                        resolved_rel = matches[0]
                        by_suffix = True
                    elif len(matches) > 1:
                        totals["code_ref_ambiguous"] += 1
                        note("code_ref_ambiguous",
                             f"{rel} -> {content} ({len(matches)} candidates)")
                        continue
            if not resolved_rel:
                totals["code_ref_dead_path"] += 1
                note("code_ref_dead_path", f"{rel} -> {content}")
                continue
            length = count_lines(root, resolved_rel, existing)
            if ref_line <= length:
                if by_suffix:
                    totals["code_ref_suffix_resolved"] += 1
                    note("code_ref_suffix_resolved",
                         f"{rel} -> {content} => {resolved_rel}")
                else:
                    totals["code_ref_resolved"] += 1
            else:
                totals["code_ref_line_out_of_range"] += 1
                note("code_ref_line_out_of_range",
                     f"{rel} -> {content} (file has {length} lines)")

    def pct(hit: int, total: int) -> float:
        return round(100.0 * hit / total, 1) if total else 0.0

    link_checkable = (
        totals["link_path_resolved"] + totals["link_path_dead"]
        + totals["link_anchor_resolved"] + totals["link_anchor_dead"]
    )
    link_resolved = totals["link_path_resolved"] + totals["link_anchor_resolved"]
    code_checkable = totals["code_ref_total"] - totals["code_ref_ambiguous"]
    code_tolerant = totals["code_ref_resolved"] + totals["code_ref_suffix_resolved"]
    wiki_all = totals["wiki_total"] + totals["wiki_code_target_total"]
    wiki_all_resolved = totals["wiki_resolved"] + totals["wiki_code_target_resolved"]
    edges_checkable = link_checkable + code_checkable + wiki_all
    edges_resolved = link_resolved + code_tolerant + wiki_all_resolved

    return {
        "schema": "forest-v2-knowledge-crosslink-probe/1",
        "read_only": True,
        "root": root.name,
        "totals": totals,
        "rates": {
            "link_resolved_pct": pct(link_resolved, link_checkable),
            "link_checkable": link_checkable,
            "code_ref_resolved_strict_pct": pct(
                totals["code_ref_resolved"], code_checkable),
            "code_ref_resolved_incl_suffix_pct": pct(code_tolerant, code_checkable),
            "code_ref_checkable": code_checkable,
            "wiki_note_resolved_pct": pct(totals["wiki_resolved"], totals["wiki_total"]),
            "wiki_code_target_resolved_pct": pct(
                totals["wiki_code_target_resolved"], totals["wiki_code_target_total"]),
            "all_edges_checkable": edges_checkable,
            "all_edges_resolved": edges_resolved,
            "all_edges_resolved_pct": pct(edges_resolved, edges_checkable),
            "all_edges_dead": edges_checkable - edges_resolved,
        },
        "dead_examples": dead_examples,
    }


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[3]
    print(json.dumps(probe(root), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
