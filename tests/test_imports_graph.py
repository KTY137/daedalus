"""Movement I.5 / Moves 2 + 4 — all-language dependency graph + sharper symbols.

Move 2: Java/Rust/JS internal imports resolve to real dependency edges + fan-in
(needs tree-sitter for precise import nodes; skipped gracefully if absent).

Move 4: the import/scope-aware symbol resolver routes a call to the IMPORTED
definition instead of every same-named unit — a pure-Python check that needs no
optional backend.
"""
import tempfile
import unittest
from pathlib import Path

from daedalus.structcore import build_index
from daedalus.structcore.index import resolution_context
from daedalus.structcore import graph
from daedalus.structcore.parse import tree_sitter_available, extract_units
from daedalus.structcore.languages import spec_for


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@unittest.skipUnless(tree_sitter_available(),
                     "tree-sitter not installed -> non-Python import edges degrade")
class MultiLanguageImportsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # Java: import app.util.Helper -> src/app/util/Helper.java
        _write(self.root, "src/app/Main.java",
               "package app;\nimport app.util.Helper;\nclass Main { }\n")
        _write(self.root, "src/app/util/Helper.java",
               "package app.util;\nclass Helper { }\n")
        # Rust: use crate::util::helper -> util.rs
        _write(self.root, "rustpkg/main.rs", "use crate::util::helper;\nfn main() { }\n")
        _write(self.root, "rustpkg/util.rs", "pub fn helper() { }\n")
        # JS: import from './util' -> web/util.js
        _write(self.root, "web/app.js",
               "import { help } from './util';\nexport function app() { return help(); }\n")
        _write(self.root, "web/util.js", "export function help() { return 1; }\n")
        self.idx = build_index(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_java_edge(self):
        deps = self.idx["dependencies"]
        self.assertIn("src/app/util/Helper.java", deps.get("src/app/Main.java", []))

    def test_rust_edge(self):
        deps = self.idx["dependencies"]
        self.assertIn("rustpkg/util.rs", deps.get("rustpkg/main.rs", []))

    def test_js_edge(self):
        deps = self.idx["dependencies"]
        self.assertIn("web/util.js", deps.get("web/app.js", []))

    def test_fan_in_counts_targets(self):
        fan = self.idx["fan_in"]
        self.assertEqual(fan.get("src/app/util/Helper.java"), 1)
        self.assertEqual(fan.get("rustpkg/util.rs"), 1)
        self.assertEqual(fan.get("web/util.js"), 1)


class SymbolResolverTest(unittest.TestCase):
    """Two unrelated modules both define ``process``; ``main`` imports only one
    and calls ``process``. Resolution must pick the imported one, not both."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "proj/__init__.py", "")
        _write(self.root, "proj/svc_a.py", "def process(x):\n    return x + 1\n")
        _write(self.root, "proj/svc_b.py", "def process(x):\n    return x - 1\n")
        _write(self.root, "proj/main.py",
               "from proj import svc_a\n\n\ndef run():\n    return svc_a.process(3)\n")
        self.idx = build_index(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def _units(self, rel):
        text = (self.root / rel).read_text(encoding="utf-8")
        return extract_units(rel, text, spec_for(rel))

    def test_resolver_routes_to_imported_definition(self):
        run = next(u for u in self._units("proj/main.py") if u.name == "run")
        candidates = self._units("proj/svc_a.py") + self._units("proj/svc_b.py")

        # Pure name-match (v1): ambiguous -> BOTH process() units match.
        naive = graph.callees(run, candidates)
        self.assertEqual({u.module for u in naive},
                         {"proj/svc_a.py", "proj/svc_b.py"})

        # Import/scope-aware (Move 4): resolves to the imported module only.
        resolver = resolution_context(self.root)
        self.assertIsNotNone(resolver)
        sharp = graph.callees(run, candidates, resolver)
        self.assertEqual([u.module for u in sharp], ["proj/svc_a.py"])

    def test_resolver_defaults_preserve_v1_behavior(self):
        # No resolver arg -> identical to the historical name-match.
        run = next(u for u in self._units("proj/main.py") if u.name == "run")
        cands = self._units("proj/svc_a.py")
        self.assertEqual(graph.callees(run, cands),
                         graph.callees(run, cands, None))


if __name__ == "__main__":
    unittest.main()
