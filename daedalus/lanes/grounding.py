"""Does what a model ASSERTED correspond to what is actually in the tree?

One module, one question. It has two shapes:

* a model cites ``daedalus/spine/attempt.py:run_attempt`` -- is that file there,
  is that symbol in it? (:func:`audit_references`)
* a model says "X is never defined" -- can that be refuted mechanically?
  (:func:`judge`)

They are the same question about the same repository and they share the same
index, so they live together. They were briefly implemented twice -- once in
``lanes/checks.py`` for reports and once in ``tools/funnel_report.py`` for
funnel output -- and the two agreed numerically, which is the flattering way to
describe duplication. This module is the merge. ``lanes/__init__`` already
argues the general case:

    "Nobody decided that. It is what per-provider copies do when one of them
    improves."

WHY IT IS SEPARATE FROM ``checks.py``
-------------------------------------
``checks.py`` asks whether a file a lane is about to WRITE is intact -- it runs
before bytes hit the disk and returns a refusal. This asks whether a model's
PROSE corresponds to the tree, and it returns a measurement. Different subject,
different consumer, different failure mode; the same file would have been two
things wearing one name.

WHAT THIS IS
------------
A GRAMMAR check. It answers "does this name exist", never "is this claim true".
MEASURED 2026-07-30: a finding whose every reference resolved, which survived
an adversarial review tier and ranked first in the resulting plan, was false --
`derive_task_from_commit` does populate the fields it was accused of ignoring,
at `correctness.py:1444`. Nothing here would have caught that. Advertising it
as a semantic check is the overclaim the master plan's section 4 forbids.

It is also, deliberately, an OBSERVATION rather than a refusal. A report may
legitimately name a runtime path or a file in another repository, and a fence
that refused those would be wrong far more often than right. Turning any of
this into a gate is a separate decision needing its own evidence.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping

__all__ = [
    "ReferenceAudit",
    "audit_references",
    "claim_text",
    "defined_in",
    "imported_in",
    "judge",
    "module_names",
]


# --------------------------------------------------------------------------
# what a module provides
# --------------------------------------------------------------------------

_DEF_RE = re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+(\w+)", re.MULTILINE)
_ASSIGN_RE = re.compile(r"^\s*(\w+)\s*(?::[^=]+)?=", re.MULTILINE)
_IMPORT_RE = re.compile(r"^\s*(?:from\s+[\w.]+\s+)?import\s+(.+)$", re.MULTILINE)


def defined_in(source: str) -> frozenset[str]:
    """Names this file DEFINES: def, class, module-level assignment."""
    return frozenset(_DEF_RE.findall(source)) | frozenset(_ASSIGN_RE.findall(source))


def imported_in(source: str) -> frozenset[str]:
    """Names this file BORROWS.

    Kept apart from :func:`defined_in` on purpose. A finding saying "X is not
    defined here" about a name the file imports is loose rather than false, and
    a metric whose whole job is proving things false must not spend its
    credibility on that distinction being blurred.
    """
    found: set[str] = set()
    for clause in _IMPORT_RE.findall(source):
        for part in clause.split(","):
            name = part.strip().split(" as ")[-1].strip().strip("()")
            if name.isidentifier():
                found.add(name)
    return frozenset(found)


def module_names(source: str) -> frozenset[str]:
    """Every def/class at ANY depth, plus module-level bindings and imports.

    Unlike ``checks.toplevel_defs``, this descends: a citation naming
    ``events.py:TransportRecord.from_dict`` is naming a method, and a
    top-level-only reading would report every method in the repository absent.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return frozenset()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.alias):
            names.add((node.asname or node.name).split(".")[0])
    return frozenset(names)


# --------------------------------------------------------------------------
# citations: "see daedalus/spine/attempt.py:run_attempt"
# --------------------------------------------------------------------------

_REFERENCE = re.compile(
    r"\b((?:[A-Za-z_][\w.\-]*/)+[\w.\-]+\.\w{1,4})(?::([\w.]+))?")


@dataclass(frozen=True)
class ReferenceAudit:
    """What a report's file/symbol citations resolve to.

    The split is the whole value. MEASURED 2026-07-30 over a four-tier advisory
    funnel: of 42 unresolvable paths in its planning tier, 19 were a real file
    with its directory dropped, 1 shared a basename with another file, and 22
    named a file that exists nowhere. Those need opposite responses -- repair,
    refuse to guess, discard -- and one number for all three is worth little.
    """

    cited: int = 0
    resolved: int = 0
    #: (as written, what it almost certainly meant)
    repaired: tuple[tuple[str, str], ...] = ()
    #: basename matches more than one file; unresolvable without guessing
    ambiguous: tuple[str, ...] = ()
    #: no file of that NAME exists anywhere in the repository
    invented: tuple[str, ...] = ()
    #: (path, symbol) where the file is real and the symbol is not in it
    absent_symbols: tuple[tuple[str, str], ...] = ()

    @property
    def rate(self) -> float:
        return self.resolved / self.cited if self.cited else 0.0

    @property
    def invention_rate(self) -> float:
        return len(self.invented) / self.cited if self.cited else 0.0

    def to_dict(self) -> dict:
        return {
            "cited": self.cited,
            "resolved": self.resolved,
            "rate": round(self.rate, 4),
            "invented": list(self.invented),
            "invention_rate": round(self.invention_rate, 4),
            "repaired": [list(pair) for pair in self.repaired],
            "ambiguous": list(self.ambiguous),
            "absent_symbols": [list(pair) for pair in self.absent_symbols],
        }


def audit_references(text: str, tracked: Mapping[str, str] | Iterable[str],
                     repo_root: str | Path = ".") -> ReferenceAudit:
    """Resolve every path (and optional ``:symbol``) named in ``text``.

    ``tracked`` is the authoritative file list -- pass ``git ls-files`` output,
    never a filesystem walk, so ignored artefacts and a contributor's scratch
    files cannot make an invented path look real.
    """
    paths = set(tracked)
    by_base: dict[str, list[str]] = {}
    #: The repository's own top-level directories, derived from the file list
    #: rather than hardcoded. A cited path is an ASSERTION ABOUT THIS
    #: REPOSITORY only when it starts inside one of them.
    #:
    #: Without this anchor the audit reported the docstring example ``a/b.py``,
    #: the runtime path ``RUN_DIR/last_report.json`` and the written type
    #: ``Any/typing.Any`` as invented files -- all measured, all noise. An
    #: audit that cries wolf is one its reader learns to skip, which costs more
    #: than the check was ever worth.
    anchors: set[str] = set()
    for path in paths:
        by_base.setdefault(PurePosixPath(path).name, []).append(path)
        parts = PurePosixPath(path).parts
        if len(parts) > 1:
            anchors.add(parts[0])

    root = Path(repo_root)
    seen: set[tuple[str, str]] = set()
    resolved = 0
    repaired: list[tuple[str, str]] = []
    ambiguous: list[str] = []
    invented: list[str] = []
    absent: list[tuple[str, str]] = []
    cache: dict[str, frozenset[str]] = {}

    for cited_path, symbol in _REFERENCE.findall(text or ""):
        if PurePosixPath(cited_path).parts[0] not in anchors:
            continue                    # not a claim about this repository
        key = (cited_path, symbol or "")
        if key in seen:
            continue
        seen.add(key)

        real = cited_path
        if real not in paths:
            candidates = by_base.get(PurePosixPath(cited_path).name, [])
            if len(candidates) == 1:
                repaired.append((cited_path, candidates[0]))
                real = candidates[0]
            elif candidates:
                ambiguous.append(cited_path)
                continue
            else:
                invented.append(cited_path)
                continue

        if not symbol:
            resolved += 1
            continue
        if real not in cache:
            try:
                cache[real] = module_names(
                    (root / real).read_text(encoding="utf-8", errors="replace"))
            except OSError:
                cache[real] = frozenset()
        leaf = symbol.rsplit(".", 1)[-1]
        if symbol.isdigit() or leaf in cache[real] or symbol in cache[real]:
            resolved += 1
        else:
            absent.append((real, symbol))

    return ReferenceAudit(
        cited=len(seen), resolved=resolved, repaired=tuple(repaired),
        ambiguous=tuple(ambiguous), invented=tuple(invented),
        absent_symbols=tuple(absent))


# --------------------------------------------------------------------------
# existence claims: "X is never defined"
# --------------------------------------------------------------------------

#: Phrasings that assert a name is absent. Deliberately narrow: this judges
#: only claims it can decide, and a wider net would score claims about
#: BEHAVIOUR as if they were claims about EXISTENCE.
#:
#: `do|does` and not just `does`: a gold set caught "_body_sha and _entry_sha,
#: which do not exist" scoring undecided while the singular scored false. A
#: judge that sees one grammatical number has a blind spot nobody would think
#: to look for.
_ABSENCE = re.compile(
    r"\b(?:is\s+)?(?:not\s+defined|undefined|never\s+defined|missing|"
    r"not\s+imported|(?:do|does|did)\s+not\s+exist|no\s+definition|"
    r"not\s+present|never\s+assigned|referenced\s+but\s+not)\b",
    re.IGNORECASE)

#: A statement that scopes its own absence claim to the window it was shown.
#:
#: MEASURED: the first version of this judge marked "AgentCapabilities and
#: AgentEvent are not defined in this chunk" as provably false, because the
#: names are imported by the file. That finding is TRUE and honest -- it names
#: the scope it was given, and several such findings go on to say "expected to
#: be defined elsewhere". Scoring a correct self-limited observation as a lie
#: is the same cry-wolf failure this metric exists to count: 461 of them in one
#: run, before this rule.
_SELF_SCOPED = re.compile(
    r"\b(?:in|within|from)\s+(?:this|the\s+(?:given|provided|visible|current))\s+"
    r"(?:chunk|window|excerpt|snippet|fragment|section|portion)\b"
    r"|\bnot\s+(?:visible|shown|included)\b"
    r"|\b(?:defined|declared|imported|provided)\s+elsewhere\b"
    r"|\boutside\s+(?:this|the)\s+(?:chunk|window|excerpt|file)\b",
    re.IGNORECASE)

_NAME = re.compile(
    r"`(\w+)`|\b(_{0,2}[a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b|\b([A-Z][a-zA-Z0-9]{3,})\b")

_SEVERITIES = frozenset({"critical", "high", "medium", "low"})


def claim_text(raw: str) -> str:
    """The assertion, with any ``<where> | <severity> | ...`` prefix stripped.

    MEASURED: without this split, ``_resolve_store | medium | Mentions refusing
    paths under memory/ but code is truncated; the check may be missing`` was
    scored provably false because ``_resolve_store`` is defined -- but the
    finding never claimed otherwise. It is about a check INSIDE that function.
    Reading the location column as the subject manufactures a lie out of an
    honest observation.
    """
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) >= 3 and parts[1].lower() in _SEVERITIES:
        return parts[2]
    return raw


def candidate_names(text: str) -> set[str]:
    return {a or b or c for a, b, c in _NAME.findall(text) if (a or b or c)}


def judge(raw: str, module: str, defined: Mapping[str, frozenset[str] | set[str]],
          imported: Mapping[str, frozenset[str] | set[str]] | None = None,
          ) -> tuple[str, str]:
    """Decide whether one finding is provably wrong about the repository.

    Verdicts:

    ``false``            the named symbol is defined in the module it is
                         claimed absent from
    ``false-elsewhere``  it exists, in another module -- wrong about WHERE,
                         which is a different error needing a different repair
    ``scoped``           the claim limits itself to the window its reader saw,
                         so it asserts nothing about the program
    ``undecided``        this cannot tell. **Not a pass.**

    It can prove a finding false. It can never prove one true.
    """
    text = claim_text(raw)
    if not _ABSENCE.search(text):
        return "undecided", "not an existence claim"
    if _SELF_SCOPED.search(text):
        return "scoped", "claim is limited to the window the reader was shown"
    here = defined.get(module)
    if here is None:
        return "undecided", f"module {module!r} not in the index"

    named = candidate_names(text)
    borrowed = set((imported or {}).get(module, ()))
    hits = sorted(n for n in named if n in here and n not in borrowed)
    if hits:
        return "false", (f"claims absence, but {', '.join(hits[:3])} "
                         f"is defined in {module}")
    if any(n in borrowed for n in named):
        return "undecided", "named symbol is imported here, not defined here"
    everywhere = {n for n in named if any(n in s for s in defined.values())}
    if everywhere:
        return "false-elsewhere", (f"claims absence, but "
                                   f"{', '.join(sorted(everywhere)[:3])} "
                                   "exists elsewhere in the repository")
    return "undecided", "no named symbol resolved"
