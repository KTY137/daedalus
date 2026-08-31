# G1-HIER-05 - Neutral gate receipt contracts

## Frozen packet metadata

- Packet ID: `G1-HIER-05`
- Active gate: **Gate 1 - Renovation and owner-directed Genesis**
- Classification: `ALIGNED`
- Owner: repository owner; no automatic merge, promotion, or Gate transition
- Base revision: `151b8d18`
- Prerequisite packet: `G1-HIER-02A` (`7d3f742b` on this branch)
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Primary claim: gates produce exact repository, retention-inventory, and
  Python-target observations through neutral runtime contracts; runtime
  admission validates them through injected read-only ports without importing
  gate implementations.

## Change boundary

`daedalus.runtimes.contracts` owns the receipt, inventory, structural target,
error, and typed port contracts shared by gates and runtime admission. The
existing gate modules retain repository reads, AST inspection, and receipt
production while re-exporting the exact same public contract objects. Runtime
preadmission and retention admission consume only the neutral contracts and
require their gate operations as explicit keyword-only ports.

The existing gate import paths remain compatible, including old pickle globals:
they resolve to the same class objects. Wire schemas, JSON fields, digests,
source paths, error domains, effect identifiers, and persistent formats do not
change.

## Acceptance and refusal matrix

| Claim/refusal | Deterministic evidence | Expected |
|---|---|---|
| Runtime-to-gate boundary | whole-package AST scan | zero direct `runtimes -> gates` imports |
| Old/new imports | object-identity tests | exact same class objects |
| Gate observations | existing gate suites | identical wire fields, digests, and failure behavior |
| Runtime validation | focused runtime suites | ports are explicit, required, and read-only |
| Authority ordering | source-review tests | authenticate before reads; HEAD fenced twice |
| Registry stability | SHA-256 measurement | `fb060b3e32949a1911e920ae91aa0c883410ca5a36074db9c338f5a64de7f165` |
| Persistent state | packet scope | no store, CAS, locator, or schema migration |

In scope: neutral shared types, compatibility exports, injected verifier ports,
review updates that follow the canonical type owner, tests, and this packet.
Forbidden: no gate implementation imported from runtime code; no new gate,
effect, event store, artifact identity, policy, provider admission, evaluator,
promotion path, Master Plan, or Amendment Chain change.

Rollback returns type ownership to the gate modules and supplies the former
gate functions directly inside runtime admission. No persistent migration is
needed in either direction.

## Builder evidence

- related gate/runtime matrix: `358 passed, 13 skipped`;
- complete `tests/gates` plus `tests/runtimes`: `1851 passed, 74 skipped`;
- wheel build and install outside the checkout: passed; wheel SHA-256
  `b91fa9997d33bdfb9e9245db07595eb23a3b9c8e210ff5511a6c19a7739980e0`;
- installed-wheel old/new identity smoke: passed for repository receipt,
  retention inventory, and Python target structure;
- `compileall` and `git diff --check`: passed;
- historical Forest-v2 corpus check: `6 passed, 2 failed` on the pre-existing
  retracted function-count pin and absent optional third-party corpus. The same
  two failures reproduce on comparison packets and are retained, not rewritten.
