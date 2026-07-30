"""The baseline every write lane runs before a model's output becomes a file.

Cheapest first, first refusal wins, fail-closed. A check returns "" to pass and
a human-readable reason to refuse; a check that RAISES is treated as a refusal,
because a guard that cannot answer must not be read as consent.

Every function here was lifted, not written: each one is a guard that already
existed in ``providers/deepseek.py`` and each carries the measurement that put
it there. The lift is the point -- see :mod:`daedalus.lanes`.

Deviation from the shape sketched in docs/HANDOFF_2026-07-30_NIGHT.md, which
proposed ``Check = (rel, original, proposed, repo_root, policy) -> str``: the
first four arguments are bundled into :class:`WriteAttempt`. Two of the baseline
checks need a fifth fact (is this file being CREATED, so that there is no
original to compare against), and a positional signature that has to grow every
time a check needs one more fact is a signature every lane has to be edited to
match. The dataclass grows instead.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Iterable, Sequence

__all__ = [
    "BASELINE",
    "BASELINE_POLICY",
    "Check",
    "CheckPolicy",
    "WriteAttempt",
    "imports_resolve",
    "no_elision",
    "not_substituted",
    "not_truncated",
    "parses",
    "run_checks",
    "toplevel_defs",
]


# --------------------------------------------------------------------------
# what a check is given
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class WriteAttempt:
    """One file a lane is about to write.

    ``original`` is the exact current text, or "" when ``creating``. Keeping the
    two facts separate rather than inferring "creating" from an empty original
    matters: a lane that truncates a real file to nothing must not be able to
    present that as a creation and skip the guards that only run on edits.
    """

    rel: str
    proposed: str
    repo_root: str
    original: str = ""
    creating: bool = False

    @property
    def is_python(self) -> bool:
        return self.rel.endswith(".py")


@dataclass(frozen=True)
class CheckPolicy:
    """The per-lane dials. Everything here is a claim about a MODEL, not about
    the repository -- which is exactly why it is a parameter and not a constant.
    """

    #: Phrases that mean "I did not return the whole file". A claim about what a
    #: particular vendor's model emits; two lanes may hold different tuples and
    #: neither is re-tuning the other. Only refused when the marker is NEW, so a
    #: file that legitimately contains the phrase does not become unwritable.
    elision_markers: tuple[str, ...] = ()
    #: Below this fraction of the original size, a "full rewrite" is a
    #: truncation.
    min_size_ratio: float = 0.5
    #: Below this fraction of surviving top-level definitions, a "rewrite" is a
    #: different file rather than an edited one. 0.5 is deliberately permissive:
    #: a genuine refactor can rename or merge a lot, and refusing a real change
    #: costs twice -- the work is lost AND the task escalates to a paid lane.
    #: The failures this exists to catch were TOTAL substitutions (0% survival),
    #: so a loose threshold still stops them.
    min_symbol_survival: float = 0.5
    #: Below this many top-level definitions the survival ratio is noise --
    #: losing one of two functions is an ordinary edit.
    min_symbols_to_judge: int = 3
    #: Import roots that belong to THIS repository. A missing third-party
    #: package is an environment question and none of this gate's business; a
    #: missing first-party module is a file the model invented.
    first_party_roots: tuple[str, ...] = ("daedalus", "tools", "tests")
    #: How many unresolved imports to name in a refusal before summarising.
    max_named_imports: int = 4


BASELINE_POLICY = CheckPolicy()

Check = Callable[[WriteAttempt, CheckPolicy], str]


# --------------------------------------------------------------------------
# shared AST helpers
# --------------------------------------------------------------------------

def toplevel_defs(source: str) -> frozenset[str] | None:
    """Top-level function and class names, or None if the text will not parse.

    Only the TOP level: a rewrite is free to reorganise nested helpers, and
    counting those would make ordinary refactors look like substitutions.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return None
    return frozenset(
        n.name for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))


def _module_path(root: Path, dotted: str) -> Path | None:
    parts = dotted.split(".")
    direct = root.joinpath(*parts).with_suffix(".py")
    if direct.is_file():
        return direct
    pkg = root.joinpath(*parts, "__init__.py")
    return pkg if pkg.is_file() else None


def _exports(path: Path) -> tuple[frozenset[str], bool]:
    """(top-level names, opaque).

    ``opaque`` means static reading is not authoritative for this module -- it
    star-imports or defines a module-level ``__getattr__``, either of which can
    legitimately provide a name no reader can see.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError, RecursionError):
        return frozenset(), True
    names: set[str] = set()
    opaque = False
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(n.name)
            if n.name == "__getattr__":
                opaque = True
        elif isinstance(n, ast.Assign):
            names.update(t.id for t in n.targets if isinstance(t, ast.Name))
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            names.add(n.target.id)
        elif isinstance(n, ast.ImportFrom):
            if any(a.name == "*" for a in n.names):
                opaque = True
            names.update(a.asname or a.name for a in n.names)
        elif isinstance(n, ast.Import):
            names.update((a.asname or a.name).split(".")[0] for a in n.names)
    return frozenset(names), opaque


# --------------------------------------------------------------------------
# the baseline checks
# --------------------------------------------------------------------------

def parses(attempt: WriteAttempt, policy: CheckPolicy) -> str:
    """A Python file that will not parse is not an improvement.

    Runs on CREATED files too, which is where the hole was: an edit that stops
    parsing was caught by :func:`not_substituted` as a side effect, but a
    brand-new module that does not parse had nothing looking at it -- the
    imports check returns early on a parse failure, calling it "a different
    guard's business". This is that guard.
    """
    if not attempt.is_python:
        return ""
    if toplevel_defs(attempt.proposed) is not None:
        return ""
    if not attempt.creating and toplevel_defs(attempt.original) is None:
        return ""          # cannot judge what was already unparsable
    try:
        ast.parse(attempt.proposed)
    except SyntaxError as exc:
        where = f" at line {exc.lineno}" if exc.lineno else ""
        return f"proposed content does not parse as Python{where}: {exc.msg}"
    except (ValueError, RecursionError) as exc:
        return f"proposed content does not parse as Python: {exc}"
    return ""              # pragma: no cover -- toplevel_defs disagreed


def not_truncated(attempt: WriteAttempt, policy: CheckPolicy) -> str:
    """The classic full-rewrite failure: the model returned part of the file."""
    if attempt.creating or not attempt.original:
        return ""
    if len(attempt.proposed) >= policy.min_size_ratio * len(attempt.original):
        return ""
    return (f"suspected truncation (under "
            f"{policy.min_size_ratio:.0%} of the original size)")


def no_elision(attempt: WriteAttempt, policy: CheckPolicy) -> str:
    """The model admitting, in prose, that it dropped code.

    Only NEW markers count. A file that already contained the phrase would
    otherwise become permanently unwritable by this lane.
    """
    if not policy.elision_markers:
        return ""
    low_new = attempt.proposed.lower()
    low_old = attempt.original.lower()
    marker = next((m for m in policy.elision_markers
                   if m in low_new and m not in low_old), None)
    if marker is None:
        return ""
    return (f"elision marker in output ('{marker}') -- "
            "file not fully rewritten")


def not_substituted(attempt: WriteAttempt, policy: CheckPolicy) -> str:
    """Why this "rewrite" looks like the WRONG FILE, or "" if it looks fine.

    MEASURED 2026-07-30, and the reason this exists. A change request naming two
    files is sent once per file; asked to rewrite ``daedalus/shift.py`` the model
    returned the contents of ``tests/test_shift.py``. The module was destroyed
    and the run reported ``status: done``. Three of five multi-file writes failed
    exactly this way.

    None of the other guards can see it. Truncation compares SIZE, and a
    substituted file is a perfectly normal size -- the test module was in fact
    larger than the module it replaced. Elision looks for a model admitting it
    omitted something, and nothing was omitted: a complete, valid, well-formed
    file arrived. It was simply the wrong one.

    So this asks the only question that separates the two cases: does the result
    still contain the thing that was sent? An edit keeps most of a file's
    top-level names; a substitution keeps none of them.

    Deliberately Python-only. The check needs a parser to be meaningful, and a
    guess about other languages would either fire on ordinary edits or provide
    false assurance for files it cannot actually read.
    """
    if not attempt.is_python or attempt.creating:
        return ""
    before = toplevel_defs(attempt.original)
    if before is None:
        return ""          # cannot judge what was already unparsable
    after = toplevel_defs(attempt.proposed)
    if after is None:
        # The original parsed and the replacement does not. Whatever this is, it
        # is not an improvement, and letting it land would break an import for
        # every consumer of the module.
        return "rewrite does not parse as Python while the original did"
    if len(before) < policy.min_symbols_to_judge:
        return ""
    survival = len(before & after) / len(before)
    if survival >= policy.min_symbol_survival:
        return ""
    lost = sorted(before - after)
    return (f"suspected content substitution: {len(before & after)} of "
            f"{len(before)} top-level definitions survive "
            f"({survival:.0%}); missing {', '.join(lost[:5])}"
            + (" ..." if len(lost) > 5 else ""))


def unresolved_first_party_imports(
    content: str, repo_root: str,
    roots: Sequence[str] = BASELINE_POLICY.first_party_roots,
) -> list[str]:
    """First-party imports in ``content`` that name nothing in the tree.

    MEASURED 2026-07-30. Twenty agents wrote test modules against source files
    they were given, and three of seven imported things that do not exist:
    ``daedalus.linting`` (it is ``daedalus.gui.lint``), ``ShiftManager`` from
    ``daedalus.shift`` (the class is ``Shift``), and ``daedalus.wiki_vault``
    (it is ``daedalus.wiki.vault``). All three are valid Python, so a syntax
    gate passes them, and all three reported ``status: done``.

    The check is STATIC on purpose. Importing the file to find out whether its
    imports resolve would execute module-level code from an untrusted lane --
    the one thing this repository refuses to do to decide whether to trust
    something.

    Conservative by construction, because a false refusal costs real work:

    * only first-party roots are judged;
    * a missing MODULE is reported, since that cannot be a re-export;
    * a missing NAME is reported only when the module has no star-import and no
      module-level ``__getattr__``.
    """
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError, RecursionError):
        return []          # a parse failure is a different guard's business
    root = Path(repo_root)
    bad: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if (alias.name.split(".")[0] in roots
                        and not _module_path(root, alias.name)):
                    bad.append(f"module '{alias.name}' does not exist")
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module:
                continue   # relative imports resolve against a package
            if node.module.split(".")[0] not in roots:
                continue
            path = _module_path(root, node.module)
            if path is None:
                bad.append(f"module '{node.module}' does not exist")
                continue
            names, opaque = _exports(path)
            if opaque:
                continue
            for alias in node.names:
                if alias.name == "*" or alias.name in names:
                    continue
                # `from daedalus import shift` binds a SUBMODULE, which is
                # perfectly valid and is named nowhere in the package's
                # __init__.py. Measured: without this the check fired on 40 of
                # 223 real files in this repo -- a false-positive rate that
                # would have made the gate useless and, worse, trained everyone
                # to ignore it.
                if _module_path(root, f"{node.module}.{alias.name}"):
                    continue
                bad.append(f"'{node.module}' does not define '{alias.name}'")
    # Deduplicated but order-preserving: the same bad import repeated ten times
    # is one problem, and the first occurrence is the one worth naming.
    return list(dict.fromkeys(bad))


def imports_resolve(attempt: WriteAttempt, policy: CheckPolicy) -> str:
    """Does it import things that exist?

    Checked for CREATED files too -- a brand-new test module against an invented
    API is exactly the failure this catches, and it has no original to compare
    against.
    """
    if not attempt.is_python:
        return ""
    bad = unresolved_first_party_imports(
        attempt.proposed, attempt.repo_root, policy.first_party_roots)
    if not bad:
        return ""
    cap = policy.max_named_imports
    extra = len(bad) - cap
    return ("unresolved first-party imports: " + "; ".join(bad[:cap])
            + (f" (+{extra} more)" if extra > 0 else ""))


#: Cheapest first. Order is load-bearing in one direction only -- the refusal a
#: caller sees should be the most specific one available, and "does not parse"
#: is more useful than "82% of definitions vanished" when both are true.
BASELINE: tuple[Check, ...] = (
    not_truncated,
    no_elision,
    parses,
    not_substituted,
    imports_resolve,
)


def run_checks(
    attempt: WriteAttempt,
    policy: CheckPolicy = BASELINE_POLICY,
    extra: Iterable[Check] = (),
) -> str:
    """Run the baseline, then any lane-specific additions. "" means write it.

    FAIL-CLOSED, and this is the part worth not losing: a check that raises is
    reported as a refusal naming the crash. The alternative -- letting the
    exception propagate, or catching it and continuing -- turns a broken guard
    into a silent permission, which is how a gate ends up passing a file that
    destroyed a module.

    A lane may pass ``extra`` to ADD checks. There is deliberately no argument
    for removing one from the baseline.
    """
    for check in (*BASELINE, *extra):
        name = getattr(check, "__name__", repr(check))
        try:
            reason = check(attempt, policy)
        except Exception as exc:            # noqa: BLE001 -- fail closed
            return (f"write check {name!r} failed to run "
                    f"({type(exc).__name__}: {exc}) -- refusing the write")
        if reason:
            return reason
    return ""


def with_markers(markers: Sequence[str],
                 policy: CheckPolicy = BASELINE_POLICY) -> CheckPolicy:
    """``policy`` with this lane's own elision markers. Convenience only."""
    return replace(policy, elision_markers=tuple(markers))
