"""G-03: the file walk must not descend directory links (junctions).

``os.walk(followlinks=False)`` refuses POSIX symlinks but happily descends
Windows junctions. The repo's own ``vault/docs`` junction (deliberate, for
Obsidian) made the engine double-count the whole doc tree: 5 phantom modules
and three phantom clone clusters of itself.
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from daedalus.structcore.index import build_index


def _make_junction(link: Path, target: Path) -> bool:
    if sys.platform == "win32":
        proc = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
        )
        return proc.returncode == 0
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except OSError:
        return False


class JunctionDedupTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        pkg = self.root / "pkg"
        pkg.mkdir()
        (pkg / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
        if not _make_junction(self.root / "linked", pkg):
            self.skipTest("cannot create directory link on this host")

    def test_linked_directory_is_not_walked(self):
        idx = build_index(self.root)
        self.assertIn("pkg/a.py", idx["modules"])
        self.assertNotIn("linked/a.py", idx["modules"])
        self.assertEqual(idx["n_files"], 1)

    def test_prune_dirnames_drops_the_link_for_every_walk(self):
        # both walks (_collect and the docs pass) share _prune_dirnames;
        # pinning the shared primitive pins them together (Codex finding:
        # the walk-level test alone could not catch a docs-pass regression)
        from daedalus.structcore.index import _prune_dirnames
        kept = _prune_dirnames(str(self.root), ["pkg", "linked"])
        self.assertEqual(kept, ["pkg"])


if __name__ == "__main__":
    unittest.main()
