# G0-RWI-20A — Repository Write Stdlib False-Negative Delta

This packet stacks directly on PR #166 at exact parent `9bd52bf7bc09ac7c5dbfee4884442bb024174a01`. It does not patch the canonical repository-write scanner, classify a target as Primary-Checkout-safe, install a guard contract, execute an effect, issue OwnerApproval, merge, promote, or claim Gate-0 closure.

## Purpose

The first syntax inventory has an honest but material false-negative boundary around standard-library APIs whose write semantics are not represented by the existing `open` and process tables. A concrete example is `gzip.open(path, "wb")`: the canonical scanner currently treats a generic terminal named `open` as a bound method and examines positional argument zero as the mode, so module-level compressed/archive openers can disappear when the filename occupies that position.

This packet makes those families machine-visible before any integration claim. The additive report is bound to:

- the exact lowercase 40-hex source revision label;
- the complete base-inventory digest produced from the same source tree;
- the sorted path and SHA-256 of every regular non-symlink production Python file;
- the sorted immutable additional finding set.

The report is permanently open in this packet:

- `canonical_scanner_integrated = false`;
- `closed = false`;
- every finding has `blocking = true`;
- `canonical-scanner-integration-missing` is always retained as a blocker.

## Additional surface families

The delta inventories literal or ambiguous writes through `gzip`, `bz2`, `lzma`, `tarfile` and `zipfile`; file-descriptor writers and truncation; temporary-file constructors; archive creation/extraction; serialization and stream sinks; generic `write`/`writelines`/row-writer methods; asynchronous subprocess creation; additional `subprocess`, `os.exec*`, `os.spawn*`, `posix_spawn*`, `pty.spawn`, multiprocessing and process-pool surfaces.

Literal read modes for the five exact compressed/archive openers do not create a delta finding. Dynamic, expanded or duplicate mode authority remains blocking. Process parsing never creates a trusted category. A callsite already reported by the parent inventory at the same path, line and column is suppressed from the delta so integration work cannot double-count it.

## Authority separation

The production module reads source bytes and invokes the retained base scanner. It contains no registry patch, SQLite writer, subprocess invocation, Git call, filesystem mutation, OwnerApproval, PromotionReceipt, Effect-Lease transition, merge or promotion authority. The CLI emits one canonical JSON document to stdout and exposes only a scoped `--require-no-additional-surfaces` assertion; even an empty delta remains open until canonical integration is reviewed separately.

## Prepared adversarial batch

Behavioral coverage includes:

- compressed/archive write, read and dynamic modes;
- fd, temporary-file, archive and stream sinks;
- asynchronous and alternative process creation;
- aliases and global rebinding ambiguity;
- malformed revisions and malformed Python;
- exact base-digest and all-production-byte binding;
- CLI output/refusal semantics and schema parity;
- repository-relative path normalization refusal.

A separate source-level counter-review checks permanent open status, blocker retention, exact surface families, lack of effect authority, one base scan, source-byte binding and exact result construction. Eight bounded mutants attack compressed-mode laundering, dynamic-mode laundering, fd and async-process omission, generic write-sink omission, base-digest unbinding, false canonical integration and false closure.

The workflow requests Ubuntu and Windows, Python 3.10 and 3.12, two hash seeds, predecessor regressions, mutation, Iron Plan verification, full suite, package build and isolated-wheel import.

## Honest remaining boundary

A dependent packet must integrate the reviewed families into the canonical scanner through a normal edit, retain exact base-byte and revision binding, run the exact-head scanner, and independently classify every finding with target and guard evidence. Project-specific wrappers, native extensions, reflection, external tools and dynamically constructed writers remain outside this finite stdlib delta and must be covered by later inventories or runtime evidence.

GitHub Actions issue #67 currently terminates hosted jobs before Step 1 with `steps=null`, no logs and no artifacts. Such runs are infrastructure observations only and are not accepted as builder, review, malformed-input, stale-revision, mutation, platform, packaging, inventory or Gate evidence.

No merge, promotion, OwnerApproval, automatic action or Gate transition is requested.

Iron Plan: **ALIGNED BY SCOPE; EXACT-HEAD EXECUTION REQUIRED**  
Iron Gate: **0**  
Promotion: **not requested**
