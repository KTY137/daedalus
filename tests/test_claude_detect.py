# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from daedalus import claude_detect as cd
from daedalus import core

SAMPLE_SINGLE = """---
name: security-reviewer
description: Argus, reviews auth and crypto changes. Read-only.
model: opus
tools: Read, Grep, Glob
---
body here
"""

SAMPLE_FOLDED = """---
name: mary
description: >
  Stateless strict reviewer. Use before finalizing
  substantial changes.
model: sonnet
---
body
"""


class ParseFrontmatterTests(unittest.TestCase):
    def test_single_line(self):
        fm = cd.parse_frontmatter(SAMPLE_SINGLE)
        self.assertEqual(fm["name"], "security-reviewer")
        self.assertEqual(fm["model"], "opus")
        self.assertIn("auth", fm["description"])
        self.assertEqual(fm["tools"], "Read, Grep, Glob")

    def test_folded_description(self):
        fm = cd.parse_frontmatter(SAMPLE_FOLDED)
        self.assertEqual(fm["name"], "mary")
        self.assertEqual(fm["model"], "sonnet")
        self.assertIn("Stateless strict reviewer", fm["description"])
        self.assertIn("substantial changes", fm["description"])

    def test_no_frontmatter(self):
        self.assertEqual(cd.parse_frontmatter("no frontmatter here"), {})


class DetectClaudeCrewTests(unittest.TestCase):
    def test_detects_agents(self):
        with tempfile.TemporaryDirectory() as d:
            agents = Path(d) / ".claude" / "agents"
            agents.mkdir(parents=True)
            (agents / "reviewer.md").write_text(SAMPLE_SINGLE, encoding="utf-8")
            (agents / "mary.md").write_text(SAMPLE_FOLDED, encoding="utf-8")
            result = cd.detect_claude_crew(d)
        self.assertEqual(result["count"], 2)
        self.assertEqual(sorted(a["name"] for a in result["agents"]), ["mary", "security-reviewer"])
        byname = {a["name"]: a for a in result["agents"]}
        self.assertEqual(byname["security-reviewer"]["model"], "opus")

    def test_empty_when_absent_or_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(cd.detect_claude_crew(d)["count"], 0)
        self.assertEqual(cd.detect_claude_crew(None)["count"], 0)

    def test_dashboard_carries_claude_crew(self):
        with patch("daedalus.core.list_projects", return_value=[]), \
                patch("daedalus.core._process_rows", return_value=[]), \
                patch("urllib.request.urlopen", side_effect=OSError("offline")):
            payload = core.get_dashboard(None)
        self.assertIn("claude_crew", payload)
        self.assertEqual(payload["claude_crew"]["count"], 0)


if __name__ == "__main__":
    unittest.main()
