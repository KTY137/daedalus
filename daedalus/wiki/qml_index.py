"""qml_index.py -- the names a Qt/QML front-end defines, so it stops being invisible.

``verify`` decides whether a wiki page tells the truth about a tree by asking
whether the names it puts in backticks exist in that tree. That question is only
as good as the vocabulary behind it, and the vocabulary was built from Python:
``ast`` definitions, config keys, and a word scrape of the text files. A Qt
application keeps a large part of its real name surface somewhere else entirely
-- in ``.qml``. A component id, a declared ``property``, a ``signal``, an
``objectName``, an enum like ``Font.DemiBold``: every one of those is a name the
documentation legitimately cites, and none of them is a Python symbol.

The measurement that commissioned this module (project_tct, 2026-08-25, taken by
the caller): with the vocabulary built from Python definitions and config keys
alone, ``unknown_symbol`` stood at 2868, overwhelmingly QML -- ids, kit component
names, property names, Qt enum members. Findings at that density are not a defect
list, they are noise that buries the two or three real errors inside it. The tree
there holds 42 hand-written ``.qml`` files (2054 more live under
``.venv``/``site-packages`` and are skipped, like everywhere else in this package).

WHAT IT BUYS TODAY: NOTHING. MEASURED.
--------------------------------------
By the time this landed, ``verify.tree_vocabulary`` no longer built the
vocabulary from Python alone -- it scrapes every identifier-shaped word out of
every readable file in the tree, ``.qml`` included. Every name returned here is
therefore a token of a file that scrape already reads, over the same skip set and
under a stricter size cap, so this module is a strict subset of it and cannot
change a single count. Measured on project_tct 2026-08-25: 0 names added over
the 39 files of ``TCT_app/gui/qml``, 0 added over the 418 readable files of
``TCT_app``. Not "small" -- zero, and structurally so.

That is the honest state, and it is not an argument for deleting the module. A
word scrape cannot tell a declaration from a sentence, which is exactly why
``unknown_symbol`` fell from thousands to almost nothing: the vocabulary grew
until it acquitted everything. When that scrape is narrowed -- and a claim check
that cannot fail is not a check -- the QML names must come back from a reader
that knows the difference. This is that reader, measured and waiting. Anyone
reporting a finding count as evidence of THIS module working should re-read this
paragraph first.

WHAT THIS IS NOT
----------------
Not a QML parser. Deterministic regexes over comment-stripped text, nothing
else -- no grammar, no Qt, no imports beyond the standard library. QML is not a
regular language and this module does not pretend otherwise.

The bias is therefore fixed in one direction: PRECISION OVER RECALL. Missing a
real symbol costs one false ``unknown_symbol`` finding, which is loud, visible,
and gets fixed. Admitting one word of prose costs a silent hole in the check --
a wrong name in a wiki page that the checker now waves through forever. So
comments are stripped before anything is matched, minified vendor bundles are
refused whole, and the one rule that infers rather than reads a declaration (a
name to the left of a colon) is filtered down to identifier shapes that could
not be an English or German word.

The function adds vocabulary and nothing else. It cannot suppress a finding
kind, lower a count, or change a verdict -- the only thing it can do is make a
name known that genuinely occurs in the tree.

"COULD NOT MEASURE" IS A SEPARATE ANSWER
---------------------------------------
Refusing a file (too large, minified, unreadable) and reading a file that
declares nothing both end in "no names from here". They are not the same fact,
and an instrument that renders them identically fails silently toward less
coverage, which here means toward a quieter checker. So the scan carries a
``ScanReport``: how many files it actually read, and every file it refused with
the reason. ``qml_vocabulary`` returns the names alone for the one caller that
only wants the set; anything that needs to know whether the measurement
happened calls ``scan`` and looks. There is no parser, so there is no parse
error -- a refusal is the only way this module can fail to see a file, and
every refusal is on the record.
"""

from __future__ import annotations

import dataclasses
import os
import pathlib
import re
from collections.abc import Iterable

# The one import back into the package. ``verify`` deliberately does NOT import
# this module at its top level -- the hook inside ``tree_vocabulary`` imports it
# on call -- so this direction stays acyclic. Do not move that hook up here.
from .verify import SKIP_DIRS

MAX_BYTES = 400_000
# Above this longest-line length a file is a minified bundle, not source. The
# seven vendor bundles under project_tct's web-ui measure 2237..172954
# characters on their longest line; the three hand-written ones measure
# 188..200. A minified bundle would donate thousands of mangled two-letter
# camelCase tokens to the vocabulary -- exactly the silent hole this module is
# built to avoid -- so it is refused whole rather than scraped.
MAX_LINE = 1000

BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
# `//` to end of line, except when preceded by a colon, which is a URL scheme
# (`https://`, `file://`) and not a comment.
LINE_COMMENT = re.compile(r"(?<!:)//[^\n]*")

# --- declarations: read literally, kept whatever shape they have -------------
ID = re.compile(r"(?<![.\w])id\s*:\s*([A-Za-z_]\w*)")
PROPERTY = re.compile(
    r"\bproperty\s+(?:list\s*<[^>]{1,80}>|[A-Za-z_][\w.]*)\s+([A-Za-z_]\w*)")
FUNCTION = re.compile(r"\bfunction\s+([A-Za-z_]\w*)\s*\(")
SIGNAL = re.compile(r"(?m)\bsignal\s+([A-Za-z_]\w*)\s*(?:\(|$)")
INLINE_COMPONENT = re.compile(r"\bcomponent\s+([A-Za-z_]\w*)\s*:")
# `Surface {`, `QtObject {`, `StatChip {` at the head of a line: a QML object
# declaration, so the capitalised token is a component type that exists.
OBJECT_HEAD = re.compile(r"(?m)^\s*([A-Z]\w*)\s*\{")
# `objectName: "kitMetricTile"` -- the key makes the string unambiguous, and
# these names are what Python tests and docs address a widget by.
OBJECT_NAME = re.compile(r"\bobjectName\s*:\s*[\"']([A-Za-z_]\w*)[\"']")
# `Font.DemiBold`, `Text.ElideRight`, `Surface.Tile`: a Capitalised.Capitalised
# pair is an enum member or an attached type, never a sentence.
QUALIFIED = re.compile(r"\b([A-Z]\w*)\.([A-Z]\w*)\b")

# --- inference: shape-filtered, because this one could catch prose -----------
# `meterFraction:`, `Layout.fillWidth:`, `Component.onCompleted:`.
ASSIGNMENT = re.compile(r"(?m)^\s*([A-Za-z_][\w.]*)\s*:")
# An underscore or an internal case transition. A bare lowercase word left of a
# colon is indistinguishable from prose (`hinweis:`, `note:`) and is dropped --
# it would also be unusable downstream, since verify's own SYMBOL_SHAPE never
# flags a single lowercase word in the first place.
INTERESTING = re.compile(r"^(?:\w*_\w*|.*[a-z].*[A-Z].*|[A-Z][a-z]+[A-Z]\w*)$")


TOO_LARGE = "too_large"
MINIFIED = "minified"
UNREADABLE = "unreadable"


@dataclasses.dataclass(frozen=True)
class ScanReport:
    """What the scan saw, and what it could not see.

    ``files_read == 0`` with an empty ``names`` means the scan found no QML at
    all; ``files_read == 42`` with an empty ``names`` would mean 42 files
    declared nothing, which would be a bug in this module. The two are only
    distinguishable because the count is here.
    """

    names: frozenset[str]
    files_read: int
    refused: tuple[tuple[str, str], ...]     # (reason, path relative to root)

    def summary(self) -> str:
        counts: dict[str, int] = {}
        for reason, _ in self.refused:
            counts[reason] = counts.get(reason, 0) + 1
        detail = ", ".join(f"{n} {reason}" for reason, n in sorted(counts.items()))
        return (f"{len(self.names)} names from {self.files_read} file(s)"
                + (f"; refused {len(self.refused)}: {detail}" if self.refused else
                   "; refused none"))


def _usable(path: pathlib.Path) -> bool:
    return not any(part in SKIP_DIRS for part in path.parts)


def _read(path: pathlib.Path) -> tuple[str | None, str]:
    """Comment-stripped source text, or ``(None, reason)`` if the file is refused."""
    try:
        if path.stat().st_size > MAX_BYTES:
            return None, TOO_LARGE
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, UNREADABLE
    if ".min." in path.name.lower():
        return None, MINIFIED
    if any(len(line) > MAX_LINE for line in text.splitlines()):
        return None, MINIFIED
    text = BLOCK_COMMENT.sub(" ", text)
    return LINE_COMMENT.sub(" ", text), ""


def _names(path: pathlib.Path, text: str) -> set[str]:
    found: set[str] = set()
    # `MetricTile.draft.qml` names the component `MetricTile`; the full stem is
    # kept too, for trees that spell a file `Foo.ui.qml`.
    for stem in (path.stem, path.name.split(".")[0]):
        if stem.isidentifier():
            found.add(stem)
    for pattern in (ID, PROPERTY, FUNCTION, SIGNAL, INLINE_COMPONENT,
                    OBJECT_HEAD, OBJECT_NAME):
        found.update(pattern.findall(text))
    for owner, member in QUALIFIED.findall(text):
        found.add(owner)
        found.add(member)
    for span in ASSIGNMENT.findall(text):
        for part in span.split("."):
            if INTERESTING.match(part):
                found.add(part)
    found.discard("")
    return found


def scan(root: pathlib.Path,
         exclude_dirs: Iterable[pathlib.Path] = ()) -> ScanReport:
    """Read every ``.qml``/``.js`` file under ``root`` and report names and refusals.

    Skips the same directories as ``verify`` (vendored Qt modules under
    ``site-packages`` are the bulk of them). ``exclude_dirs`` are the trees that
    may not vouch for the check: the wiki currently under test, and the run
    directory holding the checker's own previous report. Nothing beneath them
    contributes vocabulary -- the same rule ``verify.tree_vocabulary`` applies
    to its own scrape, restated here so the QML union cannot become a way
    around it.
    """
    # Both sides resolved, or a relative `root` against an absolute exclusion
    # would never match and the exclusion would fail open in silence -- the one
    # failure direction this module must not have.
    root = root.resolve()
    excluded = [d.resolve() for d in exclude_dirs]
    vocabulary: set[str] = set()
    refused: list[tuple[str, str]] = []
    read = 0
    for dirpath, dirnames, filenames in os.walk(root):
        here = pathlib.Path(dirpath)
        if any(here.is_relative_to(d) for d in excluded):
            dirnames[:] = []
            continue
        # Pruned at the DIRECTORY level, which `rglob` cannot do: it enumerates
        # every entry and lets the per-file filter throw it away afterwards. On
        # project_tct that is 78250 entries walked to keep 7295 -- 90.7% of the
        # work discarded, one full walk costing 61s (measured 2026-08-25 by
        # wiki-editor-test-verify). One pruned pass over both suffixes here
        # replaces two unpruned ones. `os.walk` also does not follow symlinks,
        # so a junction loop cannot hang the scan.
        dirnames[:] = [d for d in sorted(dirnames) if d not in SKIP_DIRS]
        for name in sorted(filenames):
            if not name.lower().endswith((".qml", ".js")):
                continue
            path = here / name
            if not path.is_file() or not _usable(path):
                continue
            text, reason = _read(path)
            if text is None:
                refused.append((reason, path.relative_to(root).as_posix()))
                continue
            read += 1
            vocabulary |= _names(path, text)
    return ScanReport(frozenset(vocabulary), read, tuple(sorted(refused)))


def qml_vocabulary(root: pathlib.Path,
                   exclude_dirs: Iterable[pathlib.Path] = ()) -> set[str]:
    """Every name a ``.qml`` or ``.js`` file in ``root`` declares or addresses.

    A flat set; it never reports which file a name came from, because the one
    consumer asks a single question of it -- does this name exist anywhere in
    the tree. Call ``scan`` instead when you need to know whether the scan could
    read anything at all.
    """
    return set(scan(root, exclude_dirs).names)


def main(argv: list[str]) -> int:
    args = argv[1:]
    if not args or args[0].startswith("-"):
        print("usage: python -m daedalus.wiki.qml_index <repo-root> [exclude-dir ...]")
        return 2
    root = pathlib.Path(args[0]).resolve()
    if not root.is_dir():
        print(f"not a directory: {root}")
        return 2
    report = scan(root, [pathlib.Path(a) for a in args[1:]])
    print(f"{report.summary()} under {root}")
    for reason, path in report.refused:
        print(f"  refused ({reason}): {path}")
    for name in sorted(report.names)[:40]:
        print(f"  {name}")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv))
