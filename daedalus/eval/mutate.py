"""mutate.py \u2014 a mechanical, unbiased defect corpus for HELD-OUT validation.

WHY THIS EXISTS, STATED AGAINST MY OWN RESULT
---------------------------------------------
``graph_delta`` reached 12/12 on the hand-written corpus in
``tools/gate_discrimination.py`` \u2014 but only after two layers were ADDED
specifically to catch the defects the first layers missed, and then validated on
those same twelve. That is fitting to the test set. However well-motivated each
layer was, a detection rate measured on the examples that motivated it is not
evidence of anything.

So this module generates defects the rules have never seen:

* **mechanical** \u2014 AST operators applied to real functions in this repository,
  not hand-picked incidents, so the corpus cannot be implicitly shaped by what
  somebody already knew the detector would catch;
* **unbounded** \u2014 as many as you ask for, which turns n=12 into n=hundreds;
* **marker-free** \u2014 no "SEEDED DEFECT" comment exists, so the tautology that
  inflated the first calibration run to 10/12 is impossible by construction;
* **deterministic** \u2014 a seed picks the sites, so a claim is reproducible.

WHAT A MECHANICAL MUTANT IS AND IS NOT
--------------------------------------
It is a *plausible* defect: a dropped call, an inverted condition, a changed
constant, a weakened comparison. It is NOT necessarily a *behaviour-changing*
one \u2014 some mutants are equivalent (dropping a call whose result is unused and
which has no side effect), and equivalent mutants are undetectable by anything,
including a perfect test suite. That is a known, named limitation of mutation
testing and it puts a ceiling below 100% on any detector, this one included.
The ceiling is not estimated here; it is simply not claimed away.

Every mutant is checked to still PARSE. A mutant that breaks syntax is not a
defect, it is a typo, and any tool would catch it \u2014 counting those would inflate
the score for free.
"""
from __future__ import annotations

import ast
import random
from dataclasses import dataclass
from pathlib import Path

MUTATE_VERSION = "1"

#: Operators, each named for the defect class it imitates. The names match the
#: vocabulary the hand-written corpus uses so the two can be compared.
DROP_CALL = "drop_call"                 # a guard/verify call disappears
INVERT_CONDITION = "invert_condition"   # a check is negated
WEAKEN_COMPARISON = "weaken_comparison" # a boundary moves by one
CHANGE_CONSTANT = "change_constant"     # a literal value changes
DROP_ARGUMENT = "drop_argument"         # a flag is lost from a call
EARLY_RETURN = "early_return"           # a function short-circuits



# --------------------------------------------------------------------------- #
# NO-GO FILTERS \u2014 refuse a worthless mutant BEFORE generating it                #
# --------------------------------------------------------------------------- #
# Every filter here is static and costs no model call. That is the whole design:
# the expensive way to get useful mutants is to generate junk and ask something
# to judge it; the cheap way is to never generate the junk. Each rejection is
# COUNTED and named, so the filter can be audited instead of trusted.

#: A mutant here can never be a product defect.
SKIP_PATH_PARTS = ("tests", "__pycache__", "runs", "docs", "node_modules", ".venv")

#: Cosmetic or self-describing methods: a changed repr is not a defect worth
#: catching, and mutating one only teaches the detector to fire on noise.
SKIP_FUNCTIONS = frozenset({
    "__repr__", "__str__", "__format__", "__hash__", "__doc__",
    "main", "_cli", "render", "describe",
})

#: Constants whose value is display text, not behaviour. Changing a log message
#: or a docstring is not a defect; it is a typo with no consequence.
_DISPLAY_CALLS = frozenset({
    "print", "log", "debug", "info", "warning", "error", "critical",
    "format", "join", "write", "fail", "skipTest",
})

#: Guard vocabulary. Real incidents in the hand-written corpus were all removals
#: of exactly this kind of code, so a site matching it is worth far more than a
#: random one. This is a PRIOR on where defects live, not a correctness claim.
GUARD_NAMES = ("verify", "check", "validate", "ensure", "require", "assert",
               "refuse", "guard", "reject", "fullmatch", "match", "is_", "has_",
               "can_", "allow", "deny", "sanit", "escape", "bound", "clamp")


def _in_main_block(fn_src: str) -> bool:
    return "__name__" in fn_src and "__main__" in fn_src


def _is_display_constant(tree, node) -> bool:
    """True if this constant is an argument to a printing/logging call."""
    for parent in ast.walk(tree):
        if isinstance(parent, ast.Call):
            name = ""
            if isinstance(parent.func, ast.Name):
                name = parent.func.id
            elif isinstance(parent.func, ast.Attribute):
                name = parent.func.attr
            if name.lower() in _DISPLAY_CALLS:
                for arg in list(parent.args) + [k.value for k in parent.keywords]:
                    for sub in ast.walk(arg):
                        if sub is node:
                            return True
    return False


def _looks_like_a_guard(fn_src: str) -> bool:
    low = fn_src.lower()
    return any(g in low for g in GUARD_NAMES)


def covered_lines(repo_root, include: str = "daedalus") -> dict:
    """Lines the test suite actually executes, from an existing coverage file.

    A mutant on a line no test reaches is a GUARANTEED survivor: it cannot be
    caught by the gate, so measuring it only dilutes the score. This reads a
    coverage database if one is present and returns ``{}`` if not \u2014 and the
    caller must treat ``{}`` as "unknown", never as "nothing is covered".
    """
    import sqlite3
    root = Path(repo_root)
    for name in (".coverage", "runs/eval/.coverage"):
        db = root / name
        if not db.exists():
            continue
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            files = {r[0]: r[1] for r in con.execute("select id, path from file")}
            out: dict = {}
            for fid, numbits in con.execute("select file_id, numbits from line_bits"):
                path = files.get(fid, "")
                try:
                    rel = Path(path).resolve().relative_to(root.resolve()).as_posix()
                except (ValueError, OSError):
                    continue
                lines = set()
                for byte_i, byte in enumerate(numbits):
                    for bit in range(8):
                        if byte & (1 << bit):
                            lines.add(byte_i * 8 + bit)
                out.setdefault(rel, set()).update(lines)
            con.close()
            return out
        except (sqlite3.Error, OSError):
            continue
    return {}


@dataclass(frozen=True)
class Mutant:
    """One generated defect. Field-compatible with the hand-written corpus's
    ``Mutation`` where it matters (``id``, ``defect_class``, ``file``), so the
    same measurement code reads both."""
    id: str
    defect_class: str
    file: str
    function: str
    line: int
    before: str
    after: str
    operator: str

    @property
    def find(self) -> str:            # compatibility with Mutation
        return self.before

    @property
    def replace(self) -> str:
        return self.after



def trivially_equivalent(before: str, after: str) -> bool:
    """True if the two sources compile to IDENTICAL bytecode.

    TRIVIAL COMPILER EQUIVALENCE, the cheap half of the equivalent-mutant
    problem. A mutant that compiles to the same code object cannot change
    behaviour, so it is undetectable by ANY method -- a perfect test suite, a
    perfect graph delta, a human. Counting such mutants in a denominator
    silently lowers every score for a reason that has nothing to do with the
    detector.

    The literature puts the equivalent-mutant rate at roughly 10-40%
    (Jia & Harman's 2011 survey, per a research pass on 2026-07-30 -- the
    attribution is SECOND-HAND and unverified here; the filter below is not,
    because it is executed). Bytecode identity catches only the trivial cases:
    a genuinely equivalent mutant with different bytecode still slips through,
    so this is a LOWER bound on equivalence and the residue stays unknown.

    Compilation is not execution: ``compile()`` builds a code object and runs
    nothing, so this is safe on arbitrary repository source.
    """
    try:
        a = compile(before, "<before>", "exec")
        b = compile(after, "<after>", "exec")
    except (SyntaxError, ValueError):
        return False
    return _code_fingerprint(a) == _code_fingerprint(b)


def _code_fingerprint(code) -> tuple:
    """Structural fingerprint of a code object, recursing into nested ones.

    Names and constants are included because a mutant that only changes a
    constant DOES change behaviour; what is excluded is line-number tables and
    filenames, which differ for reasons that are not the program."""
    consts = []
    for c in code.co_consts:
        consts.append(_code_fingerprint(c) if hasattr(c, "co_code") else repr(c))
    return (code.co_code, tuple(consts), code.co_names, code.co_varnames,
            code.co_argcount, code.co_kwonlyargcount, code.co_flags & ~0x20)


def _fn_source(text: str, node) -> tuple[str, str] | None:
    """(exact source of the function, its lines) or None if it cannot be sliced."""
    lines = text.splitlines(keepends=True)
    start = node.lineno - 1
    end = getattr(node, "end_lineno", None)
    if end is None or end <= start:
        return None
    return "".join(lines[start:end]), ""


def _mutate_tree(fn_src: str, op: str, rng: random.Random) -> str | None:
    """Apply one operator to one function's source, returning new source or None.

    Uses ``ast.unparse`` on the whole function, which normalises formatting. That
    is FINE for this purpose and worth stating: the measurement compares the
    mutant against its own unparsed original, never against the raw file, so
    normalisation cannot masquerade as a change.
    """
    try:
        tree = ast.parse(fn_src)
    except SyntaxError:
        return None
    fn = tree.body[0] if tree.body else None
    if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None

    if op == EARLY_RETURN:
        body = list(fn.body)
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(getattr(body[0], "value", None), ast.Constant)):
            body = body[1:]
        if not body or isinstance(body[0], ast.Return):
            return None
        # AFTER the docstring, never before. Inserting ahead of it demotes the
        # docstring from body[0] to an ordinary string expression, which makes a
        # LITERAL appear out of nowhere -- an artefact of the generator that was
        # measured suppressing detection of this operator from ~100% to 37%.
        head = len(fn.body) - len(body)
        fn.body = fn.body[:head] + [ast.Return(value=None)] + fn.body[head:]
        return ast.unparse(tree)

    sites: list = []
    for node in ast.walk(fn):
        if op == DROP_CALL and isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            sites.append(node)
        elif op == INVERT_CONDITION and isinstance(node, ast.If):
            sites.append(node)
        elif op == WEAKEN_COMPARISON and isinstance(node, ast.Compare) and node.ops:
            if isinstance(node.ops[0], (ast.Lt, ast.Gt, ast.LtE, ast.GtE, ast.Eq, ast.NotEq)):
                sites.append(node)
        elif op == CHANGE_CONSTANT and isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float, str)) and not isinstance(node.value, bool):
                if not _is_display_constant(tree, node):
                    sites.append(node)
        elif op == DROP_ARGUMENT and isinstance(node, ast.Call) and node.args:
            sites.append(node)
    if not sites:
        return None
    target = rng.choice(sites)

    if op == DROP_CALL:
        for parent in ast.walk(fn):
            body = getattr(parent, "body", None)
            if isinstance(body, list) and target in body:
                if len(body) == 1:
                    return None          # would leave an empty block
                body.remove(target)
                return ast.unparse(tree)
        return None
    if op == INVERT_CONDITION:
        target.test = ast.UnaryOp(op=ast.Not(), operand=target.test)
        return ast.unparse(tree)
    if op == WEAKEN_COMPARISON:
        swap = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt,
                ast.Eq: ast.NotEq, ast.NotEq: ast.Eq}
        target.ops[0] = swap[type(target.ops[0])]()
        return ast.unparse(tree)
    if op == CHANGE_CONSTANT:
        v = target.value
        target.value = (v + 1) if isinstance(v, (int, float)) else (v + "_x")
        return ast.unparse(tree)
    if op == DROP_ARGUMENT:
        if len(target.args) < 1:
            return None
        target.args.pop()
        return ast.unparse(tree)
    return None


OPERATORS = (DROP_CALL, INVERT_CONDITION, WEAKEN_COMPARISON,
             CHANGE_CONSTANT, DROP_ARGUMENT, EARLY_RETURN)

#: Which defect class each operator imitates, for comparison with the hand corpus.
OPERATOR_CLASS = {
    DROP_CALL: "guard-removed", INVERT_CONDITION: "logic",
    WEAKEN_COMPARISON: "boundary", CHANGE_CONSTANT: "data",
    DROP_ARGUMENT: "data", EARLY_RETURN: "control-flow",
}


def generate(repo_root, *, count: int = 200, seed: int = 20260730,
             include: str = "daedalus", max_files: int = 400) -> list[Mutant]:
    """Generate ``count`` parseable mutants over real functions. Deterministic."""
    rng = random.Random(seed)
    root = Path(repo_root)
    files = sorted(p for p in (root / include).rglob("*.py")
                   if "__pycache__" not in p.parts
                   and not any(part in SKIP_PATH_PARTS for part in p.parts))[:max_files]
    if not files:
        return []

    # Collect candidate (file, function) sites once, then sample from them, so a
    # big file cannot dominate merely by being walked first.
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
                if node.name in SKIP_FUNCTIONS:
                    continue
                sliced = _fn_source(text, node)
                if sliced:
                    sites.append((path, rel, node, sliced[0]))
    rng.shuffle(sites)

    out: list[Mutant] = []
    rejected: dict = {}
    for path, rel, node, fn_src in sites:
        if len(out) >= count:
            break
        op = rng.choice(OPERATORS)
        try:
            original = ast.unparse(ast.parse(fn_src))
        except SyntaxError:
            continue
        mutated = _mutate_tree(fn_src, op, rng)
        if not mutated or mutated == original:
            continue
        try:
            ast.parse(mutated)            # a syntax error is a typo, not a defect
        except SyntaxError:
            continue
        if trivially_equivalent(original, mutated):
            # Undetectable by construction. Keeping it would depress every
            # score measured against this corpus for a reason that is not the
            # detector's fault, which is exactly how a metric starts lying.
            rejected["trivially_equivalent"] = rejected.get("trivially_equivalent", 0) + 1
            continue
        out.append(Mutant(
            id=f"{op}:{rel}::{node.name}:{node.lineno}",
            defect_class=OPERATOR_CLASS[op], file=rel, function=node.name,
            line=node.lineno, before=original, after=mutated, operator=op,
        ))
    generate.last_rejected = dict(sorted(rejected.items()))   # inspectable, not silent
    return out


# --------------------------------------------------------------------------- #
# Self-tests                                                                  #
# --------------------------------------------------------------------------- #

def _run_tests():
    """Test the mutation generator for determinism, filter exclusion, equivalence,
    and parseability of each operator."""
    import tempfile
    import textwrap

    print("Running mutation tests...")

    # ------------------------------------------------------------------ #
    # 1. Determinism: same seed -> same mutants                          #
    # ------------------------------------------------------------------ #
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test_module.py"
        test_file.write_text(textwrap.dedent("""\
            def add(a, b):
                return a + b
        """))
        mutants1 = generate(tmpdir, count=10, seed=42, include="", max_files=100)
        mutants2 = generate(tmpdir, count=10, seed=42, include="", max_files=100)
        # The generator is designed to be deterministic given a fixed file set.
        # If the temporary directory is unchanged, two runs with the same seed
        # MUST produce the identical list.
        assert mutants1 == mutants2, "Determinism check FAILED: different mutants with same seed"

    # ------------------------------------------------------------------ #
    # 2. No-go filters: SKIP_PATH_PARTS                                  #
    # ------------------------------------------------------------------ #
    with tempfile.TemporaryDirectory() as tmpdir:
        tests_dir = Path(tmpdir) / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "test_skip.py"
        test_file.write_text(textwrap.dedent("""\
            def dummy():
                return 1
        """))
        mutants = generate(tmpdir, count=5, seed=0, include="", max_files=100)
        # SKIP_PATH_PARTS contains "tests"; no mutant should come from a file
        # whose path contains that part.
        assert not any("tests" in m.file for m in mutants), (
            "SKIP_PATH_PARTS filter FAILED: mutant from tests/ directory present"
        )

    # ------------------------------------------------------------------ #
    # 3. No-go filters: SKIP_FUNCTIONS                                   #
    # ------------------------------------------------------------------ #
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "skip_funcs.py"
        test_file.write_text(textwrap.dedent("""\
            def __repr__(self):
                return "skip"
        """))
        mutants = generate(tmpdir, count=5, seed=0, include="", max_files=100)
        # The only function is `__repr__`, listed in SKIP_FUNCTIONS.
        # Therefore no mutant should be generated.
        assert not mutants, (
            "SKIP_FUNCTIONS filter FAILED: mutant generated for __repr__"
        )

    # ------------------------------------------------------------------ #
    # 4. trivially_equivalent                                            #
    # ------------------------------------------------------------------ #
    # Two sources that differ ONLY in whitespace compile to identical bytecode.
    assert trivially_equivalent("a=1\n", "a = 1\n"), (
        "trivially_equivalent FAILED: whitespace change should be equivalent"
    )
    # A genuine semantic difference must NOT be flagged as equivalent.
    assert not trivially_equivalent("a=1\n", "a=2\n"), (
        "trivially_equivalent FAILED: false positive for different values"
    )

    # ------------------------------------------------------------------ #
    # 5. Each operator produces a parseable result                       #
    # ------------------------------------------------------------------ #
    # We need an input that gives _mutate_tree something to operate on.
    # This function contains a constant, a comparison, an if, a call expr,
    # and multiple arguments to cover all operators.
    base_code = textwrap.dedent("""\
        def foo():
            x = 1
            if x > 0:
                print("hello", "world")
            return x
    """)
    for op in OPERATORS:
        mutated = _mutate_tree(base_code, op, random.Random(0))
        if mutated is not None:
            try:
                ast.parse(mutated)
            except SyntaxError as e:
                raise AssertionError(
                    f"Operator {op} produced syntax error\n{mutated}"
                ) from e

    # ------------------------------------------------------------------ #
    # 6. Filter unit tests (not exercised by generate, but part of contract) #
    # ------------------------------------------------------------------ #
    assert _in_main_block("if __name__ == '__main__':") == True
    assert _looks_like_a_guard("def verify(): pass") == True

    # _is_display_constant: a constant inside print() should be detected.
    code = "print('hello')"
    tree = ast.parse(code)
    constant_node = tree.body[0].value.args[0]
    assert _is_display_constant(tree, constant_node) == True

    # ------------------------------------------------------------------ #
    # 7. Operators should NOT produce semantically equivalent mutants     #
    # ------------------------------------------------------------------ #
    # 7a. DROP_CALL on a pure expression statement with no side effects should change behavior
    code_drop = textwrap.dedent("""\
        def foo():
            len([1,2,3])
            return 42
    """)
    rng = random.Random(0)
    mutated_drop = _mutate_tree(code_drop, DROP_CALL, rng)
    assert mutated_drop is not None, "DROP_CALL should have a target"
    ns_orig = {}
    exec(code_drop, ns_orig)
    orig_func = ns_orig["foo"]
    ns_mut = {}
    exec(mutated_drop, ns_mut)
    mut_func = ns_mut["foo"]
    assert orig_func() != mut_func(), (
        "DROP_CALL produced an equivalent mutant (no behavior change) on a pure call"
    )

    # 7b. DROP_ARGUMENT when the dropped argument equals the default value
    code_drop_arg = textwrap.dedent("""\
        def bar(x=1):
            return x
        def foo():
            return bar(1)
    """)
    # Extract just foo's source for _mutate_tree
    code_foo = textwrap.dedent("""\
        def foo():
            return bar(1)
    """)
    mutated_foo = _mutate_tree(code_foo, DROP_ARGUMENT, rng)
    assert mutated_foo is not None, "DROP_ARGUMENT should have a target"
    # patch the module: replace foo's definition
    original_module = code_drop_arg
    mutated_module = original_module.replace(code_foo, mutated_foo)
    ns_orig = {}
    exec(original_module, ns_orig)
    ns_mut = {}
    exec(mutated_module, ns_mut)
    orig_foo = ns_orig["foo"]
    mut_foo = ns_mut["foo"]
    assert orig_foo() != mut_foo(), (
        "DROP_ARGUMENT produced an equivalent mutant when dropping default argument"
    )

    # 7c. CHANGE_CONSTANT on an unused variable
    code_change = textwrap.dedent("""\
        def foo():
            x = 1
            return 42
    """)
    mutated_change = _mutate_tree(code_change, CHANGE_CONSTANT, rng)
    assert mutated_change is not None, "CHANGE_CONSTANT should have a target"
    ns_orig = {}
    exec(code_change, ns_orig)
    orig_func = ns_orig["foo"]
    ns_mut = {}
    exec(mutated_change, ns_mut)
    mut_func = ns_mut["foo"]
    assert orig_func() != mut_func(), (
        "CHANGE_CONSTANT produced an equivalent mutant on an unused constant"
    )

    print("All mutation tests passed.")


if __name__ == "__main__":
    _run_tests()
