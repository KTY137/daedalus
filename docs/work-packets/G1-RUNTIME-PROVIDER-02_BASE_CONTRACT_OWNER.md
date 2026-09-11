# G1-RUNTIME-PROVIDER-02 - Runtime provider contract owner

## Frozen packet metadata

- Packet ID: G1-RUNTIME-PROVIDER-02
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: e961d0ec554d52cac0531a155d281a7e51cb54a1
- Dependencies: G1-HIER-01, G1-HIER-06E, G1-RUNTIME-PROVIDER-01
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

`daedalus.runtimes.providers.contracts` is the canonical owner of
`ProviderCapabilities`, `Provider`, the single rollback loop, and read-only
report enforcement. `daedalus.providers.base` is a compatibility facade that
reexports those exact class objects; it owns no implementation or state.

## Scope

This packet moves only the shared provider contract and its two existing
helper implementations. Concrete provider modules, executable registration,
admission, invocation, observations, receipts, interfaces, and persistent
state remain where they are.

## Contracts and behavior

- Concrete providers remain at their registered legacy targets. Moving an
  Effect Registry target is explicitly outside this structure packet.
- Existing imports from `daedalus.providers.base` resolve to the exact owner
  objects, so subclass checks, class attributes, monkeypatches, and unpickling
  by the old global name remain supported.
- The runtime contract owner imports only Python standard-library modules and
  has no gate, orchestration, interface, chip-design, or legacy-provider
  authority.
- The compatibility facade is recorded in the machine-readable shim register
  with source, runtime-string, wheel, documentation, monkeypatch, and pickle
  retirement criteria.
- The frozen capability fields, abstract method signatures, timeout default,
  rollback ordering, rollback failure capture, and deepest-first directory
  cleanup are byte-for-byte transcribed from the former owner.
- Read-only providers still move proposed files to
  `handoff.suggested_files`, clear mutating claims, and downgrade `done` to
  `needs_review`.
- Provider admission, executable selection, egress rules, report schemas,
  persistent formats, CLI names, and Effect Registry targets are unchanged.
- No live provider, network, or EDA invocation is part of this packet.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Object compatibility | old/new import identity contract | exact same class objects |
| Concrete compatibility | built-in subclass census | every built-in uses owner contract |
| Directed hierarchy | facade/owner AST contracts | facade-only legacy module; no outer owner import |
| Rollback/read-only behavior | provider hardening suites | unchanged reports and restoration |
| Architecture baseline | G1-HIER-01 evaluator | zero forbidden edges; 15 registered shims |
| Registry stability | semantic digest assertion | exact existing digest |
| Provider/network budget | builder tests only | zero live provider or network calls |

## Migration and rollback

There is no persistent-data migration. Rollback restores the two class
definitions in `daedalus.providers.base` and removes the runtime owner and its
shim-register entry. No provider implementation, registered target, receipt,
ledger, CAS locator, evidence path, or historical run moves.

## Evidence, expected failures, and review

- Python 3.13: 124 focused contract, provider, hardening, Effect, and
  architecture tests passed.
- Python 3.10: the same 124 focused tests passed.
- A broader Python 3.13 concrete-provider matrix passed 233 tests and 12
  subtests. Its one failure is inherited: the unchanged integration parent
  reproduces `InventedImports.test_no_false_positives_across_the_real_tree`
  with the same 134 facade-related offenders.
- Cold imports on Python 3.13 and 3.10 prove legacy/owner object identity and
  the exact Effect Registry digest.
- Changed modules compile and `git diff --check` reports no whitespace defect.

The generated Work-Packet index is refreshed centrally after parallel packet
integration. This packet does not edit the Master Plan, amendment chain,
historical `runs/`, generated web distribution, provider admission, Registry
target, or promotion state.
