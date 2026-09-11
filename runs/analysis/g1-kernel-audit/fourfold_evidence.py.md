# daedalus/kernel/fourfold_evidence.py  (631 lines)

Base 54f09753. Static read-only.

## What the file is for

Projects one already-compiled `FourfoldSnapshot` into the canonical
`EvidencePacket`/`NominationReceipt` contracts: it writes the snapshot's own
canonical JSON bytes into a content-addressed `ArtifactStore`, derives the
locator that names them, and cross-checks that packet, snapshot, candidate
digest/locator, and evidence-item provenance all name the same candidate
tree/revision/Forest/snapshot. It is a binding/projection adapter, not a
build system, evaluator, or promotion authority — it does not compile
anything, does not run tests, and does not decide promotion.

## Axis 1 — docstring truth

### CONFIRMED
- none.

### PLAUSIBLE
- none. No docstring claim in this file overclaims a property the code does
  not implement.

### Checked and honest
- Module docstring (`:1-17`) "It does not compile repositories, create a
  second evidence schema, authenticate artifact storage, consume approvals,
  or promote candidates" — confirmed: no compile/promote/approval-consuming
  code anywhere in the file; only 4 read/store-facing storage calls, all
  going through the caller-supplied `ArtifactStore`.
- Module docstring "[it] verifies that every record still names the same
  candidate tree, source revision, Forest and snapshot" — confirmed by
  `verify_fourfold_evidence_packet` (`:468-572`), which checks
  `source_revision` on packet/expectation/item/provenance, `subject_sha256`,
  `candidate_artifact_sha256`, `candidate_artifact_locator`,
  `fourfold_snapshot_sha256`/`snapshot.digest`, `source_forest_sha256`, and
  the evidence item's `input_digests` set — I read all ~20 comparisons and
  every field named in the docstring is actually compared.
- `FourfoldEvidenceUnstorable` docstring (`:65-72`) "Deliberately NOT a
  fall-back to a synthesised locator" — confirmed: `_store_snapshot`
  (`:172-207`) raises on every `ArtifactStoreError|StorageUnavailable|
  OSError|ValueError` from `store.put_bytes`; there is no fallback branch
  that mints a locator without a successful write.
- `FourfoldEvidenceExpectation` docstring (`:76-84`) "Gate-0 Fourfold
  evidence is always complete; partial semantics ... cannot be enabled by a
  caller switch here" — confirmed: neither `assemble_fourfold_evidence_packet`
  nor `verify_fourfold_evidence_packet` take a partial/allow-incomplete
  parameter; `verify_fourfold_evidence_packet` unconditionally rejects any
  plane whose `status != "complete"` (`:500-504`).
- `verify_fourfold_evidence_packet` docstring (`:475-484`) — the claim that
  it stays usable "holding a packet and a snapshot and nothing else" and
  only *resolves* the locator's bytes when a `store` is passed — confirmed:
  the byte-resolution branch is explicitly gated `elif store is not None`
  (`:536-544`); without a store only the locator *string* is re-derived and
  compared (`:534`), never resolved. This is disclosed, not hidden.

**Direct answers to the brief's Axis-1 questions for this file:**
`FOURFOLD_EVALUATOR` (`:44`) is a plain `Final[str]` constant
(`"fourfold.snapshot-binding"`), not a class, callable, or evaluation
engine — there is no code path in this file where that name resolves to
anything that runs a check; it is only ever compared as a string
(`item.evaluator == FOURFOLD_EVALUATOR`, `:514`) or written into an
`EvidenceItem.evaluator` field. A "verified" Fourfold evidence packet from
this module is, in plain terms, a digest-bound bundle of identity claims:
verification here means "packet, item, and provenance all point at the same
already-computed snapshot/candidate/forest digests, and every plane the
snapshot self-reports carries `status == "complete"`" — it is not an
independent re-derivation of whether the candidate's code, build, or tests
are actually correct. That correctness judgment is produced entirely
upstream, by whatever compiled the `FourfoldSnapshot` (outside this file,
in `daedalus.twin`), and this module trusts the snapshot's self-reported
`plane.status` field rather than recomputing it. The naming is honest about
this scope (`"snapshot-binding"`, not `"snapshot-correctness"`), and the
module docstring's own framing ("projects", never "compiles" or "verifies
correctness") matches — so this is not classed as an overclaim, but it is
the plain answer the brief asked for: verification == binding consistency,
not independent correctness evaluation.

## Axis 2 — effect surface

| site (file:line) | effect | registry row | covered? |
| --- | --- | --- | --- |
| `_store_snapshot` (`:172-207`), called from `assemble_fourfold_evidence_packet:326` | filesystem write, via `ArtifactStore.put_bytes` (daedalus/storage.py) | none of the 4 `daedalus.kernel.*` rows; plausibly `cli.ignition` (`daedalus.spine.effect_boundary.py:2560-2579`, `target="daedalus.ignition.__main__:main"`) whose notes explicitly say "FILESYSTEM_WRITE covers its receipt and content-addressed evidence stores" | covered **only when reached through `daedalus/ignition/__main__.py:main`** |
| `_resolve_store` (`:210-215`) creating `ArtifactStore(DEFAULT_EVIDENCE_STORE_ROOT)` | filesystem stat/resolve (no write itself) | same as above | same as above |
| `resolve_fourfold_snapshot_bytes` (`:218-230`) | filesystem read, via `ArtifactStore.load_locator`/`get_bytes` | none targeted; not gated at all (read-only) | not applicable — read effect |

### Notes
- Both production callers of `assemble_fourfold_evidence_packet` —
  `daedalus/ignition/gate1.py:1257` and `daedalus/ignition/runner.py:267` —
  are only reachable through `daedalus/ignition/__main__.py`, which the
  registry names as `cli.ignition` (`:2560-2579`) with `Effect.FILESYSTEM_WRITE`
  and an explicit note naming "content-addressed evidence stores". That is a
  plausible, credited covering row.
- This module has **no anchor or guard call of its own**: no import from
  `daedalus.spine` for policy/guard checks, no `begin_effect` call, no
  `EffectLease`/authorization consumption anywhere in the file. Any caller
  that imports `daedalus.kernel.fourfold_evidence` directly and invokes
  `assemble_fourfold_evidence_packet(..., store=my_own_store)` performs a
  real filesystem write with **zero registry coverage**, because the only
  covering row is anchored at the CLI entrypoint boundary, not inside this
  module. This is the file's one concrete instance of the "effectful site
  reachable without passing through one of the four kernel rows" pattern
  the brief calls the expected finding — CONFIRMED as a structural fact
  (absence of any guard import/call in this file); whether any current
  non-test caller actually takes that bypass path was not found (the only
  two production callers both go through `cli.ignition`).

## Axis 3 — unreleased resources

No findings. This file performs no direct resource acquisition — no
`open()`, no `sqlite3`, no `tempfile`, no locks, no sockets, no subprocess.
All I/O is delegated to `ArtifactStore.put_bytes`/`get_bytes`/`load_locator`
(daedalus/storage.py, out of this file's scope), which itself uses
`os.open`/atomic publish helpers, not a leaked `Connection`-style handle.

## Axis 4 — validator gaps (W4 class)

No findings. The only identifier-shaped values this module validates are
`sha256` digests (`_sha256`, canonical.py:65-71, strict `^[0-9a-f]{64}$`),
`source_revision` (`_revision`, canonical.py:74-82, strict 40/64-hex), and
`artifact-locator:sha256:...` URIs (`_artifact_locator`,
canonical.py:85-91) — none of these three go through the weak `_identifier`/
`_ID_RE` validator the W4 sweep flagged. `packet_id`, `mission_id`,
`attempt_id`, `nomination_id` (passed through to `EvidencePacket`/
`NominationReceipt`, whose `__post_init__` in canonical.py:1131-1132/2643-2644
*does* run them through the weak `_identifier`) are used in this file only
as opaque field values and inside one f-string (`evidence_id=
f"{attempt_id}:fourfold"`, `:339`) that becomes another opaque field value —
none of them ever reach `Path(...)`, `os.path.join`, or any path/filename
construction in this file. I traced the one place a digest becomes a real
filesystem path — `ArtifactStore.blob_path`/`locator_path`
(daedalus/storage.py:458-463) — and confirmed those build paths from the
already-validated sha256 hex digest only, never from `repository_id`,
`packet_id`, `mission_id`, or any other free-form string; caller metadata
(including `snapshot.repository_id`) is stored inside the JSON manifest
body, never used as a path segment (storage.py:527-591 read in full).

## Axis 5 — dead / duplicate

### CONFIRMED — `assemble_fourfold_nomination_receipt` / `verify_fourfold_nomination_receipt` have zero production callers
Scoped grep (`grep -rn "assemble_fourfold_nomination_receipt\|
verify_fourfold_nomination_receipt" --include=*.py daedalus/ tests/ scripts/
tools/ docs/ apps/ gates/`) finds both symbols only in: their own definitions
in this file (`:409`, `:575`), the internal self-call
`verify_fourfold_nomination_receipt` inside `assemble_fourfold_nomination_receipt`
(`:459`), `__all__` (`:627`, `:630`), 4 test files (`tests/kernel/
test_fourfold_evidence_adversarial.py`, `test_fourfold_evidence_owner_binding.py`,
`test_fourfold_evidence_source_review.py`), and the **stale duplicate tree**
under `apps/web/src-tauri/{backend/_internal,target/debug,target/release}` —
confirmed stale by checking `daedalus/kernel/campaigns.py` (the file that
duplicate imports and calls `verify_fourfold_nomination_receipt` at its old
line 306) does not exist in the live source tree; `git log --all --oneline
-- "**/campaigns.py"` shows it was relocated to
`daedalus/kernel/contracts/campaigns.py` by the "canonical contract
hierarchy" refactor (commits `36261b93`/`4582a71c`), and the current
`daedalus/kernel/contracts/campaigns.py` has **zero** matches for
`nomination|Nomination|fourfold|Fourfold` (checked directly). So the one
production caller these functions ever had was dropped during that refactor
and never replaced. `NominationReceipt`'s own docstring
(canonical.py:2625, "A candidate recommendation, deliberately not a
promotion decision") names no consumer, so there is no dangling promised
reader beyond what other workers already established for the D5
sealed-promotion consumption chain — this is the Fourfold-specific instance
of that same already-confirmed kernel-wide seam, not a new independent one.
`resolve_fourfold_snapshot_bytes` is NOT dead: it is exercised on the
production path whenever `store` is passed to
`verify_fourfold_evidence_packet` (`:536-544`), which both `gate1.py:1257`
and `runner.py:267` do via `assemble_fourfold_evidence_packet`.

### Duplicates
None found. No local reimplementation of `_sha256`/`_revision`/
`_artifact_locator`/`_locator_sha256` — all four are imported from
`daedalus.kernel.contracts.base` (`:24-30`), which re-exports the canonical
versions from `contracts/canonical.py`. No second evidence/nomination schema
is defined; `FOURFOLD_EVIDENCE_SCHEMA` is a new schema string but for a
genuinely new evidence *kind* (a Fourfold snapshot binding), not a
duplicate of an existing one.

## What I did not cover

- `daedalus/storage.py`'s `ArtifactStore` internals (Axis 3 resource
  handling, Axis 4 path confinement) beyond the parts needed to answer this
  file's own axis questions — that file is owned by other workers' scope.
- `daedalus/twin/contracts.py::FourfoldSnapshot` and how `plane.status`
  values are actually computed upstream — out of this file's slice.
- Full read of `daedalus/ignition/gate1.py` and `runner.py` beyond the
  ~60 lines needed to confirm the call site and the fail-soft packet
  assembly comment at gate1.py:1247-1279.
