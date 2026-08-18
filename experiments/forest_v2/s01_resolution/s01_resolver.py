"""EXPERIMENT (forest_v2 / slice s01): scope-aware call resolution over the index.

Read-only, pure stdlib, never imported by production code.

The pre-study probe classified a call site by its *spelling*: the last dotted
segment was looked up in a flat set of every function and method name in the
file.  That is generous in both directions -- it claims ``path.read_text()``
for a local method called ``read_text`` and it cannot see ``self.run()`` at all.

This resolver instead walks scopes and answers, for every ``ast.Call``, one of:

* a **repo** target with file and line (a definition we can point at),
* an **external** target with a module name (a claim, not a proof), or
* an **unresolved** site with a named reason.

The reasons are the point.  A resolver that is honest about *why* it failed
gives Gate 2 a work list; a resolver that reports one aggregate percentage
gives it a slogan.
"""
from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass, field
from pathlib import Path

from s01_index import ClassInfo, ModuleInfo, ProjectIndex, dotted_name, import_bindings

BUILTIN_NAMES = frozenset(dir(builtins))

VERIFIED_KINDS = frozenset(
    {
        "local_function",
        "local_class",
        "import_repo",
        "module_attr_repo",
        "repo_class_attr",
        "self_method",
        "super_method",
        "cls_method",
        "local_var_method",
        "self_attr_method",
    }
)

EXTERNAL_KINDS = frozenset(
    {
        "builtin",
        "import_external",
        "module_attr_external",
        "self_method_external_base",
        "external_class_attr",
    }
)


@dataclass(frozen=True)
class Resolution:
    """One call site's answer.

    ``site_line`` is where the call is; ``target_rel``/``target_line`` are where
    the definition is.  A ``verified`` resolution always carries both, which is
    what makes the claim auditable: reopen the file at that line and the
    definition must be there (see ``s01_measure.audit_definitions``).
    """

    kind: str
    status: str  # 'verified' | 'external' | 'unresolved'
    target: str
    site_rel: str
    site_line: int
    target_module: str = ""
    target_rel: str = ""
    target_line: int = 0
    origin: str = ""  # how a receiver type was learned, for local_var_method


@dataclass
class Scope:
    parent: "Scope | None" = None
    bindings: dict[str, str] = field(default_factory=dict)  # local -> dotted import
    local_defs: dict[str, tuple[str, int]] = field(default_factory=dict)  # name -> kind,line
    var_types: dict[str, str] = field(default_factory=dict)  # local -> raw class expr
    var_origin: dict[str, str] = field(default_factory=dict)
    shadowed: set[str] = field(default_factory=set)  # assigned locally, type unknown
    class_info: ClassInfo | None = None
    self_name: str = ""
    cls_name: str = ""
    is_module: bool = False

    def resolve_name(self, name: str) -> tuple[str, object]:
        """Nearest binding for ``name``: the first scope that binds it wins.

        Returns one of ``('localdef', (kind, line))``, ``('binding', dotted)``,
        ``('vartype', (raw, origin))``, ``('shadow', is_module_scope)`` or
        ``('none', None)``.
        """
        scope: Scope | None = self
        while scope is not None:
            if name in scope.local_defs:
                return "localdef", scope.local_defs[name]
            if name in scope.bindings:
                return "binding", scope.bindings[name]
            if name in scope.var_types:
                return "vartype", (
                    scope.var_types[name],
                    scope.var_origin.get(name, "assign"),
                )
            if name in scope.shadowed:
                return "shadow", scope.is_module
            scope = scope.parent
        return "none", None

    def enclosing_class(self) -> ClassInfo | None:
        scope: Scope | None = self
        while scope is not None:
            if scope.class_info is not None:
                return scope.class_info
            scope = scope.parent
        return None

    def receiver_role(self, name: str) -> str:
        """'self' / 'cls' / '' for a receiver name, honouring the nearest method."""
        scope: Scope | None = self
        while scope is not None:
            if scope.self_name and name == scope.self_name:
                return "self"
            if scope.cls_name and name == scope.cls_name:
                return "cls"
            if scope.self_name or scope.cls_name:
                return ""
            scope = scope.parent
        return ""


@dataclass(frozen=True)
class Options:
    """Ablation switches.  Each one removes a mechanism the resolver claims to
    need, so its marginal contribution can be measured instead of asserted."""

    use_imports: bool = True
    use_hierarchy: bool = True
    use_receiver_types: bool = True
    # Randomised control: repo module name -> the module its bindings should be
    # made to point at instead.  Applied to EVERY binding the resolver learns,
    # module-level and function-level alike.  A control that only rewrites the
    # module-level table leaks, because inline imports re-seed the true value.
    module_map: dict | None = None


FULL = Options()


class CallResolver:
    """Resolves every call site in one module of an indexed tree."""

    def __init__(
        self, index: ProjectIndex, module: ModuleInfo, options: Options = FULL
    ) -> None:
        self.index = index
        self.module = module
        self.options = options
        self.results: list[tuple[ast.Call, Resolution]] = []

    def _bind(self, dotted: str) -> str:
        """Apply the randomised control to one binding target, if one is active."""
        mapping = self.options.module_map
        if not mapping or not dotted:
            return dotted
        parts = dotted.split(".")
        for cut in range(len(parts), 0, -1):
            prefix = ".".join(parts[:cut])
            if prefix in mapping:
                return ".".join([mapping[prefix]] + parts[cut:])
        return dotted

    def _bind_all(self, table: dict) -> dict:
        if not self.options.module_map:
            return dict(table)
        return {local: self._bind(target) for local, target in table.items()}

    def _lookup_attribute(self, info: ClassInfo, attr: str) -> tuple[str, object]:
        if self.options.use_hierarchy:
            return self.index.lookup_attribute(info, attr)
        if attr in info.methods:
            return "method", (info, info.methods[attr])
        if attr in info.attributes:
            return "attribute", (info, info.attributes[attr])
        return "missing", None

    # ---- public -------------------------------------------------------
    def run(self) -> list[tuple[ast.Call, Resolution]]:
        scope = Scope(is_module=True)
        if self.options.use_imports:
            scope.bindings.update(self._bind_all(self.module.imports))
        scope.local_defs.update(
            {
                name: (kind, line)
                for name, (kind, line) in self.module.defs.items()
                if kind in {"function", "class"}
            }
        )
        self._seed_assignments(self.module.tree.body, scope, "assign")
        self._visit_body(self.module.tree.body, scope)
        return self.results

    # ---- scope construction -------------------------------------------
    def _seed_assignments(self, body: list[ast.stmt], scope: Scope, origin: str) -> None:
        """Learn local variable types without descending into nested scopes."""
        for stmt in body:
            for node in self._shallow_walk(stmt):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    scope.local_defs[node.name] = ("function", node.lineno)
                    scope.shadowed.discard(node.name)
                elif isinstance(node, ast.ClassDef):
                    scope.local_defs[node.name] = ("class", node.lineno)
                    scope.shadowed.discard(node.name)
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    if self.options.use_imports:
                        scope.bindings.update(
                            self._bind_all(import_bindings(node, self.module.name))
                        )
                elif isinstance(node, ast.Assign):
                    raw = (
                        dotted_name(node.value.func)
                        if isinstance(node.value, ast.Call)
                        else ""
                    )
                    for target in node.targets:
                        if not isinstance(target, ast.Name):
                            continue
                        if (
                            self.options.use_receiver_types
                            and raw
                            and self.index.class_of(self.module.name, raw)
                        ):
                            scope.var_types[target.id] = raw
                            scope.var_origin[target.id] = origin
                        else:
                            scope.shadowed.add(target.id)
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    raw = dotted_name(node.annotation)
                    if (
                        self.options.use_receiver_types
                        and raw
                        and self.index.class_of(self.module.name, raw)
                    ):
                        scope.var_types[node.target.id] = raw
                        scope.var_origin[node.target.id] = "annotation"
                    else:
                        scope.shadowed.add(node.target.id)
                elif isinstance(node, (ast.For, ast.AsyncFor)):
                    self._shadow_target(node.target, scope)
                elif isinstance(node, (ast.With, ast.AsyncWith)):
                    for item in node.items:
                        if item.optional_vars is not None:
                            self._shadow_target(item.optional_vars, scope)
                elif isinstance(node, ast.ExceptHandler) and node.name:
                    scope.shadowed.add(node.name)

    def _shadow_target(self, target: ast.AST, scope: Scope) -> None:
        for node in ast.walk(target):
            if isinstance(node, ast.Name):
                scope.shadowed.add(node.id)

    @staticmethod
    def _annotations(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.expr]:
        args = node.args
        out: list[ast.expr] = []
        if node.returns is not None:
            out.append(node.returns)
        every = (
            list(args.posonlyargs)
            + list(args.args)
            + list(args.kwonlyargs)
            + [a for a in (args.vararg, args.kwarg) if a is not None]
        )
        out.extend(a.annotation for a in every if a.annotation is not None)
        return out

    @staticmethod
    def _shallow_walk(stmt: ast.AST):
        """Yield ``stmt`` and its descendants without entering a nested scope.

        Nested ``def``/``class``/``lambda`` nodes are yielded (they bind a name
        in *this* scope) but never descended into (their bodies are their own
        scope).
        """
        nested = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        stack = [stmt]
        while stack:
            node = stack.pop()
            yield node
            if isinstance(node, nested):
                continue
            stack.extend(ast.iter_child_nodes(node))

    def _function_scope(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, parent: Scope
    ) -> Scope:
        scope = Scope(parent=parent)
        args = node.args
        positional = list(args.posonlyargs) + list(args.args)
        decorators = {dotted_name(d).split(".")[-1] for d in node.decorator_list}
        enclosing = parent.class_info
        if enclosing is not None and positional:
            if "staticmethod" not in decorators:
                if "classmethod" in decorators:
                    scope.cls_name = positional[0].arg
                else:
                    scope.self_name = positional[0].arg
        for arg in positional + list(args.kwonlyargs) + [
            a for a in (args.vararg, args.kwarg) if a is not None
        ]:
            raw = dotted_name(arg.annotation) if arg.annotation is not None else ""
            if (
                self.options.use_receiver_types
                and raw
                and self.index.class_of(self.module.name, raw)
            ):
                scope.var_types[arg.arg] = raw
                scope.var_origin[arg.arg] = "param_annotation"
            else:
                scope.shadowed.add(arg.arg)
        if scope.self_name:
            scope.shadowed.discard(scope.self_name)
        if scope.cls_name:
            scope.shadowed.discard(scope.cls_name)
        self._seed_assignments(node.body, scope, "assign")
        return scope

    # ---- traversal ----------------------------------------------------
    def _visit_body(self, body: list[ast.stmt], scope: Scope) -> None:
        for stmt in body:
            self._visit(stmt, scope)

    def _visit(self, node: ast.AST, scope: Scope) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                self._visit(decorator, scope)
            for default in list(node.args.defaults) + [
                d for d in node.args.kw_defaults if d is not None
            ]:
                self._visit(default, scope)
            for annotation in self._annotations(node):
                self._visit(annotation, scope)
            inner = self._function_scope(node, scope)
            self._visit_body(node.body, inner)
            return
        if isinstance(node, ast.ClassDef):
            for decorator in node.decorator_list:
                self._visit(decorator, scope)
            for base in list(node.bases) + [k.value for k in node.keywords]:
                self._visit(base, scope)
            inner = Scope(parent=scope)
            inner.class_info = self.module.classes.get(node.name)
            self._seed_assignments(node.body, inner, "assign")
            self._visit_body(node.body, inner)
            return
        if isinstance(node, ast.Lambda):
            for default in list(node.args.defaults) + [
                d for d in node.args.kw_defaults if d is not None
            ]:
                self._visit(default, scope)
            inner = Scope(parent=scope)
            for arg in list(node.args.posonlyargs) + list(node.args.args) + list(
                node.args.kwonlyargs
            ):
                inner.shadowed.add(arg.arg)
            self._visit(node.body, inner)
            return
        if isinstance(node, ast.Call):
            self.results.append((node, self._resolve_call(node, scope)))
            self._visit(node.func, scope)
            for child in list(node.args) + [k.value for k in node.keywords]:
                self._visit(child, scope)
            return
        for child in ast.iter_child_nodes(node):
            self._visit(child, scope)

    # ---- the actual resolution ----------------------------------------
    def _resolve_call(self, node: ast.Call, scope: Scope) -> Resolution:
        func = node.func
        if isinstance(func, ast.Name):
            return self._resolve_bare(func.id, node.lineno, scope)
        if isinstance(func, ast.Attribute):
            return self._resolve_attribute(func, node.lineno, scope)
        return self._unresolved("unresolvable_shape", node.lineno)

    def _unresolved(self, reason: str, lineno: int) -> Resolution:
        return Resolution(reason, "unresolved", "", self.module.rel, lineno)

    def _repo(self, kind: str, target, lineno: int, origin: str = "") -> Resolution:
        module, name, rel, line = target
        return Resolution(
            kind,
            "verified",
            f"{module}.{name}" if name else module,
            self.module.rel,
            lineno,
            target_module=module,
            target_rel=rel,
            target_line=line,
            origin=origin,
        )

    def _external(self, kind: str, dotted: str, lineno: int) -> Resolution:
        return Resolution(kind, "external", dotted, self.module.rel, lineno)

    def _resolve_bare(self, name: str, lineno: int, scope: Scope) -> Resolution:
        # ``cls(...)`` inside a classmethod constructs the enclosing class.
        if scope.receiver_role(name) == "cls":
            enclosing = scope.enclosing_class()
            if enclosing is not None:
                return self._repo(
                    "local_class",
                    (enclosing.module, enclosing.name,
                     self.index.modules[enclosing.module].rel, enclosing.lineno),
                    lineno,
                )

        found_kind, payload = scope.resolve_name(name)
        if found_kind == "localdef":
            def_kind, def_line = payload  # type: ignore[misc]
            bucket = "local_class" if def_kind == "class" else "local_function"
            return self._repo(
                bucket, (self.module.name, name, self.module.rel, def_line), lineno
            )
        if found_kind == "binding":
            found = self.index.resolve_dotted(str(payload))
            if found.status == "repo":
                return self._repo(
                    "import_repo",
                    (found.module, found.symbol, found.rel, found.lineno),
                    lineno,
                )
            if found.status == "external":
                return self._external("import_external", found.dotted, lineno)
            return self._unresolved("import_unknown", lineno)
        if found_kind == "vartype":
            raw, _origin = payload  # type: ignore[misc]
            info = self.index.class_of(self.module.name, str(raw))
            if info is not None:
                return self._repo(
                    "local_class",
                    (info.module, info.name, self.index.modules[info.module].rel,
                     info.lineno),
                    lineno,
                )
            return self._unresolved("local_callable", lineno)
        if found_kind == "shadow":
            return self._unresolved(
                "module_variable_callable" if payload else "local_callable", lineno
            )
        enclosing = scope.enclosing_class()
        if enclosing is not None and name in enclosing.methods:
            return self._repo(
                "local_function",
                (self.module.name, f"{enclosing.name}.{name}", self.module.rel,
                 enclosing.methods[name]),
                lineno,
            )
        if name in BUILTIN_NAMES:
            return self._external("builtin", f"builtins.{name}", lineno)
        if self.module.star_imports:
            return self._unresolved("star_import_shadow", lineno)
        return self._unresolved("unknown_name", lineno)

    def _resolve_attribute(
        self, func: ast.Attribute, lineno: int, scope: Scope
    ) -> Resolution:
        attr = func.attr
        value = func.value

        # super().method()
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "super"
        ):
            enclosing = scope.enclosing_class()
            if enclosing is None:
                return self._unresolved("super_outside_class", lineno)
            return self._from_bases(enclosing, attr, lineno, "super_method")

        if isinstance(value, ast.Name):
            role = scope.receiver_role(value.id)
            if role in {"self", "cls"}:
                enclosing = scope.enclosing_class()
                if enclosing is None:
                    return self._unresolved("self_outside_class", lineno)
                kind = "self_method" if role == "self" else "cls_method"
                return self._from_class(enclosing, attr, lineno, kind, "self_unknown")

            found_kind, payload = scope.resolve_name(value.id)
            if found_kind == "vartype":
                raw, origin = payload  # type: ignore[misc]
                info = self.index.class_of(self.module.name, str(raw))
                if info is not None:
                    return self._from_class(
                        info, attr, lineno, "local_var_method", "local_var_attr_missing",
                        origin=str(origin),
                    )
                return self._unresolved("untyped_local_receiver", lineno)
            if found_kind == "binding":
                return self._through_binding(str(payload), attr, lineno)
            if found_kind == "localdef":
                def_kind, _ = payload  # type: ignore[misc]
                if def_kind == "class":
                    info = self.module.classes.get(value.id)
                    if info is not None:
                        return self._from_class(
                            info, attr, lineno, "repo_class_attr", "repo_class_attr_missing"
                        )
                return self._unresolved("function_object_receiver", lineno)
            if found_kind == "shadow":
                return self._unresolved(
                    "module_variable_receiver" if payload else "untyped_local_receiver",
                    lineno,
                )

            if value.id in BUILTIN_NAMES:
                return self._external("builtin", f"builtins.{value.id}.{attr}", lineno)
            return self._unresolved("unknown_receiver", lineno)

        # self.<attr>.method() -- instance attribute with a known constructor
        if (
            isinstance(value, ast.Attribute)
            and isinstance(value.value, ast.Name)
            and scope.receiver_role(value.value.id) == "self"
        ):
            enclosing = scope.enclosing_class()
            if enclosing is not None and self.options.use_receiver_types:
                kind, payload = self._lookup_attribute(enclosing, value.attr)
                if kind == "attribute":
                    owner, raw = payload  # type: ignore[misc]
                    info = self.index.class_of(owner.module, raw)
                    if info is not None:
                        return self._from_class(
                            info, attr, lineno, "self_attr_method", "self_attr_missing"
                        )
                return self._unresolved("untyped_self_attribute", lineno)

        # module.submodule.func() style dotted chains
        chain = dotted_name(value)
        if chain:
            head, _, rest = chain.partition(".")
            found_kind, payload = scope.resolve_name(head)
            if found_kind == "binding":
                binding = str(payload)
                dotted = f"{binding}.{rest}.{attr}" if rest else f"{binding}.{attr}"
                return self._through_dotted(dotted, lineno)
            return self._unresolved("chain_receiver", lineno)

        if isinstance(value, ast.Call):
            return self._unresolved("call_result_receiver", lineno)
        if isinstance(value, ast.Subscript):
            return self._unresolved("subscript_receiver", lineno)
        if isinstance(value, (ast.Constant, ast.JoinedStr, ast.List, ast.Dict, ast.Set,
                              ast.Tuple, ast.ListComp, ast.DictComp, ast.SetComp)):
            return self._unresolved("literal_receiver", lineno)
        return self._unresolved("other_receiver", lineno)

    # ---- helpers -------------------------------------------------------
    def _from_class(
        self,
        info: ClassInfo,
        attr: str,
        lineno: int,
        kind: str,
        miss_reason: str,
        origin: str = "",
    ) -> Resolution:
        found, payload = self._lookup_attribute(info, attr)
        if found == "method":
            owner, line = payload  # type: ignore[misc]
            rel = self.index.modules[owner.module].rel
            return self._repo(
                kind, (owner.module, f"{owner.name}.{attr}", rel, line), lineno, origin
            )
        if found == "external_base":
            return self._external(
                "self_method_external_base", f"{payload}.{attr}", lineno
            )
        if found == "attribute":
            return self._unresolved("attribute_not_callable", lineno)
        return self._unresolved(miss_reason, lineno)

    def _from_bases(
        self, info: ClassInfo, attr: str, lineno: int, kind: str
    ) -> Resolution:
        external = ""
        for raw in info.bases:
            base = self.index.class_of(info.module, raw)
            if base is None:
                if raw.split(".")[-1] not in {"object"}:
                    external = external or raw
                continue
            found, payload = self._lookup_attribute(base, attr)
            if found == "method":
                owner, line = payload  # type: ignore[misc]
                rel = self.index.modules[owner.module].rel
                return self._repo(
                    kind, (owner.module, f"{owner.name}.{attr}", rel, line), lineno
                )
            if found == "external_base" and not external:
                external = str(payload)
        if external:
            return self._external("self_method_external_base", f"{external}.{attr}", lineno)
        return self._unresolved("super_base_missing", lineno)

    def _through_binding(self, binding: str, attr: str, lineno: int) -> Resolution:
        found = self.index.resolve_dotted(binding)
        if found.status == "repo" and found.kind == "module":
            return self._through_dotted(f"{binding}.{attr}", lineno)
        if found.status == "repo" and found.kind == "class":
            info = self.index.modules[found.module].classes.get(found.symbol)
            if info is not None:
                return self._from_class(
                    info, attr, lineno, "repo_class_attr", "repo_class_attr_missing"
                )
        if found.status == "repo":
            return self._unresolved("repo_symbol_attr", lineno)
        if found.status == "external":
            return self._external("module_attr_external", f"{found.dotted}.{attr}", lineno)
        return self._unresolved("binding_unknown", lineno)

    def _through_dotted(self, dotted: str, lineno: int) -> Resolution:
        found = self.index.resolve_dotted(dotted)
        if found.status == "repo":
            if found.kind == "module":
                return self._unresolved("module_not_symbol", lineno)
            return self._repo(
                "module_attr_repo",
                (found.module, found.symbol, found.rel, found.lineno),
                lineno,
            )
        if found.status == "external":
            return self._external("module_attr_external", found.dotted, lineno)
        return self._unresolved("dotted_unknown", lineno)


def resolve_module(
    index: ProjectIndex, module: ModuleInfo, options: Options = FULL
) -> list[tuple[ast.Call, Resolution]]:
    return CallResolver(index, module, options).run()


def resolve_tree(root: Path, packages: tuple[str, ...] | None = None):
    """Convenience: index ``root`` and resolve every module.  Yields (module, results)."""
    from s01_index import DEFAULT_PACKAGES, build_index

    index = build_index(root, packages or DEFAULT_PACKAGES)
    for module in index.modules.values():
        yield module, resolve_module(index, module)
