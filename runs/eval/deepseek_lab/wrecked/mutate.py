"""preserve.py \u2014 a mechanical, unbiased corpus of behavior-preserving transformations for HELD-OUT validation.

WHY THIS EXISTS
---------------
graph_delta was tuned on hand-written defects that it caught; a perfect score on that
set is fitting, not evidence.  To measure *specificity* (does the detector fire only on
true defects?) we need a corpus of GOOD patches \u2014 transformations that provably do
*not* change behaviour.  If the detector flags any of these it is a false positive.

This module is the mirror of ``mutate.py``:

* **deterministic** \u2014 a seed picks the sites, so claims are reproducible;
* **unbounded** \u2014 as many as you ask for;
* **marker-free** \u2014 no special comments exist that could give the game away;
* **mechanical** \u2014 transformations are applied to real functions in the repository,
  not hand-picked examples.

WHAT A PRESERVING TRANSFORMATION IS
-----------------------------------
A transformation that is **semantically equivalent** by construction: rename a local,
reorder independent statements, extract a constant, reformat.  Every transformation is
checked to still PARSE, but bytecode identity is NOT required because some (like rename)
produce different bytecode for the same behaviour.

TRANSFORMATIONS REJECTED AS NOT PROVABLY SAFE
---------------------------------------------
* **Reordering statements with side-effects** (e.g., function calls that may print or
  modify state).  We restrict reordering to two consecutive *simple* assignments whose
  right-hand sides are constants or variable names with no mutual dependency.
* **Renaming parameters or globals** \u2014 changes the interface and cannot be proven
  invisible to external code.
* **Dead-code elimination** \u2014 removing an unused statement might change timing or
  resource usage, which could be considered part of \u201cbehaviour\u201d in some contexts,
  and proving true deadness is notoriously hard.
* **Constant folding** (e.g., ``1+2`` \u2192 ``3``) \u2014 it is always detectable by
  bytecode identity and would therefore be trivially equivalent; it is not useful for
  evaluating a detector.
* **Code motion across control-flow boundaries** (moving a statement out of a loop) \u2014
  requires a full dependency analysis and is beyond the scope of a conservative,
  mechanical source.
"""
from __future__ import annotations

import ast
import random
from dataclasses import dataclass
from pathlib import Path

PRESERVE_VERSION = "1"

#: Named transformation operators, each preserving behaviour.
RENAME_LOCAL    = "rename_local"    # rename a local variable within its scope
REORDER_STMTS   = "reorder_stmts"   # swap two independent consecutive assignments
EXTRACT_CONSTANT = "extract_constant"  # pull a repeated literal into a named variable
REFORMAT        = "reformat"        # normalise formatting via ast.unparse


# --------------------------------------------------------------------------- #
# NO-GO FILTERS \u2014 refuse worthless sites before generating                    #
# --------------------------------------------------------------------------- #
# Every filter is static and costs no model call.

#: A mutant here can never be a product defect, nor a useful preserve test.
SKIP_PATH_PARTS = ("tests", "__pycache__", "runs", "docs", "node_modules", ".venv")

#: Functions where a transformation is of little interest (e.g., trivial accessors).
#: None of the transformations change behaviour, but some may not be applicable anyway.
SKIP_FUNCTIONS = frozenset({
    "__repr__", "__str__", "__format__", "__hash__", "__doc__",
    "main", "_cli", "render", "describe",
})


def _fn_source(text: str, node) -> tuple[str, str] | None:
    """(exact source of the function, its lines) or None if it cannot be sliced."""
    lines = text.splitlines(keepends=True)
    start = node.lineno - 1
    end = getattr(node, "end_lineno", None)
    if end is None or end <= start:
        return None
    return "".join(lines[start:end]), ""


def _unique_name(tree: ast.AST, prefix: str = "_prv") -> str:
    """Return a name not used anywhere in *tree*."""
    existing = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    i = 0
    while True:
        cand = f"{prefix}{i}"
        if cand not in existing:
            return cand
        i += 1


def _preserve_tree(fn_src: str, op: str, rng: random.Random) -> str | None:
    """Apply one preserving operator to a function\u2019s source, returning new source or None."""
    try:
        tree = ast.parse(fn_src)
    except SyntaxError:
        return None
    fn = tree.body[0] if tree.body else None
    if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None

    # Helper: walk the immediate scope of *node* (skipping nested functions/classes).
    def walk_immediate(node: ast.AST):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            yield child
            yield from walk_immediate(child)

    # --- RENAME_LOCAL --------------------------------------------------------
    if op == RENAME_LOCAL:
        params = {p.arg for p in fn.args.args + fn.args.posonlyargs + fn.args.kwonlyargs
                  if isinstance(p, ast.arg)}
        if fn.args.vararg:
            params.add(fn.args.vararg.arg)
        if fn.args.kwarg:
            params.add(fn.args.kwarg.arg)
        # Find a local variable: assigned in the immediate scope, not a parameter,
        # and not declared global/nonlocal.
        locals_ = set()
        global_nonlocal = set()
        for node in ast.walk(fn):
            if isinstance(node, (ast.Global, ast.Nonlocal)):
                global_nonlocal.update(node.names)
        for node in walk_immediate(fn):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                if node.id not in params and node.id not in global_nonlocal:
                    locals_.add(node.id)
        if not locals_:
            return None
        old_name = rng.choice(sorted(locals_))
        new_name = _unique_name(fn, prefix="_l")

        # Rename all occurrences in the immediate scope.
        class Renamer(ast.NodeTransformer):
            def visit_Name(self, node):
                if node.id == old_name:
                    return ast.Name(id=new_name, ctx=node.ctx)
                return node

            def visit_FunctionDef(self, node):
                # Do not descend into nested functions
                return node
            def visit_AsyncFunctionDef(self, node):
                return node
            def visit_ClassDef(self, node):
                return node

        # apply to the whole function node (but Renamer skips nested scopes)
        Renamer().visit(fn)
        return ast.unparse(tree)

    # --- REORDER_STMTS -------------------------------------------------------
    if op == REORDER_STMTS:
        # Collect candidate pairs: (parent_block, index1, stmt1, index2, stmt2)
        candidates = []
        # Recursive walk limited to function body
        def walk_blocks(node: ast.AST):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for child in ast.iter_child_nodes(node):
                    walk_blocks(child)
                return
            if isinstance(node, (ast.ClassDef,)):
                return
            body = getattr(node, "body", None)
            if isinstance(body, list) and len(body) >= 2:
                for i in range(len(body)-1):
                    s1, s2 = body[i], body[i+1]
                    # Both must be simple assignments (Assign or AnnAssign with a value)
                    # with Name targets and safe RHS.
                    if not isinstance(s1, (ast.Assign, ast.AnnAssign)):
                        continue
                    if not isinstance(s2, (ast.Assign, ast.AnnAssign)):
                        continue
                    t1 = s1.target if isinstance(s1, ast.Attribute) else s1.targets[0] if isinstance(s1, ast.Assign) else s1.target
                    t2 = s2.target if isinstance(s2, ast.Attribute) else s2.targets[0] if isinstance(s2, ast.Assign) else s2.target
                    if not isinstance(t1, ast.Name) or not isinstance(t2, ast.Name):
                        continue
                    if t1.id == t2.id:
                        continue
                    # RHS must be safe (only constants or Names not from the other assignment)
                    def safe_rhs(expr):
                        if isinstance(expr, ast.Constant):
                            return True
                        if isinstance(expr, ast.Name):
                            return True
                        return False
                    if not isinstance(s1, ast.AnnAssign) or s1.value is None:
                        v1 = s1.value if isinstance(s1, ast.Assign) else s1.value
                    else:
                        v1 = s1.value
                    if not isinstance(s2, ast.AnnAssign) or s2.value is None:
                        v2 = s2.value if isinstance(s2, ast.Assign) else s2.value
                    else:
                        v2 = s2.value
                    if not (v1 and v2):
                        continue
                    if not safe_rhs(v1) or not safe_rhs(v2):
                        continue
                    # No mutual dependency: names in RHS of one must not refer to target of other
                    used_by_s1 = {node.id for node in ast.walk(v1) if isinstance(node, ast.Name)}
                    used_by_s2 = {node.id for node in ast.walk(v2) if isinstance(node, ast.Name)}
                    if t1.id in used_by_s2 or t2.id in used_by_s1:
                        continue
                    candidates.append((node, i, s1, i+1, s2))
        walk_blocks(fn)
        if not candidates:
            return None
        parent, idx1, stmt1, idx2, stmt2 = rng.choice(candidates)
        parent.body[idx1], parent.body[idx2] = parent.body[idx2], parent.body[idx1]
        return ast.unparse(tree)

    # --- EXTRACT_CONSTANT ----------------------------------------------------
    if op == EXTRACT_CONSTANT:
        # Collect all constant nodes in immediate scope (skip nested scopes).
        const_counts = {}
        const_nodes = []
        for node in walk_immediate(fn):
            if isinstance(node, ast.Constant) and not isinstance(node.value, (type(...), type(None), bool)):
                # We treat identical values as same constant, regardless of type.
                key = repr(node.value)
                const_counts[key] = const_counts.get(key, 0) + 1
                const_nodes.append((key, node))
        # Pick a constant that appears at least twice.
        candidates = [k for k, c in const_counts.items() if c >= 2]
        if not candidates:
            return None
        chosen_key = rng.choice(candidates)
        # Find first occurrence to insert assignment before it.
        first_node = None
        for key, node in const_nodes:
            if key == chosen_key:
                first_node = node
                break
        if not first_node:
            return None
        # Create a unique variable name.
        var_name = _unique_name(fn, prefix="_c")
        new_assign = ast.Assign(targets=[ast.Name(id=var_name, ctx=ast.Store())],
                                value=ast.Constant(value=first_node.value))
        # Insert new_assign right before the first occurrence.
        inserted = False
        for parent in ast.walk(fn):
            for field, child in ast.iter_fields(parent):
                if field == "body" and isinstance(child, list):
                    for i, stmt in enumerate(child):
                        if stmt is first_node or any(stmt is n for n in ast.walk(stmt) if n is first_node):
                            child.insert(i, new_assign)
                            inserted = True
                            break
                    if inserted:
                        break
            if inserted:
                break
        if not inserted:
            return None
        # Replace all occurrences of the constant with the variable.
        replacements = 0
        class ConstantReplacer(ast.NodeTransformer):
            def visit_Constant(self, node):
                nonlocal replacements
                if repr(node.value) == chosen_key and not isinstance(node.value, (type(...), type(None), bool)):
                    replacements += 1
                    return ast.Name(id=var_name, ctx=ast.Load())
                return node
        ConstantReplacer().visit(fn)
        # Must have replaced at least the original occurrences (now maybe more if new ones inserted?)
        if replacements < 2:
            return None
        return ast.unparse(tree)

    # --- REFORMAT ------------------------------------------------------------
    if op == REFORMAT:
        new_src = ast.unparse(tree)
        # Only return if the formatting actually changes something.
        if new_src != fn_src:
            return new_src
        return None

    return None


OPERATORS = (RENAME_LOCAL, REORDER_STMTS, EXTRACT_CONSTANT, REFORMAT)

#: Descriptive label for each operator.
OPERATOR_LABEL = {
    RENAME_LOCAL: "rename_local",
    REORDER_STMTS: "reorder_stmts",
    EXTRACT_CONSTANT: "extract_constant",
    REFORMAT: "reformat",
}


@dataclass(frozen=True)
class Preserved:
    """One generated preserving transformation."""
    id: str
    transform_type: str          # operator label
    file: str
    function: str
    line: int
    before: str
    after: str
    operator: str


def generate(repo_root, *, count: int = 200, seed: int = 20260730,
             include: str = "daedalus", max_files: int = 400) -> list[Preserved]:
    """Generate *count* parseable, behavior-preserving patches. Deterministic."""
    rng = random.Random(seed)
    root = Path(repo_root)
    files = sorted(p for p in (root / include).rglob("*.py")
                   if "__pycache__" not in p.parts)[:max_files]
    if not files:
        return []

    # Collect candidate (file, function) sites once, then sample from them.
    sites: list[tuple[Path, str, object, str]] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text)
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        rel = path.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                sliced = _fn_source(text, node)
                if sliced:
                    sites.append((path, rel, node, sliced[0]))
    rng.shuffle(sites)

    out: list[Preserved] = []
    rejected: dict = {}
    for path, rel, node, fn_src in sites:
        if len(out) >= count:
            break
        op = rng.choice(OPERATORS)
        try:
            original = ast.unparse(ast.parse(fn_src))
        except SyntaxError:
            continue
        mutated = _preserve_tree(fn_src, op, rng)
        if not mutated or mutated == original:
            continue
        try:
            ast.parse(mutated)          # syntax error means our transformation is buggy
        except SyntaxError:
            continue
        out.append(Preserved(
            id=f"{op}:{rel}::{node.name}:{node.lineno}",
            transform_type=OPERATOR_LABEL[op],
            file=rel,
            function=node.name,
            line=node.lineno,
            before=original,
            after=mutated,
            operator=op,
        ))
    generate.last_rejected = dict(sorted(rejected.items()))
    return out
