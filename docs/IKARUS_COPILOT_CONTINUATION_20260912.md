# Copilot ignition continuation, 2026-09-12

Iron Plan: ALIGNED evidence-integrity repair, Gate 1. The separate repaired
shopping-list preview is an EXPERIMENT. Nothing here closes a delivery gate
or promotes a generated candidate.

## Recovered session and actual corpus

Resumed Copilot session `8b525a4e-dfe4-4d83-bdfd-dda0a18b0454`, which stopped
with quota error 402 on `c4a147969fcad94e5481c48ff48cb6b22efee9c0`, branch
`g1/ikarus-ignition-20260912`, PR #384. The interrupted second review is now
complete for the bounded KITCHEN-02 changes.

The retained order `order-44c4f73113d3313e` records 49 successful imports out
of the requested 50 repositories; date-fns was skipped as undeclared license.
No new feed or provider calls were made during this continuation.

Direct read-only SQLite measurement found:

| Measurement | Stored result |
| --- | ---: |
| Repository entries, including three generated candidates | 64 |
| Actual cards | 205,044 |
| Previously reported cards | 210,031 |
| Edges | 408,647 |
| Binding proposals | 16,524 |
| Proposals flagged verified in the historical database | 16,153 |
| Flagged verified but missing endpoints | 94 |
| Flagged verified with existing endpoints | 16,059 |

The old card totals counted overwritten duplicate identities. The new extractor
preserves occurrence identities and refuses duplicate or dangling graph input.
Status uses actual rows and excludes invalid endpoints from the verified count.
Existing observations are retained rather than silently rewritten.

Embeddings are still `hashed-blake2b/256`. Three queries over a snapshot of the
real corpus execute in 3.08-3.16s and no longer retrieve generated candidate
entries by default. This measures working retrieval, not usefulness compared
with BM25, learned embeddings or direct generation. The relation tensor remains
a projection; it is not the canonical Twin TensorView contract.

## Repairs to evidence handling

- Delivery replay returns the existing result and does not erase candidates,
  patches, failed runs or receipts. Project context participates in request
  identity. An explicit new request creates separate output paths.
- Empty, optional-only and installation-only observations cannot make a
  candidate green. Selected checks and recognized evaluator/configuration
  files are frozen before Renovation and across repairs. Failed rounds are
  persisted before another builder effect; provider disappearance is retained.
- Renames check both old and new paths against the self-renovation boundary.
  Git-inspection failure no longer means "no changed paths".
- Candidate extraction binds the observed source digest, handles Git worktrees
  and dirty bytes honestly, and refuses nomination when extraction fails.
  Digest ordering is explicitly POSIX-path lexical order across platforms;
  historical Windows ordering and old hashes are not rewritten.
- Generated candidates are excluded from default corpus retrieval. Suggested
  new tests/configuration are deferred rather than changing the frozen judge.
- One-shot CLI background mode now refuses before admission; stable request
  IDs support replay and `--new-request` permits a deliberate fresh attempt.

## Verification

Baseline: 77 passed in 13.61s on c4a14796. New acceptance:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/orchestration/test_ikarus_kitchen_retention.py tests/orchestration/test_ikarus_kitchen.py tests/orchestration/test_ikarus_greymatter_integrity.py tests/orchestration/test_ikarus_kitchen_toolchain_integrity.py tests/contracts/test_import_scc_hierarchy.py tests/interfaces/test_http_strangler_architecture.py tests/test_ikarus_shells.py tests/test_ikarus_os.py tests/test_ikarus_os_boundary.py -q -p no:cacheprovider
# 195 passed, 1 skipped, 37 subtests passed in 24.88s

.\.venv\Scripts\python.exe -m pytest tests/orchestration/test_ikarus_souschef.py tests/orchestration/test_ikarus_kitchen_retention.py tests/orchestration/test_ikarus_kitchen_toolchain_integrity.py tests/test_registry_new_doors.py -q -p no:cacheprovider
# 69 passed in 18.16s; overlaps the preceding selection
```

The skip is a symlink fixture unavailable under this host's privileges.
Independent review reproduced the defects before the fixes and reran six
selected regressions after them, all passed. No new SCC or registry failure;
`git diff --check` passes. Existing GitHub checks on c4a14796 passed, including
Windows browser flows and Linux PR validation; those checks do not validate
the continuation diff until rerun on its commit.

## Retained browser and migration failures

The old preview at `http://127.0.0.1:8765` serves an empty directory. The state
move to `~/.daedalus/kitchen` left old absolute paths in the database/receipts.
Only 3,710 of 22,512 indexed source paths still exist at the recorded roots;
22,505 exist under their migrated roots. An existing directory alone was not
proof that the source content survived at its recorded path.

Both original generated app trees still match their historical evidence under
the historical digest algorithm. The improved shopping-list workspace is
missing; its patch and evidence survive. Its patch applies to recorded base
`1df621c5ff45603e7a640d4a4671c8632de09974`, but that 8-file reconstruction is
not the original 9-file candidate identity.

Real browser verification found no delete control in either shopping-list
version. The historical improvement also throws a TypeError on every load and
allows blank quantities after the first item. These are retained negative
results despite the old green structural tests. The separate DEMO-01 repair
uses a new copy and independent browser checks; it cannot retroactively make
those earlier model runs pass.

## Remaining ignition blockers

KITCHEN-01 still owns a separate order database and directly launches builders
and checks. Canonical Mission/Attempt/EffectLease, kill/cancel/reconciliation,
source CAS, independent product acceptance and sealed EvidencePacket admission
are not established by this repair. The earlier owner decision deferred builder
containment; it does not make these other contracts present.

Frozen-file integrity covers recognized and declared verifier inputs, not all
possible transitive imports or host isolation. Candidate-generated initial
checks remain limited evidence. Live source path migration and historical
invalid corpus observations require a separate source-bound reconciliation,
with the original database retained. No new scientific performance claim,
production activation, merge or candidate promotion is supported here.

## Available repaired preview

The isolated DEMO-01 copy now passes **24/24 independent browser checks**:
button/Enter additions, quantity/default validation, blank-label refusal,
single-item deletion, completion and reload persistence, clear and reload
persistence, zero JavaScript exceptions, 390px layout and source integrity.

Open `http://127.0.0.1:8766`. Source:
`~/.daedalus/kitchen/previews/shopping-list-20260912`. A complete eight-file
archive, frozen external browser verifier, repair and independent receipts,
report and mobile screenshot are retained under
`docs/evidence/G1-IKARUS-KITCHEN-DEMO-01/`.

The archive reproduces source digest
`2b4d1ecc57cf098f57ae15f32a508f73a6bb209925110849ccb4b214f425c8b4`.
To restart locally after closing the preview:

```powershell
.\.venv\Scripts\python.exe -m http.server 8766 --bind 127.0.0.1 --directory C:\Users\Administrator\.daedalus\kitchen\previews\shopping-list-20260912
```

This is a directly repaired experimental copy. Neither original candidates nor
the historical index have been replaced, and the preview is not a claim that
the kitchen generated and verified the repair autonomously.

## Owner-directed integration onto main

The owner subsequently instructed: "tue ikarus ignition auf main und arbeite
darauf". This explicitly authorizes integration of the reviewed ignition
branch; the earlier no-merge scope above records the preceding continuation
phase. It does not change the Master Plan, promote a generated candidate or
close the remaining kernel-admission gaps.

The primary checkout was fast-forwarded onto the ignition branch at 8ba8ba04,
and subsequent work takes place on local `main`. The bundle-attribute check
then reproduced two failures: twelve transitive evaluator-bundle inputs lacked
explicit `-text` declarations. The repair adds those twelve individual entries,
without weakening the guard or adding a wildcard. Their working files were
restored to their exact already committed LF bytes; no source content changed.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ignition_bundle_gitattributes.py tests/test_ignition_bundle.py -q -p no:cacheprovider
# 38 passed, 7 Python tar-extraction warnings in 140.73s
```

The combined kitchen, Sous-Chef, corpus, verifier, import, HTTP, shell, OS and
entrypoint-registry selection was rerun in this primary checkout: **228 passed,
1 skipped, 37 subtests passed in 48.98s**. This is the union of the two earlier
selections, not additional unique coverage. Independent inspection of GitHub
run `34698299251` found the same two attribute failures in all four Python/seed
jobs (each 462 passed, 10 skipped, 2 failed); the isolated wheel passed.

This measures byte-stable evaluator packaging and the existing bundle/ignition
fixtures. It is not evidence of autonomous kitchen product acceptance.
