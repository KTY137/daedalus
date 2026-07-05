import tempfile
import unittest
from pathlib import Path

from daedalus.config import STARTER
from daedalus.verifier import verify

VALID = {"status": "done", "summary": "ok", "files_changed": ["a.md"],
         "tests_run": [], "risks": [], "todos": [], "handoff": {}}


class VerifyGateTests(unittest.TestCase):
    def test_starter_test_command_is_opt_in(self):
        # A freshly-init'd repo has no test suite -- writes must NOT be gated on a
        # nonexistent one (regression: pytest-by-default rolled back real writes).
        self.assertIsNone(STARTER["test_command"])

    def test_test_cwd_dot_resolves_to_repo_root(self):
        # test_cwd is relative to the TARGET repo, not the offload process cwd.
        # The command writes a file in its cwd; it must land in repo_root.
        with tempfile.TemporaryDirectory() as d:
            cmd = "python -c \"open('proof','w').write('1')\""
            vr = verify(VALID, d, test_command=cmd, test_cwd=".", disk_changed=["a.md"])
            self.assertTrue(vr.ok, vr.as_dict())
            self.assertTrue((Path(d) / "proof").exists(), "test ran outside repo_root")

    def test_lint_gate_fails_on_lint_error(self):
        # A .py write with a real lint error (undefined name / unused import) that
        # py_compile's syntax-only check misses must fail the gate -> escalate.
        from unittest.mock import patch
        rep = {**VALID, "files_changed": ["m.py"]}
        with patch("daedalus.verifier._py_compile", return_value=(True, "ok")), \
                patch("daedalus.verifier._lint_py", return_value=(False, "F821 undefined name 'x'")):
            vr = verify(rep, "/repo", disk_changed=["m.py"])
        self.assertFalse(vr.ok)
        self.assertIn("lint:m.py", vr.failed)

    def test_lint_gate_passes_when_clean(self):
        from unittest.mock import patch
        rep = {**VALID, "files_changed": ["m.py"]}
        with patch("daedalus.verifier._py_compile", return_value=(True, "ok")), \
                patch("daedalus.verifier._lint_py", return_value=(True, "clean")):
            vr = verify(rep, "/repo", disk_changed=["m.py"])
        self.assertTrue(vr.ok, vr.as_dict())


if __name__ == "__main__":
    unittest.main()
