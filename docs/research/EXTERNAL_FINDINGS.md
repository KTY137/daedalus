# External review findings — consolidated

Every line below is a CLAIM made by an external advisory agent reading a slice of this repository. **Nothing here has been verified.** Several of these will be confidently wrong; that is the expected cost of a cheap fan-out, and the reason this file is a queue for checking rather than a defect list.

- reports read: **265** across 6 run(s): `deepseek100`=120, `deepseek40`=40, `deepseek_impl20`=20, `deepseek_lab`=10, `deepseek_r2`=50, `deepseek_r3`=25
- lane errors (agents that failed rather than found nothing): **6**
- distinct claims: **1056**, over **140** targets
- files seen by more than one model: **33**

## What the corroboration signal is worth here: almost nothing

The largest group of agents saying the same thing is **8**. Near-duplicate detection was run at thresholds down to 0.30 and barely merged anything. That is not a bug in the clustering — it follows from the fan-out design, which gave nearly every agent a different file, so there was almost no opportunity for two agents to agree.

The consequence is worth stating plainly: **agreement cannot be used to rank these findings**, and any confidence they carry has to come from checking them, not from counting them. Cross-model agreement is noted below only for the 33 file(s) that more than one model was actually given.

## Findings by target

Ordered by whether the target is a module where a wrong answer is expensive (the fence, the budget, the promotion gate), then by whether more than one model saw it, then by volume.

### `budget.py` ⚠ high-stakes

*18 claim(s); seen by deepseek-chat, deepseek-v4-pro; agents: m14-budget, v-budget*

- **[risk]** REFUTED: Core correctness of budget enforcement is fully visible in the provided file; the Ledger class implements reserve with a check-before-commit invariant and uses atomic file replacement via a temp file and replace.
- **[risk]** Core correctness of budget enforcement (Ledger.reserve, atomic replace on Windows) not visible; no assurance that the check-before-call invariant holds.
- **[risk]** price_call raises NameError when called without explicit host, crashing any budget check that relies on the default host=None path.
- **[risk]** REFUTED: price_call contains an else clause for untrusted_endpoint = False when host is None, so it does not raise NameError.
- **[risk]** Subscription vendor handling may silently widen the cap if not thoroughly tested, but no tests seen.
- **[risk]** REFUTED: price_call does not have a NameError when host=None; regression test unnecessary.
- **[risk]** REFUTED: The suggested 'else: untrusted_endpoint = False' is already present in the code.
- **[risk]** UNDECIDABLE: Subscription vendor handling risk cannot be assessed without tests.
- *…10 more for this target*

### `worktree.py` ⚠ high-stakes

*16 claim(s); seen by deepseek-chat, deepseek-v4-pro; agents: m11-worktree, v-worktree*

- **[risk]** CONFIRMED GitWorktreeManager and cleanup_worktree not visible in this file; docstring claims about allocation record integrity and identity checks cannot be verified from given source. _(also raised by 1 other)_
- **[risk]** Docstring mismatch: _remove_tree_no_follow claims fresh lstat before every syscall, but retry paths in _force_unlink, _force_rmdir, _unlink_reparse_point do not re-verify, widening the attack window.
- **[risk]** REFUTED Docstring mismatch: _remove_tree_no_follow docstring explicitly names the retry exceptions (e.g., PermissionError chmod retry), so the claim of unacknowledged mismatch is false.
- **[risk]** _is_reparse_point returns False on OSError/ValueError, failing open. If an error prevents stat'ing a reparse point, it allows traversal into attacker-controlled junctions.
- **[risk]** CONFIRMED _is_reparse_point returns False on OSError/ValueError, failing open; a stat error on a reparse point allows traversal as if it were a regular directory.
- **[risk]** Incomplete code: _remove_tree_no_follow body truncated; could not verify that re-checks at scan, per-child unlink, and rmdir drain are performed as claimed.
- **[risk]** REFUTED Incomplete code: _remove_tree_no_follow body is fully present, including walk loop and _verify_reachable re-checks at scan, unlink, and rmdir.
- **[risk]** CONFIRMED _chain_between raises ValueError if target not under root; callers that don’t guarantee containment may let this propagate unhandled.
- *…8 more for this target*

### `containment.py` ⚠ high-stakes

*13 claim(s); seen by deepseek-chat, deepseek-v4-pro; agents: m09-containment, v-containment*

- **[risk]** `_verify_job_config` does not verify `ActiveProcessLimit` or `JobMemoryLimit` values, despite docstring claiming all settings are read back; potential for silently accepting incorrect limits.
- **[risk]** CONFIRMED: In _create_process, call to _log_as_hex (undefined) raises NameError caught by bare except, losing debug logs. Defined function is _log_hex.
- **[risk]** If `AssignProcessToJobObject` fails in `_assign_to_job`, the suspended child process is leaked without cleanup, contradicting the lifetime guarantee.
- **[risk]** Missing function `_log_as_hex` (called in `_create_process`) raises `NameError`, caught by bare except, resulting in silent loss of debug logging.
- **[risk]** UNDECIDABLE: _verify_job_config is not present in the provided excerpt; cannot verify if it checks ActiveProcessLimit and JobMemoryLimit.
- **[risk]** UNDECIDABLE: Cannot verify that _verify_job_config needs addition of limit verification without its implementation.
- **[risk]** REFUTED: The code already terminates suspended process and closes handles if job assignment fails.
- **[risk]** REFUTED: _assign_to_job terminates the suspended process and closes handles on failure; no leak.
- *…5 more for this target*

### `sensitivity-vs-offload.py` ⚠ high-stakes

*12 claim(s); seen by deepseek-chat, deepseek-v4-pro; agents: v-sensitivity-vs-offload, x06-sensitivity-vs-offload*

- **[risk]** HIGH: _slice_context in daedalus/offload.py depends on sensitivity.lane_for_host to distinguish local vs remote. A false 'trusted' classification allows a remote Ollama endpoint to receive distilled context, defeating the fence's egress controls. The slice is built inside ollama branch but the trust check is only on lane label, not on resolved host connectivity.
- **[risk]** MEDIUM: If project policy is not loaded (pol=None), semantic_slice may default to no filtering, potentially including sensitive files in slice. Combined with above, this could leak unredacted content remotely.
- **[risk]** UNDECIDABLE: claim #1 - _slice_context trust check missing host resolution; need source file to confirm
- **[risk]** UNDECIDABLE: claim #2 - semantic_slice fallback without policy may leak; need source to verify
- **[risk]** UNDECIDABLE: claim #6 - todo to document slice wire behavior; need source to document
- **[risk]** UNDECIDABLE: claim #3 - todo about host resolution check; cannot assess without code
- **[risk]** UNDECIDABLE: claim #5 - todo to audit lane_for_host; need source to audit
- **[risk]** UNDECIDABLE: claim #4 - todo for integration test; need source to design
- *…4 more for this target*

### `offload.py` ⚠ high-stakes

*10 claim(s); seen by deepseek-chat, deepseek-v4-pro; agents: m51-offload, v-offload*

- **[risk]** UNDECIDABLE: write verification gate missing; need full offload.py to see post-run verification step.
- **[risk]** UNDECIDABLE: add after-snapshot and diff; need full offload.py to confirm if already present.
- **[risk]** write verification gate missing in offload.py; write may succeed without verification
- **[risk]** scoped snapshot for parallel dispatch may miss worker writes outside declared paths
- **[risk]** CONFIRMED: scoped snapshot only hashes declared paths, may miss writes outside.
- **[risk]** CONFIRMED: isolate_paths assumption not enforced, just documented.
- **[todo]** Enforce write-scope in isolate_paths mode or document risk of undetected writes (e.g., by using full-repo snapshot when possible).
- **[todo]** Clarify isolate_paths assumption: add enforcement (e.g., worker path restriction) or explicit documentation of the bypass risk.
- *…2 more for this target*

### `containment-vs-worktree.py` ⚠ high-stakes

*8 claim(s); seen by deepseek-chat, deepseek-v4-pro; agents: v-containment-vs-worktree, x04-containment-vs-worktree*

- **[risk]** UNDECIDABLE: Add disk quota or monitoring - source file not found.
- **[risk]** UNDECIDABLE: Implement network isolation - source file not found.
- **[risk]** UNDECIDABLE: Measure named pipe behavior - source file not found.
- **[risk]** UNDECIDABLE: Reduce harness privilege - source file not found.
- **[todo]** Implement network isolation (e.g., firewall rule, AppContainer, or dedicated user principal) to close the egress gap.
- **[todo]** Consider reducing the harness's privilege or moving it into a separate integrity level.
- **[todo]** Measure named pipe behavior and document whether it creates an IPC bypass.
- **[todo]** Add disk quota or monitoring for the worktree to prevent disk fills.

### `vet.py` ⚠ high-stakes

*8 claim(s); seen by deepseek-chat, deepseek-v4-pro; agents: m59-vet, v-vet*

- **[risk]** CONFIRMED: Binary heuristic only checks first 4096 bytes for NUL, not the whole file, potentially missing later binary indicators (vet.py; _scan_file, line ~382).
- **[risk]** CONFIRMED: TOCTOU in _scan_file: stat then read without re-checking size (vet.py; _scan_file function, line ~370).
- **[risk]** REFUTED: Docstring in scan_text about line number drift is accurate and consistent with the code; no fix required.
- **[todo]** Binary detection improvement: Extend heuristic to check entire file for NUL or use python-magic for reliable binary detection, to avoid missing binary files that start with text-like content.
- **[todo]** TOCTOU fix: In _scan_file, read file content first (e.g., into memory up to MAX_FILE_BYTES+1) and then check size, or re-stat after read to ensure size hasn't changed.
- **[todo]** Address TOCTOU: either read file into memory then check size, or use a lock, or re-stat after read.
- **[todo]** Consider extending binary heuristic to scan whole file or use a library like python-magic.
- **[todo]** Fix docstring in scan_text about line number drift.

### `gated_writes.py` ⚠ high-stakes

*6 claim(s); seen by deepseek-chat, deepseek-v4-pro; agents: m15-gated_writes, v-gated_writes*

- **[risk]** CONFIRMED rebase_declared_path does not warn when rebase fails unexpectedly; specifically, it catches ValueError but not OSError from p.resolve() if the path does not exist, leading to unhandled exceptions.
- **[risk]** CONFIRMED rebase_declared_path does not normalize path case before relative_to comparison, which will fail on Windows when the resolved path and primary_root differ in case but are logically the same.
- **[todo]** Fix rebase_declared_path to normalize case before relative_to comparison, e.g., resolve both paths and compare drive and parts case-insensitively on Windows.
- **[todo]** Add case normalization to rebase_declared_path: e.g., compare os.path.normcase of resolved paths or use a case-insensitive relative_to alternative.
- **[todo]** Catch OSError in rebase_declared_path and emit a warning via logging.warning before returning the raw path, or raise a more descriptive exception.
- **[todo]** Add warning when rebase fails unexpectedly, to alert operator of path configuration issue.

### `web_api.py` ⚠ high-stakes

*3 claim(s); seen by deepseek-chat, deepseek-v4-pro; agents: m03-web_api, v-web_api*

- **[risk]** CONFIRMED Unable to verify correctness, error handling, concurrency atomicity, or docstring guarantees without source code. _(also raised by 1 other)_
- **[risk]** CONFIRMED Supply the full content of daedalus/web_api.py for audit. _(also raised by 1 other)_
- **[todo]** Provide the source code of daedalus/web_api.py.

### `typegraph.py`

*45 claim(s); seen by deepseek-chat, deepseek-v4-pro; agents: m24-typegraph, s04-typegraph, v-typegraph*

- **[risk]** CONFIRMED: _ORIGIN_RANK tie-break (`_ORIGIN_RANK = {'annassign': 0, 'self': 1, ...}`) silently hides genuine conflicts between duplicate field origins. _(also raised by 1 other)_
- **[risk]** CONFIRMED: Star imports never produce resolved edges (doc: 'A STAR IMPORT IS NOT A TIER... it can never be the single winner'), deliberately missing potential resolutions when __all__ absent.
- **[risk]** CONFIRMED: _VOCABULARY includes 'Self' and 'TypeAlias' (explicit in frozenset), which are not guaranteed builtins in all Python versions, potentially masking unresolved references.
- **[risk]** UNDECIDABLE: Tier-2 view picking first candidate when modules share dotted name cannot be verified without full _Resolver._view code; would need complete typegraph.py.
- **[risk]** CONFIRMED: Structural protocol matching is a flagged heuristic (docstring: 'FLAGGED HEURISTIC') and may produce false positives; constants mitigate but not eliminate.
- **[risk]** CONFIRMED: PlainNaming.from_rels returns empty canon dict (line: `_view=_PlainView(rel_by_dotted, {})`); callers expecting populated may break but doc says unused.
- **[risk]** CONFIRMED: _BUILTIN_TYPES includes 'NoneType' manually (`{'None', 'NoneType'}`), which is not a builtin in all Python versions, causing version-dependent behavior.
- **[risk]** PlainNaming.from_rels returns empty .canon dict; callers expecting a populated mapping (from duck typing) may break, though documentation says it is unused.
- *…37 more for this target*

### `picker.py`

*32 claim(s); seen by deepseek-chat, deepseek-v4-pro; agents: m01-picker, s12-picker, v-picker*

- **[risk]** CONFIRMED: 8 Silent config masking: _project_config returns None on non-Mapping. _(also raised by 1 other)_
- **[risk]** High-band sources (work_queue, map_island) can starve low-band but critical hotspots or eval misses forever due to band gap > BAND_SPAN.
- **[risk]** No mechanism to escalate a candidate's band based on evidence, so a critical hotspot can never outrank a trivial map_island.
- **[risk]** Default cheap sources skip eval and hotspots, so critical defects may never appear in the queue without explicit flags.
- **[risk]** Work_queue source is disabled by default, so default queue relies on potentially stale inventory and map state.
- **[risk]** Outcome memory reduces offset for failed attempts, creating a feedback loop that may starve hard problems.
- **[risk]** Docref source has high band but limited write scope, so it may not address core code issues.
- **[risk]** CONFIRMED: 9 NaN propagation possible via _clamp on NaN offset leading to NaN score.
- *…24 more for this target*

### `embeddings.py`

*18 claim(s); seen by deepseek-chat, deepseek-v4-pro; agents: m05-embeddings, v-embeddings*

- **[risk]** CONCURRENCY: _init_db migration runs in a transaction without retry; parallel first opens on the same DB (common in WSGI/async workers) will hit SQLITE_BUSY and crash the process. Windows file locking makes this worse.
- **[risk]** POTENTIAL CORRECTNESS: _normalize_vector rejects zero norm even when normalisation='none', which may be unexpected if callers want to store zero vectors (but docstring justifies it for cosine safety).
- **[risk]** MISSING IMPLEMENTATION: Search/ingest methods (search_report, ingest_report) are referenced in docstring but not visible; their actual enforcement cannot be verified.
- **[risk]** DOCSTRING MISMATCH: docstring promises record_journal_watermark enforces monotonic watermarks and hash consistency, but no such method is visible in this file.
- **[risk]** ERROR SWALLOWING: _embed_batch catches EmbeddingError and returns None silently. Callers may treat None as success, leading to missing vectors.
- **[risk]** CONFIRMED: MISSING IMPLEMENTATION: search_report and ingest_report are referenced in docstring but not implemented in the file.
- **[risk]** CONFIRMED: POTENTIAL CORRECTNESS: _normalize_vector rejects zero-norm vectors regardless of normalization setting.
- **[risk]** CONFIRMED: ERROR SWALLOWING: _embed_batch catches EmbeddingError and returns None silently, risking missed errors.
- *…10 more for this target*

### `ceiling-vs-graphdelta.py`

*17 claim(s); seen by deepseek-chat, deepseek-v4-pro; agents: v-ceiling-vs-graphdelta, x10-ceiling-vs-graphdelta*

- **[risk]** UNDECIDABLE: Claim 7 (render_ceiling_type todo) - file missing. _(also raised by 2 other)_
- **[risk]** UNDECIDABLE: Claim 8 (temporal rename resolution todo) - file missing. _(also raised by 1 other)_
- **[risk]** Dynamic typing or missing type annotations could yield incomplete type edges, understating ceiling.
- **[risk]** Building type graphs per historical revision is expensive and may require project build steps.
- **[risk]** The parent commit may contain syntax errors or incomplete refactors, breaking type extraction.
- **[risk]** Rename resolution adds complexity and potential alias probe failures (understatement risk).
- **[risk]** UNDECIDABLE: Claim 3 (syntax errors in parent commit) - file missing.
- **[risk]** UNDECIDABLE: Claim 6 (git checkout integration todo) - file missing.
- *…9 more for this target*

### `memstore.py`

*16 claim(s); seen by deepseek-chat, deepseek-v4-pro; agents: m54-memstore, v-memstore*

- **[risk]** Windows sharing violation in _ends_without_newline: opens ledger for reading while another process may have it open for append, causing PermissionError and crashing append instead of gracefully handling torn line.
- **[risk]** No cross-process append serialisation: two daemons/processes appending simultaneously can interleave writes, silently corrupting the chain (though hash chain will break, detection is reactive).
- **[risk]** _normalize_entry silently drops unexpected keys inside 'trust' dict, which contradicts the strict-reject posture for other sub-dicts; could hide mis-specified callers.
- **[risk]** CONFIRMED: _normalize_entry silently drops unexpected keys inside 'trust' dict, contradicting strict rejection for other sub-dicts.
- **[risk]** CONFIRMED: _ends_without_newline opens ledger for reading while another process may append, risking PermissionError on Windows.
- **[risk]** UNDECIDABLE: verify_ledger function body not present in provided code; full tamper-evidence guarantee cannot be confirmed.
- **[risk]** CONFIRMED: No cross-process append serialisation; threading.Lock only per-process, can interleave writes.
- **[risk]** verify_ledger function body absent from provided context; full tamper-evidence guarantee unconfirmed.
- *…8 more for this target*

### `council-bus.py`

*15 claim(s); seen by deepseek-chat, deepseek-v4-pro; agents: v-council-bus, x19-council-bus*

- **[risk]** Message-loss: _normalize_turn raises ValueError on invalid status (e.g., 'refused' from caller) or missing independence_class. If caller does not catch these, entire write may crash, discarding other turns. Trigger: a misbehaving vendor integration sending 'status'='refused'.
- **[risk]** Cross-process chain corruption: _chain_state cache uses file signature; two processes may both read the same tail before either writes, leading to stale prev and broken chain. The lock is process-local. Trigger: simultaneous appends by multiple processes.
- **[risk]** Vendor silence not visible: No dispatch/timeout code shown. When a vendor never answers, the system must record 'unavailable' turns. Without it, turns may be absent, violating the invariant of one turn per participant.
- **[risk]** Ordering non-deterministic if caller fails to sort: append_round is expected to sort turns; if _chain_records is called directly with unsorted list, chain head becomes non-reproducible. Not visible in slice.
- **[risk]** Replay acceptance: No nonce; duplicate bodies are permitted. An attacker replaying a past turn into a new round could be accepted, though round/ts injection may be hard.
- **[risk]** UNDECIDABLE: Cross-process chain corruption claim depends on _chain_state cache and locking in council-bus.py (not provided).
- **[risk]** UNDECIDABLE: Ordering non-determinism claim depends on _chain_records implementation in council-bus.py (not provided).
- **[risk]** UNDECIDABLE: Message-loss claim depends on _normalize_turn implementation in council-bus.py (not provided).
- *…7 more for this target*

### `forest.py`

*15 claim(s); seen by deepseek-chat, deepseek-v4-pro; agents: m60-forest, v-forest*

- **[risk]** HIGH: In type_nodes loop, second and subsequent rows for the same node_id are silently skipped (line approx. after `if node_id in type_ids: continue`), discarding attributes and evidence. Concrete trigger: index with multiple type_nodes entries sharing an id but differing attributes.
- **[risk]** MEDIUM: Hardcoded evidence tuples (e.g., 'structcore.type_edges') discard any per-edge provenance from the index, contradicting the docstring claim that the snapshot is evidence-preserving. This affects all edge types.
- **[risk]** LOW: `_json_value` fallback to `repr()` for unknown types may produce non-deterministic output across Python runs, violating the deterministic claim if the index ever carries custom objects with unstable repr.
- **[risk]** LOW: In temporal pairs deduplication, `seen_temporal` uses only file pair (a,b); later occurrences with different attributes are dropped. This could lose data if the iterable contains duplicate pairs.
- **[risk]** CONFIRMED: In type_nodes loop, duplicates with same node_id skip subsequent rows, discarding attributes. Trigger: multiple type_nodes entries with same id.
- **[risk]** REFUTED: Edge evidence tuples are hardcoded, but the index does not provide per-edge provenance to discard; no contradiction with docstring.
- **[risk]** CONFIRMED: Temporal pairs dedup uses only (a,b); later entries with same pair but different attributes are silently dropped.
- **[risk]** CONFIRMED: _json_value fallback to repr() may produce non-deterministic output for custom objects with unstable repr.
- *…7 more for this target*

### `repo-level-retrieval.py`

*15 claim(s); seen by deepseek-chat, deepseek-v4-pro; agents: q10-repo-level-retrieval, v-repo-level-retrieval*

- **[risk]** UNDECIDABLE: Claim 7 (Benchmark call-graph coverage): no source to inspect. _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: Claim 6 (Measure recall on internal dataset): no source or dataset to inspect.
- **[risk]** UNDECIDABLE: Claim 1 (Dense embeddings brittle on rare identifiers): no source to inspect.
- **[risk]** Dense embeddings can be brittle on rare identifiers or project-specific patterns
- **[risk]** Context budget (e.g., 8K tokens) limits number of snippets, forcing trade-offs
- **[risk]** UNDECIDABLE: Claim 2 (Context budget limits snippets): no source to inspect.
- **[risk]** Agentic search incurs high latency and LLM cost; unreliable recall metrics
- **[risk]** UNDECIDABLE: Claim 4 (BM25 misses semantic matches): no source to inspect.
- *…7 more for this target*

### `attempt.py`

*14 claim(s); seen by deepseek-chat, deepseek-v4-pro; agents: m07-attempt, v-attempt*

- **[risk]** Missing GIT_ATTR_GLOBAL strip: _git_env leaves GIT_ATTR_GLOBAL intact, so candidate-controlled filter execution may be possible if the operator has that variable set and the candidate can write to the referenced attributes file. _(also raised by 1 other)_
- **[risk]** gitdir redirection via .git file: if TaskAttempt doesn't pass git_dir to _git, a malicious candidate can rewrite .git to point to a path inside the primary checkout's .git, bypassing the overlap guard that only checks cwd vs. repo_root (doc claims no mutating command reaches the repo, but .git corruption is possible).
- **[risk]** Uncaught TimeoutExpired: _git doesn't handle subprocess timeout; if the caller (TaskAttempt.run) does not catch it, the result may be an unhandled exception, violating the documented 'always returns AttemptResult' contract.
- **[risk]** CONFIRMED claim 7: Add GIT_ATTR_GLOBAL to _git_env - the variable is indeed missing from the pop list, confirming the fix is needed.
- **[risk]** UNDECIDABLE claim 1: gitdir redirection via .git file - TaskAttempt code not provided to verify git_dir parameter passing.
- **[risk]** UNDECIDABLE claim 3: Uncaught TimeoutExpired - _git body and TaskAttempt.run not provided to verify timeout handling.
- **[risk]** UNDECIDABLE claim 5: Review ledger ordering, artifact_dir fencing, runner isolation - needs full implementation.
- **[risk]** UNDECIDABLE claim 6: Audit TaskAttempt.run for subprocess exception catching - requires full implementation.
- *…6 more for this target*

### `health.py`

*14 claim(s); seen by deepseek-chat, deepseek-v4-pro; agents: m02-health, v-health*

- **[risk]** TOCTOU in `inherited` (line 149): if file is altered between the caller's read and the `stat()` call, the recorded age reflects the new version, not the one whose value was read. This could falsely report a stale value as fresh.
- **[risk]** Docstring on exit code 2 (line 213) says `unknown` and `present` land on 2, but `NOT_PROVEN` includes `ABSENT`. Thus an absent optional probe also exits with code 2, contradicting the documented behavior.
- **[risk]** REFUTED: Claim 2 - Verdict docstring says 'unknown and present both land on 2' but does not claim only those; absent also lands on 2, consistent with NOT_PROVEN including absent. No contradiction.
- **[risk]** CONFIRMED: Claim 1 - TOCTOU in inherited(): caller reads value then calls stat on same file, so age may reflect newer version, potentially reporting stale value as fresh.
- **[risk]** The claim 'NOTHING HERE WRITES' and promises about read-only operation on spine ledger/vector index cannot be verified; none of those probes appear in the slice.
- **[risk]** `Fact.__post_init__` (line 92) does not reject empty string for `source` on `INHERITED` facts, allowing a fact with no real provenance to pass validation.
- **[risk]** REFUTED: Claim 7 - Empty string is rejected; whitespace-only sources are not caught, but the claim specifically says 'empty string', which is false.
- **[risk]** CONFIRMED: Claim 3 - Slice lacks spine ledger/vector index probes, so read-only promises in module docstring cannot be verified from given code.
- *…6 more for this target*

### `cancel.py`

*13 claim(s); seen by deepseek-chat, deepseek-v4-pro; agents: m56-cancel, v-cancel*

- **[risk]** PosixSessionBackend.signal_group returns False on any OSError (e.g., process already exited), but the CancelResult.stage could be STAGE_GRACEFUL with graceful=True even if the signal was never actually delivered, because the exit might have been coincidental. This mischaracterizes the outcome. _(also raised by 1 other)_
- **[risk]** Race condition: ManagedProcess registers in _LIVE only after Popen and after_spawn succeed. A concurrent cancel_all_managed() may miss a process that is already running (but not yet in _LIVE), violating the guarantee that the sweep kills all contained children. Trigger: rapid spawns and a kill‑switch event in that window.
- **[risk]** Posix backend kill_tree swallows all OSError; if both killpg and process.kill() fail (e.g., stuck in D state, permission error), cancel returns STAGE_TREE_KILL with returncode=None, and killed property returns True, misleading callers that rely on tree being dead.
- **[risk]** ManagedProcess.__del__ relies on deterministic collection, which is not guaranteed on non-CPython implementations; the docstring claim that an orphaned object always kills survivors is therefore weaker than stated.
- **[risk]** CONFIRMED: PosixSessionBackend.kill_tree swallows all OSError; if both killpg and process.kill() fail, cancel() returns STAGE_TREE_KILL with returncode=None and killed=True, misleading callers.
- **[risk]** CONFIRMED: Race condition: ManagedProcess registers in _LIVE only after after_spawn (__init__). Between Popen and registration, cancel_all_managed() may miss a running process.
- **[risk]** CONFIRMED: ManagedProcess.__del__ relies on CPython reference-counting; docstring promise of release on drop is weaker on non-CPython implementations.
- **[risk]** CONFIRMED: Posix kill_tree should verify termination (e.g., os.waitid or poll after wait) and raise/report 'kill_failed' instead of silent return.
- *…5 more for this target*

### `progress_sources.py`

*13 claim(s); seen by deepseek-chat, deepseek-v4-pro; agents: m57-progress_sources, v-progress_sources*

- **[risk]** CONFIRMED watch_stream: exception swallowing hides all progress recording failures (bare except: pass, line ~79); no recovery or fallback logging. _(also raised by 1 other)_
- **[risk]** CONFIRMED record_offload_result: when rolled_back is true but dirty_unreverted key missing, applied becomes False (line ~95: applied = bool(result.get('dirty_unreverted')) with bool(None) → False). This is by design to be conservative, but may underreport dirty files.
- **[risk]** CONFIRMED snapshot_from_ledger: numeric string confusion. Passing effect_key='123' first tries ledger.get(123) by id, potentially returning wrong intent or None before falling back to resolve_by_effect (lines ~165-172).
- **[risk]** UNDECIDABLE Audit limited: snapshot_from_bridge and snapshot_any are not visible in the provided slice of progress_sources.py; would need the complete file to verify their behavior.
- **[risk]** CONFIRMED track_call: heartbeat thread writes to P.heartbeat (line ~140) without explicit lock or thread-safety guarantee for the progress log, creating risk of concurrent writes.
- **[risk]** record_offload_result: if result['rolled_back'] is true but 'dirty_unreverted' key missing, applied becomes False (instead of True) even if files left dirty.
- **[risk]** snapshot_from_ledger: numeric string confusion – call with effect_key='123' queries by id=123 first, may return wrong intent or None.
- **[risk]** track_call: heartbeat thread writes to progress log concurrently without explicit thread-safety guarantee for P.heartbeat.
- *…5 more for this target*

### `cli.py`

*12 claim(s); seen by deepseek-chat, deepseek-v4-pro; agents: m21-cli, v-cli*

- **[risk]** 3. CONFIRMED: Commands without try/except (_spawn, _build, _init, _projects, _accelerators, _context, _agents, _categories, _drafts) produce traceback on downstream failures, leaking internals and exiting non-zero unexpectedly. _(also raised by 1 other)_
- **[risk]** 2. CONFIRMED: Docstring claims specific non-zero exits for 'status', 'health', 'map --check', but dispatch logic is not shown; compliance unverifiable. _(also raised by 1 other)_
- **[risk]** 1. CONFIRMED: agents add/edit, categories set, drafts apply/dismiss print error messages but return 0, causing scripts to treat failures as success. _(also raised by 1 other)_
- **[risk]** 4. UNDECIDABLE: File writes in _init, agents registry, categories lack atomicity; parallelism risks depend on config.py, agents_registry, categories modules not provided.
- **[risk]** 5. UNDECIDABLE: _context calls load_project without checking existence; depends on load_project implementation not provided.
- **[risk]** File writes in _init, agents registry, categories lack atomicity; on Windows, parallel invocations may corrupt configs.
- **[risk]** _context calls load_project without checking existence, causing AttributeError on missing project.
- **[todo]** Wrap external calls in _spawn, _context, _accelerators, _build with try/except, print user-friendly message, and sys.exit(1). _(also raised by 1 other)_
- *…4 more for this target*

### `docrefs.py`

*12 claim(s); seen by deepseek-chat, deepseek-v4-pro; agents: m38-docrefs, s14-docrefs, v-docrefs*

- **[risk]** CONFIRMED: Suffix resolution without anchoring may produce false positives when multiple modules share a basename; current code handles ambiguity by skipping, but single-hit suffix may still be wrong module. _(also raised by 1 other)_
- **[risk]** CONFIRMED: Evaluate whether partial enumeration of star-imports via importlib.metadata or similar is feasible without running code. _(also raised by 1 other)_
- **[risk]** CONFIRMED: Stripping fenced code blocks may discard legitimate doc references; consider a whitelist of known example patterns. _(also raised by 1 other)_
- **[risk]** CONFIRMED: Add test for suffix-resolved reference that is not root-anchored to verify it is marked 'suspect' or 'skipped'. _(also raised by 1 other)_
- **[risk]** CONFIRMED: Consider adding a configuration option to include/exclude certain doc patterns from code-block stripping. _(also raised by 1 other)_
- **[risk]** CONFIRMED: Consider adding threading lock for shared cache if concurrent use is expected. _(also raised by 1 other)_
- **[risk]** CONFIRMED: Evaluate whether dotted regex should allow uppercase first segment. _(also raised by 1 other)_
- **[risk]** CONFIRMED: Enhance code block stripping to handle tabs. _(also raised by 1 other)_
- *…4 more for this target*

### `index.py`

*12 claim(s); seen by deepseek-chat, deepseek-v4-pro; agents: m18-index, v-index*

- **[risk]** CONFIRMED - Need to ensure document/type/wiki opt-in logic matches all docstring claims (exclusion from modules, edges, etc.) _(also raised by 1 other)_
- **[risk]** UNDECIDABLE - docstring guarantees about documents/types/wiki layering cannot be verified without build_index implementation _(also raised by 1 other)_
- **[risk]** UNDECIDABLE - concurrency and Windows file handle issues cannot be assessed with truncated _per_file_pass _(also raised by 1 other)_
- **[risk]** _collect will return after one file if max_files=0; unknown if caller defaults to 0 or uses that value _(also raised by 1 other)_
- **[risk]** CONFIRMED - Need to obtain complete file including build_index and rest of _per_file_pass _(also raised by 1 other)_
- **[risk]** CONFIRMED - Need to verify max_files handling in _collect and its callers _(also raised by 1 other)_
- **[risk]** CONFIRMED - Need to test filesystem atomicity with content-keyed cache under concurrent access
- **[todo]** Review _per_file_pass for process pool order correctness and Windows compatibility (currently truncated) _(also raised by 2 other)_
- *…4 more for this target*

### `loop.py`

*12 claim(s); seen by deepseek-chat, deepseek-v4-pro; agents: m13-loop, v-loop*

- **[risk]** CONFIRMED: os.replace atomicity may cause PermissionError on Windows if another process has the ledger file open (e.g., concurrent reader). _(also raised by 1 other)_
- **[risk]** CONFIRMED: Missing LoopDriver and main loop: cannot verify bound enforcement, killswitch integration, or error handling. _(also raised by 1 other)_
- **[risk]** CONFIRMED: Request full loop.py file to audit LoopDriver, iteration logic, and error handling (file is incomplete). _(also raised by 1 other)_
- **[risk]** CONFIRMED: Truncated _curated_gate prevents analysis of gate_argv/gate_cwd handling. _(also raised by 1 other)_
- **[risk]** CONFIRMED: LoopLedger.save lacks exception handling; caller must cope. _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: Confirm that 'NEVER WRITES PRIMARY CHECKOUT' guarantee holds across all code paths (requires full driver and related modules to trace all code paths).
- **[risk]** UNDECIDABLE: Verify that all four bounds are checked correctly every iteration (requires LoopDriver code to see bound checks).
- **[todo]** Provide the missing LoopDriver class and main loop implementation, ensuring bounds enforcement, killswitch integration, and proper error handling.
- *…4 more for this target*

### `worktree-patterns.py`

*12 claim(s); seen by deepseek-chat, deepseek-v4-pro; agents: q30-worktree-patterns, v-worktree-patterns*

- **[risk]** UNDECIDABLE: claim 1 about merge conflicts at 100 agents - missing source file _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: claim 3 about CI pipeline saturation - missing source file _(also raised by 1 other)_
- **[risk]** At 100 concurrent agents, merge conflicts can cascade, causing thrashing and repeated rebases.
- **[risk]** Shared object database locking under high push concurrency can degrade performance.
- **[risk]** UNDECIDABLE: claim 2 about shared object database locking - missing source file
- **[risk]** CI pipeline saturation may delay feedback loops, causing stale branches.
- **[risk]** UNDECIDABLE: claim 7 about profiling Git locking - missing source file
- **[risk]** UNDECIDABLE: claim 6 about patch-stack model - missing source file
- *…4 more for this target*

### `vet-gate.py`

*9 claim(s); seen by deepseek-chat, deepseek-v4-pro; agents: m59-vet, s10-vet-gate, v-vet-gate*

- **[risk]** UNDECIDABLE: Claim 1 (Empty body_sha256 bypass) - cannot confirm or refute without vet-gate.py. _(also raised by 7 other)_
- **[risk]** Empty body_sha256 bypasses pin check, allowing allowance inheritance by name only
- **[risk]** Homoglyph characters can bypass regex patterns (e.g., Cyrillic 'е' in 'eval')
- **[risk]** Typo in vet_mcp_server causes AttributeError or incorrect severity
- **[risk]** Line number drift in scan_text may mislead human reviewers
- **[todo]** Fix typo: change REVIE to REVIEW in vet_mcp_server line. _(also raised by 1 other)_
- **[todo]** Fix body_sha256 check to treat empty identity as no pin (do not match)
- **[todo]** Add homoglyph normalization to _defang or add separate rule
- *…1 more for this target*

### `codeql-datalog.py`

*8 claim(s); seen by deepseek-chat, deepseek-v4-pro; agents: q13-codeql-datalog, v-codeql-datalog*

- **[risk]** UNDECIDABLE: incremental updates may cause latency spikes if full re-evaluation is needed - source file not provided _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: benchmark Soufflé on representative code analysis tasks - source file not provided _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: prototype extraction from multiplex graph to relations - source file not provided _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: assess whether Cypher/GQL recursive features suffice - source file not provided _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: integration complexity with existing graph db - source file not provided _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: evaluate DDlog for incremental queries - source file not provided _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: rule compilation overhead - source file not provided
- **[risk]** rule compilation overhead

### `task-decomposition.py`

*8 claim(s); seen by deepseek-chat, deepseek-v4-pro; agents: q26-task-decomposition, v-task-decomposition*

- **[risk]** UNDECIDABLE [risk] Comparisons are confounded by different tool interfaces and model capabilities; exact numbers are uncertain and based on recall of evolving leaderboards. _(also raised by 1 other)_
- **[risk]** UNDECIDABLE [risk] Plan-then-execute includes a spectrum from naive single‑step decompose‑to‑the‑end to iterated refinement; simple ablation may not capture the nuance. _(also raised by 1 other)_
- **[risk]** UNDECIDABLE [risk] Tree‑search evidence is largely from reasoning tasks (e.g., Game of 24, Creative Writing) with few rigorous coding‑task studies. _(also raised by 1 other)_
- **[risk]** UNDECIDABLE [todo] Design a head‑to‑head experiment: same LLM, same agent scaffold, vary only the decomposition‑then‑execute vs. ReAct strategy. _(also raised by 1 other)_
- **[risk]** UNDECIDABLE [risk] Fabrication risk: names like "SWE-agent" and percentages are from memory, not verified against current publications. _(also raised by 1 other)_
- **[risk]** UNDECIDABLE [todo] Search for any coding‑focused tree‑search paper (e.g., MCTS for code repair) and extract quantitative comparisons. _(also raised by 1 other)_
- **[risk]** UNDECIDABLE [todo] Re‑read the SWE-agent paper to confirm if they measured a decomposed baseline. _(also raised by 1 other)_
- **[risk]** UNDECIDABLE [todo] Audit the SWE-bench Lite leaderboard for up‑to‑date resolve rates. _(also raised by 1 other)_

### `llm-judge-reliability.py`

*7 claim(s); seen by deepseek-chat, deepseek-v4-pro; agents: q08-llm-judge-reliability, v-llm-judge-reliability*

- **[risk]** UNDECIDABLE: Over-reliance on LLM judges for code correctness without test verification may introduce subtle bugs. _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: Position and verbosity biases can skew results if not controlled. _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: Ensemble approaches increase cost and latency. _(also raised by 1 other)_
- **[todo]** Pilot the judge protocol on a sample set with human annotations to measure agreement and calibrate biases.
- **[todo]** Design detailed rubrics for code quality dimensions (correctness, readability, efficiency).
- **[todo]** Set up an ensemble of at least three different LLM judges with majority voting.
- **[todo]** Implement position randomization and length normalization in judge prompts.

### `ontology-for-code.py`

*7 claim(s); seen by deepseek-chat, deepseek-v4-pro; agents: q21-ontology-for-code, v-ontology-for-code*

- **[risk]** UNDECIDABLE: For code analysis, evaluate lightweight AST-based serialization (e.g., JSON of tree-sitter output) vs. SWO/SEON _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: Survey external tools/systems Daedalus must interoperate with (e.g., SBOM generators, repo registries) _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: Premature standardization may force rigidity where a flexible internal schema suffices _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: Interoperability benefit is limited unless explicit external exchange is required _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: If license/compliance exchange needed, map internal model to SPDX minimal profile _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: Heavy ontologies (SEON, SWO) impose semantic overhead with little tooling uptake _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: Prototype metadata export to CodeMeta if targeting scholarly repositories _(also raised by 1 other)_

### `wiki-vs-index.py`

*7 claim(s); seen by deepseek-chat, deepseek-v4-pro; agents: v-wiki-vs-index, x15-wiki-vs-index*

- **[risk]** UNDECIDABLE: [risk] The index's wiki gate (DAEDALUS_INDEX_WIKI) suggests a separate code path that may not fully replicate links.py's deterministic sort, bounds, and edge types. _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: [todo] Decide which component owns resolution: preferably wiki layer exports a reusable LinkIndex builder, and index.py calls it when documents+wiki flags are on. _(also raised by 1 other)_
- **[risk]** If resolution logic is duplicated, a bug fix in one place may be missed in the other, leading to incorrect links in diagnostic outputs (local graph vs. document_links). _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: [risk] Link resolution rules (e.g., _candidates_for in links.py) may diverge between wiki and index, causing inconsistent edge sets for the same content. _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: [todo] Verify that type: and vault: link handling is consistent across both; currently links.py just counts them, but index may attempt resolution. _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: [todo] Check that ambiguous/unresolved reporting is uniform; links.py reports, but index's document_links may silently drop. _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: [todo] Locate markdown.knowledge_links or equivalent in structcore/markdown.py and compare with wiki/links.py build_index. _(also raised by 1 other)_

### `(no file)`

*2 claim(s); seen by deepseek-chat, deepseek-v4-pro; agents: i08-tests-wiki-links, i09-tests-shift, m04-correctness, m25-switches, m26-inventory …*

- **[lane_error]** IncompleteRead: IncompleteRead(1 bytes read) _(also raised by 3 other)_
- **[lane_error]** TimeoutError: The read operation timed out _(also raised by 1 other)_

### `loop-promotion.py`

*20 claim(s); one model (deepseek-chat), one look; agents: s11-loop-promotion, v-loop-promotion*

- **[risk]** Sibling integration branches: LoopLedger.claim is a heuristic based on declared paths, not measured changed paths, so real collisions can be missed.
- **[risk]** UNDECIDABLE: Claim 1 - LoopLedger.claim heuristic uses declared paths, not measured changed paths; cannot verify without loop-promotion.py.
- **[risk]** Attempt id mismatch: LoopLedger records attempt_task_ids that picker cannot query, so picker's attempt memory is blind to loop history.
- **[risk]** Candidate's own gate is dropped: _curated_gate drops gate_paths and base_revision, potentially weakening gate accuracy.
- **[risk]** Governance red is normal: loop continues attempting but never promotes, which may surprise operators expecting a halt.
- **[risk]** UNDECIDABLE: Claim 5 - Stop latency now fixed via cancellation token in re-gate; need loop-promotion.py to verify fix.
- **[risk]** UNDECIDABLE: Claim 4 - Governance red loop continues attempting but never promotes; need source to confirm behavior.
- **[risk]** UNDECIDABLE: Claim 2 - LoopLedger records attempt_task_ids picker cannot query; need loop-promotion.py to confirm.
- *…12 more for this target*

### `evolution-island.py`

*19 claim(s); one model (deepseek-chat), one look; agents: s15-evolution-island, v-evolution-island*

- **[risk]** UNDECIDABLE: [claim 10] Integrate evaluate_change - need source file to confirm. _(also raised by 1 other)_
- **[risk]** Best-of-N baseline is not correctly implemented: ties are broken by sort stability (first in list), not random.
- **[risk]** evaluate_candidates uses binary pass/fail; intended replacement (evaluate_change) is not imported or used.
- **[risk]** select_best requires score >= 100.0, so only perfect passes are considered; no partial credit.
- **[risk]** UNDECIDABLE: [claim 9] Change select_best to handle ties - need source file to confirm.
- **[risk]** UNDECIDABLE: [claim 1] Best-of-N baseline tie-breaking - need source file to verify.
- **[risk]** generate_candidates has no timeout; a hanging agent blocks all candidates forever.
- **[risk]** UNDECIDABLE: [claim 8] Add configuration parameters - need source file to confirm.
- *…11 more for this target*

### `markdown-parser.py`

*18 claim(s); one model (deepseek-chat), one look; agents: s06-markdown-parser, v-markdown-parser*

- **[risk]** UNDECIDABLE: Source file missing. Claim: No test coverage for adversarial inputs like nested brackets, pipes in aliases, or embeds inside code fences. _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: Source file missing. Claim: Add HTML comment stripping before link parsing. _(also raised by 1 other)_
- **[risk]** Reference definitions (`_REF_DEF`) and autolinks (`_AUTOLINK`) are matched on raw lines, not filtered by `_content_lines`, so they are parsed even inside fenced code blocks — phantom edge.
- **[risk]** Inline code stripping regex `_INLINE_CODE` fails on nested backticks (e.g., `` `[[Note]]` ``) — phantom edge from wikilink inside inline code.
- **[risk]** UNDECIDABLE: Source file missing. Claim: Reference definitions and autolinks may be matched on raw lines, not filtered by _content_lines.
- **[risk]** UNDECIDABLE: Source file missing. Claim: _INLINE_CODE regex does not handle backtick escapes or multiple backtick sequences correctly.
- **[risk]** The `_INLINE_CODE` regex does not handle backtick escapes or multiple backtick sequences correctly — may miss some inline code spans.
- **[risk]** UNDECIDABLE: Source file missing. Claim: Inline code stripping regex fails on nested backticks (e.g., `` `[[Note]]` ``).
- *…10 more for this target*

### `gated-writes.py`

*17 claim(s); one model (deepseek-chat), one look; agents: s16-gated-writes, v-gated-writes*

- **[risk]** If offload() finishes with 'escalated_after_verify_fail' and non-empty wrote, the gate catches it, but the patch bytes are still captured as artifact (though not promoted). _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: [todo] Claim 8: wire Phase 2 promotion into default dispatch path or document why opt-in. _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: [todo] Claim 7: ensure artifact persistence does not bypass primary checkout fence. _(also raised by 1 other)_
- **[risk]** The offload-verify gate only checks offload's own verdict; it does not independently verify the patch, relying on offload's verify+rollback cascade as the sole authority.
- **[risk]** The name 'gated_writes' implies a write fence, but the module only gates attempts, not writes. Offload() can still auto-land into primary checkout outside a wave.
- **[risk]** Phase 2 promotion is opt-in and not wired into KairosScheduler.dispatch() default path, so concurrent writes may bypass promotion entirely.
- **[risk]** UNDECIDABLE: [risk] Claim 3: module only gates attempts, not writes; offload() can auto-land into primary checkout outside a wave.
- **[risk]** The curated command gate is only used if provided; otherwise, only the offload-verify gate runs, which is a weak check.
- *…9 more for this target*

### `wiki-links.py`

*17 claim(s); one model (deepseek-chat), one look; agents: s08-wiki-links, v-wiki-links*

- **[risk]** UNDECIDABLE: local_graph potential infinite loop on cycles; source file not available. _(also raised by 1 other)_
- **[risk]** unlinked_mentions regex uses word boundaries but does not handle underscores/hyphens inside words; e.g., title 'agent' would match 'agentive' because \b matches before 'agent' and after 'ive'? Actually \b before 'agent' and after 'ive'? No, \b after 'agent' would not match because 'i' is word char; so false positive unlikely for that case. But title 'a_b' would match 'a_b_c' because \b after 'b'? Actually 'a_b' is a single word; regex would match 'a_b' inside 'a_b_c' because \b after 'b' fails? Let's check: 'a_b_c' has word chars; \b after 'b' is between 'b' and '_' which is not a word boundary because both are word chars; so no match. So false positives are limited to cases where title appears as a separate word, which is correct. However, common words like 'the' (3 chars) are skipped by length check; but words like 'and' (3 chars) also skipped. So false positives from common words are mitigated by length check.
- **[risk]** local_graph can loop forever on a cycle if depth is large and max_nodes is not reached, because it only checks seen nodes, not visited edges; a cycle of unseen nodes would keep adding to frontier indefinitely.
- **[risk]** local_graph truncates at MAX_LOCAL_NODES and sets truncated flag, but the note says 'stopped at the node bound; the neighbourhood is larger' which is clear.
- **[risk]** unlinked_mentions truncates at MAX_MENTIONS_PER_PAGE without indicating how many were omitted; caller must check limit.
- **[risk]** UNDECIDABLE: unlinked_mentions regex boundary behavior with underscores/hyphens; source file not available.
- **[risk]** build_index silently drops links beyond MAX_LINKS_PER_PAGE per page; this could lose data without warning.
- **[risk]** UNDECIDABLE: unlinked_mentions truncation without total count; source file not available.
- *…9 more for this target*

### `mcp-security.py`

*16 claim(s); one model (deepseek-chat), one look; agents: r17-mcp-security, v-mcp-security*

- **[risk]** Prompt injection through tool output: output contains instructions that alter LLM behavior; mitigation via output sanitization (strip markdown, control characters) and context isolation.
- **[risk]** Rug-pull updates: server changes tool semantics after approval; mitigation via version pinning and hash verification of tool definitions.
- **[risk]** UNDECIDABLE: Claim about prompt injection through tool output and output sanitization cannot be verified without mcp-security.py.
- **[risk]** Tool poisoning can cause LLM to call wrong tool; mitigation via strict schema validation and human review of tool descriptions.
- **[risk]** Cross-server shadowing: multiple servers define same tool name; mitigation via unique namespacing (e.g., server_id.tool_name).
- **[risk]** UNDECIDABLE: Claim about rug-pull updates and version pinning/hash verification cannot be verified without mcp-security.py.
- **[risk]** UNDECIDABLE: Todo item 'Implement tool definition hashing and version pinning' cannot be verified without mcp-security.py.
- **[risk]** UNDECIDABLE: Todo item 'Require human approval for tool schema changes' cannot be verified without mcp-security.py.
- *…8 more for this target*

### `vault-path-safety.py`

*16 claim(s); one model (deepseek-chat), one look; agents: s07-vault-path-safety, v-vault-path-safety*

- **[risk]** UNDECIDABLE: Trailing dots/spaces only checked per segment before join, but not after path resolution (e.g., 'page.md ' passes segment check but Windows strips space) _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: Fix TOCTOU by using a single atomic check: open file with O_NOFOLLOW and then resolve, or use os.stat with follow_symlinks=False on all components _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: Reserved device names checked only on stem (seg.split('.')[0].lower()), so 'CON.txt.md' passes (stem='con') but 'CON' is still a device name _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: Windows 8.3 short names allow traversal without '..' (e.g., PROJEC~1/..../Windows/win.ini) - vault_rel does not expand short names _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: Drive-relative paths (C:foo.md) bypass absolute check because they lack leading / and regex requires colon at position 1 _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: Reject drive-relative paths (single letter followed by colon, not at start) by checking for colon in any segment _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: Case-insensitive collisions on Windows (e.g., PAGE.MD vs page.md) not detected, could overwrite existing page _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: Extend reserved device name check to full segment (not just stem) and also check after removing extension _(also raised by 1 other)_
- *…8 more for this target*

### `fitness-graph-delta.py`

*15 claim(s); one model (deepseek-chat), one look; agents: s01-fitness-graph-delta, v-fitness-graph-delta*

- **[risk]** UNDECIDABLE: Claim 5 requires the code for SCORING_LAYERS and full corpus; source file missing. _(also raised by 1 other)_
- **[risk]** change_constant mutants are invisible to the 'literals' layer because repr() of string literals is identical before/after (e.g., 'claude_cli' vs 'claude_cli' both repr to "'claude_cli'"). The multiset key uses repr, so no delta.
- **[risk]** Corpus is 300 mutants but only 62 are change_constant; the rest are deletions/insertions that naturally move AST refs or structure. This operator mix bias inflates overall detection rate.
- **[risk]** Leaky layer (code.refs.leaky) includes comment tokens, so marker words 'SEEDED DEFECT' cause false detections. This inflates the headline number.
- **[risk]** UNDECIDABLE: Claim 1 requires inspection of the 'literals' layer and how it uses repr() for string literals; source file missing.
- **[risk]** Specificity arm (real commits) is not fully implemented in the excerpt; without it, false alarm rate is unknown.
- **[risk]** UNDECIDABLE: Claim 3 requires examining the leaky layer implementation and token handling; source file missing.
- **[risk]** UNDECIDABLE: Claim 2 requires access to the corpus and mutation operator distribution; source file missing.
- *…7 more for this target*

### `observe-shape.py`

*15 claim(s); one model (deepseek-chat), one look; agents: s09-observe-shape, v-observe-shape*

- **[risk]** UNDECIDABLE: claim 3 (nbytes missing on torch tensors) _(also raised by 1 other)_
- **[risk]** pandas memory_usage(deep=False).sum() may raise on non-pandas objects with 'columns' attribute (e.g., polars); caught by except, falls back to nbytes which may be 0.
- **[risk]** dtype string may leak structured dtype field names (e.g., 'patient_id') if dtype.names contains sensitive strings; redact is not applied to dtype.
- **[risk]** nbytes attribute may not exist on torch tensors or awkward arrays; caught by int(_attr(obj, 'nbytes', 0)) which returns 0, losing size info.
- **[risk]** h5py/uproot detection relies on module name; if a custom object has 'keys' and 'num_entries' but is not a tree, it may be misclassified.
- **[risk]** UNDECIDABLE: claim 4 (h5py/uproot detection misclassification)
- **[risk]** UNDECIDABLE: claim 1 (pandas memory_usage/fallback issue)
- **[risk]** UNDECIDABLE: claim 2 (dtype leak with structured fields)
- *…7 more for this target*

### `12.py`

*14 claim(s); one model (deepseek-chat), one look; agents: s-12, v-embeddings, v-picker*

- **[risk]** UNDECIDABLE: TOCTOU on queue file read from load_work_queue; inspect body. _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: Work_queue disabled by default? Inspect build_queue logic. _(also raised by 1 other)_
- **[risk]** UNDECIDABLE: Claims 16,17,20 require full source of build_queue/load_work_queue to verify.
- **[todo]** Add WAL mode and busy timeout to _init_db to prevent SQLITE_BUSY (v-embeddings: concurrency). _(also raised by 1 other)_
- **[todo]** Add starvation detector alert for low-band candidates pending too long (v-picker claim 1). _(also raised by 1 other)_
- **[todo]** Implement search_report, ingest_report, record_journal_watermark or remove docstring promises (v-embeddings: missing implementations).
- **[todo]** Implement band escalation when offset reaches BAND_SPAN (v-picker claim 2), and add cross-band ordering test.
- **[todo]** Refactor _embed_batch to raise on EmbeddingError instead of returning None (v-embeddings: error swallowing).
- *…6 more for this target*

### `mutation-operators.py`

*14 claim(s); one model (deepseek-chat), one look; agents: s02-mutation-operators, v-mutation-operators*

- **[risk]** WEAKEN_COMPARISON can produce equivalent mutants when the boundary shift does not affect control flow (e.g., x < 5 → x <= 5 when x is always integer and the condition is followed by an else that handles equality).
- **[risk]** DROP_CALL on a guard whose result is unused and has no side effect produces an equivalent mutant that trivially_equivalent() misses because bytecode differs (the call instruction is removed).
- **[risk]** UNDECIDABLE: claim about DROP_CALL guard unused/no side effect (2) - needs analysis of `trivially_equivalent()` and call handling in `mutation-operators.py`.
- **[risk]** UNDECIDABLE: claim about WEAKEN_COMPARISON equivalent mutants (1) - requires audit of `mutation-operators.py` to see if it handles integer boundary cases.
- **[risk]** UNDECIDABLE: claim about CHANGE_CONSTANT on overwritten/unused constant (4) - needs to see how `mutation-operators.py` performs equivalence checks.
- **[risk]** UNDECIDABLE: suggestion to add SWAP_BRANCHES and REMOVE_SIDE_EFFECT operators (7) - depends on current operator set in `mutation-operators.py`.
- **[risk]** UNDECIDABLE: claim about EARLY_RETURN after docstring (3) - requires inspecting `mutation-operators.py` for equivalent mutant detection logic.
- **[risk]** UNDECIDABLE: suggestion to add redundancy check for WEAKEN_COMPARISON (6) - requires seeing existing checks in `mutation-operators.py`.
- *…6 more for this target*

### `shift-arch-memory.py`

*13 claim(s); one model (deepseek-chat), one look; agents: s20-shift-arch-memory, v-shift-arch-memory*

- **[risk]** UNDECIDABLE: Claim 5 (arch_memory.save() not atomic on Windows) cannot be verified without shift-arch-memory.py. _(also raised by 6 other)_
- **[risk]** UNDECIDABLE: Claim 4 (No concurrency test coverage) cannot be verified without shift-arch-memory.py and tests. _(also raised by 1 other)_
- **[risk]** Windows atomic write failure: os.replace raises if target exists on Windows, causing data loss
- **[risk]** UNDECIDABLE: Claim 9 (Windows CI/documentation) cannot be verified without project context.
- **[risk]** Lock steal race: two processes can both think they hold the lock
- **[risk]** Dead code in remaining() second parse branch never executes
- **[risk]** No test coverage for any concurrency scenario
- **[risk]** arch_memory.save() not atomic on Windows
- *…5 more for this target*

*95 further target(s) not shown; full set in `runs/eval/findings.json`.*