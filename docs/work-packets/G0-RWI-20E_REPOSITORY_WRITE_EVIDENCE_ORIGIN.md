# G0-RWI-20E — Authenticated Repository Write Evidence Origin

This additive packet is stacked on exact parent `be76936fd1ef9b18b1aa22c745a75c8ee5e2008d`, the current head of `g0/repository-write-evidence-authentication-linear`. It adds a narrow origin-authentication layer over the complete content-addressed materialization from G0-RWI-20D. It does not modify `main`, `experimental`, the canonical effect registry, GateReport-v2, release state, OwnerApproval, promotion, merge state, or any production caller.

## Exact external-origin binding

`issue_repository_write_evidence_origin_attestation(...)` creates a short-lived HMAC-SHA256 attestation for one complete, non-empty `RepositoryWriteEvidenceMaterializationReport`. The key is supplied externally; the repository does not provision a production collector key or trust root.

The signed subject binds:

- collector identity and collector key identity;
- exact source revision;
- classification digest and complete materialization digest;
- binding count;
- canonical per-record digests;
- exact CAS blob digests;
- canonical payload digests;
- a digest over the complete record/blob/payload projection;
- canonical issuance and expiry timestamps.

Record and blob identities must be unique. Repeated payload digests remain valid because distinct evidence envelopes may legitimately carry identical canonical payloads while retaining different subjects and blobs.

`verify_repository_write_evidence_origin(...)` authenticates the signature before projecting live materialization state. It then requires the expected collector, current revision, classification, materialization, count, record set, blob set and payload multiset to match exactly. Future, expired, stale, substituted, partial or empty subjects fail closed.

## Strict wire boundary

The byte parser accepts only bounded exact bytes, strict UTF-8 without BOM or NUL, duplicate-key-free and non-finite-free JSON, byte-for-byte canonical JSON, the exact attestation schema, sorted digest arrays and canonical UTC microsecond timestamps. Attestation lifetime is at most 24 hours.

## Non-authority boundary

A positive report means only that a configured collector key authenticated the exact complete materialization projection. It does not prove that any embedded Effect-Lease, RuntimeConformance, checkout-disjointness, guard, source-anchor or retirement claim is semantically true. It does not replay authoritative ledgers or runtime state and cannot close Gate 0.

The report therefore hard-codes:

- `origin_authenticated=true`;
- `semantic_receipts_verified=false`;
- `evidence_authenticated=false`;
- `gate_report_bound=false`;
- `closed=false`.

No production attestation or collector secret is committed by this packet.

## Adversarial batch

Prepared behavior coverage includes deterministic issue/parse/verify round trips, repeated payload digests, unknown and wrong keys, signed-field substitution, stale revision and collector identity, classification/materialization/record substitution, empty and partial materialization, future and expired attestations, maximum TTL, malformed secrets and keyrings, noncanonical/duplicate/non-finite/oversized JSON, encoding faults, schema-shape and boolean-count attacks, unsorted sets and detached record-set digests.

A separate AST/source counter-review checks absence of repository, process, database, promotion, OwnerApproval, runtime and effect-lifecycle authority; explicit non-smuggling signatures; signature-before-projection ordering; parser fence ordering; exact live binding comparisons; permanent false semantic/Gate/closure claims; HMAC-SHA256; bounded TTL and input size; and absence of file, network or database mutation.

Thirteen bounded mutants attack trust escalation, incomplete materialization, signature bypass, time-window bypass, parser bounds/canonicalization, detached record-set binding, collector substitution and stale-revision binding. Author-side isolated stub preparation reports `20 passed` and thirteen mutants killed. This is not exact-head repository, platform, packaging, semantic-runtime, independent-human, or Gate evidence.

CI requests Ubuntu and Windows on Python 3.10 and 3.12 with two hash seeds, predecessor tests, mutation, Iron Plan verification, full suite, package build and isolated-wheel import.

## Remaining blockers

A dependent packet must authenticate and semantically replay each materialized receipt against its authoritative source, retain exact provenance, and only then compose the result into GateReport-v2 and the release verifier. The live repository-write inventory and classifications still require complete evidence population. Runtime Manifest/ConformanceReceipt composition, Docker sandboxing, Primary-Checkout mutation exclusion, caller migration and the complete fault-injection matrix remain open.

Exact-head execution is pending because GitHub Actions issue #67 continues to terminate jobs before Step 1 with `steps=null`, no logs and no artifacts. Zero-step runs are infrastructure observations only.

No OwnerApproval, automatic promotion, merge or Gate transition is requested.

Iron Plan: **ALIGNED BY SCOPE; EXACT-HEAD EXECUTION REQUIRED**  
Iron Gate: **0**  
Promotion: **not requested**
