# G1-HIER-06E - Budget shim and boundary closeout

## Frozen packet metadata

- Packet ID: G1-HIER-06E
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 24f5102b8704794f7434064788361889344d5423
- Dependencies: G1-HIER-01, G1-HIER-03B, G1-HIER-06A, G1-HIER-06B, G1-HIER-06C, G1-HIER-06D
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

The `daedalus.budget` shim names the tracked canonical process owner
`daedalus.runtimes.execution.budget_process`, every registered shim locator is
present in the tracked Python census, and the architecture contract retains no
already-resolved forbidden import edge. The current, allowlisted, and new
forbidden-edge sets are all empty.

## Scope

- Correct only the inherited budget process-owner locator.
- Retire exactly the five frozen Spine boundary rows that the tracked scanner
  now proves absent; add no replacement or allowlist row.
- Bind the architecture snapshot to zero baseline edges and the current 14 shim
  entries.
- Strengthen exact-object checks for every process-adapter name directly
  reexported by the stable budget facade.
- Do not change runtime code, JSON or SQLite formats, locks, digests, effect
  targets or anchors, persistent data, provider admission, the Masterplan,
  amendments, the global packet index, historical runs, or generated output.

## Contracts and behavior

- `git ls-files` remains the locator authority. An untracked lookalike cannot
  satisfy the shim contract.
- The process implementation remains solely in
  `daedalus.runtimes.execution.budget_process`; `daedalus.budget` remains the
  registered effect/composition facade and returns the same objects for all
  direct public and compatibility-private reexports.
- The five removed baseline rows are not moved or waived: current scanning on
  both Python 3.13 and 3.10 returns none of them.
- The tracked-only import graph has 418 modules and 1,572 edges on this base.
  Its SCC census remains 12 non-trivial components (largest size 21) on both
  Python versions. SCC reduction is not claimed by this metadata closeout.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| All shim locators tracked | locator validator over `git ls-files` | 14 entries valid |
| Boundary debt retired | architecture report | baseline/current/allowlisted/new/resolved all 0 |
| Canonical process owner | exact shim row plus source module | execution owner, no adapters lookalike |
| Facade compatibility | exact-object identity test | all direct reexports identical |
| SCC honesty | tracked AST graph on 3.13 and 3.10 | 418 modules, 1,572 edges, 12 SCCs, largest 21 |
| Effect authority | Registry digest | unchanged digest above |
| Live activity | builder tests only | no provider, network, or EDA calls |

## Migration and rollback

No persistent migration exists. Rollback restores the previous locator and the
five stale baseline rows; it does not touch the process adapter, budget ledger,
Registry, or runtime state. Such a rollback deliberately restores a known
fail-closed locator error and obsolete architecture debt, so it is suitable
only for packet reversal, not as accepted evidence.

## Evidence expected failures and review

Before the patch, the architecture contract fails identically on Python 3.13
and 3.10 with `shim target locator is not tracked:
daedalus.runtimes.adapters.process`. Correcting only that locator exposes the
second inherited drift: the scanner returns no current violations while the
contract still expects five resolved Spine edges. Both failures are expected
red evidence and are closed here without broadening an allowlist.

No budget, facade-identity, locator, architecture, Registry-digest, or packet
schema failure is expected after the patch. Independent review must compare
the retired rows to the scanner's resolved set, verify all 14 locators against
tracked files, and confirm the Effect Registry file and digest did not change.
