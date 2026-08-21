"""fan_in must count one file as ONE identity across naming views (G-01).

With a declared center, a file inside the center names a center target by its
package-relative dotted name while a shell file names the same target by its
repo-root form. ``dep_edges`` keeps both spellings (importer's-eye view, by
design); ``fan_in`` must NOT — it is the published per-module ranking, and a
split identity halves every center module's score and double-lists it in the
top table (measured on this repo: 75 split identities, structcore.parse listed
twice with 13+12 instead of once with 25).
"""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from daedalus.structcore.index import build_index


def _write(root: Path, rel: str, text: str = "x = 1\n") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class FanInAliasSplitTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        _write(self.root, "app/lib.py", "VALUE = 1\n")
        # importer INSIDE the center: package-relative spelling
        _write(self.root, "app/user_in.py", "from lib import VALUE\n")
        # importer OUTSIDE the center: repo-root spelling, same target file
        _write(self.root, "out.py", "from app.lib import VALUE\n")

    def test_one_file_is_one_fan_in_identity_across_views(self):
        idx = build_index(self.root, center=["app"])
        fan_in = idx["fan_in"]
        self.assertFalse(
            "lib" in fan_in and "app.lib" in fan_in,
            f"split identity: both spellings counted separately: {fan_in}",
        )
        self.assertEqual(
            fan_in.get("lib"), 2,
            f"both importers must land on the canonical identity: {fan_in}",
        )

    def test_unscoped_repo_fan_in_is_unchanged(self):
        # without a center, "from lib import" is unresolvable (repo-root
        # naming) and only the shell importer counts — historical behavior
        idx = build_index(self.root)
        self.assertEqual(idx["fan_in"].get("app.lib"), 1)
        self.assertNotIn("lib", idx["fan_in"])


class FanInSpellingCollisionTest(unittest.TestCase):
    """Codex finding: two centers can give DIFFERENT files the same canonical
    spelling. Refuse-not-guess means fan_in must publish them per file (rel
    path), never merged under the shared spelling."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        for c in ("a", "b"):
            _write(self.root, f"{c}/lib.py", "VALUE = 1\n")
            _write(self.root, f"{c}/user.py", "from lib import VALUE\n")

    def test_colliding_spellings_are_published_per_file(self):
        idx = build_index(self.root, center=["a", "b"])
        fan_in = idx["fan_in"]
        self.assertNotIn("lib", fan_in, f"merged spelling published: {fan_in}")
        self.assertEqual(fan_in.get("a/lib.py"), 1)
        self.assertEqual(fan_in.get("b/lib.py"), 1)


class CenterDirectiveTest(unittest.TestCase):
    """G-02: `.daedalusignore` may DECLARE the center (`center: a, b`), so the
    repo carries its own scope truth instead of relying on every caller to
    remember a --center flag. Precedence: explicit arg > DAEDALUS_CENTER >
    file directive."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        _write(self.root, "app/lib.py", "VALUE = 1\n")
        (self.root / ".daedalusignore").write_text(
            "# scope declaration\ncenter: app, tools\nvendor/\n",
            encoding="utf-8",
        )

    def test_file_directive_supplies_default_center(self):
        from daedalus.structcore.ignore import project_scope
        scope = project_scope(self.root)
        self.assertEqual(scope.center, ("app", "tools"))

    def test_explicit_center_overrides_file_directive(self):
        from daedalus.structcore.ignore import project_scope
        scope = project_scope(self.root, center=["app"])
        self.assertEqual(scope.center, ("app",))

    def test_directive_line_is_not_an_ignore_pattern(self):
        from daedalus.structcore.ignore import project_scope
        scope = project_scope(self.root)
        self.assertFalse(scope.ignore.matches("center: app, tools"))
        self.assertTrue(scope.ignore.matches("vendor/x.py"))

    def test_explicit_empty_center_overrides_file_directive(self):
        # Codex finding: [] must mean "explicitly no center", not "unset";
        # the CLI passes None when the flag is absent, so this is safe.
        from daedalus.structcore.ignore import project_scope
        scope = project_scope(self.root, center=[])
        self.assertEqual(scope.center, ())

    def test_editing_the_directive_moves_the_scope_fingerprint(self):
        from daedalus.structcore.ignore import project_scope
        before = project_scope(self.root).fingerprint
        (self.root / ".daedalusignore").write_text(
            "center: app\nvendor/\n", encoding="utf-8")
        after = project_scope(self.root).fingerprint
        self.assertNotEqual(before, after)


if __name__ == "__main__":
    unittest.main()
