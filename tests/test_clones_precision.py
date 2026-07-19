"""Movement I.5 / Move 1 — clone precision: Type-2 (renamed) + Type-3 (near-miss).

Runs stdlib-only (Python abstraction uses the ``tokenize`` lexer). Verifies that
a renamed-but-structurally-identical pair lands in ``renamed_clusters`` (and NOT
in the exact ``unit_clusters``), and a gapped/near copy lands in ``near_clusters``
with a similarity score — both additive to the existing exact-clone index and
both safety-annotated.
"""
import tempfile
import unittest
from pathlib import Path

from daedalus.structcore import build_index
from daedalus.structcore.clones import abstract_normalize, token_bag, fingerprint
from daedalus.structcore.languages import spec_for


# Same structure, every identifier + literal renamed (a Type-2 clone).
ORIG = '''\
def compute_total(items):
    total = 0
    for item in items:
        total = total + item.price
        total = total * 3
    return total
'''
RENAMED = '''\
def add_up(rows):
    acc = 0
    for row in rows:
        acc = acc + row.cost
        acc = acc * 7
    return acc
'''

# Near-miss: mostly-shared token bags, but each has content the other lacks, so
# neither is contained in the other (similarity strictly between 0.8 and 1.0).
NEAR_A = '''\
def summarize(records):
    result = []
    for rec in records:
        value = rec.amount * 2
        label = rec.name.upper()
        result.append((label, value))
    return result
'''
NEAR_B = '''\
def digest(rows):
    output = []
    for row in rows:
        amount = row.total + 5
        title = row.tag.lower()
        output.append((title, amount))
    return output
'''


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class AbstractNormalizeTest(unittest.TestCase):
    def test_renamed_share_abstract_but_not_exact(self):
        spec = spec_for("x.py")
        self.assertEqual(abstract_normalize(ORIG, spec), abstract_normalize(RENAMED, spec))
        self.assertNotEqual(fingerprint(ORIG, spec), fingerprint(RENAMED, spec))

    def test_identifiers_and_literals_abstracted(self):
        spec = spec_for("x.py")
        norm = abstract_normalize(ORIG, spec)
        self.assertIn("ID", norm)
        self.assertIn("NUM", norm)
        self.assertNotIn("compute_total", norm)  # identifier erased
        self.assertIn("for", norm)               # keyword kept (structure)

    def test_token_bag_is_multiset_of_abstract_tokens(self):
        bag = token_bag(ORIG, spec_for("x.py"))
        self.assertGreater(bag["ID"], 0)
        self.assertGreater(bag["NUM"], 0)


class RenamedClusterTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "a.py", ORIG)
        _write(self.root, "b.py", RENAMED)
        self.dup = build_index(self.root)["duplication"]

    def tearDown(self):
        self._tmp.cleanup()

    def test_renamed_pair_reported_not_as_exact(self):
        exact_names = {c["name"] for c in self.dup["unit_clusters"]}
        self.assertNotIn("compute_total", exact_names)  # not byte-identical
        self.assertNotIn("add_up", exact_names)

        renamed = self.dup["renamed_clusters"]
        self.assertTrue(renamed, "expected a renamed (Type-2) cluster")
        cluster = renamed[0]
        self.assertEqual(cluster["count"], 2)
        self.assertEqual(set(cluster["names"]), {"compute_total", "add_up"})
        self.assertEqual(cluster["kind"], "renamed")
        self.assertIn("safety", cluster)  # SAFETY-CLASS fence present on the new kind

    def test_pure_exact_clone_not_double_reported_as_renamed(self):
        # Two byte-identical copies must stay exact-only (never leak into renamed).
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        _write(root, "x.py", ORIG)
        _write(root, "y.py", ORIG)
        dup = build_index(root)["duplication"]
        self.assertIn("compute_total", {c["name"] for c in dup["unit_clusters"]})
        self.assertEqual(dup["renamed_clusters"], [])
        tmp.cleanup()


class NearClusterTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "a.py", NEAR_A)
        _write(self.root, "b.py", NEAR_B)
        self.dup = build_index(self.root)["duplication"]

    def tearDown(self):
        self._tmp.cleanup()

    def test_near_copy_reported_with_similarity(self):
        near = self.dup["near_clusters"]
        self.assertTrue(near, "expected a near-miss (Type-3) cluster")
        cluster = near[0]
        self.assertEqual(cluster["count"], 2)
        self.assertEqual(set(cluster["names"]), {"summarize", "digest"})
        self.assertEqual(cluster["kind"], "near")
        self.assertGreaterEqual(cluster["similarity"], 0.8)
        self.assertLessEqual(cluster["similarity"], 1.0)
        self.assertIn("safety", cluster)

    def test_near_pair_not_exact_or_renamed(self):
        self.assertEqual(self.dup["unit_clusters"], [])
        self.assertEqual(self.dup["renamed_clusters"], [])


if __name__ == "__main__":
    unittest.main()
