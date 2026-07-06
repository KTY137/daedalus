"""Era-3 #1: advisory drafts persist instead of evaporating.

The free lane may propose, never merge -- so an accepted advisory offload must
land its proposal in runs/drafts/ where `daedalus drafts list|show|rm` (and
later the webapp queue view) can review it. Apply stays a human/Claude action.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from daedalus import drafts, metrics
from daedalus.offload import offload

_AVAIL = {"claude_cli": True, "ollama": True, "deepseek": False}


def _report(files_changed=None, status="done", summary="s"):
    return {"status": status, "summary": summary, "files_changed": files_changed or [],
            "tests_run": [], "risks": [], "todos": [], "handoff": {}}


class DraftStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = drafts.DRAFT_DIR
        drafts.DRAFT_DIR = Path(self._tmp.name) / "drafts"

    def tearDown(self):
        drafts.DRAFT_DIR = self._orig
        self._tmp.cleanup()

    def test_save_list_show_delete_round_trip(self):
        p = drafts.save_draft("Review the tips guide", ["docs/tips.md"], "tippy",
                              "ollama", "Diego", _report(summary="proposal text"),
                              repo_root="/repo")
        self.assertTrue(p.is_file())
        rows = drafts.list_drafts()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["agent"], "tippy")
        self.assertEqual(rows[0]["status"], "pending")
        full = drafts.get_draft(rows[0]["id"])
        self.assertEqual(full["report"]["summary"], "proposal text")
        self.assertEqual(full["repo_root"], "/repo")
        self.assertTrue(drafts.delete_draft(rows[0]["id"]))
        self.assertEqual(drafts.list_drafts(), [])
        self.assertFalse(drafts.delete_draft("nope"))

    def test_same_second_saves_do_not_overwrite(self):
        a = drafts.save_draft("Same objective", [], "a", "ollama", "P", _report())
        b = drafts.save_draft("Same objective", [], "b", "ollama", "P", _report())
        self.assertNotEqual(a, b)
        self.assertEqual(len(drafts.list_drafts()), 2)

    def test_apply_marks_handled_and_returns_review_packet(self):
        drafts.save_draft("Tidy the readme", ["README.md"], "quill", "ollama",
                           "Lucia", _report(summary="reword the intro"), repo_root="/r")
        did = drafts.list_drafts()[0]["id"]
        packet = drafts.apply_payload(did)
        self.assertEqual(packet["objective"], "Tidy the readme")
        self.assertEqual(packet["paths"], ["README.md"])
        self.assertEqual(packet["proposal"], "reword the intro")
        self.assertIn("never merges", packet["handoff"])
        # apply is a status transition, NOT a write -> draft now marked applied
        self.assertEqual(drafts.get_draft(did)["status"], "applied")

    def test_dismiss_and_invalid_status(self):
        drafts.save_draft("x", [], "a", "ollama", "P", _report())
        did = drafts.list_drafts()[0]["id"]
        self.assertEqual(drafts.set_status(did, "dismissed")["status"], "dismissed")
        self.assertIsNone(drafts.set_status("nope", "applied"))
        with self.assertRaises(ValueError):
            drafts.set_status(did, "merged")


class _AdvisoryDraftWorker:
    def run(self, **kwargs):
        return {"report": _report()}
    def rollback(self):
        return []


class OffloadPersistsDraftTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_dir = drafts.DRAFT_DIR
        drafts.DRAFT_DIR = Path(self._tmp.name) / "drafts"
        self._orig_log = metrics.LOG
        metrics.LOG = Path(self._tmp.name) / "m.jsonl"
        # hermetic repo with a trusted-only agent -> review-only objective routes advisory
        cfg = Path(self._tmp.name) / "repo" / ".agentenv"
        (cfg / "agents").mkdir(parents=True)
        (cfg / "agents" / "scribe.json").write_text(json.dumps(
            {"name": "scribe", "call_name": "Quill", "model_tier": "haiku",
             "external_ok": False, "owns": ["notes.md"], "triggers": ["notes", "summar"],
             "must_read": [], "output_schema": "agent_report_v1"}), encoding="utf-8")
        self.repo = str(Path(self._tmp.name) / "repo")

    def tearDown(self):
        drafts.DRAFT_DIR = self._orig_dir
        metrics.LOG = self._orig_log
        self._tmp.cleanup()

    def test_accepted_advisory_offload_stores_a_draft(self):
        with mock.patch("daedalus.providers.get_provider",
                        return_value=_AdvisoryDraftWorker()):
            r = offload("Summarize the notes file", self.repo, ["notes.md"],
                        live=True, availability=_AVAIL)
        self.assertEqual(r["mode"], "advisory")
        self.assertEqual(r["action"], "offloaded")
        self.assertTrue(r.get("draft"))                      # id returned
        rows = drafts.list_drafts()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], r["draft"])
        self.assertEqual(drafts.get_draft(r["draft"])["repo_root"], self.repo)


if __name__ == "__main__":
    unittest.main()
