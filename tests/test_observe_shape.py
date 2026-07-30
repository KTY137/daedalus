"""The observation layer's contract: shape, never value — and honest ignorance.

The negative tests carry the weight. An observer that quietly copies a payload is
a memory bug and a disclosure; one that reports "no fields" where it means "I
could not look" turns absence of evidence into evidence of absence.
"""
from __future__ import annotations

import unittest

from daedalus.observe import shape as sh


class ShapeNeverValue(unittest.TestCase):
    def test_a_dict_reports_keys_and_no_values_anywhere(self):
        secret = {"api_key": "sk-live-do-not-leak", "host": "10.0.0.9"}
        s = sh.describe(secret)
        blob = repr(s.to_dict())
        self.assertIn("api_key", blob, "key names are the discovery")
        self.assertNotIn("sk-live", blob, "a VALUE must never reach the record")
        self.assertNotIn("10.0.0.9", blob)

    def test_a_string_reports_length_not_content(self):
        s = sh.describe("correct horse battery staple")
        self.assertEqual(s.family, sh.TEXT)
        self.assertEqual(s.length, 28)
        self.assertNotIn("horse", repr(s.to_dict()))

    def test_the_element_probe_of_a_sequence_is_also_shape_only(self):
        s = sh.describe([{"token": "abc123"}, {"token": "def456"}])
        self.assertEqual(s.family, sh.SEQUENCE)
        self.assertIsNotNone(s.element)
        self.assertIn("token", repr(s.element.to_dict()))
        self.assertNotIn("abc123", repr(s.to_dict()))


class Bounds(unittest.TestCase):
    def test_names_are_clipped_but_the_true_count_survives(self):
        big = {f"col_{i}": i for i in range(sh.MAX_NAMES + 40)}
        s = sh.describe(big)
        self.assertEqual(len(s.names), sh.MAX_NAMES)
        self.assertEqual(s.n_names, sh.MAX_NAMES + 40, "the real count must not be lost")
        self.assertTrue(s.truncated)

    def test_a_long_name_is_clipped(self):
        s = sh.describe({"x" * 500: 1})
        self.assertLessEqual(len(s.names[0]), sh.MAX_NAME_CHARS)

    def test_nesting_stops_at_the_depth_bound(self):
        deep = {"a": {"b": {"c": {"d": {"e": 1}}}}}
        s = sh.describe(deep)
        depth = 0
        while s.element is not None:
            depth += 1
            s = s.element
        self.assertLessEqual(depth, sh.MAX_DEPTH)


class Redaction(unittest.TestCase):
    def test_the_redact_hook_reaches_every_name(self):
        s = sh.describe({"patient_id": 1, "dose": 2}, redact=lambda n: "REDACTED")
        self.assertEqual(set(s.names), {"REDACTED"})


class DuckTyping(unittest.TestCase):
    """No scientific library is imported; everything is probed by attribute."""

    def test_an_array_like_needs_no_numpy(self):
        class FakeFlags:
            c_contiguous, f_contiguous = True, False

        class FakeArray:
            dtype, shape, nbytes, flags = "float64", (4, 5), 160, FakeFlags()

        s = sh.describe(FakeArray())
        self.assertEqual(s.family, sh.ARRAY)
        self.assertEqual(s.dims, (4, 5))
        self.assertEqual(s.layout, "C-contiguous")

    def test_an_attribute_that_refuses_truthiness_does_not_raise(self):
        """A pandas Index raises on __bool__. The first version of describe()
        used ``getattr(...) or ()`` and blew up on a real DataFrame."""
        class Hostile(list):
            def __bool__(self):
                raise ValueError("The truth value of an Index is ambiguous")

        class FakeFrame:
            columns = Hostile(["a", "b"])
            shape = (2, 2)

        s = sh.describe(FakeFrame())          # must not raise
        self.assertEqual(s.family, sh.TABLE)
        self.assertEqual(list(s.names), ["a", "b"])

    def test_an_uncharacterisable_object_says_so(self):
        class Weird:
            __slots__ = ()

        s = sh.describe(Weird())
        self.assertEqual(s.family, sh.OPAQUE)
        self.assertTrue(s.note)


class Determinism(unittest.TestCase):
    def test_signature_is_stable_for_equal_shapes(self):
        a = sh.describe({"x": 1, "y": 2})
        b = sh.describe({"x": 9, "y": 8})
        self.assertEqual(a.signature(), b.signature(),
                         "the signature describes shape, so equal shapes match")

    def test_signature_changes_when_the_shape_changes(self):
        a = sh.describe({"x": 1})
        b = sh.describe({"x": 1, "z": 2})
        self.assertNotEqual(a.signature(), b.signature())


class TheJoin(unittest.TestCase):
    def test_a_declared_field_absent_from_the_observation_is_reported(self):
        s = sh.describe({"voltage": 1.0, "current": 2.0, "run": 3})
        c = sh.compare_declared(s, ["voltage", "current", "temperature"])
        self.assertFalse(c.agrees)
        self.assertEqual(c.missing_in_observation, ("temperature",))
        self.assertEqual(c.undeclared_in_observation, ("run",))

    def test_it_refuses_to_compare_rather_than_manufacturing_findings(self):
        """An observation with no names would otherwise report EVERY declared
        field as missing — turning 'we learned nothing' into a wall of noise."""
        class FakeArray:
            dtype, shape, nbytes = "float64", (4,), 32

        c = sh.compare_declared(sh.describe(FakeArray()), ["voltage", "current"])
        self.assertFalse(c.comparable)
        self.assertEqual(c.missing_in_observation, ())
        self.assertIn("no field names", c.reason)

    def test_nothing_declared_is_also_not_comparable(self):
        c = sh.compare_declared(sh.describe({"a": 1}), [])
        self.assertFalse(c.comparable)

    def test_a_truncated_observation_suppresses_the_missing_claim(self):
        """While the name list is clipped, 'declared but absent' cannot be
        distinguished from 'declared and past the bound'."""
        big = {f"c{i}": i for i in range(sh.MAX_NAMES + 5)}
        c = sh.compare_declared(sh.describe(big), ["c0", "not_there_at_all"])
        self.assertEqual(c.missing_in_observation, ())
        self.assertTrue(any("clipped" in n for n in c.notes))


class ProvenanceIsStamped(unittest.TestCase):
    def test_every_observation_says_it_is_observed(self):
        self.assertEqual(sh.describe({"a": 1}).provenance, "observed")
        self.assertEqual(sh.describe({"a": 1}).to_dict()["provenance"], "observed")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
