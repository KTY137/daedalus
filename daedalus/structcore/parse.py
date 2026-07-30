"""Parsing abstraction — extract code units (functions/methods) per language.

Three backends, chosen automatically:
  * Python  -> stdlib ``ast`` (always available, precise).
  * others  -> tree-sitter via ``tree_sitter_language_pack`` IF installed.
  * neither -> no unit-level extraction; the caller falls back to the universal
    windowed clone pass (see ``clones.window_clones``), which needs no parser.

The unit source returned here is what ``clones.fingerprint`` hashes, so this is
the precision lever: with tree-sitter, C/Java/Rust/… get real function-level
clone detection; without it, they still get window-level detection.

This module ALSO carries the type/data-structure extractor (see the section at
the bottom: ``PyTypeFacts`` and friends). It lives here and not in a sibling
module for one non-negotiable reason: ``cache.file_key`` mixes a sha256 of
*this file, by name* into every disk-cache key, so an edit to the extractor
invalidates every cached row. An extractor in a sibling module would leave the
key untouched and serve rows written by the PREVIOUS extractor to the new code
-- wrong type blocks, no error, no log line. What the extractor produces is raw
and unresolved: classes, fields, signatures and import NAME bindings as written,
with every annotation kept as a RAW STRING. Resolution is whole-repo work and
happens in the parent process, one layer up.
"""
from __future__ import annotations

import ast
import copy
from dataclasses import dataclass
from functools import lru_cache

from .languages import LanguageSpec


@dataclass(frozen=True)
class CodeUnit:
    language: str
    module: str          # dotted/relative module id
    name: str
    line: int            # 1-based
    end_line: int
    loc: int
    source: str


@lru_cache(maxsize=1)
def tree_sitter_available() -> bool:
    try:
        import tree_sitter_language_pack  # noqa: F401

        return True
    except Exception:
        return False


@lru_cache(maxsize=None)
def _parser_for(grammar: str):
    """Cached parser per grammar — a missing/slow grammar (download failure,
    unknown name) is attempted once per process, then treated as absent so the
    file degrades to the universal window pass without repeated retries."""
    try:
        from tree_sitter_language_pack import get_parser

        return get_parser(grammar)
    except Exception:
        return None


def extract_units(module: str, text: str, spec: LanguageSpec) -> list[CodeUnit]:
    """Return the top-level and nested function/method units in ``text``."""
    if spec.name == "python":
        return _python_units(module, text)
    if spec.ts_grammar and tree_sitter_available():
        try:
            return _tree_sitter_units(module, text, spec)
        except Exception:
            return []  # grammar missing / parse blew up -> window pass covers it
    return []


# --------------------------------------------------------------------------- #
# Python (stdlib ast) — generalizes codemap.analyze_python's unit extraction   #
# --------------------------------------------------------------------------- #
def _python_units(module: str, text: str) -> list[CodeUnit]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    return _units_from_tree(tree, module, text.splitlines())


def _units_from_tree(tree, module: str, lines: list[str]) -> list[CodeUnit]:
    units: list[CodeUnit] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", node.lineno) or node.lineno
            src = "\n".join(lines[node.lineno - 1: end])
            units.append(CodeUnit(
                language="python", module=module, name=node.name,
                line=node.lineno, end_line=end, loc=end - node.lineno + 1, source=src,
            ))
    return units


def python_units_and_imports(module: str, text: str
                             ) -> tuple[list[CodeUnit], list[tuple]]:
    """Units AND raw import records from a SINGLE ``ast.parse``.

    ``build_index`` used to parse every Python file twice — once via
    ``extract_units`` and again via ``python_imports`` — which is pure waste on
    the hot path. Both walks read the same tree here. Unit order is unchanged
    (``ast.walk`` is deterministic and the unit predicate is untouched), which
    matters because the clone passes consume ``all_units`` positionally.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return [], []
    return _units_from_tree(tree, module, text.splitlines()), _import_records(tree)


# --------------------------------------------------------------------------- #
# tree-sitter (optional) — any language in the pack                            #
# --------------------------------------------------------------------------- #
def _tree_sitter_units(module: str, text: str, spec: LanguageSpec) -> list[CodeUnit]:
    parser = _parser_for(spec.ts_grammar)
    if parser is None:
        return []
    data = text.encode("utf-8", errors="replace")
    tree = parser.parse(data)
    wanted = set(spec.function_types)
    units: list[CodeUnit] = []

    # Iterative pre-order walk. A recursive one blows Python's recursion limit
    # on deeply nested real-world ASTs (long chained/generated expressions) —
    # push children reversed so they pop back in source order.
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type in wanted:
            start = node.start_point[0] + 1
            end = node.end_point[0] + 1
            src = data[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
            units.append(CodeUnit(
                language=spec.name, module=module, name=_ts_name(node, data),
                line=start, end_line=end, loc=end - start + 1, source=src,
            ))
        stack.extend(reversed(node.children))
    return units


_ANON = "<anonymous>"

# C/C++ hide the function name where no other grammar puts it. There is no
# ``name`` field on ``function_definition``; the name sits at the bottom of a
# ``declarator`` chain:
#
#     int add(int a, int b) {}   fn_def -declarator-> function_declarator
#                                       -declarator-> identifier "add"
#
# and the chain can be arbitrarily long, because pointer/reference/array
# returns each interpose a wrapper (``void *bar()`` adds pointer_declarator).
# Meanwhile the RETURN TYPE is a plain ``type_identifier`` sitting as a direct
# child of the same node -- which is why the generic direct-children scan below
# used to return "MyType" for "MyType foo(void)". That is worse than no name:
# every function returning MyType collides on one identifier, and unlike
# "<anonymous>" a fabricated name is NOT filtered out of the clone passes.
# Hence: once a ``declarator`` field exists, its chain is authoritative and we
# never fall through to the scan.
_DECL_WRAPPERS = ("function_declarator", "pointer_declarator",
                  "reference_declarator", "array_declarator")
_DECL_NAME_TYPES = ("identifier", "field_identifier", "qualified_identifier",
                    "destructor_name", "operator_name", "template_function")


def _decl_text(node, data: bytes) -> str:
    """Name text for one resolved declarator node.

    ``operator bool()`` is the one shape whose name node spans more than the
    name: the grammar's ``operator_cast`` covers the parameter list and cv
    qualifiers too, so slicing it whole yields "operator bool() const". Cut at
    the end of its ``type`` field instead -> "operator bool" (and, when it is
    wrapped in a qualified_identifier, "Foo::operator bool").
    """
    cast = node if node.type == "operator_cast" else node.child_by_field_name("name")
    if cast is not None and cast.type == "operator_cast":
        ty = cast.child_by_field_name("type")
        if ty is not None:
            return data[node.start_byte:ty.end_byte].decode("utf-8", errors="replace")
    return data[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _declarator_name(node, data: bytes) -> str:
    """Walk a C/C++ declarator chain down to the name, or give up honestly.

    The depth bound is a guard against a malformed/adversarial tree, not an
    expected limit -- real declarator chains are two or three links.
    """
    for _ in range(16):
        if node is None:
            return _ANON
        if node.type == "operator_cast" or node.type in _DECL_NAME_TYPES:
            return _decl_text(node, data)
        # A function returning a function pointer -- "int (*get_handler(int))(void)"
        # -- nests a SECOND function_declarator inside parentheses, and which of
        # the two is "the function being defined" is genuinely ambiguous. Guessing
        # here would fabricate a name, so under-report instead.
        if node.type == "parenthesized_declarator":
            return _ANON
        if node.type not in _DECL_WRAPPERS:
            return _ANON
        nxt = node.child_by_field_name("declarator")
        if nxt is None:
            # reference_declarator ("std::string& Cfg::name()") carries its inner
            # declarator as an unnamed child rather than a labelled field.
            nxt = next((c for c in node.children if c.is_named), None)
        node = nxt
    return _ANON


def _ts_name(node, data: bytes) -> str:
    field = node.child_by_field_name("name")
    if field is not None:
        return data[field.start_byte:field.end_byte].decode("utf-8", errors="replace")
    decl = node.child_by_field_name("declarator")
    if decl is not None:
        return _declarator_name(decl, data)
    for child in node.children:
        if child.type in ("identifier", "field_identifier", "type_identifier"):
            return data[child.start_byte:child.end_byte].decode("utf-8", errors="replace")
    return _ANON


# --------------------------------------------------------------------------- #
# Python import graph (precise; other languages deferred to the graph module)  #
# --------------------------------------------------------------------------- #
def _import_records(tree) -> list[tuple]:
    """Raw, *unresolved* import statements: (kind, level, module, names).

    Deliberately independent of ``internal_tops``/``known`` — those are derived
    from the whole file set, so they are not available until every file has been
    collected. Keeping extraction (per-file, expensive, parallelizable) apart
    from resolution (whole-repo, cheap, serial) is what lets the parse run in a
    worker process while resolution stays in the parent.
    """
    out: list[tuple] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.append(("import", 0, None, tuple(a.name for a in node.names)))
        elif isinstance(node, ast.ImportFrom):
            out.append(("from", node.level or 0, node.module,
                        tuple(a.name for a in node.names)))
    return out


def python_import_records(text: str) -> list[tuple]:
    """Raw import records for one Python source (see ``_import_records``)."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    return _import_records(tree)


def resolve_python_imports(records: list[tuple], internal_tops: set[str],
                           known: set[str], src_dotted: str = "") -> set[str]:
    """Resolve raw import records to internal dotted modules (for fan-in/out).

    Handles both absolute (``from daedalus.core import x``) and RELATIVE
    (``from .router import x``, ``from ..core import y``) imports — the latter
    anchored to ``src_dotted`` (this file's own dotted module), which is
    essential inside packages that use relative imports heavily.
    """
    out: set[str] = set()
    for kind, level, module, names in records:
        if kind == "import":
            for name in names:
                if name.split(".")[0] in internal_tops:
                    out.add(name)
            continue
        if level:
            parts = src_dotted.split(".")
            base = ".".join(parts[:max(0, len(parts) - level)])
            m = f"{base}.{module}" if module else base
            if not m:
                continue
        else:
            m = module
            if not m or m.split(".")[0] not in internal_tops:
                continue
        matched = False
        for a in names:
            sub = f"{m}.{a}"
            if sub in known:
                out.add(sub)
                matched = True
        if not matched and (m in known or m.split(".")[0] in internal_tops):
            out.add(m)
    return out


def python_imports(text: str, internal_tops: set[str], known: set[str],
                   src_dotted: str = "") -> set[str]:
    """Internal modules imported by this Python source. Parse + resolve in one
    call — kept as the standalone API; ``build_index`` uses the split form."""
    return resolve_python_imports(
        python_import_records(text), internal_tops, known, src_dotted)


# =========================================================================== #
# Type / data-structure extraction (Python only, Stufe 1)                     #
#                                                                             #
# Everything below is ADDITIVE and reaches the index through NEW functions     #
# only. ``extract_units``/``_units_from_tree`` above are untouched, on purpose: #
# a class or a field that became a ``CodeUnit`` would enter ``all_units``, and  #
# ``clones.renamed_clusters`` matches abstracted fingerprints EXACTLY, with no  #
# threshold and no cluster cap, in the PRECISE tier -- so every dataclass with  #
# the same field count would be published as a full-confidence "renamed clone". #
# The records below therefore deliberately carry NO ``source`` and NO ``loc``   #
# field, which makes that mistake raise ``AttributeError`` in the clone pass    #
# instead of silently producing a wrong report.                                #
#                                                                             #
# Annotations are captured as RAW TEXT and never resolved here. Under           #
# ``from __future__ import annotations`` an annotation may be written as a      #
# string, and that is the NORMAL case in this repo; ``annotation_text`` folds   #
# the quoted and unquoted spellings onto the same text, so a consumer never has #
# to care which one the author used. Nothing here imports anything from the     #
# analysed source: ``typing.get_type_hints`` would EXECUTE imports, which is an #
# egress/safety violation in this codebase.                                    #
# =========================================================================== #

# Bump when the MEANING of any record below changes. Published in the index's
# ``types`` block so a report says which extractor produced it.
TYPE_FACTS_VERSION = "1"

# The reserved spelling for "annotated, resolvable, and says nothing". A bare
# ``Any`` must never become an edge target (it is the explicit ABSENCE of type
# information, and as a node it would be a hub that poisons every ranking), so
# ``normalize_annotation`` reports it as the ``is_any`` flag with an EMPTY
# member list -- refusing to edge is the safe default, not an opt-in. This
# constant is the label to count it under. It is not a legal Python identifier,
# so it cannot be mistaken for a type name if it ever does reach an id.
ANY_SENTINEL = "<any>"


@dataclass(frozen=True)
class TypeDecl:
    """One type DECLARATION as written. ``bases``/``decorators`` are raw text.

    ``qualname`` is dotted WITHIN the file and never contains the module, so it
    is ``Outer.Inner`` / ``Cls`` / ``fn.<locals>.Local`` (the same shape as
    Python's own ``__qualname__``). ``name`` is the leaf, which is what
    ``CodeUnit.name`` also holds.

    Deliberately NOT field-compatible with ``CodeUnit``: no ``source``, no
    ``loc``. That is the enforcement of "type is a forest node, never a unit"
    (see the section header). ``markdown.DocSection`` made the OPPOSITE choice
    on purpose, because a doc section is meant to reach ``build_resolver``.
    """
    module: str          # repo-relative path, same namespace as CodeUnit.module
    qualname: str
    name: str
    kind: str            # class|dataclass|typeddict|namedtuple|enum|protocol|alias
    line: int            # 1-based
    end_line: int
    bases: tuple[str, ...] = ()
    decorators: tuple[str, ...] = ()
    alias_target: str = ""   # only for kind == "alias": the aliased expression
    language: str = "python"


@dataclass(frozen=True)
class FieldDecl:
    """One member of a type, as written.

    ``origin`` says HOW it was written, because the four ways do not carry the
    same evidence:

      ``annassign``    ``x: int`` in the class body -- the only origin that
                       always carries an annotation.
      ``assign``       ``x = 10`` in the class body -- a member with no declared
                       type. ``annotation`` is "".
      ``self``         ``self.x = ...`` inside a method -- real state, usually
                       unannotated. ``annotation`` is "" unless it was written
                       ``self.x: int = ...``.
      ``enum_member``  ``FAST = "fast"`` in an ``Enum`` body. Enum members are
                       VALUES, not typed fields: ``annotation`` is ALWAYS "" and
                       a consumer must not emit a member->type edge for them,
                       because there is no type to point at.

    The same name can appear twice with different origins (``limit: int = 10``
    in the body plus ``self.limit = limit`` in ``__init__``). Both are kept:
    they are two different facts about one member, and deciding which one wins
    is a whole-repo judgement, not a per-file one.
    """
    module: str
    owner: str           # the owning TypeDecl.qualname
    name: str
    line: int
    annotation: str = ""      # RAW text, "" when absent. NEVER resolved here.
    origin: str = "annassign"
    has_default: bool = False
    language: str = "python"


@dataclass(frozen=True)
class ParamDecl:
    """One parameter position. ``position`` is 0-based over the concatenation
    posonly + args + vararg + kwonly + kwarg, in that order -- which is the
    order a reader sees in the source, not the order Python stores them in."""
    name: str
    position: int
    annotation: str = ""      # RAW text, "" when absent
    kind: str = "arg"         # posonly|arg|vararg|kwonly|kwarg
    has_default: bool = False


@dataclass(frozen=True)
class SignatureDecl:
    """One function's annotated surface: what it takes and what it returns.

    ``receiver`` is the name of the implicit first parameter (``self``/``cls``,
    or whatever the author called it) when this function is a method and NOT a
    staticmethod; "" otherwise. It is carried rather than assumed because a
    consumer that filters on the literal string ``self`` both misses renamed
    receivers and wrongly drops the first argument of a staticmethod.
    """
    module: str
    qualname: str
    name: str
    line: int
    end_line: int
    owner: str = ""           # enclosing TypeDecl.qualname, "" at module level
    params: tuple[ParamDecl, ...] = ()
    returns: str = ""         # RAW text of the return annotation, "" when absent
    receiver: str = ""
    is_async: bool = False
    decorators: tuple[str, ...] = ()
    language: str = "python"


@dataclass(frozen=True)
class AliasImport:
    """A NAME binding introduced by an import statement.

    ``_import_records`` above throws ``ast.alias.asname`` away, so
    ``from x import Result as R`` is unrecoverable from it and the annotation
    ``R`` could never be resolved. This record is emitted SEPARATELY rather than
    by widening that 4-tuple, because the 4-tuple is unpacked positionally in
    ``resolve_python_imports`` and round-tripped through the disk cache.

    A star import is recorded with ``local == "*"`` and ``orig == "*"``: it
    binds names this file's text does not mention, which is exactly the
    evidence a resolver needs in order to REFUSE (two star imports from two
    modules that both declare ``Result`` make ``Result`` ambiguous, and the
    ambiguity is not visible anywhere else).
    """
    local: str           # the name as bound here (asname or name); "*" for star
    kind: str            # "import" | "from"
    level: int           # relative-import dots; 0 for absolute
    module: str          # "from X import ..." -> X; "" for a bare ``import a.b``
    orig: str            # the imported name / dotted target as written
    line: int


@dataclass(frozen=True)
class PyTypeFacts:
    """Everything the type layer needs from ONE Python file: raw, unresolved.

    Same contract as ``_import_records``: per-file, expensive, parallelizable
    work stays here; whole-repo, cheap, serial resolution stays in the parent.
    Every field is a tuple, so an instance is immutable and safe as a plain
    dataclass default on ``FileAnalysis`` (no ``default_factory`` needed) and
    safe to hand across a process boundary.

    ``truncated`` is True only if the statement descent hit its depth guard,
    i.e. the file is more deeply nested than any real code -- reported rather
    than hidden, so a missing type is never silently a missing type.
    """
    module: str = ""
    types: tuple[TypeDecl, ...] = ()
    fields: tuple[FieldDecl, ...] = ()
    signatures: tuple[SignatureDecl, ...] = ()
    aliases: tuple[AliasImport, ...] = ()
    future_annotations: bool = False
    truncated: bool = False


@dataclass(frozen=True)
class Annotation:
    """The normalized reading of ONE raw annotation string. No repo knowledge.

    ``members`` are the nominal names an edge may point at, in SOURCE ORDER,
    deduplicated on first occurrence. Union members and container elements both
    land here, because in both cases the answer to "what type does this
    position mention" is the same list; ``union`` says whether they are
    alternatives (and therefore need a shared ``union_id``) and ``containers``
    says what shell they were wrapped in.

    ``None`` never becomes a member -- ``X | None`` is "optional X", not a union
    with a type called None -- and a bare ``Any`` never becomes a member either
    (see ``ANY_SENTINEL``). A generic produces NO member per instantiation:
    ``list[User]`` is one edge to ``User`` with ``container == "list"``, so the
    type vocabulary stays bounded by the number of declarations instead of the
    number of call sites.

    ``dropped`` holds nominal names the element rule deliberately discards --
    mapping KEY types (``dict[str, User]`` -> ``User``, key dropped) and
    ``Callable`` parameter types. They are published so coverage can be honest
    about them; they are never edge targets.

    A dotted name is kept VERBATIM (``ast.AST`` stays ``ast.AST``). Resolving it
    by its last segment would ask for a name called ``AST``, which nothing in
    such a file binds -- the module ``ast`` is what is bound.
    """
    raw: str
    members: tuple[str, ...] = ()
    container: str = ""              # outermost container spelling, "" if none
    containers: tuple[str, ...] = ()  # full nesting chain, outermost first
    dropped: tuple[str, ...] = ()
    optional: bool = False           # Optional[X] / X | None was stripped
    union: bool = False              # >1 member and they are ALTERNATIVES
    is_any: bool = False             # the whole annotation is a bare Any
    has_any: bool = False            # an Any appears anywhere inside it
    is_none: bool = False            # the whole annotation is None (no return type)
    missing: bool = False            # there was no annotation at all
    unparsed: bool = False           # a string annotation that is not an expression


# --------------------------------------------------------------------------- #
# Annotation text: the quoted and the unquoted spelling, folded onto one form  #
# --------------------------------------------------------------------------- #
# Structural vocabulary, matched on the LAST dotted segment so that ``Mapping``,
# ``typing.Mapping`` and ``collections.abc.Mapping`` read the same. This is
# SYNTACTIC only -- these names change the SHAPE of an annotation, so they have
# to be known here. Deciding that ``str`` or ``Literal`` is not a repo type is a
# vocabulary judgement and belongs one layer up, where the repo is known.
_UNION_NAMES = frozenset({"Union", "Optional"})
_TRANSPARENT = frozenset({
    "Annotated", "Final", "ClassVar", "InitVar", "Required", "NotRequired",
    "ReadOnly", "TypeGuard", "TypeIs", "Awaitable", "type", "Type",
})
_SEQ_CONTAINERS = frozenset({
    "list", "List", "set", "Set", "frozenset", "FrozenSet", "tuple", "Tuple",
    "deque", "Deque", "Sequence", "MutableSequence", "Iterable", "Iterator",
    "AsyncIterable", "AsyncIterator", "Generator", "AsyncGenerator", "Coroutine",
    "Collection", "AbstractSet", "KeysView", "ValuesView", "ItemsView",
    "Container", "Reversible",
})
_MAP_CONTAINERS = frozenset({
    "dict", "Dict", "Mapping", "MutableMapping", "DefaultDict", "defaultdict",
    "OrderedDict", "Counter", "ChainMap",
})
_CALLABLE_NAMES = frozenset({"Callable"})
_NONE_NAMES = frozenset({"None", "NoneType"})
_ANY_NAMES = frozenset({"Any"})
_STRUCTURAL_NAMES = (_UNION_NAMES | _TRANSPARENT | _SEQ_CONTAINERS
                     | _MAP_CONTAINERS | _CALLABLE_NAMES)

# Depth guards. Real annotations nest two or three deep and real statements a
# handful; these bound a malformed or adversarial input, they are not an
# expected limit (same posture as ``_declarator_name``'s ``range(16)``).
_ANN_DEPTH = 16
_STMT_DEPTH = 64


@lru_cache(maxsize=8192)
def _parse_expr(text: str):
    """Parse ONE expression, or None. Never raises, never imports anything."""
    try:
        return ast.parse(text.strip(), mode="eval").body
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None


def _dotted_tail(node) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _nominal_text(node) -> str:
    """The name an edge would point at, kept exactly as written."""
    if isinstance(node, ast.Name):
        return node.id
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _slice_elements(sl) -> list:
    if isinstance(sl, ast.Tuple):
        return list(sl.elts)
    index = getattr(ast, "Index", None)          # gone in 3.9+, tolerated here
    if index is not None and isinstance(sl, index):
        return [sl.value]
    return [sl]


def _destring(node, depth: int = 0):
    """Replace forward-reference string constants by the expression they spell.

    ``x: "Later"`` and ``x: Later`` mean the same thing and must produce the
    same text, or a consumer sees two type names where the author wrote one.
    Two places are deliberately left alone: ``Literal["a"]``, whose strings are
    VALUES and would become a type called ``a``, and every ``Annotated[...]``
    argument after the first, which is metadata and not a type at all.
    """
    if depth > _ANN_DEPTH:
        return node
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        inner = _parse_expr(node.value)
        return _destring(inner, depth + 1) if inner is not None else node
    if isinstance(node, ast.Subscript):
        node.value = _destring(node.value, depth + 1)
        tail = _dotted_tail(node.value)
        if tail == "Literal":
            return node
        if tail == "Annotated":
            sl = node.slice
            if isinstance(sl, ast.Tuple) and sl.elts:
                sl.elts[0] = _destring(sl.elts[0], depth + 1)
            else:
                node.slice = _destring(sl, depth + 1)
            return node
        node.slice = _destring(node.slice, depth + 1)
        return node
    if isinstance(node, (ast.Tuple, ast.List)):
        node.elts = [_destring(e, depth + 1) for e in node.elts]
        return node
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        node.left = _destring(node.left, depth + 1)
        node.right = _destring(node.right, depth + 1)
        return node
    return node


def annotation_text(node) -> str:
    """RAW annotation text for one ast annotation slot ("" when absent).

    ``ast.unparse`` rather than a source slice, so the whitespace of
    ``dict[str,Item]`` and ``dict[str, Item]`` canonicalizes to one string and
    two files that mean the same thing are counted once. The node is COPIED
    before de-stringifying, because the caller's tree is shared with the unit
    and import walks and must not be mutated under them.
    """
    if node is None:
        return ""
    try:
        return ast.unparse(_destring(copy.deepcopy(node)))
    except Exception:
        return ""


# --------------------------------------------------------------------------- #
# Pure normalization helpers (no repo knowledge, no I/O, no imports executed)  #
# --------------------------------------------------------------------------- #
class _AnnAcc:
    __slots__ = ("members", "seen", "containers", "dropped", "dropped_seen",
                 "saw_none", "saw_any", "saw_union", "unparsed")

    def __init__(self) -> None:
        self.members: list[str] = []
        self.seen: set[str] = set()
        self.containers: list[str] = []
        self.dropped: list[str] = []
        self.dropped_seen: set[str] = set()
        self.saw_none = False
        self.saw_any = False
        self.saw_union = False
        self.unparsed = False

    def member(self, name: str) -> None:
        if name and name not in self.seen:
            self.seen.add(name)
            self.members.append(name)

    def drop(self, name: str) -> None:
        if name and name not in self.dropped_seen:
            self.dropped_seen.add(name)
            self.dropped.append(name)


def _gather_dropped(node, acc: _AnnAcc, depth: int = 0) -> None:
    """Nominal names in a position the element rule discards (mapping keys,
    Callable parameters). Structural vocabulary is filtered out, so
    ``dict[str, X]`` drops ``str`` and not also ``dict``."""
    if depth > _ANN_DEPTH:
        return
    if isinstance(node, (ast.Name, ast.Attribute)):
        tail = _dotted_tail(node)
        if tail and tail not in _NONE_NAMES and tail not in _ANY_NAMES \
                and tail not in _STRUCTURAL_NAMES:
            acc.drop(_nominal_text(node))
        return
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            inner = _parse_expr(node.value)
            if inner is not None:
                _gather_dropped(inner, acc, depth + 1)
        return
    for child in ast.iter_child_nodes(node):
        _gather_dropped(child, acc, depth + 1)


def _collect(node, acc: _AnnAcc, depth: int = 0) -> None:
    if depth > _ANN_DEPTH:
        return
    if isinstance(node, ast.Constant):
        if node.value is None:
            acc.saw_none = True
        elif isinstance(node.value, str):
            inner = _parse_expr(node.value)
            if inner is None:
                acc.unparsed = True
            else:
                _collect(inner, acc, depth + 1)
        return                    # Ellipsis and numeric literals mention no type
    if isinstance(node, (ast.Name, ast.Attribute)):
        tail = _dotted_tail(node)
        if tail in _NONE_NAMES:
            acc.saw_none = True
        elif tail in _ANY_NAMES:
            acc.saw_any = True
        else:
            acc.member(_nominal_text(node))
        return
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        acc.saw_union = True      # PEP 604: X | Y is Union[X, Y]
        _collect(node.left, acc, depth + 1)
        _collect(node.right, acc, depth + 1)
        return
    if isinstance(node, ast.Subscript):
        tail = _dotted_tail(node.value)
        elts = _slice_elements(node.slice)
        if tail in _UNION_NAMES:
            if tail == "Optional":
                acc.saw_none = True
            if tail == "Union":
                acc.saw_union = True
            for elt in elts:
                _collect(elt, acc, depth + 1)
            return
        if tail in _TRANSPARENT:
            if elts:
                _collect(elts[0], acc, depth + 1)
            return                # Annotated metadata is not a type
        if tail in _CALLABLE_NAMES:
            acc.containers.append(tail)
            if elts:
                for elt in elts[:-1]:
                    _gather_dropped(elt, acc)
                _collect(elts[-1], acc, depth + 1)
            return
        if tail in _MAP_CONTAINERS and len(elts) >= 2:
            acc.containers.append(tail)
            for elt in elts[:-1]:
                _gather_dropped(elt, acc)
            _collect(elts[-1], acc, depth + 1)
            return
        if tail in _SEQ_CONTAINERS or tail in _MAP_CONTAINERS:
            acc.containers.append(tail)
            for elt in elts:
                _collect(elt, acc, depth + 1)
            return
        # An unknown generic: the BASE is the nominal and we do NOT descend.
        # ``MyGeneric[int]`` is evidence about ``MyGeneric``; minting a node per
        # instantiation is the TYGAR mistake (an unbounded vocabulary).
        _collect(node.value, acc, depth + 1)
        return
    # Anything else (a Call, a lambda, a comparison) mentions no nominal type.


@lru_cache(maxsize=8192)
def normalize_annotation(raw: str) -> Annotation:
    """Read ONE raw annotation string. Pure; see ``Annotation`` for the rules."""
    text = (raw or "").strip()
    if not text:
        return Annotation(raw="", missing=True)
    node = _parse_expr(text)
    if node is None:
        return Annotation(raw=text, unparsed=True)
    acc = _AnnAcc()
    _collect(node, acc)
    members = tuple(acc.members)
    containers = tuple(acc.containers)
    is_none = acc.saw_none and not members and not containers and not acc.saw_any
    is_any = acc.saw_any and not members and not containers and not acc.saw_none
    return Annotation(
        raw=text,
        members=members,
        container=containers[0] if containers else "",
        containers=containers,
        dropped=tuple(acc.dropped),
        optional=acc.saw_none and not is_none,
        union=acc.saw_union and len(members) > 1,
        is_any=is_any,
        has_any=acc.saw_any,
        is_none=is_none,
        unparsed=acc.unparsed,
    )


@lru_cache(maxsize=4096)
def flatten_union(raw: str) -> tuple[str, ...]:
    """Union members as raw text, in SOURCE ORDER, with ``None`` removed.

    ``Optional[Alpha]`` -> ``("Alpha",)``; ``Alpha | None`` -> ``("Alpha",)``;
    ``Union[Alpha, Beta]`` -> ``("Alpha", "Beta")``. A non-union annotation is
    its own single member, so the caller needs no special case. Nesting does not
    multiply members: ``Optional[Union[A, B]]`` is still two.
    """
    node = _parse_expr(raw)
    if node is None:
        return ()
    out: list[str] = []
    seen: set[str] = set()

    def walk(node, depth: int = 0) -> None:
        if depth > _ANN_DEPTH:
            return
        if isinstance(node, ast.Constant):
            if node.value is None:
                return
            if isinstance(node.value, str):
                inner = _parse_expr(node.value)
                if inner is not None:
                    walk(inner, depth + 1)
                return
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            walk(node.left, depth + 1)
            walk(node.right, depth + 1)
            return
        if isinstance(node, ast.Subscript) and _dotted_tail(node.value) in _UNION_NAMES:
            for elt in _slice_elements(node.slice):
                walk(elt, depth + 1)
            return
        if isinstance(node, (ast.Name, ast.Attribute)) and _dotted_tail(node) in _NONE_NAMES:
            return
        text = annotation_text(node)
        if text and text not in seen:
            seen.add(text)
            out.append(text)

    walk(node)
    return tuple(out)


@lru_cache(maxsize=4096)
def split_generic(raw: str) -> tuple[str, tuple[str, ...]]:
    """One level of generic: ``(container spelling, element texts)``.

    ``list[User]`` -> ``("list", ("User",))``; ``dict[str, User]`` ->
    ``("dict", ("User",))`` because a mapping's KEY is not its element;
    ``Callable[[int], User]`` -> ``("Callable", ("User",))``. A bare nominal is
    ``("", (raw,))``, and an unknown generic is ``("", ("MyGeneric[int]",))`` --
    no container, because we refuse to guess that an unrecognised subscript is
    a container at all.
    """
    node = _parse_expr(raw)
    if node is None:
        return "", ()
    if not isinstance(node, ast.Subscript):
        text = annotation_text(node)
        return "", ((text,) if text else ())
    tail = _dotted_tail(node.value)
    elts = _slice_elements(node.slice)
    if tail in _CALLABLE_NAMES:
        return tail, ((annotation_text(elts[-1]),) if elts else ())
    if tail in _MAP_CONTAINERS and len(elts) >= 2:
        return tail, (annotation_text(elts[-1]),)
    if tail in _SEQ_CONTAINERS or tail in _MAP_CONTAINERS:
        kept = tuple(annotation_text(e) for e in elts
                     if not (isinstance(e, ast.Constant) and e.value is Ellipsis))
        return tail, tuple(k for k in kept if k)
    text = annotation_text(node)
    return "", ((text,) if text else ())


def is_any_annotation(raw: str) -> bool:
    """True for a bare ``Any``/``typing.Any`` -- the sentinel a caller must
    refuse to edge to. ``dict[str, Any]`` is NOT bare Any; it is a dict whose
    element type is unknown, which is a different fact and a different number."""
    return normalize_annotation(raw).is_any


def union_id(module: str, owner: str, role: str, param: str) -> str:
    """Stable group id shared by every member edge of ONE union SITE.

    Derived entirely from the site's identity, never from a counter over a set
    or dict: a counter would renumber whenever iteration order shifted, and two
    processes would then disagree byte-for-byte on an id that is supposed to
    mean "these edges are alternatives to each other".
    """
    return f"{module}#{owner}:{role}:{param}"


# --------------------------------------------------------------------------- #
# The walk                                                                     #
# --------------------------------------------------------------------------- #
_ENUM_BASES = frozenset({"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag",
                         "ReprEnum", "EnumMeta", "EnumType"})


def _decl_kind(bases: tuple[str, ...], decorators: tuple[str, ...]) -> str:
    """Classify a ClassDef. Base-derived kinds win over decorator-derived ones,
    because a base changes what the declaration IS (a TypedDict is a dict shape,
    an Enum's members are values) while ``@dataclass`` only changes what is
    generated for it. Fixed order, so the answer never depends on dict order."""
    tails = {b.rsplit(".", 1)[-1].split("[", 1)[0].strip() for b in bases}
    if "TypedDict" in tails:
        return "typeddict"
    if "NamedTuple" in tails:
        return "namedtuple"
    if tails & _ENUM_BASES:
        return "enum"
    if "Protocol" in tails:
        return "protocol"
    for deco in decorators:
        if deco.split("(", 1)[0].rsplit(".", 1)[-1] == "dataclass":
            return "dataclass"
    return "class"


def _decorator_texts(node) -> tuple[str, ...]:
    out = []
    for deco in getattr(node, "decorator_list", ()):
        try:
            out.append(ast.unparse(deco))
        except Exception:
            continue
    return tuple(out)


def _base_texts(node) -> tuple[str, ...]:
    out = []
    for base in getattr(node, "bases", ()):
        try:
            out.append(ast.unparse(base))
        except Exception:
            continue
    for kw in getattr(node, "keywords", ()):
        # ``class C(Base, metaclass=M)`` -- kept as written so a consumer can see
        # the metaclass without re-parsing the source.
        try:
            out.append(f"{kw.arg}={ast.unparse(kw.value)}" if kw.arg
                       else ast.unparse(kw.value))
        except Exception:
            continue
    return tuple(out)


def _params_of(node) -> tuple[tuple[ParamDecl, ...], str]:
    """Parameters in reading order, plus the receiver candidate name."""
    args = node.args
    out: list[ParamDecl] = []
    pos = 0
    posonly = list(getattr(args, "posonlyargs", ()) or ())
    positional = posonly + list(args.args)
    first_default = len(positional) - len(args.defaults)
    for i, arg in enumerate(positional):
        out.append(ParamDecl(
            name=arg.arg, position=pos,
            annotation=annotation_text(arg.annotation),
            kind="posonly" if i < len(posonly) else "arg",
            has_default=i >= first_default,
        ))
        pos += 1
    if args.vararg is not None:
        out.append(ParamDecl(name=args.vararg.arg, position=pos,
                             annotation=annotation_text(args.vararg.annotation),
                             kind="vararg"))
        pos += 1
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        out.append(ParamDecl(name=arg.arg, position=pos,
                             annotation=annotation_text(arg.annotation),
                             kind="kwonly", has_default=default is not None))
        pos += 1
    if args.kwarg is not None:
        out.append(ParamDecl(name=args.kwarg.arg, position=pos,
                             annotation=annotation_text(args.kwarg.annotation),
                             kind="kwarg"))
        pos += 1
    return tuple(out), (positional[0].arg if positional else "")


def _alias_records(node) -> list[AliasImport]:
    out: list[AliasImport] = []
    if isinstance(node, ast.Import):
        for a in node.names:
            # ``import a.b`` binds the TOP name ``a``; ``import a.b as c`` binds ``c``.
            local = a.asname or a.name.split(".", 1)[0]
            out.append(AliasImport(local=local, kind="import", level=0,
                                   module="", orig=a.name, line=node.lineno))
    elif isinstance(node, ast.ImportFrom):
        for a in node.names:
            out.append(AliasImport(local=a.asname or a.name, kind="from",
                                   level=node.level or 0, module=node.module or "",
                                   orig=a.name, line=node.lineno))
    return out


def _end_line(node) -> int:
    return int(getattr(node, "end_lineno", node.lineno) or node.lineno)


def _qual(parts: tuple[str, ...], name: str) -> str:
    return ".".join((*parts, name))


class _TypeWalk:
    """One recursive descent over statements, carrying a scope stack.

    ``ast.walk`` cannot be used here: it is breadth-first and exposes no parent
    link, so ``Outer.Inner`` and ``Cls.method`` are not reconstructible from it.
    Expressions are never descended into -- no declaration can hide inside one --
    which keeps the recursion as shallow as the source's statement nesting.
    """

    def __init__(self, module: str) -> None:
        self.module = module
        self.types: list[TypeDecl] = []
        self.fields: list[FieldDecl] = []
        self.signatures: list[SignatureDecl] = []
        self.aliases: list[AliasImport] = []
        self.future_annotations = False
        self.truncated = False

    # -- declarations ------------------------------------------------------ #
    def _class(self, node, parts, depth) -> None:
        qualname = _qual(parts, node.name)
        bases = _base_texts(node)
        decorators = _decorator_texts(node)
        kind = _decl_kind(bases, decorators)
        self.types.append(TypeDecl(
            module=self.module, qualname=qualname, name=node.name, kind=kind,
            line=node.lineno, end_line=_end_line(node),
            bases=bases, decorators=decorators,
        ))
        self._visit(node, (*parts, node.name), depth + 1,
                    owner=qualname, owner_kind=kind, receiver="",
                    in_class_body=True)

    def _function(self, node, parts, depth, owner, owner_kind) -> None:
        qualname = _qual(parts, node.name)
        params, receiver = _params_of(node)
        decorators = _decorator_texts(node)
        is_static = any(d.rsplit(".", 1)[-1] == "staticmethod" for d in decorators)
        # A receiver exists only for a method that actually takes one. Reading
        # the first parameter's real name (rather than assuming "self") keeps a
        # renamed receiver out of the coverage denominator and keeps a
        # staticmethod's first argument IN it.
        bound = receiver if (owner and not is_static and receiver) else ""
        self.signatures.append(SignatureDecl(
            module=self.module, qualname=qualname, name=node.name,
            line=node.lineno, end_line=_end_line(node), owner=owner,
            params=params, returns=annotation_text(node.returns),
            receiver=bound, is_async=isinstance(node, ast.AsyncFunctionDef),
            decorators=decorators,
        ))
        # Inside a function body: nested defs/classes are in a ``<locals>``
        # scope, and ``self.x = ...`` assignments belong to the enclosing TYPE.
        self._visit(node, (*parts, node.name, "<locals>"), depth + 1,
                    owner=owner, owner_kind=owner_kind, receiver=bound,
                    in_class_body=False)

    # -- members ----------------------------------------------------------- #
    def _self_target(self, target, receiver: str) -> str:
        if not receiver or not isinstance(target, ast.Attribute):
            return ""
        base = target.value
        if isinstance(base, ast.Name) and base.id == receiver:
            return target.attr
        return ""

    def _annassign(self, node, owner, owner_kind, receiver, in_class_body) -> None:
        annotation = annotation_text(node.annotation)
        tail = annotation.rsplit(".", 1)[-1].split("[", 1)[0].strip()
        target = node.target
        if tail == "TypeAlias" and isinstance(target, ast.Name):
            # ``Vec: TypeAlias = list[int]`` declares a type, not a member.
            self.types.append(TypeDecl(
                module=self.module, qualname=target.id, name=target.id,
                kind="alias", line=node.lineno, end_line=_end_line(node),
                alias_target=annotation_text(node.value),
            ))
            return
        if in_class_body and owner and isinstance(target, ast.Name):
            self.fields.append(FieldDecl(
                module=self.module, owner=owner, name=target.id, line=node.lineno,
                annotation="" if owner_kind == "enum" else annotation,
                origin="enum_member" if owner_kind == "enum" else "annassign",
                has_default=node.value is not None,
            ))
            return
        name = self._self_target(target, receiver)
        if name and owner:
            self.fields.append(FieldDecl(
                module=self.module, owner=owner, name=name, line=node.lineno,
                annotation=annotation, origin="self",
                has_default=node.value is not None,
            ))

    def _assign(self, node, owner, owner_kind, receiver, in_class_body) -> None:
        # ``X = NewType("X", int)`` is the one unannotated assignment that
        # unambiguously declares a type. A bare ``X = int`` is NOT treated as an
        # alias: at module level that shape is far more often a constant, and
        # minting a type node for it would fabricate declarations.
        if isinstance(node.value, ast.Call) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and _dotted_tail(node.value.func) == "NewType":
            target = node.targets[0]
            arg = node.value.args[1] if len(node.value.args) > 1 else None
            self.types.append(TypeDecl(
                module=self.module, qualname=target.id, name=target.id,
                kind="alias", line=node.lineno, end_line=_end_line(node),
                alias_target=annotation_text(arg),
            ))
            return
        flat: list = []
        for target in node.targets:
            if isinstance(target, (ast.Tuple, ast.List)):
                flat.extend(target.elts)
            else:
                flat.append(target)
        for target in flat:
            if in_class_body and owner and isinstance(target, ast.Name):
                self.fields.append(FieldDecl(
                    module=self.module, owner=owner, name=target.id,
                    line=node.lineno, annotation="",
                    origin="enum_member" if owner_kind == "enum" else "assign",
                    has_default=True,
                ))
                continue
            name = self._self_target(target, receiver)
            if name and owner:
                self.fields.append(FieldDecl(
                    module=self.module, owner=owner, name=name, line=node.lineno,
                    annotation="", origin="self", has_default=True,
                ))

    # -- descent ----------------------------------------------------------- #
    def _visit(self, node, parts, depth, owner, owner_kind, receiver,
               in_class_body: bool) -> None:
        if depth > _STMT_DEPTH:
            self.truncated = True
            return
        alias_node = getattr(ast, "TypeAlias", None)   # PEP 695, Python 3.12+
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                self._class(child, parts, depth)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._function(child, parts, depth,
                               owner if in_class_body else "",
                               owner_kind if in_class_body else "")
            elif isinstance(child, (ast.Import, ast.ImportFrom)):
                if isinstance(child, ast.ImportFrom) \
                        and child.module == "__future__" \
                        and any(a.name == "annotations" for a in child.names):
                    self.future_annotations = True
                self.aliases.extend(_alias_records(child))
            elif isinstance(child, ast.AnnAssign):
                self._annassign(child, owner, owner_kind, receiver, in_class_body)
            elif isinstance(child, ast.Assign):
                self._assign(child, owner, owner_kind, receiver, in_class_body)
            elif alias_node is not None and isinstance(child, alias_node):
                self._pep695_alias(child)
            elif isinstance(child, ast.expr):
                continue        # no declaration can hide inside an expression
            else:
                # Any other statement container -- if/try/with/for/while, an
                # except handler, a match case. A class body's ``if`` still holds
                # class members, so in_class_body is carried through unchanged.
                self._visit(child, parts, depth + 1, owner, owner_kind, receiver,
                            in_class_body)

    def _pep695_alias(self, node) -> None:
        target = getattr(node, "name", None)
        name = target.id if isinstance(target, ast.Name) else ""
        if not name:
            return
        self.types.append(TypeDecl(
            module=self.module, qualname=name, name=name, kind="alias",
            line=node.lineno, end_line=_end_line(node),
            alias_target=annotation_text(node.value),
        ))

    def facts(self) -> PyTypeFacts:
        # Sorted, not merely "whatever the descent produced". The descent IS
        # deterministic, but two processes must agree byte-for-byte and a sort
        # makes that true by construction rather than by argument.
        return PyTypeFacts(
            module=self.module,
            types=tuple(sorted(self.types,
                               key=lambda t: (t.line, t.qualname, t.kind))),
            fields=tuple(sorted(self.fields,
                                key=lambda f: (f.line, f.owner, f.name, f.origin))),
            signatures=tuple(sorted(self.signatures,
                                    key=lambda s: (s.line, s.qualname))),
            aliases=tuple(sorted(self.aliases,
                                 key=lambda a: (a.line, a.local, a.kind,
                                                a.module, a.orig, a.level))),
            future_annotations=self.future_annotations,
            truncated=self.truncated,
        )


def _type_facts_from_tree(tree, module: str) -> PyTypeFacts:
    """Type/field/signature facts from an ALREADY PARSED tree.

    Sibling of ``_import_records`` and bound by the same contract: raw and
    unresolved, dependent on nothing but this one file, so it can run in a
    worker process while resolution stays in the parent.
    """
    walk = _TypeWalk(module)
    walk._visit(tree, (), 0, owner="", owner_kind="", receiver="",
                in_class_body=False)
    return walk.facts()


def python_units_imports_and_types(
    module: str, text: str
) -> tuple[list[CodeUnit], list[tuple], PyTypeFacts]:
    """Units, raw import records AND type facts from a SINGLE ``ast.parse``.

    The three-value continuation of ``python_units_and_imports``. Unit order and
    unit CONTENT are identical to that function's -- the same
    ``_units_from_tree`` call on the same tree -- because the clone passes
    consume ``all_units`` positionally and no type record may reach them.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return [], [], PyTypeFacts(module=module)
    return (_units_from_tree(tree, module, text.splitlines()),
            _import_records(tree),
            _type_facts_from_tree(tree, module))


def python_type_facts(module: str, text: str) -> PyTypeFacts:
    """Type facts for one Python source (standalone parse).

    The convenience form, mirroring ``python_import_records``. ``build_index``
    uses ``python_units_imports_and_types`` so the hot path parses once.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return PyTypeFacts(module=module)
    return _type_facts_from_tree(tree, module)
