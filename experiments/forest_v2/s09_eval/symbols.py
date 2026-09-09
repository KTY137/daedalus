"""EXPERIMENT (forest_v2 / slice s09): symbols as retrievable units.

Read-only.  Pure stdlib.  No writes, no network, no subprocess, no model calls.

Why this exists
---------------
``taskset_xplane.py`` states the gap it did not close::

    Making the Type plane addressable needs gold whose unit is a *symbol* -- a
    (path, qualified name, revision) triple -- which needs a symbol-resolving
    extractor over the pre-image tree and a retriever contract whose candidates
    are symbols rather than files.  Both are out of scope here and neither is
    attempted.

This module is the extractor half.  It answers exactly two questions about one
Python source: which qualified names does it define, and are two versions of a
name the same.

Identity is STRUCTURAL
----------------------
Two symbols are the same when ``ast.dump`` of their subtree matches.  That
makes a reformat invisible and a docstring edit visible -- docstrings are AST
nodes, comments are not.  ``G2-SYMGOLD-01`` measured this choice against a
source-segment definition on ``black``, a repository that *is* a code
formatter and therefore the least favourable subject for the worry, and found
a 0.5% difference in case count (440 -> 438).  The stricter definition is used
here because a corpus whose gold moves when someone runs a formatter is not
frozen.

What it deliberately does not do
--------------------------------
No rename tracking.  A symbol renamed between the two images reads as one
deletion plus one creation, and since a created symbol is never gold (it does
not exist in the pre-image), a rename contributes a spurious deletion instead
of a match.  ``taskset_xplane`` rejects rename-dominated diffs at file level
for the same reason; at symbol level the problem is recorded rather than
solved, because solving it needs similarity matching that would put a
heuristic inside the gold set.

No cross-file movement.  A symbol moved from one module to another is likewise
a deletion and a creation.
"""
from __future__ import annotations

import ast
from typing import Dict


def symbol_table(source: str) -> Dict[str, str]:
    """Map every qualified name in ``source`` to its structural identity.

    Nested classes recurse, so ``Outer.Inner.method`` is addressable.  Functions
    do not recurse: a closure is an implementation detail of its enclosing
    symbol, not a separately retrievable unit, and admitting one would let a
    retriever score by finding a helper nobody would search for.

    An unparseable source yields an empty table rather than raising.  A file
    that does not parse has no symbols to retrieve, which is a fact about the
    corpus and not an error in reading it; the caller counts such files.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}

    out: Dict[str, str] = {}

    def walk(node: ast.AST, prefix: str) -> None:
        for item in getattr(node, "body", []):
            if not isinstance(
                item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                continue
            qualified = f"{prefix}{item.name}"
            out[qualified] = ast.dump(item)
            if isinstance(item, ast.ClassDef):
                walk(item, f"{qualified}.")

    walk(tree, "")
    return out


def carries_annotation(source: str, qualname: str) -> bool:
    """Whether ``qualname`` has any type annotation on it or inside it.

    This is what makes a symbol a Type-plane member: an annotated parameter, a
    declared return, or an annotated assignment in its body.  It is a syntactic
    test on declarations, not a resolution -- ``s02_types`` measured that the
    whole resolver machinery buys at most 2.37pp over exactly this control on
    real corpora, so the cheap test is used and the claim kept correspondingly
    narrow.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False

    target: ast.AST | None = None

    def find(node: ast.AST, prefix: str) -> None:
        nonlocal target
        for item in getattr(node, "body", []):
            if not isinstance(
                item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                continue
            qualified = f"{prefix}{item.name}"
            if qualified == qualname:
                target = item
                return
            if isinstance(item, ast.ClassDef):
                find(item, f"{qualified}.")
                if target is not None:
                    return

    find(tree, "")
    if target is None:
        return False

    for node in ast.walk(target):
        if isinstance(node, ast.AnnAssign):
            return True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.returns is not None:
                return True
            args = node.args
            for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
                if arg.annotation is not None:
                    return True
            if args.vararg is not None and args.vararg.annotation is not None:
                return True
            if args.kwarg is not None and args.kwarg.annotation is not None:
                return True
    return False


def changed_symbols(pre: str, post: str) -> Dict[str, str]:
    """Qualified names whose structure differs between the two images.

    The value is the change kind -- ``modified``, ``added`` or ``removed`` --
    so a caller can apply the pre-image rule without re-deriving it. Only
    ``modified`` and ``removed`` names exist in the pre-image and are therefore
    eligible to be gold; ``added`` is returned so it can be counted rather than
    silently discarded.
    """
    before, after = symbol_table(pre), symbol_table(post)
    out: Dict[str, str] = {}
    for name in set(before) | set(after):
        in_before, in_after = name in before, name in after
        if in_before and in_after:
            if before[name] != after[name]:
                out[name] = "modified"
        elif in_after:
            out[name] = "added"
        else:
            out[name] = "removed"
    return out


__all__ = ["symbol_table", "carries_annotation", "changed_symbols"]
