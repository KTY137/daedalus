# G0-ES-17 — Revision-Bound Event-Store Writer Inventory

## Objective

Produce a deterministic, machine-readable inventory of production Python callsites that directly construct `SpineLedger` or invoke the canonical Gate-0 writer factory. This packet measures migration state; it does not silently rewrite callsites and cannot by itself prove that all dynamic writer construction is absent.

## Report contract

`scan_event_store_writers()` scans `daedalus/**/*.py`, parses every file, canonicalizes callsites and binds the report to:

- one exact lowercase 40-hex source revision;
- every scanned repository-relative path;
- the SHA-256 of every scanned production Python file;
- the sorted callsite set and classification.

The CLI prints exactly one canonical JSON object to stdout. `--require-closed` returns nonzero when blockers remain but still emits the report for evidence retention. Refusals use stderr and emit no partial JSON.

## Conservative classification

The inventory distinguishes:

- `gate0_factory`: direct, unshadowed factory call;
- `read_only`: direct, unshadowed `SpineLedger(..., read_only=True)`;
- `legacy_direct`: default or explicitly writable direct construction;
- `ambiguous_direct`: dynamic `read_only`, expanded keywords or conflicting direct arguments;
- `ambiguous_binding`: shadowed imports, conflicting aliases, simple indirect aliases or unresolved tracked bindings.

The last three classifications are blockers. A local rebinding is conservatively treated as file-wide taint: this may create an extra finding, but it cannot upgrade a questionable writer to admitted status.

## Fail-closed inputs

The scanner refuses:

- malformed or non-UTF-8 production Python;
- malformed or noncanonical revision identifiers;
- missing or escaping package roots;
- production Python symlinks that resolve outside the package;
- relative imports that escape the `daedalus` package;
- unreadable files or incomplete byte binding.

Changes to unrelated production Python bytes still change the inventory digest, even when the callsite list itself remains unchanged.

## Adversarial batch

Builder tests and a separate source-level counter-review cover absolute, module, relative and aliased imports; literal readers; writable constructors; dynamic keyword arguments; import shadowing; module attribute mutation; conflicting imports; simple assignment aliases; malformed inputs; deterministic rebuilds; stdout-only CLI behavior and the selected Attempt factory callsite.

The bounded mutation campaign attacks:

1. removing `legacy_direct` from blockers;
2. treating default constructors as read-only;
3. admitting shadowed bindings as factory calls;
4. skipping revision validation;
5. removing production file bytes from the report binding;
6. allowing raw syntax errors to escape the inventory contract.

## Honest completeness boundary

This scanner is an evidence layer, not the runtime security boundary. Python wrappers, reflection, `eval`/`exec`, nontrivial alias propagation, native launchers and external processes are not proven complete by this AST pass. Gate 0 still requires the canonical effect-entrypoint inventory, runtime manifests, conformance receipts, Effect Leases and sealed execution/promotion boundaries.

The exact-head production report is not yet available because GitHub Actions issue #67 still prevents jobs from starting. Therefore no current callsite count, migration-complete statement, test pass, mutation score, platform result or packaging result is claimed.

No production writer is automatically rewritten, no effect is executed, no OwnerApproval is minted, no checkout is mutated and no merge or promotion is requested.

Iron Plan: **ALIGNED BY SCOPE; INVENTORY EXECUTION AND MIGRATION OPEN**  
Iron Gate: **0**  
Promotion: **not requested**
