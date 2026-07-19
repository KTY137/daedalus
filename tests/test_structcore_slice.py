"""Movement I — 'Distill this': semantic slice beats whole-repo concatenation.

Verifies the slice includes the focus + its caller neighborhood, OMITS unrelated
files, and reports a real token reduction vs the naive full-repo dump.
"""
import tempfile
import unittest
from pathlib import Path

from daedalus.structcore import semantic_slice, build_index


CORE = '''\
def helper(x):
    """Return x doubled."""
    return x * 2


class Engine:
    def run(self):
        return helper(21)
'''

APP = '''\
from proj import core


def main():
    e = core.Engine()
    return e.run()
'''

# a big, unrelated file that a whole-repo dump would wastefully include
UNRELATED = "# unrelated module\nUNIQUE_MARKER = 'do-not-include'\n" + \
    "\n".join(f"def unrelated_{i}():\n    return {i}" for i in range(40))


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class SliceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "proj/__init__.py", "")
        _write(self.root, "proj/core.py", CORE)
        _write(self.root, "proj/app.py", APP)
        _write(self.root, "proj/unrelated.py", UNRELATED)
        self.idx = build_index(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_focus_and_caller_included_unrelated_omitted(self):
        res = semantic_slice(self.root, "proj/core.py", idx=self.idx)
        self.assertEqual(res["focus_file"], "proj/core.py")
        files = {i["file"]: i["role"] for i in res["included"]}
        self.assertEqual(files["proj/core.py"], "focus")
        self.assertEqual(files.get("proj/app.py"), "caller")  # app imports core
        self.assertNotIn("proj/unrelated.py", files)
        self.assertNotIn("UNIQUE_MARKER", res["slice_text"])

    def test_token_reduction_positive(self):
        res = semantic_slice(self.root, "proj/core.py", idx=self.idx)
        self.assertLess(res["slice_tokens"], res["whole_repo_tokens"])
        self.assertGreater(res["reduction_pct"], 0)

    def test_symbol_level_focus(self):
        res = semantic_slice(self.root, "proj/core.py::helper", idx=self.idx)
        self.assertEqual(res["focus_symbol"], "helper")
        # focus is just the helper function, so Engine should not be in the FOCUS block
        focus_block = res["slice_text"].split("# =====", 2)[1]
        self.assertIn("def helper", focus_block)
        self.assertNotIn("class Engine", focus_block)

    def test_suffix_target_resolves(self):
        res = semantic_slice(self.root, "core.py", idx=self.idx)
        self.assertEqual(res["focus_file"], "proj/core.py")


if __name__ == "__main__":
    unittest.main()
