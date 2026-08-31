from __future__ import annotations

from tools.run_gate_checks import G0_TESTS, G1_TESTS, PROFILES


def test_gate_check_profiles_are_deduplicated_and_cover_the_stack() -> None:
    assert len(G0_TESTS) == len(set(G0_TESTS))
    assert len(G1_TESTS) == len(set(G1_TESTS))
    consolidated = PROFILES["consolidated"]
    assert len(consolidated) == len(set(consolidated))
    assert set(G0_TESTS) | set(G1_TESTS) == set(consolidated)
    assert "tests/kernel/test_artifact_identity.py" in G0_TESTS
    assert "tests/test_architecture_boundaries.py" in G1_TESTS
    assert "tests/ignition/test_voltage_ignition.py" in G1_TESTS
