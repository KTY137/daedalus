# G1-EDA-02 - Supported-interpreter lease import companion

Packet ID: `G1-EDA-02`
Status: implemented companion; deterministic review evidence recorded
Classification: `ALIGNED`
Owner: repository owner
Active gate: Gate 1 - renovation ignition slice
Base branch: `main`
Exact base revision: `2a2f7d8748b0fb62fb72b53d1bac6bcd264499fb`
Dependencies: the G1-EDA-01 project-aware live surface and the canonical
registry/effect-lease contracts present at the exact base revision
Promotion: not requested

## Primary acceptance claim

The existing canonical effect-lease modules import on every supported CPython
minor while retaining the same immutable central registry as their default,
and the root README directs EDA users only to the project-aware admitted live
surface. This is a supported-interpreter usability companion to G1-EDA-01. It
does not change authority, registry contents, lease behavior, EDA execution,
policy, storage, schemas, or promotion.

## Frozen scope

The only production/documentation edits covered by this packet are:

- `daedalus/kernel/authorization.py`: construct the existing
  `NonRuntimeEffectAuthorization.registry` default through `default_factory`;
- `daedalus/kernel/effect_replay.py`: construct the existing
  `PersistedEffectLeaseSubject.registry` default through `default_factory`;
- `daedalus/kernel/runtime_effects.py`: construct the existing
  `RuntimeBoundEffectAuthorization.registry` default through `default_factory`;
- `README.md`: replace stale raw `--live` guidance with the admitted
  project-aware `daedalus-chip run` guidance; and
- this Work Packet.

All paths not listed above are forbidden. In particular this packet may not
edit `daedalus/chip_design/**`, tests, dependency metadata, lock files, policy,
the master plan, its amendment chain, active instructions, evidence stores, or
generated EDA projects and outputs.

## Behavior and compatibility contract

The three dataclass fields still expose `REGISTRY_BY_ID` when callers omit an
explicit registry. Only dataclass default construction changes from a direct
`MappingProxyType` value to a zero-argument factory returning that same object.
Explicit registry injection, verification, refusal, replay, and runtime-trust
semantics remain unchanged. No registry row, entrypoint, capability, event,
receipt, schema, or persisted representation changes.

The README correction is descriptive only. It does not grant authority: raw
`lint --live` and `tcl --live` remain refused, and admitted project execution
still requires G1-EDA-01's canonical lease, policy, kill-switch, containment,
and confirmation checks.

No data migration is required. Supported callers retain the same constructor
signatures and runtime default identity.

## Deterministic acceptance and evidence

1. CPython 3.10, 3.11, 3.12, and 3.13 compile and import all three touched
   kernel modules without a dataclass mutable-default exception.
2. Dataclass field inspection shows a callable `default_factory` and no direct
   default for each of the three `registry` fields; invoking each factory
   returns the canonical `REGISTRY_BY_ID` object by identity.
3. Existing effect-lease, replay, runtime-bound authorization, chip boundary,
   CLI, and repository-write inventory tests stay green. Existing malformed,
   stale, mismatched, missing-registry-row, replay, revocation, and policy
   refusal cases remain the fault-injection evidence; this packet adds no
   alternate permissive path.
4. `tools/docs_reference_check.py` accepts the README link and reports no
   current or authority-reference errors.
5. A scoped diff contains only the four frozen production/documentation paths
   above plus this packet; no master-plan or amendment-chain diff is present.

Builder evidence already measured on the shared snapshot:

- the exact 13-file G1-EDA-01 matrix passed under CPython 3.10.11 with
  `330 passed, 5 skipped` in 100.48 seconds;
- independent CPython 3.13 execution passed with `329 passed, 5 skipped`;
- compile/import checks passed under CPython 3.10.11, 3.11.15, 3.12.13, and
  3.13.5; and
- fresh no-index/no-dependency wheel installs under CPython 3.10.11 and
  3.11.15 imported the isolated package and returned exit 0 for
  `daedalus-chip --help`.

These results are compatibility and regression evidence only. They are not an
isolated commit, a live Vivado/Vitis run, FPGA signoff, promotion, or a Gate-1
closure claim.

## Budget, expected failures, and stop rule

Change budget is exactly the five paths in the frozen scope. Verification is
local, read-only outside those files, uses no network/provider/EDA process, and
has a ten-minute wall-time budget. The pre-fix CPython 3.11 import failure
(`ValueError` for a mutable `mappingproxy` dataclass default) is retained as
the motivating negative baseline. An unavailable supported interpreter is
reported as `not_run`, never converted to a pass.

Stop immediately for a new Work Packet if a fix requires a registry-content
change, constructor/schema change, new test or dependency file, policy edit,
new effectful entrypoint, live EDA execution, or any path outside the frozen
scope. Any import, identity, refusal, docs-reference, or scoped-diff failure
keeps this packet open; it does not justify widening scope.

## Rollback and review questions

Rollback is mechanical: restore the direct registry defaults in the three
kernel files, restore the prior README paragraph, and remove this packet. No
ledger, schema, artifact, or data rollback is required.

Independent review should answer:

1. Does every factory return the existing canonical registry object without
   copying or mutating it?
2. Did any authority, refusal, replay, runtime-trust, or persisted contract
   change beyond supported-interpreter dataclass construction?
3. Does the README name only the admitted G1-EDA-01 live surface without
   presenting documentation as authorization?
4. Is the diff confined exactly to the frozen paths, with no silent plan,
   policy, test, or dependency expansion?

Iron Plan: **ALIGNED**
Iron Gate: **1**
Evidence: **supported-interpreter import/identity checks, affected regression
matrix, docs-reference check, and exact scoped-diff review; no promotion
requested**
