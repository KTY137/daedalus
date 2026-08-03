# G0-ATT-13B4 — Pre-provisioned Attempt workspace-root authority

## Scope

This correction packet is stacked directly on the current persisted isolated
Attempt lifecycle. It changes only admission and revalidation of the external
workspace root and focused test provisioning. It does not execute a runtime,
issue or consume an Effect Lease, publish evidence, merge, promote, or change
the active gate.

## Residual finding

The parent packet moved topology checks before `mkdir()` and repeated them after
creation. That prevents ordinary malformed inputs from creating a nested path
inside the primary checkout or source-tree CAS. It does not close a concurrent
ancestor-replacement race: an existing ancestor may be redirected after the
prospective check but before or during `Path.mkdir(parents=True)`. The requested
child can then be created inside a protected tree before the post-create check
notices the redirect.

A refusal after protected mutation is not sufficient for Gate 0.

## Correction

Workspace-root provisioning becomes an explicit deployment/runtime
responsibility. `IsolatedAttemptCoordinator` never creates a caller-selected
root. It requires an existing external directory, verifies prospective and
resolved disjointness from the primary checkout and selected CAS, retains the
resolved path identity, and revalidates that identity:

1. before committing the lifecycle start; and
2. immediately before source-tree materialization.

A missing root, file, leaf symlink, redirected parent component, protected-tree
overlap, disappeared directory, or changed identity fails closed. Existing
compatibility timestamp keywords remain discarded by the trusted lifecycle
clock and are unrelated to this packet.

The legacy lifecycle fixtures now model the operator boundary with an explicit
test-only provisioning fixture. Tests that exercise absent roots use different
paths and remain unmasked.

## Adversarial specification

Focused tests require that:

- an absent external root is refused without creation;
- absent primary- and CAS-nested roots leave protected trees path-identical;
- a parent-component symlink cannot redirect admission into the primary tree;
- replacement after admission is refused before use;
- an existing file remains unchanged; and
- production source contains no workspace-root `mkdir` and revalidates twice
  before materialization.

The bounded mutation runner attacks root creation, primary-overlap admission,
identity-change acceptance, and removal of the final pre-materialization
revalidation. Every mutant must be killed after a green focused baseline and
the production file must be restored byte-for-byte.

## Remaining boundary

This is a logical filesystem admission boundary, not the later OS sandbox.
An actor with arbitrary host-level filesystem mutation rights remains outside
this packet's trust model. Runtime execution must still use the Docker/platform
sandbox, Runtime Manifest, current Conformance Receipt and persisted Effect
Lease required by later Gate-0 packets.

GitHub Actions issue #67 may prevent hosted jobs from reaching Step 1. A
zero-step run is infrastructure evidence only and is neither green nor a
product failure.

Iron Plan: **ALIGNED BY SCOPE; EXACT-HEAD EXECUTION REQUIRED**  
Iron Gate: **0**  
Promotion: **not requested**
