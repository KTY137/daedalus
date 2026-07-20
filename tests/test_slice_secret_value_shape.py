"""Regression for Cerberus's CRITICAL: plaintext credentials must not leak into a
slice on ANY lane, and the value-shape rule must not fire on ordinary kwargs.

Reproduced by hand against the pre-fix tree: password/token in a callee body
reached slice_text via all three paths with withheld=[]. This pins the close.
"""
import tempfile
import unittest
from pathlib import Path

import daedalus.sensitivity as _sensitivity
from daedalus.sensitivity import secret_floor_rule
from daedalus.structcore.index import build_index
from daedalus.structcore.slice import semantic_slice

_DAEDALUS_DIR = Path(_sensitivity.__file__).resolve().parent


class SecretFloorPrecisionTests(unittest.TestCase):
    def test_catches_quoted_credential_values(self):
        for line in (
            'password = "hunter2-SuperSecret-Prod-9animals"',
            "token = 'Bearer 1a2b3c4d5e6f7a8b9c0d1e2f'",
            'API_KEY = "sekret_live_value_do_not_share_1234"',
            "client_secret: 'abcdef1234567890xyz'",
        ):
            self.assertIsNotNone(secret_floor_rule("x.py", line), line)

    # --- the FOUR bypass classes Cerberus re-review found open in d714128 ---
    # The committed tests only used bare-keyword forms (`password = "..."`) and
    # stayed green while every one of these leaked on the trusted lane.

    def test_class1_underscore_and_camel_glued_names_fire(self):
        # \b never fires inside a glued identifier; keyword must match as a
        # SUB-token. These are the exact payloads reproduced leaking.
        for line in (
            'DB_PASSWORD = "prod-db-pass-9animals-XYZ"',
            'access_token = "at-live-abcdef1234567890"',
            'SECRET_KEY = "django-insecure-QWERTYuiop12345"',   # keyword is a PREFIX
            'admin_password = "hunter2hunter2hunter2"',
            'refresh_token = "rtok-abcdef1234567890xyz"',
            'my_token = "sk-verysecretvalue-abcdef"',
            'refreshToken = "rtok-abcdef1234567890xyz"',        # camelCase
            'apiKey = "at-live-abcdef1234567890"',              # camelCase
        ):
            self.assertIsNotNone(secret_floor_rule("x.py", line), line)

    def test_class2_string_prefixes_fire(self):
        for line in (
            'password = f"hunter2hunter2interp"',
            'password = b"hunter2hunter2bytes"',
            'password = r"hunter2hunter2raw12"',
            'password = rb"hunter2hunter2rawby"',
            'TOKEN = F"HUNTER2HUNTER2CAPS12"',   # IGNORECASE covers the prefix too
        ):
            self.assertIsNotNone(secret_floor_rule("x.py", line), line)

    def test_class3_triple_quoted_values_fire(self):
        for line in (
            'password = """triplequotedsecret123"""',
            "secret = '''triplequotedsecret123'''",
            'API_KEY = """another-triple-secret-val"""',
        ):
            self.assertIsNotNone(secret_floor_rule("x.py", line), line)

    def test_class4_short_values_fire_and_threshold_is_pinned(self):
        # Threshold is {4,}: a keyword bound to a quoted literal is already a
        # strong signal, and leaking even a 4-char PIN/pwd is worse than dropping
        # one file. 6- and 4-char values MUST fire; 3 and below deliberately do
        # not (this pins the choice so a silent bump back toward {8,} is caught).
        for hit in ('pwd = "a1b2c3"', 'pwd = "abcd"', 'password = "snip"'):
            self.assertIsNotNone(secret_floor_rule("x.py", hit), hit)
        for miss in ('pwd = "abc"', 'pwd = "ab"', 'pwd = ""'):
            self.assertIsNone(secret_floor_rule("x.py", miss), miss)

    # --- classes 5-6: the typed / config forms (second Cerberus review) ---

    def test_class5_annotated_assignments_fire(self):
        # A typed field (pydantic/dataclass/settings) -- name : Type = "value".
        for line in (
            'api_key: str = "sk-live-supersecretvalue"',
            'SECRET_KEY: str = "django-insecure-abcdef123"',
            'token: Optional[str] = "sometokenvalue123"',
            "api_key : str = 'spaced-before-colon-val'",
            'password: str = """triplesecretannotated"""',   # annotated + triple
        ):
            self.assertIsNotNone(secret_floor_rule("x.py", line), line)

    def test_class6_quoted_key_forms_fire(self):
        # dict-literal / JSON secret -- the keyword sits inside quotes.
        for line in (
            'data = {"password": "hunter2secretvalue"}',
            "cfg = {'api_key': 'sk-live-verysecret'}",
            '"api_key": "sk-live-verysecret-value-1234"',
            'config = {"authorization": "Bearer abcdef123456"}',  # header keyword
        ):
            self.assertIsNotNone(secret_floor_rule("x.py", line), line)

    def test_annotated_signature_and_attr_docstring_not_floored(self):
        # REGRESSION: the annotation group must not devour a def signature and
        # let the post-operator whitespace cross a newline into a docstring. This
        # exact shape (a keyword-bearing param, then a triple-quoted docstring)
        # over-blocked daedalus/structcore/clones.py in the first annotated draft.
        for txt in (
            "def _fingerprint_of_tokens(tokens: list[str]) -> str:\n"
            '    """The Type-2 fingerprint, computed from a token list."""\n',
            "class C:\n    secret_field: str\n"
            '    """PEP-224 attribute docstring, not a value."""\n',
            "def handle(self, authorization: str) -> None:\n"
            '    """Docstring following an authorization param."""\n',
        ):
            self.assertIsNone(secret_floor_rule("daedalus/x.py", txt), txt)

    def test_glued_keyword_without_a_quoted_value_stays_clean(self):
        # The broadened left side must not fire on ordinary glued identifiers
        # that are NOT assigned a quoted literal.
        for line in (
            "access_token = get_token()",
            "self.refresh_token = other.refresh_token",
            "DB_PASSWORD = os.environ['DB_PASSWORD']",
            "token_count = 5",
            "def tokenize(secret_input): ...",
        ):
            self.assertIsNone(secret_floor_rule("x.py", line), line)

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


class GluedCredentialSliceLeakTests(unittest.TestCase):
    """Integration: an underscore-glued credential in a DEPENDENCY body (the
    class-1 bypass) must never reach slice_text, and the drop must be reported,
    on BOTH the symbol path (mod.py::sym) and the module-focus path. The focus
    itself is clean so the neighbour is actually pulled in and gated (not
    fail-closed on the focus)."""

    SECRET = "at-live-abcdef1234567890deadbeef"

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "app.py").write_text(
            "from creds import connect\n\ndef run():\n    return connect()\n",
            encoding="utf-8")
        (self.root / "creds.py").write_text(
            "def connect():\n"
            f'    access_token = "{self.SECRET}"\n'
            "    return access_token\n", encoding="utf-8")
        self.idx = build_index(str(self.root))

    def _assert_gated(self, res):
        self.assertNotIn(self.SECRET, res.get("slice_text", ""))
        self.assertNotIn("access_token", res.get("slice_text", ""))
        self.assertTrue(res.get("withheld"), "secret dropped but not reported")

    def test_symbol_path_gates_glued_credential(self):
        self._assert_gated(semantic_slice(str(self.root), "app.py::run", idx=self.idx))

    def test_module_focus_path_gates_glued_credential(self):
        self._assert_gated(semantic_slice(str(self.root), "app.py", idx=self.idx))


class AnnotatedCredentialSliceLeakTests(unittest.TestCase):
    """Integration for class 5: a typed-field secret (`api_key: str = "..."`) in
    a dependency must never reach slice_text, on both the symbol and module-focus
    paths, with the drop reported."""

    SECRET = "sk-live-annotatedsupersecret-1234"

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "app.py").write_text(
            "from settings import build\n\ndef run():\n    return build()\n",
            encoding="utf-8")
        (self.root / "settings.py").write_text(
            "def build():\n"
            f'    api_key: str = "{self.SECRET}"\n'
            "    return api_key\n", encoding="utf-8")
        self.idx = build_index(str(self.root))

    def _assert_gated(self, res):
        self.assertNotIn(self.SECRET, res.get("slice_text", ""))
        self.assertTrue(res.get("withheld"), "annotated secret dropped but not reported")

    def test_symbol_path_gates_annotated_credential(self):
        self._assert_gated(semantic_slice(str(self.root), "app.py::run", idx=self.idx))

    def test_module_focus_path_gates_annotated_credential(self):
        self._assert_gated(semantic_slice(str(self.root), "app.py", idx=self.idx))


class SelfDistillabilityTests(unittest.TestCase):
    """The safety module and the token machinery must slice cleanly through the
    floor -- the whole Daedalus-on-Daedalus bootstrap depends on it. A broadened
    value-shape rule that fired on the engine's own source (its keyword lists,
    its regex literals, or a doc comment carrying a literal `name = "secret"`)
    would re-introduce the over-block this gate exists to avoid."""

    def _assert_source_not_floored(self, rel):
        src = (_DAEDALUS_DIR / rel).read_text(encoding="utf-8")
        self.assertIsNone(secret_floor_rule(f"daedalus/{rel}", src),
                          f"floor fired on engine's own {rel}")

    def test_sensitivity_own_source_not_floored(self):
        # After the doc comment was rewritten to drop the literal secret example.
        self._assert_source_not_floored("sensitivity.py")

    def test_token_machinery_source_not_floored(self):
        for rel in ("token_policy.py", "token_monitor.py", "structcore/tokens.py"):
            self._assert_source_not_floored(rel)

    def test_clones_source_not_floored(self):
        # structcore/clones.py over-blocked in the first annotated draft: a
        # `tokens: list[str]) -> str:` signature + docstring tripped the floor.
        self._assert_source_not_floored("structcore/clones.py")


if __name__ == "__main__":
    unittest.main()
