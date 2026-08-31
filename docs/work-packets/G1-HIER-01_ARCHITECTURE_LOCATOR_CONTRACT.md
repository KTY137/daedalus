# Work Packet: G1-HIER-01 Architecture and locator contract

Packet ID: `G1-HIER-01`
Artifact role: `primary`
Status: builder-verified; system CI blocked by frozen-parent defects; independent review pending
Classification: `ALIGNED`
Active gate: Gate 1 - Renovation and owner-directed Genesis
Owner: `repository owner`
Master-plan authority: `docs/IKARUS_ARIADNE_MASTER_PLAN.md` Revision 11
Master-plan SHA-256: `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
Base revision: `151b8d180e321cfba48b4c7d62f9be56579d52a5`
Dependencies: frozen G1 dirty-tree checkpoint; no dependent hierarchy packet

## Primary acceptance claim

Every tracked direct-syntax Python import from the current kernel, spine, and
runtime responsibility layers is measured deterministically. New reversed
dependencies fail while the 23 exact baseline edges remain visible debt rather
than being hidden or represented as approved architecture.

This packet adds a static delivery check and registries only. It moves no code,
changes no runtime behavior, and creates no event, artifact, policy, evaluator,
or promotion authority.

## Scope

Allowed:

- `tools/architecture_boundaries.py` and the existing registered Gate-test
  profile;
- `tools/run_gate_checks.py` and its focused profile assertion;
- `docs/architecture/import-boundaries.json`;
- `docs/architecture/shim-registry.json`;
- this Work Packet and focused tests;
- authority headers only in `docs/STATUS.md` and
  `docs/FOURFOLD_V2_EXECUTION_PLAN.md`.

Forbidden:

- Master Plan, amendment chain, Gesamtplan, policy, effect registry, runtime
  admission, persistent stores, historical runs, evidence, or generated assets;
- moving modules, changing import targets, blessing baseline debt, or granting a
  shim a permanent lifetime;
- filesystem walks, untracked files, dynamic imports, target-code execution, or
  live runtime claims as input to this static contract.

## Contracts and behavior

The source census is pinned to:

```text
git ls-files -z -- daedalus
```

Only returned `.py` paths are decoded as strict UTF-8 and parsed with the Python
AST. The rules reject:

1. `daedalus.kernel -> daedalus.{chip_design,eval,gates,kairos,providers,runtimes}`;
2. `daedalus.runtimes -> daedalus.gates`;
3. `daedalus.spine ->` declared product, orchestration, evaluator, provider,
   runtime, Twin, integration, or interface layers.

At the frozen base, the source set contains 354 tracked Python files and 23
forbidden edges: 14 kernel, four runtime, and five spine edges. Each baseline
entry binds rule, normalized path, source module, target module, line, column,
and import kind. A removed edge is reported as resolved and remains green; a
new or relocated edge is unallowlisted and fails.

The separate shim registry initially records nine known facades with owner,
tracked target modules, kind, and evidence required before removal. Registry
metadata must bind the same plan revision, gate, and baseline revision as the
import contract; every facade and target locator must exist in the tracked
Python census.

## Acceptance matrix

| Case | Evidence | Required result |
| --- | --- | --- |
| Frozen tracked tree | focused Gate-profile test | 354 tracked Python files; 23 current/allowlisted; zero new/resolved; pass |
| Untracked forbidden import | focused test | ignored because it is outside the authoritative tracked source set |
| Newly tracked forbidden import | focused test | reported as new; check fails |
| Exact reviewed debt | focused test | allowlisted and visible; check passes |
| Debt removal | focused test | reported as resolved; check passes |
| Debt relocation | focused test | old edge resolved plus new edge; check fails |
| Relative import bypass | focused test | resolved to the forbidden Daedalus target; check fails |
| Detached or missing shim metadata/locator | focused test | fail closed before an architecture verdict |

## Migration and rollback

Later hierarchy packets delete baseline rows only after removing the
corresponding edge. They must never broaden a target prefix or move an edge and
refresh the baseline in the same behavioral packet without explicit review.
Rollback is deletion of this packet's checker, registries, test, and derived
header edits; no persistent data migration exists.

Expected limitations are explicit: AST imports are `direct_syntax` evidence
with runtime status `runtime_unknown`. Dynamic imports, generated code,
descriptor dispatch, monkey-patching, and runtime metaprogramming are not
observed. Static proximity does not establish execution or causation.

## Evidence expected failures and review

Builder commands:

```text
C:\Users\Administrator\daedalus\.venv\Scripts\python.exe -m pytest tests\test_architecture_boundaries.py -q
```

Builder result: the boundary check passed with 354/23/23/0 measured counts,
the focused suite passed 7 tests, and the profile/effect-inventory integration
suite passed 9 tests. The canonical Effect Registry remained
byte-unchanged with digest
`ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`.
System CI remains blocked by two independently reproduced frozen-parent
defects: the G1 profile cannot collect because `daedalus.kernel.__init__`
imports absent `daedalus.kernel.campaigns`, and the documentation-reference
suite retains three failures because the parent names the untracked
`vscode-agent-env/dist/daedalus-vscode.vsix` from
`packaging/openvscode/README.md`. G1-HIER-01 neither created nor repairs those
separate packets.

Independent review must answer:

- Are any forbidden target prefixes overly broad or missing a current outer
  layer?
- Does every baseline row name an actual direct import at the frozen base?
- Can an untracked, relative, malformed, or relocated import evade the refusal?
- Does any shim lack a concrete owner or evidence-based retirement criterion?

No automatic merge or promotion is authorized by a green result.
