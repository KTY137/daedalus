# G1-RUNTIME-PROVIDER-06 - Runtime provider catalogue owner

## Frozen packet metadata

- Packet ID: G1-RUNTIME-PROVIDER-06
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: de6ad51984aeaef04587a4af67416cc988ae1da6
- Dependencies: G1-HIER-01, G1-RUNTIME-02, G1-RUNTIME-PROVIDER-05
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

`daedalus.runtimes.providers.catalogue` owns provider metadata,
configuration evaluation, safe probe classification, and health projection.
Concrete provider construction remains the historical
`daedalus.providers.get_provider` effect door and is injected into the runtime
owner, so the runtime package does not import legacy provider implementations.

## Scope

Only provider catalogue and health-projection ownership move. Provider names,
metadata values and order, environment keys, availability calls, serialized
health fields, routing behavior, admission, subprocess/network behavior,
registered Effect targets, stores, and persistent formats remain unchanged.
No provider is admitted more broadly.

## Contracts and behavior

- `ProviderMetadata`, the catalogue mapping, `_configured`, and
  `list_providers` are exact reexports through the legacy package.
- Configuration evaluation accepts an injected environment mapping; the
  compatibility path still reads the current process environment per call.
- Provider construction and availability are injected ports. Placeholder
  providers refuse before factory invocation, and probe exceptions remain
  classified health data rather than escaping.
- `provider_health` preserves row order and all canonical fields.
  `available_providers` continues to omit unimplemented placeholders.
- The legacy package resolves its current `get_provider` and health wrappers
  on every call, preserving existing monkeypatch seams.
- Registered concrete provider class and method targets remain at their exact
  historical import paths; no Registry source locator moves.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Exact compatibility | object-identity and ordered-value contracts | same metadata objects, names, values, order |
| Directed runtime owner | import and AST contracts | no provider/gate/orchestration/interface import |
| Effect injection | live monkeypatch contract | current factory observed on every implemented probe |
| Placeholder refusal | throwing factory contract | no construction; pending classification retained |
| Environment policy | empty injected environment | keyed provider configured/available false |
| Provider behavior | Codex, hardening, routing, secrets suites | unchanged |
| Architecture/Registry | frozen checks | zero forbidden edges; 20 shims; exact digest |

## Migration and rollback

There is no persistent migration. Rollback restores metadata and projection
bodies inside `daedalus.providers`, removes the runtime owner and package
exports, and removes the shim entry. No JSON report, ledger, receipt,
database, CAS locator, evidence path, historical run, provider authorization,
registered Effect target, or provider executable-object identity changes.

## Evidence, expected failures, and review

- Python 3.13: 116 focused catalogue, architecture, provider-registry, Codex,
  hardening, routing, and secret-row tests passed.
- Python 3.10: the same 116 focused tests passed.
- A broader Python 3.13 selection produced 139 passes and two failures. Both
  failures reproduce unchanged on the exact packet parent: the retired VS Code
  dashboard source still lacks `active_agents`, and the old COMMS test inspects
  the now-thin File Bridge facade instead of its canonical request owner.
  Neither failure is relabelled as green or repaired in this provider packet.
- Changed modules compile, cold imports succeed on Python 3.13 and 3.10, and
  `git diff --check` is clean.
- The Effect Registry semantic digest remains exactly
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`.

Review must reject a runtime import of a concrete legacy provider, a second
mutable catalogue, live probing during import, or any broader trust/admission
claim derived from inventory metadata. The global Work-Packet index remains
deferred to central integration because of the inherited G1-HERMES-01 section
defect. This packet does not edit the Master Plan, amendment chain, historical
`runs/`, generated web distribution, Registry targets, or promotion state.
