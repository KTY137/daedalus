"""typegraph.py — whole-repo RESOLUTION of the type/data-structure layer.

Stage 2 of the type-graph lane. ``parse.py`` extracted RAW, unresolved facts
per file (``PyTypeFacts``: declarations, fields, signatures, import bindings).
This module turns those raw annotation STRINGS into resolved edges over a
separate node namespace, and reports what it refused to resolve.

WHY THIS IS NOT IN parse.py
---------------------------
Extraction had to live in ``parse.py`` because ``cache.file_key`` mixes a
sha256 of ``parse.py`` specifically, so an extractor in a sibling module would
be served stale cache rows by new code with no error (plan item M9, verified
empirically while the fixture corpus was built). Resolution has the opposite
shape: it needs the WHOLE file set, it is cheap, it runs serially in the parent
and it is NOT on the disk cache at all -- exactly like markdown link resolution
and Python import resolution, both of which live in ``index.py`` rather than in
the per-file extractor. Nothing here is cache-key coupled, so nothing here can
be served stale.

THE INVARIANTS THIS MODULE IS RESPONSIBLE FOR
---------------------------------------------
I2  ``graph.SymbolResolver.defs_by_file`` IS NOT TOUCHED. Resolution uses the
    SEPARATE ``types_by_file`` table built here, and this module never imports
    ``graph`` and never calls ``build_resolver``. The reason is not tidiness:
    ``SymbolResolver.resolve`` takes the FIRST match on a bare name, so a class
    ``Foo`` would displace a function ``Foo``; and ``graph.callees`` resolves
    EVERY identifier token in a body, so field names (``path``, ``root``,
    ``name``, ``line``, ``source``, ``module`` -- none of them stop-words) would
    become fabricated CALL edges in every slice. A grep for ``defs_by_file`` in
    this file must return nothing, and a test asserts it stays unchanged.

I5  REFUSE TO GUESS. Resolution is TWO-PASS: every type declaration in the repo
    is registered first, then annotations are resolved against the finished
    table -- so a forward reference and a definition order cannot change the
    answer. A name with ZERO candidates produces NO edge and increments
    ``unresolved``; a name with MORE THAN ONE produces NO edge and increments
    ``ambiguous``. There is no tie-break anywhere in this file. Deterministic is
    not the same as correct: two modules that both declare ``Result`` make the
    first sorted import a stably reproduced FALSE edge, which is strictly worse
    than a missing one because a determinism test would then protect it.

I6  A LENS, NOT A DIFFUSION CHANNEL. Nothing here registers a relation with
    ``dss`` and nothing here is added to ``DEFAULT_RELATION_WEIGHTS``. The hub
    cap (``DEFAULT_HUB_CAP``) was MEASURED on ``daedalus/`` before this code was
    written, not guessed, and both the kept and the suppressed edge counts are
    published so nobody mistakes the kept set for the whole truth.

I1/I3/I4 are structural and are kept by what this module does NOT do: it emits
node ids in their own ``type:``/``field:`` namespace, it never constructs a
``CodeUnit``, and it never returns anything that belongs in ``modules``,
``import_edges`` or ``all_units``.

THE RESOLUTION LADDER (three tiers, then nothing)
-------------------------------------------------
For one nominal name mentioned by one annotation in file F:

  1. a type DECLARED IN F, matched on its full in-file ``qualname`` (so
     ``Outer.Inner`` resolves and a bare ``Inner`` does not -- searching nested
     qualnames by leaf name is exactly the fabrication I5 forbids);
  2. a type reachable through F's OWN EXPLICIT IMPORT BINDING
     (``from m import T``, ``import m.n``, ``as`` spellings included).
     Module-name -> file resolution is done by FILTERING the import edges
     ``index.py`` already computed, never by re-resolving imports here, so a
     type edge can never contradict the import graph: if the import edge is
     absent, so is the type edge.
     A STAR IMPORT IS NOT A TIER. ``from m import *`` is walked, but only to
     DETECT an ambiguity -- it can never be the single winner, because what a
     star actually binds depends on ``m.__all__`` (a bare assignment, which
     ``parse.py`` does not record) and on the leading-underscore rule, and
     because a star from a module outside this repo can supply the same name
     unseen. Resolving on one produced edges to names that are a ``NameError``
     at the annotation site; see ``_star_candidates`` and
     ``tests/test_typegraph_star_imports.py``;
  3. nothing. Builtins (``str``, ``int``, ``Exception``) and typing vocabulary
     (``Protocol``, ``Literal``) are counted in their own buckets rather than as
     failures, because folding them into ``unresolved`` would make the coverage
     number a lie in one direction (1722 mentions of ``str`` in ``daedalus/``
     are not 1722 gaps).

A name bound by an import whose module is NOT in this repo is ``external``, not
``unresolved``: "declared somewhere else" and "declared nowhere" are different
facts and a report that merges them cannot be acted on.

DETERMINISM
-----------
Every iteration that can reach output is over a sorted sequence, every published
list is sorted by a total order, and no counter is derived from a set's
iteration order. ``union_id`` comes from ``parse.union_id`` (derived from the
site's identity, never from a counter) for the same reason.
"""
from __future__ import annotations

import builtins
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, NamedTuple

from .parse import (
    TYPE_FACTS_VERSION,
    AliasImport,
    FieldDecl,
    PyTypeFacts,
    SignatureDecl,
    TypeDecl,
    normalize_annotation,
    union_id,
)

# Bump when the MEANING of a published node, edge or coverage key changes.
# Separate from ``TYPE_FACTS_VERSION`` (the EXTRACTOR's version) because the two
# move independently: a resolution fix does not change what was extracted, and a
# reader has to be able to tell which half produced a number.
TYPE_GRAPH_VERSION = "1"

TYPE_NODE_KIND = "type"
FIELD_NODE_KIND = "field"

# Relation names. ``has_field``/``inherits``/``consumes``/``produces``/
# ``alias_of`` are the fixed vocabulary from the plan (Joern-CPG + CodexGraph).
# ``field_type`` is the "edge onward to the field's own type" that the has_field
# row of the plan's schema table asks for; CPG calls that EVAL_TYPE. It is a
# SEPARATE relation rather than a second row inside ``has_field`` because its
# direction is field -> type while has_field's is type -> field, and one
# relation layer with two directions is unreadable in a forest.
# ``instantiates`` is DEFERRED: it needs the call graph.
REL_HAS_FIELD = "has_field"
REL_FIELD_TYPE = "field_type"
REL_INHERITS = "inherits"
REL_CONSUMES = "consumes"
REL_PRODUCES = "produces"
REL_ALIAS_OF = "alias_of"

RELATIONS: tuple[str, ...] = (
    REL_HAS_FIELD, REL_FIELD_TYPE, REL_INHERITS,
    REL_CONSUMES, REL_PRODUCES, REL_ALIAS_OF,
)

# Relations whose fan-in the hub cap governs. The 2-hop blow-up that invariant
# I6 is about is function<->type: two functions that both mention the same type
# are two hops apart. ``has_field``/``inherits``/``alias_of`` are declaration
# structure, bounded by the number of declarations, and are not capped.
_CAPPED_RELATIONS = frozenset({REL_CONSUMES, REL_PRODUCES})

# MEASURED on daedalus/ (143 files, 2207 functions, 2182 carrying >=1 type
# edge, 227 distinct nominal types) BEFORE this module existed:
#
#   uncapped, two functions sharing a type are 2 hops apart -> 1,276,024 of
#   2,379,471 possible function pairs = 53.6% of the complete graph. ``str``
#   alone is 939,135 of them.
#
# The distribution has a MEASURED empty band, so the cap is picked off a plateau
# rather than judged: sorted per-type fan-in at the top is 1722, 883, 565, 394,
# 336, 325, 317, 175 || 33, 27, 26, 25, 23, 23, 20 ... -- a 5.3x gap between
# rank 8 (float) and rank 9 (Report) with NOTHING in between, so every cap in
# [34, 174] excludes exactly the same eight types (str, None, Any, dict, int,
# Path, bool, float -- the universal vocabulary, not one domain concept among
# them). 64 = max(8, min(64, round(0.03 * 2182))), i.e. the absolute number and
# the "a type touched by more than ~3% of all functions cannot discriminate
# between them" rule agree here. Choosing the HIGH side of the band is
# deliberate: hubs only grow, while a domain type that grows into the cap would
# SILENTLY lose all of its edges, so the headroom is worth more than the
# suppression.
#
# In a resolve-only graph most of those eight never arrive anyway (``str`` and
# ``int`` are builtins and ``Path`` is external -- none is DECLARED here), so on
# daedalus/ the cap is a guard rather than a filter. It exists for the repo
# where a hub IS locally declared. 0 disables it.
DEFAULT_HUB_CAP = 64

# Structural (Protocol) matching is a FLAGGED HEURISTIC, and these two constants
# are what keep it from being noise. A protocol with a single common member name
# (``run``, ``close``) matches half a repo by coincidence, which is the fixture
# corpus's own argument (``emit``/``flush`` "make coincidence the normal case"),
# so one member is not evidence. And a protocol that matches more classes than
# the cap has told us nothing at all: the whole match set is dropped rather than
# truncated, because publishing the first N of an arbitrary set is a guess
# wearing a number.
STRUCTURAL_MIN_MEMBERS = 2
STRUCTURAL_MAX_MATCHES = 25

_MAX_SAMPLE = 25

# Field origins in preference order when the same member was written twice --
# ``limit: int = 10`` in the class body AND ``self.limit = limit`` in
# ``__init__`` are two facts about ONE member (parse.py says so explicitly), and
# two ``field`` nodes for one member would be a fabrication. An ANNOTATED origin
# always wins first; this order only breaks the remaining ties.
_ORIGIN_RANK = {"annassign": 0, "self": 1, "assign": 2, "enum_member": 3}

# Typing / ABC vocabulary that is a WORD IN THE LANGUAGE, not a repo type.
# Counted in its own bucket so it never inflates ``unresolved``. Most of these
# arrive with an explicit ``from typing import ...`` and are classified
# ``external`` before this set is consulted; the set catches the spellings that
# arrive with no binding at all. A repo that genuinely DECLARES one of these
# names shadows it, because tier 1 (same-file declaration) runs first.
_VOCABULARY = frozenset({
    "Annotated", "Any", "AnyStr", "AsyncContextManager", "AsyncGenerator",
    "AsyncIterable", "AsyncIterator", "Awaitable", "BinaryIO", "ByteString",
    "Callable", "ChainMap", "ClassVar", "Collection", "Concatenate",
    "Container", "ContextManager", "Coroutine", "Counter", "DefaultDict",
    "Deque", "Dict", "Ellipsis", "Final", "FrozenSet", "Generator", "Generic",
    "Hashable", "IO", "InitVar", "ItemsView", "Iterable", "Iterator",
    "KeysView", "List", "Literal", "LiteralString", "Mapping", "MappingView",
    "Match", "MutableMapping", "MutableSequence", "MutableSet", "NamedTuple",
    "Never", "NewType", "NoReturn", "NoneType", "NotRequired", "Optional",
    "OrderedDict", "ParamSpec", "Pattern", "Protocol", "ReadOnly",
    "Required", "Reversible", "Self", "Sequence", "Set", "Sized",
    "SupportsAbs", "SupportsBytes", "SupportsComplex", "SupportsFloat",
    "SupportsIndex", "SupportsInt", "SupportsRound", "Text", "TextIO",
    "Tuple", "Type", "TypeAlias", "TypeGuard", "TypeIs", "TypeVar",
    "TypeVarTuple", "TypedDict", "Union", "Unpack", "ValuesView",
})

# Names bound in every module by the interpreter itself. Asked of ``builtins``
# rather than hand-listed so the set cannot drift from the interpreter running
# the scan, and filtered to actual TYPES so that ``len``/``print`` (never legal
# in an annotation) are not silently treated as resolved-away vocabulary. Every
# exception class comes along for free, which matters: ``-> ValueError`` is a
# real annotation shape and it is not an unresolved repo type.
_BUILTIN_TYPES = frozenset(
    name for name, value in sorted(vars(builtins).items())
    if isinstance(value, type)
) | {"None", "NoneType"}


# --------------------------------------------------------------------------- #
# Node identity                                                                #
# --------------------------------------------------------------------------- #
# A ``kind:`` prefix (the established ``repo:``/``dir:``/``file:`` convention in
# dss.py) PLUS a ``#`` separator that no repo-relative POSIX path carries. Both
# are needed and neither is the primary guard: ``dss._canonical_file_path``
# would happily read ``type:pkg/mod.py#Foo`` as a relative path, so what
# actually keeps a type node out of the file world is the node-KIND filter. The
# id scheme is defence in depth, and it makes a leak legible in a diff.
def type_node_id(module: str, qualname: str) -> str:
    """Forest node id for a type declaration."""
    return f"type:{module}#{qualname}"


def field_node_id(module: str, qualname: str, field_name: str) -> str:
    """Forest node id for one member of a type."""
    return f"field:{module}#{qualname}.{field_name}"


def function_ref(module: str, qualname: str) -> str:
    """Stable identity of a FUNCTION for edge attributes.

    Deliberately NOT a forest node id: functions are not forest nodes today
    (the forest's nodes are files and documents), so ``consumes``/``produces``
    attach to the FILE node and carry this string in their attributes. Join it
    to a ``CodeUnit`` on ``(module, line)`` -- never on ``name``, which is a
    bare leaf and collapses ``Cls.emit`` onto ``emit``.
    """
    return f"{module}#{qualname}"


def is_type_node_id(node_id: str) -> bool:
    """True for a ``type``/``field`` node id. For forest and dss guards."""
    return node_id.startswith(("type:", "field:"))


# --------------------------------------------------------------------------- #
# Naming: the importer's-eye dotted namespace                                  #
# --------------------------------------------------------------------------- #
class _PlainView(NamedTuple):
    rel_by_dotted: dict[str, str]
    canon: dict[str, str]


@dataclass(frozen=True)
class PlainNaming:
    """The repo-root dotted namespace, for callers that have no ``_PyNaming``.

    ``index.build_index`` passes its own ``_PyNaming`` (the authority: it knows
    about declared package roots and center-relative spellings). This is the
    no-center view, which is what an unconfigured repo gets anyway, and it
    exists so tools and tests can resolve without importing ``index`` -- which
    they must not do, because ``index`` imports THIS module.

    Only two members are used from either object, so they are interchangeable
    by duck typing: ``name(rel)`` and ``tables_for(rel).rel_by_dotted`` /
    ``.canon``.
    """

    _names: dict[str, str]
    _view: _PlainView

    @classmethod
    def from_rels(cls, rels: Iterable[str]) -> "PlainNaming":
        names = {rel: _py_dotted(rel) for rel in sorted(set(rels))}
        by_name: dict[str, list[str]] = {}
        for rel in sorted(names):
            by_name.setdefault(names[rel], []).append(rel)
        rel_by_dotted: dict[str, str] = {}
        for dotted in sorted(by_name):
            # Mirrors index._disambiguate: a .pyi is a stub DECLARING its .py
            # sibling, not a rival module; two genuine modules claiming one
            # dotted name is a real ambiguity and is refused, not tie-broken.
            cands = by_name[dotted]
            real = [r for r in cands if not r.endswith(".pyi")]
            if len(cands) == 1:
                rel_by_dotted[dotted] = cands[0]
            elif len(real) == 1:
                rel_by_dotted[dotted] = real[0]
        return cls(_names=names, _view=_PlainView(rel_by_dotted, {}))

    def name(self, rel: str) -> str:
        return self._names[rel]

    def tables_for(self, rel: str) -> _PlainView:
        return self._view


def _py_dotted(rel: str) -> str:
    """``a/b.py`` -> ``a.b``. Same rule as ``index._py_dotted``."""
    stem = rel[:-3] if rel.endswith(".py") else rel.rsplit(".", 1)[0]
    return stem.replace("/", ".")


# --------------------------------------------------------------------------- #
# The separate resolution table (I2)                                           #
# --------------------------------------------------------------------------- #
def types_by_file(
    facts_by_rel: Mapping[str, PyTypeFacts],
    ignored: Iterable[str] = (),
) -> dict[str, dict[str, TypeDecl]]:
    """rel -> {qualname: TypeDecl}: THE table invariant I2 demands.

    It is never merged into ``graph.SymbolResolver.defs_by_file`` and never
    passed to ``graph.build_resolver``. Keyed by the full in-file ``qualname``
    (``Outer.Inner``, not ``Inner``), because a leaf-name key would make two
    nested classes with the same leaf name collide and force a tie-break.

    A qualname declared twice in one file (an ``if``/``try`` pair) keeps the
    FIRST by line: both spellings share one node id, so there is nothing to
    arbitrate. The count is published as ``duplicate_declarations``.
    """
    skip = set(ignored)
    out: dict[str, dict[str, TypeDecl]] = {}
    for rel in sorted(facts_by_rel):
        if rel in skip:
            continue
        bucket: dict[str, TypeDecl] = {}
        for decl in facts_by_rel[rel].types:   # already sorted by (line, ...)
            bucket.setdefault(decl.qualname, decl)
        if bucket:
            out[rel] = bucket
    return out


# --------------------------------------------------------------------------- #
# Resolution outcomes                                                          #
# --------------------------------------------------------------------------- #
RESOLVED = "resolved"
UNRESOLVED = "unresolved"
AMBIGUOUS = "ambiguous"
EXTERNAL = "external"
BUILTIN = "builtin"
VOCABULARY = "vocabulary"

_OUTCOMES = (RESOLVED, UNRESOLVED, AMBIGUOUS, EXTERNAL, BUILTIN, VOCABULARY)


class _Outcome(NamedTuple):
    kind: str
    target: str = ""                      # node id, only when kind == RESOLVED
    candidates: tuple[str, ...] = ()      # node ids, only when kind == AMBIGUOUS


@dataclass(frozen=True)
class TypeGraph:
    """The resolved layer: JSON-ready nodes, edges per relation, and coverage.

    ``nodes`` is sorted by id. ``edges`` maps every relation name in
    ``RELATIONS`` (always present, possibly empty) to a tuple of
    ``{"source", "target", "attributes"}`` rows sorted by
    ``(source, target, canonical attributes)``. Nothing here is a file node,
    nothing here is a ``CodeUnit``, and nothing here belongs in ``modules``.
    """

    nodes: tuple[dict, ...] = ()
    edges: Mapping[str, tuple[dict, ...]] = None  # type: ignore[assignment]
    coverage: Mapping[str, Any] = None            # type: ignore[assignment]
    counts: Mapping[str, Any] = None              # type: ignore[assignment]

    def to_index_blocks(self) -> dict[str, Any]:
        """The three gated ``extra`` keys, ready to splice into the index dict.

        Stage 3 publishes these verbatim under a ``types_on`` gate. The
        ``excluded_from`` list is spelled out for the same reason the documents
        block spells out its own: a consumer who sees a type layer in the index
        and zero type nodes in ``hotspots`` must be able to read WHY here
        instead of inferring a clean bill of health.
        """
        return {
            "types": {
                "enabled": True,
                "parse_version": TYPE_FACTS_VERSION,
                "graph_version": TYPE_GRAPH_VERSION,
                **dict(self.counts or {}),
                "coverage": dict(self.coverage or {}),
                "excluded_from": [
                    "all_units", "defs_by_file", "dss_diffusion", "duplication",
                    "fan_in", "hotspots", "import_edges", "module_heat",
                    "modules", "n_files", "safety_graph_nodes",
                ],
            },
            "type_nodes": [dict(node) for node in self.nodes],
            "type_edges": {
                relation: [dict(edge) for edge in (self.edges or {}).get(relation, ())]
                for relation in RELATIONS
            },
        }


# --------------------------------------------------------------------------- #
# The resolver                                                                 #
# --------------------------------------------------------------------------- #
class _Resolver:
    """Annotation-name -> type node id, or a refusal with a reason.

    Constructed AFTER every declaration in the repo is registered, so it is
    two-pass by construction and a forward reference is not a special case.
    """

    def __init__(self, *, tbf: Mapping[str, Mapping[str, TypeDecl]],
                 facts_by_rel: Mapping[str, PyTypeFacts],
                 imports_by_file: Mapping[str, Iterable[str]],
                 naming) -> None:
        self._tbf = tbf
        self._facts = facts_by_rel
        self._imports = {
            rel: tuple(sorted(set(targets)))
            for rel, targets in sorted(imports_by_file.items())
        }
        self._naming = naming
        self._views: dict[str, dict[str, str]] = {}
        self._binds: dict[str, dict[str, tuple[AliasImport, ...]]] = {}
        self._stars: dict[str, tuple[AliasImport, ...]] = {}
        self._cache: dict[tuple[str, str], _Outcome] = {}

    # -- naming ------------------------------------------------------------ #
    def _dotted(self, rel: str) -> str:
        try:
            return self._naming.name(rel)
        except (KeyError, AttributeError):
            return _py_dotted(rel)

    def _view(self, importer: str) -> dict[str, str]:
        """dotted module name -> rel, restricted to what ``importer`` IMPORTS.

        This is the "reuse the import edges, do not recompute them" step. The
        candidate set is the file's own import targets (plus itself), so a
        resolved type edge always sits on top of an import edge that
        ``index.py`` already published; a module this file does not import
        cannot supply a type to it even if the dotted name would match.
        """
        cached = self._views.get(importer)
        if cached is not None:
            return cached
        by_name: dict[str, list[str]] = {}
        for rel in sorted({importer, *self._imports.get(importer, ())}):
            if rel not in self._facts:
                continue
            dotted = self._dotted(rel)
            if not dotted:
                continue
            by_name.setdefault(dotted, []).append(rel)
            # ``pkg/__init__.py`` is named ``pkg.__init__`` by the naming table,
            # but ``from pkg import Thing`` spells the package ``pkg``. Both
            # spellings name the same file, so accepting both is not a guess --
            # and if a real ``pkg.py`` also exists, the two candidates collide
            # and the name is refused below rather than tie-broken.
            if dotted.endswith(".__init__"):
                by_name.setdefault(dotted[: -len(".__init__")], []).append(rel)
        view = {
            dotted: rels[0]
            for dotted, rels in sorted(by_name.items())
            if len(set(rels)) == 1
        }
        self._views[importer] = view
        return view

    def _bindings(self, importer: str) -> dict[str, tuple[AliasImport, ...]]:
        cached = self._binds.get(importer)
        if cached is not None:
            return cached
        bound: dict[str, list[AliasImport]] = {}
        stars: list[AliasImport] = []
        facts = self._facts.get(importer)
        for alias in (facts.aliases if facts else ()):   # sorted by parse.py
            if alias.local == "*":
                stars.append(alias)
            else:
                bound.setdefault(alias.local, []).append(alias)
        self._binds[importer] = {k: tuple(v) for k, v in sorted(bound.items())}
        self._stars[importer] = tuple(stars)
        return self._binds[importer]

    def _star_imports(self, importer: str) -> tuple[AliasImport, ...]:
        self._bindings(importer)
        return self._stars.get(importer, ())

    def _alias_module(self, importer: str, alias: AliasImport) -> str:
        """The dotted module an ``ImportFrom`` binding reads from.

        Relative levels are anchored exactly the way
        ``parse.resolve_python_imports`` anchors them, so the two never
        disagree about which package a ``from ..x import y`` means.
        """
        if not alias.level:
            return alias.module
        parts = self._dotted(importer).split(".")
        base = ".".join(parts[: max(0, len(parts) - alias.level)])
        if not alias.module:
            return base
        return f"{base}.{alias.module}" if base else alias.module

    # -- candidate generation ---------------------------------------------- #
    def _declared(self, rel: str | None, qualname: str) -> str:
        """The node id of ``qualname`` in ``rel``, or "" if it is not declared
        there. The membership test is the ONLY thing that mints a target: a name
        is never minted into a node for having been mentioned."""
        if not rel or not qualname:
            return ""
        if qualname in self._tbf.get(rel, {}):
            return type_node_id(rel, qualname)
        return ""

    def _bare_candidates(self, importer: str,
                         name: str) -> tuple[list[str], bool, bool, set[tuple]]:
        """(node ids, a binding existed, a bound module was internal, targets).

        ``targets`` is the set of distinct ``(module, original name)`` pairs the
        bindings point at, and it is what makes the try/except case refusable
        even when only ONE of the two branches is a module we can see. Python
        binds the LAST import that executes, so two bindings that disagree about
        where the name comes from make the answer a property of the environment
        rather than of the source -- and picking the visible one would be a
        guess dressed up as a resolution. Two bindings that AGREE (the common
        ``if TYPE_CHECKING`` duplicate) are not a disagreement and still resolve.
        """
        view = self._view(importer)
        out: list[str] = []
        saw_binding = False
        saw_internal = False
        targets: set[tuple] = set()
        for alias in self._bindings(importer).get(name, ()):
            saw_binding = True
            if alias.kind != "from":
                # ``import a.b`` binds a MODULE under this name, never a type.
                targets.add(("module", alias.orig))
                continue
            module = self._alias_module(importer, alias)
            targets.add((module, alias.orig))
            rel = view.get(module)
            if rel is not None:
                saw_internal = True
            node = self._declared(rel, alias.orig)
            if node:
                out.append(node)
        return out, saw_binding, saw_internal, targets

    def _star_candidates(self, importer: str, name: str) -> list[str]:
        view = self._view(importer)
        out: list[str] = []
        for alias in self._star_imports(importer):
            module = self._alias_module(importer, alias)
            node = self._declared(view.get(module), name)
            if node:
                out.append(node)
        return out

    def _dotted_candidates(self, importer: str,
                           name: str) -> tuple[list[str], bool, bool, set[tuple]]:
        """Resolve ``head.mid.Leaf`` through the binding of ``head``."""
        view = self._view(importer)
        segs = name.split(".")
        head, mid, leaf = segs[0], segs[1:-1], segs[-1]
        out: list[str] = []
        saw_binding = False
        saw_internal = False
        targets: set[tuple] = set()
        for alias in self._bindings(importer).get(head, ()):
            saw_binding = True
            targets.add((alias.kind, alias.module, alias.orig, alias.level))
            modules: list[tuple[str, str]] = []   # (dotted module, qualname)
            if alias.kind == "import":
                # ``import a.b`` binds ``a`` and the annotation spells the rest
                # out, so the prefix is the bound name; ``import a.b as c``
                # binds ``c`` for the whole dotted target, so the prefix is it.
                prefix = (head if head == alias.orig.split(".")[0]
                          else alias.orig)
                modules.append((".".join([prefix, *mid]), leaf))
            else:
                base = self._alias_module(importer, alias)
                # ``from x import y`` leaves TWO readings of ``y.Z``: y is a
                # submodule of x holding Z, or y is a type in x holding a
                # nested Z. Both are generated; if both land, that IS an
                # ambiguity and is refused below rather than ranked.
                joined = ".".join([base, alias.orig, *mid]) if base \
                    else ".".join([alias.orig, *mid])
                modules.append((joined, leaf))
                modules.append((base, ".".join([alias.orig, *mid, leaf])))
            for module, qualname in modules:
                rel = view.get(module)
                if rel is not None:
                    saw_internal = True
                node = self._declared(rel, qualname)
                if node:
                    out.append(node)
        return out, saw_binding, saw_internal, targets

    # -- the ladder -------------------------------------------------------- #
    def resolve(self, importer: str, name: str) -> _Outcome:
        key = (importer, name)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        out = self._resolve(importer, name)
        self._cache[key] = out
        return out

    def _resolve(self, importer: str, name: str) -> _Outcome:
        name = name.strip()
        if not name:
            return _Outcome(UNRESOLVED)

        # Tier 1: declared in THIS file, matched on the full in-file qualname.
        local = self._declared(importer, name)
        if local:
            return _Outcome(RESOLVED, local)

        # Tier 2: through this file's own import statements.
        starred = False
        if "." in name:
            # ``import *`` binds bare names only, so a dotted spelling is never
            # a star's doing and the star tables are not consulted.
            cands, saw_binding, saw_internal, targets = self._dotted_candidates(
                importer, name)
        else:
            cands, saw_binding, saw_internal, targets = self._bare_candidates(
                importer, name)
            if self._star_imports(importer):
                star_cands = self._star_candidates(importer, name)
                if not cands and not saw_binding:
                    # A star is the ONLY route to this name. See
                    # ``_star_candidates``: a star can prove an AMBIGUITY and
                    # can never prove a BINDING, so the candidates are kept for
                    # the report and ``starred`` refuses the resolution below.
                    cands = star_cands
                    saw_binding = True
                    saw_internal = saw_internal or bool(cands)
                    starred = bool(cands)
                elif set(star_cands) - set(cands):
                    # An explicit binding AND a star that reaches a DIFFERENT
                    # declaration of the same name. Which one wins is statement
                    # order plus the star module's ``__all__``, i.e. not
                    # something this table can read -- so the two disagree and
                    # the answer is refused, exactly as for ``try``/``except``.
                    cands = [*cands, *star_cands]

        unique = sorted(set(cands))
        if len(unique) > 1:
            return _Outcome(AMBIGUOUS, "", tuple(unique))
        if starred:
            # Exactly one candidate, reachable only through ``import *``. NOT a
            # resolution: ``__all__`` and the leading-underscore rule are both
            # invisible here, and an unseen star module may supply the name too.
            # Counted as AMBIGUOUS rather than UNRESOLVED because the candidate
            # is real and naming it in the sample is what makes the refusal
            # actionable -- "we found this and could not prove the binding" is a
            # different report from "we found nothing".
            return _Outcome(AMBIGUOUS, "", tuple(unique))
        if len(targets) > 1 and unique:
            # The bindings DISAGREE about where the name comes from, and at
            # least one of them is a type we can see. Emitting the visible one
            # is the false edge I5 exists to prevent: which import wins is a
            # property of the environment (a try/except ImportError pair), not
            # of the source.
            return _Outcome(AMBIGUOUS, "", tuple(unique))
        if len(unique) == 1:
            return _Outcome(RESOLVED, unique[0])

        # Tier 3: nothing -- but say WHICH nothing.
        head = name.split(".")[0]
        if saw_binding and not saw_internal:
            return _Outcome(EXTERNAL)
        if head in _BUILTIN_TYPES and not saw_binding:
            return _Outcome(BUILTIN)
        if head in _VOCABULARY and not saw_binding:
            return _Outcome(VOCABULARY)
        if saw_binding:
            # The module IS in this repo and does not declare the name: a real
            # gap, not an external dependency.
            return _Outcome(UNRESOLVED)
        return _Outcome(UNRESOLVED)


# --------------------------------------------------------------------------- #
# Sites: one annotation slot, normalized                                       #
# --------------------------------------------------------------------------- #
class _Site(NamedTuple):
    """One annotation slot to resolve, plus everything an edge needs from it."""
    module: str
    relation: str
    source: str                 # edge source id (node id or file rel)
    owner: str                  # union_id owner component
    role: str                   # param|return|field|base|alias
    param: str
    position: int
    line: int
    raw: str
    attributes: dict


def _canon(value: Any) -> Any:
    """JSON-canonical form of an attribute value, for the sort key."""
    if isinstance(value, Mapping):
        return tuple(sorted((str(k), _canon(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_canon(v) for v in value)
    return (type(value).__name__, str(value))


def _edge_key(edge: Mapping[str, Any]) -> tuple:
    return (str(edge["source"]), str(edge["target"]),
            _canon(edge.get("attributes") or {}))


def _dedupe_fields(fields: Iterable[FieldDecl]) -> list[FieldDecl]:
    """One record per (owner, name). An annotated origin wins; ``_ORIGIN_RANK``
    breaks the rest. parse.py emits TWO records for a member written both as a
    class-body annotation and as ``self.x = ...`` on purpose -- they are two
    facts about one member, and choosing between them is a whole-repo judgement
    that lives here."""
    best: dict[tuple[str, str], FieldDecl] = {}
    for decl in fields:
        key = (decl.owner, decl.name)
        current = best.get(key)
        if current is None or _field_rank(decl) < _field_rank(current):
            best[key] = decl
    return [best[key] for key in sorted(best)]


def _field_rank(decl: FieldDecl) -> tuple:
    return (0 if decl.annotation else 1,
            _ORIGIN_RANK.get(decl.origin, 9), decl.line, decl.name)


def _member_names(qualname: str, fields: Iterable[FieldDecl],
                  signatures: Iterable[SignatureDecl]) -> frozenset[str]:
    """The member-name set used for structural (Protocol) matching. Methods and
    fields both count: a Protocol may declare either."""
    names = {f.name for f in fields if f.owner == qualname}
    names |= {s.name for s in signatures if s.owner == qualname}
    return frozenset(names)


# --------------------------------------------------------------------------- #
# The entry point                                                              #
# --------------------------------------------------------------------------- #
def resolve_type_graph(
    *,
    facts_by_rel: Mapping[str, PyTypeFacts],
    imports_by_file: Mapping[str, Iterable[str]] | None = None,
    naming: Any = None,
    languages: Mapping[str, Any] | None = None,
    ignored: Iterable[str] = (),
    hub_cap: int = DEFAULT_HUB_CAP,
) -> TypeGraph:
    """Resolve raw per-file type facts into the published type layer.

    ``facts_by_rel``   rel -> ``PyTypeFacts`` (Python files only; Stufe 1).
    ``imports_by_file`` rel -> rels, i.e. ``index["import_edges"]`` -- REUSED,
                       never recomputed. Absent means "no imports known", which
                       degrades to same-file resolution only.
    ``naming``         anything with ``name(rel)`` / ``tables_for(rel)``
                       (``index._PyNaming``). Defaults to ``PlainNaming``.
    ``languages``      ``index["languages"]``, so coverage can report every
                       non-Python language as ``not_supported`` rather than 0.
    ``ignored``        rels whose facts are withheld, exactly as ``all_units``
                       withholds units for out-of-scope files.
    ``hub_cap``        max fan-in a type may have and still keep its
                       ``consumes``/``produces`` edges. 0 disables.
    """
    skip = set(ignored)
    facts = {rel: f for rel, f in sorted(facts_by_rel.items()) if rel not in skip}
    rels = sorted(facts)
    if naming is None:
        naming = PlainNaming.from_rels(rels)
    imports = {
        rel: tuple(sorted(set(targets)))
        for rel, targets in sorted((imports_by_file or {}).items())
        if rel not in skip
    }

    # ---- pass 1: register every declaration ------------------------------ #
    tbf = types_by_file(facts)
    duplicate_declarations = sum(
        len(facts[rel].types) - len(tbf.get(rel, {})) for rel in rels)

    nodes: dict[str, dict] = {}
    for rel in rels:
        for qualname in sorted(tbf.get(rel, {})):
            decl = tbf[rel][qualname]
            nodes[type_node_id(rel, qualname)] = {
                "id": type_node_id(rel, qualname),
                "kind": TYPE_NODE_KIND,
                "module": rel,
                "qualname": qualname,
                "name": decl.name,
                "line": decl.line,
                "end_line": decl.end_line,
                "decl_kind": decl.kind,
                "owner": "",
                "origin": "",
                "annotation": decl.alias_target,
                "container": "",
                "optional": False,
                "language": decl.language,
            }

    fields_by_rel: dict[str, list[FieldDecl]] = {}
    for rel in rels:
        kept = [f for f in _dedupe_fields(facts[rel].fields)
                if f.owner in tbf.get(rel, {})]
        fields_by_rel[rel] = kept
        for decl in kept:
            ann = normalize_annotation(decl.annotation)
            node_id = field_node_id(rel, decl.owner, decl.name)
            nodes[node_id] = {
                "id": node_id,
                "kind": FIELD_NODE_KIND,
                "module": rel,
                "qualname": f"{decl.owner}.{decl.name}",
                "name": decl.name,
                "line": decl.line,
                "end_line": decl.line,
                "decl_kind": "",
                "owner": decl.owner,
                "origin": decl.origin,
                "annotation": decl.annotation,
                "container": ann.container,
                "optional": ann.optional,
                "language": decl.language,
            }

    # ---- pass 2: resolve annotations against the finished table ---------- #
    resolver = _Resolver(tbf=tbf, facts_by_rel=facts,
                         imports_by_file=imports, naming=naming)
    counters = {name: 0 for name in _OUTCOMES}
    site_counts = {
        "sites_total": 0, "sites_annotated": 0, "sites_missing": 0,
        "sites_unparsed": 0, "sites_any": 0, "sites_any_inside": 0,
        "sites_none": 0, "sites_no_member": 0, "sites_union": 0,
        "dropped_keys": 0,
    }
    cov = {
        "total_params": 0, "annotated_params": 0,
        "total_returns": 0, "annotated_returns": 0,
        "total_fields": 0, "annotated_fields": 0,
        "total_bases": 0, "n_functions": 0,
    }
    unresolved_sample: list[tuple] = []
    ambiguous_sample: list[tuple] = []
    edges: dict[str, list[dict]] = {relation: [] for relation in RELATIONS}

    def record(kind: str, site: _Site, name: str,
               candidates: tuple[str, ...] = ()) -> None:
        counters[kind] += 1
        if kind == UNRESOLVED:
            unresolved_sample.append(
                (site.module, site.line, site.role, site.param, name, site.raw))
        elif kind == AMBIGUOUS:
            ambiguous_sample.append(
                (site.module, site.line, site.role, name, tuple(candidates)))

    def emit(site: _Site) -> None:
        """Resolve one annotation slot and append its edges."""
        site_counts["sites_total"] += 1
        ann = normalize_annotation(site.raw)
        if ann.missing:
            site_counts["sites_missing"] += 1
            return
        site_counts["sites_annotated"] += 1
        if ann.unparsed:
            site_counts["sites_unparsed"] += 1
            return
        if ann.has_any:
            site_counts["sites_any_inside"] += 1
        if ann.is_any:
            site_counts["sites_any"] += 1
            return
        if ann.is_none:
            site_counts["sites_none"] += 1
            return
        site_counts["dropped_keys"] += len(ann.dropped)
        if not ann.members:
            site_counts["sites_no_member"] += 1
            return
        if ann.union:
            site_counts["sites_union"] += 1
        group = union_id(site.module, site.owner, site.role, site.param) \
            if ann.union else ""
        for member in ann.members:
            outcome = resolver.resolve(site.module, member)
            record(outcome.kind, site, member, outcome.candidates)
            if outcome.kind != RESOLVED:
                continue
            edges[site.relation].append({
                "source": site.source,
                "target": outcome.target,
                "attributes": {
                    **site.attributes,
                    "annotation": site.raw,
                    "member": member,
                    "container": ann.container,
                    "containers": list(ann.containers),
                    "optional": ann.optional,
                    "union": ann.union,
                    "union_id": group,
                    "line": site.line,
                },
            })

    for rel in rels:
        fact = facts[rel]
        # -- declarations: inherits + alias_of ----------------------------- #
        for qualname in sorted(tbf.get(rel, {})):
            decl = tbf[rel][qualname]
            source = type_node_id(rel, qualname)
            for position, base in enumerate(decl.bases):
                if "=" in base.split("[", 1)[0]:
                    # ``class C(Base, metaclass=M)`` -- parse.py keeps keyword
                    # arguments in ``bases`` as written. A metaclass is not a
                    # base and must not become an ``inherits`` edge.
                    continue
                cov["total_bases"] += 1
                emit(_Site(module=rel, relation=REL_INHERITS, source=source,
                           owner=qualname, role="base", param=str(position),
                           position=position, line=decl.line, raw=base,
                           attributes={"base": base, "position": position,
                                       "structural": False}))
            if decl.kind == "alias" and decl.alias_target:
                emit(_Site(module=rel, relation=REL_ALIAS_OF, source=source,
                           owner=qualname, role="alias", param="", position=-1,
                           line=decl.line, raw=decl.alias_target,
                           attributes={"alias_target": decl.alias_target}))

        # -- fields: has_field + field_type -------------------------------- #
        for decl in fields_by_rel[rel]:
            owner_id = type_node_id(rel, decl.owner)
            node_id = field_node_id(rel, decl.owner, decl.name)
            ann = normalize_annotation(decl.annotation)
            cov["total_fields"] += 1
            if decl.annotation:
                cov["annotated_fields"] += 1
            edges[REL_HAS_FIELD].append({
                "source": owner_id,
                "target": node_id,
                "attributes": {
                    "name": decl.name,
                    "annotation": decl.annotation,
                    "origin": decl.origin,
                    "container": ann.container,
                    "optional": ann.optional,
                    "has_default": decl.has_default,
                    "line": decl.line,
                },
            })
            # An Enum member is a VALUE, not a typed field: parse.py forces its
            # annotation to "" precisely so no member->type edge can be
            # fabricated for it, and ``emit`` will count it as missing.
            emit(_Site(module=rel, relation=REL_FIELD_TYPE, source=node_id,
                       owner=f"{decl.owner}.{decl.name}", role="field",
                       param="", position=-1, line=decl.line,
                       raw=decl.annotation,
                       attributes={"field": decl.name, "owner": decl.owner,
                                   "origin": decl.origin}))

        # -- signatures: consumes + produces ------------------------------- #
        for sig in fact.signatures:
            cov["n_functions"] += 1
            ref = function_ref(rel, sig.qualname)
            base_attrs = {
                "function": sig.qualname,
                "function_ref": ref,
                "function_line": sig.line,
                "owner": sig.owner,
            }
            for param in sig.params:
                if param.position == 0 and sig.receiver \
                        and param.name == sig.receiver:
                    continue          # the implicit self/cls, never a param
                cov["total_params"] += 1
                if param.annotation:
                    cov["annotated_params"] += 1
                emit(_Site(
                    module=rel, relation=REL_CONSUMES, source=rel,
                    owner=sig.qualname, role="param", param=param.name,
                    position=param.position, line=sig.line,
                    raw=param.annotation,
                    attributes={**base_attrs, "role": "param",
                                "param": param.name,
                                "position": param.position,
                                "param_kind": param.kind,
                                "has_default": param.has_default}))
            cov["total_returns"] += 1
            if sig.returns:
                cov["annotated_returns"] += 1
            emit(_Site(
                module=rel, relation=REL_PRODUCES, source=rel,
                owner=sig.qualname, role="return", param="", position=-1,
                line=sig.line, raw=sig.returns,
                attributes={**base_attrs, "role": "return", "param": "",
                            "position": -1}))

    # ---- structural (Protocol) matching: a FLAGGED heuristic ------------- #
    members: dict[str, frozenset[str]] = {}
    for rel in rels:
        for qualname in sorted(tbf.get(rel, {})):
            members[type_node_id(rel, qualname)] = _member_names(
                qualname, facts[rel].fields, facts[rel].signatures)
    nominal = {(edge["source"], edge["target"]) for edge in edges[REL_INHERITS]}
    structural_matches = 0
    overmatched: list[str] = []
    protocols = sorted(
        node_id for node_id, node in sorted(nodes.items())
        if node["kind"] == TYPE_NODE_KIND and node["decl_kind"] == "protocol")
    for proto in protocols:
        wanted = members.get(proto, frozenset())
        if len(wanted) < STRUCTURAL_MIN_MEMBERS:
            continue
        matches = sorted(
            node_id for node_id in sorted(members)
            if node_id != proto
            and nodes[node_id]["decl_kind"] != "protocol"
            and (node_id, proto) not in nominal
            and wanted <= members[node_id])
        if len(matches) > STRUCTURAL_MAX_MATCHES:
            # Told us nothing: the whole match set is dropped rather than
            # truncated, because the first N of an arbitrary set is a guess.
            overmatched.append(proto)
            continue
        for node_id in matches:
            structural_matches += 1
            edges[REL_INHERITS].append({
                "source": node_id,
                "target": proto,
                "attributes": {
                    "base": nodes[proto]["qualname"],
                    "position": -1,
                    "structural": True,
                    "shared_members": len(wanted),
                    "heuristic": "protocol_member_names",
                },
            })

    # ---- hub cap (I6): measured, applied, and published ------------------ #
    raw_by_relation = {relation: len(rows) for relation, rows in edges.items()}
    fan_in: dict[str, set[str]] = {}
    for relation in sorted(_CAPPED_RELATIONS):
        for edge in edges[relation]:
            fan_in.setdefault(edge["target"], set()).add(
                f"{relation}:{edge['attributes']['function_ref']}")
    hubs = sorted(
        (target for target, refs in fan_in.items()
         if hub_cap and len(refs) > hub_cap),
        key=lambda target: (-len(fan_in[target]), target))
    hub_set = set(hubs)
    suppressed = 0
    if hub_set:
        for relation in sorted(_CAPPED_RELATIONS):
            keep = [e for e in edges[relation] if e["target"] not in hub_set]
            suppressed += len(edges[relation]) - len(keep)
            edges[relation] = keep

    for relation in RELATIONS:
        edges[relation] = sorted(edges[relation], key=_edge_key)

    # ---- coverage -------------------------------------------------------- #
    lang_report = {"python": "supported"}
    for lang in sorted(languages or {}):
        if lang != "python":
            # NEVER a numeric 0: the tree-sitter path has no class/field
            # vocabulary, so "we did not look" must not read as "we looked and
            # found none". Stufe 1 is Python only.
            lang_report[lang] = "not_supported"

    coverage = {
        **cov,
        **site_counts,
        **{name: counters[name] for name in _OUTCOMES},
        "attempts": sum(counters.values()),
        "duplicate_declarations": duplicate_declarations,
        "files_truncated": sorted(
            rel for rel in rels if facts[rel].truncated),
        "future_annotations_files": sum(
            1 for rel in rels if facts[rel].future_annotations),
        "hub_cap": hub_cap,
        "hub_suppressed_edges": suppressed,
        "hub_suppressed_types": [
            {"id": target, "fan_in": len(fan_in[target])} for target in hubs],
        "edges_before_hub_cap": raw_by_relation,
        "structural_min_members": STRUCTURAL_MIN_MEMBERS,
        "structural_max_matches": STRUCTURAL_MAX_MATCHES,
        "structural_matches": structural_matches,
        "structural_overmatched": overmatched,
        "unresolved_sample": [
            {"module": m, "line": ln, "role": role, "param": param,
             "name": name, "annotation": raw}
            for m, ln, role, param, name, raw
            in sorted(set(unresolved_sample))[:_MAX_SAMPLE]],
        "ambiguous_sample": [
            {"module": m, "line": ln, "role": role, "name": name,
             "candidates": list(cands)}
            for m, ln, role, name, cands
            in sorted(set(ambiguous_sample))[:_MAX_SAMPLE]],
        "truncated": (len(set(unresolved_sample)) > _MAX_SAMPLE
                      or len(set(ambiguous_sample)) > _MAX_SAMPLE),
        "languages": lang_report,
    }
    counts = {
        "count": sum(1 for node in nodes.values()
                     if node["kind"] == TYPE_NODE_KIND),
        "n_fields": sum(1 for node in nodes.values()
                        if node["kind"] == FIELD_NODE_KIND),
        "n_nodes": len(nodes),
        "n_edges": sum(len(rows) for rows in edges.values()),
        "n_edges_by_relation": {r: len(edges[r]) for r in RELATIONS},
        "n_files": len(rels),
        "hub_cap": hub_cap,
    }
    return TypeGraph(
        nodes=tuple(nodes[node_id] for node_id in sorted(nodes)),
        edges={relation: tuple(edges[relation]) for relation in RELATIONS},
        coverage=coverage,
        counts=counts,
    )
