# G1-MUT-02A - Provider/runtime mutation spec migration

## Frozen packet metadata

- Packet ID: G1-MUT-02A
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: c68433d1b4835a6159241a425e7b76b657e2865d
- Dependencies: G1-MUT-01, G1-WP-INDEX-01, G1-HIER-01
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

Five tracked provider/runtime mutation runners now delegate from their stable
historical paths to the single `tools.mutation_score --spec` authority. Their
five repository-confined JSON specs preserve 40 exact find/replace mutants,
the same baseline test files, per-mutant test selections and finite timeouts.
The wrappers cannot write source or spawn their own subprocesses.

The tracked-only inventory contains 24 matching provider/runtime runners.
Nineteen remain byte-identical to the base revision because the current
declarative schema cannot reproduce their semantics honestly. This is a
bounded migration, not a claim that every historical runner is declarative.

## Scope

Migrated runners and finite timeout:

| Historical runner | Spec | Jobs / mutants | Timeout |
|---|---|---:|---:|
| `run_provider_invocation_identity_mutations.py` | `provider-invocation-identity.json` | 1 / 9 | 300 s |
| `run_provider_observation_authority_mutations.py` | `provider-observation-authority.json` | 3 / 8 | 300 s |
| `run_provider_observation_persistence_inventory_mutations.py` | `provider-observation-persistence-inventory.json` | 1 / 6 | 300 s |
| `run_provider_target_verification_mutations.py` | `provider-target-verification.json` | 2 / 11 | 360 s |
| `run_runtime_effect_replay_projection_mutations.py` | `runtime-effect-replay-projection.json` | 1 / 6 | 120 s |

The 16 runners with no subprocess timeout remain unchanged. The spec contract
always supplies a finite timeout (default 900 seconds, maximum 3600), so adding
one would change rather than preserve the historical campaign. Runtime clock
authorization also replaces two matching anchors in one mutation, while the
strict declarative runner requires exactly one anchor.

Three finite-timeout runners also remain unchanged because their frozen
anchors have already drifted at this parent:

- broker exact authority expects one authorization guard but finds two;
- executable target's external-Python regex anchor is absent; and
- post-provider unknown recovery lease/idempotency anchors are absent.

No other mutation family, production module, test selection, mutant,
`tools/mutation_score.py`, historical evidence, Registry row or generated
artifact is changed.

The global `docs/work-packets/index.json` is intentionally not regenerated in
this packet branch. The integration owner will regenerate it once after all
packet commits are integrated; until then, the tracked-index check is expected
to report this new primary artifact as drift.

## Contracts and behavior

- Each migrated spec is strict JSON schema version 1, carries this Packet ID,
  stays inside the repository and resolves every source anchor exactly once.
- Multi-target legacy dictionaries become one job per target. Each job retains
  the complete historical baseline selection; each mutant retains its exact
  selected file or pytest node. Repeated per-target baseline execution is
  fail-closed and does not broaden a mutant selection.
- Timeouts remain exactly 120, 300 or 360 seconds as declared by the old
  runner. No unbounded runner is silently assigned the canonical default.
- A red baseline, missing/non-unique anchor, timeout or runner error remains
  nonzero and cannot be credited as a kill. A survivor remains named and exits
  nonzero.
- Compatibility wrappers import only `sys`, `pathlib` and the canonical
  runner. They contain no source-write, temporary-tree or subprocess logic.
- No live provider, network or EDA path is exercised. The selected tests are
  fixture-backed builder evidence.
- Effect Registry IDs, targets, effects, wiring, anchors and digest remain
  unchanged.

## Acceptance matrix

| Claim/refusal | Evidence | Result |
|---|---|---|
| Tracked family inventory | focused contract test | exactly 5 migrated + 19 unchanged = 24 |
| Strict specs and exact anchors | loader plus `--list` for all five specs | 40 mutants load; read-only |
| Frozen legacy projection | semantic job digests in focused test | targets/tests/selections/timeouts unchanged |
| Thin historical paths | wrapper AST audit | no own writes or subprocess |
| Legacy shape coverage | canonical sandbox shadow for each of five forms | all selections/timeouts observed; source unchanged |
| Python compatibility | focused suite on CPython 3.13.5 and 3.10.11 | 5 passed, 10 subtests passed on each |
| Canonical runner regression | `tests/test_mutation_score.py` on CPython 3.13.5 | 34 passed |
| Live mutation evidence | all five wrappers on CPython 3.13.5 | 38 caught, 2 survived, 0 inconclusive |
| Effect stability | before/after Registry digest | unchanged |
| External-effect budget | process/AST audit and selected fixtures | no provider, network or EDA call |

## Migration and rollback

Rollback restores the five historical scripts and removes their five JSON
specs, focused contract test and this packet. No persistent format, SQLite
database, ledger, CAS locator, source artifact, historical `runs/` evidence,
Registry row or release artifact is migrated.

The 19 unchanged runners remain eligible for later packets only when the
canonical schema can express an unbounded timeout/multi-anchor mutation without
semantic drift, or after a separately reviewed amendment to their historical
contract. Anchor drift must not be repaired incidentally in a migration packet.

## Evidence expected failures and review

The live shadows retain two negative findings:

- `ignore-persisted-record-hmac` survives the exact provider-observation
  authority selection: that spec reports 7 caught and 1 survived.
- `accept-source-symlink` survives the exact persistence-inventory selection:
  that spec reports 5 caught and 1 survived.

The other three specs report 26 caught and no survivor. Across all five:
38 caught, 2 survived, 0 not applicable and 0 inconclusive. Both survivor
wrappers correctly exit 1. This packet does not delete, weaken, broaden or
silently bless either mutant; follow-up test hardening belongs to its owning
packet.

No result is claimed for the 19 unchanged runners. In particular, the three
anchor-drift cases are retained as non-green historical controls, not relabeled
as survivors or as successful campaigns.

The global Work Packet index check is expected non-green for two independently
visible reasons. At this base it stops first on inherited `G1-MUT-01`, whose
primary lacks the currently required `scope`, `contracts_and_behavior` and
`evidence_expected_failures_and_review` sections. This packet's direct
post-index artifact validation passes all metadata and six-section checks, but
the new primary is deliberately absent from the branch-local frozen index
pending the coordinated integration regeneration.

The read-only code-ontology preflight used repository label
`g1-mut-02a`, initialized no snapshot, executed no target, provider or
network code and performed no LLM enrichment. Its Python adapter covered
imports, calls, declarations, inheritance, decorators and pipeline roles only
partially; dynamic imports, descriptor dispatch, generated code,
monkeypatching, runtime metaprogramming and runtime dispatch remain outside
static proof. If RDF is later persisted, Turtle is the portable export and
requires the store extension map.

Independent review must confirm the 5/19 boundary, exact job projections,
visible nonzero survivors, unchanged source modules and Registry digest, and
that no unchanged runner was normalized by convenience.

Iron Plan: **ALIGNED**
Iron Gate: **1**
Automatic merge or promotion: **forbidden**
