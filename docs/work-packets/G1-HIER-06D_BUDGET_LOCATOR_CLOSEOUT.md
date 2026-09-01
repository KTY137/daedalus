# G1-HIER-06D - Budget locator closeout

## Frozen packet metadata

- Packet ID: G1-HIER-06D
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 5340dec799a11cddddd0d5570cb38d5c072db17f
- Dependencies: G1-HIER-01, G1-HIER-06A, G1-HIER-06B, G1-HIER-06C
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

The envelope producer inventory and compatibility-shim registry identify the
new canonical budget owners after the pricing, ledger, and process-adapter
split; the legacy `daedalus.budget` effect facade is no longer misidentified as
the persistence implementation.

## Scope

- `UNCONVERTED_PRODUCERS` moves the existing period-ledger classification from
  `daedalus/budget.py` to `daedalus/kernel/policy/ledger.py`.
- The shim registry now records the budget facade, its three hierarchy owners,
  and the Effect Registry plus pickle audits required before retirement.
- Out of scope: retiring the facade itself, migrating the Effect Registry
  target, and any change to pricing, reservation, or process-adapter logic.

## Contracts and behavior

The producer classification remains unchanged: budget state is period-wide
policy authority, not a per-run record, so adding an ambient trace would make a
false correlation. Only the locator of that classification moves.

No JSON field, digest, SQLite row, budget path, lock path, price, reservation,
process interception, effect target, or runtime behavior changes. The legacy
`daedalus.budget` names and the new `daedalus.kernel.policy.ledger` names
resolve to the same objects, so importers on either path observe identical
behavior.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Producer census | envelope drift detector | no undeclared writer and no stale facade declaration |
| Object identity | budget hierarchy tests | old and new paths resolve to the same objects |
| Persistent ABI | budget suite | identical path, fields, locks, reservations, and refusal behavior |
| Effect authority | Registry digest | unchanged |
| Provider/network budget | builder tests only | zero live provider or network calls |

## Migration and rollback

There is no persistent-data migration. Rollback restores the producer-inventory
key and removes the shim row; it does not touch the budget ledger or its lock.

The facade remains required until a dedicated Effect Registry target migration
and source, runtime-string, wheel, documentation, monkeypatch, and pickle audits
prove that every compatibility consumer has moved.

## Evidence, expected failures and review

Evidence is builder-level and offline: the envelope drift detector over the
producer census, the budget hierarchy tests asserting old and new paths resolve
to the same objects, and the budget suite covering path, fields, locks,
reservations, and refusal behavior. Zero live provider or network calls.

Expected failure retained as negative evidence: this packet does not reduce the
shim count. `daedalus.budget` stays a declared compatibility facade with an open
retirement criterion, so a census that expects the facade to be gone will fail
by design until the Registry target migration packet runs.

Review questions: is the period-ledger classification still the only producer
declaration for budget state; does the Effect Registry digest hold unchanged;
and does the shim registry name a concrete removal criterion for each of the
three new owners rather than an open-ended one.
