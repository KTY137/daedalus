# G0-RWI-20F — Repository Write Source-Anchor Semantic Replay

This additive packet is stacked on exact parent `6743dae62d669070b866c5925a6f8fea7bbdb6f0`, the head of `g0/repository-write-evidence-origin-linear`. It introduces the first read-only semantic replay layer over the authenticated repository-write evidence chain. It does not modify `main`, `experimental`, production callers, the canonical effect registry, GateReport-v2, release state, OwnerApproval, promotion, or merge state.

## Exact replay chain

`verify_repository_write_source_anchor_semantics(...)` does not accept a loose origin report as authority. It re-materializes the supplied `RepositoryWriteClassificationReport`, re-verifies the signed origin attestation with the externally supplied collector keyring, and then binds the complete classification → materialization → origin-report → attestation digest chain.

Every classified write surface must contain exactly one `source_anchor` evidence binding. The verifier reparses that exact CAS blob under the same bounded strict-canonical JSON rules and requires its authenticated payload to name the classified surface's exact repository-relative path, line, and byte column. Missing, duplicate, stale, substituted, or detached bindings fail closed.

## Current-tree source binding

The selected repository root must be a real non-symlink directory. Each path component is checked without following symlinks, the final object must be a regular file, and the resolved path must remain below the selected root. The file is opened read-only, with `O_NOFOLLOW` where the platform provides it, and is bounded to 16 MiB.

The verifier compares the path metadata with the opened descriptor, reads the complete bytes, repeats descriptor and path identity checks, rejects incomplete reads, NUL bytes and invalid UTF-8, and then requires the exact SHA-256 from the authenticated source-anchor payload. The declared line and byte column must exist and point to a non-whitespace byte. The report retains a deterministic digest over the distinct anchored path/source-digest set.

This proves only that the authenticated source-anchor claims match the selected current tree. It does not prove Git ancestry or make the external source-revision label authoritative by itself.

## Non-authority boundary

Guard-contract, Effect-Lease, RuntimeConformance, Primary-Checkout-disjointness, and retirement receipts are not semantically replayed here. Therefore the report hard-codes:

- `origin_authenticated=true`;
- `source_anchor_semantics_verified=true`;
- `semantic_receipts_verified=false`;
- `evidence_authenticated=false`;
- `gate_report_bound=false`;
- `closed=false`.

The implementation contains no filesystem-write, process, database, Git, promotion, OwnerApproval, merge, or Gate-transition authority and accepts no callback or arbitrary keyword authority.

## Adversarial batch

Prepared behavior coverage includes deterministic exact-tree replay, changed source bytes, path/line/column substitution, whitespace and out-of-range anchor positions, multiple anchors, stale revisions, wrong collector secrets, detached cross-layer digests, symlink redirection, malformed repository roots, and empty classifications.

A separate AST/source counter-review checks read-only authority, absence of callback smuggling, materialization-before-authentication and authentication-before-tree ordering, exact one-anchor and position fences, source-digest checks, bounded no-follow file access, before/after identity checks, and permanent false complete-evidence/Gate/closure claims.

Ten bounded mutants attack semantic-trust escalation, complete-evidence escalation, false Gate binding and closure, multiple-anchor acceptance, position substitution, source-byte substitution, whitespace acceptance, symlink acceptance, and detached digest-chain acceptance. Author-side isolated stub preparation reports `19 passed`; ten mutants were killed in targeted isolated executions. This is not exact-head repository, supported-platform, packaging, independent-human, semantic-runtime, or Gate evidence.

CI requests Ubuntu and Windows on Python 3.10 and 3.12 with two hash seeds, predecessor tests, mutation, Iron Plan verification, full suite, package build, and isolated-wheel import.

## Remaining blockers

Dependent packets must replay guard-contract evidence against the canonical implementation map, Effect-Lease receipts against the persisted authoritative ledger, Runtime Manifest and RuntimeConformanceReceipt evidence against the selected runtime, Primary-Checkout disjointness against current immutable checkout/target state, and retirement receipts against production reachability. Only the complete semantic result may be bound into GateReport-v2 and the release verifier.

The live classification/evidence corpus, canonical caller migration, Docker sandbox, Primary-Checkout mutation exclusion, and complete fault-injection matrix remain open. Exact-head execution is pending because GitHub Actions issue #67 still terminates hosted jobs before Step 1 with no logs or artifacts. Zero-step runs are infrastructure observations only.

No OwnerApproval, automatic promotion, merge, or Gate transition is requested.

Iron Plan: **ALIGNED BY SCOPE; EXACT-HEAD EXECUTION REQUIRED**  
Iron Gate: **0**  
Promotion: **not requested**
