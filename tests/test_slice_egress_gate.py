"""Slice egress gate -- the assembled slice (the payload this product sends to a
model) must not carry secrets, in ANY lane, and must never withhold silently.

Two tiers (see daedalus/sensitivity.py):
  * SECRET FLOOR -- unconditional, every lane. High-precision, secret-ONLY: a
    planted .env / private key / real credential is withheld; ordinary engine
    source (token_policy.py, api_key=None kwargs) is NOT.
  * ALLOW-LIST / default-deny -- untrusted lane only; unchanged egress behaviour.

Withholding is reported (sorted ``withheld`` block + inline breadcrumb), and a
denied FOCUS fails closed rather than returning a neighbour slice in its place.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from daedalus.structcore import build_index, semantic_slice
from daedalus.sensitivity import secret_floor_rule, slice_egress_rule


# A syntactically valid PEM private-key block (fake bytes, real shape).
FAKE_PEM = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    "MIIEowIBAAKCAQEA0000000000000000000000000000000000000000000000\n"
    "-----END RSA PRIVATE KEY-----\n"
)


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Unit: the floor and the two-tier gate, in isolation.                        #
# --------------------------------------------------------------------------- #
class SecretFloorUnitTest(unittest.TestCase):
    def test_path_markers_fire(self):
        for p in ("config/.env", "deploy/id_rsa", "certs/server.pem",
                  "home/.ssh/known_hosts", "vault/app.keystore"):
            self.assertIsNotNone(secret_floor_rule(p), p)

    def test_private_key_content_fires(self):
        self.assertIsNotNone(secret_floor_rule("app/util.py", FAKE_PEM))

    def test_value_shaped_credentials_fire(self):
        for blob in (
            "aws = 'AKIAIOSFODNN7EXAMPLE'",
            "tok = 'ghp_" + "a" * 36 + "'",
            "g = 'AIza" + "b" * 35 + "'",
            "s = 'sk_live_" + "c" * 24 + "'",
        ):
            self.assertIsNotNone(secret_floor_rule("app/util.py", blob), blob)

    def test_ordinary_source_is_not_a_secret(self):
        # B1: the bare word "token" must NOT be a secret signal.
        for p in ("daedalus/runtimes/providers/token_policy.py",
                  "daedalus/interfaces/cli/token_monitor.py",
                  "daedalus/structcore/tokens.py", "daedalus/structcore/index.py"):
            self.assertIsNone(secret_floor_rule(p), p)

    def test_kwargs_are_not_secrets(self):
        # B2: api_key=None / password: are function params, not credentials.
        for txt in ("def f(api_key=None):\n    return api_key\n",
                    "class C:\n    api_key: str | None = None\n",
                    "password = get_password()  # noqa\n"):
            self.assertIsNone(secret_floor_rule("daedalus/providers/x.py", txt), txt)

    def test_trusted_lane_never_default_denies(self):
        # Ordinary source: floor clean, trusted lane allows, untrusted denies it
        # (default-deny allow-list -- the existing egress behaviour, unchanged).
        p, txt = "daedalus/structcore/index.py", "def build_index():\n    return {}\n"
        self.assertIsNone(slice_egress_rule(p, txt, lane="trusted"))
        self.assertIsNotNone(slice_egress_rule(p, txt, lane="untrusted"))

    def test_floor_wins_in_every_lane(self):
        self.assertIsNotNone(slice_egress_rule("app/util.py", FAKE_PEM, lane="trusted"))
        self.assertIsNotNone(slice_egress_rule("app/util.py", FAKE_PEM, lane="untrusted"))


# --------------------------------------------------------------------------- #
# Integration: the gate inside semantic_slice.                                #
# --------------------------------------------------------------------------- #
class SliceGateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "proj/__init__.py", "")
        # core imports keys (dependency) and is imported by app (caller).
        _write(self.root, "proj/keys.py",
               "PRIVATE = '''" + FAKE_PEM + "'''\n\n\ndef load():\n    return PRIVATE\n")
        _write(self.root, "proj/core.py",
               "from proj import keys\n\n\ndef run():\n    return keys.load()\n")
        _write(self.root, "proj/app.py",
               "from proj import core\n\n\ndef main():\n    return core.run()\n")
        self.idx = build_index(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_secret_neighbour_content_never_reaches_slice_text(self):
        res = semantic_slice(self.root, "proj/core.py", idx=self.idx)
        # THERMOMETER: the planted private key must NOT be in the payload.
        self.assertNotIn("BEGIN RSA PRIVATE KEY", res["slice_text"])
        self.assertNotIn("PRIVATE = ", res["slice_text"])

    def test_withheld_is_reported_not_silent(self):
        res = semantic_slice(self.root, "proj/core.py", idx=self.idx)
        withheld = {w["file"]: w for w in res["withheld"]}
        self.assertIn("proj/keys.py", withheld)
        self.assertEqual(res["withheld_count"], len(res["withheld"]))
        # inline breadcrumb reaches the model, not just the JSON envelope.
        self.assertIn("WITHHELD", res["slice_text"])
        self.assertIn("proj/keys.py", res["slice_text"])

    def test_secret_neighbour_dropped_from_included(self):
        res = semantic_slice(self.root, "proj/core.py", idx=self.idx)
        self.assertNotIn("proj/keys.py", {i["file"] for i in res["included"]})

    def test_symbol_path_also_gates(self):
        # keys.load() is a callee of core.run -- its body must not slip into the
        # symbol-level CALLEES block.
        res = semantic_slice(self.root, "proj/core.py::run", idx=self.idx)
        self.assertNotIn("BEGIN RSA PRIVATE KEY", res["slice_text"])
        self.assertIn("proj/keys.py", {w["file"] for w in res["withheld"]})

    def test_focus_secret_fails_closed(self):
        res = semantic_slice(self.root, "proj/keys.py", idx=self.idx)
        self.assertEqual(res["n_included"], 0)
        self.assertEqual(res["included"], [])
        self.assertEqual(res["withheld_count"], 1)
        self.assertEqual(res["withheld"][0]["role"], "focus")
        self.assertNotIn("BEGIN RSA PRIVATE KEY", res["slice_text"])
        # fail-closed: does NOT return the neighbour (app.py) slice instead.
        self.assertNotIn("def main", res["slice_text"])

    def test_ordinary_neighbour_not_withheld_trusted(self):
        # app.py is an ordinary caller of core -- trusted lane must include it.
        res = semantic_slice(self.root, "proj/core.py", idx=self.idx)
        files = {i["file"] for i in res["included"]}
        self.assertIn("proj/app.py", files)
        self.assertEqual(res["withheld"], [w for w in res["withheld"]
                                           if w["file"] != "proj/app.py"])

    def test_untrusted_focus_fails_closed_default_deny(self):
        # In the untrusted lane an ordinary (non-allow-listed) focus is refused
        # by default-deny -- the existing egress behaviour, now applied to the
        # slice. This is why "untrusted" is not the default lane.
        res = semantic_slice(self.root, "proj/core.py", idx=self.idx, lane="untrusted")
        self.assertEqual(res["n_included"], 0)
        self.assertEqual(res["withheld"][0]["role"], "focus")


class UntrustedNeighbourTierTest(unittest.TestCase):
    """Untrusted lane, with an ALLOW-LISTED focus so neighbours are actually
    reached: the floor still withholds the secret dep, and default-deny now
    ALSO withholds the ordinary (non-allow-listed) dep. Floor is lane-invariant;
    the allow-list tier is the only thing that changes."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "proj/__init__.py", "")
        _write(self.root, "proj/keys.py",
               "PRIVATE = '''" + FAKE_PEM + "'''\n\n\ndef load():\n    return PRIVATE\n")
        _write(self.root, "proj/util.py", "def fmt(v):\n    return str(v)\n")
        # focus path carries "test_" -> allow-listed even under default-deny.
        _write(self.root, "proj/test_hub.py",
               "from proj import keys\nfrom proj import util\n\n\n"
               "def go():\n    return util.fmt(keys.load())\n")
        self.idx = build_index(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_floor_and_default_deny_both_apply(self):
        res = semantic_slice(self.root, "proj/test_hub.py", idx=self.idx, lane="untrusted")
        self.assertNotIn("BEGIN RSA PRIVATE KEY", res["slice_text"])
        withheld = {w["file"]: w["rule"] for w in res["withheld"]}
        self.assertIn("proj/keys.py", withheld)        # floor
        self.assertIn("proj/util.py", withheld)        # default-deny
        # attribution differs: secret rule vs egress rule.
        self.assertIn("secret", withheld["proj/keys.py"])
        self.assertNotIn("secret", withheld["proj/util.py"])

    def test_trusted_lane_keeps_ordinary_dep(self):
        res = semantic_slice(self.root, "proj/test_hub.py", idx=self.idx, lane="trusted")
        files = {i["file"] for i in res["included"]}
        self.assertIn("proj/util.py", files)                 # ordinary: kept
        self.assertNotIn("proj/keys.py", files)              # secret: floor withholds

    def test_withheld_sorted_deterministic(self):
        res = semantic_slice(self.root, "proj/test_hub.py", idx=self.idx, lane="untrusted")
        files = [w["file"] for w in res["withheld"]]
        self.assertEqual(files, sorted(files))


class PathMarkerNeighbourTest(unittest.TestCase):
    """The path-marker tier of the floor, exercised on a real import neighbour
    (not just via the unit test): a dependency whose rel path carries a secret
    marker is withheld even though its content is clean."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "proj/__init__.py", "")
        _write(self.root, "proj/vault/__init__.py", "")
        # path contains "id_rsa" -> floor path marker; body is innocuous.
        _write(self.root, "proj/vault/id_rsa_loader.py",
               "def loader():\n    return 42\n")
        _write(self.root, "proj/core.py",
               "from proj.vault import id_rsa_loader\n\n\n"
               "def run():\n    return id_rsa_loader.loader()\n")
        self.idx = build_index(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_path_marker_neighbour_withheld(self):
        res = semantic_slice(self.root, "proj/core.py", idx=self.idx)
        withheld = {w["file"] for w in res["withheld"]}
        self.assertIn("proj/vault/id_rsa_loader.py", withheld)
        self.assertNotIn("proj/vault/id_rsa_loader.py",
                         {i["file"] for i in res["included"]})


class NoRegressionCleanSliceTest(unittest.TestCase):
    """A slice with no secrets must be untouched: empty withheld, no breadcrumb,
    same neighbourhood as before the gate."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "proj/__init__.py", "")
        _write(self.root, "proj/core.py", "def helper(x):\n    return x * 2\n")
        _write(self.root, "proj/app.py",
               "from proj import core\n\n\ndef main():\n    return core.helper(1)\n")
        self.idx = build_index(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_clean_slice_has_empty_withheld(self):
        res = semantic_slice(self.root, "proj/core.py", idx=self.idx)
        self.assertEqual(res["withheld"], [])
        self.assertEqual(res["withheld_count"], 0)
        self.assertNotIn("WITHHELD", res["slice_text"])
        self.assertIn("proj/app.py", {i["file"] for i in res["included"]})


if __name__ == "__main__":
    unittest.main()
