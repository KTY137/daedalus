# Gate 2 Project Twin post-durability audit

Status: **open — storage blocker closed, Gate 2 closure not yet claimed**

Audited head: `789b102c9f2cc55e09df675c60188bcc38ea7e08`

## Exact-head workflow evidence

The audited head completed both required repository workflows successfully:

- Iron Plan run `30741898921` — success
- Gate 2 Project Twin run `30741898863` — success

The Gate 2 workflow covers Python 3.10 and 3.12, multiple `PYTHONHASHSEED` values, the Project Twin/Genesis contract and fault suites, and isolated wheel build/install/import.

## Closed storage blocker

The durability blocker recorded in the preceding closure audit is closed on this exact head:

1. canonical lock records are emitted with a complete-write loop rather than assuming one `os.write` consumes the payload;
2. a zero-progress write fails closed;
3. the lock file is fsynced before authority is exposed;
4. containing-directory mutations are fsynced after lock creation, abandoned-lock reclamation, and owner-checked removal;
5. tests cover repeated partial writes, zero-progress writes, create/remove durability, reclaimed-lock durability, live-owner refusal, foreign-host refusal, malformed/noncanonical records, symlink refusal, and replacement races;
6. the full exact-head CI and isolated-wheel checks are green.

## Consolidated guarantees now evidenced

The stacked Gate 2 implementation provides:

- revision-exact `ProjectTwinManifest` identity;
- deterministic `GenesisCompileReceipt` identity and manifest binding;
- content-addressed source, Forest, Fourfold snapshot, compiler-contract, EvidencePacket, and output identities;
- append-only manifest/receipt persistence with canonical readback verification;
- deterministic bounded Genesis compilation and exact replay;
- revision-replay, repository-substitution, compiler-substitution, source-drift, locator-mismatch, noncanonical-encoding, and record-tamper refusal;
- revision-exact lifecycle transitions and deterministic drift classification;
- expected-head compare-and-swap while holding an exclusive repository writer lock;
- crash-window tests before replace, after replace, and after directory fsync;
- same-host abandoned-owner recovery with PID liveness proof and ownership-token cleanup;
- durable lock publication and removal under partial-write and replacement-race faults.

## Remaining Gate 2 blockers

This audit does not convert bounded reference coverage into a claim of broad Project Twin semantic completeness. Gate 2 remains open pending:

1. integration of the revision-pinned corpus pilot into this canonical stack rather than leaving it on a sibling draft branch;
2. content-addressed human/legal review evidence for corpus entries before any entry transitions from `declared` to `reviewed`;
3. explicit evidence showing the supported repository/language boundary and clearly classifying external or non-portable legacy probes;
4. a final consolidated closure review on one linear exact head after those records and workflows are green.

## Gate decision

The Project Twin lifecycle storage protocol is now sufficiently hardened against the previously identified partial-write and directory-entry durability faults. Gate 2 is nevertheless kept open because corpus and supported-semantics closure evidence is not yet integrated on this head. Gate 3 must remain stacked behind the final Gate 2 closure review.
