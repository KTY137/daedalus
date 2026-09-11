# W1 — File-handle / write-durability static sweep

Scope: `daedalus/` and `tools/` only (Python). `tests/`, `apps/`, `vault/`,
`.quarantine/`, `daedalus/lanes/` explicitly excluded per task brief.
Read-only. No files modified, no git mutation, no code executed.

Repo: `C:/Users/Administrator/daedalus`, branch `main` @ `54f0975398fd77120383c3af0ac5bb9291ef7064`.

Canonical defect writeup read first: `daedalus/kernel/effects.py` lines
576-587 (the `sqlite3.connect` `with`-is-only-a-transaction-scope leak, fixed
at 13 sites by an explicit `_connect()`/close discipline).

## Method and raw hit counts

Ripgrep via the `Grep` tool, `daedalus`+`tools`, `*.py`, tests excluded by path.

| pattern | raw hits (daedalus+tools) |
| --- | --- |
| `\bopen\(` | 117 |
| `os\.replace\(` | 13 |
| `os\.rename\(` | 3 |
| `shutil\.move\(` | 0 |
| `fsync` | 20 |
| `\.flush\(` | 10 |
| `\.write_(text\|bytes)\(` | 125 |
| `NamedTemporaryFile` | 3 |
| `zipfile.ZipFile\|tarfile.open\|gzip.open` | 5 |

Triage: all 117 `open(`/`os.open(` hits were read in context (not just
grepped). Of those, the large majority are already `with ...open(...) as`
and were cleared on sight; **20 sites were NOT syntactically inside a `with`**
(stored on `self`, raw fd captured in a local, or opened for a subprocess
pipe) and each of those 20 was individually read end-to-end to confirm its
close path. All 13 `os.replace` and 3 `os.rename` call sites in
`daedalus`/`tools` were read with their enclosing function. Of the 125
`write_text`/`write_bytes` hits, the ones feeding a subsequent
`os.replace`/`os.rename` (i.e. candidates for the fsync-gap and
direct-to-final-path findings below) were read in full; the remaining
`write_text`/`write_bytes` calls that write straight to a private,
single-reader status/log/report file (own process only, no companion process
polls it) were sampled and cleared as ordinary single-writer artifacts, not
enumerated file-by-file — see "NOT findings" for the boundary of that claim.

## Findings

### 1. LLM tool-loop writes a candidate source file directly, non-atomically, with only an in-memory rollback

`daedalus/providers/ollama.py:1378-1384`

```python
if windows:
    target.write_bytes(content.encode("utf-8"))
else:
    target.write_text(content, encoding="utf-8")
```

**Failure enabled**: `target` is the actual candidate source file inside the
repo/worktree being edited by the model's write tool, written directly (no
temp-sibling + `os.replace`). `self._backups[str(target)]` is populated just
before (line 1370) with the pre-write bytes, but that dict lives only in this
process's memory — `rollback()` (line 534) is a normal method, not registered
with `atexit`, and is only invoked from explicit exception/failure handling
inside the same run.

**On mid-operation kill**: a SIGKILL/host crash while `write_bytes`/`write_text`
is flushing its buffer leaves `target` truncated or half-written on disk, and
because the backup never left process memory, nothing on the next run knows
the original bytes to restore. This corrupts the file at its real, permanent
path — not a discardable `*.tmp` sibling. This is a stronger version of the
defect class than a stray temp file: it is the source of truth itself that
tears.

**Severity**: high. Direct hit on the plan's Invariant 2 ("candidate source
trees and code are content-addressed artifacts") — a torn write here happens
*before* any hashing/CAS step downstream would even notice, so a corrupted
file can sit in the working tree indistinguishable from a legitimate one
until someone diffs or re-hashes it. This is the model-facing write path,
not a peripheral log.

**Confidence**: certain (both the missing atomic-write route and the
process-local-only backup are read directly; whether anything upstream
re-verifies the file afterward was not traced — that would need a call-path
sweep out of this ticket's scope).

---

### 2. Two content-addressed evidence/artifact stores write straight to the canonical digest path, not through a temp sibling

`daedalus/kernel/artifacts.py:63-79` (`store_canonical_json`):

```python
path = directory / f"{ref.sha256}.json"
if path.exists():
    if path.read_bytes() != raw:
        raise ArtifactIdentityError("content-addressed artifact collision")
else:
    path.write_bytes(raw)
```

`daedalus/kernel/runtime_conformance.py:46-56` (`_store_artifact`) and
`:125-151` (`persist_conformance_receipt`) — identical shape, twice more:

```python
path = directory / f"{digest}.json"
if path.exists():
    if path.read_bytes() != raw:
        raise RuntimeConformanceError("content-addressed evidence collision")
else:
    path.write_bytes(raw)
```

**Failure enabled**: `write_bytes` on the canonical `{digest}.json` path
itself — not a `.tmp` sibling later renamed in. Two independent processes
racing to persist the *same* digest can both pass the `path.exists()` check
before either writes, then both call `write_bytes` against the same path
concurrently; POSIX/Windows give no cross-process atomicity guarantee for
that. `persist_conformance_receipt`'s own docstring states the design
assumption plainly: "a reader can refuse any persisted byte that no longer
hashes to its own name" — i.e. correctness here is delegated entirely to
every *reader* re-verifying the digest, and this sweep did not trace every
reader of these three functions to confirm that discipline is actually
followed everywhere (out of scope; flagging as the residual risk).

**On mid-operation kill**: a kill mid-`write_bytes` leaves a truncated file
sitting *at the canonical digest path* — `{digest}.json` on disk with fewer
bytes than the name promises — rather than at a `*.tmp` name a later sweep
would ignore. Contrast with the one call site in this repo that does this
correctly, `daedalus/kernel/source_trees.py` `SourceTreeStore.put_bytes`
(lines 296-339): `tempfile.mkstemp` → `os.fdopen` → write → `flush()` →
`os.fsync(stream.fileno())` → `os.link(temporary, target)` →
`self._fsync_directory(target.parent)` → unlink the temp name. That
function is in the same package family (`daedalus/kernel/`) as both
non-atomic call sites above and demonstrably knows the fix; the fix did not
propagate to the artifact/evidence stores, which is the exact "one place
had the correct implementation, the sibling call sites were copies that
never received it" shape the effects.py comment documents for the WAL leak.

**Severity**: high. This is squarely the Evidence boundary (Invariant 4)
and Artifact identity (Invariant 2) surface: `RuntimeConformanceReceipt`
and generic canonical-JSON artifacts are exactly the objects the promotion
path and gate evidence packets are built from.

**Confidence**: probable (the missing tmp+rename and the concurrent-write
race are certain from the code; whether the "reader always re-verifies"
mitigation the docstring claims is actually load-bearing everywhere needs a
reader-side trace this ticket did not do).

---

### 3. Systemic fsync gap in the canonical atomic-write helper and its hand-rolled copies (durability, not correctness)

`daedalus/atomic.py` is explicitly the repo's "one implementation" for
atomic publish (its own docstring names four legacy publishers that used to
roll their own retry and says this module replaces them). Its two most-used
entry points do **not** fsync:

```python
# daedalus/atomic.py:197-217  write_text_atomic
tmp.write_text(text, encoding=encoding, newline=newline)
replace_with_retry(tmp, target, retry_s)

# daedalus/atomic.py:220-227  write_bytes_atomic
tmp.write_bytes(data)
replace_with_retry(tmp, target, retry_s)
```

Contrast the third function in the *same file*,
`publish_bytes_once` (`daedalus/atomic.py:230-267`), which does it right:
`with tmp.open("xb") as fh: fh.write(data); fh.flush(); os.fsync(fh.fileno())`
before `os.link`.

Six in-scope callers of `write_text_atomic`/`write_bytes_atomic` inherit the
gap: `daedalus/arch_memory.py`, `daedalus/lanes/fanout.py` (lanes excluded
from this sweep's own reading but the caller list was grepped, not read),
`daedalus/loop.py`, `daedalus/projects.py`, `daedalus/shift.py`,
`daedalus/spine/killswitch.py`.

Independent hand-rolled copies of the identical "write tmp, `os.replace`,
no `flush()`/`fsync()`" pattern, each re-derived rather than importing
`daedalus.atomic`:

- `daedalus/kernel/policy/ledger.py:972-986` — `_BudgetLock._store`, **the
  monetary spend ledger**:
  ```python
  tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
  for attempt in range(10):
      os.replace(tmp, self.path)   # no flush()/fsync() anywhere above this
  ```
- `daedalus/hooks/_common.py:282-294` — `_write_atomic` (hook session state).
- `daedalus/desktop_runtime.py:1071-1077` — `_pin_host_key`'s
  `known_hosts_path` publish (SSH host-key trust store for the remote-Ollama
  tunnel).
- `daedalus/runtimes/fault_attestation_issuer.py:542-545` — `_atomic_write`
  (signed fault-attestation bundles).
- `tools/watchdog.py:193-197` — `save_json`.
- `tools/operability_drill.py:670-674` — receipt publish.

Sibling modules that DID get the fsync treatment, confirming it is a known,
applied pattern rather than an unknown technique:
`daedalus/kernel/source_trees.py` (`put_bytes`, `materialize`, both fsync
the file and the containing directory);
`daedalus/runtimes/container_fault_driver.py:489-499` `_atomic_write`
(`tempfile.mkstemp` → `os.fdopen` → `flush()` → `os.fsync()` → `os.replace`);
`daedalus/runtimes/provider_observation_store.py:435-455`
(`_fsync_file`/`_fsync_directory` helpers, POSIX-only by design, documented
Windows exception).

**Failure enabled**: `Path.write_text`/`write_bytes` close the handle via
their internal context manager, so the bytes reach the OS's page cache —
this **does** survive an ordinary process kill (SIGKILL/`taskkill`), which
is the scenario this sweep's brief centers on. It does **not** survive a
host crash or power loss before the page cache is written back, because
nothing calls `fsync`. `os.replace` on Windows additionally has no
directory-entry fsync equivalent exposed to Python, so even the *rename*
itself is not durably ordered against a crash.

**On mid-operation kill (process kill, not power loss)**: none of these six
sites tear the target file — `os.replace`/rename only ever runs after the
full tmp write returned, so a kill before that leaves an orphaned
`*.{pid}.tmp` sibling (harmless litter) and the *old* target intact. The
concrete risk is narrower than "torn write": it is **silent reversion after
power loss**, most acutely on the budget/spend ledger, where a reboot after
a crash-during-replace could resurrect a stale `spent_usd`/`entries` value
that is lower than what was truly billed, re-opening room under the period
ceiling that should already be closed.

**Severity**: medium. Every one of the direct callers above is an
effect-adjacent or kernel-adjacent path (money ledger, signed attestations,
hook state, SSH trust store), but the failure mode requires power loss or
unclean host shutdown specifically at the replace boundary, not an ordinary
kill — narrower than finding 1 or 2.

**Confidence**: certain for the missing `fsync` calls (read directly); the
downstream consequence ("ceiling reopens after reboot") is probable/logical
from the code, not reproduced (no code execution was performed per the
task's hard rules).

---

### 4. Minor: un-`with`-wrapped log handle in a concurrency test harness

`tools/bootstrap_receipt.py:654-685` (`run_concurrent`):

```python
for i in range(n):
    ...
    log = open(out_dir / f"concurrent-{i}.log", "wb")
    procs.append((i, out, log,
                  subprocess.Popen(cmd, cwd=str(CODE_ROOT), stdout=log,
                                   stderr=subprocess.STDOUT)))
...
for i, out, log, p in procs:
    codes.append({"index": i, "returncode": p.wait(), "out": str(out)})
    log.close()
```

**Failure enabled**: if `subprocess.Popen` raises for any `i > 0` (e.g. a
transient `OSError` spawning the child), the `log` handles already opened
for earlier iterations are never closed — the exception propagates out of
the function with those handles alive, released only by refcounting/GC or
process exit, the same non-deterministic-release shape as the sqlite3 defect
this sweep is modeled on, just for plain file handles instead of a WAL pair.

**On mid-operation kill**: harmless — these are per-process subprocess log
files under `out_dir`; a killed harness just leaves them present and
possibly not flushed past what the OS already wrote, which is expected for
a log.

**Severity**: low. `tools/bootstrap_receipt.py` is a concurrency-reproduction
test harness (`--single`/`run_concurrent`), not a product runtime path.

**Confidence**: certain the `with`/`try`-`finally` is absent; low real-world
impact.

---

### 5. Minor: temp patch file not guaranteed to be cleaned up on a hard kill

`daedalus/eval/correctness.py:786-802`:

```python
with tempfile.NamedTemporaryFile(prefix="daedalus-correctness-", suffix=".patch",
                                 delete=False) as fh:
    fh.write(patch_bytes)
    patch_path = fh.name
try:
    proc = subprocess.run(["git", "apply", ..., patch_path], ...)
    ...
finally:
    try:
        os.unlink(patch_path)
    except OSError:
        pass
```

**Failure enabled**: the handle itself is fine (closed via `with`,
`delete=False` is intentional so `git apply` can open it by path). The
cleanup is a `finally`, which does not run across a SIGKILL of this
process while `subprocess.run` is blocked inside it.

**On mid-operation kill**: one orphaned `daedalus-correctness-*.patch` file
in the system temp directory. No companion-file race, no evidence
corruption — this is `tempfile.gettempdir()` litter, not observable
product state.

**Severity**: low. Eval/gate machinery, not a kernel effect boundary; worst
case is disk litter.

**Confidence**: certain.

## NOT findings (negative evidence)

- **`sqlite3.connect` as `with`**: none found in `daedalus/`/`tools/` outside
  the already-fixed 13 sites the task brief references (`sqlite3` was
  explicitly out of scope for this ticket; not re-audited).
- **Raw `os.open()`/fd-returning opens NOT inside a `with`** (20 sites
  individually read): every one closes deterministically via `finally:
  os.close(descriptor)` or an explicit `__exit__`/`_close()` method on a
  small lock/log class (`ExclusiveFileLock`, `_Lock`, `_BridgeWatcherLock`,
  `_BudgetLock`, `_ShiftLock`, `PassLock` in `tools/watchdog.py`). Files:
  `daedalus/atomic.py:91`, `daedalus/desktop_runtime.py:383` (closed by all
  three callers — `_ide_log`/`_ollama_log`/`_tunnel_log` — verified each has
  a matching `.close()` on every stop path, and `close()` transitively calls
  `stop_ollama()` → `stop_ollama_transport()` which closes `_tunnel_log`),
  `daedalus/hooks/_common.py:232`, `daedalus/gates/repository_tree.py:166`,
  `daedalus/gates/repository_write_artifact_cas.py:436`,
  `daedalus/gates/repository_write_source_anchor_semantics.py:290`,
  `daedalus/kernel/source_trees.py:286,358,403`,
  `daedalus/kernel/offload_lease.py:1440`,
  `daedalus/kernel/promotion_trust_root.py:894`,
  `daedalus/kernel/promotion_fingerprint.py:43`,
  `daedalus/runtimes/admission/authorization.py:98`,
  `daedalus/runtimes/provider_observation_store.py:441,451`,
  `daedalus/shift.py:209`, `daedalus/interfaces/bridge/watcher.py:68`,
  `daedalus/kernel/policy/ledger.py:267`, `tools/watchdog.py:242`.
- **Handles stored on `self`/module globals**: the ones found
  (`ExclusiveFileLock._fh`, `_BridgeWatcherLock._fh`, `_BudgetLock._fh`,
  `_Lock.fd`, `_ShiftLock._fd`, `PassLock.fd`, `desktop_runtime`'s three
  `_*_log` handles) all document an explicit release point (lock
  `__exit__`, or an explicit `stop_*`/`close` method) rather than an
  unbounded/GC-only lifetime. None matches the "unbounded, undocumented"
  half of check #2 in the brief.
- **`zipfile.ZipFile`/`tarfile.open`/`gzip.open`** (5 raw hits): all 2
  in-scope call sites (`tools/smoke_packaged_resources.py:50`,
  `tools/select_desktop_release_assets.py:310`) are `with`-wrapped; the
  other 3 hits are in `tests/` (out of scope) or are the gate's own
  detector-string table (`daedalus/gates/repository_write_stdlib_delta.py`),
  not a call site.
- **`shutil.move`**: 0 hits in `daedalus`/`tools`.
- **Windows read-then-delete-while-open** (item 4 of the brief): no site
  found where a handle opened for read is deleted/renamed/moved before that
  same handle is closed — every `os.open`-for-read site closes the
  descriptor (`finally: os.close(...)`) strictly before any subsequent
  `unlink`/`replace`/`rename` in the same function. Not exhaustively proven
  for the whole tree (this check rode along with the `os.open` triage above
  rather than its own independent grep sweep), so flagged as checked-along,
  not separately enumerated.
- **`uproot.open` in `daedalus/twin/extractors/root_file_adapter.py:156`**:
  opens an in-memory `io.BytesIO(content)`, not a filesystem path — no OS
  file descriptor is held regardless of when/whether the returned object is
  closed, so it is out of the file-handle resource class this sweep covers.
- **`NamedTemporaryFile` in `daedalus/desktop_runtime.py:1048-1052`**:
  `with`-wrapped, `delete=False` is for a `ssh-keygen -lf` subprocess to
  open the path afterward, and the file is `unlink`ed in the enclosing
  `finally` regardless of match outcome — not a leak.
- **`with sqlite3.connect(...) as conn` NOT flagged again**: out of scope
  per the task brief ("sqlite3 is NOT yours"); not re-swept.

## Summary of enumerated set sizes

- `open(`/`os.open(` raw hits triaged: 117 of 117 (100%). 20 required
  individual function reads (not inside a `with`); all 20 cleared to a
  deterministic close point except the one already-covered dev-tool finding
  (#4 above).
- `os.replace`/`os.rename` raw hits triaged: 16 of 16 (100%) — 3 covered by
  finding #3 as new instances beyond the two already documented in
  `daedalus/atomic.py`, plus `daedalus/kernel/source_trees.py:678` and
  `daedalus/runtimes/container_fault_driver.py:496` confirmed clean
  (fsync'd before replace).
- `write_text`/`write_bytes` sites feeding a subsequent
  `os.replace`/`os.rename` or a canonical content-addressed path: all read;
  produced findings #1, #2, #3. The remaining ~110 `write_text`/`write_bytes`
  hits that write straight to a private single-process file (status/report/
  log with no documented second reader) were sampled, not individually
  enumerated — stated here as the boundary of the "NOT findings" claim
  rather than folded into a false "all clear" for that subset.
