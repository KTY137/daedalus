# G1-MUT-02F - Attempt event-time declarative mutation spec

- Packet ID: G1-MUT-02F
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: de6ad51984aeaef04587a4af67416cc988ae1da6
- Dependencies: G1-MUT-02E, G1-MUT-02D, G1-MUT-02C, G1-WP-INDEX-01
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

The transport-stable historical
`scripts/run_attempt_event_time_window_mutations.py` campaign is represented
once by the strict declarative
`configs/mutations/attempt-event-time-window.json` contract and executes only
through `tools.mutation_score --spec`. The historical script path remains a
thin compatibility wrapper. The three mutant IDs, exact anchors,
replacements and order retain semantic digest
`9f45fb294da71fd707f08de8b559a9c64f75908e08b584d6cddef4cfa2d93211`;
the five-file test selection, unbounded subprocess policy and process outcome
classes remain frozen.

This is consolidation through the existing canonical mutation runner, not a
new mutation engine. The shared runner and production target are unchanged.
The canonical runner mutates a disposable sandbox, so the authoritative
`attempt_spine_reader.py` is never rewritten and remains byte-identical.

## Scope

In scope:

- add `configs/mutations/attempt-event-time-window.json` with one job and the
  three exact legacy mutants;
- reduce `scripts/run_attempt_event_time_window_mutations.py` to the standard
  `tools.mutation_score` compatibility wrapper;
- migrate the G1-MUT-02E transport contract to strict spec, wrapper,
  unbounded-shadow, exit-class and source-identity checks;
- classify the runner as migrated in the existing Attempt/Offload/Lease
  inventory contract;
- add this Work Packet.

Out of scope and unchanged:

- `tools/mutation_score.py` and every production module;
- the five selected tests and the three mutant anchors or replacements;
- Effect Registry IDs, targets, effects, anchors and digest;
- Master Plan, amendment chain, global Work Packet index, historical `runs/`,
  generated `dist/`, databases, CAS, ledgers and persistent formats;
- all remaining Attempt/Offload/Lease runners, especially the blocked
  `run_write_evidence_production_mutations.py`;
- provider, network, EDA, release, merge or promotion activity.

## Contracts and behavior

- The spec has `schema_version: 1`, packet `G1-MUT-02F`, one target
  `daedalus/kernel/attempt_spine_reader.py` and exactly three mutations.
- The mutation order remains
  `accept-arbitrary-historical-record-time`,
  `accept-record-time-after-event`, then
  `skip-terminal-time-binding`.
- The semantic digest is calculated from the ordered `(id, find, replace)`
  tuples with the same UTF-8 compact-JSON projection used by G1-MUT-02E. It is
  unchanged at `9f45fb294da71fd707f08de8b559a9c64f75908e08b584d6cddef4cfa2d93211`.
- The baseline and every mutant use, in order, the same five Attempt lifecycle
  test files. No per-mutant narrowing or additional selection is introduced.
- `timeout_policy` is explicitly `legacy-unbounded`; `timeout_s` is absent and
  the canonical pytest adapter receives `None`, therefore omitting the
  `subprocess.run` timeout argument.
- Green/no-survivor remains exit 0, any survivor remains exit 1, and a red or
  otherwise inconclusive baseline remains exit 2. The wrapper returns the
  common runner's code without translation.
- The strict loader requires every anchor exactly once after Python's
  line-ending-neutral text read. Missing or ambiguous anchors fail spec
  validation; no fuzzy match, fallback anchor or re-anchoring exists.
- `--list` loads the exact spec without starting the effect boundary and does
  not modify the spec, wrapper or target.
- The wrapper imports no subprocess or file-mutation authority. It forwards
  only the repository root and exact spec path to `mutation_score.main`.
- The retained Gate-0 workflow continues to invoke the historical script path;
  no caller receives a new command or module name.
- Live scoring takes one disposable repository snapshot, runs baseline first,
  restores each sandbox mutant and destroys the sandbox. The authoritative
  target remains Git blob `ac7c379b41963b731e3536f4ac42db332639f109`
  and Windows working-file SHA-256
  `1d887ee2941ca4d0302502c589ef577e6507efb79f6fbe424a7dbfc4d5c79bca`.

## Acceptance matrix

| Claim/refusal | Evidence | Result |
|---|---|---|
| Legacy baseline frozen | pre-edit wrapper, CPython 3.13.5 and 3.10.11 | each killed 3/3, exit 0 |
| Legacy restoration | target blob/SHA before and after each baseline | byte-identical |
| Strict spec load | focused contract and `--list` | 3 mutants in 1 job |
| Mutant identity | ordered semantic digest contract | exact `9f45fb...3211` |
| Test identity | strict tuple contract | exact five files in legacy order |
| No re-anchoring | loader cardinality plus digest contract | all three anchors occur once |
| Unbounded execution | spec and fake canonical shadow | four calls received `None`; no deadline |
| Thin legacy path | wrapper AST and exact-argv contract | no source write or own subprocess |
| Exit classes | wrapper pass-through and common-result contract | exits 0 / 1 / 2 unchanged |
| Canonical live run 1 | CPython 3.13.5 | 3 caught; 0 survivor/N/A/inconclusive; exit 0 |
| Canonical live run 2 | CPython 3.10.11 | 3 caught; 0 survivor/N/A/inconclusive; exit 0 |
| Source restoration | target Git blob/raw SHA before and after live runs | unchanged |
| Python compatibility | focused contracts on 3.13.5 and 3.10.11 | 71 passed, 35 subtests on each |
| Existing mutation contracts | canonical runner and all spec contracts | included in the same green selection |
| Effect stability | live Registry digest | exact and unchanged |
| External-effect budget | local AST/fake shadow/pytest only | no provider, network or EDA call |

## Migration and rollback

Migration is a single authority transfer: the exact mutation data moves from
the historical Python script into the declarative spec, and the retained
historical path delegates to the existing common runner. The inventory moves
that path from transport-prepared to migrated. There is no data migration.

Rollback removes the new spec and this packet, restores the G1-MUT-02E runner
and transport contract, and moves the inventory row back to
transport-prepared. That restores the direct in-place legacy implementation;
it must also retain G1-MUT-02E's line-ending repair and its documented pre-fix
negative evidence. Rollback does not alter production sources, the shared
runner, Registry, databases, CAS, ledgers or historical evidence.

The global Work Packet index is deliberately not regenerated on this packet
branch. Coordinated integration owns one later index refresh after all packet
branches are assembled.

## Evidence expected failures and review

G1-MUT-02E's retained negative evidence remains authoritative: before its
transport repair, the exact legacy Windows runner reached mutant 2 and failed
with `accept-record-time-after-event: expected one mutation site, found 0`
and exit 1 because the target was CRLF and the multiline anchor LF. The target
was restored. G1-MUT-02F neither deletes nor relabels that failure and does not
change any anchor.

On this packet's exact base, the repaired legacy implementation was rerun
before editing on CPython 3.13.5 and 3.10.11. Both runs killed the three
mutants, exited 0, and preserved target blob
`ac7c379b41963b731e3536f4ac42db332639f109`, raw SHA-256
`1d887ee2941ca4d0302502c589ef577e6507efb79f6fbe424a7dbfc4d5c79bca`
and 245 CRLF / 245 LF bytes. The post-migration canonical wrapper then produced
the same 3/3 outcome and exit 0 on each interpreter, with zero survivor,
not-applicable or inconclusive result and the same target identities.

The blocked `run_write_evidence_production_mutations.py` remains byte-identical
and outside scope. The global index's inherited first failure remains the
unrelated G1-HERMES-01 primary missing three post-index sections; this packet
does not conceal that drift or rewrite historical packets.

The read-only Code Ontology Companion preflight used repository label
`g1-mut-02f`, no snapshot and no workspace. It observed 1,442 Python source
files, excluded three directories and 29 sensitive names, wrote no files,
executed no target code, made no direct network request and used no LLM.
Python coverage is partial for calls, decorators, declarations, imports,
inheritance and pipeline roles. Runtime dispatch/imports and dynamic imports,
descriptor dispatch, generated code, monkeypatching and runtime
metaprogramming remain unsupported. No relationship spans were materialized;
RDF 1.1 Turtle is the portable export and store extensions require mapping.
Static correlation and change proximity do not establish causation.

Independent review must verify the exact semantic digest, five-file selection,
unbounded `None` deadline, process exit classes, thin-wrapper AST, both
legacy/canonical live pairs, byte-identical target, unchanged Registry digest,
retained 02E failure and absence of shared-runner/production/plan/index diffs.

Iron Plan: **ALIGNED**
Iron Gate: **1**
Automatic merge or promotion: **forbidden**
