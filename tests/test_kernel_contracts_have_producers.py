"""A census: which canonical contracts are actually produced in production.

This is the test that would have caught the gap in the first place. Every
Gate-0 contract in ``daedalus/kernel/contracts/canonical.py`` was well-specified, strictly
validated, thoroughly unit-tested -- and seven of eight had no caller outside
``tests/``. Unit tests cannot see that, because a unit test IS the caller. So
this file walks the production tree with ``ast`` and asks a different question:
who builds this, on a path a user can reach?

The census is written as an EXACT set, not a lower bound. A contract that
quietly loses its last producer fails here, and so does a contract that gains
one without the list being updated -- because "producer-less, and here is why"
is a claim that has to be re-justified when it stops being true.
"""
import ast
import sys
from functools import lru_cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from daedalus.kernel.contracts.registry import KERNEL_CONTRACT_TYPES  # noqa: E402

PRODUCTION = ROOT / "daedalus"

EXPECTED_CONTRACT_REGISTRY = {
    "daedalus.attempt": "AttemptContract",
    "daedalus.attempt-receipt": "AttemptReceipt",
    "daedalus.build-intent-proposal": "BuildIntentProposal",
    "daedalus.campaign": "CampaignContract",
    "daedalus.campaign-receipt": "CampaignReceipt",
    "daedalus.deployment-plan": "DeploymentPlan",
    "daedalus.deployment-receipt": "DeploymentReceipt",
    "daedalus.design-contract": "DesignContract",
    "daedalus.evidence": "EvidencePacket",
    "daedalus.experiment-spec": "ExperimentSpec",
    "daedalus.genesis-autonomy-policy": "GenesisAutonomyPolicy",
    "daedalus.genesis-run-record": "GenesisRunRecord",
    "daedalus.graph-proposal": "GraphProposal",
    "daedalus.materialization-plan": "MaterializationPlan",
    "daedalus.mission": "MissionContract",
    "daedalus.nomination": "NominationReceipt",
    "daedalus.policy-decision": "PolicyDecision",
    "daedalus.product-spec": "ProductSpec",
    "daedalus.promotion": "PromotionReceipt",
    "daedalus.round-trip-report": "RoundTripReport",
    "daedalus.runtime-conformance": "RuntimeConformanceReceipt",
    "daedalus.runtime-manifest": "RuntimeManifest",
    "daedalus.target-fourfold-spec": "TargetFourfoldSpec",
    "daedalus.toolchain-manifest": "ToolchainManifest",
}

#: Adapter classmethods count as producers: they return a constructed contract.
ADAPTER_METHODS = frozenset(
    {"from_task_spec", "from_attempt_result", "from_runtime_spec"}
)

# Derive the census subject from the closed parser registry.  A hand-maintained
# tuple here missed all twelve Genesis contracts even though they were already
# parseable canonical types, allowing two producer-less release contracts to
# remain invisible.  Class names are the constructor spellings the AST census
# below measures; the separate exactness probe retains the wire-type mapping.
CONTRACTS = tuple(
    sorted({contract.__name__ for contract in KERNEL_CONTRACT_TYPES.values()})
)

#: Contracts with no live producer, each with the reason it is still honest.
#: Remove an entry here only together with the wiring that made it wrong.
PRODUCERLESS = {
    "DeploymentPlan": (
        "Gate-1 Genesis v1 has no public-publishing authority; a later release "
        "adapter may construct a plan only after exact one-use OwnerApproval"
    ),
    "DeploymentReceipt": (
        "Gate-1 Genesis v1 does not execute DeploymentPlan and therefore cannot "
        "honestly emit a deployment outcome"
    ),
    "PromotionReceipt": (
        "promotion remains sealed and has no automatic production producer"
    ),
}

#: Producer functions that exist but are not yet CALLED on a live path. This is
#: a weaker status than "produced", and the distinction matters: a constructor
#: reachable only from tests satisfies the census above while satisfying no
#: invariant at all. That is exactly how seven of eight contracts came to look
#: wired when they were not.
UNCALLED_PRODUCERS = {
    # The only honest call site is the picker -- the one piece of live code that
    # decides what to work on next. That hunk is delivered as an unapplied diff
    # because the picker is outside this change's edit boundary.
    # (mission_contract_for_build_session left this list on 2026-08-23: the
    # Gate-1 slice calls it at daedalus/ignition/gate1.py:272, so it has a
    # live producer and the "delivered as a diff" reason was stale.)
}


def _production_modules():
    for path in sorted(PRODUCTION.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        # The canonical module defines the contracts; defining is not producing.
        if path.relative_to(ROOT).as_posix() == "daedalus/kernel/contracts/canonical.py":
            continue
        yield path


@lru_cache(maxsize=1)
def _producers():
    found = {name: set() for name in CONTRACTS}
    for path in _production_modules():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a broken module is not our news
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            where = f"{path.relative_to(ROOT).as_posix()}:{node.lineno}"
            if isinstance(func, ast.Name) and func.id in found:
                found[func.id].add(where)
            elif (
                isinstance(func, ast.Attribute)
                and func.attr in ADAPTER_METHODS
                and isinstance(func.value, ast.Name)
                and func.value.id in found
            ):
                found[func.value.id].add(where)
    return found


def test_census_subject_is_exactly_the_closed_contract_registry():
    registered = {
        wire_type: contract.__name__
        for wire_type, contract in KERNEL_CONTRACT_TYPES.items()
    }
    assert registered == EXPECTED_CONTRACT_REGISTRY
    assert len(set(registered.values())) == len(registered), (
        "two wire types unexpectedly share one constructor spelling"
    )
    assert set(CONTRACTS) == set(registered.values())
    assert {
        "GenesisAutonomyPolicy",
        "BuildIntentProposal",
        "ProductSpec",
        "DesignContract",
        "TargetFourfoldSpec",
        "GraphProposal",
        "MaterializationPlan",
        "ToolchainManifest",
        "RoundTripReport",
        "DeploymentPlan",
        "DeploymentReceipt",
        "GenesisRunRecord",
    } <= set(CONTRACTS), "the complete Genesis contract domain must be censused"


def test_genesis_contract_producer_modules_are_exact():
    admission = {"daedalus/orchestration/genesis/admission.py"}
    service = {"daedalus/orchestration/genesis/service.py"}
    expected = {
        "GenesisAutonomyPolicy": admission,
        "BuildIntentProposal": admission,
        "ProductSpec": admission,
        "DesignContract": admission,
        "TargetFourfoldSpec": admission,
        "GraphProposal": admission,
        "MaterializationPlan": admission,
        "ToolchainManifest": admission,
        "RoundTripReport": service,
        "GenesisRunRecord": service,
        "DeploymentPlan": set(),
        "DeploymentReceipt": set(),
    }
    producers = _producers()
    actual = {
        contract: {site.rsplit(":", 1)[0] for site in producers[contract]}
        for contract in expected
    }
    assert actual == expected


def test_every_canonical_contract_has_a_production_producer_or_a_stated_reason():
    found = _producers()
    missing = {name for name, sites in found.items() if not sites}
    assert missing == set(PRODUCERLESS), (
        "the producer census changed. producer-less now: "
        f"{sorted(missing)}; declared producer-less: {sorted(PRODUCERLESS)}"
    )


def test_producer_functions_with_no_live_caller_are_declared_as_such():
    """"It is constructed somewhere" is not "it is produced on a live path".

    The census above cannot tell the two apart, so this names the difference
    explicitly. When the picker hunk lands, this test fails and the entry must
    be removed -- which is the point: an upgrade in status should not be able to
    happen silently either.
    """
    callers = {name: set() for name in UNCALLED_PRODUCERS}
    for path in _production_modules():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.id if isinstance(func, ast.Name)
                else func.attr if isinstance(func, ast.Attribute)
                else None
            )
            if name in callers:
                callers[name].add(
                    f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")

    for name, reason in UNCALLED_PRODUCERS.items():
        assert not callers[name], (
            f"{name} now has a live caller ({sorted(callers[name])}); the "
            f"declared reason {reason!r} is stale and this list must be updated"
        )


@pytest.mark.parametrize(
    "contract", ["AttemptContract", "AttemptReceipt", "EvidencePacket", "PolicyDecision"]
)
def test_the_attempt_spine_contracts_are_produced_by_the_spine(contract):
    """Priority order from the integration gap: the attempt spine first.

    Producing these somewhere in the tree is not enough -- they have to be
    produced on the path an attempt actually takes.
    """
    sites = _producers()[contract]
    assert any(
        site.startswith("daedalus/spine/receipts.py") for site in sites
    ), f"{contract} has no producer in the attempt spine: {sorted(sites)}"


def test_the_producer_is_actually_wired_into_the_attempt():
    """A producer nothing calls is the gap in a new costume.

    ``kernel/attempt_execution.py``'s own ``_admin_dir`` comment states the lesson this
    guards: a guard that is built and not connected is indistinguishable from a
    guard, right up until it is measured through the product. So assert the
    connection, not just the existence.
    """
    source = (PRODUCTION / "kernel" / "attempt_execution.py").read_text(
        encoding="utf-8"
    )
    assert "from daedalus.spine.receipts import" in source
    assert "canonicalise_attempt(" in source
    assert "self._canonicalise(" in source

    tree = ast.parse(source)
    resolvers = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_resolve_and_finish"
    ]
    assert len(resolvers) == 1
    body = ast.dump(resolvers[0])
    assert "_canonicalise" in body, (
        "the canonical projection is no longer built where the attempt resolves "
        "its intent, so the ledger row would carry the ad-hoc dict alone")


def test_the_legacy_attempt_dict_survives_only_where_it_is_paired_with_contracts():
    """The ad-hoc record is not deleted -- it cannot be, since loop.py,
    web_api.py and the picker's review packet all read it -- but it must not
    exist anywhere the canonical contracts do not accompany it.

    Two sites are expected and both live in the kernel-owned Attempt lifecycle:
    ``AttemptResult.to_dict`` (the JSON-safe view) and ``_resolve_and_finish``'s
    ledger payload, which now carries ``contracts`` alongside. A third site
    appearing anywhere is a second, contract-free attempt record.
    """
    legacy_keys = {"state", "gates", "artifact"}
    offenders = []
    for path in _production_modules():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys = {
                key.value
                for key in node.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
            if legacy_keys <= keys:
                offenders.append(
                    f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")

    assert len(offenders) == 2, f"unexpected attempt-shaped dicts: {offenders}"
    assert all(
        o.startswith("daedalus/kernel/attempt_execution.py") for o in offenders
    )


def test_the_ledger_payload_carries_the_contracts_key():
    source = (PRODUCTION / "kernel" / "attempt_execution.py").read_text(
        encoding="utf-8"
    )
    assert '"contracts": contract_body' in source, (
        "the spine ledger row no longer carries the canonical projection")
