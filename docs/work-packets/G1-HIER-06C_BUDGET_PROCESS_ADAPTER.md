# G1-HIER-06C - Budget process adapter

## Frozen packet metadata

- Packet ID: G1-HIER-06C
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: bacd9e6e69d58de6aebde4847e6afd6101b2ca72
- Dependencies: G1-HIER-01, G1-HIER-06A, G1-HIER-06B, G1-RUNTIME-02
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2
- Effect-registry digest:
  ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec

## Primary acceptance claim

Process and URL spend classification, explicit guard depth, subprocess and
urllib interposition, and the billable-site register have one runtime
implementation under daedalus.runtimes.execution.budget_process.
daedalus.budget remains the stable registered effect facade and composes its
current compatibility ports into that owner.

## Scope

This stage completes the requested budget.py responsibility split after the
Pricing and Ledger packets. It moves only the process adapter and register.
The root module retains the public names and the registered
process_guard_boundary_decision target. It does not change pricing, ledger
bytes, spend ceilings, provider admission, effects, anchors, persistent data,
historical evidence, or any live endpoint.

## Contracts and behavior

- classify_argv, classify_url, guard, uninstall_process_guard, the
  install-state dictionary, and the site register are exact reexports.
- The facade installer remains a function at the legacy path and passes its
  current classifier and reservation bindings explicitly. Existing
  monkeypatches therefore still intercept before any process or request.
- Explicit reservation depth remains shared between guard, subprocess.run,
  Popen, and urlopen, preventing double charging.
- Idempotent installation, safe mock-aware uninstall, Popen subclassability,
  read-only probes, remote inference classification, and fail-closed reserve
  ordering remain unchanged.
- Importing the implementation does not install the guard, mutate the ledger,
  import the legacy facade, providers, or gates, spawn a process, or open a
  connection. The existing kernel package initializer still transitively loads
  its spine-envelope compatibility dependency; this packet introduces no
  direct runtime-to-spine import and does not conceal that separate debt.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Single process authority | AST and exact-object tests | no duplicate implementation in facade |
| Compatibility ports | AST plus red/green monkeypatch tests | current facade bindings are injected |
| No double charge | explicit/interposed budget tests | one reservation and settlement |
| Interposer safety | Popen/mock/idempotence suites | reversible and subclass-safe |
| Cold import | isolated interpreter | no facade/provider/gate import |
| Effect stability | Registry digest and old decision target | unchanged digest above |
| Provider/network budget | builder tests only | zero live provider or network calls |

## Migration and rollback

No data migration is required. Rollback restores the process implementation
to daedalus.budget and removes the runtime owner. Ledger JSON, environment
names, process globals, Registry rows, anchors, and callers remain compatible
in either direction.

## Evidence expected failures and review

No budget, interposer, import, effect, Registry, process, or URL-classification
failure is expected. Existing global architecture-locator drift and the
painted-effect baseline remain retained outside this packet. Independent
review must verify the facade still injects current monkeypatch bindings and
that the implementation cannot begin a registered effect itself.
