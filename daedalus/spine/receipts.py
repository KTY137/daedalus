"""Canonicalise one finished spine attempt into the Gate-0 contracts.

WHY THIS MODULE EXISTS
----------------------
``daedalus/schemas.py`` has carried ``AttemptContract``, ``EvidencePacket``,
``AttemptReceipt`` and ``PolicyDecision`` -- with adapters
(``from_task_spec``, ``from_attempt_result``) written specifically for the
legacy spine records -- and nothing on the live path ever called them. A
contract with no producer is a schema, not a kernel: Invariant 1 ("Mission,
Attempt, Evidence, Campaign, policy decisions, budgets and promotion status
have ONE canonical contract and event spine") was unmet exactly where it is
supposed to hold. This module is the missing call.

WHAT IT IS NOT
--------------
It is not a second kernel, a second event store, a second artifact identity, or
a promotion path. It has no state, opens no database, writes no file and starts
no effect. Every record it returns is inert data built from an attempt that has
ALREADY finished, using the adapters that already live in the schema. The
caller -- :class:`daedalus.spine.attempt.TaskAttempt` -- persists them into the
one existing spine ledger row it was already writing.

WHAT IT DELIBERATELY REFUSES
----------------------------
A canonical contract that cannot be built honestly is not built at all:

* a task with no declared ``target_paths`` gets no write-capable contract (the
  schema's own refusal -- an unbounded write cannot masquerade as bounded);
* an attempt with no content-addressed store gets no ``EvidencePacket``, because
  ``EvidenceItem`` requires a durable locator for the gate output and inventing
  one would be a fabricated evidence reference;
* an attempt whose gate output was never retained gets no evidence item.

Each refusal is REPORTED (``AttemptContractSet.error``), never swallowed and
never papered over with a placeholder digest.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Mapping, Sequence

from daedalus.schemas import (
    AttemptContract,
    AttemptReceipt,
    ContractProvenance,
    EffectScope,
    EvidencePacket,
    MissionContract,
    PolicyDecision,
    ResourceBudget,
    ResourceUsage,
    RuntimeCapabilities,
    RuntimeManifest,
)


#: The effect-boundary row this spine is registered under. Its ``wiring`` is
#: LOCAL_GUARDS, not CENTRAL, so ``begin_effect`` REFUSES it and there is no
#: boundary receipt to convert. The decision recorded here is therefore the
#: decision the spine itself makes with the guards it really runs, bound to the
#: declared registry digest so a reader can see which policy text it was made
#: under. Upgrading the row to CENTRAL is the follow-up that would let this
#: come from ``begin_effect`` instead; until then the honest label is below.
ATTEMPT_ENTRYPOINT_ID = "python.attempt"

ATTEMPT_ORIGIN = "daedalus.spine.attempt.TaskAttempt"
ATTEMPT_RUNTIME_ID = "spine.attempt.harness"
ATTEMPT_KILL_SWITCH_REF = "daedalus.spine.killswitch"

#: The exact wording that travels INSIDE the PolicyDecision digest. Reasons are
#: part of the contract, so a limitation stated here cannot be lost between the
#: record and its reader -- which is the only reason it is a constant and not a
#: comment.
UNMETERED_SPEND_REASON = (
    "attempt spine does not meter model spend or tokens: usage.cost_microusd "
    "and usage.input_tokens/output_tokens are 0 because nothing measured them, "
    "not because zero was measured"
)
GATE_WALL_BOUND_REASON = (
    "budget.max_wall_time_s defaults to the GATE timeout and usage.wall_time_ms "
    "is the GATE's measured duration; the injected runner's wall time is "
    "outside this bound and is not counted against it"
)
SPEND_GRANT_REASON = (
    "effect_scope.max_cost_microusd is the spend THIS decision grants; the "
    "injected runner's own effect boundary (daedalus.offload) carries its lease "
    "and its spend, and this scope neither bounds nor meters that"
)


@lru_cache(maxsize=1)
def _policy_registry_sha256() -> str:
    """The declared effect-boundary registry digest, read lazily.

    Lazy because ``effect_boundary`` is a large module and this one is imported
    from the attempt hot path; cached because the registry is a module constant.
    """

    from daedalus.spine.effect_boundary import registry_sha256

    return registry_sha256()


def _identifier_fragment(text: str, fallback: str) -> str:
    cleaned = "".join(
        char if (char.isalnum() or char in "._:/-") else "-" for char in str(text)
    ).strip("-")
    while cleaned and not cleaned[0].isalnum():
        cleaned = cleaned[1:]
    return cleaned[:200] or fallback


def adapter_identity(runner: Any) -> str:
    """Name the injected runner as an adapter id, without importing it."""

    module = getattr(runner, "__module__", "") or ""
    qualname = getattr(runner, "__qualname__", "") or type(runner).__name__
    return _identifier_fragment(f"{module}.{qualname}", "unknown-adapter")


def attempt_runtime_manifest(
    *,
    source_revision: str,
    created_at: str,
    adapter_id: str,
    trace_id: str | None = None,
    runtime_id: str = ATTEMPT_RUNTIME_ID,
) -> RuntimeManifest:
    """Declare the harness the attempt actually ran in.

    ``assurance`` is "declared" and the schema allows nothing else here: these
    are the capabilities the attempt harness EXPRESSES, and a conformance
    receipt -- not this manifest -- is what would turn any of them into a
    measurement. The capabilities below are structural properties of
    :class:`~daedalus.spine.attempt.TaskAttempt`, not aspirations: it runs the
    candidate in a git worktree outside the primary checkout
    (``isolated-worktree``), kills its gate on a timeout, and honours a cancel
    predicate. It does not stream, does not emit provider-neutral tool events,
    does not parse structured output and does not report cost.
    """

    capabilities = RuntimeCapabilities(
        streaming=False,
        tool_events=False,
        structured_output=False,
        timeout=True,
        cancellation=True,
        workspace_isolation=True,
        cost_reporting=False,
        workspace_write=True,
    )
    return RuntimeManifest(
        runtime_id=runtime_id,
        runtime_version=(
            f"python-{sys.version_info.major}.{sys.version_info.minor}."
            f"{sys.version_info.micro}"
        ),
        adapter_id=adapter_id,
        # The adapter's version IS the source revision it was read from: this
        # harness ships with the repository, so there is no separate release
        # number that could drift away from the code that ran.
        adapter_version=source_revision,
        source_revision=source_revision,
        assurance="declared",
        capabilities=capabilities,
        declared_tools=(),
        egress_transports=(),
        workspace_modes=("isolated-worktree", "read-only"),
        cost_model="unmetered",
        provenance=ContractProvenance(
            origin=ATTEMPT_ORIGIN,
            source_revision=source_revision,
            created_at=created_at,
            input_digests=(),
            trace_id=trace_id,
        ),
    )


def attempt_policy_decision(
    *,
    decision_id: str,
    subject_id: str,
    subject_sha256: str,
    source_revision: str,
    created_at: str,
    verdict: str,
    reasons: Sequence[str],
    writable_paths: Sequence[str] = (),
    timeout_s: int | None = None,
    spend_grant_microusd: int = 0,
    trace_id: str | None = None,
) -> PolicyDecision:
    """Record the decision the attempt spine itself made.

    The guards named in ``reasons`` are the ones that really run before the
    effect: the intent ledger write (no durable record, no effect), the storage
    watermark, the worktree isolation, the declared-scope check, and the
    primary-checkout write fence. Nothing here enforces anything -- the
    enforcement already happened; this is its record.
    """

    if verdict == "allow":
        scope = EffectScope(
            read_only=False,
            writable_paths=tuple(writable_paths),
            egress_endpoints=(),
            tools=(),
            secret_refs=(),
            max_cost_microusd=int(spend_grant_microusd),
            max_concurrency=1,
            timeout_s=timeout_s,
            kill_switch_ref=ATTEMPT_KILL_SWITCH_REF,
        )
    else:
        scope = EffectScope(read_only=True)
    policy_sha = _policy_registry_sha256()
    return PolicyDecision(
        decision_id=decision_id,
        subject_id=subject_id,
        subject_sha256=subject_sha256,
        policy_version=f"effect-boundary:{ATTEMPT_ENTRYPOINT_ID}",
        policy_sha256=policy_sha,
        verdict=verdict,
        reasons=tuple(reasons),
        effect_scope=scope,
        provenance=ContractProvenance(
            origin=ATTEMPT_ORIGIN,
            source_revision=source_revision,
            created_at=created_at,
            input_digests=(subject_sha256, policy_sha),
            trace_id=trace_id,
        ),
    )


def evaluator_assurance(result: Any, task: Any) -> str:
    """How much the gate verdict is worth, derived rather than asserted.

    ``deterministic`` is claimed ONLY when the criterion came from outside the
    candidate and the candidate ran behind a boundary that actually held:

    * a spine-authored gate (``target-scope``) reads the patch, never the
      candidate's own code, so no candidate can influence its verdict;
    * a FAIL_TO_PASS/PASS_TO_PASS gate carries a frozen, pre-verified receipt
      the candidate cannot author, but only counts when the measured
      containment attestation says the child was in fact contained.

    Everything else is ``unverified`` -- including a plain pytest gate over the
    candidate's own worktree, where the candidate could have edited the tests
    that judge it. That is not pessimism: a conclusive EvidencePacket may not
    rest on unverified evidence, so calling this "deterministic" by default
    would manufacture exactly the green the evidence boundary exists to refuse.
    """

    gate = getattr(result, "gates", None)
    if gate is None:
        return "unverified"
    if str(getattr(gate, "name", "")) == "target-scope":
        return "deterministic"
    frozen_criterion = bool(
        getattr(task, "fail_to_pass", ()) or getattr(task, "pass_to_pass", ())
    )
    containment = getattr(gate, "containment", None)
    contained = bool(getattr(containment, "contained", False))
    if frozen_criterion and contained:
        return "deterministic"
    return "unverified"


@dataclass(frozen=True)
class AttemptContractSet:
    """The canonical records for one finished attempt, or the reason there are none."""

    runtime: RuntimeManifest | None = None
    policy: PolicyDecision | None = None
    attempt: AttemptContract | None = None
    evidence: EvidencePacket | None = None
    receipt: AttemptReceipt | None = None
    error: str | None = None

    @property
    def complete(self) -> bool:
        return None not in (
            self.runtime,
            self.policy,
            self.attempt,
            self.evidence,
            self.receipt,
        )

    def to_dict(self) -> dict[str, Any]:
        """The wire view written to the spine ledger. Digests included."""

        body: dict[str, Any] = {"error": self.error}
        for name in ("runtime", "policy", "attempt", "evidence", "receipt"):
            contract = getattr(self, name)
            body[name] = None if contract is None else contract.to_dict()
            body[f"{name}_sha256"] = None if contract is None else contract.digest
        return body

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AttemptContractSet":
        """Read the set back out of a ledger row.

        The round trip goes through each contract's own ``from_dict``, so a
        record that was tampered with in the ledger fails to reconstruct rather
        than reappearing as a plausible object.
        """

        if not isinstance(payload, Mapping):
            raise ValueError("attempt contract set must be an object")
        readers = (
            ("runtime", RuntimeManifest),
            ("policy", PolicyDecision),
            ("attempt", AttemptContract),
            ("evidence", EvidencePacket),
            ("receipt", AttemptReceipt),
        )
        built: dict[str, Any] = {"error": payload.get("error")}
        for name, contract_cls in readers:
            raw = payload.get(name)
            built[name] = None if raw is None else contract_cls.from_dict(raw)
        return cls(**built)


def canonicalise_attempt(
    result: Any,
    *,
    task: Any,
    mission_id: str,
    attempt_id: str,
    base_revision: str,
    adapter_id: str,
    evidence_locator: str | None,
    budget: ResourceBudget,
    usage: ResourceUsage,
    created_at: str,
    locator_error: str | None = None,
    spend_grant_microusd: int = 0,
    campaign_id: str | None = None,
    trace_id: str | None = None,
    assurance: str | None = None,
) -> AttemptContractSet:
    """Turn one finished :class:`AttemptResult` into the canonical records.

    Returns rather than raises: an attempt that already produced a patch and a
    gate verdict must not be destroyed because its canonical projection could
    not be built. The reason travels on the set and into the ledger, so a
    contract that silently stopped being produced is visible instead of absent.
    """

    runtime: RuntimeManifest | None = None
    policy: PolicyDecision | None = None
    attempt: AttemptContract | None = None
    evidence: EvidencePacket | None = None
    try:
        runtime = attempt_runtime_manifest(
            source_revision=base_revision,
            created_at=created_at,
            adapter_id=adapter_id,
            trace_id=trace_id,
        )
        target_paths = tuple(getattr(task, "target_paths", ()) or ())
        state = str(getattr(result, "state", ""))
        denied = state in {"storage_unavailable", "worktree_failed"}
        # THE REFUSAL IS RECORDED FIRST, and before the scope check. A deny
        # decision grants nothing, so it does not need a declared write scope to
        # be well-formed -- and an attempt the spine turned away is exactly the
        # case where a record is most worth having. Ordering this after the
        # target_paths refusal below would have thrown away every denial made
        # against a task that never declared a scope.
        if not denied and not target_paths:
            return AttemptContractSet(
                runtime=runtime,
                error=(
                    "task declares no target_paths; refusing to mint a canonical "
                    "attempt contract for an unbounded write scope"
                ),
            )
        reasons = [
            "spine.intent_ledger: intent committed before the effect",
            "containment.worktree: candidate ran in a git worktree outside the "
            "primary checkout",
            "containment.attempt: declared target_paths bound the accepted patch",
            "storage watermark checked before any record or worktree was created",
            SPEND_GRANT_REASON,
            UNMETERED_SPEND_REASON,
            GATE_WALL_BOUND_REASON,
        ]
        if denied:
            reasons = [
                f"attempt spine refused before the effect: state={state}",
                str(getattr(result, "error", "") or "no reason recorded"),
                UNMETERED_SPEND_REASON,
            ]
        timeout_s = int(float(getattr(task, "gate_timeout_s", 0) or 0)) or None
        policy = attempt_policy_decision(
            decision_id=f"{attempt_id}:policy",
            subject_id=attempt_id,
            subject_sha256=str(getattr(task, "digest")),
            source_revision=base_revision,
            created_at=created_at,
            verdict="deny" if denied else "allow",
            reasons=reasons,
            writable_paths=target_paths,
            timeout_s=timeout_s,
            spend_grant_microusd=spend_grant_microusd,
            trace_id=trace_id,
        )
        if denied:
            return AttemptContractSet(
                runtime=runtime,
                policy=policy,
                error=(
                    "attempt was refused before any effect; the deny decision IS "
                    "the record and there is no evidence to bind"
                ),
            )
        attempt = AttemptContract.from_task_spec(
            task,
            attempt_id=attempt_id,
            mission_id=mission_id,
            runtime_manifest_sha256=runtime.digest,
            policy_decision_sha256=policy.digest,
            budget=budget,
            base_revision=base_revision,
            campaign_id=campaign_id,
            provenance=ContractProvenance(
                origin=ATTEMPT_ORIGIN,
                source_revision=base_revision,
                created_at=created_at,
                input_digests=(
                    str(getattr(task, "digest")),
                    runtime.digest,
                    policy.digest,
                ),
                trace_id=trace_id,
            ),
        )
        if not evidence_locator:
            return AttemptContractSet(
                runtime=runtime,
                policy=policy,
                attempt=attempt,
                error=(
                    locator_error
                    or (
                        "gate output has no content-addressed locator; refusing "
                        "to mint an evidence packet that points at nothing"
                    )
                ),
            )
        packet_assurance = assurance or evaluator_assurance(result, task)
        evidence = EvidencePacket.from_attempt_result(
            result,
            attempt=attempt,
            packet_id=f"{attempt_id}:evidence",
            usage=usage,
            provenance=EvidencePacket.attempt_provenance(
                result,
                attempt=attempt,
                evidence_locator=evidence_locator,
                origin=ATTEMPT_ORIGIN,
                created_at=created_at,
                trace_id=trace_id,
            ),
            evidence_locator=evidence_locator,
            evaluator_assurance=packet_assurance,
        )
        receipt = AttemptReceipt.from_attempt_result(
            result,
            attempt=attempt,
            evidence=evidence,
            receipt_id=f"{attempt_id}:receipt",
            usage=usage,
            provenance=ContractProvenance(
                origin=ATTEMPT_ORIGIN,
                source_revision=base_revision,
                created_at=created_at,
                input_digests=tuple(
                    sorted(
                        {
                            attempt.digest,
                            runtime.digest,
                            policy.digest,
                            evidence.digest,
                        }
                    )
                ),
                trace_id=trace_id,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - reported, never fatal to an attempt
        return AttemptContractSet(
            runtime=runtime,
            policy=policy,
            attempt=attempt,
            evidence=evidence,
            error=f"{type(exc).__name__}: {exc}",
        )
    return AttemptContractSet(
        runtime=runtime,
        policy=policy,
        attempt=attempt,
        evidence=evidence,
        receipt=receipt,
    )


def mission_contract_for_candidate(
    candidate: Any,
    *,
    source_revision: str,
    created_at: str,
    budget: ResourceBudget,
    mission_id: str | None = None,
    trace_id: str | None = None,
) -> MissionContract:
    """Compile one picked candidate into the mission the attempt serves.

    THE PRODUCER SHIPS HERE, THE CALL SITE DOES NOT. The picker
    (``daedalus.spine.picker``) is the only live code that decides "this is the
    next thing to work on", so it -- and nothing else -- is where a
    MissionContract can honestly be minted per iteration. That file is outside
    this change's boundary, so the six-line call site is delivered as a diff
    instead of applied. Until it is applied, MissionContract has a producer
    function and no live caller, and this docstring is the place that says so
    rather than a status page that could quietly go stale.

    ``policy_sha256`` binds the declared effect-boundary registry, the same
    policy digest :func:`attempt_policy_decision` binds, so a mission and the
    attempts under it name one policy and not two.
    """

    task_id = _identifier_fragment(str(getattr(candidate, "task_id")), "candidate")
    reason = str(getattr(candidate, "reason", "") or "")
    policy_sha = _policy_registry_sha256()
    return MissionContract(
        mission_id=mission_id or f"mission-{task_id}",
        objective=str(getattr(candidate, "instruction", "") or reason or task_id),
        source_revision=source_revision,
        work_item_ids=(task_id,),
        success_criteria=(
            reason or "the declared gate passes on the candidate patch",
        ),
        policy_sha256=policy_sha,
        budget=budget,
        provenance=ContractProvenance(
            origin="daedalus.spine.picker",
            source_revision=source_revision,
            created_at=created_at,
            input_digests=(policy_sha,),
            trace_id=trace_id,
        ),
    )


def read_contract_set(result_body: Any) -> AttemptContractSet | None:
    """Recover the canonical set from a spine ledger row's ``result`` detail.

    The consumer half of the wiring: what the attempt wrote is read back as
    contracts, not as a dict a caller then interprets by hand. ``None`` means
    the row predates the canonical projection -- an absence, deliberately
    distinguishable from an empty set carrying an error.
    """

    if not isinstance(result_body, Mapping):
        return None
    payload = result_body.get("contracts")
    if payload is None:
        return None
    return AttemptContractSet.from_dict(payload)


__all__ = [
    "ATTEMPT_ENTRYPOINT_ID",
    "ATTEMPT_KILL_SWITCH_REF",
    "ATTEMPT_ORIGIN",
    "ATTEMPT_RUNTIME_ID",
    "GATE_WALL_BOUND_REASON",
    "AttemptContractSet",
    "SPEND_GRANT_REASON",
    "UNMETERED_SPEND_REASON",
    "adapter_identity",
    "attempt_policy_decision",
    "attempt_runtime_manifest",
    "read_contract_set",
    "canonicalise_attempt",
    "evaluator_assurance",
    "mission_contract_for_candidate",
]
