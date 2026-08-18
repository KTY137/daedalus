"""EXPERIMENT (forest_v2 / slice s01): a read-only project index for the code plane.

Frozen frame, inherited from the forest_v2 pre-study: pure stdlib AST, no
imports of production repository code, no writes, no network, no subprocess.
This module is a *representation*, never an authority (master plan section 5):
it references source files by path and line and claims nothing that is not
backed by a definition it can point at.

What it holds per module:

* ``defs``        -- module-level function/class/assignment names -> (kind, line)
* ``imports``     -- module-level binding name -> dotted target
* ``classes``     -- class name -> bases (raw dotted), methods, attribute types
* ``star_imports``-- modules pulled in by ``from x import *`` (honest unknown)

What it resolves:

* ``lookup_symbol``      -- a name in a module, following re-export chains
* ``resolve_dotted``     -- a dotted path against the longest known module prefix
* ``class_of``           -- a raw base/annotation string -> a repo ``ClassInfo``
* ``lookup_attribute``   -- an attribute over the class hierarchy (BFS, cycle safe)

Every resolution returns a ``Target`` carrying ``status``:
``repo`` (a definition inside the analysed tree, with file and line),
``external`` (a named module we cannot see -- a claim, not a proof), or
``unknown`` (we decline to guess).
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PACKAGES = ("daedalus", "tools", "runs")

# Bases that exist but contribute no attribute a caller would resolve through
# them in this corpus; counting them as "an external base might define it"
# would inflate the external bucket for free.
INERT_BASES = frozenset({"object"})


@dataclass(frozen=True)
class Target:
    """A resolution result.  ``status`` is the honesty channel."""

    status: str  # 'repo' | 'external' | 'unknown'
    module: str = ""
    symbol: str = ""
    kind: str = ""  # 'function' | 'class' | 'assign' | 'module' | ''
    rel: str = ""
    lineno: int = 0

    @property
    def dotted(self) -> str:
        if self.symbol:
            return f"{self.module}.{self.symbol}" if self.module else self.symbol
        return self.module


UNKNOWN = Target("unknown")


@dataclass
class ClassInfo:
    module: str
    name: str
    lineno: int
    bases: list[str] = field(default_factory=list)
    methods: dict[str, int] = field(default_factory=dict)
    # attribute name -> raw dotted class expression it was constructed from
    attributes: dict[str, str] = field(default_factory=dict)

    @property
    def qualname(self) -> str:
        return f"{self.module}.{self.name}"


@dataclass
class ModuleInfo:
    name: str
    path: Path
    rel: str
    tree: ast.Module
    defs: dict[str, tuple[str, int]] = field(default_factory=dict)
    imports: dict[str, str] = field(default_factory=dict)
    star_imports: list[str] = field(default_factory=list)
    classes: dict[str, ClassInfo] = field(default_factory=dict)


def dotted_name(node: ast.AST) -> str:
    """Dotted source spelling of a Name/Attribute chain, '' for anything else.

    Deliberately identical in behaviour to the pre-study probe's ``_call_name``
    so that call-site counting stays comparable.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def module_name_for(root: Path, path: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def import_bindings(node: ast.Import | ast.ImportFrom, module: str) -> dict[str, str]:
    """Bindings introduced by one import statement.  Relative imports resolved
    against ``module``'s package path."""
    package_parts = module.split(".")[:-1]
    out: dict[str, str] = {}
    if isinstance(node, ast.Import):
        for alias in node.names:
            local = alias.asname or alias.name.split(".")[0]
            target = alias.name if alias.asname else alias.name.split(".")[0]
            out[local] = target
        return out
    if node.module is None and node.level == 0:
        return out
    if node.level:
        base_parts = package_parts[: len(package_parts) - (node.level - 1)]
        base = ".".join(base_parts + ([node.module] if node.module else []))
    else:
        base = node.module or ""
    if not base:
        return out
    for alias in node.names:
        if alias.name == "*":
            continue
        out[alias.asname or alias.name] = f"{base}.{alias.name}"
    return out


def _class_info(module: str, node: ast.ClassDef) -> ClassInfo:
    info = ClassInfo(module=module, name=node.name, lineno=node.lineno)
    for base in node.bases:
        raw = dotted_name(base)
        if raw:
            info.bases.append(raw)
    for child in node.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            info.methods[child.name] = child.lineno
            if child.name in {"__init__", "__post_init__", "setUp"}:
                _collect_self_attributes(child, info)
        elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
            raw = dotted_name(child.annotation)
            if raw:
                info.attributes.setdefault(child.target.id, raw)
        elif isinstance(child, ast.Assign):
            raw = _constructed_class(child.value)
            if raw:
                for target in child.targets:
                    if isinstance(target, ast.Name):
                        info.attributes.setdefault(target.id, raw)
    return info


def _constructed_class(value: ast.AST | None) -> str:
    """``ClassName(...)`` -> 'ClassName'; anything else -> ''."""
    if isinstance(value, ast.Call):
        return dotted_name(value.func)
    return ""


def _collect_self_attributes(func: ast.AST, info: ClassInfo) -> None:
    """``self.x = ClassName(...)`` / ``self.x: Ann = ...`` inside a constructor."""
    for node in ast.walk(func):
        if isinstance(node, ast.Assign):
            raw = _constructed_class(node.value)
            if not raw:
                continue
            for target in node.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                ):
                    info.attributes.setdefault(target.attr, raw)
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
            ):
                raw = dotted_name(node.annotation)
                if raw:
                    info.attributes.setdefault(target.attr, raw)


class ProjectIndex:
    """Modules, symbols and classes of one source tree.  Read-only."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.modules: dict[str, ModuleInfo] = {}
        self.by_rel: dict[str, ModuleInfo] = {}
        self.unparseable: list[str] = []
        self._attr_cache: dict[tuple[str, str, str], object] = {}

    # ---- construction -------------------------------------------------
    @staticmethod
    def module_level_statements(body: list[ast.stmt]):
        """Statements that bind at module level, including the conditional ones.

        ``try: import x / except ImportError: def x()`` and ``if TYPE_CHECKING:``
        blocks bind names in module scope.  Reading only ``tree.body`` misses
        them, which showed up as unresolvable cross-module imports.
        """
        stack = list(reversed(body))
        while stack:
            node = stack.pop()
            yield node
            if isinstance(node, (ast.If, ast.Try, ast.With, ast.AsyncWith)):
                nested: list[ast.stmt] = list(node.body)
                nested += list(getattr(node, "orelse", []) or [])
                nested += list(getattr(node, "finalbody", []) or [])
                for handler in getattr(node, "handlers", []) or []:
                    nested += list(handler.body)
                stack.extend(reversed(nested))

    def add_source(self, module: str, path: Path, rel: str, source: str) -> bool:
        try:
            tree = ast.parse(source, filename=str(path))
        except (SyntaxError, ValueError):
            self.unparseable.append(rel)
            return False
        info = ModuleInfo(name=module, path=path, rel=rel, tree=tree)
        for node in self.module_level_statements(tree.body):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                info.defs[node.name] = ("function", node.lineno)
            elif isinstance(node, ast.ClassDef):
                info.defs[node.name] = ("class", node.lineno)
                info.classes[node.name] = _class_info(module, node)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        info.defs.setdefault(target.id, ("assign", node.lineno))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                info.defs.setdefault(node.target.id, ("assign", node.lineno))
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                info.imports.update(import_bindings(node, module))
                if isinstance(node, ast.ImportFrom) and any(
                    a.name == "*" for a in node.names
                ):
                    if node.module:
                        info.star_imports.append(node.module)
        self.modules[module] = info
        self.by_rel[rel] = info
        return True

    # ---- resolution ---------------------------------------------------
    def lookup_symbol(self, module: str, symbol: str, _depth: int = 0) -> Target:
        """A name inside a module, following re-export chains up to a depth cap."""
        info = self.modules.get(module)
        if info is None:
            return Target("external", module, symbol)
        if symbol in info.defs:
            kind, lineno = info.defs[symbol]
            return Target("repo", module, symbol, kind, info.rel, lineno)
        if symbol in info.imports and _depth < 8:
            return self.resolve_dotted(info.imports[symbol], _depth + 1)
        if info.star_imports:
            return UNKNOWN
        return UNKNOWN

    def resolve_dotted(self, dotted: str, _depth: int = 0) -> Target:
        """Resolve a fully dotted path against the longest known module prefix."""
        if not dotted:
            return UNKNOWN
        parts = dotted.split(".")
        for cut in range(len(parts), 0, -1):
            prefix = ".".join(parts[:cut])
            if prefix not in self.modules:
                continue
            rest = parts[cut:]
            info = self.modules[prefix]
            if not rest:
                return Target("repo", prefix, "", "module", info.rel, 1)
            found = self.lookup_symbol(prefix, rest[0], _depth)
            if len(rest) == 1:
                return found
            # deeper attribute access on a resolved symbol: we know the owner
            # exists but not the attribute -- report it as an unverified claim.
            if found.status == "repo":
                return Target("external", found.dotted, ".".join(rest[1:]))
            return Target("external", ".".join(parts[:-1]), parts[-1])
        owner = ".".join(parts[:-1])
        if owner:
            return Target("external", owner, parts[-1])
        # A single segment that matches no repo module is a top-level external
        # module or name (``re``, ``json``, ``hashlib``).  Naming it is a claim,
        # not a proof -- which is exactly what ``external`` means here.
        return Target("external", parts[0], "", "module")

    def class_of(self, module: str, raw: str) -> ClassInfo | None:
        """Raw dotted class expression, as spelled in ``module``, -> repo class."""
        if not raw:
            return None
        info = self.modules.get(module)
        if info is None:
            return None
        head, _, rest = raw.partition(".")
        if not rest and head in info.classes:
            return info.classes[head]
        target = info.imports.get(head)
        if target is None:
            if not rest:
                found = self.lookup_symbol(module, head)
                if found.status == "repo" and found.kind == "class":
                    return self.modules[found.module].classes.get(found.symbol)
            return None
        dotted = f"{target}.{rest}" if rest else target
        found = self.resolve_dotted(dotted)
        if found.status == "repo" and found.kind == "class":
            owner = self.modules.get(found.module)
            if owner is not None:
                return owner.classes.get(found.symbol)
        return None

    def lookup_attribute(self, info: ClassInfo, attr: str) -> tuple[str, object]:
        """BFS over the class hierarchy for ``attr``.

        Returns ``('method', (ClassInfo, lineno))``, ``('attribute', (ClassInfo, raw))``,
        ``('external_base', base_name)`` when an unseen base could still define it,
        or ``('missing', None)``.
        """
        key = (info.module, info.name, attr)
        cached = self._attr_cache.get(key)
        if cached is not None:
            return cached  # type: ignore[return-value]
        seen: set[tuple[str, str]] = set()
        queue: list[ClassInfo] = [info]
        external_base = ""
        result: tuple[str, object] = ("missing", None)
        while queue:
            current = queue.pop(0)
            ident = (current.module, current.name)
            if ident in seen:
                continue
            seen.add(ident)
            if attr in current.methods:
                result = ("method", (current, current.methods[attr]))
                break
            if attr in current.attributes:
                result = ("attribute", (current, current.attributes[attr]))
                break
            for raw in current.bases:
                base = self.class_of(current.module, raw)
                if base is not None:
                    queue.append(base)
                elif raw.split(".")[-1] not in INERT_BASES and not external_base:
                    external_base = raw
        if result[0] == "missing" and external_base:
            result = ("external_base", external_base)
        self._attr_cache[key] = result
        return result


def build_index(root: Path, packages: tuple[str, ...] = DEFAULT_PACKAGES) -> ProjectIndex:
    index = ProjectIndex(root)
    for package in packages:
        directory = root / package
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.py")):
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                index.unparseable.append(path.as_posix())
                continue
            rel = path.relative_to(root).as_posix()
            index.add_source(module_name_for(root, path), path, rel, source)
    return index
