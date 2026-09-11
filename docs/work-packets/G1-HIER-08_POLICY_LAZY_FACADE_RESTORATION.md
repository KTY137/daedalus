# G1-HIER-08 - Policy lazy facade restoration

## Frozen packet metadata

- Packet ID: G1-HIER-08
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: e91ce02e7611de19013e75d2191dac19725fcc55
- Dependencies: G1-HIER-02A, G1-HIER-06A, G1-HIER-06B
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

Requesting one `daedalus.kernel.policy` reexport loads only the owner that
holds it. The G1-HIER-02A claim that a kernel reexport loads a single owner,
which the pricing and ledger owner split silently broke, holds again for the
policy package.

## Scope

- `daedalus/kernel/policy/__init__.py` becomes a lazy reexport facade over its
  three existing owners `limits`, `pricing`, and `ledger`, using the same
  PEP 562 `__getattr__` pattern already used by `daedalus/kernel/__init__.py`.
- The three owner modules, their implementations, and their public names are
  untouched. No symbol moves between owners.
- Out of scope: the `daedalus.budget` facade and its retirement, the broader
  `daedalus.kernel` facade, any pricing or ledger behavior, and the remaining
  eager reexport packages elsewhere in the tree.

## Contracts and behavior

`__all__` keeps its exact previous order, which is a compatibility contract
independent of module grouping. All 41 exported names resolve to the same
objects as before, and `from daedalus.kernel.policy import X` continues to work
for every one of them because PEP 562 module `__getattr__` participates in
`from`-import resolution. `daedalus.budget` remains object-identical: its
`Ledger` and `price_call` are the same objects as `kernel.policy.ledger.Ledger`
and `kernel.policy.pricing.price_call`.

A name that was never exported still raises `AttributeError` naming the module
and the attribute, rather than resolving through a wildcard.

No JSON field, digest, SQLite row, ledger path, lock path, price, reservation,
environment variable, effect target, or runtime behavior changes. This is an
import-time change only.

Measured before the fix, importing the security contract `OwnerApproval`
loaded `kernel.policy`, `kernel.policy.ledger`, `kernel.policy.limits`, and
`kernel.policy.pricing`. After the fix it loads `kernel.policy` and
`kernel.policy.limits` only.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Single-owner load | `tests/kernel/test_kernel_lazy_facade.py` cold-import subprocess | only the requested name's owner in `sys.modules` |
| Object identity | all 41 `__all__` names against their owner module | identical objects |
| Export order | `__all__` comparison against the pre-facade order | unchanged sequence |
| Budget facade parity | `daedalus.budget` reexports | same `Ledger` and `price_call` objects |
| Unknown name | attribute access on an unexported name | `AttributeError` naming module and attribute |
| Effect stability | Registry digest | unchanged digest above |
| Provider/network budget | builder tests only | zero live provider or network calls |

## Migration and rollback

No persistent data, schema, or route migration exists. Rollback restores the
three eager `from .X import (...)` blocks in
`daedalus/kernel/policy/__init__.py` and removes the `_EXPORT_GROUPS` map and
`__getattr__`. Historical evidence, CAS, ledgers, databases, generated web
artifacts, Master Plan, and amendment chain are untouched.

## Evidence, expected failures and review

Evidence is builder-level and offline: the cold-import subprocess assertion in
`tests/kernel/test_kernel_lazy_facade.py`, plus the object-identity and
export-order checks over the full `__all__`. Budget: zero live provider, model,
container, or external-network calls.

Retained negative evidence: this regression was present and unnoticed on
`integration/g1-hierarchy` from the pricing/ledger owner split until this
packet. The single failing test existed and was correct the whole time; the
packets that broke it ran only their own focused subsets and never re-ran it.
The failure is reproducible at the parent revision
`e91ce02e7611de19013e75d2191dac19725fcc55`. That is process evidence about
per-packet verification scope, not evidence about the owner split itself, whose
behavior this packet does not change.

Measured while closing this packet: `policy` was the only offender under
`daedalus.kernel`. `kernel/contracts/__init__.py` and
`kernel/events/__init__.py` have no eager owner imports, and a cold import of
either pulls in only itself. Twenty-three package `__init__` modules elsewhere
in the tree do import their owners eagerly, but no lazy-load acceptance claim
covers them, so that is recorded as an observation and not as a defect of this
packet.

Review questions: does any consumer rely on `daedalus.kernel.policy` having
already imported `ledger` or `pricing` as a side effect; is the cold-import
assertion strong enough to catch the next owner added to this package; and
should the lazy-load claim be extended beyond `daedalus.kernel` in a separate
packet, or is eager import the correct default outside the kernel facade.
