# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The picker's spectral enrichment is evidence and NOTHING else.

The load-bearing test in this file is
``test_enrichment_changes_no_candidate_no_score_no_order``: it pins the standing
invariant that the spectral layer cannot move the queue. If that one ever fails,
a measurement has become a gate and the mathematics has started deciding things
it was explicitly not allowed to decide.
"""

from __future__ import annotations

import unittest

from daedalus.spine import picker


def _state() -> dict:
    return {
        "islands": ["daedalus/mapping/reach.py", "lonely/island.py"],
        "shims": ["daedalus/decompose.py"],
        "test_only": ["daedalus/mapping/reach.py"],
        "counts": {"modules": 144},
        "digest": "sha256:deadbeef",
        "unknown": [],
    }


def _rows() -> dict:
    return {
        "daedalus/mapping/reach.py": {
            "spectral_package": "daedalus/mapping",
            "spectral_package_leak_rate": 0.42,
            "spectral_package_reads_as": "ordinary",
            "spectral_boundary_agreement": 0.95,
            "spectral_boundary_reads_as": "real seam",
            "spectral_fiedler_value": -0.013,
            "spectral_declared_modularity": 0.51,
            "spectral_modularity_beats_random": True,
        },
        "daedalus/decompose.py": {
            "spectral_package": "daedalus",
            "spectral_package_leak_rate": 0.9,
            "spectral_package_reads_as": "pass-through",
            "spectral_boundary_agreement": 0.55,
            "spectral_boundary_reads_as": "false wall",
            "spectral_fiedler_value": None,
            "spectral_declared_modularity": 0.51,
            "spectral_modularity_beats_random": True,
        },
    }


class SpectralEnrichmentIsEvidenceOnly(unittest.TestCase):

    def test_default_is_byte_identical_to_before_the_seam_existed(self):
        plain, plain_notes = picker.map_candidates(_state())
        explicit, explicit_notes = picker.map_candidates(_state(), spectral=None)
        self.assertEqual([c.evidence for c in plain],
                         [c.evidence for c in explicit])
        self.assertEqual(plain_notes, explicit_notes)
        for cand in plain:
            self.assertFalse([k for k in cand.evidence if k.startswith("spectral_")])

    def test_enrichment_changes_no_candidate_no_score_no_order(self):
        """THE INVARIANT. Spectral numbers are evidence, never a gate and never
        a band. Same task_ids, same scores, same order, same count."""
        plain, plain_notes = picker.map_candidates(_state())
        rich, rich_notes = picker.map_candidates(_state(), spectral=_rows())
        self.assertEqual([c.task_id for c in plain], [c.task_id for c in rich])
        self.assertEqual([c.score for c in plain], [c.score for c in rich])
        self.assertEqual([c.source for c in plain], [c.source for c in rich])
        self.assertEqual([c.reason for c in plain], [c.reason for c in rich])
        self.assertEqual([c.instruction for c in plain],
                         [c.instruction for c in rich])
        self.assertEqual(plain_notes, rich_notes)

    def test_enrichment_only_adds_keys_and_never_overwrites_a_measurement(self):
        plain, _ = picker.map_candidates(_state())
        rich, _ = picker.map_candidates(_state(), spectral=_rows())
        for before, after in zip(plain, rich):
            for key, value in before.evidence.items():
                self.assertEqual(after.evidence[key], value,
                                 f"{key} was overwritten by enrichment")
            added = set(after.evidence) - set(before.evidence)
            self.assertTrue(all(k.startswith("spectral_") for k in added), added)

    def test_a_module_with_no_spectral_row_gets_no_spectral_keys(self):
        """Absent means NOT MEASURED. A zero here would read as a finding."""
        rich, _ = picker.map_candidates(_state(), spectral=_rows())
        by_module = {c.evidence["module"]: c for c in rich}
        self.assertIn("spectral_package", by_module["daedalus/mapping/reach.py"].evidence)
        self.assertNotIn("spectral_package", by_module["lonely/island.py"].evidence)

    def test_islands_and_shims_are_both_enriched(self):
        rich, _ = picker.map_candidates(_state(), spectral=_rows())
        by_source = {}
        for cand in rich:
            by_source.setdefault(cand.source, []).append(cand)
        island = [c for c in by_source["map_island"]
                  if c.evidence["module"] == "daedalus/mapping/reach.py"][0]
        shim = by_source["map_shim"][0]
        self.assertEqual(island.evidence["spectral_boundary_reads_as"], "real seam")
        self.assertEqual(shim.evidence["spectral_package_reads_as"], "pass-through")

    def test_a_none_fiedler_value_survives_as_none(self):
        """None must reach the evidence dict intact -- collapsing it to 0.0
        would claim the module sits exactly on the seam."""
        rich, _ = picker.map_candidates(_state(), spectral=_rows())
        shim = [c for c in rich if c.source == "map_shim"][0]
        self.assertIn("spectral_fiedler_value", shim.evidence)
        self.assertIsNone(shim.evidence["spectral_fiedler_value"])

    def test_malformed_spectral_input_is_ignored_not_raised(self):
        for bad in ({}, {"daedalus/decompose.py": None},
                    {"daedalus/decompose.py": "not a mapping"},
                    {"daedalus/decompose.py": {}}):
            cands, _ = picker.map_candidates(_state(), spectral=bad)
            self.assertEqual(len(cands), 3)
            for cand in cands:
                self.assertFalse([k for k in cand.evidence
                                  if k.startswith("spectral_")])


class BuildQueueOptIn(unittest.TestCase):

    def test_include_spectral_defaults_off(self):
        import inspect
        sig = inspect.signature(picker.build_queue)
        self.assertIs(sig.parameters["include_spectral"].default, False)

    def test_off_by_default_reports_off_and_costs_nothing(self):
        queue = picker.build_queue(map_snapshot=_state(), use_attempt_memory=False,
                                   enforce_inventory_freshness=False)
        map_source = queue.sources.get("map") or {}
        if map_source.get("state") == "valid":
            self.assertEqual(map_source.get("spectral"), "off")


if __name__ == "__main__":
    unittest.main()
