# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""reach — can a human or a tool actually GET to this module?

structcore already answers "X imports Y". That is not the same question. A
module can sit in a dense import cluster and still be unreachable: nothing that
a person types, nothing an HTTP client requests, and nothing the file bus
dispatches ever leads to it. This module answers the reachability question and
nothing else.

WHY THIS IS GENERATED, NOT WRITTEN
----------------------------------
A hand-written feature inventory listed 136 features, 8 islands and 2 dark
switches. A deep read of the same tree six hours later found 827 / 55 / 51. The
hand-written artifact was not wrong when it was written; it went stale
immediately and nothing could tell. Everything in this file is derived from the
tree on every run, so it cannot go stale. The narrative half -- WHY
``reap_branches`` must not delete inside a ``finally`` -- stays hand-written in
docs/adrs/ where a scanner has no business.

WHAT AN ENTRY POINT IS (discovered, never hardcoded)
----------------------------------------------------
  script       ``[project.scripts]`` in pyproject.toml -> "module:function"
  module_main  a ``__main__.py`` -> ``python -m package``
  main_guard   ``if __name__ == "__main__":`` -> ``python path/to/file.py``
  cli          a subcommand branch in a dispatch chain inside an entry module
  http         the same shape, where the literals are URL paths
  bus          a poll loop (``while True``) inside an entry module

The CLI case is the one a naive scan gets wrong. ``daedalus/cli.py`` dispatches
with a flat if/elif chain whose branches import LAZILY, inside the branch body::

    elif cmd == "offload":
        from .offload import main as m; m()

There is no module-level edge from cli.py to offload.py. A module-level import
scan reports every subcommand target as an island -- which is the exact false
accusation that would make this tool distrusted. Imports are therefore
collected at every scope depth, and each one is attributed to the branch
literal it sits under, so the answer is "reached by ``cli:offload``" rather than
a bare boolean.

TEST FILES ARE NOT ENTRY POINTS. A module reached only by its own test is
precisely an island, and admitting tests as roots would erase the single most
valuable signal here. Test coverage is recorded separately, per module.

HONESTY
-------
A static walk cannot see dynamic dispatch. Where the target is a literal
(``importlib.import_module("pkg.mod")``) the edge is real and is added. Where it
is not, the module is marked ``unknown`` with the evidence that made it unknown
-- a string literal naming it, an agents/*.json entry -- rather than being
accused of being an island. A gap is recoverable; a false accusation is not.

WHAT IS NOT EVIDENCE OF REACHABILITY
------------------------------------
The symmetric error is worse than a false island, because it is silent: calling
a module REACHED on the strength of an import that never runs. Three shapes are
refused, and each one costs two lines to write::

    if False:                      # a dead branch is not a caller
        from . import secret
    try:                           # a suppressed ImportError is not a caller
        from . import secret
    except ImportError:
        secret = None
    ghost = "pkg.secret:nosuchfunc"   # in [project.scripts]; raises on invocation

Imports under the first two are collected SEPARATELY (``weak``) and never enter
the reachability graph. A module whose only importers are weak is ``unknown``
carrying the reason -- the same treatment as a dynamic surface, for the same
argument: we cannot prove reachability and we will not invent it. A console
script whose ``module:function`` names a function the module does not define is
not an entry point at all; it is recorded in ``broken_entries``, because the
strongest claim this report makes must not be made for something that raises.

AND THE STRUCTURAL INDEX DOES NOT GET A VOTE
--------------------------------------------
``analyse`` accepts a structcore index, and the index's ``import_edges`` used to
be UNIONED into this walk's graph. That silently undid every refusal above:
structcore derives its edges without branch context, so the ``if False:`` import
and the swallowed-``ImportError`` import this file deliberately withheld came
straight back in as live edges, and the module they pointed at was printed
``reachable`` -- on the shipped path, because ``render.analyse_once`` always
builds an index. An edge one engine has and the other withheld is a
DISAGREEMENT BETWEEN TWO ENGINES, not a discovery. It is reported in
``index_extra_edges`` and it changes no classification. If a module's only route
to an entry point runs through such an edge, this report does not call it
reached.
"""
from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence

# structcore owns Python dotted-name resolution (relative imports, submodule
# vs. attribute disambiguation). Reusing it means this map and the structural
# index cannot disagree about what an import statement points at.
from ..structcore.parse import resolve_python_imports

__all__ = [
    "EntryPoint",
    "ModuleFacts",
    "ReachReport",
    "analyse",
]

SCHEMA = "daedalus.mapping.reach/1"

# Mirrors structcore.index._IGNORE_DIRS (private there). ``build`` matters on
# this repo: a stale wheel-build copy of the whole package lives under build/
# and would otherwise double every count.
_IGNORE_DIRS = frozenset({
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env", "__pycache__",
    "dist", "build", "target", "out", "coverage", ".next", ".nuxt", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", ".idea", ".vs", ".vscode", "vendor", ".cache",
})

# Display order, and the order in which an entry MODULE is described: a file is
# best characterised by the thing that makes it runnable at all.
ENTRY_KINDS = ("script", "module_main", "main_guard", "cli", "http", "bus")

# Propagation order, which is NOT the same and must not be collapsed into it.
# The console-script entry's targets are the whole closure of ``main()``, so it
# reaches every subcommand's module -- run it first and everything downstream is
# attributed to ``script:daedalus``, which is true and useless. The per-branch
# entries are strict refinements of it, so they claim first and the coarse
# entries only pick up what no branch explains.
_PROPAGATION_ORDER = ("cli", "http", "bus", "script", "module_main", "main_guard")

CLASSES = ("entry", "reachable", "unknown", "shim", "orphan", "island", "test")

# A dispatch chain shorter than this is an ordinary conditional, not a command
# table. Three keeps ``if x == "a" / elif x == "b" / else`` out of the results.
_MIN_DISPATCH_BRANCHES = 3

_LOOP_FUNC_HINTS = ("watch", "serve", "loop", "poll", "run_forever")


# --------------------------------------------------------------------------
# public shapes
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class EntryPoint:
    """One way in. ``targets`` are the modules this specific entry reaches
    directly -- for a CLI branch that is what the branch body imports, which is
    how a lazily-imported subcommand target gets attributed to its subcommand
    rather than to the CLI module at large."""

    kind: str
    name: str
    module: str
    function: str = ""
    targets: tuple[str, ...] = ()

    @property
    def ident(self) -> str:
        return f"{self.kind}:{self.name}"

    def to_dict(self) -> dict:
        return {"kind": self.kind, "name": self.name, "module": self.module,
                "function": self.function, "targets": list(self.targets),
                "ident": self.ident}


@dataclass(frozen=True)
class ModuleFacts:
    """Everything derived about one module. ``path`` is the SHORTEST route from
    an entry point, module by module, because "reached by what" is the useful
    answer and a boolean is not."""

    module: str
    classification: str
    reason: str = ""
    entry: str = ""
    depth: int | None = None
    path: tuple[str, ...] = ()
    imports: tuple[str, ...] = ()
    imported_by: tuple[str, ...] = ()
    tested_by: tuple[str, ...] = ()
    is_shim: bool = False
    has_main_guard: bool = False
    dynamic_imports: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "module": self.module, "classification": self.classification,
            "reason": self.reason, "entry": self.entry, "depth": self.depth,
            "path": list(self.path), "imports": list(self.imports),
            "imported_by": list(self.imported_by), "tested_by": list(self.tested_by),
            "is_shim": self.is_shim, "has_main_guard": self.has_main_guard,
            "dynamic_imports": list(self.dynamic_imports),
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class ReachReport:
    """The generated half of the architecture artifact.

    Contains no clock reading, no absolute path outside ``root`` and no set
    iteration -- two runs over an unchanged tree produce byte-identical
    ``to_dict()``. That property is the whole point: it is what makes a diff of
    this report mean "the architecture moved" instead of "the scanner ran"."""

    root: str
    schema: str = SCHEMA
    entry_points: tuple[EntryPoint, ...] = ()
    modules: tuple[ModuleFacts, ...] = ()
    counts: Mapping[str, int] = field(default_factory=dict)
    entry_counts: Mapping[str, int] = field(default_factory=dict)
    dynamic_surfaces: tuple[str, ...] = ()
    unparsable: tuple[str, ...] = ()
    # "src -> tgt" edges the structural index carries and this walk does not.
    # REPORTED, NEVER MERGED: see the module docstring. Every entry here is two
    # engines disagreeing about the import graph, which is a finding in its own
    # right and is why the gate has a kind for it.
    index_extra_edges: tuple[str, ...] = ()
    # Declared entry points that cannot actually be taken: a [project.scripts]
    # target whose module or function does not exist. Never silently dropped --
    # a dead console script is a broken promise in packaging metadata.
    broken_entries: tuple[str, ...] = ()
    # (module, why) for imports that exist in the source but are not proof that
    # anything runs them.
    weak_edges: tuple[str, ...] = ()

    def by_class(self, name: str) -> tuple[ModuleFacts, ...]:
        return tuple(m for m in self.modules if m.classification == name)

    @property
    def islands(self) -> tuple[ModuleFacts, ...]:
        return self.by_class("island")

    @property
    def shims(self) -> tuple[ModuleFacts, ...]:
        return self.by_class("shim")

    @property
    def orphans(self) -> tuple[ModuleFacts, ...]:
        return self.by_class("orphan")

    @property
    def unknown(self) -> tuple[ModuleFacts, ...]:
        return self.by_class("unknown")

    def get(self, module: str) -> ModuleFacts | None:
        for m in self.modules:
            if m.module == module:
                return m
        return None

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "root": self.root,
            "counts": dict(self.counts),
            "entry_counts": dict(self.entry_counts),
            "entry_points": [e.to_dict() for e in self.entry_points],
            "modules": [m.to_dict() for m in self.modules],
            "dynamic_surfaces": list(self.dynamic_surfaces),
            "unparsable": list(self.unparsable),
            "index_extra_edges": list(self.index_extra_edges),
            "broken_entries": list(self.broken_entries),
            "weak_edges": list(self.weak_edges),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=False)

    def render_text(self) -> str:
        out = [f"reachability map: {self.root}"]
        out.append("  " + "  ".join(
            f"{k}={self.counts.get(k, 0)}" for k in CLASSES))
        out.append("  entries: " + "  ".join(
            f"{k}={self.entry_counts.get(k, 0)}" for k in ENTRY_KINDS))
        for label in ("island", "orphan", "shim", "unknown"):
            rows = self.by_class(label)
            if not rows:
                continue
            out.append(f"\n{label} ({len(rows)}):")
            for m in rows:
                suffix = f"  -- {m.reason}" if m.reason else ""
                out.append(f"  {m.module}{suffix}")
        return "\n".join(out)


# --------------------------------------------------------------------------
# source scanning
# --------------------------------------------------------------------------

@dataclass
class _Src:
    """Mutable scratch for one parsed module. Never escapes ``analyse``."""

    rel: str
    dotted: str
    tree: ast.AST | None = None
    records: list[tuple] = field(default_factory=list)
    # qualified function name -> raw import records inside it
    func_records: dict[str, list[tuple]] = field(default_factory=dict)
    # qualified function name -> names referenced in its body
    func_names: dict[str, set[str]] = field(default_factory=dict)
    # qualified function name -> functions of THIS module it calls
    func_calls: dict[str, set[str]] = field(default_factory=dict)
    func_loops: set[str] = field(default_factory=set)
    dispatch: list[tuple[str, str, list[tuple]]] = field(default_factory=list)
    has_main_guard: bool = False
    is_shim: bool = False
    literals: set[str] = field(default_factory=set)
    dynamic: set[str] = field(default_factory=set)
    dyn_targets: set[str] = field(default_factory=set)
    # imports that exist in the text but are not proof anything runs them:
    # (record, why). Kept out of ``records``/``func_records`` entirely.
    weak: list[tuple[tuple, str]] = field(default_factory=list)
    # names bound at module level -- what a console script's ``:function`` half
    # has to be found in before the entry is believed.
    toplevel: set[str] = field(default_factory=set)


def _py_dotted(rel: str) -> str:
    return rel[:-3].replace("/", ".")


def _iter_py(root: Path) -> list[str]:
    out: list[str] = []
    for dirpath, dirnames, filenames in _walk(root):
        for fn in filenames:
            if fn.endswith(".py"):
                out.append((Path(dirpath) / fn).relative_to(root).as_posix())
    return sorted(out)


def _walk(root: Path):
    import os

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames
                             if d not in _IGNORE_DIRS and not d.startswith("."))
        yield dirpath, dirnames, sorted(filenames)


def _is_main_guard(node: ast.stmt) -> bool:
    if not isinstance(node, ast.If):
        return False
    test = node.test
    return (isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name) and test.left.id == "__name__"
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == "__main__")


def _branch_literals(test: ast.expr) -> list[str]:
    """String literals a branch condition selects on.

    Covers the two shapes real dispatch chains use: ``x == "literal"`` and
    ``x.startswith("/api/")`` (web_api routes a prefix on several paths). A
    branch we cannot read contributes nothing rather than a guess."""
    lits: list[str] = []
    if isinstance(test, ast.Compare):
        if isinstance(test.left, ast.Constant) and isinstance(test.left.value, str):
            lits.append(test.left.value)
        for c in test.comparators:
            if isinstance(c, ast.Constant) and isinstance(c.value, str):
                lits.append(c.value)
    elif isinstance(test, ast.BoolOp):
        for v in test.values:
            lits.extend(_branch_literals(v))
    elif isinstance(test, ast.Call):
        fn = test.func
        if isinstance(fn, ast.Attribute) and fn.attr in ("startswith", "endswith"):
            for a in test.args:
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    lits.append(a.value)
    return lits


def _dispatch_chains(fn: ast.AST) -> list[list[tuple[str, ast.If]]]:
    """Flat if/elif chains inside one function, as (literal, node) pairs.

    A chain is only a command table when it is long enough (``_MIN_DISPATCH_
    BRANCHES``); shorter ones are ordinary conditionals and reporting them as
    subcommands would fabricate entry points."""
    chains: list[list[tuple[str, ast.If]]] = []
    seen: set[int] = set()

    for node in ast.walk(fn):
        if not isinstance(node, ast.If) or id(node) in seen:
            continue
        chain: list[tuple[str, ast.If]] = []
        cur: ast.If | None = node
        while cur is not None:
            seen.add(id(cur))
            for lit in _branch_literals(cur.test):
                chain.append((lit, cur))
            nxt = None
            if len(cur.orelse) == 1 and isinstance(cur.orelse[0], ast.If):
                nxt = cur.orelse[0]
            cur = nxt
        if len(chain) >= _MIN_DISPATCH_BRANCHES:
            chains.append(chain)
    return chains


_DEAD_BRANCH = "inside a branch that can never run (`if False:`)"
_SUPPRESSED = "inside a `try:` whose ImportError is swallowed"

_IMPORT_ERRORS = ("ImportError", "ModuleNotFoundError")


def _is_never_true(test: ast.expr) -> bool:
    """``if False:`` / ``if 0:`` -- a branch the interpreter deletes.

    Deliberately literal-only. Inferring that some NAME is falsy would make the
    walk guess, and a guess in this direction silently deletes real edges."""
    return isinstance(test, ast.Constant) and not test.value


def _catches_import_error(node: ast.Try) -> bool:
    """Does this ``try`` swallow a failing import?

    Narrow on purpose: only handlers that NAME ImportError (or
    ModuleNotFoundError) count. A bare ``except Exception`` around an import is
    usually a lazy-optional-dependency idiom too, but widening this rule
    reclassifies real edges on evidence that is not there."""
    for h in node.handlers:
        t = h.type
        if t is None:
            continue
        names = t.elts if isinstance(t, ast.Tuple) else [t]
        for n in names:
            if isinstance(n, ast.Name) and n.id in _IMPORT_ERRORS:
                return True
            if isinstance(n, ast.Attribute) and n.attr in _IMPORT_ERRORS:
                return True
    return False


def _split_imports(node: ast.AST) -> tuple[list[tuple], list[tuple[tuple, str]]]:
    """(live records, [(weak record, why)]) for one subtree.

    Structural descent rather than ``ast.walk`` because the whole point is the
    CONTEXT an import sits in: the same statement is evidence in one branch and
    not in another."""
    live: list[tuple] = []
    weak: list[tuple[tuple, str]] = []

    def record(n) -> tuple:
        if isinstance(n, ast.Import):
            return ("import", 0, None, tuple(a.name for a in n.names))
        return ("from", n.level or 0, n.module, tuple(a.name for a in n.names))

    def rec(n, why: str) -> None:
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            (weak.append((record(n), why)) if why else live.append(record(n)))
            return
        if isinstance(n, ast.If) and _is_never_true(n.test):
            for c in n.body:
                rec(c, why or _DEAD_BRANCH)
            for c in n.orelse:                 # the else IS the live branch
                rec(c, why)
            return
        if isinstance(n, ast.Try) and _catches_import_error(n):
            for c in list(n.body) + list(n.orelse):
                rec(c, why or _SUPPRESSED)
            # the handler's own import is the fallback that actually runs
            for h in n.handlers:
                for c in h.body:
                    rec(c, why)
            for c in n.finalbody:
                rec(c, why)
            return
        for c in ast.iter_child_nodes(n):
            rec(c, why)

    rec(node, "")
    return live, weak


def _import_records_of(node: ast.AST) -> list[tuple]:
    """LIVE import records only. Weak ones are reachable only via
    :func:`_split_imports`, so no caller can pick them up by accident."""
    return _split_imports(node)[0]


def _toplevel_names(body: Sequence[ast.stmt], depth: int = 0) -> set[str]:
    """Names a module binds at import time. Descends one level into ``if`` and
    ``try`` because conditional definitions are ordinary in this codebase."""
    out: set[str] = set()
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(stmt.name)
        elif isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                if isinstance(t, ast.Name):
                    out.add(t.id)
        elif isinstance(stmt, (ast.AnnAssign, ast.AugAssign)):
            if isinstance(stmt.target, ast.Name):
                out.add(stmt.target.id)
        elif isinstance(stmt, ast.Import):
            for a in stmt.names:
                out.add(a.asname or a.name.split(".")[0])
        elif isinstance(stmt, ast.ImportFrom):
            for a in stmt.names:
                out.add(a.asname or a.name)
        elif isinstance(stmt, (ast.If, ast.Try, ast.With, ast.AsyncWith)) and depth < 3:
            inner = list(getattr(stmt, "body", ()) or ())
            inner += list(getattr(stmt, "orelse", ()) or ())
            inner += list(getattr(stmt, "finalbody", ()) or ())
            for h in getattr(stmt, "handlers", ()) or ():
                inner += list(h.body)
            out |= _toplevel_names(inner, depth + 1)
    return out


def _module_level_bindings(tree: ast.Module) -> dict[str, list[tuple]]:
    """Name bound by a MODULE-LEVEL import -> the record that bound it.

    ``from .projects import resolve_repo_root`` binds ``resolve_repo_root`` to
    the projects MODULE for reachability purposes: referencing that name inside
    a dispatch branch is a real dependency on that module, and it is how HTTP
    route handlers reach anything at all (they call ``hierarchy.hierarchy``,
    never ``import hierarchy`` inside the branch).

    MODULE LEVEL ONLY, and that restriction is load-bearing. cli.py's branches
    all write ``from .doctor import main as m`` / ``from .benchmark import main
    as m`` -- the SAME local name ``m`` in sixty different branches. Binding
    names from every scope made ``m`` resolve to all sixty modules, so every
    subcommand appeared to reach every other subcommand's target and the whole
    dispatch collapsed into one blob. A branch's own imports are handled
    separately, from that branch's own records."""
    out: dict[str, list[tuple]] = {}
    for n in tree.body:
        if isinstance(n, ast.Import):
            for a in n.names:
                bound = a.asname or a.name.split(".")[0]
                out.setdefault(bound, []).append(("import", 0, None, (a.name,)))
        elif isinstance(n, ast.ImportFrom):
            for a in n.names:
                bound = a.asname or a.name
                out.setdefault(bound, []).append(
                    ("from", n.level or 0, n.module, (a.name,)))
    return out


def _shim_body(body: Sequence[ast.stmt]) -> bool:
    """True when the module body re-exports and does nothing else.

    Detected structurally, never guessed: no def, no class, no executable
    statement beyond imports, ``__all__`` and plain alias assignments. A shim is
    worth naming because it is the one module class where "nothing reaches it"
    is expected rather than alarming."""
    saw_from = False
    for i, stmt in enumerate(body):
        if i == 0 and isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            continue
        if isinstance(stmt, ast.Import):
            continue
        if isinstance(stmt, ast.ImportFrom):
            if stmt.module != "__future__":
                saw_from = True
            continue
        if isinstance(stmt, ast.Assign):
            targets = stmt.targets
            if (len(targets) == 1 and isinstance(targets[0], ast.Name)
                    and isinstance(stmt.value, (ast.Name, ast.List, ast.Tuple,
                                                ast.Attribute))):
                continue
            return False
        if isinstance(stmt, (ast.Try, ast.If)):
            inner = list(getattr(stmt, "body", ())) + list(getattr(stmt, "orelse", ()))
            for h in getattr(stmt, "handlers", ()) or ():
                inner.extend(h.body)
            if all(isinstance(s, (ast.Import, ast.ImportFrom, ast.Pass))
                   for s in inner):
                if any(isinstance(s, ast.ImportFrom) for s in inner):
                    saw_from = True
                continue
            return False
        return False
    return saw_from


def _scan(rel: str, text: str) -> _Src:
    src = _Src(rel=rel, dotted=_py_dotted(rel))
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return src
    src.tree = tree
    src.records, src.weak = _split_imports(tree)
    src.is_shim = _shim_body(tree.body)
    src.toplevel = _toplevel_names(tree.body)

    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            if len(n.value) <= 400:
                src.literals.add(n.value)

    # every import, at every scope depth -- this is where lazy CLI branch
    # imports live, and a module-level-only pass sees none of them
    _collect_funcs(tree, "", src)

    for name, fn in _iter_funcs(tree, ""):
        for chain in _dispatch_chains(fn):
            for lit, node in chain:
                src.dispatch.append((name, lit, _branch_payload(node)))

    for stmt in tree.body:
        if _is_main_guard(stmt):
            src.has_main_guard = True

    _scan_dynamic(tree, src)
    return src


def _branch_payload(node: ast.If) -> list[tuple]:
    """(records, referenced names, called functions) for one branch body.

    ``orelse`` is deliberately excluded: for an elif chain the orelse IS the
    next branch, and folding it in would credit every subcommand with every
    later subcommand's imports."""
    body = ast.Module(body=list(node.body), type_ignores=[])
    recs = _import_records_of(body)
    names = sorted({n.id for n in ast.walk(body) if isinstance(n, ast.Name)}
                   | {n.attr for n in ast.walk(body) if isinstance(n, ast.Attribute)})
    return [("records", tuple(recs)), ("names", tuple(names))]


def _iter_funcs(node: ast.AST, prefix: str):
    for child in getattr(node, "body", ()) or ():
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = f"{prefix}{child.name}"
            yield name, child
            yield from _iter_funcs(child, f"{name}.")
        elif isinstance(child, ast.ClassDef):
            yield from _iter_funcs(child, f"{prefix}{child.name}.")


def _collect_funcs(tree: ast.AST, prefix: str, src: _Src) -> None:
    for name, fn in _iter_funcs(tree, prefix):
        src.func_records[name] = _import_records_of(fn)
        refs = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
        refs |= {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
        src.func_names[name] = refs
        for n in ast.walk(fn):
            if isinstance(n, (ast.While, ast.For)) and _is_forever(n):
                src.func_loops.add(name)

    local = set(src.func_records)
    short = {n.rsplit(".", 1)[-1]: n for n in sorted(local)}
    for name in local:
        called = set()
        for ref in src.func_names.get(name, ()):
            target = short.get(ref)
            if target and target != name:
                called.add(target)
        src.func_calls[name] = called


def _is_forever(node: ast.AST) -> bool:
    if isinstance(node, ast.While):
        t = node.test
        return isinstance(t, ast.Constant) and bool(t.value)
    return False


_DOTTED_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$")


def _scan_dynamic(tree: ast.AST, src: _Src) -> None:
    """importlib / __import__ sites.

    A literal argument is a REAL edge and is treated as one. A non-literal one
    is a hole in the static picture; it is recorded so the report can say a
    module is ``unknown`` instead of accusing it of being an island."""
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        fn = n.func
        is_dyn = ((isinstance(fn, ast.Attribute) and fn.attr == "import_module")
                  or (isinstance(fn, ast.Name) and fn.id in ("__import__", "import_module")))
        if not is_dyn:
            continue
        arg = n.args[0] if n.args else None
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            src.dyn_targets.add(arg.value)
        else:
            src.dynamic.add(f"{src.rel}:{getattr(n, 'lineno', 0)}")


# --------------------------------------------------------------------------
# resolution
# --------------------------------------------------------------------------

def _resolve(records: Iterable[tuple], tops: set[str], known: set[str],
             src_dotted: str, rel_by_dotted: Mapping[str, str],
             self_rel: str) -> set[str]:
    out: set[str] = set()
    for dotted in resolve_python_imports(list(records), tops, known, src_dotted):
        rel = rel_by_dotted.get(dotted)
        if rel and rel != self_rel:
            out.add(rel)
    return out


def _package_parents(rel: str, known_rels: set[str]) -> list[str]:
    """``__init__.py`` files Python imports as a side effect of importing this
    module. These edges are real at runtime -- omitting them would report a
    package's ``__init__`` as an island whenever nothing imports it by name."""
    parts = rel.split("/")[:-1]
    out = []
    for i in range(len(parts), 0, -1):
        cand = "/".join(parts[:i]) + "/__init__.py"
        if cand in known_rels and cand != rel:
            out.append(cand)
    return out


# --------------------------------------------------------------------------
# entry-point discovery
# --------------------------------------------------------------------------

_SCRIPTS_RE = re.compile(r"^\s*\[project\.scripts\]\s*$")
_SECTION_RE = re.compile(r"^\s*\[")
_SCRIPT_LINE_RE = re.compile(
    r"""^\s*(?P<name>[A-Za-z0-9_.\-]+)\s*=\s*["'](?P<target>[^"']+)["']""")


def _console_scripts(pyproject: Path) -> list[tuple[str, str, str]]:
    """(script name, dotted module, function) from ``[project.scripts]``.

    Hand-parsed because ``tomllib`` landed in 3.11 and this package targets
    3.10 with zero runtime dependencies."""
    if not pyproject.is_file():
        return []
    try:
        lines = pyproject.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out: list[tuple[str, str, str]] = []
    inside = False
    for line in lines:
        if _SCRIPTS_RE.match(line):
            inside = True
            continue
        if inside and _SECTION_RE.match(line):
            break
        if not inside:
            continue
        m = _SCRIPT_LINE_RE.match(line)
        if not m:
            continue
        target = m.group("target")
        mod, _, func = target.partition(":")
        out.append((m.group("name"), mod.strip(), func.strip()))
    return sorted(out)


def _func_closure(src: _Src, start: str) -> set[str]:
    """Every function of this module transitively called from ``start``.

    ``elif cmd == "spawn": _spawn(rest)`` puts the real imports one hop away, in
    a module-local helper. Without the closure that whole subcommand's targets
    are invisible."""
    seen: set[str] = set()
    stack = [start]
    while stack:
        cur = stack.pop()
        if cur in seen or cur not in src.func_records:
            continue
        seen.add(cur)
        stack.extend(sorted(src.func_calls.get(cur, ())))
    return seen


# --------------------------------------------------------------------------
# the engine
# --------------------------------------------------------------------------

def analyse(repo_root, index: Mapping | None = None) -> ReachReport:
    """Classify every Python module in ``repo_root`` by reachability.

    ``index`` is an optional structcore index dict. Any edge it has that this
    walk does not is REPORTED in ``index_extra_edges`` and is NOT added to the
    graph: structcore resolves imports without branch context, so unioning its
    edges back in re-admitted exactly the ``if False:`` and swallowed-
    ``ImportError`` imports this engine refuses on purpose, and printed the
    target ``reachable``. A disagreement between the two engines is a finding,
    not a discovery, and a finding may not quietly promote a module.
    """
    root = Path(repo_root).resolve()
    rels = _iter_py(root)
    known_rels = set(rels)

    sources: dict[str, _Src] = {}
    unparsable: list[str] = []
    for rel in rels:
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            unparsable.append(rel)
            continue
        src = _scan(rel, text)
        if src.tree is None:
            unparsable.append(rel)
        sources[rel] = src

    rel_by_dotted: dict[str, str] = {}
    collisions: set[str] = set()
    for rel in rels:
        d = _py_dotted(rel)
        if d in rel_by_dotted:
            collisions.add(d)
        rel_by_dotted[d] = rel
    for d in collisions:                      # refuse rather than bind wrongly
        rel_by_dotted.pop(d, None)
    known = set(rel_by_dotted)
    tops = {d.split(".")[0] for d in known}

    # ---- graph -----------------------------------------------------------
    explicit: dict[str, set[str]] = {rel: set() for rel in rels}
    for rel, src in sources.items():
        explicit[rel] |= _resolve(src.records, tops, known, src.dotted,
                                  rel_by_dotted, rel)
        for dotted in sorted(src.dyn_targets):
            tgt = rel_by_dotted.get(dotted)
            if tgt and tgt != rel:
                explicit[rel].add(tgt)

    # ---- weak edges ------------------------------------------------------
    # Resolved exactly like real ones, then kept OUT of ``edges``. They exist
    # only to answer "why is this module here at all", so an unreached module
    # somebody clearly intended to load is ``unknown`` rather than an island.
    weak_reasons: dict[str, set[str]] = {}
    weak_edges: list[str] = []
    for rel, src in sorted(sources.items()):
        for rec, why in src.weak:
            for tgt in sorted(_resolve([rec], tops, known, src.dotted,
                                       rel_by_dotted, rel)):
                weak_reasons.setdefault(tgt, set()).add(f"{rel}: imported {why}")
                weak_edges.append(f"{rel} -> {tgt} ({why})")

    # ---- the structural index's opinion, RECORDED and not merged -----------
    # ``explicit`` is deliberately not touched here. structcore has no branch
    # context, so its edge set contains the dead-branch and swallowed-import
    # edges ``_split_imports`` withheld two blocks up; merging them back turned
    # every one of those refusals into a silent ``reachable``.
    index_extra: list[str] = []
    if index:
        for srcrel, tgts in sorted((index.get("import_edges") or {}).items()):
            if srcrel not in explicit:
                continue
            for t in sorted(tgts):
                if t.endswith(".py") and t in known_rels and t not in explicit[srcrel]:
                    index_extra.append(f"{srcrel} -> {t}")

    edges: dict[str, set[str]] = {rel: set(v) for rel, v in explicit.items()}
    for rel in rels:                          # runtime package-init edges
        for parent in _package_parents(rel, known_rels):
            edges[rel].add(parent)

    reverse: dict[str, set[str]] = {rel: set() for rel in rels}
    for s, tgts in edges.items():
        for t in tgts:
            reverse[t].add(s)

    tests = {rel for rel in rels if _is_test(rel)}
    tested_by: dict[str, set[str]] = {rel: set() for rel in rels}
    for t in sorted(tests):
        for tgt in sorted(edges[t]):
            tested_by[tgt].add(t)

    # ---- entry points ----------------------------------------------------
    entries, broken_entries = _discover_entries(root, sources, rels, known_rels,
                                                tops, known, rel_by_dotted)

    # ---- tiered BFS ------------------------------------------------------
    claim: dict[str, tuple[str, tuple[str, ...]]] = {}
    entry_modules = {e.module for e in entries}
    for e in entries:                         # entries are already in ENTRY_KINDS order
        claim.setdefault(e.module, (e.ident, (e.module,)))
    for kind in _PROPAGATION_ORDER:
        tier = [e for e in entries if e.kind == kind]
        if not tier:
            continue
        # PER-TIER visited set, deliberately not the global ``claim``. Sharing
        # them stopped a tier's walk dead at any module some other entry had
        # already claimed -- ``spine/picker.py`` carries a __main__ guard, so it
        # was claimed at depth 0 and the ``cli:improve`` walk never got through
        # it to attempt.py or worktree.py, which then degraded to the coarsest
        # attribution available. Traversal must cross claimed nodes; only the
        # first tier to ARRIVE writes the claim.
        visited: set[str] = set()
        frontier: list[tuple[str, tuple[str, ...], str]] = []
        for e in sorted(tier, key=lambda x: (x.name, x.module)):
            if e.module not in visited:
                visited.add(e.module)
                claim.setdefault(e.module, (e.ident, (e.module,)))
                frontier.append((e.module, (e.module,), e.ident))
            for t in e.targets:
                if t in visited:
                    continue
                visited.add(t)
                claim.setdefault(t, (e.ident, (e.module, t)))
                frontier.append((t, (e.module, t), e.ident))
        while frontier:
            frontier.sort()
            nxt: list[tuple[str, tuple[str, ...], str]] = []
            for node, path, ident in frontier:
                for tgt in sorted(edges.get(node, ())):
                    if tgt in visited:
                        continue
                    visited.add(tgt)
                    claim.setdefault(tgt, (ident, path + (tgt,)))
                    nxt.append((tgt, path + (tgt,), ident))
            frontier = nxt

    # ---- dynamic evidence ------------------------------------------------
    literal_corpus = _literal_corpus(root, sources, tests)
    dynamic_surfaces = sorted(
        s for src in sources.values() for s in src.dynamic)

    # ---- classification --------------------------------------------------
    facts: list[ModuleFacts] = []
    for rel in rels:
        src = sources.get(rel) or _Src(rel=rel, dotted=_py_dotted(rel))
        base = dict(
            module=rel,
            imports=tuple(sorted(explicit.get(rel, ()))),
            imported_by=tuple(sorted(reverse.get(rel, ()))),
            tested_by=tuple(sorted(tested_by.get(rel, ()))),
            is_shim=src.is_shim,
            has_main_guard=src.has_main_guard,
            dynamic_imports=tuple(sorted(src.dynamic)),
        )
        if rel in tests:
            facts.append(ModuleFacts(classification="test",
                                     reason="test module; never an entry point",
                                     **base))
            continue
        if rel in claim and rel in entry_modules:
            ident, path = claim[rel]
            facts.append(ModuleFacts(classification="entry", entry=ident,
                                     depth=0, path=path,
                                     reason="declared entry point", **base))
            continue
        if rel in claim:
            ident, path = claim[rel]
            facts.append(ModuleFacts(classification="reachable", entry=ident,
                                     depth=len(path) - 1, path=path,
                                     reason=f"reached from {ident}", **base))
            continue

        weak = tuple(sorted(weak_reasons.get(rel, ())))
        ev = _evidence(rel, src.dotted, literal_corpus)
        if weak or ev:
            reason = ("named by a string literal; a dynamic dispatch may "
                      "reach it, which a static walk cannot prove either way")
            if weak:
                # Stated FIRST because it is the stronger finding: somebody
                # wrote the import and then guarded it out. That is a decision,
                # not an ambiguity, and calling it "reachable" would be a lie.
                reason = ("imported only where the import is not evidence that "
                          "anything runs it (a dead branch or a swallowed "
                          "ImportError); reachability is not established")
            facts.append(ModuleFacts(
                classification="unknown", evidence=weak + ev, reason=reason,
                **base))
            continue
        if src.is_shim:
            facts.append(ModuleFacts(
                classification="shim",
                reason="re-exports only; nothing reaches it by name", **base))
            continue
        if not explicit.get(rel) and not reverse.get(rel):
            facts.append(ModuleFacts(
                classification="orphan",
                reason="on disk; imports nothing and nothing imports it", **base))
            continue
        cover = "; covered by tests" if tested_by.get(rel) else "; no test touches it"
        facts.append(ModuleFacts(
            classification="island",
            reason=f"no path from any entry point{cover}", **base))

    facts.sort(key=lambda m: m.module)
    counts = {c: sum(1 for m in facts if m.classification == c) for c in CLASSES}
    entry_counts = {k: sum(1 for e in entries if e.kind == k) for k in ENTRY_KINDS}

    return ReachReport(
        root=root.as_posix(),
        entry_points=tuple(entries),
        modules=tuple(facts),
        counts=counts,
        entry_counts=entry_counts,
        dynamic_surfaces=tuple(dynamic_surfaces),
        unparsable=tuple(sorted(unparsable)),
        index_extra_edges=tuple(sorted(index_extra)),
        broken_entries=tuple(sorted(broken_entries)),
        weak_edges=tuple(sorted(set(weak_edges))),
    )


def _is_test(rel: str) -> bool:
    base = rel.rsplit("/", 1)[-1]
    return (base.startswith("test_") or base.endswith("_test.py")
            or rel.startswith("tests/") or "/tests/" in rel
            or base == "conftest.py")


def _literal_corpus(root: Path, sources: Mapping[str, _Src],
                    tests: set[str]) -> list[tuple[str, str]]:
    """(owner, text) pairs of every string literal a NON-test module carries,
    plus agent/persona JSON.

    A test naming a module proves the test imports it, not that anything
    dispatches to it -- counting test literals here would launder an island
    into ``unknown`` and hide exactly what we are looking for. Owners are kept
    (rather than one concatenated blob) for two reasons: a module's own
    docstring must not be evidence for itself, and "who names it" is the only
    part of this signal a human can act on."""
    parts: list[tuple[str, str]] = []
    for rel in sorted(sources):
        if rel in tests:
            continue
        parts.append((rel, "\n".join(sorted(sources[rel].literals))))
    for cfg in sorted(root.glob("agents/*.json")) + sorted(root.glob("*/agents/*.json")):
        try:
            parts.append((cfg.relative_to(root).as_posix(),
                          cfg.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
    return parts


def _evidence(rel: str, dotted: str,
              corpus: Sequence[tuple[str, str]]) -> tuple[str, ...]:
    """Why we refuse to call this an island.

    Matching is on the DOTTED name or the path, never on a bare stem: "core"
    or "status" appears in prose everywhere, and a stem match would mark half
    the tree ``unknown`` -- a report that says "I don't know" about everything
    is as useless as one that lies. A module's OWN literals are excluded: this
    file's docstring names this file, and self-evidence would make every module
    that documents itself permanently unknowable."""
    stem = rel.rsplit("/", 1)[-1][:-3]
    if stem == "__init__":
        return ()
    probes = [p for p in (dotted, rel, rel[:-3]) if p]
    hits: set[str] = set()
    for owner, text in corpus:
        if owner == rel:
            continue
        for probe in probes:
            if probe in text:
                hits.add(f"{probe} @ {owner}")
    return tuple(sorted(hits))


def _discover_entries(root: Path, sources: Mapping[str, _Src], rels: list[str],
                      known_rels: set[str], tops: set[str], known: set[str],
                      rel_by_dotted: Mapping[str, str],
                      ) -> tuple[list[EntryPoint], list[str]]:
    entries: list[EntryPoint] = []
    broken: list[str] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, name: str, module: str, function: str,
            targets: Iterable[str]) -> None:
        key = (kind, name)
        if key in seen or module not in known_rels:
            return
        seen.add(key)
        entries.append(EntryPoint(kind=kind, name=name, module=module,
                                  function=function,
                                  targets=tuple(sorted(set(targets)))))

    def func_targets(src: _Src, func: str) -> set[str]:
        out: set[str] = set()
        for qual in sorted(_func_closure(src, func)):
            out |= _resolve(src.func_records.get(qual, ()), tops, known,
                            src.dotted, rel_by_dotted, src.rel)
        return out

    # 1. console scripts.
    #
    # ``entry`` is the strongest claim in this report -- "a human types this and
    # it runs". It is therefore the one claim that gets verified rather than
    # believed: the module must exist AND define the named function. A dead
    # target (`pkg = "pkg.cli:nosuchfunc"`) raises the moment anyone runs it,
    # and granting it ``entry`` would paint the whole closure behind it green
    # on the strength of a line in packaging metadata that nothing executes.
    script_modules: list[tuple[str, str]] = []
    for name, dotted, func in _console_scripts(root / "pyproject.toml"):
        rel = rel_by_dotted.get(dotted) or rel_by_dotted.get(dotted + ".__init__")
        if not rel:
            broken.append(f"script:{name} -> {dotted}"
                          f"{':' + func if func else ''} (no such module)")
            continue
        src = sources.get(rel)
        if func:
            attr = func.split(".", 1)[0]
            if src is None or src.tree is None:
                broken.append(f"script:{name} -> {rel}:{func} "
                              f"(module could not be parsed)")
                continue
            if attr not in src.toplevel:
                broken.append(f"script:{name} -> {rel}:{func} "
                              f"(module defines no `{attr}`)")
                continue
        tgts = func_targets(src, func) if (src and func) else set()
        add("script", name, rel, func, tgts)
        script_modules.append((rel, func))

    # 2. python -m <package>
    for rel in rels:
        if rel.rsplit("/", 1)[-1] == "__main__.py":
            pkg = rel[:-len("/__main__.py")].replace("/", ".")
            src = sources.get(rel)
            add("module_main", f"python -m {pkg}", rel, "",
                sorted(_resolve(src.records, tops, known, src.dotted,
                                rel_by_dotted, rel)) if src else ())

    # 3. __main__ guards
    for rel in rels:
        src = sources.get(rel)
        if not src or not src.has_main_guard or _is_test(rel):
            continue
        add("main_guard", src.dotted, rel, "",
            _resolve(src.records, tops, known, src.dotted, rel_by_dotted, rel))

    # 4/5/6: dispatch chains and poll loops, but ONLY inside modules that are
    # already entry points. A dispatch chain in a module nothing can run is not
    # a way in, and admitting it would invent entry points that no human or
    # tool can actually take.
    entry_mods = sorted({e.module for e in entries})
    for rel in entry_mods:
        src = sources.get(rel)
        if not src:
            continue
        for func, literal, payload in src.dispatch:
            recs: tuple = ()
            refs: tuple = ()
            for key, val in payload:
                if key == "records":
                    recs = val
                else:
                    refs = val
            tgts = _resolve(recs, tops, known, src.dotted, rel_by_dotted, rel)
            # names referenced in the branch that are bound to a module, and
            # module-local helpers the branch calls (the ``_spawn(rest)`` case)
            for ref in refs:
                if ref in src.func_records:
                    tgts |= func_targets(src, ref)
            for ref in refs:
                for qual in sorted(src.func_records):
                    if qual.rsplit(".", 1)[-1] == ref:
                        tgts |= func_targets(src, qual)
            tgts |= _named_module_targets(src, refs, tops, known,
                                          rel_by_dotted, rel)
            kind = "http" if literal.startswith("/") else "cli"
            add(kind, literal, rel, func, tgts)

        for func in sorted(src.func_loops):
            short = func.rsplit(".", 1)[-1]
            if not any(h in short for h in _LOOP_FUNC_HINTS):
                continue
            add("bus", f"{src.dotted}:{short}", rel, func,
                func_targets(src, func))

    entries.sort(key=lambda e: (ENTRY_KINDS.index(e.kind), e.name, e.module))
    return entries, broken


def _named_module_targets(src: _Src, refs: Iterable[str], tops: set[str],
                          known: set[str], rel_by_dotted: Mapping[str, str],
                          self_rel: str) -> set[str]:
    """Modules a branch touches only by NAME.

    HTTP handlers never import inside the branch; they call ``core.envelope``
    or ``hierarchy.capabilities`` against a module-level import. Resolving the
    referenced name back through the import that bound it is the only way those
    routes reach anything."""
    if not isinstance(src.tree, ast.Module):
        return set()
    bound = _module_level_bindings(src.tree)
    out: set[str] = set()
    for ref in refs:
        for rec in bound.get(ref, ()):
            out |= _resolve([rec], tops, known, src.dotted, rel_by_dotted, self_rel)
    return out
