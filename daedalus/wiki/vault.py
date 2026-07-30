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
  * 8.3 short names (tilde in segment)    -> ``SHORT~1.MD`` can point elsewhere even
                                             inside the vault
  * UNC and drive‑relative paths          -> the validator now distinguishes these
                                             and refuses them explicitly
  * Unicode normalisation collisions      -> the rel is normalised to NFC before
                                             any checks, so NFD spellings of
                                             reserved names are caught
  * case‑insensitive duplicates           -> the whole rel is lower‑cased, removing
                                             any chance of two entries for one file

This module is READ-ONLY. It discovers, parses and validates; it never writes. The
write path needs its own gate list plus a Cerberus review, and it does not exist.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
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

    # Normalise early so any reserved‑name spelling (NFD, mixed case) is caught
    # by the segment checks.
    rel = unicodedata.normalize('NFC', rel)

    raw = rel.replace("\\", "/")

    # ----- absolute and drive‑related paths --------------------------------
    if raw.startswith("/"):
        return None, "absolute paths are refused; a page path is vault-relative"
    m = re.match(r'^[A-Za-z]:', raw)
    if m:
        # drive letter + colon -> could be C:/… or C:something
        if raw[m.end():].startswith("/"):
            return None, "absolute paths (with drive letter) are refused"
        else:
            return None, "drive-relative paths are refused"

    # ----- case canonicalisation ------------------------------------------
    raw = raw.lower()

    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if not parts:
        return None, "path names no page"

    # Pre‑resolution checks. `a/../../b` normalises into something innocent, so
    # the segment test must happen BEFORE any normalisation.
    for seg in parts:
        if seg == "..":
            return None, "'..' segment"
        if ":" in seg:
            return None, f"':' in segment {seg!r} (NTFS alternate data stream)"
        if seg != seg.rstrip(". "):
            return None, f"segment {seg!r} ends in a dot or space (Windows strips these)"
        if "~" in seg:
            return None, f"segment {seg!r} contains '~' (short name attack)"
        stem = seg.split(".")[0]          # already lower‑cased by the raw.lower() above
        if stem in _RESERVED:
            return None, f"{seg!r} is a reserved device name"
    if parts[0] in RESERVED_TOP_LEVEL:
        return None, f"{parts[0]!r} is a reserved top-level name"

    if not parts[-1].endswith(PAGE_SUFFIX):
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
    # canonical rel from the resolved path (case‑folded, NFC)
    try:
        rel_canon = path.relative_to(vault.root).as_posix()
    except ValueError:
        # shouldn't happen because vault_rel already checks this
        rel_canon = rel.replace("\\", "/")
    return Page(
        rel=rel_canon,
        title=_title_of(rel_canon, fm, body),
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


# ---------------------------------------------------------------------------
# In‑line adversarial tests for the vault path validator
# ---------------------------------------------------------------------------
# These tests attempt to exercise every refusal the validator makes, and also
# probe for escapes that may not yet be covered.  The validator must never raise.
#
# Attacks that could not be tested in a portable way:
#   * "resolves outside the vault" – without symlinks the check is unreachable
#     from a valid‑looking rel, and the symlink guard already covers the
#     realistic attack.  A per‑platform junction‑point test would be needed.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import tempfile
    import unittest
    import os
    import sys

    class TestVaultRel(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            # Create a temporary vault root with a controlled layout so that
            # resolve() and symlink behaviour are deterministic and do not depend
            # on the developer's working directory.
            cls._tmp = tempfile.TemporaryDirectory(prefix="vault_test_")
            cls.root = Path(cls._tmp.name)
            (cls.root / "subdir").mkdir(exist_ok=True)
            # A regular file to keep resolve() happy for the success‑path tests.
            (cls.root / "legit.md").write_text("hello", encoding="utf-8")
            (cls.root / "subdir" / "nested.md").write_text("nested", encoding="utf-8")

            # Symlink test setup: create a target *outside* the vault root, then
            # symlink to it from inside.  If the platform cannot create symlinks,
            # the related test will be skipped.
            cls._outside_tmp = tempfile.TemporaryDirectory(prefix="outside_")
            cls.outside_file = Path(cls._outside_tmp.name) / "outside.md"
            cls.outside_file.write_text("outside", encoding="utf-8")
            cls.symlink_path = cls.root / "link_to_outside.md"
            try:
                cls.symlink_path.symlink_to(cls.outside_file)
            except OSError:
                cls.symlink_path = None   # flag that symlinks are unsupported

        @classmethod
        def tearDownClass(cls):
            cls._tmp.cleanup()
            cls._outside_tmp.cleanup()

        def _assert_refused(self, rel, expected_reason_substring):
            path, reason = vault_rel(self.root, rel)
            self.assertIsNone(path, f"Expected refusal for {rel!r}, got {path}")
            self.assertIn(expected_reason_substring, reason.lower(),
                          f"Reason for {rel!r} should contain {expected_reason_substring!r}, got {reason!r}")

        # --- tests for every refusal the validator currently makes ------------

        def test_empty_path(self):
            self._assert_refused("", "empty")
            self._assert_refused("   ", "empty")

        def test_nul_byte(self):
            self._assert_refused("foo\x00bar.md", "nul")

        def test_path_too_long(self):
            long_path = "a" * 1025 + ".md"
            self._assert_refused(long_path, "long")

        def test_absolute_unix(self):
            self._assert_refused("/etc/passwd", "absolute paths")

        def test_drive_absolute(self):
            self._assert_refused("C:/Windows/system.ini", "absolute paths (with drive letter)")

        def test_drive_relative(self):
            self._assert_refused("C:boot.ini", "drive-relative")
            self._assert_refused("D:subdir/page.md", "drive-relative")

        def test_unc_refused_as_absolute(self):
            # UNC paths start with // or \\; after backslash normalisation they
            # begin with "/", so the absolute‑path check fires.
            self._assert_refused("//server/share/page.md", "absolute paths")
            self._assert_refused(r"\\server\share\page.md", "absolute paths")

        def test_parent_segment(self):
            self._assert_refused("../outside.md", "'..' segment")
            self._assert_refused("subdir/../../outside.md", "'..' segment")

        def test_ads_colon(self):
            self._assert_refused("file.md:stream", "':' in segment")
            self._assert_refused("dir:stream/file.md", "':' in segment")

        def test_trailing_dot_or_space(self):
            self._assert_refused("file. .md", "ends in a dot or space")   # space then dot then space
            self._assert_refused("file.md.", "ends in a dot or space")
            self._assert_refused("file.md ", "ends in a dot or space")
            self._assert_refused("dir ./file.md", "ends in a dot or space")
            self._assert_refused("file..md", "ends in a dot or space")

        def test_short_name_tilde(self):
            self._assert_refused("short~1.md", "short name attack")
            self._assert_refused("dir/normal~file.md", "short name attack")

        def test_reserved_device_name(self):
            for name in ("CON", "con", "CON.md", "COM1", "LPT3.md", "nul.txt", "PRN.md"):
                self._assert_refused(name, "reserved device name")
            # Also with a directory prefix.
            self._assert_refused("subdir/con.md", "reserved device name")

        def test_reserved_top_level_vault(self):
            self._assert_refused("vault/page.md", "reserved top-level name")

        def test_suffix_not_md(self):
            self._assert_refused("page.txt", "a page must end in")
            self._assert_refused("page.md.old", "a page must end in")

        def test_symlink_refused(self):
            if self.symlink_path is None:
                self.skipTest("platform does not support symlink creation")
            # The symlink itself is the leaf, so we pass the rel pointing to it.
            self._assert_refused("link_to_outside.md", "symlink")

        def test_unicode_normalisation_collisions(self):
            # Fullwidth CON (U+FF23 U+FF2F U+FF2E) normalises to ASCII "con".
            self._assert_refused("\uff43\uff4f\uff4e.md", "reserved device name")
            # NFD café vs NFC café — both should resolve to the same (nonexistent) path.
            path_nfc, _ = vault_rel(self.root, "caf\u00e9.md")
            path_nfd, _ = vault_rel(self.root, "cafe\u0301.md")
            self.assertIsNotNone(path_nfc, "NFC form should be accepted")
            self.assertIsNotNone(path_nfd, "NFD form should be accepted after normalisation")
            self.assertEqual(path_nfc, path_nfd,
                             "NFC and NFD spellings of the same name must produce the same path")

        def test_case_insensitive_duplicates(self):
            path1, _ = vault_rel(self.root, "MyFile.md")
            path2, _ = vault_rel(self.root, "myfile.md")
            self.assertIsNotNone(path1)
            self.assertIsNotNone(path2)
            self.assertEqual(path1, path2,
                             "Case variants must resolve to the same path after lowercasing")

        def test_valid_path_inside_vault(self):
            path, reason = vault_rel(self.root, "legit.md")
            self.assertIsNotNone(path, f"legit.md should be accepted: {reason}")
            self.assertEqual(reason, "")
            self.assertTrue(path.is_absolute())

        def test_valid_nested_path(self):
            path, reason = vault_rel(self.root, "subdir/nested.md")
            self.assertIsNotNone(path, f"nested.md should be accepted: {reason}")
            self.assertEqual(reason, "")

        # ----------- edge cases that must not raise ---------------------------
        def test_only_dots(self):
            self._assert_refused("..", "'..' segment")
            self._assert_refused(".", "empty path")   # stripped to empty
            self._assert_refused("...", "ends in a dot or space")  # trailing dot

        def test_weird_unicode_but_valid(self):
            # A valid path that uses decomposed characters should still pass.
            path, reason = vault_rel(self.root, "weird\N{LATIN SMALL LETTER E WITH ACUTE}.md")
            self.assertIsNotNone(path, f"valid unicode path rejected: {reason}")

    unittest.main()
