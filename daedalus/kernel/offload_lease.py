"""The Effect-Lease issuer: which registry rows it may issue for, and why.

WHICH ROWS. Until :func:`issuable_row` existed this module refused every row
but ``python.offload`` by construction -- ``spec = REGISTRY_BY_ID[ENTRYPOINT_ID]``
with the id spelled once at module scope, and the reason "a helper that can
issue for whichever entrypoint you name is a general-purpose capability minter".
The reason holds and nothing here weakens it. What a constant cannot say is
WHICH rows are unsafe, so 93 of 97 were refused with no statement of what was
wrong with them, and the Gate-0 repository-write classification had exactly one
door that could ever hold a lease. The predicate says the real requirement: this
issuer may issue for a row only when it can run every contract that row
declares, itself, in process, and draw every scope bound that row's effects need
from a contract that row declares. See :data:`ISSUER_CONTRACTS`,
:data:`ISSUER_EFFECTS` and :data:`EFFECT_BOUNDS`.

:func:`acquire_wave_offload_lease` remains the wave's pinned door: it names
``python.offload`` and REFUSES an ``entrypoint_id`` keyword, so no caller of the
wave path chooses which capability it is asking for.

WHAT FOLLOWS IS ABOUT THAT PINNED PATH, and it is unchanged.

One persisted ``python.offload`` Effect Lease per wave -- the issuer side.

WHY THIS MODULE EXISTS. ``daedalus/offload.py`` refuses every ``live=True``
call that arrives without an already-issued, already-persisted authorization,
and its docstring forbids the entrypoint from minting one for itself ("it never
discovers issuer secrets or mints its own lease from ambient configuration").
Until this module landed, NOTHING in production minted one: ``grep -rn
'effect_authorization=' daedalus/`` returned zero non-test call sites, so every
live loop iteration ended in ``{"action": "effect_lease_required", "wrote": []}``
and gated an empty patch (MEASURED twice; ``runs/loop/blocker_9887a98e.json``).

THE SHAPE, AND WHY IT IS THIS SHAPE. The lease is acquired ONCE PER WAVE by
the wave's starter (:meth:`daedalus.build_exec.WaveExecutor.run_wave`) and
threaded down through :meth:`daedalus.kairos.scheduler.KairosScheduler.dispatch`
into each ``offload()`` call. Not per candidate, because then the number of
capabilities in flight would be decided by how many tasks a picker happened to
return; not inside ``offload``, because an entrypoint that can authorise itself
is not bounded by anything. One wave, one lease, N narrowed executions inside
it -- and the lease's ``max_concurrency`` is the ceiling on how many of those
may be STARTED at once, enforced by the ledger, not by convention.

WHAT IS AND IS NOT A BOUNDARY HERE (plan section 1). The issuer key is a local
32-byte file under the checkout-external control root, created on first use.
It keeps a candidate that can write the repository from forging a lease,
because the key is not in the repository and is not in the environment. It does
NOT defend against anything that can already read that directory as this user.
The spend ceiling recorded on the lease is DECLARATIVE: the money is actually
stopped by ``daedalus.budget.install_process_guard``, which this module asserts
(and installs) as the ``budget.process_guard`` contract rather than restating.
Likewise ``writable_paths`` records what the wave DECLARED; the enforcement is
the isolated attempt worktree plus ``offload``'s own write guard, because an
agentic writer is not bound by the strings it was handed.

THE KILL SWITCH IS THE GENERATION. ``daedalus.spine.killswitch`` has no
generation counter, so one is derived from the permit's exact bytes. Any arm,
stop, or rewrite changes those bytes, therefore changes the generation,
therefore invalidates every lease issued under the old one -- which is what
makes a mid-wave stop revoke authority instead of merely asking for it. A
STOPPED permit yields no generation at all: the reader raises, and the raise is
a :class:`~daedalus.spine.killswitch.LoopHalted` subclass so the loop driver's
existing handler classifies it as ``killswitch`` rather than ``error``.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from daedalus.kernel.authorization import NonRuntimeEffectAuthorization
from daedalus.kernel.contracts import EffectLease, EffectLeaseRequest
from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectLeaseError,
    EffectLeaseLedger,
    EffectLeaseStateError,
    issue_effect_lease,
)
from daedalus.schemas import ContractProvenance, EffectScope, PolicyDecision
from daedalus.spine.effect_boundary import (
    REGISTRY_BY_ID,
    Effect,
    EntrypointSpec,
    GuardDecision,
    Wiring,
    registry_sha256,
)
from daedalus.spine.envelope import canonical_json, canonical_sha
from daedalus.spine.killswitch import KillSwitch, LoopHalted, profile_root_disagreement

if TYPE_CHECKING:  # pragma: no cover - typing only, never an import cycle
    from daedalus.sensitivity import Policy

#: The registry row :func:`acquire_wave_offload_lease` pins. The general issuer
#: below is parameterised, but NOT by "whichever entrypoint you name" -- see
#: :data:`ISSUER_CONTRACTS` and :func:`issuable_row` for the predicate that
#: replaced this constant as the refusal.
ENTRYPOINT_ID = "python.offload"

#: THE RULE, PART ONE: the guard contracts this module runs ITSELF, in-process,
#: as functions of subject material a caller supplies -- never of a verdict a
#: caller supplies.
#:
#: Until this set existed the issuer refused every registry row but
#: ``python.offload`` by construction ("a helper that can issue for whichever
#: entrypoint you name is a general-purpose capability minter"). The worry was
#: real and it is unchanged; what was wrong was the remedy. Hard-coding ONE id
#: refuses 46 of the 47 central rows without saying what is wrong with them,
#: and it refuses them no more safely than this predicate does: the thing that
#: must not happen is a lease issued under contracts the issuer did not run,
#: and THAT is what this set states.
#:
#: A row declaring a contract outside this set cannot be leased here, because
#: the issuer would have exactly two choices and both are defects: skip the
#: contract (recording an unrun guard as a passed one) or accept a decision the
#: caller computed (which :class:`WritePolicySource` already measured -- a
#: caller with no ``--project`` cleared every path under the UNCONFINED
#: default and the receipt said so in the ALLOW column). Refusing by name is
#: the only third answer.
ISSUER_CONTRACTS: frozenset[str] = frozenset(
    {
        "budget.process_guard",
        "provider.egress_policy",
        "provider.write_policy",
        "containment.attempt",
        # Since 2026-08-23 the issuer can also run the two contracts the
        # python.attempt row declares and no issuer implemented, which was
        # the measured Gate-0 wall (B5 handoff: exactly one door could hold
        # a lease). Both are functions of subject material a caller supplies,
        # never of a verdict it supplies:
        "containment.worktree",     # derive_wave_containment, in-module
        "spine.intent_ledger",      # _intent_ledger_decision, in-module
    }
)

#: THE RULE, PART TWO: the effects the :class:`~daedalus.schemas.EffectScope`
#: built below can actually bound. ``secrets`` and ``listen_socket`` are absent
#: because this issuer names no ``secret_refs`` and no bind authority; a lease
#: whose scope cannot express an effect is a lease that grants it unbounded,
#: which is worse than no lease.
ISSUER_EFFECTS: frozenset[str] = frozenset(
    {
        Effect.FILESYSTEM_WRITE.value,
        Effect.PROCESS_SPAWN.value,
        Effect.NETWORK_EGRESS.value,
        Effect.SPEND.value,
        Effect.REPOSITORY_MUTATION.value,
    }
)

#: THE RULE, PART THREE: which contract produces the scope field that bounds
#: each effect. Declaring an effect whose bound this issuer draws from a
#: contract the row did NOT declare is a refusal, because the alternative is a
#: scope field filled from somewhere no guard looked.
#:
#: MEASURED, and this is why the coupling exists rather than being reasoned to:
#: ``cli.loop`` declares ``network_egress`` and only ``budget.process_guard``.
#: Without this conjunct the issuer ran no egress contract, admitted no
#: endpoint, and handed ``_scope_requirements`` a network lease with an empty
#: ``egress_endpoints`` -- which raises ``EffectLeaseScopeError`` out of
#: ``issue_effect_lease``, mid-wave, after the kill switch and every contract
#: had already been evaluated. A predicate that cannot answer before the work
#: starts is not the boundary; it is a crash with a boundary's name on it.
EFFECT_BOUNDS: Mapping[str, str] = {
    # the endpoint list, admitted by `ollama_endpoint_admission` and friends
    Effect.NETWORK_EGRESS.value: "provider.egress_policy",
    Effect.LISTEN_SOCKET.value: "provider.egress_policy",
    # the declared roots, judged by `sensitivity.path_write_blocked`
    Effect.FILESYSTEM_WRITE.value: "provider.write_policy",
    Effect.REPOSITORY_MUTATION.value: "provider.write_policy",
    # the tool list and the cost ceiling. The ceiling on a lease is
    # DECLARATIVE -- `daedalus.budget.install_process_guard` is what actually
    # stops the money and the spawn -- so a row that declares spend or spawn
    # without that contract is asking for a bound this issuer only writes down.
    Effect.PROCESS_SPAWN.value: "budget.process_guard",
    Effect.PROCESS_CONTROL.value: "budget.process_guard",
    Effect.SPEND.value: "budget.process_guard",
}

#: THE RULE, PART FOUR: a row may claim a disjoint write target only when it
#: declared a containment contract, because the disjointness record this module
#: retains IS that contract's decision. A row with no containment contract that
#: nevertheless carried a ``CHECKOUT_EXTERNAL`` target would be resting on
#: another lease's measurement of another pair of roots.
CONTAINMENT_CONTRACTS: frozenset[str] = frozenset(
    {"containment.attempt", "containment.worktree"}
)

#: Identifier of the local issuer key. One id, so a lease signed by a previous
#: key file fails verification loudly instead of being silently re-signed.
ISSUER_KEY_ID = "daedalus.local.effect-issuer"

#: Names the switch a lease is bound to, recorded on both scope and execution.
KILL_SWITCH_REF = "daedalus.spine.killswitch"

POLICY_VERSION = "daedalus.wave-offload-lease/1"


def _issuer_origin(entrypoint_id: str) -> str:
    """Provenance origin for a lease of ``entrypoint_id``.

    Momus (2026-08-23): routed through the generic issuer, an attempt lease
    carried ``kernel.wave-offload-lease`` into the signed digest and every
    retained record -- wave provenance on a lease that never touched a wave.
    Origin, request id and policy version all derive from the row now; the
    historical wave spellings are preserved verbatim for ``python.offload`` so
    no existing receipt, pin or replay changes shape.
    """
    if entrypoint_id == ENTRYPOINT_ID:
        return "kernel.wave-offload-lease"
    return f"kernel.effect-lease.{entrypoint_id}"


def _issuer_policy_version(entrypoint_id: str) -> str:
    if entrypoint_id == ENTRYPOINT_ID:
        return POLICY_VERSION
    return f"daedalus.effect-lease.{entrypoint_id}/1"


def _issuer_request_id(entrypoint_id: str, mission_id: str, attempt_id: str) -> str:
    if entrypoint_id == ENTRYPOINT_ID:
        return f"{mission_id}-wave-offload-{attempt_id}"
    return f"{mission_id}-{entrypoint_id}-{attempt_id}"

#: Tools every offload attempt may spawn regardless of lane. `git` is the
#: snapshot/diff machinery offload uses to measure what changed; `python` is
#: the gate runner. Declared, not discovered.
BASE_TOOLS = ("git", "python")

#: Lane -> the endpoint that lane speaks. A lane absent from this map cannot be
#: leased: naming an endpoint we have not verified would put a claim in a
#: receipt that nobody measured.
LANE_ENDPOINTS: Mapping[str, str] = {
    "ollama": "",  # resolved live from the provider's own host, see below
    "deepseek": "https://api.deepseek.com",
}

_KEY_BYTES = 32
_MIN_TTL_S = 60
_MAX_TTL_S = 86_399  # the lease layer refuses a TTL of 24h or more


class WaveLeaseKillSwitchEngaged(LoopHalted):
    """The permit is not armed, so no capability may be issued or used.

    A :class:`LoopHalted` subclass on purpose: ``LoopDriver.run`` already
    classifies that exception as ``stop_reason='killswitch'`` (exit code 3).
    Raising a fresh exception type would have reported an operator's own stop
    as an internal error.
    """

    def __init__(self, message: str, *, deny_receipt: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.deny_receipt = dict(deny_receipt or {})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


# --------------------------------------------------------------------------- #
# checkout-external state: the control root, the issuer key, the lease ledger  #
# --------------------------------------------------------------------------- #
def control_root(repo_root: str | Path | None) -> Path:
    """The kill switch's own directory, reused rather than reinvented.

    Deriving it from :func:`daedalus.spine.killswitch.default_switch_path`
    keeps the lease ledger, the issuer key and the permit in ONE directory
    namespaced by the same repository digest, so an operator who can find one
    can find the others -- and so ``DAEDALUS_KILLSWITCH`` moves all three
    together in a test instead of splitting them across two roots.
    """
    from daedalus.spine.killswitch import default_switch_path

    return default_switch_path(repo_root).parent


def lease_ledger_path(repo_root: str | Path | None) -> Path:
    return control_root(repo_root) / "effect-leases.sqlite3"


# --------------------------------------------------------------------------- #
# the write-evidence store: what a granted, terminalised lease leaves behind   #
# --------------------------------------------------------------------------- #
#
# WHY THIS IS HERE AND NOT IN THE GATES LAYER. The Gate-0 repository-write
# chain replays retained Effect-Lease evidence; until now nothing in production
# retained any. The three facts it needs are known HERE and nowhere else: which
# lease was granted (with the exact request and policy decision the ledger only
# keeps digests of), which containment decision gated it, and -- once an
# execution has terminalised -- which terminal receipt the ledger holds.
#
# WHAT THIS MODULE DELIBERATELY DOES NOT MINT. It does not mint the chain's
# surface-bound evidence objects. Those carry a ``surface_sha256`` that only
# exists after an inventory scan, and running a gate scanner inside the effect
# path would put a gate on the critical path of every wave. The records below
# are the RAW facts; the single producer of classification rows and evidence
# objects (``scripts/declare_write_surfaces.py``) reads them and binds them to
# surfaces. One fact, one producer.

#: The fingerprint definition, pinned. See :func:`write_root_identity_sha256`.
ROOT_IDENTITY_SCHEMA = "daedalus-write-root-identity/1"

#: The retained containment decision, and the ``receipt_schema`` the chain's
#: ``primary_checkout_disjointness_receipt`` payload carries.
DISJOINTNESS_RECORD_SCHEMA = "daedalus-primary-checkout-disjointness-record/1"
DISJOINTNESS_RECEIPT_SCHEMA = "daedalus-checkout-disjointness/1"

#: The material a later reader needs to reconstitute the replay subject: the
#: ledger keeps ``lease_json`` but only the DIGESTS of the request and the
#: policy decision, and ``inspect_effect_execution`` needs the objects.
LEASE_SUBJECT_RECORD_SCHEMA = "daedalus-effect-lease-subject-record/1"

#: One derived execution identity, retained where it comes into being.
LEASE_EXECUTION_RECORD_SCHEMA = "daedalus-effect-lease-execution-record/1"

#: One terminalised execution, replayed out of the ledger.
LEASE_TERMINAL_RECORD_SCHEMA = "daedalus-effect-lease-terminal-record/1"

#: The chain's own payload id for an ``effect_lease_receipt``. Spelled here
#: because this module produces the fact that payload is built from; the gates
#: module owns the payload shape and refuses anything else.
EFFECT_LEASE_RECEIPT_SCHEMA = "daedalus-effect-lease-receipt/1"

#: The contract name the recorded decision must carry. ``containment.worktree``
#: is the one contract whose subject is a pair of roots -- attempt.py:2470 and
#: kairos/worktree.py:1197 take the same decision over the same predicate.
WORKTREE_CONTAINMENT_CONTRACT = "containment.worktree"

#: The function that takes every guard decision this module retains, and the
#: repository-relative file it lives in. Named, not guessed: a retained record
#: has to say which implementation decided, and a test resolves both.
ISSUER_TARGET = "daedalus.kernel.offload_lease:acquire_effect_lease"
ISSUER_MODULE_PATH = "daedalus/kernel/offload_lease.py"

_REVISION = re.compile(r"^[0-9a-f]{40}$")
_TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})


def write_root_identity_sha256(root: str | Path) -> str:
    """The pinned identity of one write root. Never a path string.

    THE DEFINITION, because the verifier only shape-checks 64-hex and two
    producers that disagree here would disagree undetected (Momus F4):

    * walk up from the resolved root to the nearest ancestor that EXISTS;
    * take that ancestor's filesystem identity -- ``st_dev`` and ``st_ino``,
      which on Windows are the volume serial and the file index -- so a root
      reached through a symlink, a junction, an 8.3 short name or a different
      drive mapping yields the same digest as the same root reached directly;
    * append the names that had to be descended to reach the root, in order.

    The descent is names because that is all a directory which does not exist
    yet HAS -- and it must be supported: ``derive_wave_containment`` asks about
    a PLANNED worktree root the manager creates afterwards (0f7f8187). Names
    are case-folded exactly where the platform folds them, and the payload says
    which, so the same bytes never mean two things.

    This is a MACHINE-LOCAL identity: ``st_dev``/``st_ino`` do not travel. A
    receipt therefore states a fact measured on the machine that took the
    decision, and a reader on another machine can compare digests but cannot
    re-derive them. That is stated, not claimed away.
    """

    path = Path(root)
    try:
        resolved = path.resolve()
    except (OSError, ValueError):
        resolved = Path(os.path.abspath(str(path)))
    descent: list[str] = []
    anchor = resolved
    while True:
        try:
            status = os.stat(str(anchor))
        except (OSError, ValueError):
            parent = anchor.parent
            if parent == anchor:
                raise ValueError(
                    f"no existing ancestor identifies {resolved}; the root has "
                    "no filesystem identity to fingerprint"
                )
            descent.append(anchor.name)
            anchor = parent
            continue
        break
    case_folded = os.name == "nt"
    payload = {
        "schema": ROOT_IDENTITY_SCHEMA,
        "device": int(status.st_dev),
        "inode": int(status.st_ino),
        "case_folded": case_folded,
        "descent": [
            name.casefold() if case_folded else name for name in reversed(descent)
        ],
    }
    return hashlib.sha256(canonical_json(payload).encode("ascii")).hexdigest()


def guard_decision_sha256(decision: GuardDecision) -> str:
    """The fingerprint of one taken decision, over exactly what it decided."""

    if type(decision) is not GuardDecision:
        raise TypeError("a guard-decision fingerprint requires a typed GuardDecision")
    payload = {
        "schema": "daedalus-guard-decision/1",
        "contract": str(decision.contract),
        "allowed": bool(decision.allowed),
        "evidence": str(decision.evidence),
    }
    return hashlib.sha256(canonical_json(payload).encode("ascii")).hexdigest()


def write_evidence_root(repo_root: str | Path | None, source_revision: str) -> Path:
    """The conventional store: beside the ledger, never inside the checkout.

    A CONVENTION, not a constant: every producer below takes ``evidence_root``
    as a parameter, so a caller with its own artifact root (main moved one to
    ``<profile>/.daedalus/artifacts/<digest>`` in 21c6016e) passes that instead.
    The default exists so the two callers in this repository land in one place.

    Checkout-external for the same reason the ledger is: the candidate this
    lease authorises may hold a writable checkout, and evidence about a lease
    must not be reachable by the thing the lease bounds.
    """

    if not _REVISION.fullmatch(str(source_revision)):
        raise ValueError("write evidence root requires a lowercase 40-hex revision")
    return control_root(repo_root) / "write-evidence" / str(source_revision)


def _record_sha256(body: Mapping[str, Any]) -> str:
    subject = {key: value for key, value in body.items() if key != "record_sha256"}
    return hashlib.sha256(canonical_json(subject).encode("ascii")).hexdigest()


def _publish_evidence_record(
    evidence_root: str | Path, kind: str, body: Mapping[str, Any]
) -> Path:
    """Publish one record content-addressed, exactly once.

    Through ``daedalus.atomic.publish_bytes_once`` rather than an ``open`` here:
    this module is inside the scanned package, so a raw write surface in the
    kernel is a new Gate-0 blocker, and a content-addressed store must never
    replace an object whose identity was already published.
    """

    from daedalus.atomic import publish_bytes_once

    digest = str(body["record_sha256"])
    path = Path(evidence_root) / str(kind) / f"{digest}.json"
    publish_bytes_once(path, canonical_json(dict(body)).encode("ascii"))
    return path


def record_primary_checkout_disjointness(
    decision: GuardDecision,
    *,
    primary_checkout: str | Path,
    target_root: str | Path,
    source_revision: str,
    evidence_root: str | Path,
    control_root_path: str | Path,
    recorded_at: datetime | None = None,
) -> dict[str, Any]:
    """RECORD a containment decision somebody else already took. Never re-take it.

    THE HOOK. This is the one recorder for the ``containment.worktree``
    decision, and it is deliberately a pure function of a decision that has
    already happened: it imports no predicate, calls no
    ``planned_overlap_reason``, and cannot reach a different answer than the
    call site did. ``daedalus/spine/attempt.py:2468`` takes the same decision
    over the same predicate for the attempt worktree and can call THIS function
    with THAT decision; two recorders would be two chances to disagree with the
    guard they claim to record.

    It refuses a refusal. ``disjoint`` in the chain's payload is
    ``const true``, so recording a decision that did not allow would either
    fabricate the field or emit a record no verifier can accept.
    """

    if type(decision) is not GuardDecision:
        raise TypeError("the disjointness recorder records a typed GuardDecision")
    if decision.contract != WORKTREE_CONTAINMENT_CONTRACT:
        raise ValueError(
            "the disjointness recorder records the "
            f"{WORKTREE_CONTAINMENT_CONTRACT!r} contract, not "
            f"{decision.contract!r}"
        )
    if decision.allowed is not True:
        raise ValueError(
            "a refused containment decision is not a disjointness receipt: "
            f"{decision.evidence}"
        )
    if not _REVISION.fullmatch(str(source_revision)):
        raise ValueError("a disjointness record requires a lowercase 40-hex revision")
    primary_sha256 = write_root_identity_sha256(primary_checkout)
    target_sha256 = write_root_identity_sha256(target_root)
    if primary_sha256 == target_sha256:
        # The decision said disjoint and the fingerprints say "one root".  One
        # of the two is wrong and the record must not carry both.
        raise ValueError(
            "the two roots share one identity, so the recorded decision and "
            "the measured fingerprints contradict each other"
        )
    body: dict[str, Any] = {
        "schema": DISJOINTNESS_RECORD_SCHEMA,
        "receipt_schema": DISJOINTNESS_RECEIPT_SCHEMA,
        "source_revision": str(source_revision),
        "contract": decision.contract,
        "allowed": True,
        "evidence": str(decision.evidence),
        "decision_sha256": guard_decision_sha256(decision),
        "disjoint": True,
        "primary_checkout_sha256": primary_sha256,
        "target_root_sha256": target_sha256,
        "control_root_sha256": write_root_identity_sha256(control_root_path),
        "recorded_at": _timestamp(recorded_at or _utc_now()),
    }
    body["record_sha256"] = _record_sha256(body)
    _publish_evidence_record(evidence_root, "disjointness", body)
    return body


def record_effect_lease_subject(
    lease: "WaveOffloadLease",
    *,
    evidence_root: str | Path,
    control_root_path: str | Path,
    positions: int,
    recorded_at: datetime | None = None,
) -> dict[str, Any]:
    """Retain what one granted wave lease's later replay needs.

    A thin adapter over :func:`record_effect_lease_subject_parts`, which is the
    form another issuer calls.
    """

    if type(lease) is not WaveOffloadLease:
        raise TypeError("an effect-lease subject record requires a granted lease")
    return record_effect_lease_subject_parts(
        authorization=lease.authorization,
        ledger_path=lease.ledger_path,
        evidence_root=evidence_root,
        control_root_path=control_root_path,
        positions=positions,
        recorded_at=recorded_at,
    )


def record_effect_lease_subject_parts(
    *,
    authorization: NonRuntimeEffectAuthorization,
    ledger_path: str | Path,
    evidence_root: str | Path,
    control_root_path: str | Path,
    positions: int,
    issuer_target: str = ISSUER_TARGET,
    issuer_module_path: str = ISSUER_MODULE_PATH,
    recorded_at: datetime | None = None,
) -> dict[str, Any]:
    """Retain the material a later replay needs, at the moment it exists.

    NOT the receipt. The chain's ``effect_lease_receipt`` names a TERMINAL
    receipt, which by definition does not exist when a lease is granted; that
    one is produced by :func:`emit_effect_lease_terminal_record`, out of the
    ledger, in terminal state.

    What is retained here is what the ledger does not keep: ``effect_leases``
    stores ``lease_json`` but only the ``request_sha256`` and
    ``policy_decision_sha256``, while ``inspect_effect_execution`` needs the
    request and the policy decision themselves. Without this record a granted
    lease is unreplayable the moment the process that held it exits.

    THIS IS THE FORM ANOTHER ISSUER CALLS. ``daedalus/spine/attempt.py`` holds
    its own ``NonRuntimeEffectAuthorization`` for ``python.attempt`` and no
    ``WaveOffloadLease``; it records through here rather than growing a second
    producer of the same record shape, because two producers of one record are
    two shapes waiting to drift. ``issuer_target``/``issuer_module_path`` name
    the function that took the retained decisions -- the guard-contract
    evidence a classification row carries has to name an implementation, and
    the honest answer is whichever function actually decided, which for another
    issuer is not this module's.
    """

    if type(authorization) is not NonRuntimeEffectAuthorization:
        raise TypeError(
            "an effect-lease subject record requires a NonRuntimeEffectAuthorization"
        )
    if isinstance(positions, bool) or not isinstance(positions, int) or positions < 1:
        raise ValueError("positions must be a positive integer")
    lease = authorization.lease
    revision = lease.provenance.source_revision
    if not _REVISION.fullmatch(str(revision)):
        raise ValueError("the retained lease carries no 40-hex source revision")
    body: dict[str, Any] = {
        "schema": LEASE_SUBJECT_RECORD_SCHEMA,
        "source_revision": str(revision),
        "entrypoint_id": lease.entrypoint_id,
        "lease_id": lease.lease_id,
        "lease_sha256": lease.digest,
        "issuer_key_id": lease.issuer_key_id,
        "kill_switch_generation": int(lease.kill_switch_generation),
        "ledger_path": str(ledger_path),
        "positions": int(positions),
        # WHO TOOK THE RETAINED DECISIONS. The guard-contract evidence a
        # classification row carries has to name an implementation, and the one
        # honest answer is the function that produced these exact decisions.
        # Both strings are pinned by a test that imports the module and looks
        # the function up, so a rename cannot leave a receipt pointing at a
        # target that no longer exists.
        "issuer_target": str(issuer_target),
        "issuer_module_path": str(issuer_module_path),
        "lease": lease.to_dict(),
        "request": authorization.request.to_dict(),
        "policy_decision": authorization.policy_decision.to_dict(),
        "guard_decisions": [
            {"contract": d.contract, "allowed": bool(d.allowed), "evidence": d.evidence}
            for d in authorization.guard_decisions
        ],
        "control_root_sha256": write_root_identity_sha256(control_root_path),
        "recorded_at": _timestamp(recorded_at or _utc_now()),
    }
    body["record_sha256"] = _record_sha256(body)
    _publish_evidence_record(evidence_root, "lease-subject", body)
    return body


def rebuild_effect_lease_authorization(
    subject_record: Mapping[str, Any],
    *,
    keyring: Mapping[str, bytes | str],
    ledger_path: str | Path | None = None,
) -> NonRuntimeEffectAuthorization:
    """Reconstitute the replay subject one retained record describes.

    ONE reconstitution, used by the terminal producer below and by the
    classification producer that reads this store, because two would be two
    chances to rebuild a subject the ledger never saw.

    THE GENERATION IT REPORTS is the one the retained lease was bound to, not a
    live read: ``_project_persisted_execution`` verifies the lease at the
    RETAINED start instant against ``lease.kill_switch_generation``, so that is
    the only generation a replay consults, and reading the live permit here
    would make retained evidence unreadable after any arm or stop.

    THIS IS NOT A READ-ONLY OBJECT and the type system cannot make it one:
    ``inspect_effect_execution`` (and the gates layer's
    ``EffectLeaseReplaySubject``) demand a ``NonRuntimeEffectAuthorization``,
    which also carries ``grant``/``begin_effect``/``finish_effect``. Holding the
    issuer key is what makes rebuilding possible at all, and the key lives in
    the checkout-external control root -- so this adds no authority a reader of
    that directory did not already have. Nothing in this module calls a
    mutating method on the object it returns.
    """

    if not isinstance(subject_record, Mapping):
        raise TypeError("a retained subject record must be a mapping")
    if subject_record.get("schema") != LEASE_SUBJECT_RECORD_SCHEMA:
        raise ValueError("retained record is not an effect-lease subject record")
    lease = EffectLease.from_dict(subject_record["lease"])
    request = EffectLeaseRequest.from_dict(subject_record["request"])
    policy_decision = PolicyDecision.from_dict(subject_record["policy_decision"])
    decisions = tuple(
        GuardDecision(
            str(item["contract"]), bool(item["allowed"]), str(item["evidence"])
        )
        for item in subject_record["guard_decisions"]
    )
    path = ledger_path if ledger_path is not None else subject_record["ledger_path"]
    generation = int(lease.kill_switch_generation)
    return NonRuntimeEffectAuthorization(
        lease=lease,
        request=request,
        policy_decision=policy_decision,
        effect_ledger=EffectLeaseLedger(Path(str(path))),
        lease_keyring=dict(keyring),
        guard_decisions=decisions,
        kill_switch_generation_reader=lambda: generation,
    )


def record_effect_lease_execution(
    lease: "WaveOffloadLease",
    execution: EffectExecutionRequest,
) -> dict[str, Any] | None:
    """Retain one derived execution identity, at the moment it comes into being.

    WHY NOT LIST THE LEDGER INSTEAD. A harvest that wanted to know which
    executions a lease had needed its own read-only SQLite listing, and the
    repository-write scanner counts ``sqlite3.connect`` on a non-literal
    database as ``ambiguous_sqlite_mode`` -- a BLOCKING write surface. Adding an
    unclassified blocker to the kernel, in the commit whose subject is
    classifying them, is the wrong trade. MEASURED: with the listing, this
    checkout scanned 410 -> 411 blocking surfaces, the single new one being that
    connect; without it, 410 -> 410.

    So the identity is retained where it is created rather than rediscovered:
    ``execution_for`` is the one place an execution identity comes into being,
    it memoizes, and the record it writes carries the exact request the ledger
    will later be asked about. ``inspect_effect_execution`` remains the ONLY
    reader of the effect ledger in this chain.

    Returns ``None`` when the lease was not configured with a store. Never
    raises into the caller: the execution identity is already real, and failing
    to retain it must not change what the wave may do.
    """

    if type(lease) is not WaveOffloadLease:
        raise TypeError("an execution record requires a granted lease")
    if type(execution) is not EffectExecutionRequest:
        raise TypeError("an execution record requires a typed execution request")
    if not lease.evidence_root:
        return None
    try:
        body: dict[str, Any] = {
            "schema": LEASE_EXECUTION_RECORD_SCHEMA,
            "source_revision": str(lease.lease.provenance.source_revision),
            "entrypoint_id": lease.lease.entrypoint_id,
            "lease_sha256": lease.lease.digest,
            "subject_record_sha256": str(
                lease.evidence_records.get("lease_subject", "")
            ),
            "execution_id": execution.execution_id,
            "execution_request_sha256": execution.digest,
            "execution": execution.to_dict(),
            "control_root_sha256": write_root_identity_sha256(
                lease.control_root_path
            ),
            "recorded_at": _timestamp(_utc_now()),
        }
        body["record_sha256"] = _record_sha256(body)
        _publish_evidence_record(lease.evidence_root, "lease-execution", body)
    except (OSError, TypeError, ValueError) as exc:
        lease.evidence_errors.append(
            f"execution {execution.execution_id}: {type(exc).__name__}: {exc}"
        )
        return None
    return body


def emit_effect_lease_terminal_record(
    subject_record: Mapping[str, Any],
    execution: EffectExecutionRequest,
    *,
    evidence_root: str | Path,
    control_root_path: str | Path,
    keyring: Mapping[str, bytes | str],
    ledger_path: str | Path | None = None,
) -> dict[str, Any]:
    """Produce one terminal record, in terminal state, from the ledger.

    The state comes back out of :func:`inspect_effect_execution` -- the same
    read-only projection the Gate-0 chain replays through -- and a grant, a
    start, or a still-``STARTED`` execution is refused rather than recorded.
    ``grant() -> begin_effect() -> finish_effect()`` must all be durable before
    there is anything here to name.

    ``terminal_state`` is LOWERCASE. The kernel stores ``COMPLETED``; the chain
    compares ``replay.state.lower()`` against the retained evidence payload, so
    the record carries the case the consumer compares.

    ``recorded_at`` IS THE TERMINAL RECEIPT'S OWN ``finished_at``, not the
    harvest's clock. The record is a statement about a past fact and the store
    is content-addressed, so re-harvesting the same execution republishes the
    same bytes -- a no-op -- instead of leaving one near-identical record per
    harvest for a reader to disambiguate.
    """

    if type(execution) is not EffectExecutionRequest:
        raise TypeError("a terminal record requires a typed execution request")
    authorization = rebuild_effect_lease_authorization(
        subject_record, keyring=keyring, ledger_path=ledger_path
    )
    from daedalus.kernel.effect_replay import inspect_effect_execution

    replay = inspect_effect_execution(authorization, execution)
    if replay is None:
        raise EffectLeaseStateError(
            "the retained lease has no durable start for this execution; a "
            "granted-only lease is not a terminal receipt"
        )
    terminal = replay.terminal_receipt
    if replay.pending_reconciliation or terminal is None:
        raise EffectLeaseStateError(
            "the retained execution is STARTED and has no terminal receipt; a "
            "started-only execution is not a terminal receipt"
        )
    state = str(replay.state).lower()
    if state not in _TERMINAL_STATES:
        raise EffectLeaseStateError(f"retained execution state {state!r} is not terminal")
    # NO IDENTITY RE-CHECK HERE, deliberately. A guard for "the terminal
    # receipt names another execution/lease" cannot fire: `_terminal_receipt`
    # already compares both against the persisted start receipt, which is
    # itself bound to the exact execution this call asked for, and refuses
    # before a snapshot is returned. Restating it would add two guards no test
    # can kill, which is exactly the defect 6be14dff was diagnosing.
    body: dict[str, Any] = {
        "schema": LEASE_TERMINAL_RECORD_SCHEMA,
        "receipt_schema": EFFECT_LEASE_RECEIPT_SCHEMA,
        "source_revision": str(authorization.lease.provenance.source_revision),
        "entrypoint_id": authorization.lease.entrypoint_id,
        "execution_id": execution.execution_id,
        "execution_request_sha256": execution.digest,
        "execution": execution.to_dict(),
        "lease_sha256": authorization.lease.digest,
        "subject_record_sha256": str(subject_record["record_sha256"]),
        "start_receipt_sha256": replay.start_receipt.receipt_sha256,
        "receipt_sha256": terminal.receipt_sha256,
        "terminal_state": state,
        "requested_effects": list(execution.requested_effects),
        "control_root_sha256": write_root_identity_sha256(control_root_path),
        "recorded_at": terminal.finished_at,
    }
    body["record_sha256"] = _record_sha256(body)
    _publish_evidence_record(evidence_root, "lease-terminal", body)
    return body


def harvest_effect_lease_terminal_records(
    evidence_root: str | Path,
    *,
    control_root_path: str | Path,
    keyring: Mapping[str, bytes | str],
) -> tuple[tuple[dict[str, Any], ...], tuple[str, ...]]:
    """Emit a terminal record for every retained execution that terminalised.

    Reads the retained execution identities, joins each to the subject record it
    names, and replays it. Nothing here opens the ledger: the replay does, once,
    through ``inspect_effect_execution``.

    Returns ``(records, refusals)``. A refusal is kept and named -- a harvest
    that silently skipped the executions it could not replay would report a
    clean store while the interesting rows were the ones it dropped.
    """

    root = Path(evidence_root)
    subjects: dict[str, dict[str, Any]] = {}
    records: list[dict[str, Any]] = []
    refusals: list[str] = []
    for path in sorted((root / "lease-subject").glob("*.json")):
        try:
            subject = json.loads(path.read_text(encoding="utf-8"))
            subjects[str(subject["record_sha256"])] = subject
        except (OSError, KeyError, TypeError, ValueError) as exc:
            refusals.append(f"{path.name}: unreadable subject record: {exc}")
    seen: set[str] = set()
    for path in sorted((root / "lease-execution").glob("*.json")):
        try:
            retained = json.loads(path.read_text(encoding="utf-8"))
            execution = EffectExecutionRequest(**dict(retained["execution"]))
            subject = subjects[str(retained["subject_record_sha256"])]
        except (OSError, KeyError, TypeError, ValueError) as exc:
            refusals.append(f"{path.name}: unreadable execution record: {exc}")
            continue
        seen.add(str(retained["subject_record_sha256"]))
        try:
            records.append(
                emit_effect_lease_terminal_record(
                    subject,
                    execution,
                    evidence_root=root,
                    control_root_path=control_root_path,
                    keyring=keyring,
                )
            )
        except (OSError, TypeError, ValueError, EffectLeaseError) as exc:
            # The cause travels with the refusal: the replay projection
            # collapses several distinct failures into one message, and a
            # harvest that reported only that message would name the
            # symptom instead of the fact.
            cause = exc.__cause__
            detail = f" <- {type(cause).__name__}: {cause}" if cause else ""
            refusals.append(
                f"{path.name}:{execution.execution_id}: "
                f"{type(exc).__name__}: {exc}{detail}"
            )
    for digest, subject in sorted(subjects.items()):
        if digest not in seen:
            refusals.append(
                f"{digest[:12]}: lease {subject.get('lease_id')} was granted but "
                "no execution identity was ever derived under it"
            )
    return tuple(records), tuple(refusals)


def issuer_keyring(repo_root: str | Path | None) -> dict[str, bytes]:
    """Load, or create on first use, the local lease-signing key.

    NOT from the environment. The promotion trust root measured (case A9a/A10)
    that an env-carried secret is inherited by every child this process spawns,
    which includes the candidate's own worker -- so a secret in the environment
    is a secret the candidate holds. A file outside the checkout is not a
    security boundary either, but it is not handed to children, and that is the
    difference that matters against the threat this repository actually has.
    """
    path = control_root(repo_root) / "effect-lease-issuer.key"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        material = path.read_bytes()
    except FileNotFoundError:
        material = b""
    if len(material) < _KEY_BYTES:
        fresh = os.urandom(_KEY_BYTES)
        # O_EXCL so two concurrent waves cannot both believe they created it;
        # the loser re-reads the winner's bytes. The 0o600 mode is honoured on
        # POSIX and largely cosmetic on win32 -- stated, not claimed away.
        #
        # O_BINARY, MEASURED. Without it `os.open` on Windows opens in TEXT
        # mode and translates every 0x0A byte to 0x0D 0x0A on the way out. A
        # random 32-byte key contains at least one 0x0A about 12% of the time,
        # so roughly one fresh control root in eight got a key file whose bytes
        # were NOT the bytes this process signed with -- and every lease that
        # process issued became unverifiable the moment it exited, with the
        # honest-looking message "effect lease signature mismatch". Reproduced
        # 1-in-7 over 8 fresh roots before this flag; 0-in-40 after.
        # The constant does not exist on POSIX, where the flag is a no-op.
        try:
            fd = os.open(
                str(path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0),
                0o600,
            )
        except FileExistsError:
            material = path.read_bytes()
        else:
            try:
                os.write(fd, fresh)
            finally:
                os.close(fd)
            material = fresh
    if len(material) < _KEY_BYTES:
        raise ValueError(
            f"the effect-lease issuer key at {path} is too short to sign with"
        )
    return {ISSUER_KEY_ID: material}


def kill_switch_generation(switch: KillSwitch) -> int:
    """The current generation, or raise if the permit is not armed.

    The generation is the permit's identity, not a counter: ``verify_effect_lease``
    only ever compares it for EQUALITY, so what it must express is "the switch
    is in the same state it was in when this lease was issued". A digest of the
    permit bytes says exactly that and needs no new file to maintain.
    """
    # THE LATCH FIRST, THEN THE DISK. `read_state` deliberately reads the
    # permit fresh and does NOT consult the in-process latch, so a switch that
    # already tripped -- because a stop was requested, or because the permit
    # was once unreadable, which this module's own rule counts as STOP --
    # would hand out a capability again the moment the file looked healthy.
    # `should_stop` is sticky by construction and never raises, so consulting
    # it makes the lease follow the same stop the loop's cancel token follows.
    if getattr(switch, "should_stop", None) is not None and switch.should_stop():
        raise WaveLeaseKillSwitchEngaged(
            f"kill switch engaged: {switch.reason or 'stop latched'} "
            f"[{switch.path}]"
        )
    state = switch.read_state()
    if not state.running:
        raise WaveLeaseKillSwitchEngaged(
            f"kill switch engaged: {state.reason} [{switch.path}]"
        )
    try:
        material = Path(switch.path).read_bytes()
    except OSError as exc:  # unreadable permit is STOP, same as read_state's rule
        raise WaveLeaseKillSwitchEngaged(
            f"kill switch permit could not be read ({exc}) [{switch.path}]"
        ) from exc
    return int(hashlib.sha256(material).hexdigest()[:12], 16)


# --------------------------------------------------------------------------- #
# which policy text decides the write fence                                    #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class WritePolicySource:
    """The policy that answered "may this wave write here", and its identity.

    WHY THIS EXISTS (MEASURED). ``sensitivity.path_write_blocked(path, None)``
    falls back to :data:`daedalus.sensitivity.DEFAULT_POLICY`, whose
    ``write_allow`` is empty -- which means UNCONFINED. Against this checkout::

        path_write_blocked('.agentenv/agentenv.json', None)            -> False
        path_write_blocked('daedalus/sensitivity.py', None)            -> False
        path_write_blocked('docs/IKARUS_ARIADNE_MASTER_PLAN.md', None) -> False

    and under the repository's own ``.agentenv/agentenv.json`` all three are
    ``True``. So a loop iteration run WITHOUT ``--project`` handed the issuer an
    empty ``write_policy_blocked`` list, the ``provider.write_policy`` contract
    allowed, and the receipt recorded "cleared every declared path" -- a guard
    that had never run, written down as a guard that had passed.

    An absent policy is therefore NOT a permission here. When none can be
    loaded, :attr:`policy` is ``None`` and the contract REFUSES; the lease is
    denied with the reason on the receipt. And when one is loaded, the receipt
    names WHICH file (path + sha256 of its exact bytes) cleared the paths, so a
    reader can fetch that file and recompute the verdict instead of trusting
    the sentence.
    """

    policy: "Policy | None"
    origin: str
    sha256: str
    error: str = ""

    @property
    def usable(self) -> bool:
        return self.policy is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "origin": self.origin,
            "sha256": self.sha256,
            "error": self.error or None,
        }


#: Identity stamped on a policy the CALLER supplied as an object. There are no
#: bytes on disk to digest, so the digest is over the exact fields
#: :func:`~daedalus.sensitivity.path_write_blocked` reads -- nothing else about
#: a Policy can change its verdict, and a digest over fields it ignores would
#: change without the decision changing.
CALLER_POLICY_ORIGIN = "caller-supplied:daedalus.sensitivity.Policy"


def resolve_write_policy(
    repo_root: str | Path, policy: "Policy | None" = None
) -> WritePolicySource:
    """Name the policy that will decide this wave's write fence.

    With ``policy`` given, it is used and identified by a digest over the three
    fields ``path_write_blocked`` consults. With ``policy`` omitted -- the loop
    run WITHOUT ``--project``, which is how this hole was reached -- the
    repository's own ``.agentenv/agentenv.json`` is loaded through
    :func:`daedalus.config._repo_local_policy`, the one existing reader of that
    file, rather than a second parser written here.

    Every failure mode (no file, unreadable, malformed JSON, no ``policy``
    block) returns ``policy=None`` with the reason on :attr:`WritePolicySource.error`.
    It never falls back to ``DEFAULT_POLICY``: that fallback IS the bug.
    """
    from daedalus.config import REPO_CONFIG, _repo_local_policy
    from daedalus.sensitivity import load_policy

    if policy is not None:
        return WritePolicySource(
            policy=policy,
            origin=CALLER_POLICY_ORIGIN,
            sha256=canonical_sha(
                {
                    "write_allow": list(getattr(policy, "write_allow", ()) or ()),
                    "deny_substrings": list(
                        getattr(policy, "deny_substrings", ()) or ()
                    ),
                    "high_risk_path_substrings": list(
                        getattr(policy, "high_risk_path_substrings", ()) or ()
                    ),
                }
            ),
        )

    path = Path(repo_root) / REPO_CONFIG
    origin = str(path)
    block = _repo_local_policy(str(repo_root))
    if not block:
        return WritePolicySource(
            policy=None,
            origin=origin,
            sha256="",
            error=(
                f"no usable 'policy' block at {origin} (absent, unreadable, "
                f"malformed, or without one)"
            ),
        )
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        return WritePolicySource(
            policy=None,
            origin=origin,
            sha256="",
            error=f"{origin} could not be digested ({exc})",
        )
    return WritePolicySource(
        policy=load_policy({"policy": block}), origin=origin, sha256=digest
    )


def wave_containment_roots(repo_root: str | Path) -> tuple[str, str]:
    """The two roots the containment predicate is about. It decides nothing.

    Split out so the decision below and the record that retains it name the
    same pair without either one resolving the pair for itself. Raises when the
    isolation root cannot be resolved at all; the caller turns that into a
    refusal, because unknown containment is no containment.
    """

    from daedalus.kairos.worktree import GitWorktreeManager

    root = Path(repo_root).resolve()
    return str(root), str(GitWorktreeManager(root).worktree_root)


def derive_wave_containment(repo_root: str | Path) -> tuple[bool, str]:
    """Does THIS checkout's isolation machinery really land outside it?

    WHY THE ISSUER DERIVES THIS (MEASURED, Odysseus F2). ``contained`` and
    ``containment_evidence`` are caller-supplied, and the caller was believed::

        acquire_wave_offload_lease(repo, ..., contained=True,
                                   containment_evidence="")
          -> granted, signed, persisted; receipt reason
             "containment.attempt: wave containment was asserted by the caller
              with no evidence"

    from any script that can ``import daedalus``. A capability issued on the
    strength of a boolean the requester set is a capability with no contract
    behind it, and a receipt that says "asserted with no evidence" in the ALLOW
    column is worse than no receipt: it reads as a guard that ran.

    What the issuer CAN check without the caller is the structural half:
    ``daedalus.kairos.gated_writes.run_write_wave`` isolates each write task in
    a ``TaskAttempt`` worktree allocated by
    :class:`daedalus.kairos.worktree.GitWorktreeManager`, whose ``worktree_root``
    is outside the checkout by construction -- unless it is not, on this
    machine, under this environment, which is exactly the fact worth checking.
    :func:`daedalus.primary_tree.planned_overlap_reason` is the one
    implementation of that comparison for a directory that may not exist yet,
    and it is bidirectional, so a root that would CONTAIN the checkout fails
    too.

    This is a precondition, not the whole contract: it says candidate checkouts
    can land outside the primary tree, not that this particular wave routed
    through them. The caller still has to name the mechanism it used, and
    :func:`acquire_wave_offload_lease` now refuses an empty name.
    """
    from daedalus.primary_tree import planned_overlap_reason

    root = Path(repo_root).resolve()
    try:
        _, worktree_root = wave_containment_roots(root)
    except Exception as exc:  # noqa: BLE001 - unknown containment is no containment
        return False, (
            f"the isolation root for {root} could not be resolved "
            f"({type(exc).__name__}: {exc}), so containment cannot be derived"
        )
    # A PLANNED directory: the manager creates it after the check, so it is
    # asked about the name it will land on, not about its existing ancestor
    # (which contains the checkout for every sibling root -- 57a2e7cb).
    overlap = planned_overlap_reason(Path(worktree_root), root)
    if overlap is not None:
        return False, (
            f"the attempt isolation root {worktree_root} overlaps the primary "
            f"checkout: {overlap}"
        )
    return True, (
        f"primary_tree.planned_overlap_reason({worktree_root}, {root}) is "
        f"None: TaskAttempt worktrees allocated under {worktree_root} land "
        f"outside the primary checkout in both directions"
    )


def lane_endpoint(lane: str) -> str:
    """The endpoint a dispatch lane speaks, or ``""`` when none is declared."""
    if lane == "ollama":
        from daedalus.providers.ollama import DEFAULT_HOST

        return (os.environ.get("OLLAMA_HOST") or DEFAULT_HOST).strip().rstrip("/")
    return LANE_ENDPOINTS.get(lane, "")


# --------------------------------------------------------------------------- #
# the results                                                                  #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class WaveLeaseDenied:
    """No capability was issued, and the canonical reason why.

    The deny :class:`~daedalus.schemas.PolicyDecision` IS the receipt: it is a
    digest-bearing, provenance-bearing contract that ``issue_effect_lease``
    itself refuses to turn into a lease ("deny policy decisions cannot issue
    leases"), so the refusal and the record cannot drift apart.
    """

    policy_decision: PolicyDecision
    reasons: tuple[str, ...]
    guard_decisions: tuple[GuardDecision, ...] = ()
    #: WHICH policy text refused (or could not be found). Defaulted so the one
    #: hand-built denial in ``build_exec`` -- a missing source revision, decided
    #: before any policy is consulted -- keeps its exact shape.
    write_policy: WritePolicySource | None = None
    #: WHICH row was refused. Defaulted to ``python.offload`` so the hand-built
    #: denial above keeps its exact shape; a denial that named the wrong row
    #: would be a receipt about a capability nobody asked for.
    entrypoint_id: str = ENTRYPOINT_ID

    @property
    def granted(self) -> bool:
        return False

    def receipt(self) -> dict[str, Any]:
        return {
            "verdict": "deny",
            "entrypoint_id": self.entrypoint_id,
            "policy_decision_id": self.policy_decision.decision_id,
            "policy_decision_sha256": self.policy_decision.digest,
            "policy_version": self.policy_decision.policy_version,
            "reasons": list(self.reasons),
            "guard_decisions": [
                {"contract": d.contract, "allowed": d.allowed, "evidence": d.evidence}
                for d in self.guard_decisions
            ],
            "registry_sha256": registry_sha256(),
            "write_policy": (
                None if self.write_policy is None else self.write_policy.to_dict()
            ),
            "lease_id": None,
            "requested_effects": [],
            "security_boundary_claimed": False,
            "at": _timestamp(_utc_now()),
        }


@dataclass(frozen=True)
class WaveOffloadLease:
    """One granted, persisted lease plus the narrowed executions inside it."""

    authorization: NonRuntimeEffectAuthorization
    lease: EffectLease
    request: EffectLeaseRequest
    policy_decision: PolicyDecision
    ledger: EffectLeaseLedger = field(repr=False)
    ledger_path: str = ""
    #: The policy that cleared the declared roots, named on the receipt.
    write_policy: WritePolicySource | None = None
    _executions: dict[int, EffectExecutionRequest] = field(
        default_factory=dict, repr=False
    )
    #: Where this grant's evidence is retained, and under which control root.
    #: Both are strings the caller chose (see ``acquire_wave_offload_lease``'s
    #: ``evidence_root``); empty means this lease retains nothing.
    evidence_root: str = ""
    control_root_path: str = ""
    #: What the write-evidence store retained for this grant, and why it could
    #: not, when it could not. A list rather than a raise: retaining evidence
    #: must never be able to deny a capability the ledger already accepted, and
    #: a silent skip would leave a store that looks complete.
    evidence_records: dict[str, str] = field(default_factory=dict, repr=False)
    evidence_errors: list[str] = field(default_factory=list, repr=False)

    @property
    def granted(self) -> bool:
        return True

    @property
    def lease_id(self) -> str:
        return self.lease.lease_id

    @property
    def requested_effects(self) -> tuple[str, ...]:
        return tuple(self.lease.requested_effects)

    def execution_for(
        self, position: int, writable_paths: Sequence[str] = ()
    ) -> EffectExecutionRequest:
        """The narrowed execution request for one task position in the wave.

        Derived, never supplied: position is the same 1:1 index the wave's
        tasks/assignments/results already share, so two candidates can never
        collide on one execution identity and one candidate re-dispatched in
        the same wave is correctly refused as a replay rather than run twice.
        """
        key = int(position)
        cached = self._executions.get(key)
        if cached is not None:
            return cached
        scope = self.lease.effect_scope
        declared = tuple(str(p) for p in writable_paths if str(p).strip())
        execution = EffectExecutionRequest(
            execution_id=f"{self.lease.lease_id}-exec-{key}",
            idempotency_key=f"{self.lease.idempotency_namespace}-{key}",
            requested_effects=tuple(self.lease.requested_effects),
            # The lease's own roots when the task declared none. A write
            # execution MUST name paths (the lease layer refuses otherwise),
            # and inventing a narrower claim than the wave can honour would put
            # a false bound in the receipt.
            writable_paths=declared or scope.writable_paths,
            egress_endpoints=scope.egress_endpoints,
            tools=scope.tools,
            max_cost_microusd=scope.max_cost_microusd or 0,
            kill_switch_ref=scope.kill_switch_ref,
            kill_switch_generation=self.lease.kill_switch_generation,
        )
        self._executions[key] = execution
        # Retained HERE because this is the one place an execution identity
        # comes into being, and because rediscovering the set later would mean
        # a second reader of the effect ledger. See
        # `record_effect_lease_execution` -- it never raises into this call.
        record_effect_lease_execution(self, execution)
        return execution

    def issued_execution(self, position: int) -> EffectExecutionRequest | None:
        """The execution ALREADY derived for ``position``, or None.

        Read-only on purpose: a receipt writer must be able to report what was
        issued without causing another execution identity to come into being.
        """
        return self._executions.get(int(position))

    def receipt(self) -> dict[str, Any]:
        """What the loop receipt and the attempt ledger carry about this lease."""
        scope = self.lease.effect_scope
        return {
            "verdict": "allow",
            "entrypoint_id": self.lease.entrypoint_id,
            "lease_id": self.lease.lease_id,
            "lease_sha256": self.lease.digest,
            "requested_effects": list(self.lease.requested_effects),
            "policy_decision_id": self.policy_decision.decision_id,
            "policy_decision_sha256": self.policy_decision.digest,
            "policy_version": self.policy_decision.policy_version,
            "issuer_key_id": self.lease.issuer_key_id,
            "issued_at": self.lease.issued_at,
            "expires_at": self.lease.expires_at,
            "kill_switch_ref": scope.kill_switch_ref,
            "kill_switch_generation": self.lease.kill_switch_generation,
            "max_cost_microusd": scope.max_cost_microusd,
            "max_concurrency": scope.max_concurrency,
            "timeout_s": scope.timeout_s,
            "writable_paths": list(scope.writable_paths),
            "egress_endpoints": list(scope.egress_endpoints),
            "tools": list(scope.tools),
            "execution_ids": [
                self._executions[k].execution_id for k in sorted(self._executions)
            ],
            "registry_sha256": self.lease.registry_sha256,
            # WHICH policy cleared `writable_paths`. Without this the receipt
            # said "cleared every declared path" and a reader had no way to
            # discover that the clearing policy was the unconfined default.
            "write_policy": (
                None if self.write_policy is None else self.write_policy.to_dict()
            ),
            "ledger_path": self.ledger_path,
            "security_boundary_claimed": False,
        }


# --------------------------------------------------------------------------- #
# the issuer                                                                   #
# --------------------------------------------------------------------------- #
def _intent_ledger_decision(root: Path, effect_key: str | None) -> GuardDecision:
    """``spine.intent_ledger``, run by the issuer itself.

    The contract at issuance time: the effect key this lease would authorise
    must already be an INTENDED row in the repository's own attempt ledger --
    the durable record that precedes the worktree and the runner. A lease for
    an effect nobody intends is a capability in search of an effect, and an
    intent that is already resolved is an effect that already happened; both
    are refusals, not defaults.

    READ-ONLY BY CONSTRUCTION: the ledger is opened with sqlite's ``mode=ro``
    URI, so this guard cannot create the database it claims to inspect, and a
    missing ledger is a deny rather than a fresh file. The path comes from
    :func:`daedalus.spine.picker.resolve_spine_db_path`, the repo-confined
    resolver -- deliberately not ``DAEDALUS_SPINE_DB``, the process-global
    surface (Codex, room turn 51: the two resolvers must not be unified).
    The intent's state is the newest ``intent_events`` row, exactly as
    :meth:`SpineLedger.get` derives it.
    """
    contract = "spine.intent_ledger"
    if not effect_key:
        return GuardDecision(
            contract, False,
            "the row declares spine.intent_ledger and the caller supplied no "
            "effect_key; a lease for an attempt nobody intends cannot be "
            "issued")
    from daedalus.spine.picker import resolve_spine_db_path

    path, err = resolve_spine_db_path(root)
    if err or path is None:
        return GuardDecision(
            contract, False,
            f"the attempt ledger path could not be resolved ({err}); an "
            f"intent with nowhere durable to land is not an intent")
    if not Path(path).exists():
        return GuardDecision(
            contract, False,
            f"no attempt ledger exists at {path}; the INTENDED row this lease "
            f"would authorise has nowhere to be")
    import sqlite3

    try:
        uri = f"file:{Path(path).resolve().as_posix()}?mode=ro"
        with contextlib.closing(sqlite3.connect(uri, uri=True, timeout=5)) as conn:
            row = conn.execute(
                "SELECT i.id, ("
                " SELECT e.state FROM intent_events e"
                " WHERE e.intent_id = i.id ORDER BY e.id DESC LIMIT 1"
                ") AS state FROM intents i WHERE i.effect_key = ?"
                " ORDER BY i.id DESC LIMIT 1",
                (str(effect_key),),
            ).fetchone()
    except sqlite3.Error as exc:
        return GuardDecision(
            contract, False,
            f"the attempt ledger at {path} could not be read "
            f"({type(exc).__name__}: {exc}); an unreadable intent record is "
            f"no intent record")
    if row is None:
        return GuardDecision(
            contract, False,
            f"no intent in {path} names effect_key {effect_key!r}; the intent "
            f"must be recorded before the capability that acts on it")
    intent_id, state = int(row[0]), str(row[1] or "")
    if state != "INTENDED":
        return GuardDecision(
            contract, False,
            f"the newest intent for effect_key {effect_key!r} (id {intent_id}) "
            f"is {state or 'stateless'}, not INTENDED: this lease would "
            f"authorise an effect whose intent is already resolved")
    return GuardDecision(
        contract, True,
        f"intent {intent_id} is INTENDED for effect_key {effect_key!r} in "
        f"{path}, read-only; the durable record precedes the capability")


def issuable_row(entrypoint_id: str) -> tuple[EntrypointSpec | None, tuple[str, ...]]:
    """The row this issuer may issue for, or every named reason it may not.

    THE PREDICATE THAT REPLACED THE CONSTANT. Five conjuncts, each of which can
    come back False against the real registry, and none of which the caller
    supplies:

    1. the id is registered -- an unknown row has no declared contracts at all,
       so there is nothing to run and nothing to bound;
    2. the row is ``CENTRAL`` -- :func:`issue_effect_lease` refuses anything
       else anyway, and refusing here makes it a deny receipt instead of a
       raise inside a wave;
    3. the row is not runtime-bearing -- a ``runtime_id`` requires
       :class:`~daedalus.kernel.runtime_effects.RuntimeBoundEffectAuthorization`
       and its live trust rechecks, which this module does not perform;
    4. every contract the row declares is in :data:`ISSUER_CONTRACTS`;
    5. every effect the row declares is in :data:`ISSUER_EFFECTS`, and there is
       at least one -- ``begin_effect`` refuses an effect start that declares
       none.

    Returns ``(spec, ())`` when the row is issuable and ``(None, reasons)``
    when it is not. Never raises: a refusal is a verdict about a request, and
    the caller turns it into the canonical deny receipt.
    """

    spec = REGISTRY_BY_ID.get(str(entrypoint_id))
    if spec is None:
        return None, (
            f"registry.row: {entrypoint_id!r} is not a registered entrypoint, "
            "so it declares no contracts to run and no effects to bound",
        )
    reasons: list[str] = []
    if spec.wiring is not Wiring.CENTRAL:
        reasons.append(
            f"registry.wiring: {spec.id} is {spec.wiring.value}, not central; "
            "migration is required before a capability can be issued for it"
        )
    if spec.runtime_id:
        reasons.append(
            f"registry.runtime: {spec.id} is runtime-bearing ({spec.runtime_id}), "
            "so it requires RuntimeBoundEffectAuthorization and live runtime-trust "
            "rechecks this issuer does not perform"
        )
    unrunnable = sorted(set(spec.guard_contracts) - ISSUER_CONTRACTS)
    if unrunnable:
        reasons.append(
            f"issuer.contracts: {spec.id} declares {', '.join(unrunnable)}, which "
            "this issuer has no in-process implementation of; skipping them would "
            "record an unrun guard as a passed one and accepting them from the "
            "caller is not a guard"
        )
    declared_effects = {effect.value for effect in spec.effects}
    if not declared_effects:
        reasons.append(
            f"registry.effects: {spec.id} declares no effect, and an effect start "
            "that declares none is refused at the boundary"
        )
    unboundable = sorted(declared_effects - ISSUER_EFFECTS)
    if unboundable:
        reasons.append(
            f"issuer.effects: {spec.id} declares {', '.join(unboundable)}, which the "
            "effect scope this issuer builds cannot bound; an unbounded grant in a "
            "receipt reads as a bounded one"
        )
    unbounded = sorted(
        f"{effect} (needs {EFFECT_BOUNDS[effect]})"
        for effect in declared_effects & set(EFFECT_BOUNDS)
        if EFFECT_BOUNDS[effect] not in spec.guard_contracts
    )
    if unbounded:
        reasons.append(
            f"issuer.effect_bounds: {spec.id} declares {', '.join(unbounded)}; this "
            "issuer draws that scope field from the named contract, and the row does "
            "not declare it, so the bound would be filled from somewhere no guard "
            "looked"
        )
    if reasons:
        return None, tuple(reasons)
    return spec, ()


def _deny(
    *,
    reasons: Sequence[str],
    guard_decisions: Sequence[GuardDecision],
    origin: str = "kernel.wave-offload-lease",
    policy_version: str = POLICY_VERSION,
    source_revision: str,
    trace_id: str | None,
    subject_id: str,
    subject_sha256: str,
    policy_sha256: str,
    now: datetime,
    write_policy: WritePolicySource | None = None,
    entrypoint_id: str = ENTRYPOINT_ID,
) -> WaveLeaseDenied:
    decision = PolicyDecision(
        decision_id=f"{subject_id}-deny",
        subject_id=subject_id,
        subject_sha256=subject_sha256,
        policy_version=policy_version,
        policy_sha256=policy_sha256,
        verdict="deny",
        reasons=tuple(reasons),
        # A deny decision may not carry grants -- the contract enforces it.
        effect_scope=EffectScope(),
        provenance=ContractProvenance(
            origin=origin,
            source_revision=source_revision,
            created_at=_timestamp(now),
            # DEDUPED. On this path the subject digest IS the policy digest
            # (there is no EffectLeaseRequest to hash, see the call site), and
            # ContractProvenance refuses duplicate input digests -- so the
            # canonical deny record could not be built at all the moment the
            # write contract started refusing for itself. Measured: ValueError
            # "provenance.input_digests must not contain duplicates".
            input_digests=tuple(sorted({subject_sha256, policy_sha256})),
            trace_id=trace_id,
        ),
    )
    return WaveLeaseDenied(
        policy_decision=decision,
        reasons=tuple(sorted(reasons)),
        guard_decisions=tuple(guard_decisions),
        write_policy=write_policy,
        entrypoint_id=str(entrypoint_id),
    )


def acquire_effect_lease(
    repo_root: str | Path,
    *,
    entrypoint_id: str = ENTRYPOINT_ID,
    source_revision: str,
    mission_id: str,
    attempt_id: str,
    positions: int,
    writable_paths: Sequence[str] = (),
    lanes: Sequence[str] = (),
    tools: Sequence[str] = (),
    max_spend_usd: float | None = None,
    timeout_s: float | None = None,
    contained: bool = True,
    containment_evidence: str = "",
    write_policy_blocked: Sequence[str] = (),
    write_policy: "Policy | None" = None,
    switch: KillSwitch | None = None,
    trace_id: str | None = None,
    lease_id: str | None = None,
    now: datetime | None = None,
    evidence_root: str | Path | None = None,
    effect_key: str | None = None,
) -> WaveOffloadLease | WaveLeaseDenied:
    """Run the guard contracts ONE registry row declares, then issue or deny.

    Returns a :class:`WaveOffloadLease` when every contract allows, and a
    :class:`WaveLeaseDenied` -- never an exception, never a partial grant --
    when one refuses. The one exception it DOES raise is
    :class:`WaveLeaseKillSwitchEngaged`, because a revoked permit is not a
    verdict about this wave: it is an instruction to stop the run.

    The caller supplies what only it can know (which lanes this wave routes to,
    which paths the tasks declared, whether the attempts are contained). This
    module owns everything a caller must not be trusted with: the issuer key,
    the generation, the ledger location, and -- through :func:`issuable_row` --
    the refusal to issue for any row whose contracts it cannot run itself.

    WHICH CONTRACTS RUN IS THE ROW'S DECISION, NOT THIS FUNCTION'S. Only the
    contracts ``spec.guard_contracts`` names are evaluated, and every one of
    them is. That is not a convenience: ``begin_effect`` refuses BOTH a missing
    decision and an undeclared one, so a lease carrying this module's four
    offload decisions could never be started for a row that declares one
    contract. The same rule decides the scope -- a row that does not declare
    ``network_egress`` is granted no endpoint, and one that does not declare
    ``spend`` is granted a ceiling of zero, because a scope that grants what
    the row never declared is a widening nobody asked for.

    THE WRITE FENCE IS RUN HERE, NOT ACCEPTED FROM THE CALLER.
    ``write_policy_blocked`` used to BE the ``provider.write_policy`` contract:
    a list the caller computed, which the issuer copied into a receipt. A
    caller with no ``--project`` computed it against ``policy=None``, which is
    the UNCONFINED default, so the list came back empty and the receipt said
    "cleared every declared path" (see :class:`WritePolicySource` for the
    measurement). The issuer now resolves the policy itself -- ``write_policy``
    when given, otherwise the repository's own ``.agentenv/agentenv.json`` --
    runs ``path_write_blocked`` over the declared roots, and DENIES when no
    policy can be loaded at all. The caller's list is still honoured, unioned
    in as corroboration; it can only ever add a refusal, never remove one.
    """
    instant = now or _utc_now()
    root = str(Path(repo_root).resolve())
    live_switch = switch if switch is not None else KillSwitch(repo_root=root)
    door = str(entrypoint_id)
    request_id = _issuer_request_id(door, mission_id, attempt_id)

    # -- 0. THE RULE. Before the kill switch, because a row this issuer may
    # never issue for is not a question about this machine's permit state; it
    # is a question about the registry, and the answer does not change.
    spec, row_refusals = issuable_row(door)
    if spec is None:
        # No EffectLeaseRequest and no guard decisions exist on this path: the
        # refusal happened before a single contract was consulted, so the
        # subject digest is over the refusal material itself.
        refusal_sha256 = canonical_sha(
            {
                "policy_version": POLICY_VERSION,
                "entrypoint_id": door,
                "registry_sha256": registry_sha256(),
                "issuer_contracts": sorted(ISSUER_CONTRACTS),
                "issuer_effects": sorted(ISSUER_EFFECTS),
                "reasons": sorted(row_refusals),
            }
        )
        return _deny(
            origin=_issuer_origin(door),
            policy_version=_issuer_policy_version(door),
            reasons=row_refusals,
            guard_decisions=(),
            source_revision=source_revision,
            trace_id=trace_id,
            subject_id=request_id,
            subject_sha256=refusal_sha256,
            policy_sha256=refusal_sha256,
            now=instant,
            entrypoint_id=door,
        )
    effects = tuple(sorted(effect.value for effect in spec.effects))
    declared_contracts = frozenset(spec.guard_contracts)
    declared_effects = frozenset(effects)

    # -- 1. the kill switch, before anything is computed for this wave ------ #
    # Raises. See WaveLeaseKillSwitchEngaged for why this one is not a verdict.
    generation = kill_switch_generation(live_switch)

    # -- 2. the guard contracts THIS ROW declares --------------------------- #
    guards: list[GuardDecision] = []
    if "budget.process_guard" in declared_contracts:
        from daedalus.budget import process_guard_boundary_decision

        guards.append(process_guard_boundary_decision())

    endpoints: list[str] = []
    egress_reasons: list[str] = []
    egress_ok = True
    if "provider.egress_policy" in declared_contracts:
        for lane in sorted({str(l) for l in lanes if str(l).strip()}):
            endpoint = lane_endpoint(lane)
            if not endpoint:
                egress_ok = False
                egress_reasons.append(
                    f"lane {lane!r} declares no endpoint, so its egress cannot be leased"
                )
                continue
            if lane == "ollama":
                from daedalus.providers.ollama import ollama_endpoint_admission

                allowed, _lane, evidence = ollama_endpoint_admission(endpoint)
                egress_reasons.append(f"{lane}: {evidence}")
                if not allowed:
                    egress_ok = False
                    continue
            else:
                egress_reasons.append(
                    f"{lane}: declared endpoint {endpoint} (no admission contract "
                    f"implements this lane yet, so it is leased only as a declaration)"
                )
            endpoints.append(endpoint)
        if not endpoints:
            egress_ok = False
            egress_reasons.append(
                "no admissible endpoint for this wave; a network-effect lease must "
                "name at least one"
            )
        guards.append(
            GuardDecision("provider.egress_policy", egress_ok, "; ".join(egress_reasons))
        )
    else:
        # NOT RUN, THEREFORE NOT GRANTED. The endpoints stay empty so the scope
        # below carries none: a row that does not declare `provider.egress_policy`
        # gets no leased endpoint, rather than an unadmitted one.
        endpoints = []

    # The exact roots this lease would grant, computed BEFORE the write
    # contract so the contract judges the same strings the scope will carry.
    # ``(".",)`` is the whole checkout: under a confining policy that reads as
    # a refusal, which is the right answer for "this wave declared no bound".
    declared_paths = tuple(
        sorted({str(p).strip() for p in writable_paths if str(p).strip()})
    ) or (".",)

    policy_source = resolve_write_policy(root, write_policy)
    caller_blocked = tuple(str(p) for p in write_policy_blocked)
    if "provider.write_policy" not in declared_contracts:
        # The fence is still RESOLVED (the receipt names which policy this
        # grant was issued beside), but no decision is appended: a row that
        # does not declare the contract must not carry a decision for it, and
        # `begin_effect` refuses an undeclared decision by name.
        blocked = ()
    elif not policy_source.usable:
        # NEVER ALLOW BY ABSENCE. An issuer that cannot find the fence has not
        # cleared the paths; it failed to ask. Refusing is the only reading
        # that does not record an unrun guard as a passed one.
        blocked = caller_blocked
        guards.append(
            GuardDecision(
                "provider.write_policy",
                False,
                f"{policy_source.error}; a write lease is refused rather than "
                "issued under sensitivity.DEFAULT_POLICY, whose empty "
                "write_allow means UNCONFINED",
            )
        )
    else:
        from daedalus.sensitivity import path_write_blocked

        blocked = tuple(
            sorted(
                set(caller_blocked)
                | {
                    p
                    for p in declared_paths
                    if path_write_blocked(p, policy_source.policy)
                }
            )
        )
        stamp = (
            f"{policy_source.origin} (sha256={policy_source.sha256[:16]})"
            if policy_source.sha256
            else policy_source.origin
        )
        guards.append(
            GuardDecision(
                "provider.write_policy",
                not blocked,
                (
                    f"sensitivity.path_write_blocked, under {stamp}, refuses "
                    f"{len(blocked)} declared path(s): "
                    f"{', '.join(sorted(blocked)[:5])}"
                )
                if blocked
                else (
                    f"sensitivity.path_write_blocked, under {stamp}, cleared "
                    f"all {len(declared_paths)} declared path(s); the leased "
                    "roots are a DECLARATION, enforced by offload's own write "
                    "guard and the isolated attempt worktree, not by this receipt"
                ),
            )
        )

    # THE CALLER'S FLAG IS NOT THE CONTRACT. It is one of three conjuncts,
    # and the only one the requester controls; see `derive_wave_containment`
    # for the measured grant this replaces.
    declared_mechanism = str(containment_evidence or "").strip()
    derived_ok = False
    derived_evidence = (
        f"{spec.id} declares no containment contract, so this issuer derived none"
    )
    if "containment.attempt" in declared_contracts:
        derived_ok, derived_evidence = derive_wave_containment(root)
        containment_refusals: list[str] = []
        if not contained:
            containment_refusals.append("the caller could not establish containment")
        if not declared_mechanism:
            containment_refusals.append(
                "the caller named no containment mechanism; an unevidenced "
                "assertion is not a containment boundary, so no capability is issued"
            )
        if not derived_ok:
            containment_refusals.append(derived_evidence)
        guards.append(
            GuardDecision(
                "containment.attempt",
                not containment_refusals,
                "; ".join(containment_refusals)
                if containment_refusals
                else f"{derived_evidence}; caller mechanism: {declared_mechanism}",
            )
        )

    if "containment.worktree" in declared_contracts:
        # The same derivation the wave's containment rests on, under the name
        # the python.attempt row declares: the manager's PLANNED root lands
        # outside the primary checkout in both directions
        # (primary_tree.planned_overlap_reason since 0f7f8187).
        worktree_ok, worktree_evidence = derive_wave_containment(root)
        guards.append(
            GuardDecision("containment.worktree", worktree_ok, worktree_evidence)
        )

    if "spine.intent_ledger" in declared_contracts:
        guards.append(_intent_ledger_decision(root, effect_key))

    # -- 3. the request, and the policy digest over what decided ------------ #
    # WHAT THE ROW DID NOT DECLARE IS NOT GRANTED. `_scope_requirements`
    # refuses a scope that is too NARROW for the declared effects; nothing in
    # the kernel refuses one that is too wide, so the narrowing happens here.
    cost_microusd = 0 if max_spend_usd is None else int(round(float(max_spend_usd) * 1e6))
    if cost_microusd < 0:
        cost_microusd = 0
    if Effect.SPEND.value not in declared_effects:
        cost_microusd = 0
    timeout = int(max(1, round(float(timeout_s)))) if timeout_s else 3600
    spawns = bool(
        declared_effects
        & {Effect.PROCESS_SPAWN.value, Effect.PROCESS_CONTROL.value}
    )
    declared_tools = (
        tuple(
            sorted({str(t) for t in (*BASE_TOOLS, *tools, *lanes) if str(t).strip()})
        )
        if spawns
        else ()
    )
    writes = bool(
        declared_effects
        & {Effect.FILESYSTEM_WRITE.value, Effect.REPOSITORY_MUTATION.value}
    )
    if not writes:
        declared_paths = ()

    # The digest of the exact material this verdict was computed from. Not a
    # document hash of a policy file -- there is no such file for this decision
    # -- so it names what it really is: the inputs, so a receipt reader can
    # recompute it and see whether the decision drifted.
    policy_sha256 = canonical_sha(
        {
            "policy_version": POLICY_VERSION,
            "entrypoint_id": spec.id,
            "registry_sha256": registry_sha256(),
            "effects": list(effects),
            "guard_decisions": [
                {"contract": d.contract, "allowed": d.allowed, "evidence": d.evidence}
                for d in sorted(guards, key=lambda d: d.contract)
            ],
            "kill_switch_generation": generation,
            # The write fence's IDENTITY travels inside the digest, so a
            # decision recomputed under a different policy file does not
            # reproduce this sha: the drift is visible rather than silent.
            "write_policy": policy_source.to_dict(),
            "max_cost_microusd": cost_microusd,
            "timeout_s": timeout,
            "writable_paths": list(declared_paths),
            "egress_endpoints": sorted(set(endpoints)),
            "tools": list(declared_tools),
            "max_concurrency": max(1, int(positions)),
        }
    )

    refusals = tuple(
        f"{d.contract}: {d.evidence}" for d in guards if not d.allowed
    )
    if refusals:
        return _deny(
            origin=_issuer_origin(spec.id),
            policy_version=_issuer_policy_version(spec.id),
            reasons=refusals,
            guard_decisions=guards,
            source_revision=source_revision,
            trace_id=trace_id,
            subject_id=request_id,
            # No EffectLeaseRequest exists on this path (its scope would have to
            # claim grants the policy just refused), so the subject digest is
            # over the decision material itself.
            subject_sha256=policy_sha256,
            policy_sha256=policy_sha256,
            now=instant,
            write_policy=policy_source,
            entrypoint_id=spec.id,
        )

    scope = EffectScope(
        read_only=not writes,
        writable_paths=declared_paths,
        egress_endpoints=tuple(sorted(set(endpoints))),
        tools=declared_tools,
        max_cost_microusd=cost_microusd,
        max_concurrency=max(1, int(positions)),
        timeout_s=timeout,
        kill_switch_ref=KILL_SWITCH_REF,
    )
    provenance = ContractProvenance(
        origin=_issuer_origin(spec.id),
        source_revision=source_revision,
        created_at=_timestamp(instant),
        trace_id=trace_id,
    )
    request = EffectLeaseRequest(
        request_id=request_id,
        mission_id=mission_id,
        attempt_id=attempt_id,
        entrypoint_id=spec.id,
        requested_effects=effects,
        effect_scope=scope,
        idempotency_namespace=f"{mission_id}-{attempt_id}",
        kill_switch_generation=generation,
        runtime_manifest_sha256=None,
        runtime_conformance_sha256=None,
        provenance=provenance,
    )
    policy = PolicyDecision(
        decision_id=f"{request_id}-allow",
        subject_id=request.request_id,
        subject_sha256=request.digest,
        policy_version=_issuer_policy_version(spec.id),
        policy_sha256=policy_sha256,
        verdict="allow",
        reasons=tuple(
            sorted({f"{d.contract}: {d.evidence}" for d in guards})
        ),
        effect_scope=scope,
        provenance=ContractProvenance(
            origin=_issuer_origin(spec.id) + "-policy",
            source_revision=source_revision,
            created_at=_timestamp(instant),
            input_digests=(request.digest, policy_sha256),
            trace_id=trace_id,
        ),
    )

    # Guard: profile root must not be relocated in-process before accessing
    # the lease ledger and issuer key outside the repository.
    profile_disagreement = profile_root_disagreement()
    if profile_disagreement:
        return _deny(
            origin=_issuer_origin(spec.id),
            policy_version=_issuer_policy_version(spec.id),
            reasons=(f"profile.root_relocated: {profile_disagreement}",),
            guard_decisions=guards,
            source_revision=source_revision,
            trace_id=trace_id,
            subject_id=request_id,
            subject_sha256=policy_sha256,
            policy_sha256=policy_sha256,
            now=instant,
            write_policy=policy_source,
            entrypoint_id=spec.id,
        )

    keyring = issuer_keyring(root)
    ttl = min(max(_MIN_TTL_S, timeout), _MAX_TTL_S)
    lease = issue_effect_lease(
        request,
        policy,
        lease_id=lease_id or f"{request_id}-{uuid.uuid4().hex[:8]}",
        issuer_key_id=ISSUER_KEY_ID,
        issued_at=instant,
        expires_at=instant + timedelta(seconds=ttl),
        secret=keyring[ISSUER_KEY_ID],
    )
    ledger_path = lease_ledger_path(root)
    ledger = EffectLeaseLedger(ledger_path)
    authorization = NonRuntimeEffectAuthorization(
        lease=lease,
        request=request,
        policy_decision=policy,
        effect_ledger=ledger,
        lease_keyring=keyring,
        guard_decisions=tuple(guards),
        # LIVE, not captured: the facade re-reads this at every boundary, so an
        # operator's stop during a running wave invalidates the lease at the
        # next start/finish instead of being noticed only after the spend.
        kill_switch_generation_reader=lambda: kill_switch_generation(live_switch),
    )
    # PERSIST BEFORE ANY EXECUTION MAY START. `EffectLeaseLedger.begin` refuses
    # a lease it has never seen ("effect lease was not persisted before start"),
    # so this is the line that makes the capability real.
    authorization.grant()
    store = (
        Path(evidence_root)
        if evidence_root is not None
        else write_evidence_root(root, source_revision)
    )
    control = Path(control_root(root))
    granted = WaveOffloadLease(
        authorization=authorization,
        lease=lease,
        request=request,
        policy_decision=policy,
        ledger=ledger,
        ledger_path=str(ledger_path),
        write_policy=policy_source,
        evidence_root=str(store),
        control_root_path=str(control),
    )
    # AFTER the grant, because this is the first moment the capability is real:
    # `grant()` has returned, so the ledger holds the lease and an execution may
    # start. Retention never decides the grant -- a store that cannot be written
    # (read-only control root, a racing wave) must not revoke a capability the
    # ledger already accepted -- so every failure is recorded on the lease and
    # the wave proceeds under the lease it legitimately holds.
    try:
        subject = record_effect_lease_subject(
            granted,
            evidence_root=store,
            control_root_path=control,
            positions=max(1, int(positions)),
        )
        granted.evidence_records["lease_subject"] = str(subject["record_sha256"])
    except (OSError, TypeError, ValueError) as exc:
        granted.evidence_errors.append(f"lease_subject: {type(exc).__name__}: {exc}")
    # The containment decision this lease was issued under, RECORDED -- the
    # verdict and evidence above, re-typed under the contract they are about,
    # never re-derived. `record_primary_checkout_disjointness` runs no
    # predicate; it cannot reach a different answer than this call site did.
    #
    # ONLY WHEN THIS ROW REALLY TOOK ONE. A row that declares no containment
    # contract took no containment decision, so it retains no disjointness
    # record: minting one would put THIS issuer's measurement of the attempt
    # isolation root behind a door that never asked about it, and the write
    # classification chain would then read a disjoint target off a pair of
    # roots that row's writes never touch.
    if not (declared_contracts & CONTAINMENT_CONTRACTS):
        granted.evidence_errors.append(
            f"disjointness: {spec.id} declares no containment contract, so this "
            "grant retains no primary-checkout disjointness record"
        )
        return granted
    try:
        primary_root, target_root = wave_containment_roots(root)
        record = record_primary_checkout_disjointness(
            GuardDecision(
                WORKTREE_CONTAINMENT_CONTRACT, derived_ok, derived_evidence
            ),
            primary_checkout=primary_root,
            target_root=target_root,
            source_revision=source_revision,
            evidence_root=store,
            control_root_path=control,
        )
        granted.evidence_records["disjointness"] = str(record["record_sha256"])
    except (OSError, TypeError, ValueError) as exc:
        granted.evidence_errors.append(f"disjointness: {type(exc).__name__}: {exc}")
    return granted


def acquire_wave_offload_lease(
    repo_root: str | Path, **kwargs: Any
) -> "WaveOffloadLease | WaveLeaseDenied":
    """One wave's ``python.offload`` lease. The row is PINNED here, not passed.

    The wave starter names no entrypoint, so no caller of this function can
    choose which capability it is asking for -- exactly as before the issuer
    became a rule. ``entrypoint_id`` is rejected rather than defaulted: a
    keyword this wrapper silently ignored would read at the call site as a
    request that had been honoured.
    """

    if "entrypoint_id" in kwargs:
        raise TypeError(
            "acquire_wave_offload_lease() issues for python.offload only; call "
            "acquire_effect_lease(entrypoint_id=...) to ask for another row"
        )
    return acquire_effect_lease(repo_root, entrypoint_id=ENTRYPOINT_ID, **kwargs)


ATTEMPT_ENTRYPOINT_ID = "python.attempt"


def acquire_attempt_lease(
    repo_root: str | Path, **kwargs: Any
) -> "WaveOffloadLease | WaveLeaseDenied":
    """One attempt's ``python.attempt`` lease. The row is PINNED here, not passed.

    The second narrow entry beside :func:`acquire_wave_offload_lease`, same
    shape for the same reason: no caller of this function chooses which
    capability it is asking for. The row's own contracts decide what runs --
    for ``python.attempt`` that is the intent-ledger check (which is why
    ``effect_key``, the attempt's branch name, is required here rather than
    optional), the worktree containment derivation, the write fence over the
    declared target paths, and the process spend net. ``positions`` is pinned
    to 1: an attempt is one execution identity, and a retry is a NEW attempt
    with a NEW effect_key, never a replay of this one.
    """
    if "entrypoint_id" in kwargs:
        raise TypeError(
            "acquire_attempt_lease() issues for python.attempt only; call "
            "acquire_effect_lease(entrypoint_id=...) to ask for another row"
        )
    if not kwargs.get("effect_key"):
        raise TypeError(
            "acquire_attempt_lease() requires effect_key: the attempt's branch "
            "name is the subject the spine.intent_ledger contract is run over"
        )
    kwargs["positions"] = 1
    return acquire_effect_lease(
        repo_root, entrypoint_id=ATTEMPT_ENTRYPOINT_ID, **kwargs
    )


__all__ = [
    "CALLER_POLICY_ORIGIN",
    "CONTAINMENT_CONTRACTS",
    "DISJOINTNESS_RECEIPT_SCHEMA",
    "DISJOINTNESS_RECORD_SCHEMA",
    "EFFECT_LEASE_RECEIPT_SCHEMA",
    "ENTRYPOINT_ID",
    "ISSUER_CONTRACTS",
    "ISSUER_EFFECTS",
    "ISSUER_KEY_ID",
    "KILL_SWITCH_REF",
    "LEASE_EXECUTION_RECORD_SCHEMA",
    "LEASE_SUBJECT_RECORD_SCHEMA",
    "LEASE_TERMINAL_RECORD_SCHEMA",
    "POLICY_VERSION",
    "ROOT_IDENTITY_SCHEMA",
    "WORKTREE_CONTAINMENT_CONTRACT",
    "WaveLeaseDenied",
    "WaveLeaseKillSwitchEngaged",
    "WaveOffloadLease",
    "WritePolicySource",
    "acquire_effect_lease",
    "acquire_wave_offload_lease",
    "control_root",
    "derive_wave_containment",
    "emit_effect_lease_terminal_record",
    "guard_decision_sha256",
    "harvest_effect_lease_terminal_records",
    "issuable_row",
    "issuer_keyring",
    "kill_switch_generation",
    "lane_endpoint",
    "lease_ledger_path",
    "rebuild_effect_lease_authorization",
    "record_effect_lease_execution",
    "record_effect_lease_subject",
    "record_effect_lease_subject_parts",
    "record_primary_checkout_disjointness",
    "resolve_write_policy",
    "wave_containment_roots",
    "write_evidence_root",
    "write_root_identity_sha256",
]
