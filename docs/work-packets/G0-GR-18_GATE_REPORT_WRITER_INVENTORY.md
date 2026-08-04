# G0-GR-18 — Gate Report v2 Writer-Inventory Binding

## Objective

Make the machine-readable Gate-0 release report depend on a revision-bound production Event-Store writer inventory. A report cannot claim `closed=true` when the inventory is missing, refused, or contains a direct or ambiguous writer blocker.

## Gate report v2

`daedalus-gate-report/2` adds:

- `event_store_writer_inventory_sha256`;
- `event_store_writer_failures`.

The report now requires an exact lowercase 40-hex source commit. The inventory digest is the digest of the canonical writer report for that same requested revision and the scanned production bytes. Every blocking writer callsite is projected into Gate blockers with its path, line, column, classification and resolved or syntactic callee.

A null inventory digest is always a blocker. An inventory refusal adds both a missing-digest blocker and `event_store_writer_failures:inventory-refused`. Therefore malformed source, malformed or stale revision material, or unavailable inventory evidence cannot be converted into release closure by omission.

## Strict evidence parsing

V2 parsing requires:

- the exact schema field set;
- an exact lowercase 40-hex source revision;
- lowercase SHA-256 values;
- actual booleans and integers rather than Python truthiness or coercion;
- JSON arrays of non-empty bounded strings;
- a mandatory report digest;
- a `closed` value equal to the recomputed closure state;
- a blocker list equal to the recomputed blocker projection;
- an entirely canonical payload equal to a fresh serialization of the parsed contract.

File loading is additionally bounded to 4 MiB, requires UTF-8, refuses duplicate JSON object keys, rejects `NaN` and infinity constants, normalizes malformed JSON and refuses non-object roots. A payload that is tampered and then re-signed is still refused when its derived projection, types, ordering, uniqueness or shape is inconsistent.

## V1 compatibility

`daedalus-gate-report/1` remains readable for migration and monotonic-baseline comparison when it contains an exact source commit. Its digest, exact legacy shape, derived `closed` flag and blocker projection are verified. After parsing, the resulting current contract has no writer-inventory digest and therefore cannot claim v2 closure. New output is always v2.

This is intentionally asymmetric compatibility: historical evidence remains inspectable, but old evidence cannot silently satisfy a newly introduced release obligation.

## Adversarial batch

Builder tests and a separate malformed-input review cover:

- exact inventory digest and revision binding;
- writer findings in monotonic comparison;
- inventory refusal and malformed or stale revision behavior;
- missing inventory closure refusal;
- strict v1-to-v2 migration;
- unknown fields;
- string-to-boolean coercion attempts;
- strings supplied in place of arrays;
- re-signed inconsistent `closed` and `blockers` fields;
- duplicate or noncanonical rows;
- missing report digests;
- removal of writer failures without re-signing;
- duplicate keys, non-finite constants, malformed JSON, non-UTF-8 input and oversized reports.

The bounded mutation campaign attacks inventory omission, missing or failure blocker removal, digest substitution, refusal laundering, boolean coercion, nonrevision source labels, duplicate-key acceptance, report-size removal and trust in serialized or canonical projections.

## Honest residual boundary

The report only projects evidence supplied or derived by its builders. This packet does not migrate remaining writers, execute the fault matrix, produce runtime conformance receipts, prove primary-checkout immutability, assert the security boundary, or issue an OwnerApproval. `closed=true` remains impossible through the normal builder while those obligations remain open.

Exact-head execution is still unavailable because GitHub Actions issue #67 prevents jobs from starting. No test pass, mutation kill, report artifact, platform result, package result or independent review is claimed.

No merge, promotion, approval or checkout mutation is requested.

Iron Plan: **ALIGNED BY SCOPE; RELEASE EVIDENCE INCOMPLETE**  
Iron Gate: **0**  
Promotion: **not requested**
