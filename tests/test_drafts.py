# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

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

from daedalus import metrics
from daedalus.kairos import drafts
# THE LIVE CASCADE TAKES A LEASE NOW, AND SO DOES THIS TEST. The shim that
# used to stand here called ``daedalus.offload._offload_impl`` directly with
# ``live=True`` -- a complete, un-leased write path. That second caller is
# exactly why ``scripts/declare_write_surfaces.py`` could not attribute the
# provider run to ``python.offload``'s Effect Lease: a write reachable from a
# leased AND an un-leased caller is attributable to neither. The planner no
# longer executes anything, so these tests take the door production takes.
from test_offload_lease_harness import live_offload as offload


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

    def test_listing_scopes_to_one_repository(self):
        """One project must never be shown another project's drafts.

        The store is a single directory shared by every project. Before the
        listing carried ``repo_root`` there was nothing to scope on, and the
        cockpit's decision card counted every project's drafts under whichever
        project happened to be selected -- the same defect class design review
        has twice caught on this surface.
        """
        drafts.save_draft("Water the tomatoes", ["notes.md"], "gardener", "ollama",
                          "Diego", _report(), repo_root="/repo/garden")
        drafts.save_draft("Close the gate", ["daedalus/gate1.py"], "builder", "ollama",
                          "Diego", _report(), repo_root="/repo/kernel")

        everything = drafts.list_drafts()
        self.assertEqual(len(everything), 2)
        # the summary carries the root, or nothing downstream can scope at all
        self.assertEqual({r["repo_root"] for r in everything},
                         {"/repo/garden", "/repo/kernel"})

        garden = drafts.list_drafts("/repo/garden")
        self.assertEqual([r["objective"] for r in garden], ["Water the tomatoes"])
        kernel = drafts.list_drafts("/repo/kernel")
        self.assertEqual([r["objective"] for r in kernel], ["Close the gate"])

    def test_scoping_survives_windows_path_spelling(self):
        """The same tree spelled two ways is one tree.

        A draft written by the CLI carries a native path; the same repository
        arrives from a URL with forward slashes and a lower-case drive letter.
        Comparing the raw strings would hide a project's own drafts from it,
        which is the same lie as showing it someone else's.
        """
        drafts.save_draft("Close the gate", ["a.py"], "builder", "ollama", "Diego",
                          _report(), repo_root="C:\\Users\\x\\agent_env")
        for spelling in ("C:\\Users\\x\\agent_env",
                         "C:/Users/x/agent_env",
                         "c:\\users\\x\\agent_env",
                         "C:\\Users\\x\\agent_env\\"):
            with self.subTest(spelling=spelling):
                self.assertEqual(len(drafts.list_drafts(spelling)), 1,
                                 f"{spelling} did not resolve to the stored root")

    def test_a_rootless_draft_is_claimed_by_no_project(self):
        """A draft written before the field existed belongs to nobody.

        Assigning it to whichever project asks would be inventing provenance.
        It stays visible in the unfiltered listing and is absent from every
        scoped one.
        """
        drafts.save_draft("Ancient proposal", ["x.md"], "old", "ollama", "Diego",
                          _report(), repo_root=None)
        self.assertEqual(len(drafts.list_drafts()), 1)
        self.assertEqual(drafts.list_drafts("/repo/anything"), [])

    def test_path_traversal_ids_are_refused(self):
        # draft_id arrives from CLI args and URL segments -> must never index a
        # path outside DRAFT_DIR. Every accessor fails closed on a hostile id.
        for evil in ["../../secret", "..\\..\\secret", "/etc/passwd",
                     "a/b", "with space", "x" * 200, ""]:
            self.assertIsNone(drafts.get_draft(evil), evil)
            self.assertFalse(drafts.delete_draft(evil), evil)
            self.assertIsNone(drafts.set_status(evil, "applied"), evil)
            self.assertIsNone(drafts.apply_payload(evil), evil)


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
