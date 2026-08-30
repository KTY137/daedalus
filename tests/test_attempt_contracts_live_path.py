# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The LIVE attempt path must produce the canonical Gate-0 contracts.

Invariant 1 says Mission, Attempt, Evidence, Campaign, policy decisions,
budgets and promotion status have ONE canonical contract and event spine.
``daedalus/schemas.py`` has carried those contracts -- with adapters written
specifically for the legacy spine records -- since Gate 0 opened, and until this
change NOTHING outside ``tests/`` ever called them. A contract with no producer
does not satisfy an invariant; it only looks like it does.

So these tests do not construct contracts by hand. They run a real
:class:`~daedalus.spine.attempt.TaskAttempt` against a real git repository, a
real spine ledger and a real content-addressed store, and assert that the
contracts fall out of THAT. A test that built its own AttemptContract would pass
just as happily with the wiring ripped out, which is the exact failure mode
``spine/attempt.py``'s own ``_admin_dir`` comment warns about: a guard that is
built and not connected is indistinguishable from a guard until it is measured
through the product.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from daedalus.schemas import (  # noqa: E402
    AttemptContract,
    AttemptReceipt,
    EvidencePacket,
    PolicyDecision,
    ResourceBudget,
    RuntimeManifest,
)
from daedalus.spine.attempt import (  # noqa: E402
    GateResult,
    TaskAttempt,
    TaskSpec,
)
from daedalus.spine.ledger import SpineLedger  # noqa: E402
from daedalus.spine.receipts import (  # noqa: E402
    AttemptContractSet,
    UNMETERED_SPEND_REASON,
    evaluator_assurance,
    read_contract_set,
)


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "contracts@example.com")
    _git(root, "config", "user.name", "contracts")
    (root / "target.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "other.py").write_text("OTHER = 0\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return root


def _spec(**kw):
    body = dict(
        task_id="live-contract-task",
        instruction="raise VALUE to 2",
        target_paths=("target.py",),
        gate_timeout_s=60.0,
    )
    body.update(kw)
    return TaskSpec(**body)


def _writer(name="target.py", text="VALUE = 2\n"):
    def _runner(ctx):
        (ctx.worktree / name).write_text(text, encoding="utf-8")
    return _runner


def _green(name="demo-gate", output="everything green\n"):
    def _gate(ctx):
        return GateResult(passed=True, name=name, command=("echo", "ok"),
                          returncode=0, output=output, duration_s=0.4)
    return _gate


def _run(repo, tmp_path, *, spec=None, runner=None, gate=None, store=True, **kw):
    attempt = TaskAttempt(
        spec or _spec(),
        runner=runner or _writer(),
        gate=gate or _green(),
        repo_root=str(repo),
        ledger_path=tmp_path / "spine.sqlite3",
        artifact_dir=(tmp_path / "store") if store else None,
        reap=False,
        **kw)
    return attempt, attempt.run()


# --------------------------------------------------------------------------- #
# the attempt spine (AttemptContract + AttemptReceipt)                         #
# --------------------------------------------------------------------------- #
def test_live_attempt_yields_a_validating_attempt_contract_and_receipt(
        repo, tmp_path):
    attempt, result = _run(repo, tmp_path)

    assert result.state == "clean"
    assert result.contracts_error is None, result.contracts_error
    contracts = result.contract_set()
    assert contracts.complete

    assert isinstance(contracts.attempt, AttemptContract)
    assert isinstance(contracts.receipt, AttemptReceipt)

    # Identity is the effect key, not a parallel id space. One string names the
    # branch in the world, the ledger row and the contract.
    assert contracts.attempt.attempt_id == attempt.effect_key == result.branch
    assert contracts.attempt.mission_id == attempt.mission_id
    assert contracts.attempt.task_sha256 == attempt.task.digest
    assert contracts.attempt.writable_paths == ("target.py",)

    # The contract binds the RESOLVED revision, not the task's request (which
    # was None here and would have refused construction).
    assert attempt.task.base_revision is None
    assert contracts.attempt.base_revision == result.base_revision

    # Provenance per Invariant 7: origin, revision, inputs.
    prov = contracts.attempt.provenance
    assert prov.origin == "daedalus.spine.attempt.TaskAttempt"
    assert prov.source_revision == result.base_revision
    assert set(prov.input_digests) >= {
        attempt.task.digest,
        contracts.runtime.digest,
        contracts.policy.digest,
    }

    # The receipt binds every contract it references, and nominates nothing.
    assert contracts.receipt.attempt_contract_sha256 == contracts.attempt.digest
    assert contracts.receipt.evidence_packet_sha256 == contracts.evidence.digest
    assert contracts.receipt.runtime_manifest_sha256 == contracts.runtime.digest
    assert contracts.receipt.policy_decision_sha256 == contracts.policy.digest
    assert set(contracts.receipt.to_dict()).isdisjoint(
        {"nominated", "promoted", "owner_approval_ref"})

    # Validating means round-tripping through the schema's own reader.
    assert AttemptContract.from_dict(contracts.attempt.to_dict()) == contracts.attempt
    assert AttemptReceipt.from_dict(contracts.receipt.to_dict()) == contracts.receipt


def test_receipt_reports_inconclusive_rather_than_laundering_a_green_gate(
        repo, tmp_path):
    """A green exit code is not a conclusive verdict.

    The gate here runs pytest-style over the candidate's OWN worktree, where the
    candidate could have edited the tests that judge it, so the evaluator
    assurance is ``unverified`` and the packet is inconclusive by its own rules.
    The receipt must follow the evidence, not the legacy ``clean`` state.
    """
    _attempt, result = _run(repo, tmp_path)

    contracts = result.contract_set()
    assert result.state == "clean"
    assert contracts.evidence.items[0].assurance == "unverified"
    assert contracts.evidence.evaluation_status == "inconclusive"
    assert contracts.receipt.outcome == "inconclusive"


def test_spine_authored_gate_is_deterministic_and_conclusive(repo, tmp_path):
    """The one gate no candidate can influence: the declared-scope check.

    ``target-scope`` is authored by the spine and reads the patch, never the
    candidate's code, so it is the case where a conclusive canonical verdict is
    honestly available on the live path.
    """
    _attempt, result = _run(repo, tmp_path, runner=_writer("other.py"))

    contracts = result.contract_set()
    assert result.state == "gates_failed"
    assert result.gates.name == "target-scope"
    assert evaluator_assurance(result, _spec()) == "deterministic"
    assert contracts.evidence.items[0].assurance == "deterministic"
    assert contracts.evidence.evaluation_status == "failed"
    assert contracts.receipt.outcome == "failed"


# --------------------------------------------------------------------------- #
# the gate reader (EvidencePacket)                                             #
# --------------------------------------------------------------------------- #
def test_evidence_packet_from_a_real_gate_result_validates_and_round_trips(
        repo, tmp_path):
    _attempt, result = _run(repo, tmp_path, gate=_green(output="x" * 12000))

    packet = result.contract_set().evidence
    assert isinstance(packet, EvidencePacket)
    assert EvidencePacket.from_dict(packet.to_dict()) == packet

    item = packet.items[0]
    assert item.evaluator == "demo-gate"
    assert item.output_sha256 == result.gates.output_sha256

    # THE LOCATOR POINTS AT THE FULL BYTES, not the 4000-char ledger excerpt.
    # A verdict that cannot be re-read is not evidence.
    store_root = tmp_path / "store"
    locator_sha = item.evidence_locator.rsplit(":", 1)[1]
    from daedalus.storage import ArtifactStore

    store = ArtifactStore(store_root)
    blob = store.verify(store.load_locator(locator_sha)).blob_path
    assert blob.read_bytes() == result.gates.output.encode("utf-8", "replace")
    assert len(result.gates.output) > len(result.to_dict()["gates"]["output_tail"])

    # The candidate artifact is bound by content address, not by path.
    assert packet.candidate_artifact_sha256 == result.artifact.diff_sha256
    assert packet.candidate_artifact_locator == result.artifact_locator["locator_uri"]


def test_evidence_is_refused_rather_than_faked_when_nothing_can_hold_it(
        repo, tmp_path):
    """No store means no durable locator means no evidence packet.

    The attempt still succeeds and still yields an AttemptContract: the refusal
    is reported, never swallowed, and never papered over with a placeholder
    digest that would point at bytes nobody kept.
    """
    _attempt, result = _run(repo, tmp_path, store=False)

    contracts = result.contract_set()
    assert result.state == "clean"
    assert contracts.attempt is not None
    assert contracts.evidence is None
    assert contracts.receipt is None
    assert "no artifact store configured" in result.contracts_error


def test_unbounded_write_scope_cannot_masquerade_as_a_bounded_contract(
        repo, tmp_path):
    """Now refused TWICE, and the order is the point.

    This asserted ``state == "clean"``: the attempt ran to completion, the gate
    ran, and only ``canonicalise_attempt`` refused afterwards. That refusal is
    real and is still asserted below -- but a contract refused after a green
    gate is a record of a verdict that may already have been subverted, because
    the gate loads the candidate's own ``conftest.py`` into the evaluator
    process (docs/inventory/2026-08-24/DENY_FLOOR_CORPUS.md). The attempt now
    refuses at the target-scope check, BEFORE ``_run_gates``, and the contract
    layer keeps refusing behind it. Both assertions belong here: this test's
    claim is that an unbounded scope cannot become a bounded contract, and it is
    now true at two layers instead of one.
    """
    _attempt, result = _run(repo, tmp_path, spec=_spec(target_paths=()))

    contracts = result.contract_set()
    assert result.state == "gates_failed"
    assert "declared no target_paths at all" in (result.error or "")
    assert contracts.attempt is None
    assert "no target_paths" in result.contracts_error


# --------------------------------------------------------------------------- #
# the effect boundary (PolicyDecision)                                         #
# --------------------------------------------------------------------------- #
def test_policy_decision_records_the_scope_the_spine_actually_granted(
        repo, tmp_path):
    attempt, result = _run(repo, tmp_path)

    decision = result.contract_set().policy
    assert isinstance(decision, PolicyDecision)
    assert PolicyDecision.from_dict(decision.to_dict()) == decision

    assert decision.verdict == "allow"
    assert decision.subject_id == attempt.attempt_id
    assert decision.subject_sha256 == attempt.task.digest

    scope = decision.effect_scope
    assert scope.read_only is False
    assert scope.writable_paths == ("target.py",)
    assert scope.egress_endpoints == ()          # this spine grants no egress
    assert scope.secret_refs == ()
    assert scope.max_concurrency == 1
    assert scope.timeout_s == 60
    assert scope.kill_switch_ref

    # It binds the DECLARED policy text it was made under.
    from daedalus.spine.effect_boundary import registry_sha256

    assert decision.policy_sha256 == registry_sha256()

    # THE LIMITATION TRAVELS INSIDE THE DIGEST. A caveat that lives only in a
    # docstring is a caveat the record's reader never sees.
    assert UNMETERED_SPEND_REASON in decision.reasons


def test_a_refused_attempt_still_produces_a_deny_decision(repo, tmp_path, monkeypatch):
    """The deny IS the receipt. An attempt turned away before any effect is
    exactly the case where a record is most worth having."""
    attempt = TaskAttempt(
        _spec(), runner=_writer(), gate=_green(), repo_root=str(repo),
        ledger_path=tmp_path / "spine.sqlite3", artifact_dir=tmp_path / "store",
        reap=False)

    def _boom(*_a, **_k):
        raise RuntimeError("simulated worktree failure")

    monkeypatch.setattr(attempt._manager, "create_worktree", _boom)
    result = attempt.run()

    contracts = result.contract_set()
    assert result.state == "worktree_failed"
    assert contracts.policy.verdict == "deny"
    assert contracts.policy.effect_scope.read_only is True
    assert contracts.policy.effect_scope.has_effects is False
    assert contracts.attempt is None and contracts.evidence is None


# --------------------------------------------------------------------------- #
# one spine, one row                                                           #
# --------------------------------------------------------------------------- #
def test_the_contracts_join_the_existing_ledger_row_and_read_back_as_contracts(
        repo, tmp_path):
    """No second event store: the canonical records land in the SAME intent the
    attempt already resolved, and come back out as contracts rather than as a
    dict the caller has to interpret."""
    _attempt, result = _run(repo, tmp_path)
    contracts = result.contract_set()

    ledger = SpineLedger(tmp_path / "spine.sqlite3")
    try:
        rows = ledger.recent_intents("attempt.candidate", limit=5)
        assert len(rows) == 1
        body = rows[0].result

        # Every legacy key keeps its exact shape: additive, not a rewrite.
        assert {"state", "branch", "base_revision", "artifact", "gates",
                "artifact_locator", "persist_error", "error"} <= set(body)

        recovered = read_contract_set(body)
        assert isinstance(recovered, AttemptContractSet)
        assert recovered.complete
        assert recovered.attempt.digest == contracts.attempt.digest
        assert recovered.evidence.digest == contracts.evidence.digest
        assert recovered.receipt.digest == contracts.receipt.digest
        assert recovered.policy.digest == contracts.policy.digest
        assert isinstance(recovered.runtime, RuntimeManifest)
    finally:
        ledger.close()


def test_a_tampered_ledger_record_fails_to_reconstruct(repo, tmp_path):
    """Reading back through the schema is the point: a record edited in the
    ledger must refuse to become a plausible object again."""
    _attempt, result = _run(repo, tmp_path)
    body = json.loads(json.dumps({"contracts": result.contracts}))
    body["contracts"]["attempt"]["writable_paths"] = ["target.py", "../escape.py"]

    with pytest.raises(ValueError):
        read_contract_set(body)


def test_a_declared_budget_and_mission_are_carried_into_the_contract(
        repo, tmp_path):
    budget = ResourceBudget(max_tokens=50_000, max_cost_microusd=250_000,
                            max_wall_time_s=120)
    attempt, result = _run(repo, tmp_path, mission_id="mission-ignition-1",
                           budget=budget, campaign_id="campaign-a",
                           spend_grant_microusd=250_000)

    contracts = result.contract_set()
    assert contracts.attempt.mission_id == "mission-ignition-1"
    assert contracts.attempt.campaign_id == "campaign-a"
    assert contracts.attempt.budget == budget
    assert contracts.policy.effect_scope.max_cost_microusd == 250_000
    assert attempt.budget == budget


# --------------------------------------------------------------------------- #
# the hardened seals, on the same live path                                    #
# --------------------------------------------------------------------------- #
def test_the_policy_text_the_mission_binds_rides_the_attempt_contract(
        repo, tmp_path):
    """One policy text per chain, carried rather than assumed.

    ``MissionContract.policy_sha256`` and the attempt's own
    ``PolicyDecision.policy_sha256`` were never compared, so a registry edited
    between compiling the mission and projecting the attempt produced a chain
    naming two different policy texts with nothing to notice. The digest now
    joins the attempt contract's own provenance inputs, which is what lets a
    reader holding only this record name the policy it was decided under.
    """
    from daedalus.spine.effect_boundary import registry_sha256

    _attempt, result = _run(repo, tmp_path)
    contracts = result.contract_set()

    assert contracts.policy.policy_sha256 == registry_sha256()
    assert registry_sha256() in contracts.attempt.provenance.input_digests


def test_the_assurance_derivation_records_why_and_not_only_what(repo, tmp_path):
    """``unverified`` alone does not say WHICH seal failed.

    A reader who cannot tell a missing criterion from a criterion the gate
    never read cannot act on the record, so the sentence travels inside the
    PolicyDecision digest alongside the verdict.
    """
    _attempt, result = _run(repo, tmp_path)
    contracts = result.contract_set()

    reasons = [r for r in contracts.policy.reasons
               if r.startswith("evaluator assurance")]
    assert len(reasons) == 1
    assert reasons[0].startswith("evaluator assurance unverified: ")
    # This spec declares no criterion at all, so the honest reading is that the
    # gate judged the candidate's own worktree.
    assert "no criterion the candidate was barred from writing" in reasons[0]
    assert contracts.evidence.items[0].assurance == "unverified"


def test_the_contract_set_refuses_to_reconstruct_a_shuffled_ledger_row(
        repo, tmp_path):
    """Each contract validating ITSELF is not the same as the five belonging together.

    ``read_contract_set`` is what a promotion path uses to recover the record
    from the ledger. A row whose parts came from two different attempts is five
    individually well-formed contracts, and it used to reconstruct into a
    plausible object carrying someone else's green.
    """
    _first_attempt, first = _run(repo, tmp_path)
    _second_attempt, second = _run(
        repo, tmp_path, spec=_spec(task_id="live-contract-task-two"))

    assert read_contract_set({"contracts": first.contracts}).complete

    shuffled = json.loads(json.dumps(first.contracts))
    shuffled["receipt"] = json.loads(json.dumps(second.contracts["receipt"]))
    with pytest.raises(ValueError, match="not internally bound"):
        read_contract_set({"contracts": shuffled})
