"""Parsing abstraction — extract code units (functions/methods) per language.

Three backends, chosen automatically:
  * Python  -> stdlib ``ast`` (always available, precise).
  * others  -> tree-sitter via ``tree_sitter_language_pack`` IF installed.
  * neither -> no unit-level extraction; the caller falls back to the universal
    windowed clone pass (see ``clones.window_clones``), which needs no parser.

The unit source returned here is what ``clones.fingerprint`` hashes, so this is
the precision lever: with tree-sitter, C/Java/Rust/… get real function-level
clone detection; without it, they still get window-level detection.
"""
from __future__ import annotations

import ast
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
