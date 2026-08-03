# G0-WP-04 — Content-addressed source trees

Status: builder-verified; system CI externally blocked  
Classification: ALIGNED  
Active gate: Gate 0 — Canonical Kernel  
Base revision: `9d7a34a2f15a2a21ecb193fb0c56fb23f0c8c34d` (`g0/effect-leases`)  
Dependency: G0-WP-03 persisted effect leases

## Primary acceptance claim

Daedalus can capture an ordinary repository source directory as immutable,
content-addressed regular-file blobs plus one canonical, revision-bound source
tree manifest, and can materialize that exact tree into a new destination
without following symlinks, overwriting an existing workspace, or mutating the
source directory.

This packet does not run an Attempt, authorize an effect, create Evidence, or
promote a candidate. Those remain dependent packets.

## In scope

- `daedalus/kernel/artifacts.py`
- `daedalus/kernel/__init__.py`
- `configs/schemas/source-tree-manifest-v1.schema.json`
- `tests/kernel/test_artifact_store.py`
- `.github/workflows/gate0-source-tree-cas.yml`
- this packet

## Forbidden scope

- primary checkout mutation
- Git ref updates or promotion
- owner-approval issuance or consumption
- runtime execution
- evaluator or policy changes
- automatic merge
- master-plan or amendment edits

## Contract and storage invariants

1. Object identity is SHA-256 of exact bytes.
2. Manifest identity uses the canonical Gate-0 JSON serialization.
3. Every manifest binds one exact source revision and every retained blob.
4. Only regular files are retained. Symlinks and special files refuse.
5. Repository-relative paths refuse traversal, case-fold collisions, and
   file/child conflicts.
6. `.git` and `.daedalus` top-level metadata are explicitly excluded from
   candidate source identity.
7. Writes are temporary-file, fsync, atomic-replace operations followed by
   digest verification.
8. Reads recompute the digest and fail closed on corruption.
9. Manifest, blob, per-file, and total-tree reads are bounded before candidate
   publication.
10. Materialization targets must not already exist and are built in a sibling
    staging directory before atomic publication.

## Acceptance matrix

| Case | Expected result |
| --- | --- |
| identical tree captured twice | identical manifest and locator |
| source content changes | new blob and manifest identity; old object remains readable |
| duplicate file contents | one blob, two path entries |
| executable regular file | mode retained on POSIX materialization |
| `.git` / `.daedalus` metadata | excluded and declared in manifest |
| source-root or entry symlink | refusal without reading target |
| FIFO or another special file | refusal |
| addressed object replaced by symlink | corruption refusal |
| `../` manifest path | malformed manifest refusal |
| manifest/provenance revision mismatch | stale-revision refusal |
| case-only path or ignored-root collision | refusal across supported platforms |
| file `a` plus child `a/b` | refusal |
| addressed object tampering | read and existence checks fail closed |
| oversized manifest/blob/tree | refusal before publication |
| missing referenced blob | no destination is published |
| existing materialization destination | refusal |
| injected atomic-replace failure | no addressed object or temporary residue |

## Independent adversarial review

A separate review pass over the builder diff found four material weaknesses:

1. A source path could be changed between the initial symlink check and the
   open operation on platforms without `O_NOFOLLOW`.
2. An existing addressed object was read without first refusing symlink and
   non-regular-file replacement.
3. Object and manifest reads were not bounded before allocation.
4. Materialization trusted manifest sizes without applying independent
   per-file and total-byte ceilings.

The implementation now performs pre-open path metadata capture, descriptor
identity checks, post-read path identity checks, regular-file `lstat` checks,
bounded reads, and independent capture/materialization ceilings. Tests cover
source-root and entry symlinks, special files, object-address symlinks, corrupt
objects, stale revisions, and failure before destination publication.

The reviewer also considered the final destination rename race. This packet
requires an unused destination inside an attempt-owned parent. Preventing a
hostile peer from creating that exact sibling path is therefore assigned to the
dependent isolated-Attempt workspace packet and later OS sandbox. This packet
does not claim hostile multi-tenant directory isolation.

## Focused mutation evidence

Six temporary mutations were each killed by the focused tests:

1. follow source symlinks and remove `O_NOFOLLOW`;
2. skip digest recomputation on object reads;
3. allow materialization over an existing destination;
4. ignore manifest/provenance revision mismatch;
5. allow case-fold path collisions;
6. publish a partial staging tree after a missing-blob failure.

The mutation runner used fresh copies of the module for each mutant and restored
the correct implementation after every run. Results were respectively one
failed test with eleven passing tests for each mutant. These are targeted
builder mutation results, not a whole-repository mutation score.

## Builder verification

A minimal isolated Python 3.13 harness reproducing the repository's canonical
contract validators and serialization executed the module's focused suite:

- `12 passed`;
- byte-for-byte capture/materialization exercised;
- corruption, malformed input, stale revision, symlink/special-file, bounds,
  and injected atomic-replace failures exercised;
- module and tests compile successfully.

This harness is useful implementation evidence but does not replace execution
against the full Daedalus package, wheel, supported Python matrix, or platform
matrix.

## System-CI blocker

GitHub Actions runs are currently created but every job terminates before its
first step. The Actions API returns an empty step list and no downloadable log;
log retrieval returns `BlobNotFound`. The same pre-step failure affects both the
new packet workflow and the pre-existing Iron Plan workflow, as well as an
independent one-job checkout-export probe. This distinguishes the blocker from
a pytest, packaging, workflow-command, or packet-specific test failure.

Last observed affected runs:

- Gate 0 Source Tree CAS: `30788106137`;
- Iron Plan: `30788106158`.

The dependent packet is not considered green while this external runner/account
condition persists. Work that does not require GitHub-hosted execution may
continue, and CI must be retried before handoff.

## Rollback

Delete the additive module, schema, tests, workflow, and exports. No existing
caller is migrated by this packet, so rollback does not require data migration.

## Residual boundary

This is the candidate artifact substrate only. Gate 0 remains open until
isolated Attempt lifecycle, runtime conformance, sandboxing, centralized effect
wiring, sealed promotion, and the complete fault matrix are implemented and the
machine-readable release report returns `closed=true`.

Iron Plan: **ALIGNED**  
Iron Gate: **0**  
Promotion: **not requested**
