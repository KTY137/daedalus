"""Module-scope facade resolution for the two registry derivation instruments.

WHY THIS EXISTS
---------------
``tests/test_registry_new_doors.py`` derives a door's effect set by walking the
repository-local call graph, and ``tests/test_registry_retired_rows.py`` derives
the Ollama rollback closure by locating two named bodies. Both walks resolve a
dotted name to the *file that defines it*. The hierarchy refactor moved most
implementations one layer down and left the historical locators behind as
FACADES, so a name-based walk that stops at the historical locator now finds an
empty module and silently derives nothing.

That failure mode is not "a few missing witnesses". It is the derivation going
blind while still reporting a set, which makes the under-declaration direction
of both instruments pass by saying nothing. This module teaches the walk the
four constructs the refactor actually used, so the derivation follows the code
instead of the filename.

THE SIX CONSTRUCTS, AND WHAT EACH ONE MEANS FOR A LOOKUP
--------------------------------------------------------
1. WHOLE-MODULE ALIAS -- ``sys.modules[__name__] = _owner``
   (``daedalus/spine/ledger.py``, ``envelope.py``, ``durability.py``).
   The locator does not merely re-export the owner; it *is* the owner. Every
   attribute lookup, and every submodule path below it, belongs to the owner.

2. RE-EXPORT -- ``from ..runtimes.providers.contracts import Provider``
   (``daedalus/providers/base.py``, ``daedalus/limit_policy.py``).
   The locator binds a name that is defined elsewhere. A lookup of that ONE
   name hops; other names do not.

3. MODULE-CLASS FALLBACK -- ``_module = sys.modules[__name__]`` followed by
   ``_module.__class__ = _Facade``, where ``_Facade.__getattr__`` returns
   ``getattr(_owner, name)`` (``daedalus/spine/attempt.py``).
   Locally defined names win; everything else falls through to the owner. This
   is a partial facade and must be modelled as one -- treating it as a whole
   alias would silently attribute the local composition seams to the owner.

4. PEP 562 -- a module-level ``def __getattr__(name)`` that maps a name to an
   owner (``daedalus/spine/__init__.py``, the three kernel packages'
   ``_EXPORT_GROUPS`` table, ``daedalus/orchestration/__init__.py``'s
   single-owner guard, ``daedalus/structcore/__init__.py``'s inline tuple test).
   A per-name fallback, derived from the table the hook actually reads. A hook
   whose shape this reader cannot interpret contributes NOTHING and is reported
   through ``Facade.unreadable_hook`` so the blind spot stays counted.

5. INHERITED DOOR -- ``class TaskAttempt(_owner.TaskAttempt)`` whose method is
   one ``super().__init__(...)`` call, and ``self.method()`` where the method is
   defined on a base one module away (:meth:`Resolver.method`,
   :meth:`Resolver.bases`). The refactor left several registered doors as a thin
   subclass over the implementation owner; a walk that only looks in the module
   where the class is written stops at the wrapper.

6. INJECTED PORT -- a parameter whose ANNOTATION names the receiver's type
   (:meth:`Resolver.receivers`). ``evaluator_port.command_gate(...)`` binds no
   name a constructor could be read from, which is how three doors lost the
   gate child that justifies their PROCESS_CONTROL. A concrete annotation is the
   class itself; a ``Protocol`` expands to the repository-local classes that
   define its declared methods -- the same structural rule a type checker
   applies, restricted to the scanned packages so a test double cannot widen a
   production door.

What is still NOT resolved, deliberately: a callable with no type to read --
passed positionally into ``**kwargs``, pulled out of a dict, or returned by a
method. There the implementation genuinely is not named anywhere the walk can
see it, and guessing would be the widening these instruments exist to refuse.
The honest answers are a declared bridge or a binding the walk can see.

LAST WRITE WINS
---------------
Every table below is built by interpreting module-scope statements IN ORDER,
letting a later binding replace an earlier one, because that is what Python
does. An ``ast.walk`` over the whole tree does not: it sees a dead alias line
and a rebinding as equally true and takes whichever it happens to visit.

That is not a theoretical concern. The reader for these same constructs in the
parallel packet G1-HIER-13 failed security review twice, and six of the
constructs that flipped its gate were pure statement-order problems:

  * a dead alias line followed by a rebinding of the same name;
  * ``__class__`` retyped before the name was bound to this module at all;
  * a tuple assignment followed by a rebinding of one element;
  * a retype undone by a second ``__class__`` assignment;
  * a same-named, hook-less class shadowing the facade class;
  * ``def __getattr__`` followed by ``del __getattr__`` in one class body.

``tests/test_registry_facade_order.py`` plants a real effect behind each of
those six shapes and requires the reader to land on the owner Python would
land on -- asserting BOTH that the surviving owner's effect is derived and that
the dead line's is not, so a reader that simply gave up on the shape fails too.

FAIL CLOSED ON AN UNREADABLE OWNER
----------------------------------
:func:`resolve` raises :class:`FacadeResolutionError` when a facade names an
owner inside a scanned package that is not in the model set. A module drops out
of the model set when it cannot be parsed -- a three-byte UTF-8 BOM is enough --
and a hop that treats "I could not read the owner" as "the owner has no
effects" converts an unreadable file into silent acceptance of every row
downstream of it. The caller must let that exception reach the test runner.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any, Mapping

#: Packages the effect scanner models. A facade pointing at a module inside one
#: of these that is nevertheless absent from the model set is an UNREADABLE
#: owner, not an external dependency -- see the fail-closed note above.
SCANNED_ROOTS = ("daedalus", "tools", "runs")


_MODELS: dict[str, dict[str, Any]] = {}
_RESOLVERS: dict[str, "Resolver"] = {}


def models(root) -> dict[str, Any]:
    """``module name -> _ModuleModel`` for the scanned packages under ``root``.

    REFUSES an incomplete model set. ``_models`` drops any file it cannot parse
    and reports it as a ``scan.source_unreadable`` blocker; every module missing
    from the set is a hole the walk cannot see, and a hole the walk cannot see
    looks exactly like a function with no effects.

    The per-hop check in :meth:`Resolver._require` catches this only where a
    FACADE names the missing module. Measured on this tree: dropping
    ``daedalus.spine.cancel`` silently removed PROCESS_CONTROL from three doors
    and dropping ``daedalus.offload`` silently removed NETWORK_EGRESS, SECRETS
    and SPEND from two, because those are reached through ordinary imports, and
    an ordinary import of a missing ``daedalus.owner`` is absorbed by the
    modelled ``daedalus`` package rather than refused. So the refusal belongs
    here as well, where it covers every path into the walk rather than the
    subset that happens to run through a facade.

    Cached per root: both registry instruments need the same model set, and
    building it twice in one pytest session costs seconds for no new
    information.
    """
    key = str(root)
    if key not in _MODELS:
        from daedalus.spine.effect_boundary import _models

        built, findings = _models(root)
        unreadable = sorted(
            finding.subject
            for finding in findings
            if finding.code == "scan.source_unreadable"
        )
        if unreadable:
            raise FacadeResolutionError(
                "the model set is incomplete -- these sources could not be "
                f"parsed: {unreadable}. No effect below them can be derived, "
                "and reporting a smaller effect set instead would silently "
                "satisfy the under-declaration direction of both registry "
                "instruments for every door beneath them."
            )
        _MODELS[key] = {model.module: model for model in built}
    return _MODELS[key]


def resolver(root) -> "Resolver":
    """The shared :class:`Resolver` over :func:`models`."""
    key = str(root)
    if key not in _RESOLVERS:
        _RESOLVERS[key] = Resolver(models(root))
    return _RESOLVERS[key]


class FacadeResolutionError(RuntimeError):
    """A facade hop landed on an owner the model set cannot see.

    Raised rather than returned. A caller that catches this and continues has
    reintroduced exactly the fail-open hop this module exists to prevent.
    """


# --------------------------------------------------------------------------- #
# the module-scope interpreter                                                 #
# --------------------------------------------------------------------------- #
@dataclass
class Facade:
    """What a module forwards, and to whom.

    ``alias``     this module IS that module (construct 1);
    ``exports``   local name -> absolute dotted owner name (construct 2);
    ``fallback``  owner module for any name not defined locally (construct 3);
    ``lazy``      local name -> owner module, from a PEP 562 hook (construct 4).
    """

    alias: str | None = None
    exports: dict[str, str] = field(default_factory=dict)
    #: Export name -> the module the import statement NAMED, which must be
    #: readable before the export can be followed. Kept separately because the
    #: joined dotted name cannot be split back into module and attribute: a
    #: missing ``daedalus.owner`` is absorbed by the modelled ``daedalus``
    #: package as the remainder ``owner.sink``, and the hop then reports "no
    #: effects here" for a file nobody could read.
    export_owners: dict[str, str] = field(default_factory=dict)
    fallback: str | None = None
    lazy: dict[str, tuple[str, str]] = field(default_factory=dict)
    #: True when this module has a module-level ``__getattr__`` whose forwarding
    #: this reader could not interpret. The lookup then simply does not resolve;
    #: the flag exists so ``test_registry_new_doors`` can COUNT the unreadable
    #: hooks instead of letting them accumulate as silent blind spots.
    unreadable_hook: bool = False
    #: Names bound at module scope by something other than an import: a def, a
    #: class, or an assignment whose value is not a resolvable module/name
    #: reference. These SHADOW ``fallback`` and ``lazy``, because a locally
    #: defined name never reaches ``__getattr__``.
    local: set[str] = field(default_factory=set)


def _import_from_base(module: str, node: ast.ImportFrom) -> str:
    """Absolute package base for ``from . import x`` inside ``module``."""
    if module.endswith(".__init__"):
        package = module[: -len(".__init__")]
    else:
        package = module.rsplit(".", 1)[0] if "." in module else ""
    base = node.module or ""
    if not node.level:
        return base
    parts = package.split(".") if package else []
    if node.level > 1:
        parts = parts[: -(node.level - 1)] or []
    return ".".join([*parts, base]) if base else ".".join(parts)


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _is_self_module_expr(value: ast.AST, names: Mapping[str, str]) -> bool:
    """``sys.modules[__name__]`` -- however ``sys`` was spelled."""
    if not isinstance(value, ast.Subscript):
        return False
    if not (isinstance(value.slice, ast.Name) and value.slice.id == "__name__"):
        return False
    target = _dotted(value.value)
    if not target.endswith(".modules"):
        return False
    head = target.split(".")[0]
    return names.get(head, head) == "sys"


def _class_forwards_to(node: ast.ClassDef, names: Mapping[str, str]) -> str | None:
    """The module a ``__getattr__`` hook on this class forwards to, if any.

    The class body is interpreted IN ORDER so that a hook removed by a later
    ``del __getattr__`` is not credited, and a later redefinition of the hook
    replaces an earlier one.
    """
    if node.decorator_list:
        # A decorator can return anything -- a different class, one with the
        # hook stripped, or a non-class. Crediting the hook we can see would be
        # crediting a facade Python may not have. Over-credit is the direction
        # that attributes an effect to a module the lookup never reaches.
        return None
    hook: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for stmt in node.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if stmt.name == "__getattr__":
                hook = stmt
        elif isinstance(stmt, ast.Delete):
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "__getattr__":
                    hook = None
        elif isinstance(stmt, ast.Assign):
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "__getattr__":
                    # Rebound to something this reader cannot interpret.
                    hook = None
    if hook is None:
        return None
    return _getattr_forward_target(hook, names)


def _getattr_forward_target(
    hook: ast.FunctionDef | ast.AsyncFunctionDef, names: Mapping[str, str]
) -> str | None:
    """``return getattr(<bound module>, name)`` -> that module's dotted name."""
    for child in ast.walk(hook):
        if not isinstance(child, ast.Call):
            continue
        if _dotted(child.func) != "getattr" or not child.args:
            continue
        owner = _dotted(child.args[0])
        if not owner:
            continue
        head = owner.split(".")[0]
        return names.get(head, head) + owner[len(head) :]
    return None


def _lazy_table(
    hook: ast.FunctionDef | ast.AsyncFunctionDef,
    module_body: list[ast.stmt],
    module: str,
    names: Mapping[str, str],
) -> dict[str, tuple[str, str]]:
    """Local name -> (owner module, attribute) for a module-level PEP 562 hook.

    A PEP 562 hook is arbitrary Python, so this reader interprets the shapes the
    repository actually uses and DECLINES everything else. A hook it cannot read
    contributes nothing and is reported by
    :func:`unreadable_lazy_hooks`, so an unreadable facade is counted rather
    than silently treated as "this module exports nothing".

    Readable shapes:

    * a module-scope table consulted with ``_TABLE.get(name)`` / ``_TABLE[name]``
      whose values are either an owner-module string (``spine/__init__.py``) or
      a ``(module, attribute)`` pair (``daedalus/__init__.py``);
    * a single-owner hook -- ``if name not in <SET>: raise`` or
      ``if name != "x": raise`` followed by ``getattr(import_module(...), name)``
      -- where the owner is a string constant, an ``f"{__name__}.sub"`` template
      (``orchestration/__init__.py``), or a module-scope module binding;
    * ``if name in ("a", "b"): from . import mod`` (``structcore/__init__.py``).
    """
    scope = {
        stmt.targets[0].id: stmt.value
        for stmt in module_body
        if isinstance(stmt, ast.Assign)
        and len(stmt.targets) == 1
        and isinstance(stmt.targets[0], ast.Name)
    }
    scope.update(
        {
            stmt.target.id: stmt.value
            for stmt in module_body
            if isinstance(stmt, ast.AnnAssign)
            and isinstance(stmt.target, ast.Name)
            and stmt.value is not None
        }
    )

    out: dict[str, tuple[str, str]] = {}

    # Shape 1/2: a module-scope table the hook looks the name up in. The owner
    # it records is sometimes a full module path (``spine/__init__.py``) and
    # sometimes a submodule LEAF that the hook composes with the package it
    # lives in -- ``getattr(import_module(f"{__name__}.{owner}"), name)``, the
    # canonical kernel facade. Which one is a property of the hook, not of the
    # table, so it is read off the hook.
    prefix = _relative_owner_prefix(hook, module)
    for consulted in _consulted_tables(hook):
        table = _table_dict(scope.get(consulted), scope)
        for key, value in _string_dict(table).items():
            out[key] = (prefix + value, key)
        for key, pair in _pair_dict(table).items():
            out[key] = (prefix + pair[0], pair[1])

    # Shape 5: ``if name in (...)`` guarding a relative import.
    for branch in ast.walk(hook):
        if not isinstance(branch, ast.If):
            continue
        for key in _membership_names(branch.test, negated=False):
            for stmt in ast.walk(branch):
                if isinstance(stmt, ast.ImportFrom) and stmt.names:
                    base = _import_from_base(module, stmt)
                    owner = (
                        f"{base}.{stmt.names[0].name}" if base else stmt.names[0].name
                    )
                    out.setdefault(key, (owner, key))

    if out:
        return out

    # Shape 3/4: one owner module, guarded by the set of names it serves.
    owner = _single_owner_module(hook, module, scope, names)
    if owner is None:
        return {}
    served = _guarded_names(hook, scope)
    if served is None:
        return {}
    return {key: (owner, key) for key in served}


def _consulted_tables(hook: ast.AST) -> set[str]:
    """Module-scope names the hook subscripts or calls ``.get`` on."""
    found: set[str] = set()
    for node in ast.walk(hook):
        if isinstance(node, ast.Call):
            dotted = _dotted(node.func)
            if dotted.endswith(".get") and dotted.count(".") == 1:
                found.add(dotted.split(".")[0])
        elif isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
            found.add(node.value.id)
    return found


def _is_import_module(func: ast.AST) -> bool:
    """``import_module`` however it was aliased in.

    The kernel facades import it as ``_import_module``; matching the exact
    spelling silently skipped three of them and cost the whole kernel export
    table.
    """
    return _dotted(func).rsplit(".", 1)[-1].lstrip("_") == "import_module"


def _relative_owner_prefix(hook: ast.AST, module: str) -> str:
    """``"daedalus.kernel.policy."`` when the hook composes owner with __name__.

    Distinguishes ``import_module(owner)`` -- the table holds a full module path
    -- from ``import_module(f"{__name__}.{owner}")``, where it holds a leaf.
    Only a template of exactly ``__name__``, a literal ``.`` and one other
    substitution counts; anything else leaves the table's values alone.
    """
    package = module[: -len(".__init__")] if module.endswith(".__init__") else module
    for node in ast.walk(hook):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        if not _is_import_module(node.func):
            continue
        template = node.args[0]
        if not isinstance(template, ast.JoinedStr):
            continue
        substitutions = [
            piece for piece in template.values if isinstance(piece, ast.FormattedValue)
        ]
        literals = "".join(
            piece.value
            for piece in template.values
            if isinstance(piece, ast.Constant) and isinstance(piece.value, str)
        )
        if len(substitutions) != 2 or literals != ".":
            continue
        first = substitutions[0].value
        if isinstance(first, ast.Name) and first.id == "__name__":
            return package + "."
    return ""


def _table_dict(node: ast.AST | None, scope: Mapping[str, ast.AST]) -> ast.Dict | None:
    """The dict literal a table name is bound to, comprehensions expanded."""
    if isinstance(node, ast.Dict):
        return node
    if isinstance(node, ast.DictComp):
        return _grouped_comprehension(node, scope)
    return None


def _grouped_comprehension(
    node: ast.DictComp, scope: Mapping[str, ast.AST]
) -> ast.Dict | None:
    """``{name: owner for owner, names in GROUPS for name in names}`` -> a dict.

    The canonical kernel export table: a module-scope tuple of
    ``(owner, (name, ...))`` pairs flattened into name -> owner. Read rather
    than skipped because three kernel packages share it, and an export table
    this reader cannot see is a hop the derivation silently stops at.
    """
    if len(node.generators) != 2:
        return None
    outer, inner = node.generators
    if outer.ifs or inner.ifs:
        return None
    if not (
        isinstance(outer.target, ast.Tuple)
        and len(outer.target.elts) == 2
        and all(isinstance(element, ast.Name) for element in outer.target.elts)
        and isinstance(outer.iter, ast.Name)
        and isinstance(inner.target, ast.Name)
        and isinstance(inner.iter, ast.Name)
    ):
        return None
    owner_var, names_var = (element.id for element in outer.target.elts)
    if inner.iter.id != names_var:
        return None
    if not (
        isinstance(node.key, ast.Name)
        and node.key.id == inner.target.id
        and isinstance(node.value, ast.Name)
        and node.value.id == owner_var
    ):
        return None
    groups = scope.get(outer.iter.id)
    if not isinstance(groups, (ast.Tuple, ast.List)):
        return None
    keys: list[ast.expr] = []
    values: list[ast.expr] = []
    for pair in groups.elts:
        if not (isinstance(pair, ast.Tuple) and len(pair.elts) == 2):
            return None
        owner, members = pair.elts
        if not (isinstance(owner, ast.Constant) and isinstance(owner.value, str)):
            return None
        for member in _constant_elements(members):
            keys.append(member)
            values.append(owner)
    return ast.Dict(keys=keys, values=values)


def _string_dict(node: ast.Dict | None) -> dict[str, str]:
    """Flatten a str->str dict literal, including ``**{... for ...}`` spreads."""
    out: dict[str, str] = {}
    if node is None:
        return out
    for key, value in zip(node.keys, node.values):
        if key is None:  # ``**<expr>`` spread
            if isinstance(value, ast.Dict):
                out.update(_string_dict(value))
            elif isinstance(value, ast.DictComp):
                out.update(_string_dict_comp(value))
            continue
        if (
            isinstance(key, ast.Constant)
            and isinstance(key.value, str)
            and isinstance(value, ast.Constant)
            and isinstance(value.value, str)
        ):
            out[key.value] = value.value
    return out


def _pair_dict(node: ast.Dict | None) -> dict[str, tuple[str, str]]:
    """Flatten a ``str -> (module, attribute)`` dict literal."""
    out: dict[str, tuple[str, str]] = {}
    if node is None:
        return out
    for key, value in zip(node.keys, node.values):
        if key is None:
            if isinstance(value, ast.Dict):
                out.update(_pair_dict(value))
            continue
        if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
            continue
        if not (isinstance(value, ast.Tuple) and len(value.elts) == 2):
            continue
        owner, attribute = value.elts
        if (
            isinstance(owner, ast.Constant)
            and isinstance(owner.value, str)
            and isinstance(attribute, ast.Constant)
            and isinstance(attribute.value, str)
        ):
            out[key.value] = (owner.value, attribute.value)
    return out


def _string_dict_comp(node: ast.DictComp) -> dict[str, str]:
    """``{name: "owner" for name in ("a", "b")}`` with constant members only."""
    if (
        len(node.generators) != 1
        or not isinstance(node.key, ast.Name)
        or not isinstance(node.value, ast.Constant)
        or not isinstance(node.value.value, str)
    ):
        return {}
    generator = node.generators[0]
    if not (
        isinstance(generator.target, ast.Name)
        and generator.target.id == node.key.id
        and not generator.ifs
    ):
        return {}
    return {
        element.value: node.value.value
        for element in _constant_elements(generator.iter)
    }


def _constant_elements(node: ast.AST | None) -> list[ast.Constant]:
    if isinstance(node, ast.Call) and _dotted(node.func) in {
        "frozenset",
        "set",
        "tuple",
        "list",
        "sorted",
    }:
        return _constant_elements(node.args[0]) if node.args else []
    if not isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return []
    return [
        element
        for element in node.elts
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    ]


def _membership_names(test: ast.AST, *, negated: bool) -> list[str]:
    """``name in ("a", "b")`` (or ``not in``) -> ``["a", "b"]``."""
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return []
    wanted = ast.NotIn if negated else ast.In
    if not isinstance(test.ops[0], wanted):
        return []
    if not (isinstance(test.left, ast.Name) and test.left.id == "name"):
        return []
    return [element.value for element in _constant_elements(test.comparators[0])]


def _guarded_names(
    hook: ast.FunctionDef | ast.AsyncFunctionDef, scope: Mapping[str, ast.AST]
) -> list[str] | None:
    """The names a single-owner hook admits, read off its refusal guard.

    ``None`` means the guard could not be read. A hook whose admitted set is
    unknown must not be credited with a table, because that would attribute
    every unknown attribute of the module to the owner.
    """
    for node in ast.walk(hook):
        if not isinstance(node, ast.If):
            continue
        if not any(isinstance(stmt, ast.Raise) for stmt in ast.walk(node)):
            continue
        names = _membership_names(node.test, negated=True)
        if names:
            return names
        test = node.test
        if isinstance(test, ast.Compare) and len(test.ops) == 1:
            if (
                isinstance(test.ops[0], ast.NotIn)
                and isinstance(test.left, ast.Name)
                and test.left.id == "name"
                and isinstance(test.comparators[0], ast.Name)
            ):
                return [
                    element.value
                    for element in _constant_elements(
                        scope.get(test.comparators[0].id)
                    )
                ]
            if (
                isinstance(test.ops[0], ast.NotEq)
                and isinstance(test.left, ast.Name)
                and test.left.id == "name"
                and isinstance(test.comparators[0], ast.Constant)
                and isinstance(test.comparators[0].value, str)
            ):
                return [test.comparators[0].value]
    return None


def _single_owner_module(
    hook: ast.FunctionDef | ast.AsyncFunctionDef,
    module: str,
    scope: Mapping[str, ast.AST],
    names: Mapping[str, str],
) -> str | None:
    """The one module a single-owner hook forwards to, if there is exactly one."""
    owners: set[str] = set()
    for node in ast.walk(hook):
        if not isinstance(node, ast.Call):
            continue
        if not _is_import_module(node.func) or not node.args:
            continue
        target = _module_string(node.args[0], module, scope)
        if target is not None:
            owners.add(target)
    if not owners:
        target = _getattr_forward_target(hook, names)
        if target is not None:
            owners.add(target)
    return owners.pop() if len(owners) == 1 else None


def _module_string(
    node: ast.AST, module: str, scope: Mapping[str, ast.AST]
) -> str | None:
    """Evaluate a module-name expression: constant, ``__name__`` template, or binding."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return _module_string(scope[node.id], module, scope) if node.id in scope else None
    if isinstance(node, ast.JoinedStr):
        package = module[: -len(".__init__")] if module.endswith(".__init__") else module
        parts: list[str] = []
        for piece in node.values:
            if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                parts.append(piece.value)
            elif (
                isinstance(piece, ast.FormattedValue)
                and isinstance(piece.value, ast.Name)
                and piece.value.id == "__name__"
            ):
                parts.append(package)
            else:
                return None
        return "".join(parts)
    return None


def build_facade(module: str, tree: ast.Module) -> Facade:
    """Interpret ``tree``'s module-scope statements in order.

    Only statements at module TOP LEVEL are interpreted. A binding made
    conditionally (inside ``if``/``try``) is not credited as a facade hop,
    because which branch ran is exactly the thing a static reader does not
    know; the name simply stays unresolved and the walk reports a missing
    witness rather than inventing one.
    """
    names: dict[str, str] = {"__module__": module}
    classes: dict[str, ast.ClassDef] = {}
    self_module: set[str] = set()
    facade = Facade()
    hook: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    assigned_hook = False
    conditional = _conditionally_bound(tree.body)

    def bind(name: str, absolute: str | None, owner: str = "") -> None:
        facade.export_owners.pop(name, None)
        if name in conditional:
            # This name is also assigned by a module-scope ``if``/``for``/
            # ``try``, which this reader deliberately does not interpret --
            # which branch ran is exactly what a static reader does not know.
            # It must therefore DECLINE the name rather than keep the binding
            # it could see, because keeping it credits the dead line: a
            # ``from owner import x`` followed by ``if True: x = decoy`` would
            # otherwise resolve to the owner, an owner the lookup never
            # reaches. Declining under-derives, which fails loudly in the
            # painted-label direction; crediting over-derives, which invents
            # justification for a row.
            absolute = None
        if absolute is None:
            names.pop(name, None)
            facade.exports.pop(name, None)
            facade.local.add(name)
        else:
            names[name] = absolute
            facade.exports[name] = absolute
            facade.local.discard(name)
            if owner:
                facade.export_owners[name] = owner
        self_module.discard(name)
        classes.pop(name, None)

    def value_target(value: ast.AST) -> str | None:
        """The absolute dotted name ``value`` refers to, if it refers to one."""
        dotted = _dotted(value)
        if not dotted:
            return None
        head = dotted.split(".")[0]
        if head not in names:
            return None
        return names[head] + dotted[len(head) :]

    for stmt in tree.body:
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                if alias.asname:
                    bind(alias.asname, alias.name, alias.name)
                else:
                    head = alias.name.split(".")[0]
                    bind(head, head, head)
        elif isinstance(stmt, ast.ImportFrom):
            base = _import_from_base(module, stmt)
            for alias in stmt.names:
                if alias.name == "*":
                    continue
                bind(
                    alias.asname or alias.name,
                    f"{base}.{alias.name}" if base else alias.name,
                    base,
                )
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bind(stmt.name, None)
            if stmt.name == "__getattr__":
                hook, assigned_hook = stmt, False
        elif isinstance(stmt, ast.ClassDef):
            bind(stmt.name, None)
            classes[stmt.name] = stmt
        elif isinstance(stmt, ast.Delete):
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name):
                    names.pop(tgt.id, None)
                    facade.exports.pop(tgt.id, None)
                    facade.local.discard(tgt.id)
                    self_module.discard(tgt.id)
                    classes.pop(tgt.id, None)
                    if tgt.id == "__getattr__":
                        hook, assigned_hook = None, False
        elif isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            value = stmt.value
            targets = (
                stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            )
            for target in targets:
                for tgt, val in _pairs(target, value):
                    if isinstance(tgt, ast.Name):
                        if val is not None and _is_self_module_expr(val, names):
                            names.pop(tgt.id, None)
                            facade.exports.pop(tgt.id, None)
                            facade.local.add(tgt.id)
                            classes.pop(tgt.id, None)
                            self_module.add(tgt.id)
                        else:
                            bind(
                                tgt.id,
                                value_target(val) if val is not None else None,
                            )
                        if tgt.id == "__getattr__":
                            # Rebound to an expression, not a readable ``def``.
                            # There IS a hook; this reader just cannot read it,
                            # which is a counted blind spot, not an absence.
                            hook = None
                            assigned_hook = val is not None
                    elif (
                        isinstance(tgt, ast.Subscript)
                        and _is_self_module_expr(tgt, names)
                    ):
                        # construct 1: this module IS the assigned module.
                        facade.alias = value_target(val) if val is not None else None
                    elif (
                        isinstance(tgt, ast.Attribute)
                        and tgt.attr == "__class__"
                        and (
                            (
                                isinstance(tgt.value, ast.Name)
                                and tgt.value.id in self_module
                            )
                            or _is_self_module_expr(tgt.value, names)
                        )
                    ):
                        # construct 3: retype this module. Resolved against the
                        # class binding CURRENT AT THIS STATEMENT, so a later
                        # hook-less class of the same name does not retroact.
                        klass = classes.get(_dotted(val)) if val is not None else None
                        facade.fallback = (
                            _class_forwards_to(klass, names)
                            if klass is not None
                            else None
                        )

    if hook is not None:
        facade.lazy = _lazy_table(hook, tree.body, module, names)
    # A module-level ``__getattr__`` this reader did not turn into a table is
    # counted, and "did not turn into a table" includes the shapes where there
    # is no ``def`` to read at all -- ``__getattr__ = _make(...)``, or a ``def``
    # nested in a ``try:``. Those set ``hook`` to None, so keying the flag off
    # ``hook is not None`` made a facade invisible to the walk AND invisible to
    # the census that exists to count invisible facades. The flag is keyed off
    # the NAME being bound instead.
    if not facade.lazy and (
        hook is not None or assigned_hook or _binds_module_getattr(tree.body)
    ):
        facade.unreadable_hook = True
    return facade


def _conditionally_bound(body: list[ast.stmt]) -> set[str]:
    """Module-scope names bound inside an ``if``/``for``/``while``/``try``/``with``.

    This reader interprets module TOP-LEVEL statements in order and does not
    interpret conditional ones, because which branch ran is exactly what a
    static reader cannot know. That was fine while the two layers stayed
    separate and wrong the moment they met: a dead ``from owner import x``
    followed by ``if True: x = decoy`` left ``x`` bound to the owner in the
    ordered table, so the reader credited an owner the lookup never reaches.

    MEASURED 2026-09-02, before this: three shapes (``if``, ``for``,
    ``try``/``except``) each made the reader derive the dead owner's
    NETWORK_EGRESS where CPython binds the decoy and the answer is
    PROCESS_SPAWN. Naming these here turns that over-credit into a decline.

    Bodies of nested functions and classes are NOT descended into: those bind
    their own locals, not module-scope names.
    """
    found: set[str] = set()

    def scan(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                continue
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                found.add(child.id)
            elif isinstance(child, ast.alias):
                found.add(child.asname or child.name.split(".")[0])
            scan(child)

    for stmt in body:
        if isinstance(stmt, (ast.If, ast.For, ast.While, ast.Try, ast.With)):
            scan(stmt)
        elif isinstance(stmt, (ast.AsyncFor, ast.AsyncWith)):
            scan(stmt)
    return found


def _binds_module_getattr(body: list[ast.stmt]) -> bool:
    """Is ``__getattr__`` bound by a CONDITIONAL module-scope statement?

    Top-level ``def``/assignment/``del`` are handled by the ordered interpreter.
    This covers only what the interpreter deliberately does not read: a hook
    created inside ``if``/``try``/``for``/``while``/``with`` at module scope,
    which is still a hook at runtime. Bodies of nested functions and classes are
    NOT descended into -- a ``__getattr__`` on a class is a different mechanism,
    read by :func:`_class_forwards_to`, and counting it here would invent
    unreadable module facades that do not exist.
    """
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if not isinstance(stmt, (ast.If, ast.Try, ast.For, ast.While, ast.With)):
            continue
        for child in ast.walk(stmt):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if child.name == "__getattr__":
                    return True
            elif (
                isinstance(child, ast.Name)
                and isinstance(child.ctx, ast.Store)
                and child.id == "__getattr__"
            ):
                return True
    return False


def _pairs(target: ast.AST, value: ast.AST | None):
    """Positional (target, value) pairs, so a tuple assignment binds elementwise."""
    if isinstance(target, ast.Tuple):
        elements = (
            value.elts
            if isinstance(value, ast.Tuple) and len(value.elts) == len(target.elts)
            else [None] * len(target.elts)
        )
        for tgt, val in zip(target.elts, elements):
            yield from _pairs(tgt, val)
        return
    yield target, value


# --------------------------------------------------------------------------- #
# resolution                                                                   #
# --------------------------------------------------------------------------- #
class Resolver:
    """Resolve a dotted name to the module that really defines it."""

    def __init__(self, models: Mapping[str, Any]) -> None:
        self._models = models
        self._facades: dict[str, Facade] = {}
        self._implementations: dict[tuple[str, str], tuple[tuple[str, str], ...]] = {}

    def facade(self, module: str) -> Facade:
        if module not in self._facades:
            self._facades[module] = build_facade(module, self._models[module].tree)
        return self._facades[module]

    def aliases(self, module: str) -> dict[str, str]:
        """Module-scope names, with the ones a later statement killed removed.

        ``_ModuleModel.aliases`` collects imports with ``ast.walk``, which has
        no notion of statement order: an import a later assignment overwrote is
        recorded as though it were still live. The facade's tables are built by
        interpreting module-scope statements IN ORDER, so they are layered on
        top -- ``local`` drops the rebound names, ``exports`` supplies the
        survivors with relative imports resolved.
        """
        facade = self.facade(module)
        out = dict(self._models[module].aliases)
        for rebound in facade.local:
            out.pop(rebound, None)
        out.update(facade.exports)
        return out

    # -- inheritance ------------------------------------------------------ #
    def bases(self, module: str, klass: str) -> tuple[str, ...]:
        """Absolute dotted names of ``klass``'s declared bases.

        Recomputed from the tree with the order-safe alias table rather than
        read from ``_ModuleModel.class_bases``, which resolves its base names
        through the unordered alias map, and taking the LAST class statement of
        that name, which is the one Python leaves bound.
        """
        aliases = self.aliases(module)
        node: ast.ClassDef | None = None
        for stmt in self._models[module].tree.body:
            if isinstance(stmt, ast.ClassDef) and stmt.name == klass:
                node = stmt
        if node is None:
            return ()
        out: list[str] = []
        for base in node.bases:
            dotted = _dotted(base)
            if not dotted:
                continue
            head = dotted.split(".")[0]
            out.append(aliases.get(head, head) + dotted[len(head) :])
        return tuple(out)

    # -- injected ports --------------------------------------------------- #
    def protocol_methods(self, module: str, klass: str) -> frozenset[str] | None:
        """The methods a repository-local ``Protocol`` declares, or ``None``.

        ``None`` means "not a Protocol" -- an ordinary class annotation is
        resolved by :meth:`method` through its own body and bases, and must not
        be broadened into "every class shaped like this one".
        """
        if module not in self._models:
            return None
        node: ast.ClassDef | None = None
        for stmt in self._models[module].tree.body:
            if isinstance(stmt, ast.ClassDef) and stmt.name == klass:
                node = stmt
        if node is None:
            return None
        if not any(_dotted(base).split(".")[-1] == "Protocol" for base in node.bases):
            return None
        declared = frozenset(
            stmt.name
            for stmt in node.body
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not stmt.name.startswith("__")
        )
        return declared or None

    def implementations(self, module: str, klass: str) -> tuple[tuple[str, str], ...]:
        """Repository-local classes that satisfy the Protocol ``module.klass``.

        THE INJECTED-PORT HOP, and the only one this reader performs. When the
        kernel calls ``evaluator_port.command_gate(...)`` the receiver is a
        parameter, so no constructor binds it and the walk stops -- which is how
        ``cli.picker`` lost the gate child that justifies its PROCESS_CONTROL.

        The resolution is derived, not guessed: the parameter's ANNOTATION names
        a Protocol, the Protocol declares its method set, and a class that
        defines every one of those methods is an implementation of it. That is
        the same structural rule the type checker applies. Classes outside the
        scanned packages are not considered, so a test double cannot widen a
        production door's derived effect set.

        When more than one class satisfies the protocol every one of them is
        followed, because a lower-bound reachability walk may not pick a
        favourite; the painted-label direction stays honest because
        ``test_a_planted_effect_and_a_deleted_one_are_both_caught`` fails the
        moment the closure grows wide enough to justify an effect the door does
        not really have.

        THE LOOSENESS IS IN THE SINGLE-METHOD PROTOCOLS, and it is real:
        structural matching on one method name matches anything that has it.
        MEASURED 2026-09-02: 7 repository-local Protocols declare methods;
        ``AvailableProvider`` (one method, ``available``) expands to 5 classes
        and ``TransportSink`` (one method, ``publish``) to 4 -- one of which,
        ``ikarus_supervisor:StateLedger``, is not a transport sink by any
        reading. Every other Protocol expands to exactly one class or none.
        Neither loose one is consumed by any of the 14 registered row closures,
        so no row's declared effects rest on a loose match today. If one ever
        does, the honest fix is a nominal marker on the port, not a wider walk.
        """
        key = (module, klass)
        if key in self._implementations:
            return self._implementations[key]
        declared = self.protocol_methods(module, klass)
        if declared is None:
            self._implementations[key] = ()
            return ()
        probe = sorted(declared)[0]
        found: list[tuple[str, str]] = []
        for owner, model in self._models.items():
            for candidate in {
                name.split(".", 1)[0]
                for name in model.functions
                if name.endswith("." + probe)
            }:
                if (owner, candidate) == key:
                    continue
                if all(
                    self.method(owner, candidate, name) is not None
                    for name in declared
                ):
                    found.append((owner, candidate))
        self._implementations[key] = tuple(sorted(found))
        return self._implementations[key]

    def receivers(self, module: str, klass: str) -> tuple[tuple[str, str], ...]:
        """The classes a parameter annotated ``module.klass`` can actually be.

        A Protocol expands to its implementations; a CONCRETE class is simply
        itself. The concrete case is the more common one after the refactor and
        the more conservative -- ``run_mission(..., executor: WaveExecutor)``
        even refuses a subclass at runtime (``type(executor) is not
        WaveExecutor``), so following the annotation is reading the contract,
        not widening it.
        """
        if module not in self._models:
            return ()
        if self.protocol_methods(module, klass) is not None:
            return self.implementations(module, klass)
        if klass in self._models[module].class_bases:
            return ((module, klass),)
        return ()

    def method(
        self, module: str, klass: str, method: str
    ) -> tuple[str, str] | None:
        """``(module, "Cls.method")`` for ``method`` on ``klass`` or a base of it.

        The hierarchy refactor left several registered doors as a thin subclass
        over the implementation owner -- ``class TaskAttempt(_owner.TaskAttempt)``
        with an ``__init__`` that is one ``super().__init__(...)`` call. A walk
        that only looks for ``Cls.method`` in the module where ``Cls`` is
        written stops at the wrapper and derives nothing from the body that
        does the work.

        Only DECLARED bases that resolve to a repository-local class are
        followed, breadth-first, in declaration order -- close enough to the MRO
        for a lower-bound reachability walk, and refusing anything it cannot
        name.
        """
        queue: list[tuple[str, str]] = [(module, klass)]
        seen: set[tuple[str, str]] = set()
        while queue:
            owner_module, owner_class = queue.pop(0)
            if (owner_module, owner_class) in seen:
                continue
            seen.add((owner_module, owner_class))
            if owner_module not in self._models:
                continue
            qualname = f"{owner_class}.{method}"
            if qualname in self._models[owner_module].functions:
                return owner_module, qualname
            for base in self.bases(owner_module, owner_class):
                found = self.resolve(base)
                if found is None:
                    continue
                base_module, rest = found
                if rest and "." not in rest:
                    queue.append((base_module, rest))
        return None

    # -- modules ---------------------------------------------------------- #
    def _known(self, module: str) -> str | None:
        for candidate in (module, module + ".__init__"):
            if candidate in self._models:
                return candidate
        return None

    def _require(self, owner: str, why: str) -> str | None:
        """Canonical model name for ``owner``, or fail closed / decline.

        Declines (returns ``None``) for anything outside a scanned package --
        stdlib and third-party modules have no model and never did. RAISES for
        a scanned module with no model, because that means the source could not
        be parsed and the walk is about to under-report.
        """
        known = self._known(owner)
        if known is not None:
            return known
        if owner.split(".")[0] in SCANNED_ROOTS:
            raise FacadeResolutionError(
                f"{why} names {owner!r}, which is inside a scanned package but "
                "absent from the model set -- the source could not be parsed, "
                "so no effect below it can be derived. Treating this as 'no "
                "effects found' would silently accept every row downstream."
            )
        return None

    def module(self, dotted: str, _seen: frozenset[str] = frozenset()) -> str | None:
        """Canonical model name for a module path, following whole-module aliases."""
        known = self._known(dotted)
        if known is None:
            return None
        alias = self.facade(known).alias
        if alias is None or alias in _seen:
            return known
        target = self._require(alias, f"the module alias in {known}")
        if target is None:
            return known
        return self.module(alias, _seen | {known})

    # -- symbols ---------------------------------------------------------- #
    def split(self, absolute: str) -> tuple[str, str] | None:
        """``pkg.mod.Cls.meth`` -> (model name, ``Cls.meth``), longest module first."""
        parts = absolute.split(".")
        for cut in range(len(parts) - 1, 0, -1):
            module = self.module(".".join(parts[:cut]))
            if module is not None:
                return module, ".".join(parts[cut:])
        return None

    def resolve(self, absolute: str) -> tuple[str, str] | None:
        """Follow facades until ``absolute`` lands on the module that defines it.

        Returns ``(model module, remainder)``. The remainder is not guaranteed
        to be a function -- callers still decide what counts as a hit -- but the
        module is the furthest owner this reader can justify.

        Raises :class:`FacadeResolutionError` when a hop names an unreadable
        owner inside a scanned package.
        """
        seen: set[tuple[str, str]] = set()
        found = self.split(absolute)
        while found is not None and found not in seen:
            seen.add(found)
            module, rest = found
            if not rest:
                return found
            model = self._models[module]
            if rest in model.functions or f"{rest}.__init__" in model.functions:
                return found
            head, _, tail = rest.partition(".")
            if f"{head}.{rest.rsplit('.', 1)[-1]}" in model.functions:
                return found
            if head in model.class_bases:
                return found
            facade = self.facade(module)
            hop: str | None = None
            if head in facade.exports:
                # The module the import NAMED must be readable. Deriving it from
                # the joined dotted name instead does not work: ``split`` never
                # returns None for ``daedalus.owner.sink`` when ``daedalus`` is
                # a modelled package, because the parent absorbs the missing
                # module as the remainder ``owner.sink`` -- which is how this
                # hop silently swallowed an unparseable owner until it was
                # measured. ``export_owners`` keeps the module from the import
                # statement, so the check has something exact to ask about.
                self._require(
                    facade.export_owners.get(head, ""),
                    f"the re-export in {module}",
                )
                hop = facade.exports[head]
            elif head in facade.local:
                return found
            elif head in facade.lazy:
                lazy_module, lazy_attr = facade.lazy[head]
                owner = self._require(
                    lazy_module, f"the PEP 562 table in {module}"
                )
                hop = f"{lazy_module}.{lazy_attr}" if owner else None
            elif facade.fallback is not None:
                owner = self._require(
                    facade.fallback, f"the module-class facade in {module}"
                )
                hop = f"{facade.fallback}.{head}" if owner else None
            if hop is None:
                return found
            candidate = self.split(f"{hop}.{tail}" if tail else hop)
            if candidate is None:
                self._require(hop.rsplit(".", 1)[0], f"the re-export in {module}")
                return found
            found = candidate
        return found
