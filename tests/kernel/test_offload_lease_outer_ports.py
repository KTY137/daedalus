from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from daedalus.chip_design.completion_publication import (
    record_chip_eda_publication,
    retain_chip_eda_terminal_artifact,
)
from daedalus.chip_design.execution_plan import EdaExecutionPlan
from daedalus.chip_design.lease_ports import validate_eda_execution_plan
from daedalus.chip_design.publication_verifier import (
    verify_chip_eda_publication_graph,
)
from daedalus.kernel import offload_lease
from daedalus.kernel.offload_lease import (
    EgressAdmissionObservation,
    WaveLeaseDenied,
    acquire_wave_offload_lease,
    lane_endpoint,
    wave_containment_roots,
)
from daedalus.orchestration.workspace_containment import resolve_worktree_root
from daedalus.runtimes.admission.offload_egress import (
    admit_offload_egress,
    resolve_lane_endpoint,
)
from daedalus.sensitivity import Policy
from daedalus.spine.effect_boundary import GuardDecision, registry_sha256
from daedalus.spine.killswitch import KillSwitch


ROOT = Path(__file__).resolve().parents[2]
KERNEL_PATH = ROOT / "daedalus" / "kernel" / "offload_lease.py"
FORBIDDEN_PREFIXES = (
    "daedalus.chip_design",
    "daedalus.eval",
    "daedalus.gates",
    "daedalus.kairos",
    "daedalus.providers",
    "daedalus.runtimes",
)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _function(path: Path, name: str) -> ast.FunctionDef:
    matches = [
        node
        for node in _tree(path).body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(matches) == 1
    return matches[0]


def _call_names(function: ast.FunctionDef) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            result.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            result.add(node.func.attr)
    return result


def test_kernel_has_no_outer_import_or_dynamic_import_escape() -> None:
    tree = _tree(KERNEL_PATH)
    edges: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            edges.append(node.module)
        elif isinstance(node, ast.Import):
            edges.extend(alias.name for alias in node.names)
    assert [
        edge
        for edge in edges
        if any(edge == prefix or edge.startswith(prefix + ".") for prefix in FORBIDDEN_PREFIXES)
    ] == []
    assert "importlib" not in edges
    assert "__import__" not in {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


def test_cold_kernel_import_loads_no_outer_implementation() -> None:
    script = f"""
import json, sys
sys.path.insert(0, {str(ROOT)!r})
import daedalus.kernel.offload_lease
prefixes = (
    'daedalus.chip_design', 'daedalus.eval', 'daedalus.gates',
    'daedalus.kairos', 'daedalus.providers', 'daedalus.runtimes',
)
print(json.dumps(sorted(
    name for name in sys.modules
    if any(name == prefix or name.startswith(prefix + '.') for prefix in prefixes)
)))
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=ROOT,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert json.loads(completed.stdout) == []


def test_chip_publication_authority_has_one_outer_owner_and_thin_facades() -> None:
    completion_path = (
        ROOT / "daedalus" / "chip_design" / "completion_publication.py"
    )
    verifier_path = ROOT / "daedalus" / "chip_design" / "publication_verifier.py"

    retain_facade = _function(KERNEL_PATH, "_retain_chip_eda_terminal_artifact")
    record_facade = _function(KERNEL_PATH, "_record_chip_eda_publication")
    graph_facade = _function(KERNEL_PATH, "verify_chip_eda_publication_graph")
    assert "terminal_artifact_retainer" in _call_names(retain_facade)
    assert "publication_recorder" in _call_names(record_facade)
    assert "publication_graph_verifier" in _call_names(graph_facade)
    assert "put_bytes" not in _call_names(retain_facade)
    assert "_publish_evidence_record" not in _call_names(record_facade)

    assert _function(completion_path, "retain_chip_eda_terminal_artifact")
    assert _function(completion_path, "record_chip_eda_publication")
    assert _function(verifier_path, "verify_chip_eda_publication_graph")
    assert retain_chip_eda_terminal_artifact.__module__.endswith(
        ".completion_publication"
    )
    assert record_chip_eda_publication.__module__.endswith(
        ".completion_publication"
    )
    assert verify_chip_eda_publication_graph.__module__.endswith(
        ".publication_verifier"
    )


def test_workspace_and_lane_compatibility_facades_require_explicit_ports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("DAEDALUS_WORKTREE_ROOT", str(tmp_path / "worktrees"))
    resolved = resolve_worktree_root(repo)
    assert wave_containment_roots(
        repo,
        worktree_root_resolver=resolve_worktree_root,
    ) == (str(repo.resolve()), str(resolved.resolve()))
    with pytest.raises(TypeError, match="worktree_root_resolver port"):
        wave_containment_roots(repo)

    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434/")
    assert lane_endpoint(
        "ollama",
        endpoint_resolver=resolve_lane_endpoint,
    ) == "http://127.0.0.1:11434"
    with pytest.raises(TypeError, match="endpoint_resolver port"):
        lane_endpoint("ollama")


def test_runtime_egress_observation_is_exact_and_missing_composition_denies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    observation = admit_offload_egress(("ollama", "deepseek", "ollama"))
    assert type(observation) is EgressAdmissionObservation
    assert observation.requested_lanes == ("deepseek", "ollama")
    assert observation.endpoints == (
        "https://api.deepseek.com",
        "http://127.0.0.1:11434",
    )
    assert observation.decision.allowed is True

    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(tmp_path / "killswitch"))
    switch = KillSwitch(repo_root=ROOT)
    switch.arm(note="outer-port test")
    result = acquire_wave_offload_lease(
        ROOT,
        source_revision="0" * 40,
        mission_id="outer-port-test",
        attempt_id="missing-egress",
        positions=1,
        lanes=("ollama",),
        max_spend_usd=0.0,
        timeout_s=60,
        writable_paths=("docs/x.md",),
        write_policy=Policy(write_allow=("docs/",)),
        contained=True,
        containment_evidence="test worktree isolation",
        worktree_root=tmp_path / "planned-worktrees",
        switch=switch,
    )
    assert isinstance(result, WaveLeaseDenied)
    decision = next(
        item
        for item in result.guard_decisions
        if item.contract == "provider.egress_policy"
    )
    assert decision == GuardDecision(
        "provider.egress_policy",
        False,
        "no runtime egress admission port was composed; a network-effect "
        "lease is refused before endpoint selection",
    )

    def mismatched_egress(_lanes: tuple[str, ...]) -> EgressAdmissionObservation:
        return EgressAdmissionObservation(
            requested_lanes=("deepseek",),
            endpoints=("https://api.deepseek.com",),
            decision=GuardDecision(
                "provider.egress_policy",
                True,
                "forged observation for another request",
            ),
        )

    with pytest.raises(ValueError, match="not bound to the requested lanes"):
        acquire_wave_offload_lease(
            ROOT,
            source_revision="0" * 40,
            mission_id="outer-port-test",
            attempt_id="mismatched-egress",
            positions=1,
            lanes=("ollama",),
            max_spend_usd=0.0,
            timeout_s=60,
            writable_paths=("docs/x.md",),
            write_policy=Policy(write_allow=("docs/",)),
            contained=True,
            containment_evidence="test worktree isolation",
            worktree_root=tmp_path / "planned-worktrees",
            egress_admission=mismatched_egress,
            switch=switch,
        )


def test_chip_execution_plan_adapter_preserves_exact_type_and_digest(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    workspace = tmp_path / "workspace"
    store = tmp_path / "store"
    for path in (source, workspace, store):
        path.mkdir()
    digest = "a" * 64
    plan = EdaExecutionPlan(
        phase="inspect",
        argv=("vivado", ""),
        source_root=str(source),
        source_project=str(source / "project.xpr"),
        cwd=str(workspace),
        artifact_paths=("result.json",),
        artifact_store_root=str(store),
        timeout_s=60,
        environment_keys=(),
        environment_sha256=digest,
        source_manifest_sha256=digest,
        workspace_manifest_sha256=digest,
        source_identity_sha256=digest,
        trusted_tcl_sha256=digest,
        launcher_sha256=digest,
        publication_adapter_sha256=digest,
    )
    binding = validate_eda_execution_plan(plan)
    assert binding.source_root == plan.source_root
    assert binding.cwd == plan.cwd
    assert binding.digest == plan.digest
    with pytest.raises(TypeError, match="exact EdaExecutionPlan"):
        validate_eda_execution_plan(plan.to_dict())
    with pytest.raises(TypeError, match="execution_plan_validator"):
        offload_lease.acquire_chip_eda_lease(
            tmp_path / "authority",
            project_root=source,
            worktree_root=workspace,
            containment_evidence="test isolated workspace",
            write_policy_path=".agentenv/chip-eda-policy.json",
            operation_plan=plan,
            source_revision="a" * 40,
            repository_head_verifier=lambda *_args: None,
            mission_id="outer-port-test",
            attempt_id="missing-plan-validator",
        )


def test_registry_and_legacy_kernel_object_identity_are_unchanged() -> None:
    assert registry_sha256() == (
        "ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec"
    )
    assert offload_lease.WaveLeaseDenied.__module__ == (
        "daedalus.kernel.offload_lease"
    )
    assert offload_lease.WaveOffloadLease.__module__ == (
        "daedalus.kernel.offload_lease"
    )
