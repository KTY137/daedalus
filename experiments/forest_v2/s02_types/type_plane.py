"""EXPERIMENT slice s02: type-plane extraction over the kernel package.

Read-only, stdlib-only continuation of the forest_v2 pre-study, under the same
frozen frame as the call-resolution probes: no imports of repository code, no
writes, no network, no subprocess; one JSON object on stdout.

What it builds
--------------
A *type plane* in the sense of master plan section 5: declared and directly
inferable types (annotations, signatures, dataclass/TypedDict/NamedTuple
fields, class bases, type aliases) lifted out of the AST into typed nodes and
typed edges.

* Type nodes  ``type:<bucket>:<canonical name>`` -- plane ``type``.
* Symbol nodes ``sym:<module>.<qualname>`` (and ``...#<param>``) -- plane
  ``code``.  They are anchors, not a second code plane: this slice does not
  re-derive the code plane, it only names the endpoints its edges need.
* Cross-plane edges (code -> type): ``param_type``, ``return_type``,
  ``field_type``, ``var_type``, ``subtype_of``.
* Intra-plane edges (type -> type): ``type_arg``, ``alias_of``.

Every edge in this slice is *declaration evidence*, not a latent proposal:
it exists because a source annotation says so.  Section 6's verifier problem
therefore does not arise here -- what does arise is whether the name in the
annotation can be attributed to a real definition, which is what the buckets
below measure.

Resolution buckets (a type name lands in exactly one)
----------------------------------------------------
``builtin``          a name in ``builtins`` (``int``, ``None``, ...).
``typing``           attributed to ``typing``/``typing_extensions``.
``repo``             VERIFIED: the owning repo module's symbol table has it.
``repo_unverified``  attributed to a repo module, symbol not found there.
``stdlib``           attributed to a stdlib root (``sys.stdlib_module_names``).
``third_party``      attributed to some other importable root.
``unresolved``       no binding, no local definition, not a builtin.
``structural``       not a name at all (unparsable forward ref, odd shape).

``stdlib``/``third_party``/``repo_unverified`` are *name attributions*, not
existence proofs -- the same honesty caveat continuation 1 carries.  Only
``repo`` is verified against a symbol table the probe itself built.

Metrics, and what each one can and cannot falsify
-------------------------------------------------
``sig_resolved`` (the original headline) is: every parameter (implicit
``self``/``cls`` excluded) and the return annotated, AND every type name
referenced by that signature attributable.  It is *coupled to annotation
coverage by construction* -- a missing annotation sets both ``annotated`` and
``resolved`` to false -- so ``sig_resolved <= sig_annotated`` always holds and
the rate mostly measures how well the corpus is annotated.  It is retained for
continuity and it is NOT the metric any claim about resolvability may rest on.

The correct control for it is therefore ``annotation_only``: "is the signature
syntactically complete?", i.e. ``sig_annotated``.  The marginal contribution of
the entire import-binding + symbol-table machinery is the disagreement between
the two, ``sig_annotated - sig_resolved``, and nothing larger: the machinery
can only ever *subtract* from the annotation-only control.

The ``builtins_only`` resolver is retained as RETRACTED negative evidence, not
as a control.  It cannot read a single import statement by construction, so the
difference against it measures "does this corpus use non-builtin types", which
nobody doubted.

Two *decoupled* metrics carry the actual resolvability question, and both can
be low on a fully annotated corpus and high on a barely annotated one:

``type_name_resolution``   resolved / total type-name occurrences.
``sig_present_annotations_resolve``  among functions with at least one
                           annotation, the share whose *present* annotations
                           all attribute -- no completeness requirement.

Those two are what the slice's falsifier is allowed to fire on.
"""
from __future__ import annotations

import argparse
import ast
import builtins
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Iterator

SCHEMA = "forest-v2-type-plane/1"
DEFAULT_PACKAGES = ("daedalus",)

BUILTIN_NAMES = frozenset(dir(builtins)) | {"None", "True", "False"}
TYPING_ROOTS = frozenset({"typing", "typing_extensions"})
STDLIB_ROOTS = frozenset(getattr(sys, "stdlib_module_names", frozenset()))

# ``Literal[...]`` arguments are values, not types; ``Annotated[T, ...]`` binds
# only its first argument as a type.  Keyed by the last canonical segment.
VALUE_ARG_HEADS = frozenset({"Literal"})
FIRST_ARG_ONLY_HEADS = frozenset({"Annotated"})

# ``special`` covers fully determined non-name type forms (``...`` in
# ``Callable[..., T]`` / ``tuple[T, ...]``).  They are resolved, not unknown.
RESOLVED_BUCKETS = frozenset(
    {"builtin", "typing", "repo", "repo_unverified", "stdlib", "third_party", "special"}
)
UNRESOLVED_BUCKETS = frozenset({"unresolved", "structural"})
REPO_BUCKETS = frozenset({"repo", "repo_unverified"})
FIELD_BASE_HINTS = frozenset({"TypedDict", "NamedTuple"})


# --------------------------------------------------------------------------
# module discovery / symbol tables
# --------------------------------------------------------------------------
def iter_py_files(root: Path, packages: Iterable[str]) -> Iterator[Path]:
    for package in packages:
        base = root / package
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            yield path


def module_name_of(root: Path, path: Path) -> tuple[str, bool]:
    """Return ``(dotted module, is_package_init)``."""
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    is_package = bool(parts) and parts[-1] == "__init__"
    if is_package:
        parts = parts[:-1]
    return ".".join(parts), is_package


def _assigned_names(node: ast.AST) -> Iterator[str]:
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                yield target.id
    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        yield node.target.id


def top_level_symbols(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        else:
            names.update(_assigned_names(node))
    return names


def _relative_base(module: str, is_package: bool, level: int) -> str:
    base = module if is_package else module.rpartition(".")[0]
    for _ in range(level - 1):
        base = base.rpartition(".")[0]
    return base


def import_bindings(tree: ast.Module, module: str, is_package: bool) -> dict[str, str]:
    """Name -> dotted target, over the WHOLE tree (function-level imports too).

    Same rule as ``probe_cross_module_resolution.py`` so the two probes stay
    comparable.
    """
    bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    bindings[alias.asname] = alias.name
                else:
                    head = alias.name.split(".")[0]
                    bindings[head] = head
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = _relative_base(module, is_package, node.level)
                source = f"{base}.{node.module}" if node.module else base
            else:
                source = node.module or ""
            if not source:
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                bindings[alias.asname or alias.name] = f"{source}.{alias.name}"
    return bindings


# --------------------------------------------------------------------------
# graph accumulator
# --------------------------------------------------------------------------
class Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: dict[tuple[str, str, str], dict[str, Any]] = {}

    def type_node(self, bucket: str, name: str) -> str:
        node_id = f"type:{bucket}:{name}"
        node = self.nodes.get(node_id)
        if node is None:
            self.nodes[node_id] = {
                "id": node_id,
                "plane": "type",
                "bucket": bucket,
                "name": name,
                "occurrences": 1,
            }
        else:
            node["occurrences"] += 1
        return node_id

    def symbol_node(self, node_id: str, **fields: Any) -> str:
        node = self.nodes.get(node_id)
        if node is None:
            self.nodes[node_id] = {"id": node_id, "plane": "code", **fields}
        return node_id

    def edge(self, src: str, dst: str, kind: str, file: str, line: int) -> None:
        key = (src, dst, kind)
        edge = self.edges.get(key)
        if edge is None:
            self.edges[key] = {
                "src": src,
                "dst": dst,
                "kind": kind,
                "count": 1,
                "first_seen": {"file": file, "line": line},
            }
        else:
            edge["count"] += 1


# --------------------------------------------------------------------------
# name resolution
# --------------------------------------------------------------------------
class Resolver:
    def __init__(
        self,
        module_symbols: dict[str, set[str]],
        module_names: set[str],
        repo_roots: frozenset[str],
    ) -> None:
        self.module_symbols = module_symbols
        self.module_names = module_names
        self.repo_roots = repo_roots

    def resolve(
        self,
        dotted: str,
        module: str,
        local_names: set[str],
        bindings: dict[str, str],
    ) -> tuple[str, str]:
        """Return ``(bucket, canonical name)`` for a dotted annotation name."""
        head, _, rest = dotted.partition(".")
        if head in local_names:
            return "repo", f"{module}.{dotted}"
        target = bindings.get(head)
        if target is not None:
            full = f"{target}.{rest}" if rest else target
            owner, _, symbol = full.rpartition(".")
            if symbol and symbol in self.module_symbols.get(owner, ()):
                return "repo", full
            if full in self.module_names:
                return "repo", full
            root = full.split(".")[0]
            if root in TYPING_ROOTS:
                return "typing", full
            if root in self.repo_roots:
                return "repo_unverified", full
            if root in STDLIB_ROOTS:
                return "stdlib", full
            return "third_party", full
        if not rest and dotted in BUILTIN_NAMES:
            return "builtin", dotted
        return "unresolved", dotted


def builtins_only_bucket(dotted: str) -> str:
    """RETRACTED control: nothing but bare builtins is attributable.

    Kept as executable negative evidence.  This resolver cannot read an import
    statement -- there is no code path by which it could -- so a corpus that
    uses any non-builtin type name is guaranteed to score low against it.  Its
    difference from the full resolver is not a marginal contribution and must
    not be reported as one.  See ``annotation_only`` for the real control.
    """
    if "." not in dotted and dotted in BUILTIN_NAMES:
        return "builtin"
    return "unresolved"


# --------------------------------------------------------------------------
# annotation decomposition
# --------------------------------------------------------------------------
def dotted_of(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted_of(node.value)
        return f"{base}.{node.attr}" if base else ""
    return ""


class TypeExprWalker:
    """Turns one annotation expression into type nodes + ``type_arg`` edges."""

    def __init__(
        self,
        graph: Graph,
        resolver: Resolver,
        module: str,
        local_names: set[str],
        bindings: dict[str, str],
        rel_file: str,
        unresolved_names: dict[str, list[str]],
        totals: dict[str, int],
    ) -> None:
        self.graph = graph
        self.resolver = resolver
        self.module = module
        self.local_names = local_names
        self.bindings = bindings
        self.rel_file = rel_file
        self.unresolved_names = unresolved_names
        self.totals = totals

    def walk(self, expr: ast.expr, line: int, seen: set[str]) -> list[str]:
        """Return the head type node ids; records buckets into ``seen``."""
        if isinstance(expr, ast.Constant):
            if expr.value is None:
                return [self._emit("builtin", "None", seen, line)]
            if isinstance(expr.value, str):
                try:
                    inner = ast.parse(expr.value, mode="eval").body
                except SyntaxError:
                    return [self._emit("structural", "<bad-forward-ref>", seen, line)]
                return self.walk(inner, line, seen)
            if expr.value is Ellipsis:
                return [self._emit("special", "...", seen, line)]
            return [self._emit("structural", type(expr.value).__name__, seen, line)]

        if isinstance(expr, (ast.Name, ast.Attribute)):
            dotted = dotted_of(expr)
            if not dotted:
                return [self._emit("structural", "<attr-chain>", seen, line)]
            bucket, canonical = self.resolver.resolve(
                dotted, self.module, self.local_names, self.bindings
            )
            return [self._emit(bucket, canonical, seen, line)]

        if isinstance(expr, ast.Subscript):
            heads = self.walk(expr.value, line, seen)
            head_leaf = heads[0].rsplit(":", 1)[-1].rsplit(".", 1)[-1] if heads else ""
            args = self._slice_elements(expr.slice)
            if head_leaf in VALUE_ARG_HEADS:
                return heads
            if head_leaf in FIRST_ARG_ONLY_HEADS:
                args = args[:1]
            for arg in args:
                for dst in self.walk(arg, line, seen):
                    for src in heads:
                        self.graph.edge(src, dst, "type_arg", self.rel_file, line)
            return heads

        if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.BitOr):
            union = self._emit("typing", "typing.Union", seen, line)
            for side in (expr.left, expr.right):
                for dst in self.walk(side, line, seen):
                    self.graph.edge(union, dst, "type_arg", self.rel_file, line)
            return [union]

        if isinstance(expr, (ast.Tuple, ast.List)):
            out: list[str] = []
            for element in expr.elts:
                out.extend(self.walk(element, line, seen))
            return out

        return [self._emit("structural", type(expr).__name__, seen, line)]

    def _slice_elements(self, node: ast.expr) -> list[ast.expr]:
        if isinstance(node, ast.Tuple):
            return list(node.elts)
        return [node]

    def _emit(self, bucket: str, name: str, seen: set[str], line: int) -> str:
        seen.add(bucket)
        # Occurrence-level accounting.  Unlike the signature metrics this is
        # independent of annotation COVERAGE: a corpus that annotates one
        # parameter in a thousand still gets a resolution rate over that one.
        self.totals["type_name_sites"] = self.totals.get("type_name_sites", 0) + 1
        key = f"sites_{bucket}"
        self.totals[key] = self.totals.get(key, 0) + 1
        if bucket in RESOLVED_BUCKETS:
            self.totals["type_name_sites_resolved"] = (
                self.totals.get("type_name_sites_resolved", 0) + 1
            )
        if bucket in UNRESOLVED_BUCKETS:
            # An unattributed annotation name is only evidence if a reader can
            # go look at it, so keep source locators, not a bare count.
            sites = self.unresolved_names.setdefault(name, [])
            site = f"{self.rel_file}:{line}"
            if site not in sites:
                sites.append(site)
        return self.graph.type_node(bucket, name)


# --------------------------------------------------------------------------
# per-file extraction
# --------------------------------------------------------------------------
def _is_dataclass_decorated(node: ast.ClassDef) -> bool:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if dotted_of(target).rsplit(".", 1)[-1] == "dataclass":
            return True
    return False


def _has_field_base(node: ast.ClassDef) -> bool:
    for base in node.bases:
        if dotted_of(base).rsplit(".", 1)[-1] in FIELD_BASE_HINTS:
            return True
    return False


def _signature_params(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, is_method: bool
) -> tuple[list[ast.arg], int]:
    """Return ``(params, implicit receivers skipped)``."""
    positional = list(fn.args.posonlyargs) + list(fn.args.args)
    skipped = 0
    if is_method and positional and positional[0].arg in {"self", "cls"}:
        positional = positional[1:]
        skipped = 1
    params = positional + list(fn.args.kwonlyargs)
    if fn.args.vararg is not None:
        params.append(fn.args.vararg)
    if fn.args.kwarg is not None:
        params.append(fn.args.kwarg)
    return params, skipped


class FileExtractor:
    def __init__(
        self,
        graph: Graph,
        resolver: Resolver,
        module: str,
        rel_file: str,
        local_names: set[str],
        bindings: dict[str, str],
        totals: dict[str, int],
        unresolved_names: dict[str, list[str]],
    ) -> None:
        self.graph = graph
        self.module = module
        self.rel_file = rel_file
        self.local_names = local_names
        self.bindings = bindings
        self.resolver = resolver
        self.totals = totals
        self.unresolved_names = unresolved_names
        self.walker = TypeExprWalker(
            graph,
            resolver,
            module,
            local_names,
            bindings,
            rel_file,
            unresolved_names,
            totals,
        )

    # -- helpers ----------------------------------------------------------
    def _sym(self, qualname: str, line: int) -> str:
        node_id = f"sym:{self.module}.{qualname}" if self.module else f"sym:{qualname}"
        return self.graph.symbol_node(
            node_id,
            module=self.module,
            qualname=qualname,
            file=self.rel_file,
            line=line,
        )

    def _annotation(self, expr: ast.expr, line: int) -> tuple[list[str], set[str]]:
        seen: set[str] = set()
        heads = self.walker.walk(expr, line, seen)
        for bucket in seen:
            self.totals[f"names_{bucket}"] = self.totals.get(f"names_{bucket}", 0) + 1
        return heads, seen

    def _control_ok(self, expr: ast.expr) -> bool:
        """Would the builtins-only control resolver attribute every name here?"""
        for node in ast.walk(expr):
            if isinstance(node, ast.Name):
                if builtins_only_bucket(node.id) != "builtin":
                    return False
            elif isinstance(node, ast.Attribute):
                return False
            elif isinstance(node, ast.Constant):
                if isinstance(node.value, str):
                    return False
        return True

    # -- traversal --------------------------------------------------------
    def run(self, tree: ast.Module) -> None:
        self._body(tree.body, prefix="", in_class=False, depth=0)

    def _body(
        self, body: list[ast.stmt], prefix: str, in_class: bool, depth: int
    ) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                self._class(node, prefix, depth)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._function(node, prefix, in_class, depth)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                self._ann_assign(node, prefix, in_class, class_kind=None)
            elif isinstance(node, ast.Assign):
                self._maybe_alias(node, prefix)

    def _class(self, node: ast.ClassDef, prefix: str, depth: int) -> None:
        qualname = f"{prefix}{node.name}"
        sym = self._sym(qualname, node.lineno)
        self.totals["classes"] += 1
        is_dataclass = _is_dataclass_decorated(node)
        has_field_base = _has_field_base(node)
        if is_dataclass:
            self.totals["dataclasses"] += 1
        for base in node.bases:
            heads, _ = self._annotation(base, base.lineno)
            for head in heads:
                self.graph.edge(sym, head, "subtype_of", self.rel_file, base.lineno)
                self.totals["class_bases"] += 1
        kind = "dataclass" if is_dataclass else ("typed_fields" if has_field_base else None)
        for child in node.body:
            if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                self._ann_assign(child, f"{qualname}.", True, class_kind=kind)
            elif isinstance(child, ast.ClassDef):
                self._class(child, f"{qualname}.", depth + 1)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._function(child, f"{qualname}.", True, depth)

    def _ann_assign(
        self,
        node: ast.AnnAssign,
        prefix: str,
        in_class: bool,
        class_kind: str | None,
    ) -> None:
        assert isinstance(node.target, ast.Name)
        qualname = f"{prefix}{node.target.id}"
        sym = self._sym(qualname, node.lineno)
        heads, seen = self._annotation(node.annotation, node.lineno)
        edge_kind = "field_type" if in_class else "var_type"
        for head in heads:
            self.graph.edge(sym, head, edge_kind, self.rel_file, node.lineno)
        if in_class:
            self.totals["class_fields"] += 1
            if class_kind == "dataclass":
                self.totals["dataclass_fields"] += 1
                if not seen & UNRESOLVED_BUCKETS:
                    self.totals["dataclass_fields_resolved"] += 1
            elif class_kind == "typed_fields":
                self.totals["typed_base_fields"] += 1
        else:
            self.totals["module_vars"] += 1

    def _maybe_alias(self, node: ast.Assign, prefix: str) -> None:
        """Conservative alias detection: RHS is a typing subscript or a TypeVar."""
        targets = [t for t in node.targets if isinstance(t, ast.Name)]
        if not targets:
            return
        value = node.value
        head_dotted = ""
        if isinstance(value, ast.Subscript):
            head_dotted = dotted_of(value.value)
        elif isinstance(value, ast.Call):
            head_dotted = dotted_of(value.func)
        if not head_dotted:
            return
        bucket, canonical = self.resolver.resolve(
            head_dotted, self.module, self.local_names, self.bindings
        )
        leaf = canonical.rsplit(".", 1)[-1]
        is_factory = bucket == "typing" and leaf in {"TypeVar", "NewType", "ParamSpec"}
        if bucket != "typing" and not is_factory:
            return
        for target in targets:
            sym = self._sym(target.id, node.lineno)
            self.totals["type_aliases"] += 1
            if is_factory:
                dst = self.graph.type_node(bucket, canonical)
                self.graph.edge(sym, dst, "alias_of", self.rel_file, node.lineno)
            else:
                heads, _ = self._annotation(value, node.lineno)
                for head in heads:
                    self.graph.edge(sym, head, "alias_of", self.rel_file, node.lineno)

    def _function(
        self,
        fn: ast.FunctionDef | ast.AsyncFunctionDef,
        prefix: str,
        in_class: bool,
        depth: int,
    ) -> None:
        qualname = f"{prefix}{fn.name}"
        sym = self._sym(qualname, fn.lineno)
        bucket_key = "methods" if in_class else ("nested" if depth > 0 else "functions")
        self.totals[bucket_key] += 1
        params, skipped = _signature_params(fn, in_class)
        self.totals["implicit_receivers"] += skipped
        self.totals["params"] += len(params)

        annotated = True
        resolved = True
        control_ok = True
        sig_buckets: set[str] = set()
        # Decoupled accounting: what is actually THERE, and does it resolve.
        # ``annotated``/``resolved`` are locked together by construction (a
        # missing annotation kills both); these two are not.
        present = 0
        present_unresolved = 0

        for param in params:
            param_sym = self.graph.symbol_node(
                f"{sym}#{param.arg}",
                module=self.module,
                qualname=f"{qualname}#{param.arg}",
                file=self.rel_file,
                line=fn.lineno,
            )
            if param.annotation is None:
                annotated = False
                resolved = False
                control_ok = False
                continue
            self.totals["params_annotated"] += 1
            present += 1
            # locate at the annotation itself, not at the enclosing ``def``:
            # a multi-line signature would otherwise send every reader to the
            # wrong line.
            ann_line = param.annotation.lineno
            heads, seen = self._annotation(param.annotation, ann_line)
            for head in heads:
                self.graph.edge(param_sym, head, "param_type", self.rel_file, ann_line)
            sig_buckets |= seen
            if seen & UNRESOLVED_BUCKETS:
                resolved = False
                present_unresolved += 1
            control_ok = control_ok and self._control_ok(param.annotation)

        if fn.returns is None:
            annotated = False
            resolved = False
            control_ok = False
        else:
            self.totals["returns_annotated"] += 1
            present += 1
            ret_line = fn.returns.lineno
            heads, seen = self._annotation(fn.returns, ret_line)
            for head in heads:
                self.graph.edge(sym, head, "return_type", self.rel_file, ret_line)
            sig_buckets |= seen
            if seen & UNRESOLVED_BUCKETS:
                resolved = False
                present_unresolved += 1
            control_ok = control_ok and self._control_ok(fn.returns)

        if annotated:
            self.totals["sig_annotated"] += 1
        if resolved:
            self.totals["sig_resolved"] += 1
        if annotated and not resolved:
            # The ENTIRE marginal contribution of the binding + symbol-table
            # machinery over the annotation-only control lives in this counter.
            self.totals["sig_annotated_but_unresolvable"] += 1
        if present:
            self.totals["sig_any_annotation"] += 1
            if not present_unresolved:
                self.totals["sig_present_annotations_resolve"] += 1
        else:
            self.totals["sig_no_annotation"] += 1
        if control_ok:
            self.totals["sig_resolved_builtins_only"] += 1
            if not params:
                self.totals["sig_resolved_builtins_only_zero_param"] += 1
        if resolved:
            if sig_buckets & REPO_BUCKETS:
                self.totals["sig_resolved_needs_repo_types"] += 1
            else:
                self.totals["sig_resolved_without_repo_types"] += 1
        if not params:
            self.totals["zero_param_functions"] += 1
            if resolved:
                self.totals["sig_resolved_zero_param"] += 1

        self._body(fn.body, f"{qualname}.", in_class=False, depth=depth + 1)


# --------------------------------------------------------------------------
# revision (file reads only -- no subprocess)
# --------------------------------------------------------------------------
def git_revision(root: Path) -> str | None:
    try:
        git = root / ".git"
        if git.is_file():
            text = git.read_text(encoding="utf-8").strip()
            if not text.startswith("gitdir:"):
                return None
            git = Path(text.split(":", 1)[1].strip())
            if not git.is_absolute():
                git = (root / git).resolve()
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref:"):
            return head
        ref = head.split(":", 1)[1].strip()
        candidates = [git / ref]
        commondir = git / "commondir"
        if commondir.is_file():
            common = Path(commondir.read_text(encoding="utf-8").strip())
            if not common.is_absolute():
                common = (git / common).resolve()
            candidates.append(common / ref)
        for candidate in candidates:
            if candidate.is_file():
                return candidate.read_text(encoding="utf-8").strip()
        for candidate in candidates:
            packed = candidate.parent
            while packed != packed.parent and not (packed / "packed-refs").is_file():
                packed = packed.parent
            packed_refs = packed / "packed-refs"
            if packed_refs.is_file():
                for line in packed_refs.read_text(encoding="utf-8").splitlines():
                    if line.endswith(f" {ref}"):
                        return line.split(" ", 1)[0]
    except OSError:
        return None
    return None


# --------------------------------------------------------------------------
# top level
# --------------------------------------------------------------------------
TOTAL_KEYS = (
    "files_parsed",
    "files_unparseable",
    "functions",
    "methods",
    "nested",
    "classes",
    "dataclasses",
    "class_bases",
    "class_fields",
    "dataclass_fields",
    "dataclass_fields_resolved",
    "typed_base_fields",
    "module_vars",
    "type_aliases",
    "params",
    "params_annotated",
    "returns_annotated",
    "implicit_receivers",
    "sig_annotated",
    "sig_resolved",
    "sig_annotated_but_unresolvable",
    "sig_any_annotation",
    "sig_no_annotation",
    "sig_present_annotations_resolve",
    "sig_resolved_builtins_only",
    "sig_resolved_builtins_only_zero_param",
    "sig_resolved_needs_repo_types",
    "sig_resolved_without_repo_types",
    "zero_param_functions",
    "sig_resolved_zero_param",
    "type_name_sites",
    "type_name_sites_resolved",
)


def corpus_pin(entries: list[tuple[str, bytes]]) -> dict[str, Any]:
    """Content pin for the corpus actually read.

    A revision only pins a repository.  The external corpora this slice grew
    to need (a stdlib subset, a fixture tree) have no revision, so every run
    carries a digest over ``<relpath>\\0<sha256>`` of every file it parsed --
    including the unparseable ones, which are part of the corpus too.

    Line endings are normalised to ``\\n`` before hashing.  A checkout that
    rewrites CRLF would otherwise move every pin without one character of
    content changing, and this repository does rewrite them.  The digest is
    therefore content-exact rather than byte-exact, which is the property the
    pin is actually for.
    """
    digest = hashlib.sha256()
    for rel, data in sorted(entries):
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        normalised = data.replace(b"\r\n", b"\n")
        digest.update(hashlib.sha256(normalised).hexdigest().encode("ascii"))
        digest.update(b"\n")
    return {"files": len(entries), "sha256": digest.hexdigest()}


def build_type_plane(
    root: Path, packages: Iterable[str] = DEFAULT_PACKAGES
) -> dict[str, Any]:
    packages = tuple(packages)
    paths = list(iter_py_files(root, packages))

    parsed: list[tuple[Path, str, bool, ast.Module]] = []
    module_symbols: dict[str, set[str]] = {}
    totals: dict[str, int] = {key: 0 for key in TOTAL_KEYS}
    pin_entries: list[tuple[str, bytes]] = []

    for path in paths:
        try:
            raw = path.read_bytes()
        except OSError:
            totals["files_unparseable"] += 1
            continue
        pin_entries.append((path.relative_to(root).as_posix(), raw))
        try:
            tree = ast.parse(raw.decode("utf-8", errors="replace"))
        except (SyntaxError, ValueError):
            totals["files_unparseable"] += 1
            continue
        module, is_package = module_name_of(root, path)
        parsed.append((path, module, is_package, tree))
        module_symbols[module] = top_level_symbols(tree)
        totals["files_parsed"] += 1

    resolver = Resolver(
        module_symbols=module_symbols,
        module_names=set(module_symbols),
        repo_roots=frozenset(packages),
    )
    graph = Graph()
    unresolved_names: dict[str, list[str]] = {}

    for path, module, is_package, tree in parsed:
        rel = path.relative_to(root).as_posix()
        extractor = FileExtractor(
            graph=graph,
            resolver=resolver,
            module=module,
            rel_file=rel,
            local_names=module_symbols[module],
            bindings=import_bindings(tree, module, is_package),
            totals=totals,
            unresolved_names=unresolved_names,
        )
        extractor.run(tree)

    all_functions = totals["functions"] + totals["methods"] + totals["nested"]
    top_functions = totals["functions"] + totals["methods"]
    denominator = all_functions or 1

    bucket_counts: dict[str, int] = {}
    for node in graph.nodes.values():
        if node["plane"] == "type":
            bucket = node["bucket"]
            bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1

    edge_kinds: dict[str, int] = {}
    for edge in graph.edges.values():
        edge_kinds[edge["kind"]] = edge_kinds.get(edge["kind"], 0) + 1

    def pct(numerator: int, total: int) -> float:
        # Two decimals on purpose: at one decimal 3294/3295 prints as a
        # flawless 100.0, and a rate that rounds up into a flawless score is
        # the one number a reader must never be handed.
        return round(100.0 * numerator / (total or 1), 2)

    marginal = totals["sig_annotated_but_unresolvable"]
    controls = {
        "annotation_only": {
            "status": "control",
            "resolved": totals["sig_annotated"],
            "pct": pct(totals["sig_annotated"], denominator),
            "rule": "signature counts iff every parameter and the return "
            "carry a syntactic annotation; no name is looked up",
        },
        "full_resolver": {
            "resolved": totals["sig_resolved"],
            "pct": pct(totals["sig_resolved"], denominator),
            "rule": "annotation_only AND every referenced type name attributable",
        },
        "marginal_vs_annotation_only": {
            "functions": marginal,
            "pp": round(100.0 * marginal / denominator, 4),
            "direction": "subtractive" if marginal else "none",
            "note": "the full resolver is a strict subset of the "
            "annotation-only control, so this is both the observed "
            "difference and its own upper bound",
        },
        "builtins_only": {
            "status": "RETRACTED -- not a control",
            "resolved": totals["sig_resolved_builtins_only"],
            "pct": pct(totals["sig_resolved_builtins_only"], denominator),
            "zero_param_share_of_hits": pct(
                totals["sig_resolved_builtins_only_zero_param"],
                totals["sig_resolved_builtins_only"],
            ),
            "note": "cannot read any import statement by construction; "
            "retained as negative evidence only",
        },
    }
    return {
        "schema": SCHEMA,
        "read_only": True,
        "root": root.as_posix(),
        "packages": list(packages),
        "revision": git_revision(root),
        "corpus_pin": corpus_pin(pin_entries),
        "totals": totals,
        "functions_total": all_functions,
        "functions_top_level_and_methods": top_functions,
        "controls": controls,
        "coupling": {
            "sig_resolved_is_subset_of_sig_annotated": totals["sig_resolved"]
            <= totals["sig_annotated"],
            "decoupled_metrics": [
                "type_name_resolution_pct",
                "sig_present_annotations_resolve_pct",
            ],
        },
        "rates": {
            "sig_annotated_pct": pct(totals["sig_annotated"], denominator),
            "sig_resolved_pct": pct(totals["sig_resolved"], denominator),
            # Decoupled from annotation coverage -- these are the two rates a
            # resolvability claim (or its falsification) may rest on.
            "type_name_resolution_pct": pct(
                totals["type_name_sites_resolved"], totals["type_name_sites"]
            ),
            "sig_present_annotations_resolve_pct": pct(
                totals["sig_present_annotations_resolve"], totals["sig_any_annotation"]
            ),
            "sig_resolved_builtins_only_pct": pct(
                totals["sig_resolved_builtins_only"], denominator
            ),
            "sig_resolved_without_repo_types_pct": pct(
                totals["sig_resolved_without_repo_types"], denominator
            ),
            "sig_resolved_pct_excl_zero_param": pct(
                totals["sig_resolved"] - totals["sig_resolved_zero_param"],
                all_functions - totals["zero_param_functions"],
            ),
            "params_annotated_pct": pct(totals["params_annotated"], totals["params"]),
            "returns_annotated_pct": pct(totals["returns_annotated"], denominator),
            "dataclass_fields_resolved_pct": pct(
                totals["dataclass_fields_resolved"], totals["dataclass_fields"]
            ),
        },
        "graph": {
            "type_nodes": sum(bucket_counts.values()),
            "symbol_nodes": sum(
                1 for n in graph.nodes.values() if n["plane"] == "code"
            ),
            "edges_unique": len(graph.edges),
            "edges_weighted": sum(e["count"] for e in graph.edges.values()),
            "type_nodes_by_bucket": dict(sorted(bucket_counts.items())),
            "edges_by_kind": dict(sorted(edge_kinds.items())),
        },
        "annotations_touching_bucket": {
            key[len("names_") :]: value
            for key, value in sorted(totals.items())
            if key.startswith("names_")
        },
        "type_name_sites_by_bucket": {
            key[len("sites_") :]: value
            for key, value in sorted(totals.items())
            if key.startswith("sites_")
        },
        "unresolved_annotation_names": [
            {"name": name, "sites": sites}
            for name, sites in sorted(
                unresolved_names.items(), key=lambda kv: (-len(kv[1]), kv[0])
            )
        ],
        "_graph_object": graph,
    }


def summary(report: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in report.items() if key != "_graph_object"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="forest_v2 s02 type-plane probe")
    parser.add_argument("root", nargs="?", default=None)
    parser.add_argument("--packages", default=",".join(DEFAULT_PACKAGES))
    parser.add_argument(
        "--graph",
        action="store_true",
        help="also print the full node/edge lists (large)",
    )
    args = parser.parse_args(argv)
    root = Path(args.root) if args.root else Path(__file__).resolve().parents[3]
    report = build_type_plane(root, tuple(p for p in args.packages.split(",") if p))
    payload = summary(report)
    if args.graph:
        graph: Graph = report["_graph_object"]
        payload["nodes"] = sorted(graph.nodes.values(), key=lambda n: n["id"])
        payload["edges"] = sorted(
            graph.edges.values(), key=lambda e: (e["src"], e["kind"], e["dst"])
        )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
