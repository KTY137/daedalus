# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Production issuance of a ``RuntimeBoundEffectAuthorization``.

WHY THIS MODULE EXISTS.  Measured 2026-08-26 at 4f71c020, unchanged since
2026-08-18: zero production files construct a ``RuntimeBoundEffectAuthorization``
-- all six construction sites live under ``tests/``.  Every remaining Gate-0
blocker funnels through that absence: no production minter means no live
runtime start, no ``live-runtime`` conformance envelope (the two
``live-envelope-unavailable`` fault rows), no persisted runtime-conformance
receipt bundle, and no path for ``provider.claude`` to leave INVENTORY_ONLY.
The chain it feeds is complete and waiting: ``runtime_effects.py`` defines the
capability, ``runtimes/broker.py`` consumes it, ``providers/claude_cli.py``
already calls the seam, and ``claude_bridge.ask_claude`` already accepts the
parameter.  What was missing is the composition root -- one place that turns
real, checkout-external ingredients into the object -- and that is all this
module is.

WHAT IT DELIBERATELY IS NOT.  It mints a capability; it performs no effect,
spawns nothing, contacts no provider, and cannot widen the registry: the
underlying ``issue_effect_lease`` refuses any row that is not CENTRAL
("<id> is inventory_only, not central; migration is required first"), so this
issuer against the real registry FAILS CLOSED for every provider row today.
That refusal is pinned by test rather than worked around -- flipping
``provider.claude`` to CENTRAL remains the explicitly separate second half of
the condition recorded at ``effect_boundary.py`` ("caller injection AND
exact-head verification"), and ``test_claude_bypass_inventory`` still guards
the flip itself.

KEY CUSTODY follows the one pattern this repository has measured and adopted
(``offload_lease.issuer_keyring``, cases A9a/A10): keys are FILES in the
checkout-external control root, never environment variables -- an env-carried
secret is inherited by every child this process spawns, which includes the
candidate's own worker.  Three keys, three files, because they answer three
different questions: the lease-issuer key signs "this capability was granted",
the runtime-authority key signs "this capability is bound to that exact
verified runtime", and the trust-ledger integrity key authenticates the
persisted admission rows those two rest on.  One shared key would collapse
those authorities into each other, which is exactly the HMAC-symmetry failure
the promotion trust-root finding documented.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from daedalus.kernel.contracts import EffectLeaseRequest
from daedalus.kernel.effects import EffectLeaseLedger
from daedalus.kernel.offload_lease import kill_switch_generation, lease_ledger_path
from daedalus.kernel.runtime_effects import (
    RuntimeBoundEffectAuthorization,
    issue_runtime_bound_effect_lease,
)
from daedalus.runtimes.trust_store import RuntimeTrustLedger
from daedalus.schemas import PolicyDecision
from daedalus.spine.effect_boundary import (
    REGISTRY_BY_ID,
    EntrypointSpec,
    GuardDecision,
)
from daedalus.spine.killswitch import KillSwitch, control_root

#: Key identities carried on the signed objects.  Distinct from
#: ``offload_lease.ISSUER_KEY_ID`` on purpose: a runtime-bound lease and a
#: non-runtime wave lease are different authorities, and a shared key id would
#: let a verifier accept one where the other was meant.
RUNTIME_LEASE_KEY_ID = "daedalus.local.runtime-lease-issuer"
RUNTIME_AUTHORITY_KEY_ID = "daedalus.local.runtime-authority"

_KEY_BYTES = 32
_MIN_TTL_S = 30
_MAX_TTL_S = 3600


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _load_or_create_key(path: Path) -> bytes:
    """One key file, created once, read forever.

    Same shape as ``offload_lease.issuer_keyring`` for the same measured
    reasons: O_EXCL so two concurrent processes cannot both believe they
    created it (the loser re-reads the winner's bytes), and O_BINARY because a
    Windows text-mode write translates 0x0A to 0x0D 0x0A -- roughly one random
    32-byte key in eight contains a 0x0A, and every signature made with the
    in-memory bytes then fails verification against the file (measured 1-in-7
    over 8 fresh roots before that flag existed there; 0-in-40 after).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        material = path.read_bytes()
    except FileNotFoundError:
        material = b""
    if len(material) < _KEY_BYTES:
        fresh = os.urandom(_KEY_BYTES)
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
        raise ValueError(f"the key at {path} is too short to sign with")
    return material


def runtime_trust_ledger_path(repo_root: str | Path | None) -> Path:
    """The one runtime-trust ledger for this checkout, beside the other ledgers.

    Checkout-external for the reason every ledger here is: the candidate a
    runtime lease authorises may hold a writable checkout, and the admission
    rows its trust rests on must not be reachable by the thing being trusted.
    """
    return control_root(repo_root) / "runtime-trust" / "trust.sqlite3"


def runtime_trust_ledger(repo_root: str | Path | None) -> RuntimeTrustLedger:
    """Open (or create) the production runtime-trust ledger.

    EXPOSED SEPARATELY because it has two callers with different jobs: the
    conformance-admission step (a live provider run binding its envelope) must
    write into the SAME ledger this issuer later reads, or the trust chain
    splits into two stores that each look complete.
    """
    root = control_root(repo_root)
    integrity = _load_or_create_key(root / "runtime-trust-integrity.key")
    return RuntimeTrustLedger(
        runtime_trust_ledger_path(repo_root), integrity_key=integrity
    )


def acquire_runtime_bound_authorization(
    repo_root: str | Path | None,
    *,
    request: EffectLeaseRequest,
    policy_decision: PolicyDecision,
    guard_decisions: Iterable[GuardDecision],
    runtime_envelope_sha256: str,
    switch: KillSwitch,
    lease_id: str | None = None,
    ttl_s: int = 900,
    registry: Mapping[str, EntrypointSpec] | Sequence[EntrypointSpec] = REGISTRY_BY_ID,
) -> RuntimeBoundEffectAuthorization:
    """Mint the runtime-bound capability for one exact request, or refuse.

    Fail-closed by composition, not by re-checking: every refusal below is
    raised by the layer that owns the rule --

    * a non-CENTRAL registry row is refused inside ``issue_effect_lease``
      ("is inventory_only, not central; migration is required first"), so this
      facade cannot be used to route around the registry;
    * a request without manifest/conformance digests, an envelope the trust
      ledger has not admitted (or has quarantined, or that expired), and a
      lease outliving its trust record are refused inside
      ``issue_runtime_bound_effect_lease``;
    * empty guard decisions are refused by the authorization itself;
    * an engaged or unreadable kill switch refuses in
      ``kill_switch_generation`` before any signature is made.

    The clock is owned here (``issued_at = now``) and by the facade afterwards:
    ``RuntimeBoundEffectAuthorization`` re-verifies at ITS OWN clock on every
    grant/start/finish, so a caller cannot backdate trust after expiry.
    """

    root = control_root(repo_root)
    lease_key = _load_or_create_key(root / "runtime-lease-issuer.key")
    authority_key = _load_or_create_key(root / "runtime-authority.key")
    trust = runtime_trust_ledger(repo_root)
    generation = kill_switch_generation(switch)
    if int(request.kill_switch_generation) != int(generation):
        # The request carries the generation its lease will be verified
        # against for its whole life.  Signing one built against a stale
        # permit would mint a capability that fails its very first
        # ``grant()`` -- honest, but a refusal AFTER two signatures and a
        # ledger open, with a message about verification rather than about
        # the actual mistake.  Refused here, named for what it is.
        raise ValueError(
            "request kill_switch_generation "
            f"{request.kill_switch_generation} is not the live permit "
            f"generation {generation}; rebuild the request against the "
            "armed switch"
        )

    ttl = min(max(_MIN_TTL_S, int(ttl_s)), _MAX_TTL_S)
    issued = _utc_now()
    capability = issue_runtime_bound_effect_lease(
        request,
        policy_decision,
        lease_id=lease_id or f"{request.request_id}-rt",
        lease_issuer_key_id=RUNTIME_LEASE_KEY_ID,
        lease_issuer_secret=lease_key,
        runtime_envelope_sha256=runtime_envelope_sha256,
        runtime_trust_ledger=trust,
        runtime_authority_key_id=RUNTIME_AUTHORITY_KEY_ID,
        runtime_authority_secret=authority_key,
        issued_at=issued,
        expires_at=issued + timedelta(seconds=ttl),
        registry=registry,
    )
    return RuntimeBoundEffectAuthorization(
        capability=capability,
        request=request,
        policy_decision=policy_decision,
        effect_ledger=EffectLeaseLedger(lease_ledger_path(repo_root)),
        runtime_trust_ledger=trust,
        lease_keyring={RUNTIME_LEASE_KEY_ID: lease_key},
        runtime_authority_keyring={RUNTIME_AUTHORITY_KEY_ID: authority_key},
        guard_decisions=tuple(guard_decisions),
        current_kill_switch_generation=generation,
        registry=registry,
    )


__all__ = [
    "RUNTIME_AUTHORITY_KEY_ID",
    "RUNTIME_LEASE_KEY_ID",
    "acquire_runtime_bound_authorization",
    "runtime_trust_ledger",
    "runtime_trust_ledger_path",
]
