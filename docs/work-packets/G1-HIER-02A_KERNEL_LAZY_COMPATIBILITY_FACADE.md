# G1-HIER-02A - Lazy kernel compatibility facade

## Frozen packet metadata

- Packet ID: `G1-HIER-02A`
- Active gate: **Gate 1 - Renovation and owner-directed Genesis**
- Classification: `ALIGNED`
- Owner: repository owner; no automatic merge, promotion, or Gate transition
- Base revision: `151b8d18`
- Master-plan authority: Revision 11
- Master-plan digest: `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Parent program: `G1-HIER-02` contract/kernel decomposition
- Primary claim: importing the kernel package or an independent kernel
  submodule does not require an absent, unrelated Campaign slice, while every
  declared compatibility export retains its original owning object.

## Baseline reproduced

The WIP facade eagerly imports eleven capability modules and then imports
`daedalus.kernel.campaigns`, a referenced file that is absent at the frozen
parent. Consequently `import daedalus.kernel`, `import
daedalus.kernel.artifacts`, and `import daedalus.web_api` all fail with the same
unrelated `ModuleNotFoundError` before their requested code can load.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Bare package import | isolated-process test | zero kernel capability submodules loaded eagerly |
| Independent submodule/Web import | import tests | succeeds without importing Campaigns |
| Existing root reexports | identity tests | facade object is the exact owner-module object |
| Compatibility inventory | frozen-list test | existing 96-name `__all__` and order unchanged |
| Campaign module/export access | refusal tests | targeted `ModuleNotFoundError` naming the absent slice |
| Later real Campaign module | loader behavior | loaded normally; dependency failures are not masked |
| Provider/network budget | focused tests | zero live starts/calls |

In scope: `daedalus/kernel/__init__.py`, one focused compatibility test module,
and this packet. Forbidden: no Campaign implementation, substitute contract,
event store, import hook, effect entrypoint, policy change, persistent-data
change, or Master Plan edit.

Rollback restores the eager facade and therefore restores the recorded WIP
import failure. No persistent migration exists. Independent review must verify
that lazy lookup cannot mislabel a dependency failure as a missing Campaign
slice.
