# G1-HIER-06B - Budget ledger owner

## Frozen packet metadata

- Packet ID: G1-HIER-06B
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: fb4dd37a5392735706ca5621b8b22086a6d895ee
- Dependencies: G1-HIER-01, G1-HIER-02, G1-HIER-06A
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

Persistent money-budget state, cross-process locking, Reservation, and
SpendEnvelope have one canonical implementation under
`daedalus.kernel.policy.ledger`. `daedalus.budget` reexports the exact same
objects; `daedalus.kernel.policy` reexports non-colliding contract names while
retaining `policy.ledger` as the importable owner module.

## Scope

This stage moves ledger configuration, refusal types, locking, state views,
reservation settlement/release, spend envelopes, JSON persistence, and the
module-level default ledger. It does not change the ledger path or bytes, move
historical `runs/` data, alter pricing, classify a process or URL, interpose a
process, call a provider, or add an effect door. The process-aware `guard`
remains with the existing effect facade for the later process-adapter packet.

## Contracts and behavior

- Legacy and hierarchy imports are exact object identities, including the
  cross-process lock used by compatibility tests.
- Ledger JSON keys, periods, entry truncation, locators, lock ordering,
  reservation IDs, envelope IDs, refusal text, and fail-closed behavior are
  unchanged.
- Existing pickle globals naming `daedalus.budget.Ledger` or `Reservation`
  continue to resolve through the facade.
- Importing the owner performs no process interposition, provider import,
  effect start, ledger write, or network call.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Single authority | AST plus exact identity tests | no duplicate ledger definitions |
| Persistence parity | budget, wave, crash, and spend-envelope suites | identical state and refusals |
| Authority isolation | AST and cold-import probes | no process, provider, gate, or effect owner |
| Locator parity | exact default-path assertion | unchanged `runs/budget/ledger.json` |
| Pickle compatibility | legacy GLOBAL probes | canonical classes resolve |
| Effect stability | Registry digest | unchanged digest above |
| Provider/network budget | builder tests only | zero live provider or network calls |

## Migration and rollback

No persistent migration is required. Rollback restores the ledger definitions
to `daedalus.budget` and removes the owner/reexports; existing ledger JSON and
historical evidence remain in place. The root facade cannot retire until the
source, runtime-string, wheel, docs, Effect-Registry, and pickle audits pass.

## Evidence expected failures and review

No budget, persistence, process-guard, Registry, import, or pickle failure is
expected. The frozen architecture locator drift and existing painted-effect
diagnostic remain retained negative evidence outside this packet.
