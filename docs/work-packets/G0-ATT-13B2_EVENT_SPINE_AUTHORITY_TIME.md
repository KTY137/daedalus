# G0-ATT-13B2 — Event-spine-bound Attempt lifecycle time

## Scope

This correction packet is stacked on `G0-ATT-13B1`. It changes only the time
authority of persisted isolated-Attempt start and terminal records and the
strict Event-Store projection used to verify them. It does not invoke a
runtime, execute provider code, issue or consume an Effect Lease, publish an
EvidencePacket, merge, promote, or change the active gate.

## Finding

The parent lifecycle exposed `started_at` on `AttemptLedger.begin` and
`IsolatedAttemptCoordinator.prepare`, and `completed_at` on
`AttemptLedger.complete`. Those caller-supplied values became canonical record
and provenance fields. The strict projection retained the Event Store's
`created_ts` and `resolved_ts` but did not causally bind them to the record
timestamps.

A caller could therefore backdate or future-date evidence, and could submit a
completion timestamp before its persisted start, while the canonical Event
Store recorded a different transition time.

## Correction

The lifecycle authority now samples start and completion time internally. The
public mutation API no longer accepts lifecycle timestamps.

For every retained transition:

- the record timestamp equals its provenance `created_at` exactly;
- the Event Store transition cannot precede the authority record time;
- the authority record must be within a bounded interval of the Event Store
  transition;
- the `INTENDED` event timestamp must equal the intent-row `created_ts`;
- completion cannot precede the persisted start;
- terminal Event Store time cannot precede start Event Store time;
- replay retains the first persisted timestamps and never replaces them with a
  later call's clock sample.

The bound is deliberately short and fail-closed. It is not a distributed-clock
claim and does not authorize remote runtime evidence. Later runtime packets
must bind their own manifest and conformance clocks or use monotonic duration
receipts as specified by their contracts.

## Adversarial evidence specification

Behavioral tests cover:

1. absence of caller-supplied timestamp parameters;
2. authority-owned start and completion timestamps;
3. future or stale authority time against the Event Store;
4. direct substitution of intent-row time;
5. canonical payload repackaging with a historical start time;
6. completion before start;
7. canonical terminal-receipt repackaging before start.

The bounded mutation runner attacks caller-time parameter reintroduction,
caller-derived timestamps, removal of start/event binding, removal of causal
completion ordering, and detachment of record/provenance time. Every mutant
must be killed after a green focused baseline and all production files must be
restored byte-for-byte.

## Remaining boundary

`AttemptLedger.begin`, `AttemptLedger.complete`, and
`IsolatedAttemptCoordinator.prepare` remain explicit effect-inventory blockers
until the canonical registry contains honest rows and the later execution packet
mechanically composes persisted Effect Lease, Runtime Manifest, current
Conformance Receipt and sandbox evidence. This packet does not claim central
wiring.

GitHub Actions issue #67 may prevent hosted jobs from reaching Step 1. A
zero-step run is infrastructure evidence only and is neither green nor a
product failure.

Iron Plan: **ALIGNED BY SCOPE; EXACT-HEAD EXECUTION REQUIRED**  
Iron Gate: **0**  
Promotion: **not requested**
