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
    kind: str
    status: str  # 'verified' | 'external' | 'unresolved'
    target: str
    rel: str
    lineno: int
    target_module: str = ""
    origin: str = ""  # how a receiver type was learned, for local_var_method


@dataclass
class Scope:
    parent: "Scope | None" = None
    bindings: dict[str, str] = field(default_factory=dict)  # local -> dotted import
    var_types: dict[str, str] = field(default_factory=dict)  # local -> raw class expr
    var_origin: dict[str, str] = field(default_factory=dict)
    shadowed: set[str] = field(default_factory=set)  # assigned locally, type unknown
    class_info: ClassInfo | None = None
    self_name: str = ""
    cls_name: str = ""

    def binding(self, name: str) -> str | None:
        scope: Scope | None = self
        while scope is not None:
            if name in scope.bindings:
                return scope.bindings[name]
            if name in scope.shadowed or name in scope.var_types:
                return None
            scope = scope.parent
        return None

    def var_type(self, name: str) -> tuple[str, str] | None:
        scope: Scope | None = self
        while scope is not None:
            if name in scope.var_types:
                return scope.var_types[name], scope.var_origin.get(name, "assign")
            if name in scope.shadowed:
                return None
            scope = scope.parent
        return None

    def is_local(self, name: str) -> bool:
        scope: Scope | None = self
        while scope is not None:
            if name in scope.shadowed or name in scope.var_types:
                return True
            scope = scope.parent
        return False

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


class CallResolver:
    """Resolves every call site in one module of an indexed tree."""

    def __init__(self, index: ProjectIndex, module: ModuleInfo) -> None:
        self.index = index
        self.module = module
        self.results: list[tuple[ast.Call, Resolution]] = []

    # ---- public -------------------------------------------------------
    def run(self) -> list[tuple[ast.Call, Resolution]]:
        scope = Scope()
        scope.bindings.update(self.module.imports)
        self._seed_assignments(self.module.tree.body, scope, "assign")
        self._visit_body(self.module.tree.body, scope)
        return self.results

    # ---- scope construction -------------------------------------------
    def _seed_assignments(self, body: list[ast.stmt], scope: Scope, origin: str) -> None:
        """Learn local variable types without descending into nested scopes."""
        for stmt in body:
            for node in self._shallow_walk(stmt):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    scope.bindings.update(import_bindings(node, self.module.name))
                elif isinstance(node, ast.Assign):
                    raw = (
                        dotted_name(node.value.func)
                        if isinstance(node.value, ast.Call)
                        else ""
                    )
                    for target in node.targets:
                        if not isinstance(target, ast.Name):
                            continue
                        if raw and self.index.class_of(self.module.name, raw):
                            scope.var_types[target.id] = raw
                            scope.var_origin[target.id] = origin
                        else:
                            scope.shadowed.add(target.id)
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    raw = dotted_name(node.annotation)
                    if raw and self.index.class_of(self.module.name, raw):
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
        """Yield ``stmt`` and its descendants, stopping at nested scopes."""
        stack = [stmt]
        while stack:
            node = stack.pop()
            yield node
            for child in ast.iter_child_nodes(node):
                if isinstance(
                    child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
                ):
                    continue
                stack.append(child)

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
            if raw and self.index.class_of(self.module.name, raw):
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
            rel,
            lineno,
            target_module=module,
            origin=origin,
        )

    def _external(self, kind: str, dotted: str, lineno: int) -> Resolution:
        return Resolution(kind, "external", dotted, self.module.rel, lineno)

    def _resolve_bare(self, name: str, lineno: int, scope: Scope) -> Resolution:
        binding = scope.binding(name)
        if binding is not None:
            found = self.index.resolve_dotted(binding)
            if found.status == "repo":
                kind = "import_repo"
                return self._repo(
                    kind, (found.module, found.symbol, found.rel, found.lineno), lineno
                )
            if found.status == "external":
                return self._external("import_external", found.dotted, lineno)
            return self._unresolved("import_unknown", lineno)
        if scope.is_local(name):
            typed = scope.var_type(name)
            if typed is not None:
                info = self.index.class_of(self.module.name, typed[0])
                if info is not None:
                    return self._repo(
                        "local_class", (info.module, info.name, self.module.rel, info.lineno),
                        lineno,
                    )
            return self._unresolved("local_callable", lineno)
        if name in self.module.defs:
            kind, def_line = self.module.defs[name]
            bucket = "local_class" if kind == "class" else "local_function"
            if kind == "assign":
                return self._unresolved("module_variable_callable", lineno)
            return self._repo(
                bucket, (self.module.name, name, self.module.rel, def_line), lineno
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

            typed = scope.var_type(value.id)
            if typed is not None:
                info = self.index.class_of(self.module.name, typed[0])
                if info is not None:
                    return self._from_class(
                        info, attr, lineno, "local_var_method", "local_var_attr_missing",
                        origin=typed[1],
                    )

            binding = scope.binding(value.id)
            if binding is not None:
                return self._through_binding(binding, attr, lineno)

            if scope.is_local(value.id):
                return self._unresolved("untyped_local_receiver", lineno)

            if value.id in self.module.defs:
                kind, _ = self.module.defs[value.id]
                if kind == "class":
                    info = self.module.classes.get(value.id)
                    if info is not None:
                        return self._from_class(
                            info, attr, lineno, "repo_class_attr", "repo_class_attr_missing"
                        )
                return self._unresolved("module_variable_receiver", lineno)

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
            if enclosing is not None:
                kind, payload = self.index.lookup_attribute(enclosing, value.attr)
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
            binding = scope.binding(head)
            if binding is not None:
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
        found, payload = self.index.lookup_attribute(info, attr)
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
            found, payload = self.index.lookup_attribute(base, attr)
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


def resolve_module(index: ProjectIndex, module: ModuleInfo) -> list[tuple[ast.Call, Resolution]]:
    return CallResolver(index, module).run()


def resolve_tree(root: Path, packages: tuple[str, ...] | None = None):
    """Convenience: index ``root`` and resolve every module.  Yields (module, results)."""
    from s01_index import DEFAULT_PACKAGES, build_index

    index = build_index(root, packages or DEFAULT_PACKAGES)
    for module in index.modules.values():
        yield module, resolve_module(index, module)
