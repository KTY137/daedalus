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

## Scope and contracts

- `UNCONVERTED_PRODUCERS` moves the existing period-ledger classification from
  `daedalus/budget.py` to `daedalus/kernel/policy/ledger.py`.
- The classification remains unchanged: budget state is period-wide policy
  authority, not a per-run record, so adding an ambient trace would make a
  false correlation.
- The shim registry now records the budget facade, its three hierarchy owners,
  and the Effect Registry plus pickle audits required before retirement.
- No JSON field, digest, SQLite row, budget path, lock path, price, reservation,
  process interception, effect target, or runtime behavior changes.

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
