"""The self-policy must CONFINE writes, not merely describe confinement.

WHY THIS FILE EXISTS. `docs/PROPOSED_SELF_POLICY.md` proposed a policy for
Daedalus's own repo and claimed, in prose:

    "The ONLY paths a candidate patch may touch. Everything else is denied by
     default_deny, so this list is the whole permission."

Measured against `path_write_blocked` -- the function the local write lane
actually calls -- that claim was false. `allow` and `default_deny` are read by
`classify_data` (the EGRESS axis) and by nothing on the write axis. 8 of 12
paths the document claimed to deny were writable, including `daedalus/config.py`,
which loads the policy. A candidate could have rewritten the policy loader.

So the tests below assert on the PREDICATE, never on the document, and the
confinement they pin is `write_allow`.

RED-WHEN-DISABLED, verified by actually disabling it: deleting the
`if policy.write_allow:` block in `sensitivity.path_write_blocked` turns
`test_general_source_is_blocked` red on all 8 paths (measured, see the
docstring on that test). Deleting `write_allow` from `.agentenv/agentenv.json`
turns `test_installed_policy_confines_writes` red.
"""

import json
import unittest
from pathlib import Path

from daedalus.config import (
    REPO_CONFIG,
    STARTER,
    resolve_project,
    resolve_write_wave_policy,
)
from daedalus.sensitivity import (
    _within_write_allow,
    change_risk,
    load_policy,
    path_write_blocked,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

# The 8 paths that leaked under the drafted policy. Named individually rather
# than globbed: a glob would silently shrink if the tree were reorganised, and
# this list is the regression, not an illustration of it.
LEAKED_UNDER_THE_DRAFT = (
    "daedalus/core.py",
    "daedalus/offload.py",
    "daedalus/router.py",
    "daedalus/providers/ollama.py",
    "daedalus/cli.py",
    "daedalus/health.py",
    "daedalus/config.py",
    "pyproject.toml",
)

CONFINED = {"policy": {"write_allow": ["docs/", "tests/", "README.md"]}}


class WriteAllowSemanticsTests(unittest.TestCase):
    """`write_allow` is an ALLOW list, so a loose match errs toward permitting.
    It must therefore be prefix-anchored, unlike every deny list in the module.
    """

    def setUp(self):
        self.pol = load_policy(CONFINED)

    def test_subtree_entries_admit_their_subtree(self):
        for p in ("docs/HANDOFF.md", "docs/notes/deep/x.md", "tests/test_x.py"):
            self.assertFalse(path_write_blocked(p, self.pol), p)

    def test_file_entries_admit_exactly_that_file(self):
        self.assertFalse(path_write_blocked("README.md", self.pol))
        # ...and not a same-named file somewhere else in the tree.
        self.assertTrue(path_write_blocked("vendor/README.md", self.pol))

    def test_file_entries_do_not_extend_to_descendants(self):
        """REGRESSION, found by Codex in review one hour after shipping.

        The first `_within_write_allow` matched a file entry with
        `anchored.startswith(e + "/")`, so every DESCENDANT of a file entry
        passed -- `README.md/payload.py` was writable while the docstring
        directly above the code said file entries name exactly one file.

        This test is the whole reason the sibling test above is not enough:
        `vendor/README.md` probes the wrong direction (a same-named file
        ELSEWHERE) and stayed green through the entire bug. Only a descendant
        probes the semantics that were actually claimed.
        """
        for rel in ("README.md/payload.py", "README.md/nested/deep.py",
                    "README.md/.agentenv/agentenv.json"):
            with self.subTest(path=rel):
                self.assertTrue(path_write_blocked(rel, self.pol), rel)
        # The directory entries must still extend, or the fix over-corrected.
        self.assertFalse(path_write_blocked("docs/nested/deep/x.md", self.pol))

    def test_within_write_allow_file_entry_is_equality_only(self):
        # Same claim at the helper level, where it is unambiguous.
        self.assertTrue(_within_write_allow("readme.md", ("readme.md",)))
        self.assertFalse(_within_write_allow("readme.md/x.py", ("readme.md",)))
        self.assertTrue(_within_write_allow("docs/x.py", ("docs/",)))

    def test_confinement_is_not_substring_matching(self):
        # THE BUG THIS PREVENTS: `"docs/" in "evildocs/payload.py"` is True.
        # A substring confinement would have admitted an attacker-named
        # top-level directory, i.e. leaked in the one direction it exists to
        # stop. Both of these are prefix-anchored misses.
        self.assertTrue(path_write_blocked("evildocs/payload.py", self.pol))
        self.assertTrue(path_write_blocked("vendor/docs/x.py", self.pol))

    def test_entries_are_normalised_so_a_dead_entry_is_impossible(self):
        # Matching runs against a lower-cased, forward-slashed path, so a
        # literal "README" / "Docs\\" entry could never match anything. Under a
        # DENY list a dead entry is harmless; under a confinement list it reads
        # as "I permitted this" while permitting nothing.
        pol = load_policy({"policy": {"write_allow": ["Docs\\", "README.MD"]}})
        self.assertEqual(pol.write_allow, ("docs/", "readme.md"))
        self.assertFalse(path_write_blocked("docs/x.md", pol))

    def test_empty_write_allow_means_unconfined(self):
        # The field is opt-in. An empty list must be byte-identical to the
        # previous behaviour, or shipping it would silently confine every other
        # repo's write lane.
        pol = load_policy({"policy": {}})
        self.assertEqual(pol.write_allow, ())
        self.assertFalse(path_write_blocked("some/ordinary/module.py", pol))

    def test_within_write_allow_handles_leading_slashes_either_way(self):
        self.assertTrue(_within_write_allow("docs/x.md", ("docs/",)))
        self.assertTrue(_within_write_allow("/docs/x.md", ("/docs/",)))
        self.assertFalse(_within_write_allow("docsx/y.md", ("docs/",)))


class ConfinementNarrowsButNeverWidensTests(unittest.TestCase):
    """A confinement list must not become a way to UNBLOCK something."""

    def test_secret_floor_still_wins_inside_the_allowed_subtree(self):
        pol = load_policy({"policy": {"write_allow": ["docs/"]}})
        self.assertTrue(path_write_blocked("docs/credentials.md", pol))
        self.assertTrue(path_write_blocked("docs/prod.env", pol))

    def test_named_high_risk_paths_still_win_inside_the_allowed_subtree(self):
        pol = load_policy({"policy": {"write_allow": ["docs/"],
                                      "high_risk_paths": ["docs/adrs/"]}})
        self.assertFalse(path_write_blocked("docs/HANDOFF.md", pol))
        self.assertTrue(path_write_blocked("docs/adrs/ADR-013.md", pol))

    def test_mixed_case_high_risk_entry_is_live_not_decorative(self):
        pol = load_policy({
            "policy": {
                "write_allow": ["Docs/"],
                "high_risk_paths": ["Docs/MASTER_PLAN.MD"],
            }
        })
        self.assertIn("docs/master_plan.md", pol.high_risk_path_substrings)
        self.assertTrue(path_write_blocked("docs/MASTER_PLAN.md", pol))
        self.assertEqual(
            change_risk("edit documentation", ["DOCS/master_plan.md"], pol),
            "high",
        )

    def test_simulated_exemption_does_not_tunnel_under_confinement(self):
        # `*_simulated.py` is exempted from the deny lists so a weak model may
        # touch fake hardware backends. Under an explicit confinement that
        # exemption would instead be a way to skip the high-risk check, so it
        # is disabled whenever write_allow is set.
        pol = load_policy({"policy": {"write_allow": ["docs/"]}})
        self.assertTrue(path_write_blocked("daedalus/devices/motor_simulated.py", pol))


class InstalledSelfPolicyTests(unittest.TestCase):
    """The policy actually installed in THIS repo, read from disk.

    These read `.agentenv/agentenv.json` rather than a fixture on purpose: the
    thing that must be true is a property of the installed file, and a fixture
    would keep passing after someone widened the real one.
    """

    @classmethod
    def setUpClass(cls):
        cls.pdata = resolve_project(str(REPO_ROOT))
        if not cls.pdata or not cls.pdata.get("policy"):
            raise unittest.SkipTest(f"no {REPO_CONFIG} in {REPO_ROOT}")
        cls.pol = load_policy(cls.pdata)

    def test_the_policy_file_is_valid_json_with_a_policy_block(self):
        raw = json.loads((REPO_ROOT / REPO_CONFIG).read_text(encoding="utf-8"))
        self.assertIn("policy", raw)
        self.assertTrue(raw["policy"].get("write_allow"),
                        "write_allow is what makes the allow-list real for WRITES; "
                        "without it `allow` governs egress only and source is writable")

    def test_installed_policy_confines_writes(self):
        self.assertTrue(self.pol.write_allow)

    def test_docs_and_tests_are_writable(self):
        # If this goes red the loop has nothing it may touch and the policy is
        # pointless -- the failure mode opposite to a leak.
        self.assertFalse(path_write_blocked("docs/HANDOFF.md", self.pol))
        self.assertFalse(path_write_blocked("tests/test_smoke.py", self.pol))

    def test_general_source_is_blocked(self):
        """The 8 paths that leaked under the drafted policy.

        RED-WHEN-DISABLED RECEIPT, measured by actually disabling the
        confinement block in `path_write_blocked`: 9 tests fail, and **6 of
        these 8 subtests** report writable -- core, router, providers/ollama,
        cli, health, pyproject.toml.

        The two that stayed blocked are the interesting ones. `offload.py` and
        `config.py` are ALSO named in the installed policy's `high_risk_paths`,
        so a second, independent mechanism catches them. That is what the
        belt-and-braces in `.agentenv/agentenv.json` is for, and this is the
        measurement showing it does real work rather than restating write_allow.
        Do not "fix" this docstring to say 8 -- 8 was the guess, 6 is the
        reading.
        """
        for rel in LEAKED_UNDER_THE_DRAFT:
            with self.subTest(path=rel):
                self.assertTrue(path_write_blocked(rel, self.pol),
                                f"{rel} is writable by the local model")

    def test_the_safety_core_is_blocked(self):
        for rel in ("daedalus/sensitivity.py", "daedalus/budget.py",
                    "daedalus/spine/attempt.py", "daedalus/kairos/worktree.py",
                    "tools/operability_drill.py"):
            with self.subTest(path=rel):
                self.assertTrue(path_write_blocked(rel, self.pol), rel)

    def test_the_policy_cannot_rewrite_itself(self):
        # The one that matters most: a candidate that can edit the policy file
        # or the loader has, in one move, all of the permissions above.
        for rel in (".agentenv/agentenv.json", "daedalus/config.py"):
            with self.subTest(path=rel):
                self.assertTrue(path_write_blocked(rel, self.pol), rel)

    def test_iron_plan_and_ledger_are_live_high_risk_fences(self):
        for rel in (
            "docs/IKARUS_ARIADNE_MASTER_PLAN.md",
            "docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl",
            ".gitattributes",
        ):
            with self.subTest(path=rel):
                self.assertTrue(path_write_blocked(rel, self.pol), rel)
                self.assertEqual(change_risk("edit documentation", [rel], self.pol),
                                 "high")

    def test_installed_policy_disables_automatic_write_wave_promotion(self):
        raw = json.loads((REPO_ROOT / REPO_CONFIG).read_text(encoding="utf-8"))
        self.assertEqual(raw.get("write_wave_policy"), "never")
        self.assertEqual(resolve_write_wave_policy(self.pdata), "never")
        self.assertEqual(
            resolve_write_wave_policy({"write_wave_policy": "always"}),
            "never",
        )
        self.assertEqual(
            resolve_write_wave_policy({"write_wave_policy": "low_risk"}),
            "never",
        )
        self.assertEqual(
            STARTER.get("write_wave_policy"),
            "never",
            "newly scaffolded repos must not arm automatic promotion",
        )


if __name__ == "__main__":
    unittest.main()
