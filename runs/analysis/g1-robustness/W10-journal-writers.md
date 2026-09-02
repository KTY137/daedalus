# W10 — Journal/append writer enumeration (read-only, static)

Scope: `daedalus/` and `tools/` (Python only). `tests/`, `apps/` out of scope.
`vault/`, `.quarantine/`, `daedalus/lanes/` untouched.

Repo: `C:/Users/Administrator/daedalus`
HEAD at time of read: `c4b27e099c0ef5d7532f462e48911330b048eb2`
(2026-09-02T12:35:04+02:00, "Merge packet/g1-batshim-fix"). This is later than
the `54f09753` named in the task; the tree moved under me while reading, which
is expected on a shared checkout with a fix packet in flight. `git status
--porcelain` on every file discussed below was empty at read time — everything
cited here is committed, not a dirty edit I am looking at mid-write.

**`daedalus/journal_io.py` EXISTS at this commit.** It exports
`append_lines(journal, lines) -> int`: serializes the batch to one `bytes`
blob, takes `daedalus.atomic.ExclusiveFileLock` (cross-process, `msvcrt`/`fcntl`,
persistent lock file, held across the whole open+seek+write), opens the
journal with `os.O_WRONLY|O_CREAT|O_APPEND`, does exactly one `os.lseek` +
one `os.write`, and raises `ShortJournalWrite` if the OS reports a short
write instead of silently returning success. Five production call sites
already use it (see "Already-ported" below).

## Raw pattern counts (grep, before reading)

| pattern | daedalus/ | tools/ | notes |
|---|---|---|---|
| `open(...["']a` (any of `a`, `a+`, `ab`, `a+b`) | 16 lines | 5 lines | 2 of the 16 are comments (MEASURED notes, not code); 1 of the 5 is a string literal inside a test-generator, not a real writer |
| `O_APPEND` | 4 (1 in an AST-pattern list, 3 in `journal_io.py` itself) | 0 | repo-wide (incl. `runs/`, `tests/`, `experiments/`) there are 16 more outside scope |
| `FileHandler` (stdlib `logging`) | 0 | 0 | confirmed empty both dirs |
| `logging.basicConfig(` | 0 | 0 | no stdlib file-logging anywhere in scope |
| `"ab"`/`"a+"`/`"a+b"` specifically | 5 lines | 0 | all lock files or one test-fixture byte-corruption target, see table |
| `writelines` | 1 (AST pattern-detector's own vocabulary list) | 0 | no production `.writelines()` call on a journal in scope |
| literal `.jsonl'`/`.ndjson'` path strings | 13 lines | 3 lines | path constants / references, several are readers not writers |
| `append_lines` (journal_io calls) | 5 production sites + the definition | 0 | |
| `journal_io` (any mention) | 7 files matched by grep (misses `journal_io.py` itself, which doesn't self-reference by name) | 0 | |

**Enumerated (read, not just grepped): 17 live raw-append code sites** in
scope (13 in `daedalus/`, 4 in `tools/`), plus 1 retired dead file and 1 grep
false positive, both excluded from the 17 and called out separately below.
Denominator for "raw append writers": **17**.

## THE REPOINT LIST

| file:line | target path (expression) | mode/mechanism | line-shaped? | flush/fsync | lock held | multi-writer path? | role | already-ported? |
|---|---|---|---|---|---|---|---|---|
| `daedalus/atomic.py:91` | `self.path` (caller-supplied lock file) | `Path.open("a+b")` inside `ExclusiveFileLock.__enter__` | no — it's the lock handle itself, never written to | no | this **is** the lock primitive | N/A (lock file, not payload) | infra (lock, not journal) | N/A |
| `daedalus/adapters/transport.py:39` | `self.path` (`JsonlTransportSink`, path is caller-configured) | `with self.path.open("a", encoding="utf-8")` | yes, JSONL | no | `asyncio.Lock()` — **in-process only** | possible if two processes point sinks at one path (unconfirmed downstream) | (a)/(b) borderline — docstring says "preserving every normalized input/output"; sounds evidentiary but I did not trace every caller | **no** |
| `daedalus/council/bus.py:558` | `store_path` = `runs/council/<council_id>.jsonl` (hash-chained transcript, `prev`/`entry_sha`) | `with store_path.open("a", encoding="utf-8") as fh: fh.write(...)` | yes, JSONL, hash-chained like the amendment ledger | no | `threading.Lock()` (`_WRITE_LOCK`, module-level) — **in-process only, not cross-process** | **yes** — every session's council process shares this path | **(a)** — a broken chain here reproduces exactly the "dropped record breaks previous-record-hash" failure the amendment chain is vulnerable to, applied to council transcripts | **no** |
| `daedalus/desktop_runtime.py:372` | `self.log_path` (desktop runtime operational log) | `with self.log_path.open("a", encoding="utf-8") as out` | yes, line-per-message but free text, not JSONL | no | none | possible if >1 desktop runtime instance targets the same repo root (unconfirmed; plausible on a shared checkout) | (b)/(c) operational log | no |
| `daedalus/desktop_runtime.py:383` | `self.log_path` | `self.log_path.open("ab", buffering=0)` — child-process stdout/stderr capture | no, raw bytes tail | unbuffered by design (`buffering=0`) substitutes for flush | none | same file as the line above — same process's own log, so not concurrent with itself but is with the line above's writer | (b)/(c) operational log | no |
| `daedalus/hooks/events.py:390` | `note` = per-day vault session note (precompact diary) | `with note.open("a", encoding="utf-8", newline="") as handle` | yes, markdown lines | no | **yes** — cross-process `_Lock` (`O_CREAT\|O_EXCL` + stale-break-by-rename, from `hooks/_common.py`) wraps this call | yes (many sessions), but protected | (c) diary — best-protected of the un-migrated sites | no (but already has an equivalent cross-process lock, so lower priority) |
| `daedalus/hooks/_common.py:334` | `d / LEDGER_NAME` = `runs/hooks/ledger.jsonl` | `with path.open("a", encoding="utf-8") as fh` inside `ledger_append()`, wrapped only in `try/except OSError: pass` | yes, JSONL | no | **none at all** | **yes, definitely** — every Claude Code hook invocation from every session on this shared checkout appends here | **(a)/(b) borderline** — named "ledger", records policy-dispatcher outcomes, but the code explicitly says "a ledger that cannot be written must not cost a turn" (designed loss-tolerant). Not named/shaped like the 5 already-fixed journals, so easy to skip. | **no** |
| `daedalus/interfaces/bridge/projection.py:62` | `log` = `inbox / "LATEST.log"` (bridge terminal-report arrival signal) | `with log.open("a", encoding="utf-8") as handle`, wrapped in bare `try/except OSError: pass` | yes, one line per arrival | no | none | plausible — multiple bridge report producers could race on one inbox | **(a)/(b) borderline** — it's the single documented "idempotent arrival signal" for terminal reports; a silently dropped line could mean a completed WorkItem's arrival is never observed | **no** |
| `daedalus/interfaces/bridge/watcher.py:68` | `self.path` (bridge watcher ownership lock file) | `self._fh = self.path.open("a+b")` inside `_BridgeWatcherLock.__enter__` | no — lock handle | no | this **is** the lock primitive | N/A | infra (lock, not journal) | N/A |
| `daedalus/kernel/policy/ledger.py:267` | `self.path` (budget lock file, separate from the ledger payload file) | `self._fh = open(self.path, "a+b")` inside `_BudgetLock.__enter__` | no — lock handle | no | this **is** the lock primitive (cross-process, `msvcrt`/`fcntl`) | N/A | infra (lock guarding an atomic-replace ledger elsewhere in the same file, not an append target) | N/A |
| `daedalus/kernel/promotion_trust_root.py:752` | `claim_ledger_path(repo_root)` = promotion-state-root `/ claims.jsonl` | `with open(path, "a", encoding="utf-8") as fh: fh.write(...); fh.flush(); os.fsync(fh.fileno())` in `_append_claim()` | yes, JSONL, hash-chained (`prev_sha256`) | **yes** (flush+fsync) | **none** — no cross-process lock anywhere in this file (grepped for `Lock`/`threading`/`flock`/`msvcrt`: zero hits) | conditionally yes: the `O_CREAT\|O_EXCL` single-use *marker* serializes two claims of the **same** replay key, but two **different** approvals claimed concurrently by two processes both reach this raw buffered append unserialized | **(a) — high priority.** Directly gates sealed promotion (invariant 5) and provenance (invariant 7); this is the audit trail proving an `OwnerApproval` was consumed exactly once | **no** |
| `daedalus/kernel/promotion_trust_root.py:956` | `second_factor_ledger_path(repo_root)` = promotion-state-root `/ second_factor.jsonl` | `with open(path, "a", encoding="utf-8") as fh: fh.write(...); fh.flush(); os.fsync(fh.fileno())` in `_append_record()` | yes, JSONL | **yes** (flush+fsync) | **none** (same file, same absence of locking as above) | plausible under concurrent promotion attempts | **(a) — high priority.** Docstring: *"MANDATORY FOR THE RECORD: the caller turns a failure here into a REJECT... losing an authoritative event without saying so is precisely what 'never silently dropped' forbids."* The irony is that the buffered-append mechanism it uses is exactly the class of write this repo just proved silently drops records. | **no** |
| `daedalus/runtimes/live_probe_drivers.py:492` | `copy` = a temp-directory copy of a provider binary | `with copy.open("ab") as handle: handle.write(b"\x00daedalus-live-probe-drift")` | no — one deliberate byte-flip for a drift-detection self-test, not a journal | no | none needed (single-writer, single-use temp file) | no | not a journal at all — included only because it matched the grep pattern | N/A |
| `tools/watchdog.py:166` | `root / LOG_REL` (watchdog's own operational log, size-rotated) | `with p.open("a", encoding="utf-8") as fh`, wrapped in `try/except OSError: pass` | yes, free-text lines | no | none | possible if >1 watchdog instance runs against the same repo root (watchdog is designed as a singleton daemon, so low real risk) | (b) operational telemetry | no |
| `tools/watchdog.py:702` | `root / PRUNES_LOG_REL` | `with (...).open("a", encoding="utf-8", newline="") as fh`, `try/except OSError: pass` | yes | no | none | same low-risk single-daemon assumption | (b) telemetry (also mirrored into `mstate`/`STATE_REL` via `save_json`, which is atomic-replace, not append) | no |
| `tools/watchdog.py:749` | `root / SWEEPS_LOG_REL` | `with (...).open("a", encoding="utf-8") as fh`, `try/except OSError: pass` | yes | no | none | same as above | (b) telemetry | no |
| `tools/watchdog.py:974` | `root / "vault/Sessions/<day>.md"` | `with note.open("a", encoding="utf-8") as fh`, `try/except OSError: pass` | yes, markdown session lines | no | none | possible (many watchdog/session writers over a day) — but out of instruction scope to touch `vault/` | (c) cosmetic diary | no |

### Excluded from the 17 (named, not silently dropped)

- `daedalus/kairos/_gated_writes_legacy.py.src:541` — `self._fh = open(self.path, "a+b")`. File extension is `.py.src`, **not** live Python (nothing imports a `.py.src` module); its own module docstring says it is retired history superseded by `daedalus.spine.attempt.TaskAttempt`. Not a live writer.
- `tools/self_test.py:78` — the string `"open(_rp, 'a', encoding='utf-8').write('\\nseeded\\n')\n"` is a **Python source literal embedded in a test-generator string**, not an executed append. False positive from the grep pattern.
- `daedalus/gates/repository_write_inventory.py:494` — `"O_APPEND"` appears in a `set` of AST-flag tokens inside `_os_open_flags()`, the write-classifier instrument's own vocabulary. This file is the **scanner**, not a writer; it is the mechanism that would let the port packet grep for `os.open(..., O_APPEND)` sites programmatically.
- `daedalus/kairos/archive.py:171` and `daedalus/memory/__init__.py:62` — matched the `open(...["']a` grep only inside a `# MEASURED 2026-09-02...` comment documenting the historical bug; the live code at both sites already calls `journal_io.append_lines` (see below).

## Already-ported column (journal_io.append_lines callers)

All five are committed at HEAD `c4b27e09`, each with a `# MEASURED 2026-09-02`
comment citing an exact concurrent-writer record-loss count that motivated the
switch:

| caller | target path | measured loss before the fix |
|---|---|---|
| `daedalus/memory/__init__.py:74` (`append_event`) | `memory/events.local.jsonl` | 4 of 120 records, 6 concurrent appenders |
| `daedalus/progress.py:296` (`ProgressLog.append`) | `runs/progress/events.jsonl` (default) | 115/118/119 of 120 across 3 runs, 6 concurrent appenders |
| `daedalus/metrics.py:50` (`record`) | `memory/offload_metrics.local.jsonl` | 111 of 120 rows, 6 concurrent appenders |
| `daedalus/kairos/archive.py:185` (`record_attempt`) | caller-supplied `path` (attempt notebook) | 6 of 60 records, 4 concurrent processes |
| `daedalus/council/canary.py:1207` (`append_history`) | `runs/canary/history.jsonl` (default) | 14 of 64 results, 4 concurrent writers — "the largest proportional loss of the five journals" |

All five wrap the `append_lines` call in an **additional** process-local
`threading.Lock`, explicitly documented (in `progress.py` and `metrics.py`) as
answering a different question than the cross-process lock inside
`journal_io` — both are kept.

## Path → writers map (paths with more than one writer highlighted)

| path | writer site(s) |
|---|---|
| `memory/events.local.jsonl` | `daedalus/memory/__init__.py::append_event` only (via `journal_io`). `daedalus/memory/projection_worker.py`'s `JOURNAL_ID` constant is a **reader**-side identifier, not a second writer. |
| `memory/offload_metrics.local.jsonl` | `daedalus/metrics.py::record` only (via `journal_io`) — but called from **every session's** offload dispatch, so one path, one writer *function*, many concurrent *processes*. |
| `runs/progress/events.jsonl` | `daedalus/progress.py::ProgressLog.append` only (via `journal_io`) — same many-processes-one-function-one-path shape. |
| `runs/canary/history.jsonl` | `daedalus/council/canary.py::append_history` only (via `journal_io`) — explicitly documented as expected to be shared across runs. |
| **`runs/hooks/ledger.jsonl`** | **writer:** `daedalus/hooks/_common.py::ledger_append` (raw, unlocked). **reader:** `tools/watchdog.py:824` (health check, read-only — confirmed no second writer there). One writer function, but invoked by every hook call from every session on the shared checkout — the exact concurrency shape that produced the measured loss elsewhere, and this site has **no lock at all**, not even the in-process `threading.Lock` the already-fixed journals use as a second layer. |
| **`runs/council/<council_id>.jsonl`** | **writer:** `daedalus/council/bus.py::_append_chain` / `append_round` (raw `open("a")`, in-process `threading.Lock` only). I did not find a second writer to this exact JSONL path inside `daedalus/`/`tools/`. *(Out-of-scope note: `runs/council/summarize.py::append_record` writes a **different** file — the human-readable `room.md` transcript, not this JSONL — using a single `os.write` on an `O_APPEND` fd + `fsync`, and its own docstring says explicitly *"the hook appends to this same file concurrently"*, confirming `room.md` has ≥2 writer sites. That file and its second writer are under `runs/`, outside this task's scope, but the port packet should know the pattern recurs there too, already fixed independently of `journal_io`.)* |
| `daedalus/kernel/promotion_trust_root.py`'s `claims.jsonl` | `_append_claim` only — single writer *function*, unlocked, reachable from every promotion attempt. |
| `daedalus/kernel/promotion_trust_root.py`'s `second_factor.jsonl` | `_append_record` only (also reachable through an injectable `sink` test seam, which is not a second production writer). |
| **`docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl`** | **out of the `daedalus/`+`tools/` scope**, but named explicitly in the task (item 6) so recorded here: written today only by one-off owner tools under `docs/recovery/` — `gate0_seal_append_record.py`, `amendment_004_descope_harness_kit.py`, `amendment_005_kit.py`, `amendment_006_kit.py`, `amendment_gesamtplan_kit.py`, `unify_and_retire_guard_kit.py` — each a **separate script**, so the path has **more than one distinct writer site** over the repository's history, even though only one is ever run at a time. See "Amendment chain" section below. |

## Amendment chain: exactly how it is written today

`docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl` is **not** written by any
runtime code path in `daedalus/` or `tools/`. It is written only by hand-run,
one-shot owner tools in `docs/recovery/`. Read in full:
`docs/recovery/gate0_seal_append_record.py` — its mechanism, generalized
across the sibling recovery kits:

1. Read the whole chain with `CHAIN.read_text(...).splitlines()`, parse the
   last non-blank line as JSON, and refuse if the tail `sequence` is not
   exactly the expected predecessor (e.g. "refuses if sequence 8 is already
   appended" / "refuses if tail is not sequence 7").
2. Compute `record_sha256` over the canonical
   `json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
   encoding, chaining `previous_record_sha256` from the read tail.
3. Append with **`CHAIN.open("a", encoding="utf-8", newline="\n")`** — a raw
   buffered text append, no lock, no fsync, no `journal_io`.
4. Print the appended line and exit.

Correctness today rests entirely on **operational** guarantees, not a
technical lock: `AGENTS.md`/`tools/watchdog.py` explicitly forbid an agent
from touching this file ("NEVER TOUCH... docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl");
the amendment protocol (master plan §16) requires the owner to run the script
"FROM THE REPO ROOT, in YOUR terminal"; and each script's own sequence check
makes a second concurrent run against the same tail a hard refusal on the
loser (it reads the same stale tail, but whichever writes second either
still refuses because its own precondition already failed, or, in the
genuinely racy window between the read and the append, could still produce
the exact same silent-loss shape `journal_io` fixes elsewhere — nothing
technical prevents two owner terminals from racing this open("a") call).
**A dropped record here would break `previous_record_sha256` chaining
exactly as feared** — the same graph-integrity failure mode this task's
context describes for `journal_io`'s five already-fixed journals — but the
practical exposure is far lower than the shared-checkout, many-sessions
concurrency pattern that produced the measured 4–14% losses elsewhere,
because this path is used at most a few times total, one owner, one
terminal, one sequence-gated invocation at a time. I found no evidence any
of these six recovery scripts currently share an active concurrent-run
window; several are already-consumed one-shots (their own guard would refuse
a second run today).

## Findings: where loss is a correctness failure (role a, priority for the port)

1. **`daedalus/kernel/promotion_trust_root.py:752` (`claims.jsonl`) and `:956`
   (`second_factor.jsonl`)** — no cross-process lock at all, raw
   `open(path, "a")` + `flush()` + `os.fsync()`. These are the audit trail for
   sealed, single-use promotion approvals (master-plan invariant 5) and the
   demoted HMAC second factor. `flush()+fsync()` proves the bytes hit disk;
   it does not prove two processes' buffered writes didn't interleave at the
   OS level the way `journal_io`'s docstring measured. The `O_CREAT|O_EXCL`
   marker file only serializes two claims of the *identical* replay key —
   two *different* approvals claimed concurrently are unprotected. This is
   the single strongest candidate the port packet should check first: it is
   role (a) by the plan's own invariants 1/5/7, uses the exact defect shape
   named in the task, and is not on the already-fixed list.
2. **`daedalus/council/bus.py:558` (`runs/council/<id>.jsonl` hash-chained
   transcript)** — only an in-process `threading.Lock` guards a raw
   `open("a")` + `fh.write()`. The file is explicitly hash-chained
   (`prev`/`entry_sha`), so a dropped line breaks the chain the same way a
   dropped amendment record would. If more than one process can append to
   the same `council_id` transcript (plausible — councils can be
   long-running and multi-agent), this reproduces the measured defect.
3. **`daedalus/hooks/_common.py:334` (`runs/hooks/ledger.jsonl`)** — no lock
   whatsoever, every hook invocation from every session on this shared
   checkout appends here (per this repo's own standing lesson: "many
   sessions, one index"). Explicitly designed loss-tolerant by policy
   ("errors are swallowed... must not cost a turn"), so may be an accepted
   risk rather than a defect — but it is exactly the kind of file a
   port-by-`grep`-for-known-names pass would miss, because it is never
   called a "journal" in its own docstring the way the other five are.
4. **`daedalus/interfaces/bridge/projection.py:62` (`LATEST.log`)** — no
   lock, bare `except OSError: pass`. Named the "single append-only
   report-arrival signal path" for the file bridge; a dropped line could
   make a completed WorkItem's terminal report look like it never arrived.

## Non-`open("a")` writers a naive grep-for-append-mode pass would miss

None found as **executed** production code. Specifically:

- No `logging.FileHandler` or `logging.basicConfig(filename=...)` anywhere in
  `daedalus/` or `tools/` (checked both directories independently — zero
  hits in either).
- No `os.open(..., os.O_APPEND, ...)` outside `journal_io.py` itself (the
  correct implementation) and the AST scanner's vocabulary list
  (`repository_write_inventory.py`) inside the `daedalus/`/`tools/` scope.
  (Two more real `O_APPEND` writers exist repo-wide but outside scope:
  `runs/council/summarize.py::append_record`, already using the correct
  single-`os.write`+`fsync` recipe, and `experiments/concurrency/probe_append_atomicity.py`,
  which is the reproduction harness for this exact bug, not production code.)
- No read-modify-write-whole-file `.jsonl` rewrite pattern (`write_text(existing
  + new_line)` or equivalent) found for any JSONL/NDJSON path in scope — the
  `write_text()` calls I found (`interfaces/bridge/journal.py:180`,
  `interfaces/bridge/queue.py:166`, `interfaces/bridge/watcher.py:182`) are
  all full-payload atomic replacements of single-snapshot files (heartbeat,
  queue state), not journals.
- **The one real "would have been missed" case is `daedalus/hooks/_common.py:334`**
  (finding 3 above): it is line-shaped, appended with raw `open("a")`, shares
  its path across every session, and is never named "journal" or "ledger" in
  a way a naive search for the five already-known names would surface. I
  would flag this as the single most likely site for the port packet to
  overlook, followed by `interfaces/bridge/projection.py:62`.

## What I could not determine statically

- Whether `daedalus/adapters/transport.py::JsonlTransportSink` (line 39) is
  ever configured with a path that more than one process writes to — I did
  not trace every constructor call site; its docstring's wording
  ("preserving every normalized input/output") reads evidentiary but I could
  not confirm downstream consumers treat it as authoritative within the
  static-only, no-execution constraint of this task.
- Whether `desktop_runtime.py`'s `log_path` (lines 372, 383) is ever shared
  by two concurrently-running desktop runtime instances against the same
  repository root — plausible on this shared-checkout machine, not
  confirmed statically.
- Whether the six `docs/recovery/*.py` amendment-chain writers have ever
  actually raced each other in practice — each carries its own
  sequence-tail guard, and several report themselves as already-consumed
  one-shots, but I did not execute anything to confirm a script's guard
  still refuses today (that would require running code, which is out of
  scope for this task).
- Runtime behavior in general: this is a static read-only enumeration; no
  code was executed, no test was run, and no measurement was reproduced.
  Every "measured" figure quoted above is copied from comments already
  committed in the source, not independently re-measured by me.
