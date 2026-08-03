# G0-ATT-13B3 — Bounded Attempt record/Event-Store time window

## Scope

This correction packet is stacked directly on the current
`G0-ATT-13B — Persisted Isolated Attempt Lifecycle` head. It changes only the
strict read projection for lifecycle timestamps and its adversarial evidence.
It does not invoke a runtime, execute provider code, issue or consume an Effect
Lease, create a workspace, publish an EvidencePacket, merge, promote, or change
the active gate.

## Residual finding

The parent packet correctly removed caller authority over lifecycle time and
rejected records whose trusted timestamp followed the Event-Store transition.
However, the strict projection enforced only one side of the relationship:

`record_time <= event_store_time`

A hostile persisted row could therefore be repacked with an arbitrarily old
start or terminal timestamp, matching provenance, payload digest, event detail,
and terminal effect digest. The Event-Store timestamps could remain unchanged
and the record would still hydrate. Because this lifecycle explicitly treats
direct SQLite substitution as hostile input, ordering alone is insufficient.

## Correction

The strict read projection now requires each canonical lifecycle record time to
be both:

1. not later than the Event-Store transition that retained it; and
2. no more than 60 seconds earlier than that transition.

Malformed record or Event-Store timestamps are normalized to
`AttemptStateError`. The intent-row start timestamp must still equal the
`INTENDED` event timestamp exactly. The existing lifecycle clock remains the
writer-side authority; this packet adds no second clock or writer.

The bounded interval is deliberately conservative. It is not a distributed
clock claim. A local transition delayed by more than the bound fails closed and
must be investigated rather than silently converting detached evidence into a
trusted lifecycle receipt.

## Adversarial specification

Tests canonically repackage both start and terminal records into the future and
far past, including matching provenance and recomputed payload/effect digests.
All variants must fail before a lifecycle object is returned.

The bounded mutation runner attacks:

- removal of the historical-time bound;
- removal of the future-time refusal; and
- omission of terminal time binding.

Every mutant must be killed after a green focused baseline and the production
reader must be restored byte-for-byte.

## Remaining boundary

The isolated Attempt lifecycle remains an inventory-only/local-guard boundary
until a later packet mechanically composes the canonical effect registry,
persisted Effect Lease, current Runtime Conformance Receipt and OS sandbox.
This correction does not claim central effect coverage.

GitHub Actions issue #67 may prevent hosted jobs from reaching Step 1. A
zero-step run is infrastructure evidence only and is neither green nor a
product failure.

Iron Plan: **ALIGNED BY SCOPE; EXACT-HEAD EXECUTION REQUIRED**  
Iron Gate: **0**  
Promotion: **not requested**
