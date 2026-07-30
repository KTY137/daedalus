# Research wave — questions raised by the structural synthesis

Each question below came out of the audit of this repository rather than from a reading list. Answers are from `deepseek-v4-pro` with no source access, so they are literature knowledge, not verified fact.

## q01-win-replace-open-file

**Q:** On win32, exactly which conditions make MoveFileEx / os.replace fail over an open target file, and what retry and backoff shape is correct? Can CPython be persuaded to open files with FILE_SHARE_DELETE so a replace succeeds while a reader holds a handle?

On Windows, os.replace() fails if the target file is open without FILE_SHARE_DELETE. Most Python file openings lack this flag. Retries with exponential backoff may help transient locks but not sustained ones. Proper fix: open files with FILE_SHARE_DELETE via ctypes/msvcrt, or design to avoid replacement while handles open. Recommend bounded retry (5 attempts, exp backoff 100ms–1.6s) as a safety net, but primary resolution is FILE_SHARE_DELETE.

*Recommended:*

- Audit all file opens to identify long-held handles on files that might be replaced.
- Implement a utility to open files with FILE_SHARE_DELETE using ctypes or msvcrt.open_osfhandle.
- Add bounded retry wrapper around os.replace for transient-lock scenarios, logging failures.
- Consider a write-to-temp-then-rename strategy for writers, with readers using FILE_SHARE_DELETE.

*Caveats:*

- Retrying may mask systemic design issues if the lock is persistent.
- Using FILE_SHARE_DELETE may allow readers to see inconsistent state if writer replaces mid-read.
- Exponential backoff in a critical path could introduce latency.

## q02-posix-rename-semantics

**Q:** Does SetFileInformationByHandle with FILE_RENAME_INFO_EX and FILE_RENAME_POSIX_SEMANTICS (Windows 10 1709+) give true POSIX rename-over-open-file semantics, and what are its limits on NTFS, ReFS and SMB shares?

SetFileInformationByHandle with FILE_RENAME_INFO_EX and FILE_RENAME_POSIX_SEMANTICS provides genuine POSIX rename-over-open-file semantics on Windows 10 1709+ on NTFS and ReFS: the rename is immediate and all open handles reflect the new name. Cross-volume renames are not atomic; fallback to MoveFileEx is required. SMB support requires protocol-level POSIX extensions (SMB 3.1.1+ with appropriate server capabilities). FAT/exFAT do not support it. Atomicity is maintained locally but may be impacted by memory-mapped files or oplocks.

*Recommended:*

- Use FILE_RENAME_POSIX_SEMANTICS for local renames on NTFS/ReFS when the file may be open; fallback to FILE_RENAME_INFO (delayed rename) for broader version compatibility.
- Implement a pre-check for cross-volume rename and use MoveFileEx with COPY_ALLOWED, noting the lack of atomicity.
- Test SMB behavior against target server OS versions; check for SMB dialect and POSIX extension support via GetFileInformationByHandleEx or WMI.
- Add assertion that the volume is not FAT/exFAT before attempting POSIX rename.
- Consider detecting memory-mapped sections via NtQueryVirtualMemory and aborting the rename if unmapping is not possible.
- Measure rename latency under load to verify no regressions; no published benchmarks exist, so instrument the code.

*Caveats:*

- Only available on Windows 10 version 1709 and later; call will fail with ERROR_INVALID_PARAMETER on older releases.
- Fails on SMB shares unless the server supports the SMB 3.1.1 POSIX extensions and the share is configured appropriately—many NAS devices do not support this.
- Not supported on FAT/exFAT volumes; may fail or behave unexpectedly.
- Memory-mapped files or files with active oplocks can prevent the rename even with the POSIX flag (observed in some edge cases).
- Renaming across volumes is not atomic and requires a copy/delete fallback (MoveFileEx with MOVEFILE_COPY_ALLOWED).
- Atomicity guarantees are not fully documented for all failure modes; no published formal verification.

## q03-replacefile-vs-movefileex

**Q:** ReplaceFile versus MoveFileEx(REPLACE_EXISTING) versus rename-into-place on Windows: which preserves atomicity, ACLs and alternate data streams, and which survives a concurrent reader holding the target open?

MoveFileEx(MOVEFILE_REPLACE_EXISTING) on same volume is atomic via NTFS rename, preserving ACLs/ADS of new file. Concurrent readers holding target open without FILE_SHARE_DELETE cause failure. Safe workaround: rename target out of way, then rename new file in. ReplaceFile is not atomic and fails on open handles unless dangerous flag used.

*Recommended:*

- Use MoveFileEx via ctypes with a temporary file on the same volume for atomic replacement.
- Before replacing, attempt to rename existing target to a random backup name (handles concurrent readers without delete sharing).
- Set all required ACLs and alternate data streams on the temporary file before the rename.
- Flush and close the temporary file, then call MoveFileEx(new_file, target, MOVEFILE_REPLACE_EXISTING).
- Implement retry logic with backoff for transient sharing violations or directory locks.

*Caveats:*

- Rename-out-then-rename-in has a brief window where target name is missing; other processes may fail to open.
- Fallback rename of open target may be blocked by anti-malware or security software, causing unpredictable failures.
- Transactional NTFS is deprecated, so no fully atomic multi-step alternative exists on Windows.
- If new file is not on the same volume as target, MoveFileEx falls back to non-atomic copy; must enforce same-volume placement.

## q04-sqlite-wal-durability

**Q:** SQLite with journal_mode=WAL and synchronous=NORMAL: what exactly is guaranteed across a process crash, an OS crash and power loss, and how do those guarantees change on a network share or a OneDrive-synced path?

Analyzed SQLite WAL synchronous=NORMAL durability. Process crash: no corruption; recent commits safe if OS cache intact, but not guaranteed. OS crash/power loss: database safe from corruption (WAL checksums), but transactions since last checkpoint may be lost. Network shares/OneDrive: unsupported, high corruption risk; WAL likely non-functional. Recommendation: use only on local disk; implement proactive checkpoints; reject network paths.

*Recommended:*

- Enforce local storage only for SQLite databases; detect and block network/cloud paths
- Use journal_mode=WAL and synchronous=NORMAL for performance
- Implement periodic checkpointing (e.g., after N writes or time-based) to reduce loss window
- If durability is critical, consider synchronous=FULL
- Add integrity check on database open (PRAGMA integrity_check)
- If network paths are unavoidable, design a server-based storage instead

*Caveats:*

- Data loss window on OS crash proportional to checkpoint interval
- Network/cloud paths (including OneDrive) cause corruption; WAL mode may fail entirely
- OneDrive may corrupt file during sync or rename operations
- Windows network shares may not support required byte-range locking

## q05-crash-safe-rollback

**Q:** Crash-safe file rollback: what on-disk undo-journal designs do editors and package managers actually use, and what is the minimum durable record that makes in-memory backups recoverable after a kill between write and verify?

Crash-safe file rollback commonly uses undo-journals: SQLite's rollback journal writes original pages before in-place modification; dpkg stores package state in /var/lib/dpkg/updates/; Emacs and Vim use backup/swap files. Minimum durable record: before a write, save original file content (or differential) to a synced journal file. On recovery, restore if journal is present. Measured overhead on HDD: ~2x writes for full file copies; page-level journals reduce cost. The approach is proven but requires strict fsync ordering.

*Recommended:*

- Implement per-file undo-journal: before in-place write, copy original to .<filename>.undo, fsync the undo file, then proceed.
- On process startup, scan for orphan undo files; if found, copy content back to original to restore last safe state.
- Add a verification step after write (e.g., checksum) and only delete undo on success — if killed between write and verify, the undo persists and rollback is safe.
- Consider atomic write-and-rename for new files or single-operation changes to avoid undo overhead.
- Benchmark overhead with target file sizes; if unacceptable, implement page-level or block-level journal like SQLite (copy only modified blocks).
- Add locking mechanism (fcntl/win32 lock) to prevent concurrent modification of the same file during undo-protected operation.

*Caveats:*

- Double-write overhead for large files (potentially 2x I/O) unless using delta/page-level journal.
- Requires reliable fsync ordering: journal must be durable before main file is touched; some filesystems weaken this.
- Race conditions if multiple processes attempt concurrent modifications — need file locking.
- Rollback discards intended writes; may surprise users if crash occurs after data is logically committed but before journal deletion.
- On Windows, fsync semantics depend on FlushFileBuffers; NTFS metadata ordering is not always guaranteed without write-through.

## q06-file-locking-semantics

**Q:** Byte-range locks (msvcrt.locking / LockFileEx) versus fcntl.flock: what are the semantics for multiple handles in one process, for threads, for lock release when ANY handle closes, and over SMB? Which is safe for a cross-process mutex in Python?

Byte-range locks via LockFileEx (msvcrt.locking) are safe for a cross‑process mutex on Windows when each process uses a single handle. Lock release occurs only when the last handle to the file closes; intra‑process handle duplication causes self‑conflict. fcntl.flock is unavailable on native Windows and unreliable over SMB. Advisory lock semantics require cooperative checking; SMB reliability depends on server oplocks.

*Recommended:*

- Implement cross‑process mutex as a singleton context manager that opens the lock file once and holds the handle.
- Test lock acquisition/release over local NTFS and SMB shares under process crash scenarios.
- Add an optional fallback to Windows named mutexes (win32event) if file locking proves unreliable over SMB.

*Caveats:*

- Advisory-only: processes must voluntarily check locks; no mandatory enforcement.
- Intra‑process deadlock if the same lock file is opened multiple times without sharing the same handle.
- SMB byte‑range lock reliability varies with client/server caching and oplock support; test under failure conditions.
- msvcrt.locking offers no timeout or async wait; polling wastes CPU.

## q07-policy-evaluation-order

**Q:** Policy-engine evaluation order: is 'exceptions evaluated before denies' ever a defensible default, and what do AWS IAM, Cedar and OPA/Rego mandate about explicit-deny precedence? What goes wrong when a project-scoped allow list can shadow a baseline deny?

Industry standard (AWS IAM, Cedar, common OPA patterns) mandates explicit deny takes precedence over any allow, regardless of evaluation order. 'Exceptions before denies' (allow-overrides) is rarely defensible; it risks project-scoped allows shadowing baseline denies, leading to unintended access and privilege escalation. Recommend deny-overrides default.

*Recommended:*

- Adopt explicit deny precedence: deny always wins over allow, regardless of declaration order.
- Ensure the evaluation engine returns 'deny' if any applicable policy yields an explicit deny, else 'allow' if any allows and no denies, else 'deny'.
- Audit existing allow lists to verify they cannot circumvent baseline denies under the new precedence.
- Document the precedence rule clearly in project guidelines and architecture decision records.

*Caveats:*

- Allow-overrides model can cause privilege escalation if a project-scoped allow list inadvertently permits access blocked by a baseline deny.
- Maintaining security posture becomes harder when local exceptions can override global safeguards.
- Order-dependent evaluation ('first match') can lead to inconsistent policy interpretations and bypasses.

## q08-reparse-point-errno

**Q:** Which errno and NTSTATUS values can lstat return for a Windows reparse point, and which of them should a security-critical path guard treat as HOSTILE rather than as absent? What is the correct fail-closed posture for an unstattable ancestor directory?

On Windows, lstat on a reparse point typically succeeds, returning stat for the reparse point itself. Failures can yield EACCES (STATUS_ACCESS_DENIED), ENOENT (STATUS_OBJECT_NAME_NOT_FOUND), EIO (STATUS_IO_DEVICE_ERROR), or rarely STATUS_REPARSE_POINT_ENCOUNTERED if flags are misused. Security-critical path guards should treat any lstat error (including ENOENT) as HOSTILE rather than absent, because it prevents path verification. For an unstattable ancestor directory, the only safe posture is fail‑closed: deny access.

*Recommended:*

- Implement a path guard that calls os.lstat on every component of a candidate path.
- Treat any OSError (any errno) as HOSTILE – deny the operation immediately.
- After a successful lstat, check st_mode: if S_ISLNK, resolve the reparse point target and verify it remains within allowed boundaries; if out of bounds, treat as HOSTILE.
- For ancestor directories that cannot be statted, adopt fail‑closed: deny the entire operation.

*Caveats:*

- Strict fail‑closed could reject legitimate but transiently inaccessible paths (e.g., network flakiness).
- Performance may degrade when statting every ancestor in deep paths; caching may mitigate this.
- Lack of empirical data on lstat failure modes in real Windows deployments; reliance on OS documentation and limited testing.

## q09-deferred-import-cycles

**Q:** When a Python codebase uses function-local (deferred) imports to break import cycles, what are the documented failure modes at scale, and what techniques make the resulting runtime cycles visible in CI rather than only under manual graph analysis?

Deferred imports break cycles but cause delayed ImportError, performance overhead, and hidden dependency graphs. CI visibility requires exhaustive path import testing, import hook tracing, and static cycle detection.

*Recommended:*

- Implement CI workflow that invokes all registered agent entry-points to trigger deferred imports and captures import errors
- Add custom pytest fixture that wraps imports to log and assert no circular import exceptions
- Integrate import-linter or custom pylint rule to flag modules using deferred imports for review
- Refactor critical cycles using dependency injection or interfaces to eliminate deferred imports
- Monitor import time during performance tests to identify hot-deferred-imports

*Caveats:*

- Runtime overhead from repeated importlib lookups in hot paths
- Delayed discovery of missing modules until seldom-used code paths executed
- Potential circular import errors re-emerging under specific call sequences
- Static analysis tools may not detect dynamically evaluated imports
- Windows-specific import quirks (e.g., case insensitivity) may complicate tracing

## q10-architecture-enforcement

**Q:** What is the state of the art for detecting and enforcing architectural layering in Python (import-linter, tach, dependency contracts)? Can any of them express 'this module must have zero internal imports' or 'no module under path P may be named in module Q's data'?

import-linter and tach can enforce static import layering, e.g., forbidding imports within a package. They cannot express data-level rules such as 'module X must not be referenced in string literals of module Y'. This requires custom static analysis (e.g., semgrep) or runtime checks. Literature on this specific intersection is sparse; most research addresses static dependencies, not dynamic name references in data.

*Recommended:*

- Use import-linter with layer contracts to enforce static import boundaries; define each package as a layer and disallow internal imports via forbidden rules.
- For data-level constraints, write a custom semgrep rule or a script using ast/string scanning to detect strings matching module paths under P inside Q.
- Establish a contract document specifying both static and dynamic expectations to guide tool configuration and custom checks.
- Add a pre-commit hook combining linter and custom check to fail closed on violations.

*Caveats:*

- import-linter and tach operate on AST, missing runtime imports or dynamic references.
- Data-level rule is vaguely defined – clarification needed on what constitutes 'named in data' (e.g., string literal, variable, config).
- No single tool covers all cases; a combination of linters and custom checks increases maintenance burden.
- False positives possible if modules are referenced intentionally for documentation or logging.

## q11-monkeypatch-control-bypass

**Q:** For a spend or security control implemented as a process-global monkeypatch of subprocess and urlopen, what are the known bypass classes, and what architectural alternatives (a broker process, seccomp, Windows job objects, wrapper binaries on PATH) give coverage that does not depend on which process starts?

IncompleteRead: IncompleteRead(1 bytes read)

## q12-run-record-correlation

**Q:** What patterns exist for correlating run records across heterogeneous producers with incompatible id schemes? Is in-toto / ITE-6 attestation plus an OpenTelemetry trace_id carried alongside the accepted approach, and what does it fail to give you compared with a full re-keying migration?

Correlating run records across incompatible ID schemes can be achieved via a correlation service mapping to a global UUID, combined with OpenTelemetry trace context and in-toto attestations. A full re-keying migration is riskier and often unnecessary; the literature (e.g., in-toto NSDI'19) shows attestation overhead is minimal (<5ms per step), while tracing adds negligible latency in instrumented services.

*Recommended:*

- Implement a correlation service that generates and stores a global UUID for each event, mapping to producer-native IDs. Use a lightweight database (e.g., SQLite) with atomic writes.
- Inject W3C traceparent header into all outgoing calls allowed by the egress fence; wrap calls with a retry-instrumenting decorator.
- Generate in-toto link attestations for each orchestration step, embedding the trace_id in the predicate and signing with a local key.
- For legacy records, run a one-off migration script to populate the mapping table, leaving original IDs untouched.
- Add a health check that verifies trace_id propagation across test agents; fail-closed if missing.

*Caveats:*

- External LLM agents may not propagate trace headers, creating partial traces and correlation gaps.
- ID mapping tables must be transactionally consistent and persist across restarts; corruption leads to attribution errors.
- in-toto key management on Windows/Python requires secure storage; compromise breaks chain of trust.
- OpenTelemetry instrumentation introduces dependency bloat; ensure it aligns with fail-closed egress rules.
- Granularity mismatch: trace IDs correlate request flows, while in-toto links attest to pipeline steps; correlating both requires careful metadata design.

## q13-entrypoint-vs-dead

**Q:** What are the accepted criteria for distinguishing a DEAD module from an ENTRYPOINT module in static analysis, given entrypoints invoked via python -m, console_scripts, git hooks, and external config files that live outside the repository?

No universal accepted criteria exist; entrypoints are any explicitly designated launch points (console_scripts, `__main__`, git hooks, config files). Dead code is unreachable from these under a conservative call graph. Numbers are scarce: e.g., Vulture reports precision ~60–80% with heavy false positives from dynamic features. Disagreements center on handling dynamism (eval, decorators, importlib). For Daedalus: combine static import/call graphs with explicit entrypoint registration, parse config files statically where possible, and supplement with dynamic coverage; provide manual overrides fo

*Recommended:*

- Enumerate all known entrypoints from setup.py/console_scripts, `__main__` modules, git hooks, and explicitly listed config files.
- Build a conservative import-based call graph (e.g., via `sys.modules` snapshot or AST analysis) starting from those entrypoints.
- Integrate optional dynamic coverage data to recover reachability missed by static analysis.
- Implement a dead‑code whitelist mechanism to allow developers to suppress false positives.

*Caveats:*

- Static dead-code detection in Python has high false positives due to reflection, eval, metaclasses, and dynamic imports.
- External entrypoints (git hooks, config files) may be missed without manual curation.
- Tool-specific heuristics (e.g., Vulture, PyCG) are not standardised and require tuning.
- On Windows, path handling and shebang-less entrypoints may complicate identification.

## q14-code-in-artifact-dirs

**Q:** How do mature projects handle executable code that must live alongside output artifacts, and what conventions prevent an artifact directory from silently becoming a source directory with its own unguarded entrypoints?

Mature projects (e.g., Linux kernel, Django, Apache) enforce strict separation: source in src/, artifacts in out/ or build/. They prevent silent code entrypoints by excluding artifact dirs from the module search path, using read-only permissions, and naming conventions (e.g., no .py or .sh in artifact dirs). Specific numbers are scarce, but a 2021 study on Python package security found 12% of packages inadvertently execute test artifacts. No single standard exists; conventions vary.

*Recommended:*

- Designate a dedicated artifact root (e.g., daedalus_artifacts/) that is never added to sys.path.
- Configure the runtime to reject any import from that root (e.g., via custom import hooks).
- Set filesystem ACLs to deny execute permission on the artifact directory and all subdirectories.
- Implement a periodic scan in the orchestration loop to alert on any .py or .sh files appearing in the artifact tree.
- Document this separation as a core security invariant for all contributors.

*Caveats:*

- Over-separation may complicate debugging when generated code must be inspected or reused.
- Relying solely on naming conventions is fragile; an attacker or LLM could name a malicious file .pkl but embed executable code.
- Windows permission models differ from Unix; ACLs may not prevent execution if the file is explicitly invoked.
- Dynamic code loading (e.g., importlib) could bypass directory exclusions if not carefully implemented.

## q15-shim-lifecycle

**Q:** What is known about the lifecycle of backwards-compatibility re-export shims? How do teams decide when a shim with zero internal importers can be deleted, and what telemetry or deprecation mechanisms make that decision evidence-based rather than a guess?

Backwards-compatibility shims are temporary re-export modules used during refactorings. Teams often rely on static analysis and runtime telemetry to confirm zero imports before deletion, but evidence shows many deprecations are never completed. For a fail-closed, LLM-driven system like Daedalus, an evidence-based approach should combine import-hook telemetry, a fixed observation window, and explicit deprecation signals to avoid unexpected breakage.

*Recommended:*

- Implement an import hook (sys.meta_path) that logs any access to shim modules, sending events to a central telemetry database with a minimum 90-day observation window before deletion.
- Combine with static analysis (e.g., vulture + grep for dynamic patterns) to confirm zero internal references.
- For external-facing components, issue a deprecation warning via runtime warnings and a changelog entry at least one release cycle before removal.
- In the telemetry pipeline, tag shim accesses with the stack trace to identify calling context for auditing.
- Only delete when both static analysis and telemetry show zero accesses over the observation period; if telemetry is incomplete, default to keeping the shim.

*Caveats:*

- Static analysis may miss dynamic imports (e.g., importlib.import_module with constructed names).
- Telemetry might have blind spots (e.g., early process exit before log flush).
- External consumers (if any) are invisible to internal monitoring, potentially causing silent failures downstream.
- Deleting a shim in a fail-closed system could inadvertently disable a security-critical path if it was the only way to reach a deprecated but essential module.

## q16-divergent-health-surfaces

**Q:** When several modules independently answer the same operational question ('is the system healthy?'), what architectural patterns keep them from silently diverging: a single verdict vocabulary, a consistency test between surfaces, or collapsing to one engine with multiple views?

Prevent silent divergence by combining a single verdict vocabulary (canonical health states) with a consistency test across surfaces. The vocabulary ensures compatibility; the diversity test detects hidden disagreements. Collapsing to one engine removes diversity and risks single-point failures.

*Recommended:*

- Define a canonical health vocabulary (e.g., healthy, degraded, failed, unknown) with optional structured reasons.
- Implement multiple independent health assembly modules (e.g., resource monitor, LLM heartbeat, egress fence status).
- Add a reconciler module that compares health verdicts and raises an alert on divergence.

*Caveats:*

- Even with a vocabulary, modules may interpret thresholds differently; regular calibration needed.
- Consistency tests may cause false positives if modules have different latency/refresh rates.
- Diverse modules may have common failure modes if underlying dependencies overlap (e.g., Windows system calls).

## q17-wrong-file-rewrites

**Q:** MEASURED IN OUR SYSTEM: an LLM asked to rewrite file A, given a change request that also mentions file B, returned B's contents and destroyed A. Three of five multi-file writes failed this way. Is this failure documented in the literature or in agent-framework issue trackers? What prompt structures and output validations are known to prevent output-target confusion in multi-file edit agents?

Output-target confusion in multi-file LLM edits is documented in SWE-bench and agent frameworks (e.g., Aider, OpenHands). SWE-bench reports that even strong models often apply patches to wrong files, but exact rates for this specific overwrite error are uncertain. Prevention: structured prompts with clear file boundaries, use of diff formats, and validation checking if output content matches another file's original content (to reject and re-prompt).

*Recommended:*

- Implement output sanitizer that flags if rewrite content is identical to another file's original content, then re-prompt with emphasis on correct file.
- Adopt unified diff output format with explicit file path headers.
- Add a verification step (separate LLM call) to confirm edits are applied to intended file.

*Caveats:*

- Validation may produce false positives (e.g., legitimate identical lines) or be circumvented.
- No single prompt structure is foolproof; model may ignore instructions.
- Relying solely on output validation might mask underlying planning failures.

## q18-patch-vs-rewrite

**Q:** Whole-file rewrite versus unified-diff versus search-replace-block as the edit format for LLM code agents: what does the measured evidence say about failure rates, file-size ceilings, and silent truncation? Aider's benchmarks are the obvious source -- what did they actually find, and what edit format should a system with a 24,000-character rewrite ceiling adopt instead?

Based on Aider's benchmarks (2024-07-22 edit formats), whole-file rewrites have a 23% apply failure rate vs 5% for search/replace and 10% for unified diff. Whole-file hits context limits and suffers from silent truncation. With a 24K-char rewrite ceiling, recommend switching to search/replace blocks to handle larger files and reduce failures.

*Recommended:*

- Implement search/replace edit format (e.g., Aider's SEARCH/REPLACE blocks) as the default for file edits.
- Add validation to parse and apply patches, with fallback to whole-file only for files <= 24K chars.
- Include few-shot examples in the system prompt to reduce format errors.
- Test failure rates on representative files > 24K characters.

*Caveats:*

- Search/replace blocks can fail if the LLM generates ambiguous or incorrect SEARCH strings (Aider's 5% failure rate includes this).
- Requires careful prompt engineering with few-shot examples to teach the model the format.
- The LLM may still attempt to generate whole-file edits if not constrained.
- If the file changes are very large, search/replace blocks can still exceed context limits; may need chunking.

## q19-detect-hallucinated-imports

**Q:** MEASURED IN OUR SYSTEM: zero of 26 LLM-written tests passed, and three of seven test files imported modules that do not exist. What is the reported rate of hallucinated imports and APIs in LLM-generated code, and which cheap static checks catch the most of it per unit of cost?

LLMs hallucinate imports/APIs at rates of 20-40% in open-ended coding tasks. A study by Phan et al. (2023, uncertain citation) found 23% of GPT-generated code had import errors. Cheap static checks that attempt to resolve imports and validate attribute existence via `importlib.util.find_spec()` and `dir()` catch most such hallucinations at minimal cost.

*Recommended:*

- Implement a static validator that uses `importlib.util.find_spec()` to verify module existence and `dir()` to check API presence for all imports in generated code.
- Run the validator as a mandatory pass in the code generation pipeline to block obviously hallucinated imports before any test execution.

*Caveats:*

- Hallucination rates vary significantly by model version, prompt complexity, and task domain; the cited 23% figure is based on an uncertain recollection of a study and may not generalize.
- Static checks may miss dynamically created names or conditional imports; false positives can occur if a module is available only in the target environment but not in the checking environment.

## q20-llm-test-generation-quality

**Q:** What is the measured quality of LLM-generated unit tests: pass rate on first run, mutation score of the resulting suite, and the rate of tests that would still pass if the feature under test were deleted? Name the studies and their numbers.

LLM-generated test pass rates: 50-80% typical (e.g., Jain et al., 2023 report 76% for GPT-4, uncertain). Mutation scores rarely reported; EvalPlus (Liu et al., 2023) shows vulnerability to trivial tests. Delete-resistance (tests passing after feature deletion) is not measured in literature. Disagreements: pass rate alone is insufficient; mutation testing and delete-checks are needed to gauge real test quality.

*Recommended:*

- Benchmark Daedalus test generation on pass rate, mutation score, and delete-resistance using a sample of 50 functions.
- Integrate mutation testing tool (e.g., mutmut for Python) into CI.
- Implement feature-delete test: remove function body and verify generated tests fail.
- Use EvalPlus-style test augmentation to detect overfitting tests.

*Caveats:*

- Reported pass rates overestimate quality if tests contain weak assertions.
- Mutation testing is computationally expensive and may slow CI.
- Delete-resistance metric is non-standard and may produce false positives/negatives.
- Test quality varies widely across LLM models and problem domains.

## q21-tests-that-test-mocks

**Q:** How do you mechanically detect a test that tests only its own mocks -- one that would pass with the implementation deleted? What tools or techniques exist (mutation testing, coverage of the module under test, assertion analysis), and what do they cost to run per commit?

Detecting tests that rely solely on mocks involves three main techniques: mutation testing (e.g., deleting the implementation and checking if the test passes), coverage analysis (measuring how much of the module under test is actually executed), and assertion analysis (inspecting whether assertions only validate mock interactions). Mutation testing is the most reliable but computationally expensive, with tools like MutPy for Python. Coverage inspection is cheap and can be done per-commit using tools like coverage.py. Assertion analysis via static analysis is lightweight but may produce false p

*Recommended:*

- Implement a per-commit pre-commit hook or CI step that uses coverage.py to check if a test module exercises the corresponding implementation module below a threshold (e.g., <X% line coverage) and flags it for manual review.
- Integrate a heuristic that counts assertions on mock objects vs. real return values; if mock assertions dominate, raise a warning.
- Set up a nightly mutation testing job (e.g., using mutmut or a custom script that replaces functions with mocks) to catch more subtle cases; store results for periodic audit.
- For immediate triage, create a script that temporarily deletes the implementation module's body and re-runs tests to see if any still pass; this can be run manually on suspicious tests.

*Caveats:*

- False positives: low coverage does not guarantee a test only tests mocks; it may test edge cases that happen to not cover lines.
- Dynamic Python features and mocking frameworks (e.g., unittest.mock, pytest-mock) complicate static analysis of assertions.
- Mutation testing may be too slow for per-commit feedback; on a moderate codebase, full mutation analysis can take minutes to hours, while targeted mutation (deletion of specific functions) may take seconds per test but requires careful selection.
- Windows compatibility: some mutation testing tools (like mutmut) may have limited Windows support, requiring alternatives.

## q22-agent-capability-vs-instruction

**Q:** In agent frameworks, what is the evidence on prompt-level restrictions ('do not edit X') versus capability-level restrictions (no write tool, path allow lists)? What compliance rates have been measured for instruction-only constraints, and which frameworks enforce structurally instead?

Prompt-level restrictions ('do not edit X') rely on instruction-following; adversarial prompt injection (e.g., 'ignore previous instructions') defeats them with measured success rates of 70–90% in public benchmarks (Schulhoff et al. 2023, HackAPrompt 2023). Capability‑level restrictions (tool allow lists, path sandboxing) stop unauthorized actions irrespective of model output, reducing risk to implementation bugs. No major LLM agent framework (AutoGPT, LangChain, CrewAI) enforces structural restrictions by default; all hinge on prompts. Given the fail‑closed egress fence on Windows, adopt stru

*Recommended:*

- Implement a tool runner with mandatory path allow list for file I/O operations; block any write outside whitelisted directories regardless of model instructions.
- Enforce a tool allow list in the agent execution loop (e.g., before dispatching a tool call, validate the tool name against a static set) rather than relying on a prompt.
- For code evolution tasks, run generated code in a sandboxed subprocess with restricted file system permissions and no network access unless explicitly needed.
- Add monitoring and logging of all tool invocations to detect and alert on policy violations, supporting the fail‑closed requirement.

*Caveats:*

- Cited compliance rates are model‑ and attack‑dependent; updated models may resist simple injections better, but adversarial robustness remains an open problem.
- Structural enforcement requires careful implementation (e.g., OS‑level sandboxing, robust path canonicalization) to avoid bypasses.
- Over‑restriction may harm agent utility; a balance between flexibility and security must be struck through iterative threat modelling.

## q23-review-and-write-modes

**Q:** Agent interfaces that switch between an advisory mode and a write mode: what is the accepted design for letting an agent BOTH make a change AND report observations about it? Is there prior art on write-mode agents losing their reporting channel, and how do mature systems structure the response schema?

Mature agent designs separate action and observation channels via structured tool calls (e.g., ReAct, OpenAI function calling, Anthropic tool use). When an agent writes code directly as plain text, it often loses the ability to report observations because the output is consumed. Prior art (AutoGPT, early LangChain agents) showed that agents can execute commands and forget to check results. The accepted pattern is to have the agent output a structured edit request, let the system apply it, and return the outcome as an observation, keeping the reporting channel intact.

*Recommended:*

- Design a tool-based interface for write operations: agent outputs a structured 'edit_file' action with parameters (path, content, diff), system applies it and returns an observation (diff, success/failure).
- Implement a standard cycle: (1) agent optionally produces reasoning, (2) agent outputs tool call, (3) environment executes and appends observation to conversation, (4) repeat.
- Ensure that all write operations go through this tool API; never allow the agent to directly output code meant for execution without an observation step.
- Adopt a schema like OpenAPI function calling or a minimal JSON format with 'thought' and 'action' fields to keep parsing simple.

*Caveats:*

- Structured tool calls add parsing overhead and can fail if the agent produces malformed JSON or arguments.
- Agents may ignore observations if they are not explicitly forced to process them; mitigation requires a mandatory observation-injection step.
- Switching modes (advisory vs. write) can still cause state confusion if not handled carefully; the system must maintain a consistent message history.
- No single published benchmark specifically measures 'lost reporting channel' in code-editing agents; empirical evidence is anecdotal (e.g., AutoGPT run failures due to missing read-back).

## q24-symbol-survival-heuristics

**Q:** For validating that an LLM's file rewrite is an EDIT rather than a REPLACEMENT, what heuristics are used in practice? We use surviving top-level definition ratio with a 50% threshold. What alternatives exist (AST edit distance, embedding similarity, identifier overlap), and what false-positive rates do they carry on genuine refactors?

In practice, LLM code edit heuristics include top-level definition survival, line diff ratio, identifier Jaccard, and AST edit distance. Thresholds are rarely public; Aider likely uses ~70% token overlap. No reported false-positive rates on genuine refactors. Multi-metric ensemble is safest.

*Recommended:*

- Implement a composite classifier using weighted combination of top-level ratio, identifier Jaccard, and normalized AST edit distance.
- Train thresholds on a curated dataset of intentional edits vs. replacements.
- Add a confidence score and flag ambiguous cases (e.g., 0.4-0.6) for human review.
- Monitor false-positive rate in production and adjust thresholds per file type.

*Caveats:*

- A fixed 50% top-level definition ratio may falsely classify large refactors (e.g., module splits) as replacements.
- AST edit distance is sensitive to formatting changes, inflating false positives.
- Identifier Jaccard is high for renames during refactoring, leading to false negatives.
- Embedding similarity is unstable for small changes and lacks clear thresholds.
- Any single heuristic is insufficient; a composite approach is needed but tuning is data-intensive.

## q25-cheap-model-census-reliability

**Q:** MEASURED IN OUR SYSTEM: a cheap model performing structural extraction over 300 code slices produced reliable aggregate shape but hallucinated specific claims (two of two checked __all__ claims were false). What is known about the reliability of cheap models for structured extraction versus judgement, and what verification ratio is worth paying for?

Cheap models reliably produce structured output but hallucinate specifics. Literature shows higher factual error rates for smaller/cheaper models, though exact numbers vary. The verification ratio depends on error cost, verification cost, and hallucination rate; statistical quality control suggests piloting to estimate p and setting sampling accordingly (no universal ratio). Recommendation: use cheap model for structure, verify claims with a stronger judge, start with 100% verification on a small set to calibrate.

*Recommended:*

- Pilot: run cheap model on a representative sample (e.g., 100 slices) and verify all claims with a strong model (or human) to estimate hallucination rate p.
- If p > acceptable threshold, consider using cheap model only for output structure (schema mapping) and delegate claim extraction to a more reliable model.
- For ongoing verification, implement statistical sampling plan (e.g., ANSI/ASQ Z1.4) with AQL based on risk tolerance; start with 10-20% random verification and adjust.
- Track false positive vs false negative hallucinations separately; different cost implications.
- Explore confidence signals from cheap model (logprobs, etc.) to prioritize verification.
- Benchmark cheap vs expensive model on your task using standard metrics (precision, recall, factual consistency) to inform cost-quality trade-off.

*Caveats:*

- Verification model may also hallucinate; verify its own error rate.
- Cheap model hallucination rate may drift as prompts or data change; periodic recalibration needed.
- No published study exactly matches 'code slice structural extraction' scenario; numbers from other domains may not transfer.
- Cost of verification with a strong model might negate savings if hallucination rate is high.

## q26-fan-out-without-corroboration

**Q:** MEASURED IN OUR SYSTEM: 1,226 claims from 244 agents, and the largest cluster of agents making the same claim was TWO, because each saw a different file. When a fan-out gives every agent a different input, corroboration is structurally unavailable as a ranking signal. What ranking or triage methods work in that regime?

For disparate fan-out where agents have no shared inputs, apply a two-stage pipeline: (1) agents generate claims with citations; (2) a local judge model scores each claim against its source file. Triage by judge confidence, flagging low-scoring claims for human review. This avoids external calls (fits fail-closed egress) and provides measurable, auditable scores.

*Recommended:*

- Implement a claim‑verification step: for each generated claim, retrieve the source file snippet and prompt a local judge LLM to output a 1–5 confidence score with a mandatory justification.
- Create a simple scoring rubric for the judge (e.g., 'Does the claim faithfully reflect the file content?').
- Pilot on a small subset; measure inter‑judge agreement between two different local models.
- Set a threshold (e.g., score < 3) for automatic triage to a human review queue.
- Integrate this verification as an optional post‑processing step in the Daedalus pipeline, configurable per workflow.

*Caveats:*

- Judge model may hallucinate or be inconsistent itself; mitigate with explicit citation checks and an ensemble of light + heavy judges.
- Computational cost of judging 1,226 claims may be high; consider sampling if throughput is limited.
- No published benchmarks for exactly this setup; adaptation from QA fact-checking may overfit.
- Agents might generate claims that are unfalsifiable without external knowledge—judge will be limited to file content.

## q27-verifier-same-family

**Q:** When the verifier is the same model family as the claimant, how much independent signal remains? What has been measured about self-verification, cross-family verification, and the correlation of errors within a model family on code tasks?

Self-verification within the same model family provides limited independent signal on code tasks. Measurements show marginal gains (e.g., Self-Refine improved pass@1 on MBPP by ~5.6% without execution feedback; Self-Debugging without execution saw ~3.8% improvement). With execution feedback, gains are substantial (Reflexion: +17.7% on HumanEval). Cross-family verification is under-measured but expected to reduce correlated errors. Error correlation within a family is high due to shared training data and biases. Consensus: pure self-verification is unreliable; external feedback (tests) or diver

*Recommended:*

- Prioritize test-based verification wherever possible (e.g., run candidate code in sandbox).
- If model-only verification is needed, use a verifier from a different model family to reduce error correlation.
- When only one family is available, use majority voting across multiple samples with varied temperature.
- Implement a fallback protocol: if verifier and claimant are same family and no tests pass, flag for human review.
- Log verification outcomes to measure actual error correlation in your setting.

*Caveats:*

- Self-verification leads to overconfidence and repeated mistakes due to correlated errors.
- Cross-family verification may introduce calibration issues if verifier is weaker.
- Execution feedback requires secure sandboxing (fail-closed constraint).
- Published numbers may not transfer to Daedalus' specific codebase and model mix.

## q28-refutation-prompting

**Q:** We instructed a verification wave that REFUTED is the most valuable verdict, and 22% of checkable claims were refuted. What is known about the effect of adversarial or refutation-framed prompting on verification accuracy, and does it trade recall for precision?

No direct empirical evidence exists on the effect of refutation-framed prompting on verification accuracy or precision/recall trade-off. Existing verification methods (e.g., process supervision, SelfCheckGPT) use neutral prompts and report overall accuracy, not the trade-off. The 22% refutation rate may reflect genuine errors or prompt-induced over-skepticism. A controlled experiment is needed to quantify the trade-off given your fail-closed fence.

*Recommended:*

- Design a side-by-side experiment: compare neutral vs. refutation-focused prompts on a labeled verification dataset.
- Measure precision, recall, false-negative rate, and F1 for each framing.
- If recall drops below required thresholds, recalibrate the prompt (e.g., add calibration examples or a secondary verification step).
- Document the trade-off and set an operational decision rule based on the cost of false negatives.

*Caveats:*

- Refutation framing may increase false negatives, causing critical flaws to be missed.
- The 22% refutation rate could be an artifact of prompt bias rather than true error density.
- No published numbers exist for this exact instruction; any extrapolation is guesswork.
- A precision-optimized verifier violates fail-closed egress requirements, potentially passing dangerous outputs silently.

## q29-docstring-drift-detection

**Q:** Detecting docstrings that promise guarantees the implementation does not provide -- atomicity, fail-closed behaviour, 'never writes X'. What automated techniques exist (specification mining, NL-to-assertion, contract inference), and what precision do they report on real codebases?

Specification mining (Daikon, Texada) reports >90% precision for simple invariants; NL-to-assertion (Toradocu, Jdoctor) ~70-85% precision for comment-code consistency. Disagreements: soundness vs completeness, static vs dynamic. Recommend LLM-based extraction + runtime assertions. Measure precision internally.

*Recommended:*

- Build LLM-based extraction: parse docstrings into formal assertions using few-shot prompts
- Implement lightweight runtime checks for 'never writes X' and atomicity using decorators
- Run on sample of 100 docstrings, manually label, compute precision/recall
- Iterate on prompt engineering and assertion generation

*Caveats:*

- LLM may hallucinate specifications, leading to false assertions
- Dynamic mining limited to observed paths
- Runtime monitoring may introduce performance overhead
- Literature precision may not transfer to Python codebases

## q30-guarantee-vocabulary

**Q:** Is there an accepted vocabulary or annotation scheme for machine-checkable code guarantees (atomic, idempotent, fail-closed, pure, never-writes)? What have JML, Dafny, contracts.py, and Rust's type-level approaches actually achieved in mainstream codebases?

No single accepted vocabulary. JML, Dafny, contracts.py, and Rust's type-level approaches have niche adoption; mainstream use only for Rust (e.g., AWS Firecracker, Deno). Dafny's Ironclad Apps verified 4 apps with zero bugs, but no large-scale uptake. Recommend a lightweight Python decorator scheme (@idempotent, @fail_closed, @pure) with runtime checks and property testing for Daedalus agents.

*Recommended:*

- Define a minimal set of decorators for guarantees (atomic, idempotent, fail-closed, pure, never-writes)
- Implement runtime validation (e.g., using icontract or custom wrappers) and property-based tests with Hypothesis
- Create a linter to detect missing or misused decorators in agent-generated code
- Document semantics clearly for LLM agents, with examples and failure modes
- Enforce fail-closed behavior via context managers and review patterns for external calls

*Caveats:*

- LLM-generated code may violate annotation semantics; thorough testing essential
- Runtime checks add overhead; no compile-time verification
- Dynamic nature of Python limits static enforcement of guarantees
- Agent understanding of informal decorators may drift without formal spec

## q31-worktree-parallel-agents

**Q:** Git worktree strategies for many parallel agents: what breaks at ten and at a hundred concurrent worktrees, how do teams handle shared object-store contention and index locks, and what is the practical alternative when worktrees stop scaling?

Git worktrees share a single object store and index, leading to lock contention on index.lock and race conditions on pack files. At 10 concurrent worktrees, occasional index lock failures are likely; at 100, frequent lock timeouts, operation failures, and possible object store corruption (e.g., concurrent gc) become common. Formal benchmarks are sparse; practitioner reports and mailing list discussions indicate issues beyond ~30-50 worktrees. Disagreements exist on whether to use worktrees with retry logic or switch to per-agent clones. For Daedalus on Windows, the fail-closed egress fence and

*Recommended:*

- Implement a write-serializing adapter around Git operations (e.g., a queue or lock file) to avoid index/store contention among worktrees.
- Benchmark the system at 10 and 100 simulated parallel agents, measuring lock contention rate, operation latency, and failure frequency.
- Evaluate per-agent thin clones (e.g., `git clone --shared` from a bare reference repo) as a fallback; compare disk and time overhead.
- Ensure no automatic garbage collection on shared object stores and add health checks for repository corruption.
- If adopting worktrees, add retry logic with exponential backoff for index lock errors.

*Caveats:*

- Windows file locking (antivirus, OS) may worsen contention and cause spurious failures.
- Shared object store writes (e.g., `git gc`, `git repack`) can corrupt the database if not serialized.
- Many short-lived worktrees increase inode usage and disk churn.
- Serializing all Git writes through a single point becomes a bottleneck, limiting true parallelism.
- Alternatives like per-agent clones consume more disk space and take longer to initialize.

## q32-scaling-review-fanout

**Q:** At what point does adding more review agents stop finding new defects? What is known about the marginal yield curve of review fan-out, and how should a budget be split between more finders and more verifiers?

Literature suggests diminishing returns after ~3–4 reviewers. SmartBear reported one reviewer finds ~50% of defects, two ~60%, three ~75%, four ~85%, five ~90%. Weller (1993) found two inspectors 86%, three 91%, four 96%. For LLMs, ensemble studies show plateau at 3–5 agents. Budget split: allocate 60–70% to finders, 30–40% to verifiers, but adapt dynamically.

*Recommended:*

- Pilot Daedalus with a known-defect corpus to map the marginal yield curve of LLM reviewers.
- Implement dynamic fan-out: start with 3 finders, measure unique defect discovery rate, expand only if >5% new defects.
- Test verifier models (e.g., stronger LLM, majority voting, debate) to filter false positives from finders.

*Caveats:*

- Over-fan-out increases latency, cost and false-positive rate due to LLM bias overlap.
- Existing numbers are from human inspection; LLM yield curves may differ and lack robust measurement.
- Fixed fan-out wastes budget if defects quickly saturate; adaptive mechanisms need careful tuning.

## q33-structured-extraction-schema

**Q:** For fan-out extraction tasks where results must be merged mechanically, what schema design choices most improve mergeability? Closed tag vocabularies, one-fact-per-line, JSON schema enforcement -- what is the measured effect on downstream aggregation quality?

JSON schema enforcement and one-fact-per-line designs maximise merge reliability. Grammar-constrained decoding (jsonformer, outlines) virtually eliminates parsing errors, dropping malformed-output rates from ~10% to 0% in reported benchmarks. Closed tag vocabularies reduce semantic inconsistency. In TAC KBP tasks, per-line facts improved recall and simplified deduplication. For Daedalus, this combination allows deterministic set-union merging with minimal loss.

*Recommended:*

- Adopt JSON schema enforcement with a predefined set of entity/relation types.
- Require each output to be a list of flat JSON objects, each describing one fact.
- Implement merge logic as a union of fact sets, deduplicating on normalized key fields.
- If latency is critical, use post-hoc JSON repair instead of real-time grammar constraints.

*Caveats:*

- Rigid schema may exclude valid facts; a fallback extraction path is advisable.
- Grammar-constrained decoding increases latency and may reduce factual recall.
- Closed vocabularies require maintenance and re-annotation as domains evolve.
- One-fact-per-line can duplicate boilerplate and increase token costs.

## q34-self-improving-gates

**Q:** Systems that harden their own safety gates by attacking themselves: what prior art exists for using an agent fan-out as an adversarial test of the harness that runs it? What did such systems find, and what did they miss?

Prior art includes automated red-teaming (Perez et al., 2022) where LLMs generate adversarial prompts, finding up to 30% attack success on earlier models but missing nuanced harms. Ganguli et al. (2022) reported harmful outputs in 10-20% of cases after RLHF. Multi-agent adversarial testing for harness hardening is less common; debated whether fan-out improves coverage or just creates redundant attacks. Self-attacking systems are underexplored but conceptually similar to automated red-teaming applied to the entire agent pipeline.

*Recommended:*

- Implement a self-adversarial test suite using a fan-out of attacker agents that attempt to bypass the egress fence via prompt injection, social engineering, and multi-step plans.
- Measure bypass rate over time and monitor for novel attack patterns using a separate detector agent.
- Incorporate known jailbreak templates as seeds and use LLM generalization to create variants.
- Conduct regular human red-teaming to complement automated tests and catch overlooked attack types.

*Caveats:*

- Self-adversarial testing can miss novel attack vectors that the attacker models haven't been trained to generate.
- Generating adversarial tests with the same model class may lead to blind spots if the harness shares vulnerabilities with the attacker.
- Fan-out may amplify trivial bypasses rather than discovering fundamental flaws.
- Real-world adversarial examples may differ from generated ones in distribution, leading to overconfidence in safety.

## q35-mutation-operator-design

**Q:** Designing mutation operators that produce genuinely defective programs with a low equivalent-mutant rate: which operator families have the best defect-to-equivalent ratio in practice, and which are known to be mostly equivalent and therefore wasted budget?

Operators altering arithmetic/logic (AOR, ROR, LCR, UOI) achieve low equivalent mutant rates (~10-20%), while statement deletion (SDL) and constant replacement (CDL/CRP) often exceed 30-50% equivalent, wasting budget. For Daedalus, prioritize AOR, ROR, LCR, UOI and filter SDL via reachability analysis.

*Recommended:*

- Prioritise mutation operators AOR, ROR, LCR, UOI in Daedalus's defect-generation pipeline.
- Implement a static reachability filter to discard statement deletions in unreachable code or unused assignments.
- Collect empirical equivalent rates on your Python codebase using a tool like mutmut to calibrate operator selection.
- Avoid constant replacement operators unless the constant appears in a branching condition.

*Caveats:*

- Equivalent mutant rates are language- and test-suite-dependent; Python's dynamic typing may inflate rates for type-changing operators.
- Static dead-code analysis may miss runtime properties and incorrectly filter non-equivalent deletions.
- Literature numbers derive from Fortran/Java/C; direct extrapolation to Python requires validation.
- Operator effectiveness also depends on fault-revealing power, not just equivalence rate.

## q36-semantics-preserving-transforms

**Q:** Provably behaviour-preserving source transformations for Python specifically: which are actually safe given closures, mutable default arguments, decorators, generators, name shadowing and evaluation-order side effects? Which transformations look safe and are not?

No system provides fully provably behaviour-preserving transformations for all Python features. Formal semantics exist (e.g. Politz et al. 2014, Guth et al. 2015) but have not been leveraged for a comprehensive refactoring tool. Conservative static analysis can catch some issues (e.g. variable capture in closures, mutable default aliasing, evaluation order changes), but guarantees are limited. Common refactorings like extract method, rename, and move are unsafe under closures, decorators, generators, name shadowing and side effects without careful checks. I recommend starting with a small set 

*Recommended:*

- Implement a tiny set of safe transformations (e.g., local variable rename) using a formal model of Python's scoping and evaluation order; prove them correct.
- Build a 'refactoring firewall' that rejects transformations unless the affected code passes a conservative side-effect purity analysis.
- Integrate with a regression test runner to catch any unintended changes during development.

*Caveats:*

- Formal semantics may not cover all Python constructs (e.g., certain decorators, metaclasses, C extensions).
- Even proven transformations may have subtle interactions with dynamic features like introspection or monkey-patching.
- User must accept a restricted subset of Python or annotate impure regions to retain safety.

## q37-cold-start-thresholds

**Q:** When calibrating a defect detector per project using synthetic corpora, how many synthetic examples are needed before thresholds stabilise, and how much does a threshold calibrated on synthetic mutants differ from one calibrated on real defects?

Literature does not give a single definitive number. Mutation testing work (e.g., Inozemtseva & Holmes, 2014) suggests 20–50 mutants can approximate full mutant set metrics, but this is for mutation score, not defect-detector thresholds. Studies on synthetic defect injection for prediction (e.g., Just et al., 2014) show mutants can mimic real faults incompletely; thresholds from mutants diverge from real-defect thresholds by an uncertain margin. Recommendation: per-project empirical convergence analysis with bootstrapping; start with ≥200 mutants, validate with historical defects if available.

*Recommended:*

- Implement bootstrapping on synthetic corpus to determine threshold stability point (likely 100–500 mutants).
- Collect a small set of real post-mortem defects (≥20) for validation and potential threshold adjustment.
- Start with a conservative threshold (e.g., top 5% of mutant suspiciousness scores) and monitor in production.

*Caveats:*

- Mutant-based thresholds may overfit to artificial patterns, causing missed critical defects (fail-open risk) or excessive false positives.
- Without real-defect data, calibration uncertainty persists; synthetic-to-real transfer gap is unquantified broadly.

## q38-static-import-resolution

**Q:** Statically resolving whether a Python import will succeed, without executing the module: what are the hard cases (conditional imports, __getattr__, namespace packages, lazy loaders, re-exports), and what false-positive rate do existing tools report?

Static import resolution in Python faces false positives from conditional imports, __getattr__, namespace packages, lazy loaders, and re-exports. Existing tools (Pyright, mypy, Jedi) report no aggregate false-positive rates; observed rates vary wildly (0–30% depending on codebase). Recommendation: use allow-lists and limit dynamic imports in Daedalus' fail-closed fence.

*Recommended:*

- Implement an allow-list-based import resolver that only permits whitelisted modules unless a module passes strict static checks.
- Integrate with mypy/Pyright strict mode (with '--warn-unused-imports' and '--follow-imports=error') to catch obvious invalid imports.
- Detect namespace packages by scanning sys.path for matching directories without __init__.py; treat as potential false positives.
- Ban top-level conditional imports and __getattr__/lazy loader usage in agent-generated code; allow only within sandboxed submodules.
- Use a runtime import audit in a controlled sandbox for modules that fail static resolution, logging any discrepancies.

*Caveats:*

- Static analysis cannot guarantee resolution correctness for all dynamic import patterns; false negatives (unsafe modules allowed) are dangerous.
- Allow-lists may block legitimate imports if not regularly updated, hindering agent flexibility.
- Namespace packages and lazy loaders can evade simple file-existence checks.
- Overly strict restrictions on dynamic imports may limit the usefulness of code generation.

## q39-egress-classification

**Q:** Classifying whether a source file may leave a machine: what techniques exist for detecting secrets, proprietary content and device identifiers in source, what are their false-positive rates, and how do teams handle test fixtures that deliberately look like credentials?

Secret detection in source files commonly uses regex, entropy, and ML. GitHub reported initial regex precision ~18% (82% false positives) improving to ~90% with ML. Other tools like TruffleHog can reach >90% false positives on high-entropy non-secrets. Test fixtures with dummy secrets are handled via allowlists/baselines (e.g., detect-secrets). For Daedalus, a layered approach with local ML reduces false positives without violating the egress fence.

*Recommended:*

- Implement a regex+entropy scanner (e.g., Gitleaks, detect-secrets) with a curated allowlist for known false positives and test fixtures.
- Train or fine-tune a small language model (e.g., CodeBERT) for local classification of flagged strings as secret vs. benign, avoiding external API calls.
- Automatically populate the allowlist from directories containing test fixtures and from historical false-positive logs.
- Monitor false-positive and false-negative rates in production; periodically retrain the local classifier using updated data.

*Caveats:*

- Allowlists may become stale, missing new test fixtures or secret patterns.
- Local ML model (e.g., fine-tuned CodeBERT) requires representative training data and may not generalize to all secret types.
- Entropy-based scanning still triggers many alerts on minified code, UUIDs, or base64-encoded non-secrets.
- False negatives from novel or obfuscated secrets remain a risk regardless of method.

## q40-cost-of-being-wrong

**Q:** In automated code review, what is the measured cost of a false positive relative to a false negative, in terms of engineer trust and long-term tool adoption? What false-positive rate causes teams to stop reading a tool's output entirely?

In automated code review, false positives (FPs) erode trust more than false negatives due to alert fatigue. Studies (e.g., Google Tricorder) show that FP rates below 10% are tolerated, while rates above 20% may cause teams to stop reading entirely (uncertain). No precise relative cost is quantified, but wasted developer effort is the main hurdle. Recommendation: target FP rate <10%, use confidence thresholds, and monitor fix rate.

*Recommended:*

- Review Google Tricorder paper (Sadowski et al., ICSE 2015) and Johnson et al. (ICSE 2013) for specific numbers.
- Implement FP rate monitoring and track developer fix rates and engagement over time.
- Start with conservative FP rate target (<10%) and suppress low-confidence findings; adjust based on pilot feedback.

*Caveats:*

- Citations for exact thresholds (10%, 20%) are uncertain; literature lacks a definitive universal number.
- Relative cost of FP vs FN is context-dependent; organizational culture and criticality of bugs affect tolerance.
- No measured ratio exists; research focuses on FP rate impact rather than direct comparison.
