# G1-MUT-02B - Gate/promotion mutation spec migration

## Frozen packet metadata

- Packet ID: G1-MUT-02B
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 77bcce1973b325bc2140822fb7526bd9f2e98d03
- Dependencies: G1-MUT-01, G1-MUT-02A, G1-WP-INDEX-01
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

The GateReport-v3 mutation campaign delegates from its stable historical path
to the single `tools.mutation_score --spec` authority. Its repository-confined
JSON spec preserves all 13 exact mutants, the same eight baseline test files,
the complete per-mutant selection, the 300-second subprocess timeout and the
historical mutant-timeout text/exit contract.

The requested tracked family contains nine runners. Eight remain byte-identical
to the base revision because their unbounded timeout behavior cannot be
represented by the finite declarative schema without semantic drift. This is a
bounded migration, not a claim that the entire family is declarative.

## Scope

The migrated runner is:

| Historical runner | Spec | Jobs / mutants | Tests | Timeout |
|---|---|---:|---:|---:|
| `run_gate_report_v3_mutations.py` | `gate-report-v3.json` | 1 / 13 | 8 exact files | 300 s |

The eight unchanged runners and precise blockers are:

| Runner | Mutants | Blocking legacy behavior |
|---|---:|---|
| `run_gate_report_writer_inventory_mutations.py` | 10 | no subprocess timeout |
| `run_gate_baseline_v2_mutations.py` | 8 | no subprocess timeout |
| `run_gate0_release_writer_inventory_mutations.py` | 7 | no subprocess timeout |
| `run_promotion_receipt_authority_mutations.py` | 6 | no timeout and one mutant creates/removes a competing module |
| `run_promotion_execution_reader_mutations.py` | 12 | no subprocess timeout |
| `run_promotion_execution_mutations.py` | 11 | no subprocess timeout |
| `run_persisted_promotion_authorization_mutations.py` | 3 | no subprocess timeout |
| `run_live_promotion_seam_mutations.py` | 11 | no timeout and one mutant requires two replacements |

The eight immutable runner byte digests are frozen in the focused contract
test. Several also stop at the first survivor while the canonical scorer
continues through the population. No timeout, survivor-collection or mutation
shape is normalized by convenience.

No offload/attempt runner, production module, historical evidence, test
selection, Registry row, generated artifact or persistent format is changed.
The prior MUT-02A inventory contract now selects specs by its own Packet ID
instead of claiming global ownership of every non-repository-tree spec; its
5/19 runner boundary and frozen projections remain unchanged.
The global `docs/work-packets/index.json` is intentionally not regenerated in
this packet branch; the integration owner will update it once after coordinated
packet integration.

## Contracts and behavior

- `gate-report-v3.json` is schema version 1, carries this Packet ID, stays
  repository-confined and resolves every source anchor exactly once.
- The job retains the exact eight legacy pytest files, their order, all 13
  find/replace mutants and timeout 300. No mutant receives a narrowed or
  widened selection.
- `mutant_timeout_policy` is an optional, strictly validated per-spec enum.
  Existing specs omit it and retain canonical `INCONCLUSIVE`/exit 2 behavior.
- The explicit value `legacy-timeout-exit-1` maps only pure mutant timeouts
  after a green baseline to the historical
  `timed-out mutations: <ids>` line and exit 1. Timeout remains separately
  identified and is never credited as a kill.
- A baseline timeout/red baseline, missing or non-unique anchor,
  NOT_APPLICABLE mutation, runner error or mixed INCONCLUSIVE result remains
  exit 2 even for an opted-in spec.
- The historical wrapper imports only `sys`, `pathlib` and the canonical
  runner. It contains no source-write, temporary-tree or subprocess logic.
- The canonical sandbox keeps the subject checkout byte-identical. No live
  provider, network or EDA path is exercised.
- Effect Registry IDs, targets, effects, wiring, anchors and digest remain
  unchanged.

## Acceptance matrix

| Claim/refusal | Evidence | Result |
|---|---|---|
| Exact family boundary | tracked paths plus focused contract | 1 migrated + 8 unchanged = 9 |
| Unchanged blockers | eight frozen byte digests | all unchanged from base |
| Strict declarative input | loader and read-only `--list` | 13 unique mutants in one job |
| Frozen legacy projection | semantic job digest | module/tests/anchors/replacements/timeout unchanged |
| Thin historical path | wrapper AST audit | no own writes or subprocess |
| Legacy shape coverage | canonical fake-runner sandbox shadow | 13 selections at 300 s; source unchanged |
| Timeout parity | synthetic mutant timeout | exact legacy line and exit 1 |
| Default safety | synthetic default/malformed policy tests | existing specs exit 2; unknown policy refused |
| Cross-packet coexistence | MUT-02A contract rerun | its own five specs remain exact without rejecting MUT-02B |
| Legacy live baseline | CPython 3.13.5 old runner | 13 caught, 0 survived |
| Canonical live shadow | CPython 3.13.5 new wrapper | 13 caught, 0 survived, 0 inconclusive |
| Python compatibility | focused suites on CPython 3.13.5 and 3.10.11 | 47 passed, 20 subtests on each |
| Effect stability | before/after Registry digest | unchanged |
| External-effect budget | selected fixtures and AST audit | no provider, network or EDA call |

## Migration and rollback

Rollback restores `run_gate_report_v3_mutations.py`, removes its JSON spec,
focused contract test and this packet, and removes the opt-in timeout policy
plus its scorer tests. Existing declarative specs require no migration because
the omitted policy continues to mean canonical INCONCLUSIVE/exit 2.

No SQLite database, ledger, CAS locator, source artifact, historical `runs/`
evidence, promotion receipt, Gate report, Registry row or release artifact is
migrated.

The eight unchanged runners become eligible only after the common schema can
express unbounded execution and, where applicable, file creation or an atomic
multi-replacement mutant without changing classification or survivor order.

## Evidence expected failures and review

The measured legacy campaign and canonical shadow each report exactly
13 caught, 0 survived, 0 not applicable and 0 timeout/inconclusive. There is no
retained survivor in the migrated runner. The eight unchanged runners were not
executed by this packet and receive no new survivor claim; their source bytes
and historical behavior remain the retained evidence.

The global Work Packet index check remains expected non-green. At this base it
stops first on inherited `G1-HERMES-01`, whose primary lacks the currently
required `scope`, `contracts_and_behavior` and
`evidence_expected_failures_and_review` sections. This packet's direct
post-index artifact validation must pass, while its new primary deliberately
awaits the coordinated index regeneration.

The read-only code-ontology preflight used repository label `g1-mut-02b`,
initialized no snapshot, wrote no files, executed no target/provider code,
made no direct network request and used no LLM enrichment. Its Python adapter
is partial for calls, decorators, declarations, imports, inheritance and
pipeline roles; runtime dispatch/imports, dynamic imports, descriptor dispatch,
generated code, monkeypatching and runtime metaprogramming remain outside
static proof. RDF/Turtle is portable but store extensions require mapping;
static correlation and change proximity do not prove causation.

Independent review must confirm the 1/8 migration boundary, default-policy
compatibility, the narrow timeout-only exit mapping, exact 13-mutant projection,
unchanged source module and Registry digest, and the absence of offload/attempt
or production-code changes.

Iron Plan: **ALIGNED**
Iron Gate: **1**
Automatic merge or promotion: **forbidden**
