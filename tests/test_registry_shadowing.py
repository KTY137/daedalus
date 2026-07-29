"""Naming a project must never grant more write permission than not naming one.

FOUND BY THE PRODUCT-SURFACE AGENT, 2026-07-29, while trying to render the
write-confinement gate honestly -- it could not, because the gate reported two
different answers for the same repository.

`resolve_project(repo_root, project)` returned the REGISTRY entry
`projects/<name>.json` whenever a project name was supplied, and consulted the
repo-local `.agentenv/agentenv.json` only when none was. Registry entries
predate `write_allow` and carry none, and `path_write_blocked` treats an empty
`write_allow` as "unconfined" by design. So the confinement installed that same
morning evaporated the moment a task was dispatched as `--project agent_env`.

MEASURED before the fix, on this repository::

    no project        write_allow ('docs/','tests/','readme.md')
      BLOCKED  daedalus/sensitivity.py
      BLOCKED  daedalus/config.py
      BLOCKED  .agentenv/agentenv.json

    --project agent_env   write_allow () == UNCONFINED
      WRITABLE  daedalus/sensitivity.py     <- the egress fence
      WRITABLE  daedalus/config.py          <- the policy loader
      WRITABLE  .agentenv/agentenv.json     <- the policy itself

Same shape as the defect `write_allow` was introduced to fix, one day later:
a fence the code consults only sometimes.

RED-WHEN-DISABLED: remove the `_apply_repo_confinement(...)` call from
`resolve_project` and every test in `RegistryMustNotShadowTheRepoTests` fails,
with the three paths above reported WRITABLE.
"""

import unittest
from pathlib import Path

from daedalus.config import resolve_project
from daedalus.sensitivity import intersect_write_allow, load_policy, path_write_blocked

REPO_ROOT = Path(__file__).resolve().parents[1]

# The three that matter most: the fence, the loader, and the policy itself.
# A candidate that reaches any one of them has, in one move, all the rest.
SELF_PROTECTING = (
    "daedalus/sensitivity.py",
    "daedalus/config.py",
    ".agentenv/agentenv.json",
)


def _policy_for(project):
    data = resolve_project(str(REPO_ROOT), project)
    if not data or not data.get("policy"):
        return None
    return load_policy(data)


class RegistryMustNotShadowTheRepoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bare = _policy_for(None)
        if cls.bare is None or not cls.bare.write_allow:
            raise unittest.SkipTest(
                "this repo declares no write_allow, so there is nothing to shadow")
        cls.named = _policy_for("agent_env")

    def test_the_named_project_still_resolves(self):
        # Control. Without this the assertions below could pass because the
        # registry entry vanished, which would prove nothing about confinement.
        self.assertIsNotNone(self.named)

    def test_naming_a_project_does_not_unconfine(self):
        self.assertTrue(
            self.named.write_allow,
            "naming a project dropped the repo's own write confinement")

    def test_naming_a_project_grants_no_extra_path(self):
        """The invariant, stated directly: no path may become writable purely
        because a project was named."""
        for rel in SELF_PROTECTING + ("daedalus/core.py", "daedalus/cli.py",
                                      "pyproject.toml"):
            with self.subTest(path=rel):
                self.assertTrue(path_write_blocked(rel, self.bare), f"setup: {rel}")
                self.assertTrue(
                    path_write_blocked(rel, self.named),
                    f"{rel} is writable under --project but not without it")

    def test_the_permitted_lane_still_works_under_a_named_project(self):
        # A confinement that blocks everything would pass the test above while
        # making the product useless. Both directions or neither.
        for rel in ("docs/HANDOFF.md", "tests/test_smoke.py"):
            with self.subTest(path=rel):
                self.assertFalse(path_write_blocked(rel, self.named), rel)


class IntersectWriteAllowTests(unittest.TestCase):
    """The merge rule itself, where it is unambiguous."""

    def test_an_empty_list_means_unconfined_and_yields_to_the_other(self):
        self.assertEqual(intersect_write_allow((), ("docs/",)), ("docs/",))
        self.assertEqual(intersect_write_allow(("docs/",), ()), ("docs/",))
        self.assertEqual(intersect_write_allow((), ()), ())

    def test_the_more_specific_entry_survives(self):
        # Prefix semantics: docs/sub/ is inside docs/, so the intersection is
        # docs/sub/ -- the narrower of the two, never the wider.
        self.assertEqual(intersect_write_allow(("docs/",), ("docs/sub/",)),
                         ("docs/sub/",))
        self.assertEqual(intersect_write_allow(("docs/sub/",), ("docs/",)),
                         ("docs/sub/",))

    def test_disjoint_confinements_permit_nothing(self):
        # The fail-closed direction, and deliberately NOT special-cased back
        # into "unconfined" -- that collapse is the whole bug this guards.
        self.assertEqual(intersect_write_allow(("docs/",), ("src/",)), ())

    def test_an_overlap_keeps_only_the_overlap(self):
        got = intersect_write_allow(("docs/", "tests/"), ("docs/", "src/"))
        self.assertEqual(got, ("docs/",))


if __name__ == "__main__":
    unittest.main()
