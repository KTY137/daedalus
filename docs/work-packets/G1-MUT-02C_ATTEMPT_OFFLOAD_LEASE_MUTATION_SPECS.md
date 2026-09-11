# G1-MUT-02C - Attempt/offload/lease mutation spec migration

## Frozen packet metadata

- Packet ID: G1-MUT-02C
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: af5b9f09fd80b8be86ecb4859f6c13e850a8bc76
- Dependencies: G1-MUT-01, G1-MUT-02B, G1-HIER-04B, G1-WP-INDEX-01
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

The repository-write Effect-Lease mutation campaign delegates from its stable
historical script path to the single `tools.mutation_score --spec` authority.
Its repository-confined JSON spec preserves all 13 exact source anchors and
replacements, the exact two-file baseline, all per-mutant selections, the
180-second timeout, survivor classification, source restoration and the
historical mutant-timeout text/exit contract.

The requested tracked scope contains eight runners whose name or declared
target has the exact `attempt`, `offload` or `lease` token. Seven remain
byte-identical to the base revision because their behavior is not honestly
representable by the current declarative contract. The substring in `release`
does not make a release runner part of the Lease family.

## Scope

The migrated runner is:

| Historical runner | Spec | Jobs / mutants | Baseline | Timeout |
|---|---|---:|---:|---:|
| `run_repository_write_effect_lease_mutations.py` | `repository-write-effect-lease.json` | 1 / 13 | 2 exact files | 180 s |

The seven unchanged runners and exact blockers are:

| Runner | Mutants | Blocking legacy behavior |
|---|---:|---|
| `run_attempt_durability_admission_mutations.py` | 3 | no subprocess timeout |
| `run_attempt_effect_inventory_mutations.py` | 2 | no subprocess timeout |
| `run_attempt_event_time_window_mutations.py` | 3 | no subprocess timeout |
| `run_attempt_workspace_root_authority_mutations.py` | 4 | no subprocess timeout |
| `run_isolated_attempt_mutations.py` | 22 | no subprocess timeout and five targets |
| `run_offload_lease_dominance_mutations.py` | 4 | no subprocess timeout, two targets and a line-ending-aware writer |
| `run_write_evidence_production_mutations.py` | 30 declared | HIER-04B removed anchor 29; its failed restore also changes `offload_lease.py` bytes on Windows |

The last runner is in scope because its declared `KERNEL` target is
`daedalus/kernel/offload_lease.py`, even though its filename lacks those tokens.
Its legacy run reaches mutation 29,
`measure-containment-over-the-default-manager`, then refuses because the
historical two-line anchor occurs zero times after G1-HIER-04B. The `finally`
path rewrites the target through normalized text and changed the measured Git
blob from `9a058cc8437addff16122299997c1fede306c5db` to
`bc1fbf396877bd8376e087029e3d33c8e15bd282` on Windows. The isolated worktree
was restored byte-for-byte from the known clean parent immediately after this
measurement. Treating the first 28 non-survivals as a complete 30-mutant score
would be false evidence, so this packet leaves the runner untouched.

No production module, offload/attempt contract, historical evidence, Registry
row, generated artifact or persistent format changes. The global
`docs/work-packets/index.json` is intentionally not regenerated in this packet
branch; the integration owner will update it once after coordinated packet
integration.

## Contracts and behavior

- `repository-write-effect-lease.json` is schema version 1, carries this
  Packet ID, stays repository-confined and resolves each source anchor exactly
  once.
- The job baseline remains exactly
  `test_repository_write_effect_lease.py` plus its review file, in the legacy
  order. It is not widened to the two files used only by four individual
  mutants.
- `mutant_test_files` is a strict per-job allowlist for per-mutant selections
  outside the baseline. Omission retains the old fail-closed loader rule; a
  scalar, missing file, path escape or unlisted selection is refused.
- The allowlist grants no default execution. Each of the four external
  selections remains attached only to its original mutation.
- All 13 mutants retain their exact order, anchors, replacements and selected
  pytest node IDs. Timeout remains 180 seconds for baseline and mutants.
- The existing `legacy-timeout-exit-1` policy retains
  `timed-out mutations: <ids>` and exit 1 for mutant-only timeouts. Baseline
  failure/timeout, malformed anchors and mixed inconclusive results remain
  exit 2; survivors remain named and exit 1.
- The historical wrapper contains no source-write, temporary-tree or
  subprocess logic. It delegates only to the canonical spec runner.
- The canonical runner mutates disposable sandboxes and restores each target;
  both live shadows leave the authoritative source blob byte-identical.
- Effect Registry IDs, targets, effects, wiring, anchors and digest remain
  unchanged. No provider, network or EDA path is exercised.

## Acceptance matrix

| Claim/refusal | Evidence | Result |
|---|---|---|
| Exact family boundary | tracked runner and target audit | 1 migrated + 7 unchanged = 8 |
| Unchanged blockers | seven frozen byte digests | all unchanged from base |
| HIER-04B drift retained | old anchor count plus failed legacy run | zero anchors; no partial score claimed |
| Strict declarative input | loader and read-only `--list` | 13 unique mutants in one job |
| Baseline remains narrow | job contract | 2 baseline files; 2 explicit mutant-only files |
| Frozen legacy projection | semantic job digest | target, tests, anchors, replacements and timeout unchanged |
| Thin historical path | wrapper AST audit | no own writes or subprocess |
| Legacy shape coverage | canonical fake-runner sandbox | exact selections at 180 s; source unchanged |
| Negative allowlist behavior | synthetic malformed/unlisted tests | fail-closed; default unchanged |
| Legacy live baseline | CPython 3.13.5 old Effect-Lease runner | 13 killed, exit 0 |
| Canonical live shadow 1 | CPython 3.13.5 new wrapper | 13 caught, 0 survived/NA/inconclusive |
| Canonical live shadow 2 | independent repeat | 13 caught, 0 survived/NA/inconclusive |
| Python compatibility | focused suites on CPython 3.13.5 and 3.10.11 | 81 passed, 29 subtests on each |
| Source restoration | before/after Git blob | `b49b58094485628e165cc88dee07b6fa8057fd6b` unchanged |
| Effect stability | before/after Registry digest | unchanged |
| External-effect budget | fixtures, fake runners and AST audit | no provider, network or EDA call |

## Migration and rollback

Rollback restores `run_repository_write_effect_lease_mutations.py`, removes its
JSON spec, focused contract test and this packet, and removes the strict
`mutant_test_files` option plus its scorer tests. Existing specs require no
migration because omission preserves the previous requirement that every
per-mutant test file also appear in its job baseline.

No SQLite database, ledger, CAS locator, source artifact, historical `runs/`
evidence, Effect Lease, Gate report, Registry row or release artifact is
migrated.

The six unbounded runners become eligible only if a future common schema can
represent unbounded execution without silently imposing a timeout. The
write-evidence production runner additionally needs a separately reviewed
current semantic mutant for the HIER-04B port shape and a byte-preserving
multi-target restore contract. This packet neither invents that mutant nor
normalizes its retained failed evidence.

## Evidence expected failures and review

The migrated campaign reports 13 caught, 0 survived, 0 not applicable and
0 inconclusive in both complete canonical shadows. There is no retained
survivor in this campaign.

The write-evidence production legacy run is an expected non-green baseline,
not a mutation score: it exits with
`RuntimeError: mutation measure-containment-over-the-default-manager expected one source anchor, found 0`.
The other six unchanged runners were not executed and receive no new survivor
claim; their source bytes and historical evidence remain intact.

The direct post-index artifact validation for this primary must pass. The
global Work Packet index check remains expected non-green on inherited packet
metadata and is not regenerated here.

The read-only code-ontology preflight used repository label `g1-mut-02c`, no
snapshot, no workspace and observed static evidence only. It wrote no files,
executed no target code, made no direct network request and used no LLM
enrichment. It saw 1,420 Python files, excluded three directories and 29
sensitive names, and reports partial Python coverage for calls, decorators,
declarations, imports, inheritance and pipeline roles. Runtime dispatch and
runtime imports are unsupported; dynamic imports, descriptor dispatch,
generated code, monkeypatching and runtime metaprogramming remain outside
static proof. RDF/Turtle is portable but store extensions require mapping;
static correlation and change proximity do not establish causation.

Independent review must confirm the 1/7 migration boundary, exact two-file
baseline, narrow external-test allowlist, timeout/exit behavior, both full
shadows, unchanged source and Registry digests, retained HIER-04B failure and
absence of production/offload/attempt changes.

Iron Plan: **ALIGNED**
Iron Gate: **1**
Automatic merge or promotion: **forbidden**
