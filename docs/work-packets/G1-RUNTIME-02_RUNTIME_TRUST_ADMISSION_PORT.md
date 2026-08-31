# G1-RUNTIME-02 — Runtime Trust Admission Port

## Authority and classification

- Iron Plan: `ALIGNED`
- Iron Gate: `1`
- Master Plan: Revision 11, SHA-256
  `711DE9F0BDF0AB15011314528821B75ED5666906F4805EC9FF9C65386ED5A3B2`
- Frozen parent: `151b8d180e321cfba48b4c7d62f9be56579d52a5`
- Packet branch: `packet/g1-runtime-02`
- Promotion, merge, provider invocation, and network access: not requested

This packet is the bounded Gate-1 hierarchy slice that removes concrete
runtime-trust ownership from the kernel. It does not change the Master Plan,
mint a new trust authority, or claim Gate closure.

## Delivered boundary

The kernel owns only the neutral, read-only contracts it consumes:

- `RuntimeTrustLedgerPort` for exact active-record lookup;
- `RuntimeTrustRecordPort` for the authenticated binding fields;
- `RuntimeTrustPortError` for fail-closed trust-authority failures.

`daedalus.kernel.runtime_effects` and the replay projection consume those
ports. The concrete `RuntimeTrustLedger`, persisted trust schema, integrity
checks, production ledger location, key custody, and authorization composition
belong to `daedalus.runtimes`.

The production composition root is now
`daedalus.runtimes.admission.acquire_runtime_bound_authorization`. It still
uses the existing runtime-bound lease, trust ledger, Effect-Lease ledger,
kill-switch generation, registry, keys, TTL bounds, and clock behavior. No
wire field, canonical digest, SQLite schema, registry row, key identifier, or
effect target changes in this packet.

## Compatibility shim

`daedalus.kernel.runtime_authorization_issuer` remains a registered, removable
PEP-562 compatibility facade. Bare module loading imports only the standard
library. Accessing a legacy export lazily resolves the canonical object from
`daedalus.runtimes.admission`; it does not define a wrapper, second function,
ledger singleton, or parallel authority. Old and new exports are required to
be object-identical.

The packet-local machine-readable register is
`G1-RUNTIME-02_SHIM_REGISTER.json`. Retirement requires completed source,
runtime-string, wheel, documentation, and pickle/global-reference audits.

## Fail-closed properties

1. Runtime-effect issuance requires an injected `RuntimeTrustLedgerPort`.
2. An absent or structurally invalid port is refused before
   `issue_effect_lease` can mint or persist a lease.
3. A port returning an invalid record is refused as a binding mismatch.
4. Concrete lookup failures retain their existing exception classes while
   also crossing the neutral kernel error boundary.
5. Active-record identity, envelope, manifest, conformance receipt, source
   revision, expiry, and canonical record digest remain bound exactly as
   before.
6. Runtime replay catches the neutral port failure, not a concrete runtime
   implementation.

## Preserved provider admission

The effect registry is not edited. The exact frozen-parent wiring remains:

- `provider.claude`: `INVENTORY_ONLY`
- `provider.codex`: `INVENTORY_ONLY`
- `provider.ollama`: `LOCAL_GUARDS`

This packet cannot broaden those rows and performs no live provider, network,
or EDA operation. The registry source SHA-256 before this packet is
`FB060B3E32949A1911E920AE91AA0C883410CA5A36074DB9C338F5A64DE7F165` and
must remain identical at the packet commit.

## Verification

The packet supplies focused evidence for:

- zero static `daedalus.kernel -> daedalus.runtimes` Python import edges;
- neutral Protocol ownership and concrete runtime composition ownership;
- lazy facade shape and exact old/new object identity;
- invalid-port refusal before Effect-Lease issuance;
- unchanged provider registry wiring;
- existing issuance, binding, clock, replay, and persisted trust behavior.

The frozen parent has a pre-existing collection blocker:
`daedalus.kernel.__init__` imports the absent
`daedalus.kernel.campaigns`. Native focused pytest therefore stops during
collection with `ModuleNotFoundError`. The missing subsystem is not recreated
or replaced in this packet. To distinguish that parent defect from this
slice, the same focused suites are additionally executed with an explicitly
named, process-local `_FrozenParentCampaignStub` containing only the missing
exports; the stub is diagnostic, never written to the tree, and supplies no
behavior.

Expected packet evidence at commit:

- boundary suite: 5 passed;
- diagnostic issuer/admission/clock/replay/trust suite: 46 passed;
- focused compile-all: passed;
- native focused suite: blocked during collection only by the absent parent
  `campaigns` module;
- registry digest: unchanged;
- direct kernel-to-runtime import search: no matches.

## Rollback and remaining work

Rollback delegates the registered facade to the previous implementation while
leaving persisted data untouched. Shim removal is a later packet after every
registered audit succeeds. This slice does not migrate provider registries,
open inventory-only rows, alter persistence, add a runtime, repair the frozen
parent's missing campaigns module, merge, promote, or close Gate 1.
