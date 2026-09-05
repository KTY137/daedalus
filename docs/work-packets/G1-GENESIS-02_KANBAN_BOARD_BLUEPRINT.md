# G1-GENESIS-02 — Deterministic Kanban board blueprint

## Frozen packet metadata

- Packet ID: `G1-GENESIS-02`
- Artifact role: primary
- Classification: `ALIGNED`
- Active gate: Gate 1 — owner-directed Genesis product strand
- Owner: repository owner
- Base revision: `61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0`
- Design authority: `docs/IKARUS_ARIADNE_MASTER_PLAN.md`, Revision 12,
  SHA-256 `126594137ebf1854458e625b64831c431c64b4a9f3dd8ca2b03c7867e0e8d8fb`
- Dependencies: green `G1-GENESIS-01` item-collection vertical slice
- Promotion: forbidden; a green preview is not merge, release, or publication

## Primary acceptance claim

Genesis can additionally compile the exact phrase `kanban board` or
`kanban-board` into a deterministic `kanban-board-v1` Web/PWA candidate with
fixed Backlog, In Progress, and Done columns. Cards have a typed
`id/title/details/column` contract, local persistence, create/edit/delete, and
keyboard-operable Move Back/Move Forward actions. Search remains optional.

This packet does not widen Genesis into an arbitrary application compiler.
Kanban CLI requests, custom columns, drag-and-drop, authentication, cloud
services, dependencies, and unconsumed requirements refuse before any state,
lease, workspace, process, or candidate effect. Desktop and mobile remain the
existing honestly labelled PWA targets.

## Contracts and behavior

- Existing item-collection requests remain policy `11.2`, request identity `/1`,
  materializer identity, template hashes, evaluator
  `197bc14cf98255c08f16a0b1447e8d9598f5114b9d829c9674321e697364dde7`,
  operation schema `/1`, source output, replay, and preview compatible.
- `kanban-board-v1` alone uses policy `12.1`, request identity `/2`, its own
  materializer identity, evaluator, and operation schema.
- The request-key-derived Run/Mission/Attempt suffix deliberately remains in
  the frozen 11.2 idempotency namespace for both profiles. Reusing one key for
  another profile therefore conflicts instead of forking canonical state.
- Replay and preview select the evaluator from the retained CAS-bound
  `GenesisAutonomyPolicy` plus `ProductSpec.defaults.blueprint`. Unknown or
  crossed version/profile pairs fail closed.

## Scope

In scope: the existing Genesis admission, materializer, service, focused tests,
and this packet. Out of scope: HTTP and frontend facades, effect registry,
kernel contract shape, master plan/amendments, release adapters, index
regeneration, merge, promotion, and publication.

## Acceptance matrix

| Claim | Deterministic evidence |
|---|---|
| Legacy byte/identity compatibility | fixed prompt/key asserts complete source revision, Run ID, contract, evaluator, rendered-files, and operation digests |
| Exact routing | only exact `kanban board` / `kanban-board` selects the new blueprint; `task board` remains 11.2 |
| Effect-free refusal | CLI, unknown blueprint/features, custom columns, and unconsumed requirements leave no Genesis control state |
| Deterministic safe materialization | all PWA targets return identical sorted safe byte trees and no external/dependency surface |
| Typed Fourfold candidate | generated tests pass and the Card model/schema/README compile to four complete planes |
| Fixed keyboard workflow | generated source contains only Backlog/In Progress/Done plus Move Back/Move Forward controls; no drag-and-drop |
| Independent evaluator | hardcoded app-template, model, and schema identities plus structural markup/search checks bind the exact candidate CAS |
| Mutation sensitivity | no-op movement, changed columns/model/schema/markup, and missing requested search turn the candidate red |
| Replay compatibility | legacy 11.2 and Kanban 12.1 terminal results replay and preview together; crossed profile/key conflicts |
| No promotion authority | result continues to report owner approval required and automatic promotion false |

## Migration and rollback

Rollback removes only the 12.1 profile branches and this blueprint's generated
templates/tests. It leaves the 11.2 path and all retained candidates, negative
observations, Attempt/effect terminals, and content-addressed evidence intact.
No historical policy, report, or evaluator digest is rewritten.

## Evidence, expected failures and review

Retain the deterministic compatibility, routing, refusal, materialization,
mutation-sensitivity and replay receipts named in the acceptance matrix.
Unknown blueprints, widened product requirements, crossed profile identity, or
any publication authority are release-blocking failures.
