# G1-GENESIS-04 - Read committed live WAL evidence for source delivery

Packet ID: `G1-GENESIS-04`
Artifact role: `primary`
Active gate: `1`
Classification: `ALIGNED`
Owner: `repository owner`
Base revision: `b605586b2778659a119b25fa7d05938a986356e3`
Dependencies: `Master Plan Revision 13; G1-GENESIS-03; G1-INTEGRATION-01`

## Primary acceptance claim

A successfully completed Genesis candidate remains readable by source download
and preview while the existing canonical Event Store retains committed rows
in an uncheckpointed WAL. Read delivery must not initialize schema, checkpoint,
repair, retry execution, create a second store, or weaken retained CAS/effect
verification. This is a corrective product packet, not scientific Gate closure.

## Scope

Allowed: `daedalus/orchestration/genesis/service.py`, the existing canonical
Attempt reader/lookup seams in `daedalus/kernel/attempt_spine_reader.py` and
`daedalus/kernel/attempt_ledger.py`, narrowly necessary HTTP reader wiring,
focused Genesis/Attempt read regression tests, and this packet/evidence.
The ordinary immutable lookup default stays intact where it is required.
Forbidden: plan, policy, evaluator, execution semantics, Event Store schema,
checkpoint/repair, new event/snapshot stores, provider starts, and promotion.

## Contracts and behavior

Read one trustworthy SQLite snapshot through the existing strict canonical
Attempt decoder. Active live evidence must include committed WAL state.
Checkpointed and missing-store read-only behavior stays unchanged. Invalid or
incomplete retained evidence still refuses; source identity remains the CAS
manifest, and source.zip stays a transport representation. Filesystem byte
provenance and concurrency limits must be stated rather than inferred from
an immutable URI that hides live WAL. No hostile-filesystem sandbox is claimed.

## Acceptance matrix

1. Retain fresh-WAL failure before implementation: real canonical writer open,
   schema/terminal row committed in WAL, source archive and preview fail under
   the old immutable projection.
2. Corrected archive and preview succeed for that exact terminal candidate;
   inspect archive manifest/hash and exact preview source bytes independently.
3. Reads invoke no writable ledger construction, schema/DDL, checkpoint,
   execution, repair, or initialization; no sidecar files are created.
4. Pin a consistent read transaction for multi-query lifecycle projection if
   live WAL is consumed. Retain immutable-default and checkpointed no-write
   tests, absent-store refusal, corrupt/different candidate and effect evidence.
5. Run focused Genesis service/source archive/HTTP and canonical Attempt-reader
   suites; independent review precedes integration. Real browser reproduction
   remains separate from focused tests.

## Migration and rollback

No store migration or historical evidence rewrite. Reverting this corrective
commit restores the previous read behavior and its measured WAL failure.

## Evidence expected failures and review

2026-09-08 diagnostic GUI run at initially de358424 (sources/tests changed during
that run) returned preview-ready for genesis-bfc724b649f33e8e235706fb, then
source.zip returned HTTP404. The unchanged-main browser baseline passed this
flow, but GET/source-export/Attempt-reader source is byte-identical to main.
Read-only diagnosis against retained state found main DB4096 bytes,
WAL131872 bytes and SHM32768 bytes. Immutable lookup raised no such table:
intents; ordinary canonical mode=ro found one COMPLETED lifecycle for the same
run. This is a preexisting state-sensitive read bug, not a lost merge route.
No DB checkpoint, repair or schema write was used during diagnosis.

Freeze recorded before production edits. Red/green logs and final exact source
revisions will be appended after measurement; no pass or no-sidecar claim is
made here before those tests run.


Frozen implementation boundary before source edits (2026-09-08): add an explicit
existing-WAL opt-in to the canonical Attempt lookup/reader, selected only by
Genesis source/preview delivery. With no sidecars retain the immutable reader;
with a live WAL require an existing regular WAL/SHM pair and reject partial or
malformed sidecar shape before opening SQLite. Read in one explicit transaction.
No normal reader is opened to create absent sidecars, and no retry/checkpoint
fallback is permitted. SQLite SHM read-mark bookkeeping for an admitted live
pair is permitted; DB/WAL bytes and the file set remain unchanged. This is an
entry-time contract, not protection against hostile filesystem replacement.


## Reviewed scope clarification and concrete negative probes

No-files-created is measured with a stable preexisting sidecar lifecycle. The
entry-time file checks do not pin WAL/SHM lifetime: an ordinary concurrent last
writer close, as well as hostile replacement, can remove them between admission
and SQLite open. This implementation does not provide a filesystem lease or an
unconditional no-creation guarantee across that race. Checkpointed reads select
immutable mode; no sidecars are opened merely to initialize them.

The bounded admission checks cover a regular existing pair, whole SHM pages,
initialized duplicate SHM headers and their checksum, WAL header format and
checksum, complete physical frame extent, and matching WAL/SHM header metadata.
They do not independently replay frames, prove every WAL page or SHM hash entry,
or replace SQLite snapshot/format interpretation or the strict Attempt decoder.
The source performs no checkpoint, repair, retry or writer call. SQLite live
SHM locking/read-mark bookkeeping remains allowed. This is bounded validation
of demonstrated failure modes, not a universal malformed-file guarantee.

Retained probe `runs/integration-20260908/genesis-wal-sqlite-malformed-probe.log`
uses a checkpointed table plus one committed WAL row and an isolated file copy.
With plain mode=ro/query_only/BEGIN, a damaged WAL magic or header checksum and a
partial final frame all silently returned the stale empty main-table view.
A damaged or truncated SHM header was rebuilt. Clean read returned the live row;
DB/WAL bytes stayed unchanged. These are the concrete grounds for bounded header
admission instead of assuming that mode=ro alone always refuses corruption.
Format constants/checksums follow SQLite's [WAL file format](https://www.sqlite.org/fileformat2.html#wal_file_format)
and [WAL-index format](https://www.sqlite.org/walformat.html).

The initial fixture diagnostic `genesis-wal-red.xml/log` used a keeper on the
wrong database and failed only its missing-BEGIN check; it remains negative
fixture evidence and is not claimed as a reproduction of HTTP404. The corrected
`genesis-wal-red-canonical.xml/log` held the actual authority spine open and
retained two real HTTP404 failures (archive and preview, 52 deselected, 3.28s).
The first corrected run `genesis-wal-first-green.xml/log` passed both exact
cases (52 deselected, 3.23s). The additional boundary/snapshot run
`genesis-wal-boundary-first.xml/log` passed 18 cases (52 deselected, 3.60s).
These focused results are not real-browser acceptance or scientific Gate closure.


## Independent review correction: existing transient SHM reconstruction

2026-09-08, explicit root scope decision after independent review: the earlier
frozen wording that suggested no SQLite SHM reconstruction, or read-mark-only
changes, was too strong. A valid stable retained DB/WAL/SHM pair with no active
keeper caused SQLite's first reader to reconstruct its existing transient SHM
index. The independent probe observed changes outside the read-mark offsets;
DB/WAL bytes remained unchanged. Header admission does not establish SHM index
integrity and does not prevent SQLite's first-reader recovery of that index.

The permitted effect is now explicit: SQLite may update its existing transient
SHM bookkeeping, including first-reader index reconstruction. There is no active
keeper requirement, borrowed-connection seam, new store, VFS or authority.
Application checkpoint/repair calls, DB/WAL writes, schema initialization,
execution/retry and new authority remain forbidden. No-file-set-change is a
measurement under a stable existing sidecar lifecycle, not an unconditional
guarantee across ordinary last-writer cleanup or hostile replacement races.
This corrects the product read-effect claim; it changes no Master Plan rule.

A separate retained-pair regression now exercises the first reader with no
keeper on that pair, permits arbitrary transient SHM changes, and checks that
both DB/WAL bytes and the existing file set stay unchanged. The fresh-WAL HTTP
cases continue to hold the canonical keeper and validate exact source identity.


Admission availability limit: header copies and physical file extents are read
separately. An ordinary valid concurrent append/header update can therefore
cause a temporary fail-closed refusal before the SQLite transaction begins.
There is no automatic retry. The concurrent-commit test proves coherent
consumption after admission; it does not prove wait-free admission availability.


## Final focused measurements

The frozen behavior suite (`genesis-wal-focused-frozen.xml/log`) passed 275
cases with 4 skips in 81.63s: all isolated Attempt tests plus Genesis service,
source archive, HTTP, and the new WAL admission/snapshot tests. The preceding
`genesis-wal-focused.xml/log` remains retained with 273 passes, 4 skips and 2
source-inspection failures: explanatory Python docstring edits moved source
lines after process import. It was a mixed-source diagnostic run and supplies
no final acceptance claim. The frozen rerun resolved both inspection failures.

After the independent SHM correction, only docstrings/comments and the new
no-keeper test changed. The final affected reader/HTTP/source-inspection suite
(`genesis-wal-reviewed.xml/log`) passed 90 cases in 38.53s. Exact five-file
source digests are in `genesis-wal-reviewed-source.json`; the earlier broad
suite's source digests remain in `genesis-wal-focused-source.json`.

The exact retained failing GUI state also became readable without execution:
`genesis-wal-retained-gui-read.json` records run
`genesis-bfc724b649f33e8e235706fb`, candidate
`960838c237b68a23a95a32f9e7b80ebd3b1d7c8145537e60d3ab416b2701be75`,
32226 archive bytes and 2173 preview bytes. Independent reads checked the ZIP
manifest, every source blob digest, and exact preview/source equality. Spine
DB/WAL hashes and the file set stayed unchanged. This reads the old failure
state; it is not a new browser acceptance run.

All filenames above are relative to `runs/integration-20260908/`. Root owns
retained evidence packaging, the final commit and the separate browser gate.
No scientific Gate advancement, comparative result or promotion is claimed.
