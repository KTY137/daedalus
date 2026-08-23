"""Byte-identity probe for the wave path across the authority/subject split.

Everything volatile is pinned: the permit bytes (hence the kill-switch
generation), the issuer key, the lease id and the issuing instant.  The lease
ledger is removed before each run so the same lease id grants cleanly, and the
control root, key and permit are kept so the signature is over the same secret.

Usage: python identity_probe.py <label>
Prints one JSON object of digests.  Two runs that agree are one unchanged wave.
"""
from __future__ import annotations

import dataclasses
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from daedalus.kernel import offload_lease as ol  # noqa: E402
from daedalus.spine.envelope import canonical_sha  # noqa: E402
from daedalus.spine.killswitch import KillSwitch  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

LABEL = sys.argv[1]
INSTANT = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)
LEASE_ID = "identity-probe-fixed-lease-id"
REVISION = "d" * 40
MECHANISM = "identity probe: gated_writes.run_write_wave TaskAttempt worktrees"

control = ol.control_root(str(ROOT))
for stale in control.glob("effect-leases.sqlite3*"):
    stale.unlink()

switch = KillSwitch(repo_root=str(ROOT))
if not (control / "killswitch").exists():
    switch.arm(note="identity probe")

granted = ol.acquire_wave_offload_lease(
    str(ROOT),
    source_revision=REVISION,
    mission_id="identity-probe",
    attempt_id="ip-1",
    positions=1,
    lanes=("ollama",),
    tools=("pytest",),
    max_spend_usd=0.25,
    timeout_s=900,
    writable_paths=("docs/x.md",),
    contained=True,
    containment_evidence=MECHANISM,
    switch=switch,
    lease_id=LEASE_ID,
    evidence_root=control / "probe-evidence",
)
assert granted.granted, getattr(granted, "reasons", None)

receipt = dict(granted.receipt())
# The four clock-bearing keys, dropped for the same reason as above: they move
# between any two runs and say nothing about this change. Everything else the
# receipt publishes -- entrypoint, effects, scope, endpoints, tools, ceilings,
# generation, write policy, ledger path -- must be identical.
for volatile in ("issued_at", "expires_at", "lease_sha256",
                 "policy_decision_sha256"):
    receipt.pop(volatile, None)
print(json.dumps({
    "label": LABEL,
    # TIMESTAMP-FREE BY CONSTRUCTION. `lease.digest` and `request.digest`
    # both cover an issuing instant, and the facade owns that instant (a
    # pinned past one expires at grant, a pinned future one is not yet
    # valid), so they cannot be compared across two runs and say anything
    # about this change. `policy_sha256` is the digest over the exact
    # material the verdict was computed from -- contracts, guard decisions,
    # scope, effects, generation, write fence -- and carries no clock. It is
    # the decision, which is what must be identical.
    "policy_sha256": granted.policy_decision.policy_sha256,
    "lease_id": granted.lease.lease_id,
    "receipt_sha256": canonical_sha(receipt),
    "guard_decisions": canonical_sha([
        {"contract": d.contract, "allowed": d.allowed, "evidence": d.evidence}
        for d in sorted(granted.authorization.guard_decisions,
                        key=lambda d: d.contract)
    ]),
    "effect_scope": canonical_sha(dataclasses.asdict(granted.lease.effect_scope)),
}, indent=2, sort_keys=True))
