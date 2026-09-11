# G1-HIER-02B - Runtime provider report contract

## Frozen packet metadata

- Packet ID: G1-HIER-02B
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: aa19b663c8abc285a63dbbad16cdfb5be9dd7bf1
- Dependencies: G1-HIER-01, G1-HIER-02, G1-RUNTIME-PROVIDER-02
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

`daedalus.runtimes.contracts.provider_report` is the single owner of the
provider-returned `AgentReport`, `REPORT_KEYS`, and `validate_report` wire
contract. Orchestration retains `AgentTask` and `RunState` only, while its
legacy report module and `daedalus.schemas` reexport the exact runtime-owned
objects for compatibility.

## Scope

This packet moves only the existing provider report dataclass, closed key set,
and validation function. It does not alter provider invocation, admission,
egress, report coercion, orchestration execution, UI projections, persistent
formats, Effect targets, or promotion behavior.

## Contracts and behavior

- Field names, field order, mutable default factories, `to_dict()` shape,
  accepted status vocabulary, summary bound, error order, and exact error text
  are transcribed unchanged from the former owner.
- `daedalus.AgentReport`, `daedalus.validate_report`, `daedalus.schemas`, and
  `daedalus.orchestration.legacy_reports` all resolve to the canonical runtime
  objects. Old pickle globals through both legacy modules still resolve.
- Provider report construction and verification import the runtime owner
  directly. No runtime contract imports providers, gates, orchestration,
  interfaces, or chip design.
- The mixed orchestration compatibility module is registered as a temporary
  shim; its own `AgentTask` and `RunState` implementations remain authoritative
  orchestration projections.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Single report authority | old/new identity assertions | exact same objects |
| Wire compatibility | valid and invalid report fixtures | identical dicts/errors |
| Pickle compatibility | old global loads | canonical runtime class |
| Directed hierarchy | owner and legacy AST checks | no outer owner imports or duplicate definitions |
| Provider behavior | Codex, Claude, verifier, budget suites | unchanged |
| Architecture baseline | G1-HIER-01 evaluator | zero forbidden edges; 16 registered shims |
| Registry stability | semantic digest assertion | exact existing digest |

## Migration and rollback

No persisted record changes: existing JSON reports are plain mappings and need
no migration. Rollback restores the three definitions in
`orchestration.legacy_reports`, points facade imports back there, and removes
the new runtime module and shim entry. No ledger, database, CAS locator,
evidence path, registered target, or historical run moves.

## Evidence, expected failures, and review

- Python 3.13: 272 focused contract, agent-environment, provider, budget, and
  architecture tests passed.
- Python 3.10: the same 272 focused tests passed.
- A broader Python 3.13 Codex, Claude, verifier, provider-contract, and
  rollback matrix passed 143 tests and 11 subtests.
- Direct cold imports through runtime, schema, orchestration, and package-root
  paths resolve to the same class and validator; changed modules compile.
- The Effect Registry semantic digest remains exactly
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`.

The generated Work-Packet index is refreshed centrally after parallel packet
integration; the inherited incomplete G1-HERMES-01 packet still blocks a
global render. This packet does not edit the Master Plan, amendment chain,
historical `runs/`, generated web distribution, Registry target, admission,
or promotion state.
