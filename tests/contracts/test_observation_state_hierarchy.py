from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import daedalus.orchestration.conversation as conversation
import daedalus.health as health
import daedalus.kernel.contracts as contracts
from daedalus.kernel.contracts import observations
from daedalus.spine.effect_boundary import REGISTRY_BY_ID, registry_sha256


ROOT = Path(__file__).resolve().parents[2]
STATE_NAMES = ("WORKING", "PRESENT", "DEGRADED", "ABSENT", "UNKNOWN")
REGISTRY_SHA256 = "1afe32ac18cb6cb755a1bf9a3f5aa47834c3716298e8914c0cc6c983633aef3d"


def _assigned_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
            for target in targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def test_health_and_conversation_reexport_one_exact_observation_contract() -> None:
    assert contracts.observations is observations
    assert "observations" in dir(contracts)
    assert observations.OBSERVATION_STATES == (
        "working",
        "present",
        "degraded",
        "absent",
        "unknown",
    )
    assert health.STATES is observations.OBSERVATION_STATES
    assert conversation.OUTCOME_STATES is observations.OBSERVATION_STATES
    for name in STATE_NAMES:
        canonical = getattr(observations, name)
        assert getattr(health, name) is canonical
        assert getattr(conversation, name) is canonical


def test_observation_values_are_defined_only_by_the_kernel_contract() -> None:
    canonical_names = set(STATE_NAMES) | {"OBSERVATION_STATES"}
    assert canonical_names <= _assigned_names(
        ROOT / "daedalus" / "kernel" / "contracts" / "observations.py"
    )
    # Named as whole paths rather than as leaves under one parent: G1-FLAT-03
    # moved conversation.py into daedalus/orchestration/, and a loop that
    # rebuilt the path from a shared parent went looking for a file that had
    # moved instead of asserting on the one that exists.
    for path in (
        ROOT / "daedalus" / "health.py",
        ROOT / "daedalus" / "orchestration" / "conversation.py",
    ):
        assert canonical_names.isdisjoint(_assigned_names(path))


def test_cold_conversation_import_does_not_load_health_implementation() -> None:
    script = f"""
import json, sys
sys.path.insert(0, {str(ROOT)!r})
import daedalus.orchestration.conversation
print(json.dumps({{
    'health_loaded': 'daedalus.health' in sys.modules,
    'contract_loaded': 'daedalus.kernel.contracts.observations' in sys.modules,
}}))
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert json.loads(completed.stdout) == {
        "health_loaded": False,
        "contract_loaded": True,
    }


def test_health_effect_door_and_registry_digest_do_not_move() -> None:
    row = REGISTRY_BY_ID["cli.health"]
    assert row.target == "daedalus.health:main"
    assert tuple((anchor.target, anchor.call) for anchor in row.anchors) == (
        ("daedalus.health:main", "begin_effect"),
    )
    assert registry_sha256() == REGISTRY_SHA256
