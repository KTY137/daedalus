# G1-ARIADNE-08 — Committed bytes without the git binary

Packet ID: G1-ARIADNE-08

Artifact role: primary

Classification: `ALIGNED`

Active gate: Gate 1

Owner: repository owner

Base revision: cfe8d34b8ef1438156e6fa3e6982f5a30d91696f

Working-tree context: isolated worktree `.claude/worktrees/lane3-git-objects`, branch `loop/lane3-git-objects`, stacked on `loop/stage3-failed-receipt`

Dependencies: `G1-ARIADNE-05_WORKING_TREE_BASE_BINDING`, `G1-ARIADNE-06_NAMED_REFUSALS`

Stage: lane 3 of the owner-directed 2026-09-05 fleet.

## Primary acceptance claim

Daedalus can read the exact bytes a file had at an exact commit without a `git`
binary, without a process spawn, and without reading the working tree, or it
refuses with a named reason. The reader parses loose objects and packfiles
(`.idx` v2 plus `.pack`, `OFS_DELTA` and `REF_DELTA` chains, several packs),
walks commit → tree → subtrees, verifies every materialized object against the
id it was addressed by, refuses symlink, gitlink and tree entries as not-a-blob,
bounds memory by a caller-given `max_bytes`, and refuses a linked-worktree
`.git` pointer file the same way the HEAD verifier does.

This closes the open half of `G1-ARIADNE-05`. That packet's Scope section said
HEAD-content verification "must use git itself
(`git --no-optional-locks diff --quiet HEAD -- <path>`)". This packet refutes
that necessity with a measured reader: the subprocess was never required for
*reading*, only convenient. The packet does **not** flip
`head_content_verified`; section "Contracts and behavior" states exactly how a
later packet would, and why the flip is one-directional.

## Reproduced negative baseline (measured 2026-09-05, this worktree)

- The whole content question was open, not merely unimplemented:
  `daedalus/ariadne/campaign.py:242` writes `"head_content_verified": False`
  into `daedalus-ariadne-base-tree-binding/1`, and
  `daedalus/runtimes/contracts/repository.py` (`to_dict`) pins
  `"commit_object_verified": False` in every HEAD receipt. Nothing in the tree
  could read a committed blob:
  `daedalus/gates/repository/tree.py` refuses NUL bytes and non-UTF-8, so it
  cannot even read a zlib object stream.
- Tests before the module existed: `1 error` (collection, module absent).
- Tests against a stub whose functions raise `NotImplementedError`:
  `58 failed in 229.36s` — every one of the 58 discriminates.

## Scope

In scope, both files new:

- `daedalus/runtimes/contracts/git_objects.py`
- `tests/runtimes/test_git_objects.py`

Explicitly out of scope and untouched: `daedalus/ariadne/campaign.py` (another
lane and the release freeze own it), `daedalus/runtimes/contracts/repository.py`,
`daedalus/gates/repository/*`, every kernel contract, the HTTP facade, the
workbench. No caller is wired to the new module in this packet: it is a leaf
that nothing imports yet, so it can be reviewed and, if rejected, deleted with
no migration.

Deliberately not built: a git implementation. No index, no refs, no
`.gitattributes` filters, no writes, no shallow/partial-clone promisor objects,
no alternates, no `.idx` v1, no SHA-256 repository format. Each of those is a
named refusal, not a silent gap.

## Contracts and behavior

Public surface:

- `blob_at(root, commit_id, path, max_bytes) -> bytes`
- `blob_sha256_at(root, commit_id, path, max_bytes) -> str`
- `read_blob_at(...) -> GitBlobObservation` — the same read plus provenance:
  `blob_id`, `mode`, `size`, `sha256`, `source` (`loose`/`pack`), `pack_name`,
  `delta_kinds` (outermost first). `to_dict()` is a receipt projection
  (`daedalus-git-blob-observation/1`) that carries the digest and not the bytes,
  and states `process_spawned: false`, `working_tree_read: false`,
  `object_id_verified: true`.

Refusal types, all under `GitObjectError`: `GitObjectRequestError` (root type,
commit-id shape, path shape, size bound), `GitObjectLayoutError` (no `.git`,
`.git` symlink, gitdir pointer file, alternates, `.idx` v1, unsupported pack
version), `GitObjectNotFoundError` (commit or path absent at that revision),
`GitObjectKindError` (symlink, gitlink/submodule, tree, or a non-commit id
passed as the commit), `GitObjectSizeError` (above `max_bytes`),
`GitObjectIntegrityError` (SHA-1 mismatch, truncated or over-long stream,
malformed header, delta that copies outside its base, reserved delta opcode).

Verification boundary, stated precisely because it is the point of the packet:
every object this reader materializes is hashed as `"<type> <len>\0" + payload`
and compared against an id that came from the object store or the caller — the
caller's commit id, the tree id inside the commit, the entry id inside a tree,
the base id inside a `REF_DELTA`, and — for `OFS_DELTA` — the id the `.idx`
records for that pack offset. An offset is therefore never an unchecked
address. Not verified, and not claimed: the pack trailer checksum and the
`.idx` CRC table (per-object SHA-1 subsumes them for the objects actually
read), and the pack's own SHA-1 name.

Bounds: `max_bytes` is a strict positive `int` up to a 64 MiB reader ceiling; a
blob whose declared size exceeds it refuses *before* the payload is
materialized (loose: from the object header; packed: from the pack header or
the delta's declared result size). Commits, trees and delta bases use
`max(max_bytes, 64 MiB)`. Delta chains are bounded at 64 links and an
`OFS_DELTA` base must lie earlier in the pack, so a cycle cannot exist.

### How `G1-ARIADNE-05` could set `head_content_verified: true` (not done here)

`daedalus/ariadne/campaign.py` already has everything the flip needs, in the
right order. Between the second `_verify_head` (line 1176) and the binding
(line 1355) it holds `root`, the verified `source_revision`, the admitted
`relative`, and `target_snapshot.source_sha256`. The whole change is:

```python
# after the second _verify_head, inside the existing try/except discipline
try:
    head_blob_sha256 = blob_sha256_at(
        root, source_revision, relative, MAX_CAMPAIGN_FILE_BYTES
    )
except GitObjectError:
    head_blob_sha256 = None          # named, retained, never fatal
verified = head_blob_sha256 == target_snapshot.source_sha256
```

and `_base_tree_binding(..., head_content_verified=verified)`. The bound fits:
`MAX_CAMPAIGN_FILE_BYTES` is 16 MiB (`campaign.py:108`), under the reader's
64 MiB ceiling, so the call is admissible for every target the campaign accepts.
Four properties
have to hold and all four do:

1. **One-directional.** `True` proves the working-tree bytes are the bytes of
   the blob at that revision. `False` proves nothing, because `.gitattributes`
   `text=auto` is live in this repository and a checkout may legitimately hold
   CRLF where the object holds LF. `test_committed_bytes_differ_from_the_working_tree_under_eol_filters`
   measures exactly that case. So a mismatch must never refuse a campaign, must
   never be reported as "the target is dirty", and Momus's stage-4 rejection of
   a raw byte compare stands unchanged — the reader removes the subprocess, not
   the filter semantics.
2. **A function of the campaign identity only.** The binding stays replayable:
   `(source_revision, relative)` are already in it, and the blob at a fixed
   revision is immutable, so a replayed receipt's binding is still true. No
   index state, no timestamp, no `git add` sensitivity — the defect that killed
   the "index-match field" option in stage 4.
3. **No new refusal surface.** Every failure mode of the reader (linked
   worktree, path absent at that revision, blob above the ceiling, `.idx` v1,
   alternates, a corrupt object) is a `GitObjectError` and must degrade to
   `head_content_verified: false`, never to an `AriadneRequestError`. A
   campaign that runs today must still run.
4. **Digest impact is bounded and new-only.** The binding blob's SHA-256 is a
   provenance input of the nominated and the failed receipts; flipping the
   boolean changes that digest for *new* campaigns only. `operation_sha` does
   not contain the binding, so replay-by-identity is untouched. Retained
   receipts stay valid.

Two options were considered and are recorded as rejected: (a) adding
`head_blob_sha256` to the binding requires a `/2` schema and touches the
receipt-input scan, which is more churn than the boolean is worth until a
consumer needs the value; (b) putting the reader behind the HEAD receipt
(`commit_object_verified`) is refused because
`RepositoryHeadRevisionReceipt.to_dict()`/`from_dict()` verify an exact field
set — G1-ARIADNE-05 already measured that adding a field there breaks it.

## Acceptance matrix

Real repositories built by the actual `git` binary in `tmp_path`; `git` is a
test dependency only, and `test_reader_spawns_no_process` measures that the
subject never spawns one.

| Check | Result (2026-09-05, worktree, git 2.38.1.windows.1, CPython 3.13.14) |
| --- | --- |
| the 58 tests before the module existed | 1 collection error |
| the 58 tests against a `NotImplementedError` stub | 58 failed (229.4 s) |
| the 58 tests against the implementation | 58 passed (268.0 s under the ten-agent fleet load; 37.6 s when re-run alone) |
| loose objects, every revision, versus `git cat-file blob` | passed |
| `git gc --aggressive` pack, every revision, versus `git cat-file blob` | passed; fixture asserts every delta is type 6 (`OFS_DELTA`), reader reports chains of depth ≥ 2 |
| `repack.useDeltaBaseOffset=false` pack | passed; fixture asserts every delta is type 7 (`REF_DELTA`), reader reports `ref_delta` chains |
| two packs in one store, plus loose objects written on top of a pack | passed; the reader names which pack each blob came from |
| nested path, path absent, path not yet present at an older revision | typed `GitObjectNotFoundError` |
| symlink entry (mode 120000), gitlink (160000), tree, blob used as a directory, blob id passed as the commit | typed `GitObjectKindError` |
| 9 unsafe paths, 7 malformed commit ids, 6 malformed size bounds, non-`Path` root | typed `GitObjectRequestError` |
| blob one byte above `max_bytes`, loose and packed | typed `GitObjectSizeError`, exact bound in the message |
| loose object replaced by a valid zlib stream of forged content | `GitObjectIntegrityError` naming the object id |
| loose object truncated to 6 bytes; one byte flipped inside the packed record of the blob under read | `GitObjectIntegrityError` |
| `.git` is a gitdir pointer file (a real `git worktree add`) | `GitObjectLayoutError` naming the linked worktree and the remedy, while the main checkout still reads |
| `.git` absent, `objects/info/alternates` present, `.idx` v1 | `GitObjectLayoutError` |
| working tree modified, then deleted, under a fixed commit | committed bytes unchanged |
| `core.autocrlf=true` + `*.txt text` | object holds LF, checkout holds CRLF, reader returns the object |
| every `os.open` during a read | all under `<root>/.git`; the target file is never opened |
| `subprocess.Popen`, `os.system`, `os.posix_spawn` patched to raise | not called |
| synthetic `.idx` with a >4 GiB offset in the 8-byte table | parsed (the fixture path real packs cannot reach) |
| `tests/runtimes/test_runtime_gate_contract_boundaries.py` (runtimes must not import `daedalus.gates`) | passed |
| `tests/test_architecture_boundaries.py`, `tests/kernel/test_contract_hierarchy.py`, `tests/gates/test_repository_head_revision*.py`, `tests/test_ariadne_campaign_v0.py` | see the evidence log |

## Migration and rollback

Nothing imports the module, so rollback is `git rm` of two files. No contract,
schema, receipt, digest pin, registry row or effect-boundary entry changes: the
module is a pure read-only library with no `main()`, no writes, no spawns and no
network, so it needs no Effect Registry row. `daedalus.runtimes` may not import
`daedalus.gates` (`docs/architecture/import-boundaries.json`,
rule `runtimes-no-gates`); the module imports nothing from `daedalus` at all,
which is why it re-implements a bounded file read instead of reusing
`daedalus.gates.repository.tree`.

## Evidence, expected failures, and review

Evidence: `docs/evidence/G1-ARIADNE-08_GIT_OBJECT_READER/`.

Expected failures and honest residuals:

- **Large-offset packs are proven only synthetically.** A >4 GiB pack cannot be
  built in a test, so the 8-byte offset table is exercised through a
  hand-written `.idx` against `_PackIndex`. The `.pack` side of that path is
  untested.
- **Chain-depth and pack-count bounds are unexercised.** `_MAX_DELTA_DEPTH`
  (64) and `_MAX_PACK_FILES` (1024) are refusals no fixture reaches.
- **Only what was read is verified.** A repository can be corrupt in objects
  this reader never touches and still answer. The claim is per-object, not
  per-repository; it is not `git fsck`.
- **SHA-1 repositories only.** A SHA-256 repository would fail as a shape or
  integrity error, not as a named "unsupported object format".
- **Windows-only measurement.** The suite has not run on Linux or macOS in this
  packet. The reader uses `O_NOFOLLOW` where the platform has it and
  `O_BINARY` where it exists, so POSIX behaviour is expected but unmeasured.
- **`git` in the fixtures.** If the review wants the subject proven against a
  repository no `git` binary produced, that is a separate fixture packet.

Review questions: (1) does the per-object verification boundary as stated cover
what a reviewer would call "verified", given the pack trailer is not checked?
(2) is a leaf module with no caller acceptable at Gate 1, or should the flip in
`G1-ARIADNE-05` be one packet with it? (3) is the one-directional reading of
`head_content_verified` the right contract, or should a mismatch be recorded as
a third state rather than as `false`?

Not merged, not promoted, not pushed. Codex review not requested for this
packet.

Iron Plan: **ALIGNED**

Iron Gate: **1**

Automatic merge/promotion: **forbidden**
