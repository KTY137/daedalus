"""The bookkeeper renders ARCHITECTURE.md -> architecture.html and files a
timestamped history snapshot when the architecture changed. These tests pin the
markdown renderer's core constructs and the change-detection/history behavior,
against a temp docs dir (never the real one)."""

import tempfile
import unittest
from pathlib import Path

from daedalus.interfaces.cli import bookkeeper as bk


class RenderTests(unittest.TestCase):
    def test_core_markdown_constructs(self):
        md = ("# Title\n\nA **bold** and `code` and [link](x).\n\n"
              "## Section\n\n- one\n- two\n\n"
              "| a | b |\n|---|---|\n| 1 | 2 |\n\n"
              "> a quote\n\n```\ncode block\n```\n\n---\n")
        html = bk.render_markdown(md)
        self.assertIn("<h1>Title</h1>", html)
        self.assertIn("<h2>Section</h2>", html)
        self.assertIn("<strong>bold</strong>", html)
        self.assertIn("<code>code</code>", html)
        self.assertIn('<a href="x">link</a>', html)
        self.assertIn("<li>one</li>", html)
        self.assertIn("<table>", html)
        self.assertIn("<td>1</td>", html)
        self.assertIn("<blockquote>", html)
        self.assertIn("<pre><code>code block</code></pre>", html)
        self.assertIn("<hr>", html)

    def test_html_is_escaped(self):
        html = bk.render_markdown("A <script> & stuff\n")
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>", html)


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        d = Path(self._tmp.name)
        self._orig = (bk.DOCS, bk.SOURCE, bk.ARTIFACT, bk.HISTORY)
        bk.DOCS = d
        bk.SOURCE = d / "ARCHITECTURE.md"
        bk.ARTIFACT = d / "architecture.html"
        bk.HISTORY = d / "architecture_history"
        bk.SOURCE.write_text("# Arch v1\n\n- a\n", encoding="utf-8")

    def tearDown(self):
        bk.DOCS, bk.SOURCE, bk.ARTIFACT, bk.HISTORY = self._orig
        self._tmp.cleanup()

    def test_first_update_snapshots_then_unchanged_does_not(self):
        r1 = bk.update()
        self.assertTrue(r1["ok"] and r1["changed"])
        self.assertTrue(bk.ARTIFACT.is_file())
        self.assertEqual(r1["snapshots_total"], 1)

        r2 = bk.update()                      # source unchanged
        self.assertFalse(r2["changed"])
        self.assertIsNone(r2["snapshot"])
        self.assertEqual(r2["snapshots_total"], 1)

    def test_changed_source_files_a_new_snapshot(self):
        bk.update()
        bk.SOURCE.write_text("# Arch v2\n\n- a\n- b\n", encoding="utf-8")
        r = bk.update(note="after build: x")
        self.assertTrue(r["changed"])
        self.assertEqual(r["snapshots_total"], 2)
        # history index + manifest exist and list both
        self.assertTrue((bk.HISTORY / "index.html").is_file())
        snaps = list(bk.HISTORY.glob("architecture-*.html"))
        self.assertEqual(len(snaps), 2)

    def test_force_snapshots_even_when_unchanged(self):
        bk.update()
        r = bk.update(force=True)
        self.assertTrue(r["changed"])
        self.assertEqual(r["snapshots_total"], 2)


if __name__ == "__main__":
    unittest.main()
