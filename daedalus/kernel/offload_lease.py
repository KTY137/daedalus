"""One persisted ``python.offload`` Effect Lease per wave -- the issuer side.

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

import hashlib
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from daedalus.kernel.authorization import NonRuntimeEffectAuthorization
from daedalus.kernel.contracts import EffectLease, EffectLeaseRequest
from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectLeaseLedger,
    issue_effect_lease,
)
from daedalus.schemas import ContractProvenance, EffectScope, PolicyDecision
from daedalus.spine.effect_boundary import (
    REGISTRY_BY_ID,
    GuardDecision,
    registry_sha256,
)
from daedalus.spine.envelope import canonical_sha
from daedalus.spine.killswitch import KillSwitch, LoopHalted

if TYPE_CHECKING:  # pragma: no cover - typing only, never an import cycle
    from daedalus.sensitivity import Policy

#: The registry row this module issues for. Never parameterised: a helper that
#: can issue for "whichever entrypoint you name" is a general-purpose capability
#: minter, which is precisely what the boundary exists to prevent.
ENTRYPOINT_ID = "python.offload"

#: Identifier of the local issuer key. One id, so a lease signed by a previous
#: key file fails verification loudly instead of being silently re-signed.
ISSUER_KEY_ID = "daedalus.local.effect-issuer"

#: Names the switch a lease is bound to, recorded on both scope and execution.
KILL_SWITCH_REF = "daedalus.spine.killswitch"

POLICY_VERSION = "daedalus.wave-offload-lease/1"

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
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
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
    :func:`daedalus.primary_tree.overlap_reason` is the one implementation of
    that comparison and it is bidirectional, so a root that CONTAINS the
    checkout fails too.

    This is a precondition, not the whole contract: it says candidate checkouts
    can land outside the primary tree, not that this particular wave routed
    through them. The caller still has to name the mechanism it used, and
    :func:`acquire_wave_offload_lease` now refuses an empty name.
    """
    from daedalus.kairos.worktree import GitWorktreeManager
    from daedalus.primary_tree import nearest_existing, overlap_reason

    root = Path(repo_root).resolve()
    try:
        worktree_root = GitWorktreeManager(root).worktree_root
        ground = nearest_existing(Path(worktree_root))
    except Exception as exc:  # noqa: BLE001 - unknown containment is no containment
        return False, (
            f"the isolation root for {root} could not be resolved "
            f"({type(exc).__name__}: {exc}), so containment cannot be derived"
        )
    overlap = overlap_reason(ground, root)
    if overlap is not None:
        return False, (
            f"the attempt isolation root {worktree_root} overlaps the primary "
            f"checkout: {overlap}"
        )
    return True, (
        f"primary_tree.overlap_reason({ground}, {root}) is None: TaskAttempt "
        f"worktrees allocated under {worktree_root} land outside the primary "
        f"checkout in both directions"
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

    @property
    def granted(self) -> bool:
        return False

    def receipt(self) -> dict[str, Any]:
        return {
            "verdict": "deny",
            "entrypoint_id": ENTRYPOINT_ID,
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
def _deny(
    *,
    reasons: Sequence[str],
    guard_decisions: Sequence[GuardDecision],
    source_revision: str,
    trace_id: str | None,
    subject_id: str,
    subject_sha256: str,
    policy_sha256: str,
    now: datetime,
    write_policy: WritePolicySource | None = None,
) -> WaveLeaseDenied:
    decision = PolicyDecision(
        decision_id=f"{subject_id}-deny",
        subject_id=subject_id,
        subject_sha256=subject_sha256,
        policy_version=POLICY_VERSION,
        policy_sha256=policy_sha256,
        verdict="deny",
        reasons=tuple(reasons),
        # A deny decision may not carry grants -- the contract enforces it.
        effect_scope=EffectScope(),
        provenance=ContractProvenance(
            origin="kernel.wave-offload-lease",
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
    )


def acquire_wave_offload_lease(
    repo_root: str | Path,
    *,
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
) -> WaveOffloadLease | WaveLeaseDenied:
    """Run the four ``python.offload`` guard contracts, then issue or deny.

    Returns a :class:`WaveOffloadLease` when every contract allows, and a
    :class:`WaveLeaseDenied` -- never an exception, never a partial grant --
    when one refuses. The one exception it DOES raise is
    :class:`WaveLeaseKillSwitchEngaged`, because a revoked permit is not a
    verdict about this wave: it is an instruction to stop the run.

    The caller supplies what only it can know (which lanes this wave routes to,
    which paths the tasks declared, whether the attempts are contained). This
    module owns everything a caller must not be trusted with: the issuer key,
    the generation, the ledger location, and the refusal to issue for any row
    other than ``python.offload``.

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
    spec = REGISTRY_BY_ID[ENTRYPOINT_ID]
    effects = tuple(sorted(effect.value for effect in spec.effects))

    # -- 1. the kill switch, before anything is computed for this wave ------ #
    # Raises. See WaveLeaseKillSwitchEngaged for why this one is not a verdict.
    generation = kill_switch_generation(live_switch)

    # -- 2. the four declared guard contracts ------------------------------- #
    from daedalus.budget import process_guard_boundary_decision

    guards: list[GuardDecision] = [process_guard_boundary_decision()]

    endpoints: list[str] = []
    egress_reasons: list[str] = []
    egress_ok = True
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

    # The exact roots this lease would grant, computed BEFORE the write
    # contract so the contract judges the same strings the scope will carry.
    # ``(".",)`` is the whole checkout: under a confining policy that reads as
    # a refusal, which is the right answer for "this wave declared no bound".
    declared_paths = tuple(
        sorted({str(p).strip() for p in writable_paths if str(p).strip()})
    ) or (".",)

    policy_source = resolve_write_policy(root, write_policy)
    caller_blocked = tuple(str(p) for p in write_policy_blocked)
    if not policy_source.usable:
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

    # -- 3. the request, and the policy digest over what decided ------------ #
    request_id = f"{mission_id}-wave-offload-{attempt_id}"
    cost_microusd = 0 if max_spend_usd is None else int(round(float(max_spend_usd) * 1e6))
    if cost_microusd < 0:
        cost_microusd = 0
    timeout = int(max(1, round(float(timeout_s)))) if timeout_s else 3600
    declared_tools = tuple(
        sorted(
            {str(t) for t in (*BASE_TOOLS, *tools, *lanes) if str(t).strip()}
        )
    )

    # The digest of the exact material this verdict was computed from. Not a
    # document hash of a policy file -- there is no such file for this decision
    # -- so it names what it really is: the inputs, so a receipt reader can
    # recompute it and see whether the decision drifted.
    policy_sha256 = canonical_sha(
        {
            "policy_version": POLICY_VERSION,
            "entrypoint_id": ENTRYPOINT_ID,
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
        )

    scope = EffectScope(
        read_only=False,
        writable_paths=declared_paths,
        egress_endpoints=tuple(sorted(set(endpoints))),
        tools=declared_tools,
        max_cost_microusd=cost_microusd,
        max_concurrency=max(1, int(positions)),
        timeout_s=timeout,
        kill_switch_ref=KILL_SWITCH_REF,
    )
    provenance = ContractProvenance(
        origin="kernel.wave-offload-lease",
        source_revision=source_revision,
        created_at=_timestamp(instant),
        trace_id=trace_id,
    )
    request = EffectLeaseRequest(
        request_id=request_id,
        mission_id=mission_id,
        attempt_id=attempt_id,
        entrypoint_id=ENTRYPOINT_ID,
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
        policy_version=POLICY_VERSION,
        policy_sha256=policy_sha256,
        verdict="allow",
        reasons=tuple(
            sorted({f"{d.contract}: {d.evidence}" for d in guards})
        ),
        effect_scope=scope,
        provenance=ContractProvenance(
            origin="kernel.wave-offload-lease-policy",
            source_revision=source_revision,
            created_at=_timestamp(instant),
            input_digests=(request.digest, policy_sha256),
            trace_id=trace_id,
        ),
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
    return WaveOffloadLease(
        authorization=authorization,
        lease=lease,
        request=request,
        policy_decision=policy,
        ledger=ledger,
        ledger_path=str(ledger_path),
        write_policy=policy_source,
    )


__all__ = [
    "CALLER_POLICY_ORIGIN",
    "ENTRYPOINT_ID",
    "ISSUER_KEY_ID",
    "KILL_SWITCH_REF",
    "POLICY_VERSION",
    "WaveLeaseDenied",
    "WaveLeaseKillSwitchEngaged",
    "WaveOffloadLease",
    "WritePolicySource",
    "acquire_wave_offload_lease",
    "control_root",
    "derive_wave_containment",
    "issuer_keyring",
    "kill_switch_generation",
    "lane_endpoint",
    "lease_ledger_path",
    "resolve_write_policy",
]
