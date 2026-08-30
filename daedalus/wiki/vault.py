# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""vault.py — nested wikis on disk, and the path validator that guards them.

WHAT A VAULT IS
---------------
A folder of plain Markdown files. Deliberately **Obsidian vault format**, because
Obsidian itself is closed and unembeddable (MIT + Commons Clause on React Bits is
a different question; Obsidian has no licence to embed at all), but its FORMAT is
the de-facto standard: `.md` files, `[[wikilinks]]`, YAML frontmatter. Being
format-compatible costs nothing and gives every user an escape hatch — they can
open the same folder in Obsidian and keep working.

Vaults NEST: a global vault the operator owns, and one vault per project. See
``docs/research/TYPE_GRAPH_AND_KNOWLEDGE_SPACE_PLAN.md``.

THE SAFETY SURFACE, AND WHY THE VALIDATOR IS THE FIRST THING IN THIS FILE
------------------------------------------------------------------------
A Momus review of the Knowledge plan flagged this as CRITICAL and it is the reason
the write path is still blocked:

    Every existing path parameter in ``web_api.py`` is an ID matched against
    ``^[A-Za-z0-9._-]{1,160}$`` — ``/`` is forbidden, so traversal is impossible
    by construction. A wiki page rel MUST contain ``/``. ``PUT /api/knowledge/
    page/<rel>`` would therefore be the first arbitrary-write traversal surface
    in this API.

``vault_rel`` is that guard, written before any endpoint exists so the endpoint
cannot be written without it. It is FAIL-CLOSED: every rejection returns None with
a reason, and there is no "best effort" path that resolves a suspicious spelling
into something plausible.

Rejections, each for a specific documented attack:
  * absolute paths and drive letters      -> escapes the vault outright
  * any ``..`` segment BEFORE resolution  -> classic traversal; checked pre-resolve
                                             because ``a/../../b`` normalises to
                                             something innocent-looking
  * a resolved path outside the vault     -> the backstop, checked after resolve
  * symlinks anywhere on the chain        -> a link inside the vault can point out
  * ``:`` in a segment                    -> NTFS alternate data streams
                                             (``page.md:$DATA`` writes a hidden fork)
  * Windows reserved device names         -> ``CON``, ``NUL``, ``COM1`` … open a
                                             device, not a file
  * trailing dots or spaces               -> Windows silently strips them, so
                                             ``x.md.`` and ``x.md`` are the same file
                                             under a different name
  * a suffix other than ``.md``           -> a vault holds prose, not executables

This module is READ-ONLY. It discovers, parses and validates; it never writes. The
write path needs its own gate list plus a Cerberus review, and it does not exist.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

VAULT_VERSION = "1"

PAGE_SUFFIX = ".md"
MAX_PAGES = 5000
MAX_PAGE_BYTES = 2 * 1024 * 1024

#: Windows opens these as devices no matter the extension or directory.
_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)

#: A vault-relative path may not name these. ``vault`` is reserved so the
#: cross-vault link literal ``[[vault:name/page]]`` can never collide with a real
#: directory — the ambiguity Momus flagged in the first draft, where
#: ``[[global/note]]`` was indistinguishable from a real ``global/note.md``.
RESERVED_TOP_LEVEL = frozenset({"vault"})


class VaultPathError(ValueError):
    """A rejected path, carrying the reason a human can act on."""


def vault_rel(vault_root, rel: str) -> tuple[Path | None, str]:
    """Resolve ``rel`` inside ``vault_root``, or refuse with a reason.

    Returns ``(path, "")`` on success and ``(None, reason)`` on refusal. Never
    raises for a bad path — a caller that forgets a try/except would otherwise
    turn a refusal into a 500 and, worse, might be tempted to catch broadly and
    continue.
    """
    root = Path(vault_root)
    if not isinstance(rel, str) or not rel.strip():
        return None, "empty path"
    if len(rel) > 1024:
        return None, "path longer than 1024 characters"
    if "\x00" in rel:
        return None, "NUL byte in path"

    raw = rel.replace("\\", "/")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        return None, "absolute paths are refused; a page path is vault-relative"

    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if not parts:
        return None, "path names no page"

    # Pre-resolution checks. `a/../../b` normalises into something innocent, so
    # the segment test must happen BEFORE any normalisation.
    for seg in parts:
        if seg == "..":
            return None, "'..' segment"
        if ":" in seg:
            return None, f"':' in segment {seg!r} (NTFS alternate data stream)"
        if seg != seg.rstrip(". "):
            return None, f"segment {seg!r} ends in a dot or space (Windows strips these)"
        stem = seg.split(".")[0].lower()
        if stem in _RESERVED:
            return None, f"{seg!r} is a reserved device name"
    if parts[0].lower() in RESERVED_TOP_LEVEL:
        return None, f"{parts[0]!r} is a reserved top-level name"

    if PurePosixPath(parts[-1]).suffix.lower() != PAGE_SUFFIX:
        return None, f"a page must end in {PAGE_SUFFIX}"

    candidate = root.joinpath(*parts)

    # Symlink check walks the WHOLE chain: a link on any component can leave the
    # vault, and checking only the leaf would miss `docs/link_to_etc/passwd.md`.
    probe = root
    for seg in parts:
        probe = probe / seg
        try:
            if probe.is_symlink():
                return None, f"symlink on the path at {seg!r}"
        except OSError:
            return None, f"cannot stat {seg!r}"

    try:
        resolved = candidate.resolve()
        root_res = root.resolve()
    except OSError as exc:
        return None, f"cannot resolve: {exc.__class__.__name__}"
    try:
        resolved.relative_to(root_res)
    except ValueError:
        return None, "resolves outside the vault"
    return candidate, ""


# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Vault:
    """One wiki root. ``name`` is what a cross-vault link says after ``vault:``."""
    name: str
    root: Path
    kind: str                    # "project" | "global"

    def to_dict(self) -> dict:
        return {"name": self.name, "root": str(self.root), "kind": self.kind}


@dataclass(frozen=True)
class Page:
    rel: str
    title: str
    vault: str
    frontmatter: dict = field(default_factory=dict)
    body: str = ""
    body_sha256: str = ""
    #: What kind of page this is, from frontmatter ``type``. One type per page —
    #: the Capacities model, which maps onto a typed graph without a second
    #: taxonomy. Unset means ``note``, which is a default, not a claim.
    page_type: str = "note"
    status: str = ""
    updated: str = ""

    def to_dict(self) -> dict:
        return {"rel": self.rel, "title": self.title, "vault": self.vault,
                "type": self.page_type, "status": self.status,
                "updated": self.updated, "frontmatter": dict(sorted(self.frontmatter.items())),
                "body_sha256": self.body_sha256}


_FENCE = "---"


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """YAML-ish frontmatter, stdlib only.

    Deliberately a SUBSET: ``key: value``, plus ``key: [a, b]`` and dashed lists.
    Nested structures are NOT parsed — they are carried verbatim as a string so
    nothing is silently dropped, and so this never becomes a second YAML
    implementation with its own bugs. PyYAML would also execute tags, which is a
    class of surprise a wiki reader must not have.
    """
    if not text.startswith(_FENCE):
        return {}, text
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FENCE:
        return {}, text
    end = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == _FENCE:
            end = i
            break
    if end is None:
        return {}, text                       # unterminated: it is body, not metadata

    fm: dict = {}
    key = None
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith((" ", "\t")) and line.lstrip().startswith("- ") and key:
            fm.setdefault(key, [])
            if isinstance(fm[key], list):
                fm[key].append(line.lstrip()[2:].strip().strip("\"'"))
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            fm[key] = [v.strip().strip("\"'") for v in value[1:-1].split(",") if v.strip()]
        elif value:
            fm[key] = value.strip("\"'")
        else:
            fm[key] = []
    body = "\n".join(lines[end + 1:])
    return fm, body.lstrip("\n")


def _title_of(rel: str, fm: dict, body: str) -> str:
    """Frontmatter title, else the first H1, else the filename. In that order,
    because a page's own declaration beats a heading and both beat a path."""
    t = fm.get("title")
    if isinstance(t, str) and t.strip():
        return t.strip()
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return PurePosixPath(rel).stem.replace("-", " ").replace("_", " ")


def read_page(vault: Vault, rel: str) -> tuple[Page | None, str]:
    """Read one page, or refuse with a reason. Bounded; never follows a symlink."""
    path, why = vault_rel(vault.root, rel)
    if path is None:
        return None, why
    try:
        if path.stat().st_size > MAX_PAGE_BYTES:
            return None, f"page exceeds the {MAX_PAGE_BYTES}-byte bound"
        raw = path.read_bytes()
    except OSError as exc:
        return None, f"cannot read: {exc.__class__.__name__}"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None, "not valid UTF-8"

    fm, body = parse_frontmatter(text)
    ptype = fm.get("type")
    return Page(
        rel=rel.replace("\\", "/"),
        title=_title_of(rel, fm, body),
        vault=vault.name,
        frontmatter=fm,
        body=body,
        body_sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        page_type=(ptype if isinstance(ptype, str) and ptype else "note"),
        status=str(fm.get("status") or ""),
        updated=str(fm.get("updated") or ""),
    ), ""


def discover_pages(vault: Vault) -> tuple[list[Page], list[dict]]:
    """Every page in a vault, sorted by rel. Refusals are RETURNED, not skipped —
    "we could not read four pages" and "there are no pages" must not look alike."""
    pages: list[Page] = []
    refused: list[dict] = []
    if not vault.root.is_dir():
        return pages, [{"rel": str(vault.root), "reason": "vault root is not a directory"}]
    for path in sorted(vault.root.rglob(f"*{PAGE_SUFFIX}")):
        try:
            rel = path.relative_to(vault.root).as_posix()
        except ValueError:
            continue
        page, why = read_page(vault, rel)
        if page is None:
            refused.append({"rel": rel, "reason": why})
        else:
            pages.append(page)
        if len(pages) >= MAX_PAGES:
            refused.append({"rel": "*", "reason": f"stopped at the {MAX_PAGES}-page bound"})
            break
    return pages, refused


#: Where a project vault lives. One place, so a page's address is stable.
PROJECT_VAULT_DIR = "docs/wiki"


def discover_vaults(repo_root, *, global_root=None) -> list[Vault]:
    """The vaults visible from a project, project first.

    The global vault is OPT-IN via an explicit argument rather than a default
    home-directory path: it lives outside the repo, and everything outside the
    repo root breaks assumptions the index, the write-confinement rules and the
    egress lane all make. Until those are answered it must be a deliberate act.
    """
    out: list[Vault] = []
    root = Path(repo_root)
    project = root / PROJECT_VAULT_DIR
    if project.is_dir():
        out.append(Vault(name=root.resolve().name, root=project, kind="project"))
    if global_root:
        g = Path(global_root).expanduser()
        if g.is_dir():
            out.append(Vault(name="global", root=g, kind="global"))
    return out


def page_tree(pages) -> dict:
    """Nested tree from page paths. Deterministic: every level sorted by name."""
    root: dict = {"name": "", "pages": [], "dirs": {}}
    for p in sorted(pages, key=lambda x: x.rel):
        parts = PurePosixPath(p.rel).parts
        node = root
        for seg in parts[:-1]:
            node = node["dirs"].setdefault(seg, {"name": seg, "pages": [], "dirs": {}})
        node["pages"].append({"rel": p.rel, "title": p.title, "type": p.page_type,
                              "status": p.status})

    def norm(node):
        return {"name": node["name"],
                "pages": node["pages"],
                "dirs": [norm(node["dirs"][k]) for k in sorted(node["dirs"])]}

    return norm(root)
