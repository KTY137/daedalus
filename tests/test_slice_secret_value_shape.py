"""Regression for Cerberus's CRITICAL: plaintext credentials must not leak into a
slice on ANY lane, and the value-shape rule must not fire on ordinary kwargs.

Reproduced by hand against the pre-fix tree: password/token in a callee body
reached slice_text via all three paths with withheld=[]. This pins the close.
"""
import tempfile
import unittest
from pathlib import Path

from daedalus.sensitivity import secret_floor_rule
from daedalus.structcore.index import build_index
from daedalus.structcore.slice import semantic_slice


class SecretFloorPrecisionTests(unittest.TestCase):
    def test_catches_quoted_credential_values(self):
        for line in (
            'password = "hunter2-SuperSecret-Prod-9animals"',
            "token = 'Bearer 1a2b3c4d5e6f7a8b9c0d1e2f'",
            'API_KEY = "sekret_live_value_do_not_share_1234"',
            "client_secret: 'abcdef1234567890xyz'",
        ):
            self.assertIsNotNone(secret_floor_rule("x.py", line), line)

    def test_does_not_fire_on_kwargs_or_labels(self):
        for line in (
            "api_key: str | None = None",
            "api_key=None",
            "api_key=self.api_key",
            'mode = "run"',
            "def token_bag(source, spec): ...",
            r'r"\bsecret\b\s*[=:]",',   # sensitivity.py's own pattern literal
        ):
            self.assertIsNone(secret_floor_rule("x.py", line), line)

    def test_engine_token_files_are_not_floored_by_path(self):
        # The bootstrap depends on these staying distillable.
        for p in ("daedalus/token_policy.py", "daedalus/structcore/tokens.py"):
            self.assertIsNone(secret_floor_rule(p, "x = 1\n"), p)


class SliceLeakTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "app.py").write_text(
            "from creds import connect\n\ndef run():\n    return connect()\n", encoding="utf-8")
        (self.root / "creds.py").write_text(
            'def connect():\n'
            '    password = "hunter2-SuperSecret-Prod-9animals"\n'
            '    token = "Bearer 1a2b3c4d5e6f7a8b9c0d1e2f3a4b"\n'
            '    return (password, token)\n', encoding="utf-8")
        self.idx = build_index(str(self.root))

    def _assert_clean(self, res):
        t = res.get("slice_text", "")
        self.assertNotIn("hunter2", t)
        self.assertNotIn("1a2b3c", t)

    def test_symbol_slice_does_not_leak(self):
        r = semantic_slice(str(self.root), "app.py::run", idx=self.idx)
        self._assert_clean(r)
        self.assertTrue(r.get("withheld"), "leak blocked but not reported")

    def test_module_slice_does_not_leak(self):
        self._assert_clean(semantic_slice(str(self.root), "creds.py", idx=self.idx))

    def test_secret_file_as_focus_fails_closed(self):
        r = semantic_slice(str(self.root), "creds.py::connect", idx=self.idx)
        self._assert_clean(r)
        self.assertEqual(r.get("n_included"), 0)


if __name__ == "__main__":
    unittest.main()
