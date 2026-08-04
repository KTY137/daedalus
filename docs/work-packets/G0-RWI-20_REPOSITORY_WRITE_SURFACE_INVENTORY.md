# G0-RWI-20 — Revision-Bound Repository Write Surface Inventory

## Scope

This Work Packet branches from the exact head of the GateReport-v2 baseline line and adds a conservative discovery layer for production write-capable callsites. It does not modify the Gate report, classify a path as Primary-Checkout-safe, execute an effect, issue OwnerApproval, migrate a caller, merge, promote, or claim Gate-0 closure.

The report says only that a production Python callsite can write, create, remove, rename, launch a process, or open SQLite with write-capable or unresolved semantics. It does **not** say where that callsite writes. Therefore `primary_checkout_target_proven` is fixed to `false`, and every finding except an exact literal SQLite `mode=ro` connection remains blocking.

## Revision and byte binding

`scan_repository_write_surfaces(repository_root, source_revision=...)` requires a lowercase 40-hex source revision and scans every regular non-symlink `daedalus/**/*.py` file. The report binds the sorted repository-relative path and SHA-256 of every scanned production file. Malformed UTF-8 or Python syntax, package or file symlinks, package escape, relative-import escape, unreadable files, and missing production packages refuse the entire report rather than dropping a finding.

The revision string is an externally supplied exact-head label. This packet does not invoke Git and does not independently prove that the supplied revision is the current checkout. Exact Git ancestry and artifact retention remain release-workflow obligations.

## Conservative classifications

The scanner discovers:

- direct `os`, `shutil`, `tempfile`, and path-method mutation primitives;
- built-in, `io`, and path `open` calls with literal write modes or unresolved modes;
- `os.open` calls with write-capable or unresolved flags;
- SQLite connections that are write-capable, default-create, or dynamically addressed;
- subprocess and process-launch surfaces, including literal Git mutation commands;
- import aliases, file-wide rebinding, simple indirect aliases, and expression-based path methods.

Literal parsing never makes a process call trusted: even a static read-looking Git command remains `process_effect_unknown` and blocking because process configuration, working directory, hooks, environment, and optional locking are not proven here. Only an exact literal SQLite URI with `uri=True` and exactly `mode=ro` is nonblocking.

The scanner intentionally prefers false-positive blockers over false-negative omission. A later target/guard classifier must use revision-bound source and runtime evidence; source comments or self-asserted annotations cannot serve as authority.

## Machine interface

The canonical report schema is `daedalus-gate0-repository-write-inventory/1`. The stdout-only CLI is:

```text
python scripts/report_repository_write_inventory.py . --source-revision <40-hex>
```

`--require-closed` is only a scoped inventory assertion. It returns nonzero while any unclassified write-capable surface remains. It cannot close Gate 0.

## Adversarial batch prepared

Behavioral coverage includes deterministic byte binding, filesystem and path methods, literal and dynamic open modes, `os.open` flags, SQLite modes, literal and dynamic process calls, import aliases, indirect aliases, rebound methods, malformed source, stale/nonrevision labels, package redirection, CLI exit semantics, and strict contract objects.

A separate source-level review verifies that the scanner itself has no repository-write, process, OwnerApproval, Effect-Lease, merge, or promotion authority; all unknown and mutating categories remain blocking; the report cannot claim Primary-Checkout target proof; process parsing has no nonblocking outcome; expression-method fallback precedes classification; and revision plus production bytes are mandatory digest inputs.

Eight bounded mutants attack filesystem blocker laundering, ignored write modes, Git mutation downgrade, nonrevision labels, production-byte unbinding, dropped expression-method discovery, default SQLite laundering, and acceptance of a symlinked package root.

The dedicated workflow requests Ubuntu and Windows, Python 3.10 and 3.12, two hash seeds, focused malformed/source-review/schema/CLI tests, the mutation campaign, the full suite, package build, and isolated-wheel import.

## Honest remaining boundary

This packet is inventory-only. It does not prove which findings can reach the Primary Checkout, does not bind target roots or runtime working directories, does not identify every reflective/native/external write path, and does not add guard contracts. The inventory digest is not yet a GateReport-v2 or release-verifier input.

A dependent packet must execute and retain the exact-head inventory, independently classify every finding using revision-bound evidence, bind Primary-Checkout disjointness or immutable before/after fingerprints, migrate or retire every inventory-only/unguarded/ambiguous production path, and then bind the exact inventory digest and blocker projection into the Gate report and release verification.

Exact-head executable verification is pending. Repository GitHub Actions issue #67 repeatedly ends jobs before Step 1 with `steps=null`, no logs, and no artifacts. Such zero-step runs are infrastructure observations only and are not accepted as inventory, test, mutation, platform, packaging, or Gate evidence.

No OwnerApproval, effect transition, merge, promotion, automatic action, or Gate transition is requested.

Iron Plan: **ALIGNED BY SCOPE; EXACT-HEAD EXECUTION REQUIRED**  
Iron Gate: **0**  
Promotion: **not requested**
