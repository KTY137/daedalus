from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

import daedalus.schemas as legacy
from daedalus.kernel.artifacts import ArtifactRef
from daedalus.kernel.contracts import (
    GENESIS_CONTRACT_TYPES,
    KERNEL_CONTRACT_TYPES,
    BuildIntentProposal,
    DeploymentPlan,
    DeploymentReceipt,
    DesignContract,
    GenesisAutonomyPolicy,
    GenesisRunRecord,
    GraphProposal,
    MaterializationPlan,
    ProductSpec,
    ResourceBudget,
    RoundTripReport,
    TargetFourfoldSpec,
    ToolchainManifest,
    parse_kernel_contract,
)
from daedalus.kernel.contracts.base import ContractProvenance


REVISION = "a" * 40
NOW = "2026-09-04T10:00:00+02:00"


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def ref(value: str) -> ArtifactRef:
    return ArtifactRef.from_sha256(sha(value))


def provenance(*inputs: str) -> ContractProvenance:
    return ContractProvenance(
        origin="test.genesis-contracts",
        source_revision=REVISION,
        created_at=NOW,
        input_digests=tuple(inputs),
        trace_id="trace-genesis-contracts",
    )


def contract_chain() -> tuple[object, ...]:
    runtime = sha("runtime")
    context = sha("context")
    sandbox = sha("sandbox")
    evaluator = sha("evaluator")
    evidence = sha("evidence")
    approval = sha("owner-approval")
    mission = sha("mission")
    input_tree = ref("empty-source-tree")
    candidate = ref("candidate-source-tree")
    actual = ref("actual-fourfold")

    policy = GenesisAutonomyPolicy(
        policy_id="genesis-policy",
        policy_version="2026-09-04",
        source_revision=REVISION,
        defaults={
            "target": "web",
            "audience": "one-local-user",
            "login": False,
            "telemetry": False,
            "storage": "local-first",
            "accessibility": "WCAG-2.2-AA",
        },
        allowed_targets=("web", "cli"),
        default_target="web",
        budget=ResourceBudget(
            max_tokens=50_000,
            max_cost_microusd=1_000_000,
            max_wall_time_s=900,
            max_attempts=4,
        ),
        max_files=250,
        max_bytes=8_000_000,
        max_repairs=2,
        allow_isolated_preview=True,
        public_release_requires_owner_approval=True,
        provenance=provenance(),
    )
    intent = BuildIntentProposal(
        proposal_id="intent-1",
        lineage_id="product-lineage-1",
        source_revision=REVISION,
        prompt="Build a small local-first task board.",
        target=None,
        stack="vite-react",
        advisory=True,
        runtime_manifest_sha256=runtime,
        provenance=provenance(runtime),
        assumptions=("single local user",),
        requested_features=("create tasks", "complete tasks"),
    )
    product = ProductSpec(
        product_id="task-board",
        lineage_id=intent.lineage_id,
        source_revision=REVISION,
        name="Task Board",
        summary="A responsive task board for one local user.",
        target="web",
        audience="one local user",
        features=("complete tasks", "create tasks"),
        constraints=("no telemetry", "local-first storage"),
        base_repository=None,
        defaults={"target": "web", "login": False, "telemetry": False},
        policy_sha256=policy.digest,
        build_intent_proposal_sha256=intent.digest,
        provenance=provenance(policy.digest, intent.digest),
    )
    design = DesignContract(
        design_id="design-1",
        lineage_id=intent.lineage_id,
        source_revision=REVISION,
        product_spec_sha256=product.digest,
        interaction_requirements=("keyboard operable", "responsive layout"),
        accessibility_requirements=("WCAG 2.2 AA",),
        visual_contract={"palette": {"background": "#ffffff"}, "min_width": 320},
        provenance=provenance(product.digest),
    )
    target = TargetFourfoldSpec(
        target_spec_id="target-1",
        lineage_id=intent.lineage_id,
        source_revision=REVISION,
        product_spec_sha256=product.digest,
        design_contract_sha256=design.digest,
        code_requirements=("task state transitions",),
        type_requirements=("Task has stable identity",),
        data_requirements=("tasks persist locally",),
        knowledge_requirements=("usage and limitations documented",),
        acceptance_criteria=("production build succeeds", "round trip conforms"),
        provenance=provenance(product.digest, design.digest),
    )
    graph = GraphProposal(
        proposal_id="graph-1",
        lineage_id=intent.lineage_id,
        source_revision=REVISION,
        target_fourfold_spec_sha256=target.digest,
        runtime_manifest_sha256=runtime,
        context_capsule_sha256=context,
        budget=ResourceBudget(max_tokens=20_000, max_wall_time_s=300),
        operations=(
            {"operation": "add-node", "plane": "code", "subject": "TaskBoard"},
            {"operation": "bind", "from": "Task", "to": "storage"},
        ),
        writable_paths=("src", "tests"),
        advisory=True,
        provenance=provenance(target.digest, runtime, context),
    )
    materialization = MaterializationPlan(
        plan_id="materialization-1",
        lineage_id=intent.lineage_id,
        source_revision=REVISION,
        product_spec_sha256=product.digest,
        design_contract_sha256=design.digest,
        target_fourfold_spec_sha256=target.digest,
        graph_proposal_sha256=graph.digest,
        input_tree=input_tree,
        work_item_ids=("wi-002-test", "wi-001-build"),
        writable_paths=("tests", "src"),
        expected_outputs=("dist", "src"),
        max_files=policy.max_files,
        max_bytes=policy.max_bytes,
        provenance=provenance(
            product.digest,
            design.digest,
            target.digest,
            graph.digest,
            input_tree.sha256,
        ),
    )
    toolchain = ToolchainManifest(
        manifest_id="toolchain-1",
        lineage_id=intent.lineage_id,
        source_revision=REVISION,
        target="web",
        stack="vite-react",
        versions={"node": "22.18.0", "npm": "10.9.3"},
        required_tools=("npm", "node"),
        lockfiles=("package-lock.json",),
        build_command=("npm", "run", "build"),
        test_command=("npm", "test", "--", "--run"),
        run_command=("npm", "run", "preview"),
        package_command=("npm", "run", "build"),
        licenses=("MIT",),
        egress_endpoints=(),
        materialization_plan_sha256=materialization.digest,
        sandbox_policy_sha256=sandbox,
        provenance=provenance(materialization.digest, sandbox),
    )
    round_trip = RoundTripReport(
        report_id="roundtrip-1",
        lineage_id=intent.lineage_id,
        mission_id="mission-1",
        source_revision=REVISION,
        candidate_tree=candidate,
        actual_fourfold=actual,
        target_fourfold_spec_sha256=target.digest,
        evaluator_sha256=evaluator,
        evidence_packet_sha256=evidence,
        checks={"code": True, "data": True, "knowledge": True, "type": True},
        status="passed",
        mismatches=(),
        provenance=provenance(
            candidate.sha256,
            actual.sha256,
            target.digest,
            evaluator,
            evidence,
        ),
    )
    deployment = DeploymentPlan(
        plan_id="deploy-1",
        lineage_id=intent.lineage_id,
        source_revision=REVISION,
        candidate_tree=candidate,
        round_trip_report_sha256=round_trip.digest,
        evidence_packet_sha256=evidence,
        toolchain_manifest_sha256=toolchain.digest,
        owner_approval_sha256=approval,
        target_matrix={"web-production": {"provider": "owner-selected"}},
        provenance=provenance(
            candidate.sha256,
            round_trip.digest,
            evidence,
            toolchain.digest,
            approval,
        ),
    )
    deployment_receipt = DeploymentReceipt(
        receipt_id="deployment-receipt-1",
        lineage_id=intent.lineage_id,
        source_revision=REVISION,
        deployment_plan_sha256=deployment.digest,
        candidate_tree=candidate,
        evidence_packet_sha256=evidence,
        owner_approval_sha256=approval,
        status="deployed",
        target_results={"web-production": "deployed"},
        provenance=provenance(deployment.digest, candidate.sha256, evidence, approval),
    )
    run = GenesisRunRecord(
        run_id="genesis-run-1",
        lineage_id=intent.lineage_id,
        mission_id="mission-1",
        source_revision=REVISION,
        policy_sha256=policy.digest,
        product_spec_sha256=product.digest,
        mission_contract_sha256=mission,
        status="deployed",
        work_item_ids=materialization.work_item_ids,
        attempt_ids=("attempt-1", "attempt-2"),
        repair_count=1,
        candidate_tree=candidate,
        evidence_packet_sha256=evidence,
        round_trip_report_sha256=round_trip.digest,
        deployment_receipt_sha256=deployment_receipt.digest,
        provenance=provenance(
            policy.digest,
            product.digest,
            mission,
            candidate.sha256,
            evidence,
            round_trip.digest,
            deployment_receipt.digest,
        ),
    )
    return (
        policy,
        intent,
        product,
        design,
        target,
        graph,
        materialization,
        toolchain,
        round_trip,
        deployment,
        deployment_receipt,
        run,
    )


def test_complete_genesis_contract_family_is_registered_and_round_trips() -> None:
    contracts = contract_chain()

    assert set(GENESIS_CONTRACT_TYPES) <= set(KERNEL_CONTRACT_TYPES)
    assert KERNEL_CONTRACT_TYPES is legacy.KERNEL_CONTRACT_TYPES
    for contract in contracts:
        rebuilt = parse_kernel_contract(contract.to_dict())
        assert rebuilt == contract
        assert rebuilt.to_json() == contract.to_json()
        assert rebuilt.digest == contract.digest
        assert GENESIS_CONTRACT_TYPES[contract.CONTRACT_TYPE] is type(contract)


def test_genesis_exports_have_one_class_identity() -> None:
    from daedalus.kernel import contracts
    from daedalus.kernel.contracts import genesis

    for name in genesis.__all__:
        assert getattr(contracts, name) is getattr(genesis, name)
        assert getattr(legacy, name) is getattr(genesis, name)


def test_product_spec_keeps_no_base_and_visible_defaults_immutable() -> None:
    product = contract_chain()[2]
    assert isinstance(product, ProductSpec)
    assert "base_repository" in product.to_dict()
    assert product.to_dict()["base_repository"] is None
    assert product.to_dict()["defaults"] == {
        "login": False,
        "target": "web",
        "telemetry": False,
    }
    with pytest.raises(TypeError):
        product.defaults["telemetry"] = True
    with pytest.raises(ValueError, match="explicit null"):
        replace(product, base_repository="https://example.invalid/repo.git")

    wire = product.to_dict()
    wire.pop("base_repository")
    with pytest.raises(ValueError, match="missing field"):
        ProductSpec.from_dict(wire)


def test_model_proposals_cannot_claim_authority() -> None:
    _, intent, _, _, _, graph, *_ = contract_chain()
    assert isinstance(intent, BuildIntentProposal)
    assert isinstance(graph, GraphProposal)

    with pytest.raises(ValueError, match="remain advisory"):
        replace(intent, advisory=False)
    with pytest.raises(ValueError, match="remain advisory"):
        replace(graph, advisory=False)


def test_public_release_cannot_drop_owner_approval_binding() -> None:
    policy, *_, deployment, receipt, _run = contract_chain()
    assert isinstance(policy, GenesisAutonomyPolicy)
    assert isinstance(deployment, DeploymentPlan)
    assert isinstance(receipt, DeploymentReceipt)

    with pytest.raises(ValueError, match="must require owner approval"):
        replace(policy, public_release_requires_owner_approval=False)
    with pytest.raises(ValueError, match="does not bind"):
        replace(
            deployment,
            provenance=provenance(
                deployment.candidate_tree.sha256,
                deployment.round_trip_report_sha256,
                deployment.evidence_packet_sha256,
                deployment.toolchain_manifest_sha256,
            ),
        )
    with pytest.raises(ValueError, match="does not bind"):
        replace(
            receipt,
            provenance=provenance(
                receipt.deployment_plan_sha256,
                receipt.candidate_tree.sha256,
                receipt.evidence_packet_sha256,
            ),
        )


def test_round_trip_status_cannot_contradict_retained_checks() -> None:
    report = contract_chain()[8]
    assert isinstance(report, RoundTripReport)

    with pytest.raises(ValueError, match="contradicts"):
        replace(report, checks={**report.checks, "code": False})
    with pytest.raises(ValueError, match="requires a mismatch"):
        replace(report, status="failed")
    blocked = replace(
        report,
        status="blocked",
        checks={"evaluator-available": False},
        mismatches=("required evaluator unavailable",),
    )
    assert RoundTripReport.from_dict(blocked.to_dict()) == blocked


def test_green_and_deployed_run_states_require_complete_evidence_chain() -> None:
    run = contract_chain()[-1]
    assert isinstance(run, GenesisRunRecord)

    with pytest.raises(ValueError, match="green Genesis run"):
        replace(
            run,
            status="succeeded",
            round_trip_report_sha256=None,
            deployment_receipt_sha256=None,
        )
    with pytest.raises(ValueError, match="deployment receipt"):
        replace(run, deployment_receipt_sha256=None)
    with pytest.raises(ValueError, match="blocked_reason"):
        replace(run, status="blocked", deployment_receipt_sha256=None)


def test_unknown_or_tampered_genesis_wire_fails_closed() -> None:
    product = contract_chain()[2]
    assert isinstance(product, ProductSpec)

    wrong_version = product.to_dict()
    wrong_version["contract_version"] = "999"
    with pytest.raises(ValueError, match="contract_version"):
        parse_kernel_contract(wrong_version)

    unknown = product.to_dict()
    unknown["unexpected_authority"] = True
    with pytest.raises(ValueError, match="unknown field"):
        parse_kernel_contract(unknown)

    unbound = product.to_dict()
    unbound["policy_sha256"] = sha("other-policy")
    with pytest.raises(ValueError, match="does not bind"):
        parse_kernel_contract(unbound)
