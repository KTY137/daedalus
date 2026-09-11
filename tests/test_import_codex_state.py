from __future__ import annotations

import tempfile
import subprocess
import sys
import unittest
from pathlib import Path

from tools.import_codex_state import import_state


class SafeCodexImportTest(unittest.TestCase):
    def test_direct_script_help_resolves_project_imports(self) -> None:
        script = Path(__file__).resolve().parents[1] / "tools" / "import_codex_state.py"
        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            cwd=tempfile.gettempdir(),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("offline/mounted laptop CODEX_HOME", result.stdout)

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.source = root / "laptop"
        self.destination = root / "desktop"
        self.source.mkdir()
        self.destination.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write(self, root: Path, rel: str, text: str) -> None:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_dry_run_does_not_copy_and_excludes_secrets_and_sqlite(self) -> None:
        self.write(self.source, "sessions/2026/08/chat.jsonl", "chat")
        self.write(self.source, "memories/MEMORY.md", "memory")
        self.write(self.source, "auth.json", "secret")
        self.write(self.source, "state_5.sqlite", "db")
        report = import_state(self.source, self.destination)
        self.assertEqual(
            report.copied,
            ["sessions/2026/08/chat.jsonl", "memories/MEMORY.md"],
        )
        self.assertEqual(list(self.destination.rglob("*")), [])

    def test_apply_copies_missing_files_and_is_idempotent(self) -> None:
        self.write(self.source, "sessions/2026/08/chat.jsonl", "chat")
        first = import_state(self.source, self.destination, apply=True)
        second = import_state(self.source, self.destination, apply=True)
        self.assertEqual(first.copied, ["sessions/2026/08/chat.jsonl"])
        self.assertEqual(second.identical, ["sessions/2026/08/chat.jsonl"])

    def test_divergent_target_is_a_conflict_and_is_not_overwritten(self) -> None:
        rel = "memories/rollout_summaries/one.md"
        self.write(self.source, rel, "laptop")
        self.write(self.destination, rel, "desktop")
        report = import_state(self.source, self.destination, apply=True)
        self.assertEqual(report.conflicts, [rel])
        self.assertEqual((self.destination / rel).read_text(encoding="utf-8"), "desktop")


if __name__ == "__main__":
    unittest.main()
