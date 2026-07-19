"""Movement I.5 / Move 3 — churn x complexity hotspots.

``git_churn`` degrades cleanly (no git / not a repo -> {}); when a repo IS
present, a frequently-changed file outranks an equally-complex but stable one in
the hotspot list (the CodeScene signal). The git-fixture test is skipped if git
is not on PATH; the graceful-degradation test always runs.
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from daedalus.structcore import build_index
from daedalus.structcore.churn import git_churn, _parse_numstat


# An identically-complex function body (long + guarded) planted in two files, so
# base complexity is equal and CHURN is the only differentiator.
def _complex(tag: str) -> str:
    body = [f"def handler_{tag}(payload):", "    total = 0"]
    for i in range(60):
        body.append(f"    try:")
        body.append(f"        total = total + {i}")
        body.append(f"    except Exception:")
        body.append(f"        total = total - {i}")
    body.append("    return total")
    return "\n".join(body) + "\n"


GIT = shutil.which("git")


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t.co", "-c", "user.name=Test", "-C", str(root), *args],
        check=True, capture_output=True,
    )


class NumstatParseTest(unittest.TestCase):
    def test_parses_and_sums_added_plus_deleted(self):
        out = "10\t2\tfoo.py\n5\t5\tfoo.py\n-\t-\timg.png\n"
        churn = _parse_numstat(out)
        self.assertEqual(churn["foo.py"], 10 + 2 + 5 + 5)
        self.assertEqual(churn.get("img.png"), 0)  # binary '-' counts as 0

    def test_rename_notation_follows_new_path(self):
        out = "3\t1\told.py => new.py\n2\t0\tpkg/{a => b}/mod.py\n"
        churn = _parse_numstat(out)
        self.assertEqual(churn.get("new.py"), 4)
        self.assertEqual(churn.get("pkg/b/mod.py"), 2)


class GracefulDegradeTest(unittest.TestCase):
    def test_non_git_dir_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(git_churn(d), {})

    def test_hotspots_present_without_churn(self):
        # Non-git repo: hotspots still produced, churn field defaults to 0.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "m.py").write_text(_complex("x"), encoding="utf-8")
            idx = build_index(root)
            self.assertTrue(idx["hotspots"])
            self.assertEqual(idx["hotspots"][0]["churn"], 0)


@unittest.skipUnless(GIT, "git not on PATH")
class ChurnRankingTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _git(self.root, "init", "-q")
        # Both files start identical (equal base complexity).
        (self.root / "hot.py").write_text(_complex("hot"), encoding="utf-8")
        (self.root / "stable.py").write_text(_complex("stable"), encoding="utf-8")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", "init")
        # Churn ONLY hot.py: many edits, then restore original (base stays equal).
        original = _complex("hot")
        for n in range(1, 16):
            (self.root / "hot.py").write_text(
                original.replace("total = 0", f"total = {n}"), encoding="utf-8")
            _git(self.root, "commit", "-qam", f"edit {n}")
        (self.root / "hot.py").write_text(original, encoding="utf-8")
        _git(self.root, "commit", "-qam", "restore")

    def tearDown(self):
        self._tmp.cleanup()

    def test_churn_map_ranks_hot_above_stable(self):
        churn = git_churn(self.root)
        self.assertGreater(churn.get("hot.py", 0), churn.get("stable.py", 0))

    def test_hotspot_score_reflects_churn(self):
        idx = build_index(self.root)
        rows = {h["module"]: h for h in idx["hotspots"]}
        self.assertIn("hot.py", rows)
        self.assertIn("stable.py", rows)
        self.assertGreater(rows["hot.py"]["churn"], rows["stable.py"]["churn"])
        # Equal base complexity, higher churn -> strictly higher hotspot score.
        self.assertGreater(rows["hot.py"]["score"], rows["stable.py"]["score"])
        order = [h["module"] for h in idx["hotspots"]]
        self.assertLess(order.index("hot.py"), order.index("stable.py"))


if __name__ == "__main__":
    unittest.main()
