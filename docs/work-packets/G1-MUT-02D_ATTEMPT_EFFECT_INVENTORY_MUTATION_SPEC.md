# G1-MUT-02D - Attempt effect-inventory mutation spec migration

## Frozen packet metadata

- Packet ID: G1-MUT-02D
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: aa19b663c8abc285a63dbbad16cdfb5be9dd7bf1
- Dependencies: G1-MUT-01, G1-MUT-02C, G1-HIER-03D, G1-WP-INDEX-01
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

The smallest remaining Attempt/Offload/Lease mutation campaign now delegates
from its stable historical script path to the single
`tools.mutation_score --spec` authority. The repository-confined spec retains
the two exact source anchors and replacements, the exact two-file baseline,
mutation order, unbounded subprocess execution and exit classification of
`run_attempt_effect_inventory_mutations.py`.

The common runner gains one strictly opt-in per-job timeout policy. Existing
specs remain `bounded`, retain their configured or default finite deadline and
retain their existing selection and exit behavior. Only a job declaring
`legacy-unbounded` may omit the subprocess deadline; pairing that policy with
`timeout_s` is refused as an ambiguous contract.

## Scope

The migrated runner is:

| Historical runner | Spec | Jobs / mutants | Baseline | Timeout |
|---|---|---:|---:|---:|
| `run_attempt_effect_inventory_mutations.py` | `attempt-effect-inventory.json` | 1 / 2 | 2 exact files | legacy unbounded |

It is the smallest of the seven runners retained by G1-MUT-02C: two mutants,
one target and two baseline files, compared with 3, 3, 4, 22, 4 and 30
declared mutants in the other campaigns. Its base SHA-256 is
`f9a8d82984e18507ec7eff8df36ac5f866344269b5e4631fb564edea3c854b35`.

The six unchanged runners and exact blockers are:

| Runner | Mutants | Blocking legacy behavior |
|---|---:|---|
| `run_attempt_durability_admission_mutations.py` | 3 | unbounded; larger next candidate |
| `run_attempt_event_time_window_mutations.py` | 3 | unbounded; larger next candidate |
| `run_attempt_workspace_root_authority_mutations.py` | 4 | unbounded; larger next candidate |
| `run_isolated_attempt_mutations.py` | 22 | unbounded and five targets |
| `run_offload_lease_dominance_mutations.py` | 4 | unbounded, two targets and line-ending-aware writer |
| `run_write_evidence_production_mutations.py` | 30 declared | stale HIER-04B anchor and non-byte-restoring Windows writer |

No production module, plan, amendment, global Work Packet index, historical
`runs/` evidence, generated `dist/` artifact, Registry row or persistent format
changes. The global index is intentionally deferred to coordinated integration.

## Contracts and behavior

- `attempt-effect-inventory.json` is schema version 1, carries this Packet ID,
  stays repository-confined and resolves each source anchor exactly once.
- The target remains `daedalus/spine/effect_boundary.py`; the baseline remains
  the registration test followed by the effect-inventory test.
- The mutants remain, in order,
  `hide-attempt-ledger-from-static-discovery` and
  `remove-canonical-attempt-begin-owner`. Both use the complete job baseline.
- `timeout_policy` defaults to `bounded`. Bounded jobs retain the 900-second
  default, the existing `(0, 3600]` validation and the same subprocess timeout
  argument. Unknown values, non-strings and a finite timeout combined with
  `legacy-unbounded` fail closed.
- `legacy-unbounded` maps to `timeout_s is None` and causes the pytest adapter
  to omit the subprocess deadline. It is not a timeout-as-kill policy and does
  not alter top-level mutant-timeout classification.
- Baseline failure remains exit 2, any named survivor remains exit 1, and two
  caught mutants remain exit 0. The selected test files and mutation order are
  unchanged.
- The historical wrapper contains no subprocess, source-write or sandbox
  implementation. It delegates only to the canonical spec runner.
- The canonical runner mutates disposable sandboxes; both live shadows leave
  the authoritative target Git blob byte-identical.
- Effect Registry IDs, targets, effects, wiring, anchors and digest remain
  unchanged. No provider, network or EDA path is exercised.

## Acceptance matrix

| Claim/refusal | Evidence | Result |
|---|---|---|
| Smallest retained candidate | tracked family audit | 2 mutants; next candidates have at least 3 |
| Strict declarative input | loader and read-only `--list` | 2 unique mutants in one job |
| Exact legacy projection | semantic job digest | `7d84b2853fddaeee9fed16ec0f7ce5e3befe6da625a847102255eb8cba9cef48` |
| Timeout is genuinely unbounded | synthetic subprocess contract | no `timeout` keyword when opted in |
| Existing defaults unchanged | bounded loader and prior-family contracts | finite deadlines retained |
| Thin historical path | wrapper AST audit | no own writes or subprocess |
| Legacy live result | CPython 3.13.5 base runner | 2 killed, exit 0 |
| Canonical live shadow 1 | CPython 3.13.5 wrapper | 2 caught, exit 0 |
| Canonical live shadow 2 | independent repeat | 2 caught, exit 0 |
| Python compatibility | focused suites on CPython 3.13.5 and 3.10.11 | 55 passed, 19 subtests on each |
| Prior spec compatibility | all four mutation-spec contract files | 23 passed, 30 subtests on each Python |
| Source restoration | before/after Git blob | `65b7c8891b5fab22f5e1bbb993e36e3b63292db0` unchanged |
| Effect stability | before/after Registry digest | unchanged |
| Remaining inventory | six frozen script SHA-256 values | byte-identical to base |
| External-effect budget | fixtures, fake runners and AST audit | no provider, network or EDA call |

## Migration and rollback

Rollback restores the base version of
`run_attempt_effect_inventory_mutations.py`, removes its JSON spec, focused
contract test and this packet, and removes the opt-in job timeout policy plus
its scorer tests. Existing declarative specs need no data migration because
omission selects the previous bounded behavior.

No SQLite database, ledger, CAS locator, source artifact, historical evidence,
Effect Lease, Gate report, Registry row or release artifact is migrated. The
old script path remains a compatibility wrapper until a separate caller audit
proves it removable.

The other three unbounded single-target Attempt runners remain eligible for a
later packet. The isolated-attempt and offload-dominance campaigns still need
their multi-target and writer behavior audited independently.

## Evidence expected failures and review

The legacy run and both complete canonical shadows report the same two mutant
outcomes: both caught/killed, no survivor, no not-applicable row and no
inconclusive row. There is no retained survivor in this campaign.

The `write_evidence_production` blocker is deliberately not hidden. Its
`measure-containment-over-the-default-manager` anchor still occurs zero times
after HIER-04B, and its legacy Windows restore path can normalize target bytes.
Its runner remains byte-identical at
`2ec05e6f868741c6fdfa63fbc5c9bc51632a14f8e02bd2f755ad20942936e657`;
this packet claims no partial score for its first 28 mutations.

The direct packet tests pass. The global Work Packet index is intentionally not
regenerated in this individual branch, so index drift for G1-MUT-02D remains an
expected integration-owner action rather than hidden green evidence. Its
read-only check currently stops first on the inherited G1-HERMES-01 primary,
which lacks three post-index contract sections; this packet does not rewrite
that unrelated artifact.

The read-only code-ontology preflight used repository label `g1-mut-02d`, no
snapshot and no workspace. It observed static evidence only, wrote no files,
executed no target code, made no direct network request and used no LLM
enrichment. It saw 1,426 Python files, excluded three directories and 29
sensitive names, and reports partial Python coverage for calls, decorators,
declarations, imports, inheritance and pipeline roles. Runtime dispatch and
runtime imports are unsupported; dynamic imports, descriptor dispatch,
generated code, monkeypatching and runtime metaprogramming remain outside
static proof. No relationship span was materialized. RDF/Turtle is portable
but store extensions require mapping; static correlation and change proximity
do not establish causation.

Independent review must confirm the one-of-seven candidate choice, exact
anchors, exact two-file selection, strict timeout opt-in, both live shadows,
unchanged source and Registry digests, six retained runner hashes and explicit
write-evidence refusal.

Iron Plan: **ALIGNED**
Iron Gate: **1**
Automatic merge or promotion: **forbidden**
