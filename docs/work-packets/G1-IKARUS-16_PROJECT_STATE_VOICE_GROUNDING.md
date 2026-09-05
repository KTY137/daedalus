# G1-IKARUS-16 - Project-state Voice grounding

## Frozen packet metadata

- Packet ID: `G1-IKARUS-16`
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: `61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0`
- Dependencies: G1-IKARUS-14 and G1-UI-08
- Promotion authority: repository owner; no automatic merge, promotion,
  release, action, or Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`

## Primary acceptance claim

An answer-shaped question about the selected project's current state reaches
the selected text-only Voice with a bounded, visibly sourced, read-only
evidence snapshot instead of context-free dialogue. The snapshot reuses the
canonical project/status/dashboard/picker owners; it creates no store, route,
event, workflow state, mutation, or new authority. Explicit mutation language
still reaches only the confirmation-gated Hand.

## Baseline reproduced

At the frozen base plus G1-UI-08's Voice-classifier repair, the exact live
prompt `Schau dir den aktuellen Projektzustand an. Nenne die drei wichtigsten
nächsten Schritte und erkläre kurz, warum.` classified as `chat`, but
`_project_context` returned `_EMPTY_CTX` because the prompt contains no
file-shaped token. The selected provider therefore received only generic
dialogue. Measured against live project `pnp_app`: zero project-context bytes.

After the change, the same project produced a 3,316-character snapshot with 37
explicit facts in 0.44 seconds on this host. It truthfully named a clean
`master` tree, an empty project queue, a stale watcher belonging to another
project, two absent governance gates, a non-ready work item whose base revision
differs from observed HEAD, and deliberately disabled map/inventory sources.
Those observations are retained as evidence; this packet does not repair or
reinterpret them.

## Scope

In scope:

- `daedalus/orchestration/ikarus/shell.py`: recognize narrowly phrased
  selected-project state questions and compile their context from
  `status.collect_status`, `file_bridge.bridge_status`,
  `core.get_governance`, and `spine.picker.build_queue(limit=3)`;
- `daedalus/status.py`: accept an optional bounded Git timeout while retaining
  the existing 30-second default for non-interactive callers;
- `daedalus/spine/picker.py`: permit the interactive projection to disable the
  expensive docref scan while retaining the existing enabled default;
- `tests/test_ikarus_project_grounding.py`: prompt, egress/bounds, explicit
  editor-context composition, and Hand refusal tests;
- this packet.

Forbidden and unchanged: Conversation UI, settings, HTTP/effect registry,
provider authority, context-ref storage, canonical spine formats, Genesis,
GPU packaging, distribution files, policy, evaluator, ledger, promotion, the
Master Plan, amendment chain, and work-packet index.

## Contracts and behavior

The projection has fixed caps: 8,000 rendered characters, 12 dirty paths, 3
ranked candidates, 12 source states, 8 governance gates, and 480 characters per
candidate text field. Size omissions are reported in the context receipt; JSON
is never byte-truncated. Repository roots, raw exceptions, picker evidence
blobs, and free-form dashboard warnings never enter the prompt.

The first streaming `start` receipt is emitted before conversation or project
measurement. Interactive Git work has a two-second budget and docref scanning
is explicitly disabled for this projection. Invalid policy/configuration data
fails closed into a small, complete JSON measurement failure rather than
raising before the user sees progress.

Every dirty path, declared source root, candidate provenance artifact, and
candidate target/gate path passes the existing per-project
`slice_egress_rule`. Both sides of a Git rename are checked independently.
Candidate prose is withheld when its source, any referenced path, or the
unconditional secret floor refuses it. Explicit editor `context_refs` retain
their existing separately materialized capsule and are composed after this
snapshot rather than replaced by it.

Adversarial review found that repository-controlled watcher, governance and
picker strings could previously enter the projection without a closed
vocabulary, candidate IDs were not covered by the complete-candidate egress
check, invalid policy input could raise, and generic `status` routing could win
before an answer-shaped German project question. The retained repair accepts
only known states, gates, sources, booleans, bounded counts and revision
formats; withholds unknown keys/strings with visible static measurement
failures; gates the complete candidate JSON before clipping; and evaluates the
answer-shaped Voice rule before generic status routing. Explicit status and
slash commands retain their deterministic routes.

## Acceptance matrix

| Claim/refusal | Evidence | Required result |
|---|---|---|
| Exact live question is grounded | mocked existing owners plus selected Ollama Voice | context contains Git, bridge, governance, picker facts; Voice answers; no action |
| Context refs survive | explicit editor capsule text in the same stream test | project snapshot and explicit context both reach the Voice in declared order |
| Bounded projection | oversized/list caps plus output assertion | complete JSON is at most 8,000 characters; omissions are counted |
| Untrusted egress stays pruned | docs-allow policy, disallowed source, secret text, cross-policy rename | permitted docs survive; source/secret/rename candidate data is absent and counted withheld |
| Mutation cannot borrow Voice grounding | exact observation-plus-`fix` counterexample | context/provider untouched; Hand proposal requires confirmation |
| Existing slice/chat contracts hold | focused Ikarus context/router/stream suites | green; ordinary and file-explicit messages retain their prior behavior |

## Evidence, expected failures and review

- `python -m pytest -q tests/test_ikarus_project_grounding.py
  tests/test_ikarus_context.py tests/test_ikarus_os.py
  tests/test_ikarus_stream.py`: **61 passed, 3 subtests passed** in 5.32 s.
- Post-review hardening rerun:
  `python -m pytest -q tests/test_ikarus_project_grounding.py
  tests/test_ikarus_os.py tests/test_ikarus_stream.py`:
  **47 passed, 3 subtests passed** in 3.73 s.
- Extended post-review rerun covering project grounding, context, Ikarus OS,
  streaming, health, picker outcome/spectral/work-queue/map/return-arc suites:
  **313 passed, 1 expected xfail, 3 subtests passed** in 199.12 s.
- `python -m py_compile daedalus/orchestration/ikarus/shell.py
  daedalus/status.py daedalus/spine/picker.py`: passed after the adversarial
  repair.
- No provider, socket, file write, task enqueue, or effect-registry change was
  used by the focused tests.

## Migration and rollback

Rollback removes the narrow snapshot path, its tests, and this packet. There is
no persisted-data migration. Independent review should challenge whether any
new path-bearing field can bypass per-path egress, whether a missing component
is ever presented as healthy, and whether any wording implies that Voice ran a
tool or authorized work.
