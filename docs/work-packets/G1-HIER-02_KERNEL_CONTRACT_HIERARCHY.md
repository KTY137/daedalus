# G1-HIER-02 - Kernel contract hierarchy

## Frozen packet metadata

- Packet ID: `G1-HIER-02`
- Artifact role: `primary`
- Active gate: `1`
- Classification: `ALIGNED`
- Owner: `repository owner`
- Base revision: `151b8d180e321cfba48b4c7d62f9be56579d52a5`
- Dependencies: `G1-HIER-02A at 4c591e9020bde86a97d2f87bb35447b783647614 on the packet branch`
- Promotion authority: no automatic merge, promotion, or Gate transition
- Prerequisite packet: `G1-HIER-02A` (`4c591e90` on this branch)
- Master-plan authority: Revision 11
- Master-plan digest: `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
## Primary acceptance claim

Kernel wire contracts and execution-limit policy have canonical owners below
`daedalus.kernel`, while old import paths expose the exact same objects and
bytes.

## Scope

The former root `schemas.py` implementation now lives at
`kernel/contracts/canonical.py`. Stable domain locators group mission, attempt,
evidence, campaign, policy, runtime, promotion, resource, registry, and
security contracts below `kernel/contracts/`. The former root
`limit_policy.py` implementation is owned by `kernel/policy/limits.py`.

The root modules remain compatibility facades with no implementation or
singleton state. Legacy `AgentTask`, `AgentReport`, `RunState`, and
`validate_report` forms are owned by `orchestration/legacy_reports.py`; they
remain object-identical exports of `daedalus.schemas`.

The domain files are hierarchy locators over one implementation nucleus in
this packet. Physically distributing the individual class bodies among those
files is deliberately deferred until all source, pickle, wheel, runtime-string,
and documentation consumers have crossed the locators. This packet does not
claim that follow-on retirement is complete.

## Contracts and behavior

Compatibility, refusal behavior, serialized bytes, and authority ownership are
frozen by the following matrix.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Old/new class import | identity tests | the exact same Python object |
| Existing serialized payload | canonical contract suites | identical JSON and digest |
| Old pickle global | protocol-0 compatibility test | resolves through `daedalus.schemas` |
| Limit policy | identity and policy suites | same objects, env bytes, fingerprint |
| Legacy reports | identity and report tests | same behavior under orchestration owner |
| Promotion authority | AST and identity tests | one class definition in canonical owner |
| Effect registry | SHA-256 measurement | unchanged `fb060b3e32949a1911e920ae91aa0c883410ca5a36074db9c338f5a64de7f165` |
| Persistent stores/CAS | packet scope | no schema, locator, or data migration |

In scope: the contract/policy ownership move, exact compatibility facades,
domain locators, focused tests, and this packet. Forbidden: no contract field,
digest, ID, registry, effect, policy decision, admission, store, CAS, evidence,
promotion, Master Plan, or Amendment Chain change.

## Migration and rollback

Rollback restores the previous root implementations. Persisted data requires
no migration because contract fields, canonical JSON, digests, SQLite formats,
CAS locators, and evidence paths are unchanged.

## Evidence expected failures and review

No live provider, network, EDA, merge, or promotion operation is expected.
Independent review must verify object and pickle identity, unchanged canonical
bytes and digests, and the absence of implementation or singleton state in the
legacy facades.
