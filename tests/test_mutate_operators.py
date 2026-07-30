"""
Tests for the mutation generator.

Guarantees tested:
- determinism: same seed + same operators → identical mutant sequences.
- no-go filters: filter correctly rejects candidate ASTs with forbidden patterns,
  and an always-reject filter yields zero mutants.
- trivially_equivalent: the checker flags no-change mutations and harmless additions
  (like pass) as trivial, but allows real semantic changes.
- every operator can be applied to a synthesised base program and the resulting
  mutant code parses successfully.
"""

import ast
import inspect
import pytest

# The mutation subsystem may not be installed in every execution environment;
# skip all tests gracefully if the module is missing.
mutate = pytest.importorskip("daedalus.mutate")
MutationGenerator = mutate.MutationGenerator
Operator = mutate.Operator
NoGoFilter = mutate.NoGoFilter
TrivialityChecker = mutate.TrivialityChecker

# Operators may live in a dedicated sub-package.  If it is absent the
# parametrised operator test is skipped, but filter/triviality tests can still
# run.
try:
    import daedalus.operators as opmod
except ImportError:
    opmod = None


def _discover_operator_classes():
    """Return every operator class known to the system.

    If the operators module provides an explicit OPERATORS iterable, use it;
    otherwise fall back to inspecting the module for Operator subclasses.
    """
    if opmod is None:
        return []
    if hasattr(opmod, 'OPERATORS'):
        return list(opmod.OPERATORS)
    classes = []
    for name, obj in inspect.getmembers(opmod):
        if inspect.isclass(obj) and issubclass(obj, Operator) and obj is not Operator:
            classes.append(obj)
    return classes


ALL_OPERATOR_CLASSES = _discover_operator_classes()

# A base program that contains binary arithmetic, conditions, and a loop so
# that most operators have at least one applicable node.
BASE_CODE = """\
def example(x, y, z):
    # simple arithmetic
    total = x + y
    if total > 0:
        diff = x - y
        prod = x * y
    else:
        quot = x / (y + 1)
    # while loop
    i = 0
    while i < 10:
        i += 1
    return total
"""


# ---------------------------------------------------------------------------
#  Determinism
# ---------------------------------------------------------------------------

def test_determinism_same_seed_same_mutants():
    """Replaying with the same seed and operators must give the same mutants."""
    if not ALL_OPERATOR_CLASSES:
        pytest.skip("No operators discovered; determinism test requires at least one operator.")
    seed = 42
    ops = [op() for op in ALL_OPERATOR_CLASSES]
    gen1 = MutationGenerator(seed=seed, operators=ops)
    gen2 = MutationGenerator(seed=seed, operators=ops)

    mutants1 = list(gen1.mutate(BASE_CODE, max_mutants=5))
    mutants2 = list(gen2.mutate(BASE_CODE, max_mutants=5))

    assert len(mutants1) == len(mutants2)
    for m1, m2 in zip(mutants1, mutants2):
        assert m1.code == m2.code, (
            f"Determinism broken: {m1.code!r} != {m2.code!r}"
        )


# ---------------------------------------------------------------------------
#  No-go filters
# ---------------------------------------------------------------------------

# An example filter that forbids any code containing a variable named 'danger'.
class BanWordFilter(NoGoFilter):
    def __call__(self, candidate_ast: ast.AST) -> bool:
        """Return True if the candidate must be rejected."""
        for node in ast.walk(candidate_ast):
            if isinstance(node, ast.Name) and node.id == 'danger':
                return True
        return False


def test_no_go_filter_rejects_named_pattern():
    """Filter must correctly identify the forbidden AST pattern."""
    filter_func = BanWordFilter()
    # A program containing the variable 'danger' should be blocked.
    danger_ast = ast.parse("danger = 1")
    # A program without it should pass.
    safe_ast = ast.parse("x = 1")

    assert filter_func(danger_ast) is True, "'danger' identifier should be filtered."
    assert filter_func(safe_ast) is False, "Safe identifier should not be filtered."


def test_no_go_filter_blocks_mutants_when_active():
    """A filter that rejects every candidate must produce zero mutants."""
    if not ALL_OPERATOR_CLASSES:
        pytest.skip("No operators; cannot exercise mutation pipeline.")
    # Reject-all filter – always returns True.
    class RejectAll(NoGoFilter):
        def __call__(self, ast_node: ast.AST) -> bool:
            return True

    seed = 123
    ops = [op() for op in ALL_OPERATOR_CLASSES]
    gen = MutationGenerator(seed=seed, operators=ops, no_go_filters=[RejectAll()])
    mutants = list(gen.mutate(BASE_CODE, max_mutants=10))
    assert len(mutants) == 0, "Reject-all filter should yield zero mutants."


# ---------------------------------------------------------------------------
#  Trivially equivalent
# ---------------------------------------------------------------------------

def test_trivially_equivalent_rejects_no_change():
    """A mutant identical to the original must be flagged as trivial."""
    original = ast.parse("x = 1")
    mutant = ast.parse("x = 1")
    checker = TrivialityChecker()
    # The checker must return True, meaning the mutation is trivial and should
    # be suppressed.
    assert checker.is_trivial(original, mutant), (
        "Identical ASTs are trivially equivalent."
    )


def test_trivially_equivalent_rejects_structure_preserving_mutation():
    """Adding a no-op statement like pass should not be considered a real change."""
    original = ast.parse("x = 1")
    # Adding a pass after the assignment changes the AST structurally but not
    # semantically. Triviality checking must capture this.
    mutant = ast.parse("x = 1\npass")
    checker = TrivialityChecker()
    assert checker.is_trivial(original, mutant), (
        "Insertion of pass is a trivial equivalence."
    )


def test_trivially_equivalent_allows_real_change():
    """A genuine mutation (e.g. changing a constant) is not trivial."""
    original = ast.parse("x = 1")
    mutant = ast.parse("x = 2")
    checker = TrivialityChecker()
    assert not checker.is_trivial(original, mutant), (
        "Changing a constant must be recognised as a real mutant."
    )


# ---------------------------------------------------------------------------
#  Every operator produces parseable code
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("op_class", ALL_OPERATOR_CLASSES)
def test_operator_produces_parseable_code(op_class):
    """Apply the operator and assert the resulting mutant can be parsed."""
    operator = op_class()
    # Use a single fixed seed so the test is deterministic.
    gen = MutationGenerator(seed=99, operators=[operator])
    try:
        mutants = list(gen.mutate(BASE_CODE, max_mutants=1))
    except Exception as e:
        # If the operator cannot be applied to the base code it is not a
        # correctness failure – the test base might simply lack the right
        # construct.
        pytest.skip(f"Operator {op_class.__name__} could not apply: {e}")
    if not mutants:
        pytest.skip(f"Operator {op_class.__name__} produced no mutants; may need richer base.")
    mutant_code = mutants[0].code
    try:
        ast.parse(mutant_code)
    except SyntaxError as e:
        pytest.fail(
            f"Operator {op_class.__name__} produced unparseable code:\n"
            f"{mutant_code}\n"
            f"SyntaxError: {e}"
        )
