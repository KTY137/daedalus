# G1-HIER-06A - Budget pricing owner

## Frozen packet metadata

- Packet ID: G1-HIER-06A
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 0e8cd9061bf977cc7daf1d6720369736342f0e33
- Dependencies: G1-HIER-01, G1-HIER-02, G1-RUNTIME-02
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

Pre-call pricing has one canonical implementation under
`daedalus.kernel.policy.pricing`; `daedalus.budget` reexports the exact same
classes, functions, constants, and price table while retaining Ledger,
Reservation, SpendEnvelope, and process-interposer authority for later
strangler packets.

## Scope

This stage moves `BudgetError`, `UnknownPrice`, `VendorPrice`, `Estimate`, the
price catalogue, subscription declaration, unknown-price policy, and
`price_call`. It does not move or modify ledger files, locks, period rollovers,
reservations, settlement, spend envelopes, process monkeypatches, effect
boundaries, provider calls, or persistent formats.

The legacy module decreases from 2,207 to 1,999 lines. The 215-line pricing
owner imports no ledger, process, network, provider, SQLite, event, or effect
implementation. It continues to consult the existing canonical host/egress
classifier; no second host trust rule is introduced.

## Contracts and behavior

- Old and new imports are exact object identities, including the private price
  table used by compatibility tests.
- Local, operator-trusted remote, untrusted remote, flat-rate subscription,
  token-priced, worst-case, and unknown/refuse orderings are unchanged.
- Unknown calls remain charged at the same conservative value and never become
  free. A subscription remains dollar-free but call-counted and cannot launder
  an untrusted endpoint.
- Existing pickle globals naming `daedalus.budget.Estimate` still resolve
  through the facade to the canonical class.
- All environment variable names, returned fields, reason strings, values, and
  caller-facing exception inheritance remain compatible.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Single authority | AST plus old/new/package identity tests | no pricing definitions in `budget.py`; exact objects |
| Pricing parity | complete budget and subscription/egress tests | identical estimates and refusals |
| Authority isolation | owner AST/import test | no ledger, process, network, provider, SQLite, or effect authority |
| Cold import | isolated interpreter | no legacy budget or provider module loaded |
| Pickle compatibility | legacy GLOBAL probe | resolves to canonical `Estimate` |
| Effect stability | Registry digest | unchanged digest above |
| Provider/network budget | builder tests only | zero live provider or network calls |

## Migration and rollback

Rollback restores the pricing definitions to `daedalus.budget` and removes the
hierarchy owner/reexports. No ledger JSON, environment value, reservation,
envelope, runtime state, historical evidence, or Registry row is migrated.

Later packets must move Ledger/Reservation and the process adapter separately;
the root facade cannot retire until source, runtime-string, wheel, docs,
Effect-Registry, and pickle audits find no remaining caller.

## Evidence expected failures and review

No pricing, ledger, spend, desktop, Registry, import, or pickle failure is
expected. The frozen architecture-baseline locator drift and existing
integration painted-effect diagnostic are outside this packet and remain
retained negative evidence. Independent review must confirm that the pricing
owner cannot reserve, settle, spawn, call a provider, or mutate persistent
state and that the conservative host/subscription ordering is unchanged.
