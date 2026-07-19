"""Regression — unbounded recursion in tree-sitter AST walks.

``parse._tree_sitter_units`` and ``imports._ts_import_nodes`` used to walk the
tree-sitter AST with a RECURSIVE ``visit()`` closure. On a real deeply-nested
file this raised ``RecursionError`` and killed the whole ``/api/structure``
scan (see daedalus/structcore/parse.py::_tree_sitter_units and
daedalus/structcore/imports.py::_ts_import_nodes, both now ITERATIVE
stack-based pre-order walks that push ``reversed(node.children)``).

Two fixtures, both proven (below) to blow a hand-rolled recursive walker over
the SAME parsed tree under Python's default 1000-frame recursion limit:

  * ``_NESTED_FUNCS`` — 2000 nested named function declarations. Exercises
    ``extract_units``/``extract_imports`` directly and checks pre-order
    (source-order) is preserved — the property the ``reversed()`` push
    protects.
  * ``_NESTED_IFS`` — one function with 1500 nested ``if`` blocks (a single
    CodeUnit). Used for the ``build_index`` end-to-end check so the expensive
    O(n^2) clone-comparison pass isn't run over 2000 near-identical units.
"""
import tempfile
import unittest
from pathlib import Path

from daedalus.structcore import build_index
from daedalus.structcore.imports import extract_imports
from daedalus.structcore.languages import spec_for
from daedalus.structcore.parse import (
    _parser_for,
    extract_units,
    tree_sitter_available,
)

FUNC_DEPTH = 2000  # deep enough to exceed Python's default recursion limit
IF_DEPTH = 1500    # ditto, for a fixture that yields a single CodeUnit


def _nested_funcs(depth: int) -> str:
    """``depth`` nested named function declarations, source-ordered f0..f{n-1}."""
    opens = [f"function f{i}() {{" for i in range(depth)]
    closes = ["}"] * depth
    return "\n".join(opens) + "\nreturn 0;\n" + "\n".join(closes) + "\n"


def _nested_ifs(depth: int) -> str:
    """One function body with ``depth`` nested ``if`` blocks -> a single unit,
    but an AST just as deep as ``_nested_funcs`` -- keeps build_index's clone
    pass cheap (1 unit) while still stressing the walk's recursion depth."""
    opens = ["if (true) {"] * depth
    closes = ["}"] * depth
    body = "\n".join(opens) + "\nvar x = 1;\n" + "\n".join(closes)
    return "function outer() {\n" + body + "\n}\n"


_NESTED_FUNCS = _nested_funcs(FUNC_DEPTH)
_NESTED_IFS = _nested_ifs(IF_DEPTH)
_SPEC = spec_for("deep.js")


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _recursive_visit_count(src: str, wanted_types: set[str]) -> int:
    """A recursive walk mirroring the PRE-FIX implementation, over the same
    parsed tree the real (now iterative) code walks."""
    parser = _parser_for(_SPEC.ts_grammar)
    tree = parser.parse(src.encode("utf-8"))
    found = []

    def visit(node):
        if node.type in wanted_types:
            found.append(node)
        for child in node.children:
            visit(child)

    visit(tree.root_node)
    return len(found)


@unittest.skipUnless(tree_sitter_available(),
                     "tree-sitter not installed -> AST walk never runs")
class DeepAstRecursionTest(unittest.TestCase):
    def test_naive_recursive_walk_reproduces_the_old_bug(self):
        """Sanity-check the fixture itself: a recursive visit() over the SAME
        parsed tree (mirroring the pre-fix implementation) genuinely blows
        Python's recursion limit at this depth. If this assertion ever stops
        raising, the fixture is no longer deep enough to prove anything."""
        with self.assertRaises(RecursionError):
            _recursive_visit_count(_NESTED_FUNCS, set(_SPEC.function_types))

    def test_extract_units_survives_deep_nesting(self):
        try:
            units = extract_units("deep.js", _NESTED_FUNCS, _SPEC)
        except RecursionError:
            self.fail("extract_units raised RecursionError on deeply nested AST")
        self.assertEqual(len(units), FUNC_DEPTH)
        # Pre-order == source order: f0 (outermost, earliest line) comes first.
        self.assertEqual([u.name for u in units], [f"f{i}" for i in range(FUNC_DEPTH)])
        self.assertTrue(all(units[i].line < units[i + 1].line
                            for i in range(len(units) - 1)))

    def test_extract_imports_survives_deep_nesting(self):
        # Same walk (over wanted=import_types instead), same recursion risk —
        # the fixture has no import statements, so the honest answer is [].
        try:
            edges = extract_imports("deep.js", _NESTED_FUNCS, _SPEC,
                                    tree_sitter_available())
        except RecursionError:
            self.fail("extract_imports raised RecursionError on deeply nested AST")
        self.assertEqual(edges, [])

    def test_build_index_survives_deep_nesting(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, "deep.js", _NESTED_IFS)
            try:
                idx = build_index(root)
            except RecursionError:
                self.fail("build_index raised RecursionError scanning a deeply nested file")
        self.assertIn("javascript", idx["languages"])
        self.assertEqual(idx["modules"]["deep.js"]["n_functions"], 1)


if __name__ == "__main__":
    unittest.main()
