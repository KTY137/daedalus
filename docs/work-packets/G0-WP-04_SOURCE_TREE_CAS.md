# G0-WP-04 — Content-addressed source trees

Status: builder candidate  
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
9. Materialization targets must not already exist and are built in a sibling
   staging directory before atomic publication.
10. File and total-byte limits are mandatory capture bounds.

## Acceptance matrix

| Case | Expected result |
| --- | --- |
| identical tree captured twice | identical manifest and locator |
| source content changes | new blob and manifest identity; old object remains readable |
| duplicate file contents | one blob, two path entries |
| executable regular file | mode retained on POSIX materialization |
| `.git` / `.daedalus` metadata | excluded and declared in manifest |
| source symlink | refusal without reading target |
| `../` manifest path | malformed manifest refusal |
| manifest/provenance revision mismatch | stale-revision refusal |
| case-only path collision | refusal across supported platforms |
| file `a` plus child `a/b` | refusal |
| addressed object tampering | read and existence checks fail closed |
| missing referenced blob | no destination is published |
| existing materialization destination | refusal |
| injected atomic-replace failure | no addressed object or temporary residue |

## Adversarial review questions

- Can a source or manifest path escape the declared root?
- Can a symlink or special file smuggle evaluator/policy bytes into a candidate?
- Can a stale revision be repackaged under a valid tree identifier?
- Can corruption be reported as cache presence?
- Can a partial materialization become visible as a candidate workspace?
- Can two paths that collide on Windows produce a platform-dependent identity?
- Does this create a second serialization or artifact identity authority?

## Mutation seeds

The following focused mutations must be killed before review handoff:

1. remove source symlink refusal;
2. stop recomputing object digests on read;
3. allow materialization over an existing destination;
4. remove provenance/source-revision equality;
5. remove case-fold collision detection;
6. publish the destination before all blobs are verified.

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
