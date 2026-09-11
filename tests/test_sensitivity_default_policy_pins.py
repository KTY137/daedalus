"""F6: what an unattended write lane may edit when NO project was named.

THE REACHABLE PATH, not a hypothetical one::

    python -m daedalus.orchestration.loop --repo-root <repo> --arm      # no --project
      -> KairosScheduler(project=None)
      -> policy=None
      -> path_write_blocked(path, None) -> DEFAULT_POLICY

MEASURED against ``DEFAULT_POLICY`` before this fix -- every line below said
WRITABLE::

    AGENTS.md
    CLAUDE.md
    docs/IKARUS_ARIADNE_MASTER_PLAN.md
    docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl
    tools/iron_plan_guard.py
    .agentenv/agentenv.json
    .agentenv/tool-allowances.json
    daedalus/kairos/gated_writes.py
    daedalus/kairos/_gated_writes_legacy.py.src
    daedalus/sensitivity.py
    .git/config
    .claude/settings.json

Only ``/kernel/`` was fenced. So the local model could rewrite the
constitution that governs it, the guard that checks the constitution, the
capability policy that bounds its effects, the gate that promotes its work,
the module that decides all of the above, and ``.git/config`` -- which chooses
which program "verifies" the owner's promotion signature -- and then report
success. That is not a hardening gap, it is the governance being writable by
the thing it governs.

These entries are project-INDEPENDENT because the files ship WITH the harness:
dropping it onto an arbitrary repo carries them along, so the fence has to as
well. ``load_policy`` unions ``GENERIC_HIGH_RISK_PATHS`` in and cannot remove
them, which the last test here pins.

TO SEE THIS GO RED: remove the second half of ``GENERIC_HIGH_RISK_PATHS`` in
``daedalus/sensitivity.py``. ``TheOrdinaryLaneStaysOpenTests`` is the other
direction and goes red if someone "fixes" this by fencing everything.

ONE ENTRY IS BARE, AND IT WAS MEASURED THAT WAY: the anchored
``/daedalus/kairos/gated_writes`` left ``_gated_writes_legacy.py.src``
WRITABLE, one underscore away. ``gated_writes`` matches both.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from daedalus.sensitivity import (  # noqa: E402
    DEFAULT_POLICY,
    GENERIC_HIGH_RISK_PATHS,
    change_risk,
    load_policy,
    path_write_blocked,
)

#: Everything a candidate write lane may never touch, whatever the project.
PINNED = (
    "AGENTS.md",
    "CLAUDE.md",
    "docs/IKARUS_ARIADNE_MASTER_PLAN.md",
    "docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl",
    "docs/IKARUS_ARIADNE_MASTER_PLAN.lock",
    "tools/iron_plan_guard.py",
    "tools/run_gate_checks.py",
    ".agentenv/agentenv.json",
    ".agentenv/tool-allowances.json",
    ".git/config",
    ".git/hooks/pre-commit",
    ".claude/settings.json",
    "daedalus/kairos/gated_writes.py",
    "daedalus/kairos/_gated_writes_legacy.py.src",
    "daedalus/sensitivity.py",
)

#: Ordinary product paths. If any of these ever blocks, the fence has stopped
#: being a fence and become a wall.
ORDINARY = (
    "src/app/view.py",
    "README.md",
    "docs/ARCHITECTURE.md",
    "docs/HANDOFF.md",
    "tests/test_smoke.py",
    "utils/clamp.py",
    "TCT_app/gui/scan_panel.py",
    "my_tools/helper.py",          # not "/tools/"
    "mycontroller/core.py",        # the existing anchoring case
)


class DefaultPolicyPinsTheGovernanceTests(unittest.TestCase):

    def test_every_pinned_path_is_refused_with_no_project(self):
        for rel in PINNED:
            with self.subTest(path=rel):
                self.assertTrue(
                    path_write_blocked(rel, None),
                    f"{rel} is writable by an unattended lane with no --project")

    def test_the_same_holds_for_the_explicit_default_policy(self):
        """``policy=None`` and ``DEFAULT_POLICY`` are the same door; a fix that
        only closed one of them would be worse than none."""
        for rel in PINNED:
            with self.subTest(path=rel):
                self.assertTrue(path_write_blocked(rel, DEFAULT_POLICY), rel)

    def test_windows_separators_and_case_do_not_open_it(self):
        for rel in (r"AGENTS.md", r".agentenv\agentenv.json",
                    r"docs\IKARUS_ARIADNE_MASTER_PLAN.md", r".git\config"):
            with self.subTest(path=rel):
                self.assertTrue(path_write_blocked(rel, None), rel)

    def test_an_absolute_path_does_not_open_it(self):
        for rel in (r"C:\repo\AGENTS.md", "/home/u/repo/.agentenv/agentenv.json"):
            with self.subTest(path=rel):
                self.assertTrue(path_write_blocked(rel, None), rel)

    def test_a_project_policy_cannot_remove_the_pins(self):
        """``load_policy`` unions the generic floor in. A project that declares
        its own ``high_risk_paths`` extends it and never replaces it."""
        policy = load_policy({"policy": {"high_risk_paths": ["/mine/"]}})
        for entry in GENERIC_HIGH_RISK_PATHS:
            self.assertIn(entry, policy.high_risk_path_substrings)
        for rel in PINNED:
            with self.subTest(path=rel):
                self.assertTrue(path_write_blocked(rel, policy), rel)

    def test_a_project_policy_that_declares_nothing_cannot_remove_them(self):
        policy = load_policy({})
        for rel in PINNED:
            with self.subTest(path=rel):
                self.assertTrue(path_write_blocked(rel, policy), rel)

    def test_the_pinned_paths_also_read_as_high_change_risk(self):
        """``change_risk`` reads the same tuple, so a task naming one of these
        paths must not be routed as a low-risk edit."""
        for rel in ("AGENTS.md", "tools/iron_plan_guard.py", ".git/config"):
            with self.subTest(path=rel):
                self.assertEqual(change_risk("tidy comments", [rel]), "high")


class TheOrdinaryLaneStaysOpenTests(unittest.TestCase):
    """The other direction. Without this, fencing the entire repo would pass
    every assertion above while making the write lane useless."""

    def test_ordinary_paths_remain_writable(self):
        for rel in ORDINARY:
            with self.subTest(path=rel):
                self.assertFalse(
                    path_write_blocked(rel, None),
                    f"{rel} became unwritable; the fence over-reached")

    def test_the_pre_existing_fence_entries_are_untouched(self):
        self.assertTrue(path_write_blocked("controller/core.py", None))
        self.assertTrue(path_write_blocked(r"controller\core.py", None))
        self.assertFalse(path_write_blocked("mycontroller/core.py", None))
        self.assertEqual(change_risk("tidy comments", ["controller/core.py"]),
                         "high")
        self.assertEqual(change_risk("tidy comments", ["utils/clamp.py"]), "low")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
