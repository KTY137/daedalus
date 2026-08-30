# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""F1: the kill switch's control root must be the directory it says it is.

WHAT WENT WRONG, MEASURED ON THIS BOX. The repo's ``python`` is the
Microsoft-Store shim
(``.../WindowsApps/PythonSoftwareFoundation.Python.3.10_qbz5n2kfra8p0``), which
virtualises ``%LOCALAPPDATA%``. ``default_switch_path`` derived the control
root from ``%LOCALAPPDATA%``, so::

    default_switch_path -> C:\\Users\\<u>\\AppData\\Local\\daedalus\\control\\<d>\\killswitch
    arm()               -> running=True
    cmd /c type <that>  -> "Das System kann den angegebenen Pfad nicht finden." rc=1
    echo STOP> <that>   -> rc=1
    read_state()        -> running=True        <-- THE STOP DID NOT STOP ANYTHING
    realpath(<that>)    -> ...\\AppData\\Local\\Packages\\PythonSoftwareFoundation.
                           Python.3.10_qbz5n2kfra8p0\\LocalCache\\Local\\daedalus\\...

The permit, the lease ledger and the issuer key were none of them where
``receipt.killswitch_path`` said. The same probe after the fix: the path is
under ``%USERPROFILE%\\.daedalus``, ``cmd /c type`` answers ``RUN`` rc=0, the
operator's ``echo STOP>`` returns rc=0, and ``read_state()`` reads
``running=False, reason='stop was requested'``.

WHAT THESE TESTS PIN, and it is deliberately not "do not use LOCALAPPDATA":
the placement is one bug, the class of bug is "this process cannot tell that
its writes are being redirected". So the checks are on the SYMPTOM -- a
realpath disagreement, and bytes a second process cannot read -- which a
virtualisation nobody here has heard of trips just the same.

TO SEE THEM GO RED, disable the guard rather than trusting the assertion:

  * ``KillSwitchRefusesAnUnusableControlRootTests`` -- delete the
    ``if not check.ok`` block at the top of ``KillSwitch.read_state`` and the
    one at the top of ``KillSwitch.arm``;
  * ``ControlRootIsUnderTheUserProfileTests`` -- restore the ``LOCALAPPDATA``
    base in ``control_root``;
  * ``LegacyControlRootIsARefusalTests`` -- delete the ``check_legacy`` block
    in ``_verify_control_root_uncached``;
  * ``ControlRootVerificationTests`` -- return an ``ok=True`` check
    unconditionally from ``verify_control_root``.

NOT COVERED, and named rather than implied: nothing here proves the Store shim
specifically is defeated on a machine that does not have it. The redirection
test synthesises the mismatch with a directory symlink, which is the same
mechanism from the filesystem's side; the Store case is recorded above as a
measurement, not asserted here.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from daedalus.spine.killswitch import (  # noqa: E402
    ENV_SWITCH_PATH,
    ControlRootCheck,
    KillSwitch,
    LEGACY_CONTROL_ARTIFACTS,
    LoopHalted,
    control_root,
    default_switch_path,
    legacy_control_root,
    repo_control_digest,
    verify_control_root,
)

REPO = r"C:\some\repo"


class ControlRootIsUnderTheUserProfileTests(unittest.TestCase):
    """The placement half of the fix."""

    def test_control_root_is_derived_from_userprofile_not_localappdata(self):
        """Both bases are set, to two different directories, so the assertion
        distinguishes them. (A single temp home would not: pytest's temp dirs
        live UNDER ``AppData\\Local`` on Windows, and a naive "no appdata in
        the path" check passes on the buggy code and fails on the fixed one --
        MEASURED, that is how this test first went red.)"""
        with tempfile.TemporaryDirectory() as home, \
                tempfile.TemporaryDirectory() as la, \
                mock.patch.dict(os.environ,
                                {"USERPROFILE": home, "LOCALAPPDATA": la}):
            root = control_root(REPO)
            parts = Path(root).parts
            self.assertEqual(parts[:len(Path(home).parts) + 2],
                             Path(home).parts + (".daedalus", "control"))
            self.assertNotIn(os.path.normcase(la), os.path.normcase(str(root)))

    def test_the_permit_is_the_control_root_plus_a_name(self):
        env = {k: v for k, v in os.environ.items() if k != ENV_SWITCH_PATH}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(default_switch_path(REPO).parent, control_root(REPO))
            self.assertEqual(default_switch_path(REPO).name, "killswitch")

    def test_the_repo_digest_did_not_change(self):
        """Renaming the namespace would orphan every existing control root."""
        repo = Path(__file__).resolve().parents[1]
        expected = hashlib.sha256(str(repo).encode("utf-8")).hexdigest()[:12]
        self.assertEqual(repo_control_digest(repo), expected)

    def test_the_legacy_root_is_still_computable_so_it_can_be_refused(self):
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": r"C:\la"}):
            legacy = legacy_control_root(REPO)
        self.assertIsNotNone(legacy)
        self.assertEqual(Path(legacy).parts[-3:-1], ("daedalus", "control"))


class ControlRootVerificationTests(unittest.TestCase):
    """The detector half: refuse what cannot be verified."""

    def test_an_ordinary_directory_passes_and_says_why(self):
        with tempfile.TemporaryDirectory() as d:
            check = verify_control_root(d, check_legacy=False, use_cache=False)
            self.assertTrue(check.ok, check.reason)
            self.assertIn("visible to another process", check.reason)
            self.assertEqual(os.path.normcase(check.path),
                             os.path.normcase(check.realpath))

    def test_a_redirected_root_is_refused_and_names_both_paths(self):
        """A symlink is the same mechanism the Store shim uses, seen from the
        filesystem's side: realpath disagrees with the literal path."""
        with tempfile.TemporaryDirectory() as d:
            real = Path(d) / "real"
            real.mkdir()
            link = Path(d) / "link"
            try:
                os.symlink(real, link, target_is_directory=True)
            except (OSError, NotImplementedError, AttributeError) as exc:
                self.skipTest(f"cannot create a directory link here: {exc}")
            check = verify_control_root(link, check_legacy=False, use_cache=False)
            self.assertFalse(check.ok)
            self.assertIn("REDIRECTED", check.reason)
            self.assertIn(str(link), check.reason)
            self.assertIn(str(real), check.reason)

    def test_a_root_a_second_process_cannot_read_is_refused(self):
        """The decisive check. The reader is made blind, which is exactly what
        a virtualised store looks like from in here: this process wrote the
        bytes and another process cannot see them."""
        import daedalus.spine.killswitch as ks

        def blind(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, b"",
                                               b"cannot find the path")

        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(ks.subprocess, "run", blind):
                check = verify_control_root(d, check_legacy=False,
                                            use_cache=False)
        self.assertFalse(check.ok)
        self.assertIn("second process cannot see the control root", check.reason)

    def test_the_check_never_raises(self):
        """``read_state`` is documented never to raise, and it calls this."""
        check = verify_control_root("\x00not a path", check_legacy=False,
                                    use_cache=False)
        self.assertFalse(check.ok)
        self.assertIsInstance(check.reason, str)


class LegacyControlRootIsARefusalTests(unittest.TestCase):
    """A fresh ledger beside a populated old one is a replay window."""

    def test_pre_migration_state_refuses_and_names_both_roots(self):
        with tempfile.TemporaryDirectory() as home, \
                tempfile.TemporaryDirectory() as la, \
                mock.patch.dict(os.environ,
                                {"USERPROFILE": home, "LOCALAPPDATA": la}):
            legacy = legacy_control_root(REPO)
            legacy.mkdir(parents=True)
            (legacy / "effect-leases.sqlite3").write_text("old state")
            check = verify_control_root(control_root(REPO), repo_root=REPO,
                                        check_legacy=True, use_cache=False)
            self.assertFalse(check.ok)
            self.assertIn("pre-migration", check.reason)
            self.assertIn("effect-leases.sqlite3", check.reason)
            self.assertIn(str(legacy), check.reason)
            self.assertIn(str(control_root(REPO)), check.reason)
            self.assertEqual(check.legacy_path, str(legacy))

    def test_an_empty_legacy_directory_is_not_state(self):
        """Refusing on a leftover empty directory would be a false alarm, and
        a false alarm teaches an operator to ignore this message."""
        with tempfile.TemporaryDirectory() as home, \
                tempfile.TemporaryDirectory() as la, \
                mock.patch.dict(os.environ,
                                {"USERPROFILE": home, "LOCALAPPDATA": la}):
            legacy_control_root(REPO).mkdir(parents=True)
            check = verify_control_root(control_root(REPO), repo_root=REPO,
                                        check_legacy=True, use_cache=False)
            self.assertTrue(check.ok, check.reason)

    def test_every_named_artifact_trips_it(self):
        for name in LEGACY_CONTROL_ARTIFACTS:
            with self.subTest(artifact=name), \
                    tempfile.TemporaryDirectory() as home, \
                    tempfile.TemporaryDirectory() as la, \
                    mock.patch.dict(os.environ,
                                    {"USERPROFILE": home, "LOCALAPPDATA": la}):
                legacy = legacy_control_root(REPO)
                legacy.mkdir(parents=True)
                (legacy / name).write_text("x")
                check = verify_control_root(control_root(REPO), repo_root=REPO,
                                            check_legacy=True, use_cache=False)
                self.assertFalse(check.ok, f"{name} did not trip the refusal")


class KillSwitchRefusesAnUnusableControlRootTests(unittest.TestCase):
    """The wiring: an unverifiable root is STOP, and arming is refused."""

    @staticmethod
    def _blind_switch(permit: Path) -> KillSwitch:
        switch = KillSwitch(permit)
        switch._control_check = ControlRootCheck(
            False, "synthetic: a second process cannot see the control root",
            str(permit.parent), "elsewhere")
        return switch

    def test_read_state_is_stopped_before_the_permit_is_even_read(self):
        with tempfile.TemporaryDirectory() as d:
            permit = Path(d) / "killswitch"
            permit.write_text("RUN\n")            # a perfectly valid permit
            state = self._blind_switch(permit).read_state()
            self.assertFalse(state.running)
            self.assertIn("control root is not usable", state.reason)
            self.assertIn("second process cannot see", state.reason)

    def test_arm_refuses_even_with_force(self):
        with tempfile.TemporaryDirectory() as d:
            switch = self._blind_switch(Path(d) / "killswitch")
            with self.assertRaises(LoopHalted) as caught:
                switch.arm(force=True)
            self.assertIn("refusing to arm", str(caught.exception))

    def test_a_usable_root_still_arms_and_stops_normally(self):
        """Both directions. Without this, a switch that refused EVERYTHING
        would pass every assertion above."""
        with tempfile.TemporaryDirectory() as d:
            switch = KillSwitch(Path(d) / "killswitch")
            self.assertTrue(switch.control_check.ok, switch.control_check.reason)
            self.assertTrue(switch.arm(force=True).running)
            self.assertFalse(switch.stop("test").running)

    def test_a_second_process_can_read_the_armed_permit(self):
        """The end-to-end property the whole finding is about: the operator is
        in another terminal, so the operator has to be able to read and write
        the very file this process is watching."""
        with tempfile.TemporaryDirectory() as d:
            permit = Path(d) / "killswitch"
            KillSwitch(permit).arm(force=True)
            cmd = (["cmd", "/c", "type", str(permit)] if os.name == "nt"
                   else ["cat", str(permit)])
            proc = subprocess.run(cmd, capture_output=True, timeout=30)
            self.assertIn(b"RUN", proc.stdout, proc.stderr)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
