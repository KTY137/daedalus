# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Movement I -- the additive ``include_focus`` param on ``semantic_slice``.

Consumer: the offload rewrite path already puts the target file body in the
prompt, so it asks for the NEIGHBOURHOOD only (``include_focus=False``): the FOCUS
body is replaced by a one-line header, but the focus SOURCE is still read + still
resolves the symbol's callees/callers, and -- the load-bearing safety invariant --
the FOCUS GATE (floor scan of the FULL focus text, fail-closed) runs FIRST and
IDENTICALLY regardless of the flag. Default ``True`` stays byte-identical to today
(the other slice test files are the evidence); these tests pin the False branch
and the default-path equality.
"""
import tempfile
import unittest
from pathlib import Path

from daedalus.structcore import build_index, semantic_slice


# The exact tail of the omitted-focus header (ASCII ``--``, matching file style).
OMITTED = "(body omitted -- supplied separately)"

# A syntactically valid PEM private-key block (fake bytes, real shape) -- the same
# marker the egress-gate tests use; trips the unconditional secret floor.
FAKE_PEM = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    "MIIEowIBAAKCAQEA0000000000000000000000000000000000000000000000\n"
    "-----END RSA PRIVATE KEY-----\n"
)

# A unique token planted in a FOCUS body -> present in slice_text iff the body is
# actually emitted, so its absence proves the omission.
FOCUS_MARKER = "MARKER_FOCUS_BODY_DO_NOT_EMIT"

CORE = (
    "def helper(x):\n"
    f"    # {FOCUS_MARKER}\n"
    '    """Return x doubled."""\n'
    "    return x * 2\n"
)
APP = (
    "from proj import core\n\n\n"
    "def main():\n"
    "    return core.helper(21)\n"
)


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _chunky(mod_i: int) -> str:
    """A dep with 12 fat function signatures -> a non-trivial skeleton, so a tight
    token budget must actually shed whole neighbours (mirrors the budget test)."""
    return "\n\n".join(
        f"def {chr(97 + mod_i)}_function_number_{j}(argument_one, argument_two, "
        f"argument_three):\n    return argument_one + argument_two + {j}"
        for j in range(12)
    ) + "\n"


class ModulePathOmitTest(unittest.TestCase):
    """(1) Module path, include_focus=False: header line only, body absent,
    neighbours still present, included[0] reported mode 'omitted'."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "proj/__init__.py", "")
        _write(self.root, "proj/core.py", CORE)
        _write(self.root, "proj/app.py", APP)
        self.idx = build_index(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_module_omit_header_body_absent_neighbours_present(self):
        res = semantic_slice(self.root, "proj/core.py", idx=self.idx, include_focus=False)
        text = res["slice_text"]
        # slice_text STARTS with the single-line omitted header.
        self.assertTrue(
            text.startswith(f"# ===== FOCUS: proj/core.py {OMITTED} ====="), text[:120])
        # the focus BODY is absent.
        self.assertNotIn(FOCUS_MARKER, text)
        # neighbour section still present (app.py imports core -> CALLERS skeleton).
        self.assertIn("# ===== CALLERS (skeleton) =====", text)
        self.assertIn("proj/app.py", text)
        # included[0] is the focus, reported as mode "omitted".
        self.assertEqual(res["included"][0]["role"], "focus")
        self.assertEqual(res["included"][0]["mode"], "omitted")
        self.assertEqual(res["included"][0]["file"], "proj/core.py")


class SymbolPathOmitTest(unittest.TestCase):
    """(2) Symbol path (file.py::symbol), include_focus=False: callees + callers
    still emitted (resolved from the REAL source), focus body absent."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "pkg/__init__.py", "")
        _write(self.root, "pkg/core.py", "def helper(x):\n    return x * 2\n")
        _write(self.root, "pkg/util.py", "def fmt(v):\n    return str(v)\n")
        _write(self.root, "pkg/app.py",
               "from pkg import core\nfrom pkg.util import fmt\n\n\n"
               "def main():\n"
               f"    # {FOCUS_MARKER}\n"
               "    return fmt(core.helper(21))\n")
        # a caller of main(), so the CALLERS block is exercised too.
        _write(self.root, "pkg/driver.py",
               "from pkg import app\n\n\ndef drive():\n    return app.main()\n")
        self.idx = build_index(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_symbol_omit_callees_and_callers_emitted_body_absent(self):
        res = semantic_slice(self.root, "pkg/app.py::main", idx=self.idx, include_focus=False)
        text = res["slice_text"]
        self.assertEqual(res["focus_symbol"], "main")
        # header line only; focus body (main's, incl. the marker) is absent.
        self.assertTrue(
            text.startswith(f"# ===== FOCUS: pkg/app.py::main {OMITTED} ====="), text[:120])
        self.assertNotIn(FOCUS_MARKER, text)
        self.assertEqual(res["included"][0]["mode"], "omitted")
        # callees still resolved from the real source: helper + fmt bodies present.
        self.assertIn("# ===== CALLEES (symbol-level, approximate) =====", text)
        self.assertIn("def helper", text)
        self.assertIn("def fmt", text)
        callee_files = {i["file"] for i in res["included"] if i["role"] == "callee"}
        self.assertEqual(callee_files, {"pkg/core.py", "pkg/util.py"})
        # callers still resolved too: driver.drive() calls main().
        self.assertIn("# ===== CALLERS (symbol-level, approximate) =====", text)
        caller_files = {i["file"] for i in res["included"] if i["role"] == "caller"}
        self.assertEqual(caller_files, {"pkg/driver.py"})


class SecretFocusFailsClosedIdenticallyTest(unittest.TestCase):
    """(3) SECRET-BEARING focus file: the fail-closed refusal is IDENTICAL with
    include_focus=False and =True -- omission runs the gate first and cannot
    bypass or alter it. The gate returns before the include_focus branch."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "proj/__init__.py", "")
        # focus file itself carries a private key -> focus gate fails closed.
        _write(self.root, "proj/keys.py",
               "PRIVATE = '''" + FAKE_PEM + "'''\n\n\ndef load():\n    return PRIVATE\n")
        # a clean caller, so a bypass would have SOMETHING to leak in its place.
        _write(self.root, "proj/app.py",
               "from proj import keys\n\n\ndef main():\n    return keys.load()\n")
        self.idx = build_index(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_omit_cannot_bypass_focus_gate_module_and_symbol(self):
        for target in ("proj/keys.py", "proj/keys.py::load"):
            kept = semantic_slice(self.root, target, idx=self.idx, include_focus=True)
            omit = semantic_slice(self.root, target, idx=self.idx, include_focus=False)
            # full result dict is identical -> same breadcrumb slice_text, same
            # withheld entry, same everything. Omission changes nothing here.
            self.assertEqual(omit, kept, target)
            # and it really is the fail-closed refusal:
            self.assertEqual(omit["n_included"], 0, target)
            self.assertEqual(omit["withheld_count"], 1, target)
            self.assertEqual(omit["withheld"][0]["role"], "focus", target)
            self.assertNotIn("BEGIN RSA PRIVATE KEY", omit["slice_text"], target)
            # fail-closed: the clean caller (app.py) is NOT returned in its place.
            self.assertNotIn("def main", omit["slice_text"], target)


class BudgetOmitTest(unittest.TestCase):
    """(4) Tight max_tokens + include_focus=False: the omitted FOCUS header and the
    WITHHELD block are kept, neighbours are dropped, the TRIMMED marker is present,
    no crash."""

    DEPS = [f"d{i}" for i in range(5)]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "proj/__init__.py", "")
        imports = "".join(f"from proj import {d}\n" for d in self.DEPS)
        imports += "from proj import secret\n"
        body = "".join(f"    {d}.{chr(97 + i)}_function_number_0(1, 2, 3)\n"
                        for i, d in enumerate(self.DEPS))
        _write(self.root, "proj/focus.py", imports + "\n\ndef run():\n" + body)
        for i, d in enumerate(self.DEPS):
            _write(self.root, f"proj/{d}.py", _chunky(i))
        # a secret dependency -> withheld by the floor even on the trusted lane.
        _write(self.root, "proj/secret.py",
               "PRIVATE = '''" + FAKE_PEM + "'''\n\n\ndef load():\n    return PRIVATE\n")
        self.idx = build_index(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_tight_budget_keeps_omitted_focus_and_withheld_drops_neighbours(self):
        full = semantic_slice(self.root, "proj/focus.py", idx=self.idx, include_focus=False)
        self.assertGreaterEqual(full["withheld_count"], 1)          # secret dep withheld
        cap = full["slice_tokens"] // 3                             # forces a real trim
        res = semantic_slice(self.root, "proj/focus.py", idx=self.idx,
                             max_tokens=cap, include_focus=False)
        text = res["slice_text"]
        self.assertGreater(res["trimmed_count"], 0)                 # degrade exercised
        # the omitted FOCUS header survives (never the body).
        self.assertTrue(text.startswith(f"# ===== FOCUS: proj/focus.py {OMITTED} ====="))
        self.assertNotIn("def run():", text)                        # body really omitted
        # WITHHELD breadcrumb survives the trim -- the whole point.
        self.assertIn("# ===== WITHHELD (egress gate) =====", text)
        self.assertIn("proj/secret.py", text)
        self.assertNotIn("BEGIN RSA PRIVATE KEY", text)             # secret never leaks
        # honest, visible TRIMMED marker, kept as the last block.
        self.assertTrue(text.rstrip().endswith("to fit budget ====="))


class DefaultPathEqualityTest(unittest.TestCase):
    """(5) include_focus=True explicit == the omitted-param call: identical result
    dict on the same fixture, guarding the byte-identical default path."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "proj/__init__.py", "")
        _write(self.root, "proj/core.py", CORE)
        _write(self.root, "proj/app.py", APP)
        self.idx = build_index(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_default_equals_explicit_true_module(self):
        default = semantic_slice(self.root, "proj/core.py", idx=self.idx)
        explicit = semantic_slice(self.root, "proj/core.py", idx=self.idx, include_focus=True)
        self.assertEqual(default, explicit)

    def test_default_equals_explicit_true_symbol(self):
        default = semantic_slice(self.root, "proj/core.py::helper", idx=self.idx)
        explicit = semantic_slice(self.root, "proj/core.py::helper",
                                  idx=self.idx, include_focus=True)
        self.assertEqual(default, explicit)


if __name__ == "__main__":
    unittest.main()
