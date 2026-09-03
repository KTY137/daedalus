"""spine/docrefs.py -- prose that contradicts the code it describes.

THE PROBLEM THIS EXISTS FOR
---------------------------
Measured on 2026-07-29: every candidate the picker produced from its existing
sources (7 ``map_island``, 7 ``inventory_island``, 3 ``map_shim``) was source
surgery under ``daedalus/``. The installed self-policy permits writes to
``docs/``, ``tests/`` and ``README.md`` only. The intersection was EMPTY -- the
loop, pointed at itself, selected only work it is forbidden to perform.

Widening the write permission is the day-one failure mode and is not the fix.
The fix is a source of work that is REAL, VERIFIABLE, and inside the permitted
tree. This is that source.

WHAT IT MEASURES
----------------
A reference in the documentation to a code symbol that does not exist.

    docs/HANDOFF.md says  `daedalus.spine.picker.pick_next`
    daedalus/spine/picker.py defines no `pick_next`

That is a defect with a reader-visible cost (a human follows the doc and finds
nothing), it is machine-checkable without running anything, and the remedy is a
prose edit inside ``docs/``. This repo has produced nine such defects.

THE FALSE-POSITIVE FILTER IS THE WHOLE DESIGN
---------------------------------------------
Documentation legitimately names paths that do not exist: a plan describes what
will be built, an ADR describes an option that was refused, a handoff describes
what was taken out. Flagging those would send a fixer to "correct" a document
that is already true.

So a reference is only ever judged when THE MODULE EXISTS AND THE SYMBOL DOES
NOT. A reference to ``daedalus/hermes/`` -- a package that has never existed --
is SKIPPED, not reported, because this module cannot tell a plan from drift and
will not guess. A reference to ``daedalus.sensitivity.no_such_thing`` is
reported, because ``daedalus/sensitivity.py`` is right there and does not
contain it: the document is describing live code and describing it wrongly.

Everything else errs the same way. Fenced code blocks are transcripts and
examples, so they are stripped. A module that will not parse is skipped. A
module with a star-import or a module-level ``__getattr__`` has names this
module cannot enumerate, so its references are skipped wholesale. Each skip is
COUNTED and reported, so "I did not check this" never reads as "this is fine".

THE ANTI-GAMING PROPERTY
------------------------
The island metric is gameable: remove a test, the module becomes ``unknown``,
the headline count falls and the dead code is untouched. A defect count over a
corpus the fixer can edit has exactly the same hole -- take the document out,
and every finding in it disappears.

So the measurement is a PAIR, and the pair is what is checked:

    resolving   references that name code which exists   (the denominator)
    broken      references that name code which does not (the finding)

There are two legitimate remedies for a broken reference, and this module
accepts both: make the reference name the symbol that exists now, or withdraw
the stale claim. Both leave ``resolving`` untouched. What is REFUSED is a fix
that lowers ``resolving`` -- taking out the whole file, or mangling it until
the extractor finds nothing. :func:`verify_fix` checks that FIRST, before it
checks whether the claim went away, precisely because taking the file out does
both at once and the deletion must not be masked by its own side effect.

Stated as an invariant: ``verify_fix`` can never return ``ok`` for a change
that reduced the number of references which resolve. A test pins it, including
the case where the fixer takes out the entire corpus.

NOTHING HERE WRITES ANYTHING
-----------------------------
This module reads ``.md`` files and parses ``.py`` files with :mod:`ast`. It
never imports the code it inspects (importing a module to ask what it defines
runs it), never spawns a process, and never writes. The paths a candidate
declares in ``proposed_paths`` are a SELECTION hint for the picker and are
never an authorisation to write -- see :func:`daedalus.spine.picker.admissibility`.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "DOC_GLOBS",
    "DocRefReport",
    "FixVerdict",
    "Reference",
    "check_denominator",
    "extract_references",
    "iter_doc_files",
    "reference_key",
    "resolve_reference",
    "scan",
    "verify_fix",
    "verify_fix_counts",
    "verify_fixes",
]

# Where prose lives. README.md is included because the policy names it
# explicitly as writable, so a defect there is actionable for the same reason.
DOC_GLOBS: tuple[str, ...] = ("docs/**/*.md", "README.md")

# An inline-code span. Deliberately single-backtick only: a fenced block is a
# transcript or an example, and examples name symbols that were never meant to
# exist.
_INLINE_CODE = re.compile(r"`([^`\n]+)`")

# A fence opener/closer in markdown.
_FENCE = re.compile(r"^\s{0,3}(```+|~~~+)")

# A list marker, so an indented list continuation is not mistaken for an
# indented code block.
_LIST_MARKER = re.compile(r"^(?:[-*+]\s|\d+[.)]\s|>)")

# Characters that mean the reference is a PATTERN, not a name: a glob, a
# placeholder, an ellipsis. Judging these would be judging a template.
_PLACEHOLDER = re.compile(r"[*?<>\[\]{}]|\.\.\.")

# A dotted reference: at least two segments, first segment lower-case-ish so
# `Path.resolve` and prose like `Foo.bar` do not enter as module paths.
_DOTTED = re.compile(r"^[a-z_][a-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")

# `path/to/mod.py::symbol` and `path/to/mod.py:symbol`. The colon form requires
# an IDENTIFIER after it, so `daedalus/interfaces/cli/entry.py:794` (a line number) is not read
# as a symbol that is missing.
_PATH_SYMBOL = re.compile(r"^([\w./-]+\.py)::?([A-Za-z_][A-Za-z0-9_]*)$")

# A bare in-repo module path, no symbol.
_PATH_ONLY = re.compile(r"^[\w./-]+\.py$")

# Attributes every module has at runtime that no source line declares. Asking
# ast whether `daedalus` defines `__file__` gets the answer "no", which is true
# of the SOURCE and false of the module. Measured: `daedalus.__file__` in
# docs/adrs/015 was reported broken by the first version of this file.
_MODULE_DUNDERS: frozenset[str] = frozenset({
    "__file__", "__name__", "__doc__", "__path__", "__package__", "__spec__",
    "__loader__", "__dict__", "__builtins__", "__version__",
})

# A dotted reference whose last segment is one of these is a FILENAME, not an
# attribute. Measured: `room.md` and `parse.rs` were both reported as missing
# attributes of runs/council/room.py and daedalus/structcore/parse.py.
_FILE_EXTENSIONS: frozenset[str] = frozenset({
    "md", "rs", "json", "yaml", "yml", "toml", "txt", "html", "htm", "css",
    "js", "jsx", "ts", "tsx", "sh", "ps1", "bat", "cfg", "ini", "lock", "log",
    "db", "sqlite", "csv", "xml", "png", "svg", "jpg", "gif", "pdf", "zip",
    "exe", "dll", "so", "dylib", "rst", "in", "out", "tmp", "bak", "env",
})

# Dotted inline-code spans that are demonstrably NOT module-symbol references.
# These are measured corpus ambiguities, not a general vocabulary blacklist:
#
# * ``core.autocrlf`` is Git's configuration key. A coincidental ``core.py``
#   made the suffix resolver reinterpret accurate historical prose as a missing
#   Python attribute.
# * ``status.code`` is an ``OperationStatus`` instance attribute. A coincidental
#   ``status.py`` made the same mistake.
#
# The scanner dispatches autonomous edits, so a known false positive must be
# skipped explicitly rather than left to a writer to "improve" into falsehood.
_NON_MODULE_DOTTED_NAMES: frozenset[str] = frozenset({
    "core.autocrlf",
    "status.code",
})


# --------------------------------------------------------------------------- #
# records                                                                      #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Reference:
    """One documentation reference to code, and what became of it."""

    doc_path: str          # repo-relative, forward slashes
    line: int              # 1-based
    raw: str               # the text inside the backticks, as written
    module_path: str = ""  # repo-relative .py the reference resolved TO
    symbol: str = ""       # the attribute chain after the module, dotted
    state: str = "skipped"  # 'resolving' | 'broken' | 'suspect' | 'skipped'
    why: str = ""          # why it was skipped, or what is missing
    anchored: bool = False  # the author named a FILE, not a bare dotted word

    def to_dict(self) -> dict:
        return {"doc_path": self.doc_path, "line": self.line, "raw": self.raw,
                "module_path": self.module_path, "symbol": self.symbol,
                "state": self.state, "why": self.why, "anchored": self.anchored}


def reference_key(ref: Reference) -> str:
    """The identity of a reference ACROSS an edit.

    Deliberately excludes the line number: correcting a sentence above moves
    every reference below it, and a key that moved with them would report the
    original finding as "withdrawn" for every unrelated edit in the file.
    """
    return f"{ref.doc_path}|{ref.raw}"


@dataclass(frozen=True)
class DocRefReport:
    """The measurement: what resolves, what does not, and what was not checked.

    ``resolving`` is not decoration. It is the denominator that makes the
    ``broken`` count un-gameable -- see the module docstring.
    """

    resolving: tuple[Reference, ...] = ()
    broken: tuple[Reference, ...] = ()
    skipped: tuple[Reference, ...] = ()
    files_scanned: int = 0
    skipped_in_code_block: int = 0
    errors: tuple[str, ...] = ()

    @property
    def n_resolving(self) -> int:
        return len(self.resolving)

    @property
    def n_broken(self) -> int:
        return len(self.broken)

    def broken_in(self, doc_path: str) -> int:
        return sum(1 for r in self.broken if r.doc_path == doc_path)

    def resolving_in(self, doc_path: str) -> int:
        return sum(1 for r in self.resolving if r.doc_path == doc_path)

    def to_dict(self) -> dict:
        return {
            "n_resolving": self.n_resolving,
            "n_broken": self.n_broken,
            "n_skipped": len(self.skipped),
            "files_scanned": self.files_scanned,
            "skipped_in_code_block": self.skipped_in_code_block,
            "broken": [r.to_dict() for r in self.broken],
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class FixVerdict:
    """Whether an attempted fix actually fixed anything.

    ``ok`` is False for ``evidence_destroyed`` no matter what else happened.
    """

    ok: bool
    verdict: str
    detail: str
    resolving_before: int = 0
    resolving_after: int = 0

    def to_dict(self) -> dict:
        return {"ok": self.ok, "verdict": self.verdict, "detail": self.detail,
                "resolving_before": self.resolving_before,
                "resolving_after": self.resolving_after}


# --------------------------------------------------------------------------- #
# extraction                                                                   #
# --------------------------------------------------------------------------- #
def iter_doc_files(repo_root: str | Path) -> tuple[Path, ...]:
    """Every prose file in the corpus, sorted, deduplicated."""
    root = Path(repo_root)
    found: list[Path] = []
    for pattern in DOC_GLOBS:
        found.extend(p for p in root.glob(pattern) if p.is_file())
    return tuple(sorted(set(found)))


def _strip_code_blocks(text: str) -> tuple[list[tuple[int, str]], int]:
    """Return ``[(line_no, line)]`` for prose lines, plus how many were dropped.

    Two kinds of code are dropped: fenced blocks, and lines indented four or
    more spaces that are not list continuations. Both carry examples and
    transcripts, which name symbols that were never supposed to exist. The
    dropped COUNT is returned so "not checked" is reported rather than implied.
    """
    prose: list[tuple[int, str]] = []
    dropped = 0
    fence: str | None = None
    for i, line in enumerate(text.splitlines(), 1):
        m = _FENCE.match(line)
        if m:
            token = m.group(1)[:3]
            if fence is None:
                fence = token
            elif line.strip().startswith(fence):
                fence = None
            dropped += 1
            continue
        if fence is not None:
            dropped += 1
            continue
        stripped = line.lstrip()
        if line[:4] == "    " and stripped and not _LIST_MARKER.match(stripped):
            dropped += 1
            continue
        prose.append((i, line))
    return prose, dropped


def extract_references(text: str, doc_path: str) -> tuple[
        tuple[Reference, ...], int]:
    """Pull candidate code references out of one prose file.

    Returns ``(references, lines_dropped_as_code)``. Everything returned is
    UNRESOLVED -- shape only. :func:`resolve_reference` decides what is true.
    """
    prose, dropped = _strip_code_blocks(text)
    refs: list[Reference] = []
    for line_no, line in prose:
        for span in _INLINE_CODE.findall(line):
            raw = span.strip()
            # A trailing call suffix is how prose names a function; it is not
            # part of the name.
            probe = raw[:-2].strip() if raw.endswith("()") else raw
            if not probe or _PLACEHOLDER.search(probe):
                continue
            if _PATH_SYMBOL.match(probe) or _DOTTED.match(probe) or \
                    _PATH_ONLY.match(probe):
                refs.append(Reference(doc_path=doc_path, line=line_no, raw=raw))
    return tuple(refs), dropped


# --------------------------------------------------------------------------- #
# resolution                                                                   #
# --------------------------------------------------------------------------- #
# Trees that are not the source of truth. ``build/`` is the killer: it holds a
# COPY of daedalus/, so without this every basename in the repo is ambiguous and
# suffix resolution silently resolves nothing at all.
_EXCLUDED_DIRS: frozenset[str] = frozenset({
    "build", "dist", ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".worktrees", "site-packages", ".room",
})

_GENERATED_PYTHON_ROOTS: tuple[str, ...] = (
    "apps/web/src-tauri/backend",
    "apps/web/src-tauri/target",
)


def _repository_python_files(root: Path) -> list[Path]:
    """Every ``*.py`` in THIS checkout, nested checkouts excluded.

    A NESTED CHECKOUT MAKES EVERY MODULE AMBIGUOUS AT ONCE, and ambiguity is
    this module's absent-module case (see :func:`_suffix_index`). A second copy
    of the tree therefore does not add noise at the margin -- it turns the
    resolver off, and the report that comes out says "no document mentions
    this module" about modules that are mentioned, which reads exactly like
    real drift.

    MEASURED 2026-08-26 on the live tree, with a git worktree checked out under
    ``.claude/worktrees/`` (git-excluded, so ``git status`` showed nothing):
    3622 ambiguous path suffixes, of which **3242 were ambiguous only because
    of that checkout**. Nine in ten. The name-based exclusion above could not
    see it: the excluded set holds ``.worktrees`` but the directory in the tree
    was ``.claude/worktrees``, and a list of names is always one name behind.

    The rule is structural instead of nominal: a directory holding a ``.git``
    entry is another repository -- a file for a worktree, a directory for a
    clone -- and ``root`` itself is never tested, since the walk enters it
    before any test applies. Pruned while walking, so a deep nested checkout
    costs nothing to skip.
    """

    import os

    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in _EXCLUDED_DIRS
            and not (here / name / ".git").exists()
            and not (here / name).relative_to(root).as_posix().startswith(
                _GENERATED_PYTHON_ROOTS
            )
        )
        for name in sorted(filenames):
            if name.endswith(".py"):
                found.append(here / name)
    return found


def _suffix_index(root: Path) -> dict[str, tuple[str, ...]]:
    """Map every path SUFFIX of every module to the files that end with it.

    Prose names modules the way a person would -- ``sensitivity.py``,
    ``spine/containment.py`` -- not from the repo root. Measured: 370 of 374
    skipped references were relative like this, so a root-anchored resolver was
    declining to check the overwhelming majority of the corpus and reporting a
    confident zero.

    A suffix resolves ONLY when exactly one module ends with it. Ambiguity is
    the absent-module case: two files named ``index.py`` mean this module cannot
    tell which one the sentence is about, and guessing would manufacture a
    finding against a file the author never mentioned.
    """
    index: dict[str, list[str]] = {}
    for path in _repository_python_files(root):
        rel_parts = path.relative_to(root).parts
        rel = "/".join(rel_parts)
        for i in range(len(rel_parts)):
            index.setdefault("/".join(rel_parts[i:]), []).append(rel)
    return {k: tuple(sorted(set(v))) for k, v in index.items()}


def _module_file(root: Path, parts: Sequence[str],
                 suffixes: Mapping[str, tuple[str, ...]] | None = None) -> Path | None:
    rel = "/".join(parts)
    for candidate in (root / f"{rel}.py", root / rel / "__init__.py"):
        if candidate.is_file():
            return candidate
    if suffixes is not None:
        for probe in (f"{rel}.py", f"{rel}/__init__.py"):
            hits = suffixes.get(probe)
            if hits is not None and len(hits) == 1:
                return root / hits[0]
    return None


def _collect_names(body: Iterable[ast.stmt]) -> tuple[
        set[str], dict[str, set[str]], bool]:
    """Top-level names, class members, and whether the namespace is DYNAMIC.

    Walks into module-level ``if``/``try`` bodies, because a conditional or
    guarded import is a normal way to define a public name and missing it would
    manufacture a false "this symbol does not exist".
    """
    names: set[str] = set()
    classes: dict[str, set[str]] = {}
    dynamic = False
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
            if node.name == "__getattr__":
                # PEP 562: the module answers for names nothing declares.
                dynamic = True
        elif isinstance(node, ast.ClassDef):
            names.add(node.name)
            members: set[str] = set()
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef,
                                    ast.ClassDef)):
                    members.add(sub.name)
                elif isinstance(sub, ast.Assign):
                    members.update(t.id for t in sub.targets
                                   if isinstance(t, ast.Name))
                elif isinstance(sub, ast.AnnAssign) and isinstance(
                        sub.target, ast.Name):
                    members.add(sub.target.id)
            classes[node.name] = members
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "*":
                    dynamic = True  # cannot enumerate what a star brought in
                    continue
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, (ast.If, ast.Try)):
            sub_names, sub_classes, sub_dynamic = _collect_names(node.body)
            names |= sub_names
            classes.update(sub_classes)
            dynamic = dynamic or sub_dynamic
            for extra in (getattr(node, "orelse", []),
                          getattr(node, "finalbody", [])):
                more_names, more_classes, more_dynamic = _collect_names(extra)
                names |= more_names
                classes.update(more_classes)
                dynamic = dynamic or more_dynamic
            for handler in getattr(node, "handlers", []):
                h_names, h_classes, h_dynamic = _collect_names(handler.body)
                names |= h_names
                classes.update(h_classes)
                dynamic = dynamic or h_dynamic
    return names, classes, dynamic


def _parse_cache(cache: dict, root: Path, module: Path) -> tuple[
        set[str], dict[str, set[str]], bool, str]:
    key = str(module)
    if key in cache:
        return cache[key]
    try:
        source = module.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except (OSError, SyntaxError, ValueError) as e:
        result = (set(), {}, True, f"{type(e).__name__}: {e}")
    else:
        names, classes, dynamic = _collect_names(tree.body)
        result = (names, classes, dynamic, "")
    cache[key] = result
    return result


def resolve_reference(ref: Reference, repo_root: str | Path,
                      cache: dict | None = None) -> Reference:
    """Decide whether ``ref`` names code that exists. Never raises.

    The precondition for judging AT ALL is that the module resolves. A
    reference whose module is absent is ``skipped`` -- see the module docstring
    on why that is the entire false-positive filter.
    """
    root = Path(repo_root)
    cache = {} if cache is None else cache
    suffixes = cache.get("__suffixes__")
    if suffixes is None:
        suffixes = cache["__suffixes__"] = _suffix_index(root)
    probe = ref.raw[:-2].strip() if ref.raw.endswith("()") else ref.raw
    if probe in _NON_MODULE_DOTTED_NAMES:
        return Reference(**{
            **ref.__dict__,
            "state": "skipped",
            "why": "known non-module dotted name; a coincidental module basename "
                   "must not turn it into an autonomous edit target",
        })

    def _by_path(rel_path: str) -> Path | None:
        direct = root / rel_path
        if direct.is_file():
            return direct
        hits = suffixes.get(rel_path.lstrip("./"))
        return (root / hits[0]) if hits is not None and len(hits) == 1 else None

    module: Path | None = None
    chain: tuple[str, ...] = ()
    anchored = False

    m = _PATH_SYMBOL.match(probe)
    if m:
        candidate = _by_path(m.group(1))
        if candidate is not None:
            # `path/to/mod.py::symbol` is a COMMITMENT by the author: a .py file
            # and a name inside it. No competing reading exists, so a failure
            # here is a finding rather than a guess about what they meant.
            module, chain, anchored = candidate, (m.group(2),), True
    elif _PATH_ONLY.match(probe):
        candidate = _by_path(probe)
        if candidate is not None:
            module, chain, anchored = candidate, (), True
    elif _DOTTED.match(probe):
        parts = probe.split(".")
        if parts[-1].lower() in _FILE_EXTENSIONS:
            return Reference(**{**ref.__dict__, "state": "skipped",
                                "why": f"ends in {parts[-1]!r}, so it names a "
                                       f"file rather than an attribute"})
        # LONGEST module prefix wins: `daedalus.spine.picker.build_queue` must
        # resolve to the module picker.py, not stop at the package daedalus.
        for n in range(len(parts), 0, -1):
            found = _module_file(root, parts[:n], suffixes)
            if found is not None:
                module, chain = found, tuple(parts[n:])
                # ANCHORED only if the dotted prefix is a real module path from
                # the repo root. `daedalus.council.vendors` is; a bare `vendors`
                # resolved through the suffix index is not -- see the note on
                # _suffix_index and the measured false positives below.
                anchored = _module_file(root, parts[:n], None) is not None
                break

    if module is None:
        return Reference(**{**ref.__dict__, "state": "skipped",
                            "why": "no module of that name is in the tree, so "
                                   "this may be a plan or a record of something "
                                   "taken out -- not judged"})

    rel = module.relative_to(root).as_posix()
    if not chain:
        return Reference(**{**ref.__dict__, "module_path": rel,
                            "state": "resolving",
                            "why": "names a module that exists"})

    names, classes, dynamic, error = _parse_cache(cache, root, module)
    if error:
        return Reference(**{**ref.__dict__, "module_path": rel,
                            "symbol": ".".join(chain), "state": "skipped",
                            "why": f"module could not be read as Python ({error})"})
    if dynamic:
        return Reference(**{**ref.__dict__, "module_path": rel,
                            "symbol": ".".join(chain), "state": "skipped",
                            "why": "module has a star-import or a module-level "
                                   "__getattr__, so its public names cannot be "
                                   "enumerated without running it"})

    head = chain[0]
    if head in _MODULE_DUNDERS:
        return Reference(**{**ref.__dict__, "module_path": rel,
                            "symbol": ".".join(chain), "state": "resolving",
                            "why": "names an attribute the interpreter supplies "
                                   "on every module"})
    if head not in names:
        # A METHOD documented by its bare name. Prose writes
        # `ollama.py::_run_rewrite` for a method of the class in that file, and
        # pytest's own `file.py::name` addresses a top-level function, so both
        # spellings are in use for the same thing. Measured: the first version
        # of this file called TWO methods missing -- ollama.py::_run_rewrite
        # (line 423) and a test at line 183 -- because it looked only at module
        # scope. Accepting any class member is deliberately LOOSE: it can only
        # turn a finding into a non-finding, which is the direction a checker
        # that dispatches work is allowed to be wrong in.
        owner = next((cls for cls, members in sorted(classes.items())
                      if head in members), None)
        if owner is not None:
            return Reference(**{**ref.__dict__, "module_path": rel,
                                "symbol": ".".join(chain), "state": "resolving",
                                "why": f"{rel} defines {head!r} as a member of "
                                       f"{owner!r}"})
        if module.name == "__init__.py":
            # `daedalus.nemesis` against daedalus/__init__.py. The reference
            # names a SUBMODULE that is not in the tree, which is the absent-
            # module case, not the absent-symbol case -- and absent modules are
            # not judged, for the reason the module docstring gives. Measured:
            # the first version of this file reported four of these, and all
            # four were prose that was already correct. `daedalus.nemesis` and
            # `daedalus.cerberus` are log ACTOR names in a namespace convention
            # and `daedalus.root` is a VS Code settings key -- none of the three
            # is a Python attribute at all.
            return Reference(**{**ref.__dict__, "module_path": rel,
                                "symbol": ".".join(chain), "state": "skipped",
                                "why": (f"names {head!r} under the package {rel} "
                                        f"but no such submodule is in the tree; "
                                        f"an absent module is not judged")})
        return Reference(**{**ref.__dict__, "module_path": rel,
                            "symbol": ".".join(chain), "state": "broken",
                            "why": f"{rel} defines no {head!r}"})
    if len(chain) >= 2 and head in classes:
        member = chain[1]
        if member not in classes[head]:
            return Reference(**{**ref.__dict__, "module_path": rel,
                                "symbol": ".".join(chain), "state": "broken",
                                "why": f"{rel} has {head!r} but it has no "
                                       f"{member!r}"})
    return Reference(**{**ref.__dict__, "module_path": rel,
                        "symbol": ".".join(chain), "state": "resolving",
                        "why": f"{rel} defines {head!r}"})


def _rel_key(path: str | Path) -> str:
    """Normalise a repo-relative path the way :class:`Reference` records one."""
    text = str(path).replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


def scan(repo_root: str | Path, doc_files: Sequence[Path] | None = None,
         overrides: Mapping[str, str | None] | None = None) -> DocRefReport:
    """Measure the whole prose corpus against the tree. Never raises.

    ``overrides`` maps a repo-relative doc path to the text to scan INSTEAD of
    whatever is on disk, or to ``None`` meaning "this file does not exist in the
    snapshot being measured". It exists so a caller that remembers what a
    document said BEFORE an edit can compute the before-report exactly, without
    moving files and without disturbing ``doc_path`` -- which is half of
    :func:`reference_key`, so a relocated corpus would make every finding look
    withdrawn.

    The MODULE tree is read from ``repo_root`` on both sides. That is deliberate:
    the denominator compares two prose snapshots against ONE tree, so a
    difference in ``resolving`` is attributable to the prose edit and to nothing
    else. It is not a general time machine and must not be used as one.
    """
    root = Path(repo_root)
    files = tuple(doc_files) if doc_files is not None else iter_doc_files(root)
    over: dict[str, str | None] = {
        _rel_key(k): v for k, v in (overrides or {}).items()}
    cache: dict = {}
    resolving: list[Reference] = []
    broken: list[Reference] = []
    skipped: list[Reference] = []
    errors: list[str] = []
    dropped_total = 0
    scanned = 0

    planned: list[tuple[str, Path | None]] = []
    seen: set[str] = set()
    for path in files:
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            rel = path.as_posix()
        rel = _rel_key(rel)
        if rel in seen:
            continue
        seen.add(rel)
        planned.append((rel, path))
    # An override may ADD a document the snapshot on disk no longer has -- the
    # deletion case, which is the one the denominator exists to catch.
    for rel in sorted(over):
        if rel not in seen and over[rel] is not None:
            seen.add(rel)
            planned.append((rel, None))

    for rel, path in planned:
        if rel in over:
            text = over[rel]
            if text is None:
                continue            # absent in this snapshot: not scanned, not an error
        elif path is None:
            continue
        else:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                errors.append(f"{path}: {type(e).__name__}: {e}")
                continue
        scanned += 1
        refs, dropped = extract_references(text, rel)
        dropped_total += dropped
        for ref in refs:
            settled = resolve_reference(ref, root, cache)
            if settled.state == "resolving":
                resolving.append(settled)
            elif settled.state == "broken":
                broken.append(settled)
            else:
                skipped.append(settled)

    return DocRefReport(
        resolving=tuple(resolving), broken=tuple(broken), skipped=tuple(skipped),
        files_scanned=scanned, skipped_in_code_block=dropped_total,
        errors=tuple(errors))


# --------------------------------------------------------------------------- #
# verification -- the anti-gaming half                                         #
# --------------------------------------------------------------------------- #
def check_denominator(resolving_before: int, resolving_after: int) -> FixVerdict | None:
    """The denominator half, on its own. ``None`` means the denominator HELD.

    Extracted so the ordering that makes this module safe is STRUCTURAL rather
    than a paragraph of prose asking the next caller to be careful. Every path
    that judges a prose fix goes through here first, because
    :func:`verify_fix_counts` calls it on its first line and there is no other
    way in.

    It takes counts, not reports, because the count is all the rule needs and a
    caller that only has a remembered number (the queue's pick-time
    measurement, carried on a gate command line) must be able to apply the same
    rule as one holding both full reports.
    """
    if resolving_after < resolving_before:
        return FixVerdict(
            ok=False, verdict="evidence_destroyed",
            resolving_before=resolving_before, resolving_after=resolving_after,
            detail=(f"the corpus went from {resolving_before} to "
                    f"{resolving_after} references that resolve. A fix may "
                    f"correct a claim or withdraw one; it may not reduce the "
                    f"documentation that was already true. This is refused "
                    f"whatever happened to the finding itself."))
    return None


def verify_fix_counts(resolving_before: int, after: DocRefReport,
                      target: Reference | Mapping[str, Any]) -> FixVerdict:
    """:func:`verify_fix` with the before-side reduced to its one load-bearing
    number, for callers that never held the before-report."""
    destroyed = check_denominator(resolving_before, after.n_resolving)
    if destroyed is not None:
        return destroyed

    key = (reference_key(target) if isinstance(target, Reference)
           else f"{target.get('doc_path')}|{target.get('raw')}")

    still_broken = any(reference_key(r) == key for r in after.broken)
    if still_broken:
        return FixVerdict(
            ok=False, verdict="still_broken",
            resolving_before=resolving_before, resolving_after=after.n_resolving,
            detail="the reference is still in the file and still names code "
                   "that is not there")

    now_resolving = any(reference_key(r) == key for r in after.resolving)
    if now_resolving:
        return FixVerdict(
            ok=True, verdict="fixed",
            resolving_before=resolving_before, resolving_after=after.n_resolving,
            detail="the reference now names code that exists")
    return FixVerdict(
        ok=True, verdict="claim_withdrawn",
        resolving_before=resolving_before, resolving_after=after.n_resolving,
        detail=("the reference is gone and no reference that resolved was lost "
                "-- the stale claim was withdrawn, which is the other honest "
                "remedy"))


def verify_fix(before: DocRefReport, after: DocRefReport,
               target: Reference | Mapping[str, Any]) -> FixVerdict:
    """Did the attempted fix fix the thing, without destroying the evidence?

    ORDER IS THE SAFETY PROPERTY. The denominator is checked FIRST. Taking the
    document out withdraws the claim AND lowers ``resolving`` in one move, so a
    check that asked "is the claim gone?" first would call that a success and
    reward exactly the behaviour the island metric already taught this repo to
    expect. Asking about the denominator first makes the deletion visible no
    matter what it did to the finding.

    Both honest remedies pass: naming the symbol that exists now (``fixed``) and
    withdrawing the stale claim (``claim_withdrawn``). Neither lowers the count
    of references that resolve.

    KNOW WHERE ``target`` CAME FROM. ``claim_withdrawn`` is the verdict for a
    key found in neither list, and that reading is only sound when the target
    was taken from ``before.broken``: then absence really does mean the sentence
    went. A caller that reconstructs a target from somewhere else -- a command
    line, a serialised and TRUNCATED copy in a queue's evidence -- can produce a
    key that never matched anything, and will be told the claim was honourably
    withdrawn. Such a caller must establish independently that the claim was
    there to withdraw; :mod:`daedalus.spine.docref_gate` does it by requiring the
    text to be gone from the document.
    """
    return verify_fix_counts(before.n_resolving, after, target)


def verify_fixes(resolving_before: int, after: DocRefReport,
                 targets: Sequence[Reference | Mapping[str, Any]]) -> tuple[
                     bool, tuple[FixVerdict, ...]]:
    """Judge a whole document's worth of findings under ONE denominator check.

    The denominator is a property of the corpus, not of any one reference, so it
    is asked once and asked FIRST: if the evidence was destroyed, that is the
    only verdict returned and no per-reference verdict is manufactured to sit
    beside it looking reassuring.

    NO EMPTY GREEN. An empty ``targets`` returns ``False``. Verifying nothing is
    not the same as verifying something and finding it sound, and a gate that
    passed on zero targets would turn "we lost the findings" into a green tick
    -- which is the exact shape of failure the rest of this harness exists to
    refuse.
    """
    destroyed = check_denominator(resolving_before, after.n_resolving)
    if destroyed is not None:
        return False, (destroyed,)
    verdicts = tuple(verify_fix_counts(resolving_before, after, t) for t in targets)
    return bool(verdicts) and all(v.ok for v in verdicts), verdicts
