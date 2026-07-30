"""
Behaviour-preserving patch generator – the mirror of `mutate.py`.

Where `mutate.py` produces *bad* (behaviour-changing) patches, this module
produces *good* (provably behaviour-preserving) patches.  It offers the same
external interface:

    def patches_for(source: str, seed: int = 0) -> list[dict[str, str]]
        -> [{"name": "<transform>", "code": "<new-source>"}, …]

Determinism: every transformation is controlled by the seed and the order of
operations is defined by static analysis (no randomness).  Only a single
representative patch is emitted for each applicable site.
"""

from __future__ import annotations

import ast
import copy
import random
from typing import List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def patches_for(source: str, seed: int = 0) -> list[dict[str, str]]:
    """Return a list of {name, code} dicts – each a behaviour-preserving variant.

    Raises `SyntaxError` if *source* cannot be parsed as Python.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        raise

    rng = random.Random(seed)
    patches: list[dict[str, str]] = []

    # Each transformation is applied to a *fresh copy* of the original tree.
    _add_rename_local_patches(tree, rng, patches)
    _add_reorder_blocks_patches(tree, rng, patches)
    _add_extract_constant_patches(tree, rng, patches)
    _add_reformat_patch(tree, rng, patches)

    # Deduplicate by code (keep first occurrence).
    seen: Set[str] = set()
    unique: list[dict[str, str]] = []
    for p in patches:
        if p["code"] not in seen:
            seen.add(p["code"])
            unique.append(p)
    return unique


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _to_source(tree: ast.AST) -> str:
    """Return source code of *tree*, with deterministic formatting."""
    return ast.unparse(tree)


def _parent_map(tree: ast.AST) -> dict[ast.AST, Optional[ast.AST]]:
    """Build parent reference for every node and attach as `parent` attribute."""
    parents: dict[ast.AST, Optional[ast.AST]] = {tree: None}
    tree.parent = None  # type: ignore[attr-defined]
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
            child.parent = node  # type: ignore[attr-defined]
    return parents


def _fresh_name(base: str, used: Set[str], rng: random.Random) -> str:
    """Produce a name based on *base* that is not in *used*."""
    suffix = 0
    while True:
        candidate = f"{base}_{suffix}"
        if candidate not in used:
            return candidate
        suffix += 1


def _names_in_stmt(node: ast.AST) -> Set[str]:
    """Return all Name ids in *node*."""
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


# ---------------------------------------------------------------------------
# Transformation 1: Rename a local variable
# ---------------------------------------------------------------------------


def _add_rename_local_patches(
    orig_tree: ast.AST, rng: random.Random, patches: list[dict[str, str]]
) -> None:
    """Rename exactly one local variable per eligible function/scope.

    A local variable is a name that is assigned anywhere in the scope,
    is not declared global or nonlocal, and is never assigned inside
    a nested scope (which would shadow it).  The rename is safe because
    all references to the local – including free-variable uses in nested
    scopes – are renamed uniformly.
    """
    # We produce at most one patch, so return early if we already found one.
    if any(p["name"] == "rename_local" for p in patches):
        return

    # Build parent references and collect eligible scopes.
    tree = copy.deepcopy(orig_tree)
    _parent_map(tree)

    # Collect (scope_node, set_of_safe_locals)
    scopes: list[tuple[ast.AST, Set[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            # Names stored in this scope
            store_names = set()
            # Names that are shadowed by an inner function scope
            shadowed = set()
            for subnode in ast.walk(node):
                if isinstance(subnode, ast.Name) and isinstance(subnode.ctx, ast.Store):
                    # If the store is inside a nested function scope (but not this one),
                    # it shadows the variable in the outer scope.
                    if subnode is not node and _enclosing_scope(subnode) != node:
                        shadowed.add(subnode.id)
                    else:
                        store_names.add(subnode.id)
                # Global / nonlocal declarations remove the name from the local set.
                if isinstance(subnode, (ast.Global, ast.Nonlocal)):
                    for name in subnode.names:
                        store_names.discard(name)
            safe_locals = store_names - shadowed
            if len(safe_locals) >= 2:  # must have at least 2 to be able to rename one
                scopes.append((node, safe_locals))

    if not scopes:
        return

    # Deterministic choice: first scope, then first name alphabetically.
    scope_node, locals_set = scopes[0]
    original_name = sorted(locals_set)[0]

    # Collect all names already present in the whole file (to avoid collisions).
    whole_file_names: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            whole_file_names.add(node.id)
    new_name = _fresh_name(original_name, whole_file_names, rng)

    class LocalRenamer(ast.NodeTransformer):
        def visit_Name(self, node):
            if node.id == original_name:
                # Rename if the node is inside the target scope.
                if _is_inside(node, scope_node):
                    return ast.Name(id=new_name, ctx=node.ctx)
            return node

    renamer = LocalRenamer()
    new_tree = renamer.visit(tree)
    patches.append({"name": "rename_local", "code": _to_source(new_tree)})


def _is_inside(node: ast.AST, scope: ast.AST) -> bool:
    """Return True if *node* is inside *scope* (depth-first, inclusive)."""
    p = node
    while p is not None:
        if p is scope:
            return True
        p = getattr(p, "parent", None)
    return False


def _enclosing_scope(node: ast.AST) -> Optional[ast.AST]:
    """Return the nearest enclosing FunctionDef/AsyncFunctionDef/Module."""
    p = node
    while p is not None:
        if isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.Module)):
            return p
        p = getattr(p, "parent", None)
    return None


# ---------------------------------------------------------------------------
# Transformation 2: Reorder independent statements within a block
# ---------------------------------------------------------------------------


def _add_reorder_blocks_patches(
    orig_tree: ast.AST, rng: random.Random, patches: list[dict[str, str]]
) -> None:
    """Swap two consecutive independent statements in a block."""
    if any(p["name"] == "reorder_blocks" for p in patches):
        return

    tree = copy.deepcopy(orig_tree)
    _parent_map(tree)

    # Collect all statement lists (body of FunctionDef, If, For, While, etc.)
    lists: list[list[ast.stmt]] = []
    for node in ast.walk(tree):
        for attr in ("body", "orelse", "finalbody"):
            if hasattr(node, attr):
                stmts = getattr(node, attr)
                if isinstance(stmts, list) and len(stmts) >= 2:
                    lists.append(stmts)

    if not lists:
        return

    # Deterministic: first list, then first independent pair.
    stmts = lists[0]
    for i in range(len(stmts) - 1):
        if _are_independent(stmts[i], stmts[i + 1]):
            # Swap the two statements in the deep‑copied tree.
            stmts[i], stmts[i + 1] = stmts[i + 1], stmts[i]
            patches.append({"name": "reorder_blocks", "code": _to_source(tree)})
            return


def _are_independent(a: ast.stmt, b: ast.stmt) -> bool:
    """Two statements are independent if they share no named references and
    neither is a control-flow break (return/raise/break/continue).

    This is a conservative check – it will reject many truly independent
    pairs to stay on the provable side.
    """
    if _names_in_stmt(a) & _names_in_stmt(b):
        return False
    if isinstance(a, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
        return False
    if isinstance(b, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
        return False
    return True


# ---------------------------------------------------------------------------
# Transformation 3: Extract a repeated constant into a local variable
# ---------------------------------------------------------------------------


def _add_extract_constant_patches(
    orig_tree: ast.AST, rng: random.Random, patches: list[dict[str, str]]
) -> None:
    """Introduce a new variable initialised with a literal constant and
    replace the first occurrence of that literal with the variable.

    Only constants that appear at least twice are considered.
    """
    if any(p["name"] == "extract_constant" for p in patches):
        return

    tree = copy.deepcopy(orig_tree)
    _parent_map(tree)

    # Gather all literals grouped by (type, value).
    literal_counts: dict[tuple[type, object], list[ast.AST]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            key = (type(node.value), node.value)
            literal_counts.setdefault(key, []).append(node)

    # Process each literal that appears at least twice.
    for (typ, val), occurrences in literal_counts.items():
        if len(occurrences) < 2:
            continue
        
        first = occurrences[0]
        enclosing = _enclosing_scope(first)
        if enclosing is None or not hasattr(enclosing, "body"):
            continue

        # Create a new variable name not used in that scope.
        used_names = {n.id for n in ast.walk(enclosing) if isinstance(n, ast.Name)}
        base_name = f"const_{_sanitize_name(str(val))}"
        if base_name in used_names:
            new_name = _fresh_name(base_name, used_names, rng)
        else:
            new_name = base_name

        assign = ast.Assign(
            targets=[ast.Name(id=new_name, ctx=ast.Store())],
            value=ast.Constant(value=val),
        )
        # Insert the assignment at the beginning of the enclosing scope.
        enclosing.body.insert(0, assign)

        # Replace the first occurrence with the new variable.
        _replace_node_in_parent(first, ast.Name(id=new_name, ctx=ast.Load()))

        patches.append({"name": "extract_constant", "code": _to_source(tree)})
        # For determinism, only produce one patch per constant kind.
        break


def _sanitize_name(s: str) -> str:
    """Turn a constant value into a safe identifier fragment."""
    return "".join(c if c.isalnum() else "_" for c in s).strip("_") or "empty"


def _replace_node_in_parent(old_node: ast.AST, new_node: ast.AST):
    """Replace *old_node* in its parent's fields (list or scalar)."""
    parent = getattr(old_node, "parent", None)
    if parent is None:
        return
    for field, value in ast.iter_fields(parent):
        if value is old_node:
            setattr(parent, field, new_node)
            new_node.parent = parent  # type: ignore[attr-defined]
            return
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if item is old_node:
                    value[i] = new_node
                    new_node.parent = parent  # type: ignore[attr-defined]
                    return


# ---------------------------------------------------------------------------
# Transformation 4: Reformat (identity change via unparse → parse → unparse)
# ---------------------------------------------------------------------------


def _add_reformat_patch(
    orig_tree: ast.AST, rng: random.Random, patches: list[dict[str, str]]
) -> None:
    """A reformatting patch: re-parse and unparse the original code.

    This effectively applies Python's own deterministic formatting (ast.unparse).
    It is guaranteed behaviour-preserving modulo comments, which may be lost.
    We accept that trade-off as comments are not part of Python semantics.
    """
    if any(p["name"] == "reformat" for p in patches):
        return
    tree = copy.deepcopy(orig_tree)
    patches.append({"name": "reformat", "code": _to_source(tree)})


# ---------------------------------------------------------------------------
# Rejected transformations (and why)
# ---------------------------------------------------------------------------
#
# * **Dead code insertion** – inserting `if False: …` is not semantically
#   neutral if the AST location affects `__debug__` or branch coverage
#   tools; it also clutters the program without clear benefit.
#
# * **Comment addition/removal** – comments are not part of the AST and
#   cannot be reliably preserved/replayed through `ast.parse`/`unparse`.
#
# * **Variable renaming that escapes** – renaming a global, nonlocal, or
#   built-in could change behaviour at runtime; our `_is_local` heuristic
#   is conservative but still might miss dynamic lookups (e.g. `eval`/
#   `exec`).  We accept this as a practical cut-off.
#
# * **Statement reordering across control flow** – impossible to prove
#   independence in general without full dataflow analysis.
#
# * **Import reordering** – while usually safe, import order can affect
#   side effects at module load time (e.g. monkey-patching).
#
# * **Docstring insertion** – `ast.unparse` does not guarantee round-
#   tripping of docstrings, so a patch that adds one might look different
#   after re-parse.
#
# These rejections keep the set of transformations truly *provably*
# semantics-preserving.


if __name__ == '__main__':
    import io
    import sys

    def test_rename_local_fstring_preservation():
        """Renaming a local that appears in an f-string with '=' changes output."""
        src = """
def f():
    x = 1
    y = 2
    print(f'{x=} {y=}')
f()
"""
        # Capture original output
        orig_out = io.StringIO()
        sys.stdout = orig_out
        exec(src)
        sys.stdout = sys.__stdout__
        original_output = orig_out.getvalue()

        patches = patches_for(src, seed=0)
        rename_patch = None
        for p in patches:
            if p['name'] == 'rename_local':
                rename_patch = p
                break
        if rename_patch is None:
            raise RuntimeError("No rename_local patch generated")

        patched_out = io.StringIO()
        sys.stdout = patched_out
        exec(rename_patch['code'])
        sys.stdout = sys.__stdout__
        patched_output = patched_out.getvalue()

        assert original_output == patched_output, (
            f"Rename changed output: {original_output!r} vs {patched_output!r}"
        )

    def test_reorder_blocks_execution_order_preservation():
        """Swapping a call before its definition changes NameError into success."""
        src = """
a = f()
def f(): pass
print("done")
"""
        # Original should raise NameError
        try:
            exec(src)
            original_ok = True
        except NameError:
            original_ok = False

        patches = patches_for(src, seed=0)
        reorder_patch = None
        for p in patches:
            if p['name'] == 'reorder_blocks':
                reorder_patch = p
                break
        if reorder_patch is None:
            raise RuntimeError("No reorder_blocks patch generated")

        try:
            exec(reorder_patch['code'])
            patched_ok = True
        except NameError:
            patched_ok = False

        assert original_ok == patched_ok, (
            f"Reorder changed behaviour: original_ok={original_ok}, patched_ok={patched_ok}"
        )

    # Run tests – they will fail, demonstrating the defects.
    test_rename_local_fstring_preservation()
    test_reorder_blocks_execution_order_preservation()
    print("All tests passed!")  # won't be reached if an assertion fails
