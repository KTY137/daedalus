# G0-WP-04 — Canonical Kernel Storage

Status: independent preparatory batch; not promotion-capable  
Classification: `ALIGNED`  
Active gate: Gate 0 — Canonical Kernel  
Owner: repository owner  
Base revision: `9e621318c955b4b91a0acdc13baaae08b719f7fe`  
Parent packet: `G0-WP-03 — Persisted Effect Leases`

## Blocker boundary

The hardened parent head cannot currently obtain fresh GitHub Actions evidence:
returned jobs terminate before executing any step, contain zero step records,
and expose no downloadable job log. This packet is independent of lease
execution semantics and may be prepared without consuming or widening an effect
lease. No dependent attempt, runtime, promotion, or production-entrypoint
migration may build on this packet until the parent and this packet both have
executable CI evidence.

## Primary acceptance claim

Daedalus has one stdlib-only kernel storage backend that can retain immutable
content-addressed artifacts and append revision/subject-bound events without
silently accepting corruption, stale heads, replay, timestamp regression, or
write attempts through a read-only handle.

This packet does not claim that existing legacy state stores have been migrated.
It adds the target kernel backend behind a new responsibility boundary; later
strangler packets must adapt existing producers into it and retire parallel
state only after measured compatibility.

## In scope

- `daedalus/kernel/storage.py`
- `daedalus/kernel/__init__.py`
- `tests/kernel/test_storage.py`
- `tests/kernel/test_storage_adversarial.py`
- `.github/workflows/gate0-kernel-storage.yml`
- this Work Packet

## Forbidden in this packet

- changes to `main`, `experimental`, the master plan, or amendment ledger;
- migration of production callers;
- effect-registry rows or claims that storage is a centrally leased runtime
  entrypoint;
- OwnerApproval, promotion, runtime, sandbox, attempt, or Fourfold semantics;
- automatic merge or promotion;
- deleting or rewriting legacy ledgers.

## Storage contract

### Content-addressed store

- identity is lowercase SHA-256 over exact bytes;
- locators use the canonical `artifact-locator:sha256:<digest>` spelling;
- JSON publication uses the existing canonical serializer;
- publication writes and fsyncs a same-directory temporary file, then publishes
  by an atomic hard link that cannot replace an existing identity;
- a concurrent winner is accepted only after byte-level digest verification;
- every read verifies the digest;
- malformed locators, missing blobs, corrupt blobs, symbolic-link blob paths,
  non-canonical JSON and non-finite values fail closed;
- read-only handles never create storage or publish artifacts.

### Event store

- SQLite WAL with `synchronous=FULL`, `BEGIN IMMEDIATE`, busy timeout and
  query-only read handles;
- immutable append-only rows and no update/delete API;
- globally unique event IDs and event digests;
- independent per-stream hash chains;
- each append binds event ID, stream, kind, subject digest, canonical payload
  digest, timestamp and previous stream head;
- caller supplies the exact expected stream head; stale writers fail closed;
- per-stream timestamps cannot regress;
- schema version, exact table shape, uniqueness constraints and stream index are
  checked before use;
- reads revalidate metadata, canonical payload, event digest, timestamp order
  and the complete stream chain;
- append verifies existing stream history before extending it.

The hash chain detects accidental or unprivileged file corruption. It is not an
authentication mechanism against an attacker who can rewrite the database and
all descendant hashes. Authentication and effect authority remain separate
kernel responsibilities.

## Acceptance matrix

| Area | Required evidence |
| --- | --- |
| deterministic identity | repeated byte/JSON publication returns one digest and canonical bytes |
| concurrency | concurrent identical CAS writes converge; one stale-head event writer wins |
| replay | duplicate event ID remains refused after process restart |
| malformed input | invalid IDs/digests/locators, non-object payloads and non-finite values refuse |
| corruption | blob bytes, symlinks, JSON encoding, event payload, metadata, schema and chain tampering refuse |
| crash/fault | failed publication leaves neither visible blob nor temporary file; aborted SQLite insert rolls back |
| read-only | artifact/event writes refuse and event inspection leaves DB contents unchanged |
| portability | focused suite on Python 3.10/3.12 on Ubuntu and Windows |
| regression | relevant Gate-0 trust suites plus full suite on supported Linux interpreter |
| packaging | isolated wheel install imports `ContentAddressedStore` and `EventStore` |
| governance | `python tools/iron_plan_guard.py verify` |

## Adversarial counter-review record

A context-separated adversarial pass by the same automation/model instance found
and fixed four issues before dependent use:

1. a destination symlink with matching target bytes could make a CAS write
   appear successful while verified reads refused the locator;
2. non-finite JSON loaded from stored bytes escaped the artifact-corruption
   error family;
3. the schema version marker did not prove the actual events table and
   constraints matched the contract;
4. append trusted the latest stored event hash without first validating the
   existing stream and could therefore extend corrupt history.

Regression tests now cover all four cases. This counter-review is builder-side
evidence only. It is not independent review, may share blind spots with the
implementation pass, and cannot satisfy the final Gate-0 review requirement.

## Adversarial mutation targets

The focused tests must kill at least these equivalent mutations:

1. skip artifact digest verification on read;
2. publish by replacement without refusing an existing identity;
3. remove exact expected-head comparison;
4. make the event chain global instead of stream-local;
5. accept duplicate event IDs after restart;
6. omit payload/chain verification during read;
7. treat a failed SQLite constraint as a successful append;
8. allow writes through a read-only handle.

The isolated hardened implementation completed with 16 passing tests. Five
temporary mutants were executed and killed: skipped blob-read verification,
skipped expected-head comparison, unverified existing stream on append,
noncanonical event-payload acceptance and destination-symlink acceptance. These
results are development evidence only and do not replace exact-branch CI.

## Exact-branch verification status

Reviewed code head: `122badc6ce1af13d65eeee2e912ed5320ed35228`.
Subsequent commits in this packet only qualify documentation evidence.

GitHub Actions runs `30848710330` and `30848932265` each instantiated all ten
requested storage jobs, including Ubuntu and Windows, Python 3.10 and 3.12, two
hash seeds, full suite and isolated wheel. Every job terminated before executing
a step and returned `steps=null`. Iron Plan runs failed in the same zero-step
state. No test log exists, so these runs are accepted neither as green evidence
nor as product-code failures.

## Rollback

Delete this packet's new module, tests, workflow and exports. No production
caller is migrated, so rollback does not require data conversion. Any test CAS
or SQLite files are disposable fixtures.

## Residual risks and next prerequisite

- legacy state stores remain parallel and authoritative for their current
  callers;
- the new mutating APIs are infrastructure backends, not externally reachable
  runtime starts; later callers must obtain effect authorization before invoking
  them;
- no attempt workspace, candidate-tree archive, EvidencePacket binding or
  Fourfold integration is added here;
- independent external review remains outstanding;
- dependent work remains frozen until executable CI verifies the current parent
  and this branch.

Iron Plan: **ALIGNED**  
Iron Gate: **0**  
Promotion: **not requested**
