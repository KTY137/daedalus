# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""F1b: the control root may not be relocated by an in-process env write.

WHAT WENT WRONG, MEASURED ON THIS BOX (2026-08-22). ``control_root`` read
``%USERPROFILE%`` out of the environment of the very process it protects. With
``%USERPROFILE%`` and ``%LOCALAPPDATA%`` both pointed at fresh temp directories
before the first :class:`KillSwitch` construction -- which is what a harness
that "sandboxes the environment" does, in-process, before anything else runs::

    control_root()      -> ...\\Temp\\heracles-seams2-home-qqhk94xi\\.daedalus\\control\\2ea46e496ce4
    legacy_control_root -> ...\\Temp\\heracles-seams2-la-mk7hjrdi\\daedalus\\control\\2ea46e496ce4
    arm(force=True)     -> running=True
    control_check.ok    -> True

Two failures in one move. The operator's ``C:\\Users\\<u>\\.daedalus\\control``
is not the file the loop watches, so a stop written there is never read -- the
F1 bug again, by a different road. And the pre-migration refusal inspected a
temp directory instead of the real ``%LOCALAPPDATA%`` root, which on this box
genuinely holds ``killswitch``, ``effect-leases.sqlite3`` and
``effect-lease-issuer.key``: the replay window that refusal exists to catch was
waved through. ``_CONTROL_CHECK_CACHE`` is keyed by the root path, so the first
process to verify a moved root also decided the answer for every later reader.

WHAT THESE TESTS PIN. The profile directory comes from the OPERATING SYSTEM
(``shell32.SHGetKnownFolderPath``/``SHGetFolderPathW`` on Windows,
``pwd.getpwuid`` elsewhere), frozen in :data:`OS_PROFILE_DIR` at import; and a
DERIVED switch whose environment disagrees with it REFUSES rather than arming
at the moved address. A refusal, not a silent correction: writing the permit to
a path the caller does not believe in is the same lie one directory along.

TO SEE THEM GO RED, disable the guard rather than trusting the assertions:

  * ``RelocatedProfileIsARefusalTests`` and ``CacheCannotLaunderARelocatedRootTests``
    -- make :func:`profile_root_disagreement` ``return None`` unconditionally,
    or delete the ``if check.ok and self._derived_path:`` block in
    ``KillSwitch.control_check``. MEASURED with the first mutation:
    ``arm(force=True) -> running=True`` at the temp-dir permit again.
  * ``OperatingSystemProfileIsStableTests`` -- make ``_resolve_os_profile_dir``
    read ``os.environ["USERPROFILE"]`` first.

NOT COVERED, and named rather than implied: :mod:`daedalus.kernel.offload_lease`
and :mod:`daedalus.kernel.promotion_trust_root` still derive their roots from
:func:`control_root` without consulting :func:`profile_root_disagreement`, so a
relocated environment still moves the lease ledger and the promotion ledger.
Closing that is a one-line call in each of those modules and belongs to
whoever owns them; this file does not pretend it is already done.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from daedalus.spine.killswitch import (  # noqa: E402
    ENV_SWITCH_PATH,
    KillSwitch,
    LoopHalted,
    OS_PROFILE_DIR,
    OS_PROFILE_SOURCE,
    _PROFILE_SOURCE_ENV,
    control_root,
    os_control_root,
    profile_root_disagreement,
    verify_control_root,
)

REPO = r"C:\some\repo"


def _moved_profile(home: str, local_appdata: str | None = None):
    """Move every variable a home directory can hide in, and drop the permit
    override so the switch under test is a DERIVED one.

    ``%LOCALAPPDATA%`` moves too, because that is the reported shape -- a layer
    that relocates "the environment" moves all of them -- and because leaving
    it alone makes these tests depend on whether the box running them happens
    to hold pre-migration state under the real one.
    """
    env = {k: v for k, v in os.environ.items() if k != ENV_SWITCH_PATH}
    env.update({"USERPROFILE": home, "HOME": home,
                "LOCALAPPDATA": local_appdata or os.path.join(home, "AppData",
                                                              "Local")})
    return mock.patch.dict(os.environ, env, clear=True)


class OperatingSystemProfileIsStableTests(unittest.TestCase):
    """The derivation half: the OS answer does not move when the env does."""

    def test_the_profile_source_is_the_operating_system(self):
        """If this is the environment fall-back, every refusal below is
        vacuous -- so the suite says so out loud instead of passing quietly."""
        if OS_PROFILE_SOURCE == _PROFILE_SOURCE_ENV:
            self.skipTest(
                "this interpreter could not ask the OS for the profile "
                "directory; the relocation guard is inactive here by design")
        self.assertTrue(Path(OS_PROFILE_DIR).is_absolute())

    def test_the_os_root_is_unchanged_by_moving_userprofile_and_home(self):
        before = os_control_root(REPO)
        with tempfile.TemporaryDirectory() as home, _moved_profile(home):
            self.assertEqual(os_control_root(REPO), before)

    def test_control_root_still_reports_the_moved_derivation_truthfully(self):
        """``control_root`` answers where THIS process's derivation lands. It
        is the switch that refuses to use it -- a function that quietly
        returned a different directory than it derived would be the same class
        of lie one layer down."""
        with tempfile.TemporaryDirectory() as home, _moved_profile(home):
            self.assertNotEqual(control_root(REPO), os_control_root(REPO))
            self.assertEqual(Path(control_root(REPO)).parts[:len(Path(home).parts)],
                             Path(home).parts)

    def test_an_unmoved_environment_derives_exactly_the_os_root(self):
        if OS_PROFILE_SOURCE == _PROFILE_SOURCE_ENV:
            self.skipTest("no OS answer to agree with on this interpreter")
        with mock.patch.dict(os.environ,
                             {"USERPROFILE": str(OS_PROFILE_DIR),
                              "HOME": str(OS_PROFILE_DIR)}):
            self.assertEqual(control_root(REPO), os_control_root(REPO))
            self.assertIsNone(profile_root_disagreement())


class RelocatedProfileIsARefusalTests(unittest.TestCase):
    """The detector half: a moved profile is STOP, not a new home."""

    def setUp(self):
        if OS_PROFILE_SOURCE == _PROFILE_SOURCE_ENV:
            self.skipTest("no OS answer to disagree with on this interpreter")

    def test_the_disagreement_names_both_directories(self):
        with tempfile.TemporaryDirectory() as home, _moved_profile(home):
            reason = profile_root_disagreement()
        self.assertIsNotNone(reason)
        self.assertIn(home, reason)
        self.assertIn(str(OS_PROFILE_DIR), reason)

    def test_a_derived_switch_refuses_to_arm_and_says_why(self):
        with tempfile.TemporaryDirectory() as home, _moved_profile(home):
            switch = KillSwitch()
            self.assertFalse(switch.control_check.ok)
            with self.assertRaises(LoopHalted) as caught:
                switch.arm(force=True)
            message = str(caught.exception)
            permit = switch.path
        self.assertIn("refusing to arm", message)
        self.assertIn(home, message)
        self.assertFalse(permit.exists(),
                         "the refusal still wrote the permit at the moved root")

    def test_force_does_not_override_it(self):
        """``force=True`` overrules an operator's stop marker. It may not
        overrule "this permit is at an address no operator can reach"."""
        with tempfile.TemporaryDirectory() as home, _moved_profile(home):
            with self.assertRaises(LoopHalted):
                KillSwitch().arm(force=True)

    def test_read_state_is_stopped_before_the_permit_is_read(self):
        with tempfile.TemporaryDirectory() as home, _moved_profile(home):
            switch = KillSwitch()
            switch.path.parent.mkdir(parents=True, exist_ok=True)
            switch.path.write_text("RUN\n")      # a perfectly valid permit
            state = switch.read_state()
        self.assertFalse(state.running)
        self.assertIn("control root is not usable", state.reason)
        self.assertIn("operating system reports", state.reason)

    def test_an_explicitly_named_permit_is_not_refused(self):
        """Both directions. A switch that refused EVERYTHING would satisfy
        every assertion above; a caller who names a path (a test, an operator
        with an unusual layout, ``DAEDALUS_KILLSWITCH``) chose it deliberately
        and is not the caller this refusal protects."""
        with tempfile.TemporaryDirectory() as home, _moved_profile(home), \
                tempfile.TemporaryDirectory() as d:
            switch = KillSwitch(Path(d) / "killswitch")
            self.assertTrue(switch.control_check.ok, switch.control_check.reason)
            self.assertTrue(switch.arm(force=True).running)
            self.assertFalse(switch.stop("test").running)


class CacheCannotLaunderARelocatedRootTests(unittest.TestCase):
    """``_CONTROL_CHECK_CACHE`` is keyed by path, so an ok verdict for the
    moved root is exactly what a first writer could leave behind for everyone
    else. The profile check runs per switch and before that cache is read."""

    def setUp(self):
        if OS_PROFILE_SOURCE == _PROFILE_SOURCE_ENV:
            self.skipTest("no OS answer to disagree with on this interpreter")

    def test_a_cached_ok_verdict_for_the_moved_root_does_not_arm_it(self):
        with tempfile.TemporaryDirectory() as home, _moved_profile(home):
            moved = control_root(REPO)
            seeded = verify_control_root(moved, check_legacy=False, use_cache=True)
            self.assertTrue(seeded.ok, seeded.reason)   # the cache now says yes
            switch = KillSwitch(repo_root=REPO)
            self.assertFalse(switch.control_check.ok)
            self.assertIn("operating system reports", switch.control_check.reason)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
