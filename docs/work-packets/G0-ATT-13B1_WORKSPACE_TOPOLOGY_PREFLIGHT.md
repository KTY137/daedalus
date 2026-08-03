# G0-ATT-13B1 — Non-mutating Attempt workspace topology preflight

## Scope

This correction packet is stacked directly on `G0-ATT-13B`. It changes only
checkout-external workspace-parent admission and its focused review evidence.
It does not execute an Attempt, invoke a runtime, issue or consume an Effect
Lease, publish evidence, merge, promote, or change the active gate.

## Finding

The parent packet created `workspace_parent` with `mkdir()` before checking
whether that path overlapped the primary checkout or the selected source-tree
CAS. A refused path such as `<primary>/new-workspaces` therefore mutated the
primary checkout before the coordinator raised its disjointness error.

That ordering violates the Gate-0 invariant that Attempt preparation must not
mutate the primary checkout, including on malformed or hostile input.

## Correction

The coordinator now:

1. refuses an existing or broken leaf symlink;
2. resolves the prospective path without creating it, including existing
   symlinked parent components;
3. checks bidirectional disjointness against the primary checkout and selected
   CAS before any filesystem mutation;
4. creates the parent only after that preflight;
5. re-resolves the created directory and repeats the full topology check before
   retaining workspace authority.

Creation failures are normalized to `AttemptWorkspaceError`. The implementation
continues to retain the exact selected `SourceTreeStore` and canonical
`AttemptLedger`; it creates no new state or artifact authority.

## Adversarial specification

Focused tests require that:

- an absent nested workspace under the primary checkout is refused without
  creating any path;
- an absent nested workspace under the CAS is refused without creating any
  path;
- a symlinked parent component cannot redirect creation into the primary
  checkout;
- an existing file is not replaced or reinterpreted as a directory;
- source ordering contains one non-mutating preflight before `mkdir()` and one
  post-create recheck.

The bounded mutation runner removes each topology check independently. Both
mutants must be killed after a green focused baseline and the production source
must be restored byte-for-byte.

## Remaining boundary

The separate lifecycle-time authority finding remains open on the parent line:
start and completion evidence are still caller-timestamped. No runtime/lease
execution packet may treat this workspace correction as resolving that issue.

GitHub Actions issue #67 may prevent hosted jobs from reaching Step 1. A
zero-step run is infrastructure evidence only and is neither green nor a product
failure.

Iron Plan: **ALIGNED BY SCOPE; EXACT-HEAD EXECUTION REQUIRED**  
Iron Gate: **0**  
Promotion: **not requested**
