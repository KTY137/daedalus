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
from typing import Callable, Iterable, Mapping, Sequence

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
    """Where a dotted first-party module lives, or None if nothing provides it.

    A directory WITHOUT ``__init__.py`` still counts. Since Python 3.3 such a
    directory is an implicit namespace package (PEP 420) and imports perfectly
    well -- ``tools`` and ``tests`` in this repository are exactly that, and
    both import fine while reporting ``__file__ is None``.

    MEASURED 2026-07-30: without this branch the gate reported "module 'tools'
    does not exist" for `tests/test_iron_plan_guard.py`, a real committed file
    that imports it, and `test_no_false_positives_across_the_real_tree` failed
    with its own message -- "this gate must never refuse real repo code". Any
    lane writing a module that imports `tools` or `tests` would have been
    refused for importing something that is demonstrably there.

    This does not loosen the guard. The invented imports it exists to catch --
    ``daedalus.linting``, ``daedalus.wiki_vault`` -- name directories that do
    not exist either, so they are still refused. A directory is required to
    contain at least one ``.py`` file, so an empty or data-only folder cannot
    launder an import that would fail at runtime.

    The returned directory is deliberately not a readable module: :func:`_exports`
    fails closed on it (an OSError becomes ``opaque=True``), which is the honest
    answer, because what a namespace package provides is its submodules and no
    single file lists them.
    """
    parts = dotted.split(".")
    direct = root.joinpath(*parts).with_suffix(".py")
    if direct.is_file():
        return direct
    pkg = root.joinpath(*parts, "__init__.py")
    if pkg.is_file():
        return pkg
    namespace = root.joinpath(*parts)
    if namespace.is_dir() and any(namespace.glob("*.py")):
        return namespace
    return None


#: How many alias hops :func:`_exports` will follow. The tree uses exactly one
#: (``daedalus/spine/*.py`` -> ``daedalus/kernel/events/*.py``); the bound is
#: here so that a cycle -- A aliasing B aliasing A -- terminates instead of
#: recursing until the interpreter does it for us.
_MAX_ALIAS_HOPS = 4


def _alias_target(tree: ast.Module) -> str | None:
    """The dotted module a file hands its own locator to, or ``None``.

    Recognises exactly one construct, the module alias::

        import sys as _sys
        from daedalus.kernel.events import ledger as _owner
        _sys.modules[__name__] = _owner

    After that statement runs, ``daedalus.spine.ledger`` IS the owner module
    object: every name the owner defines resolves through the old locator, and
    nothing this file's own body defines is reachable at all.

    MEASURED 2026-09-01 at 4efa2a53. Without this, :func:`_exports` read
    ``daedalus/spine/envelope.py`` literally and reported its exports as
    ``{_sys, _owner}``, so ``unresolved_first_party_imports`` refused 134 real
    committed files for importing names that demonstrably resolve at runtime --
    ``'daedalus.spine.envelope' does not define 'canonical_json'`` and 21 more
    of that shape. That is the failure mode this module already learned once
    from namespace packages (see :func:`_module_path`): a gate with false
    positives costs twice, because the work is discarded AND everyone is taught
    to ignore the gate.

    Deliberately narrow, because a reader taught to follow aliases can be taught
    to follow too much. All of these must hold:

    * the assignment is at MODULE scope -- a swap inside a function or an ``if``
      is not this construct and is not followed;
    * the subscripted object is ``<sys>.modules`` where ``<sys>`` is a name this
      same file bound to the real :mod:`sys` module, or a bare ``modules`` bound
      by ``from sys import modules``;
    * the key is literally ``__name__``, not some other module's name -- writing
      into another entry of ``sys.modules`` is a different act and is not an
      alias for THIS locator;
    * the right-hand side is a plain name that this same file bound with an
      import, so the target is statically known.

    Anything else returns ``None`` and the file is read literally, as before.
    """
    imports = _module_scope_imports(tree)
    target: str | None = None
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        dest, value = node.targets[0], node.value
        if not isinstance(value, ast.Name):
            continue
        if not _is_own_sys_modules_slot(dest, imports):
            continue
        # Last one wins, exactly as it would at runtime.
        target = imports.modules.get(value.id)
    return target


#: The two hooks that let a type answer with a name no reader of a module's top
#: level can enumerate. ``__getattr__`` is the one this tree uses; a custom
#: ``__getattribute__`` intercepts even more.
_DYNAMIC_ATTRIBUTE_HOOKS = frozenset({"__getattr__", "__getattribute__"})


def _installs_dynamic_module_protocol(tree: ast.Module) -> bool:
    """Does this file put a name-SYNTHESIZING type on its own module object?

    Recognises the second construct in this tree, ``daedalus/spine/attempt.py``::

        class _AttemptFacade(ModuleType):
            def __getattr__(self, name): return getattr(_owner, name)

        _module = sys.modules[__name__]
        _module.__class__ = _AttemptFacade

    After that, attribute lookup on ``daedalus.spine.attempt`` can answer with
    names no reader of this file's top level can enumerate, so :func:`_exports`
    reports ``opaque``.

    That is not a new concession. The gate already grants exactly this to the
    eleven modules in the tree that spell the same thing as a module-level
    ``def __getattr__`` (PEP 562). MEASURED 2026-09-01: without this branch the
    gate refused 34 real committed files with 24 distinct messages, every one of
    them ``'daedalus.spine.attempt' does not define '<a forwarded name>'``.

    The ``__getattr__`` requirement is the whole rule, and it is here because an
    earlier version of this function did not have it. ADVERSARIAL REVIEW
    2026-09-02 broke that version with nine lines::

        class _Facade(ModuleType):
            pass
        def real_function():
            return 1
        sys.modules[__name__].__class__ = _Facade

    An ordinary, working, non-crashing module -- and every invented import from
    it was accepted, because retyping alone was read as "unjudgeable". It is
    not: a ``ModuleType`` subclass with no hook forwards NOTHING, the module's
    own top level is still the whole truth, and ``from that import invented``
    raises ``ImportError`` at runtime. Requiring the hook puts this rule at
    exactly the cost of the PEP 562 rule beside it and buys no new surface: a
    file that wants to be unjudgeable has to actually install a forwarder, which
    it could already do in one line at module scope.

    The class must be a module-scope ``class`` statement in THIS file. An
    imported or expression-valued class is not resolvable here, and treating an
    unreadable one as a licence is the same mistake one paragraph up.

    Following through to the owner instead of going opaque was rejected: it
    would require proving statically that ``__getattr__`` forwards everything
    and synthesizes nothing, which is exactly the claim a reader of a class body
    cannot make.
    """
    dynamic_classes = {
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and any(
            isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
            and member.name in _DYNAMIC_ATTRIBUTE_HOOKS
            for member in node.body
        )
    }
    if not dynamic_classes:
        return False
    imports = _module_scope_imports(tree)
    own: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Subscript):
            continue
        if _is_own_sys_modules_slot(node.value, imports):
            own.update(t.id for t in node.targets if isinstance(t, ast.Name))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Name) or node.value.id not in dynamic_classes:
            continue
        for dest in node.targets:
            if not isinstance(dest, ast.Attribute) or dest.attr != "__class__":
                continue
            holder = dest.value
            if isinstance(holder, ast.Name) and holder.id in own:
                return True
            if _is_own_sys_modules_slot(holder, imports):
                return True
    return False


@dataclass(frozen=True)
class _ModuleScopeImports:
    """What a file's module-scope imports bound, as far as ``ast`` can tell."""

    sys_aliases: frozenset[str]
    modules_aliases: frozenset[str]
    modules: Mapping[str, str]


def _module_scope_imports(tree: ast.Module) -> _ModuleScopeImports:
    """Names bound by MODULE-SCOPE imports only.

    Scope matters for both alias rules: an import nested in a function or an
    ``if`` block does not establish the module-level binding the constructs
    below rely on, so it is not collected.
    """
    sys_aliases: set[str] = set()
    modules_aliases: set[str] = set()
    modules: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "sys":
                    sys_aliases.add(alias.asname or "sys")
                elif alias.asname:
                    modules[alias.asname] = alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module:
                continue
            for alias in node.names:
                if node.module == "sys" and alias.name == "modules":
                    modules_aliases.add(alias.asname or "modules")
                elif alias.name != "*":
                    modules[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return _ModuleScopeImports(
        frozenset(sys_aliases), frozenset(modules_aliases), modules)


def _is_own_sys_modules_slot(node: ast.expr,
                             imports: _ModuleScopeImports) -> bool:
    """Is ``node`` the expression ``sys.modules[__name__]`` for THIS module?

    The key must literally be ``__name__``. Reading or writing some other
    module's ``sys.modules`` entry is a different act, and treating it as an
    alias for this locator is precisely the "taught to follow too much" failure
    these two rules have to avoid.
    """
    if not isinstance(node, ast.Subscript):
        return False
    key = node.slice
    if not isinstance(key, ast.Name) or key.id != "__name__":
        return False
    table = node.value
    if (isinstance(table, ast.Attribute) and table.attr == "modules"
            and isinstance(table.value, ast.Name)
            and table.value.id in imports.sys_aliases):
        return True
    return isinstance(table, ast.Name) and table.id in imports.modules_aliases


def _exports(path: Path, root: Path,
             _hops: int = _MAX_ALIAS_HOPS) -> tuple[frozenset[str], bool]:
    """(top-level names, opaque).

    ``opaque`` means static reading is not authoritative for this module -- it
    star-imports or defines a module-level ``__getattr__``, either of which can
    legitimately provide a name no reader can see.

    A module that replaces its own ``sys.modules`` entry (see
    :func:`_alias_target`) is read THROUGH to its owner, because that is what an
    importer of the old locator actually gets. Following buys PRECISION, not
    silence: an invented name is still refused for every module whose alias
    target is readable, which is all three of them in this tree.

    When the owner CANNOT be opened -- outside the tree, a namespace-package
    directory, the file itself, or past ``_MAX_ALIAS_HOPS`` -- the file is not
    treated as an alias at all and is read literally, which in practice refuses.
    That direction is deliberate and it is a correction. ADVERSARIAL REVIEW
    2026-09-02 broke the version that answered ``opaque`` there, three ways, all
    of them cheap: a three-line module aliasing itself; a five-file chain
    ``a1 -> ... -> a5`` that exhausts the budget one hop before a perfectly
    readable terminal; and an alias to a namespace-package directory, which this
    repository really has two of (``tools`` and ``tests`` -- see
    :func:`_module_path`). Each turned an honest "I cannot judge this owner"
    into a blanket accept for every invented name behind it. A guard whose job
    is to refuse must not fail open on the cases it cannot follow, and no module
    in this tree needs it to: all three real aliases are one hop to a ``.py``
    file.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError, RecursionError):
        return frozenset(), True
    if _hops > 0 and (alias := _alias_target(tree)) is not None:
        owner = _module_path(root, alias)
        if owner is not None and owner != path and owner.is_file():
            return _exports(owner, root, _hops - 1)
        # The file names an owner this reader cannot open: outside the tree, a
        # namespace-package directory, itself, or past the hop budget. It is
        # then NOT treated as an alias and is read literally below.
    if _installs_dynamic_module_protocol(tree):
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
            names, opaque = _exports(path, root)
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


# Grounding a model's PROSE against the tree -- audit_references, judge --
# lives in daedalus/lanes/grounding.py. It was briefly here, and being here
# made this module two things: a write gate that refuses, and a report
# measurement that observes. Different subject, different consumer.
