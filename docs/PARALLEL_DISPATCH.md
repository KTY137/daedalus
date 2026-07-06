# Parallel Dispatch — design & safety model (Era 3 #2)

Theseus' coffee gripe: `Ikarus.dispatch` was a `for` loop, so "6 agents in
parallel" was really six agents in a queue. This is the safe way to make it real
— and, just as importantly, the reason it stays **off by default**.

## The bug we refuse to reintroduce

Live writes are verified by **disk ground truth**: `offload` hashes the repo
*before* and *after* the worker runs and diffs the two snapshots
(`_repo_snapshot`). That is what makes "wrote yes" honest — the model's
self-report is never trusted.

The default snapshot is **whole-repo** (path-agnostic) on purpose: the agentic
tool-loop can write files outside the hint list, and we want to catch that.

But two tasks running **concurrently on the same repo** break this: task A's
after-snapshot is taken while task B is mid-write, so A's `disk_changed`
includes B's file. Cross-attribution — the exact class of bug this project is
paranoid about. A naive `ThreadPoolExecutor` around the loop would ship it.

## The safe design

Parallelism is **opt-in** (`dispatch(..., parallel=True)`) and correct by
construction:

1. **Per-task attribution.** In parallel mode each `offload` runs with
   `isolate_paths=True`, so it hashes **only that task's declared paths**
   (`_scoped_snapshot`), never the whole repo. Task A can no longer see task B's
   writes. Safe because the parallel lane is the **scoped-write** lane (≤3
   declared paths, written deterministically).

2. **Conflict refusal.** Before parallelizing, `_paths_overlap` checks that no
   two **write** tasks share a path. If they do (two agents editing one file =
   a real edit conflict, not just an attribution problem), the batch **falls
   back to sequential** and emits an honest `note` row. Advisory tasks write
   nothing, so they never conflict.

3. **Thread-safe metrics.** The metrics append is now under a lock so two
   workers finishing at once can't interleave into one corrupt JSONL line.

4. **Bounded.** Concurrency is capped at `Ikarus.max_workers`.

5. **Order preserved.** Output rows keep input order regardless of completion
   order, so callers/report tables read the same as sequential.

## What it does and does NOT buy you

- **Does:** overlap the *verify / test / IO* phases of independent tasks, and
  model the crew honestly as concurrent workers.
- **Does not:** give 6× model throughput. Ollama on one GPU serializes
  generation, so several qwen calls queue on the device. The real throughput
  win needs **multiple runtimes** (a second local model / a remote lane), which
  the runtime registry already anticipates.

## Still sequential by default

`parallel=False` remains the default because the whole-repo tripwire (catching
writes outside `--paths`) is a stronger safety net for untrusted/agentic runs.
Parallel is for batches of **disjoint, scoped** maintenance tasks — exactly the
"free agents doing bookkeeping" workload.

## Not yet (future)

- **Per-runtime worktrees.** For true multi-file feature builds, give each
  concurrent task its own `git worktree` / temp checkout and merge
  non-conflicting results back — removes the disjoint-paths restriction.
- **Wave dependencies.** Today waves are order-only; a real DAG would let
  dependent tasks sequence while independent ones fan out.

## Tests

`tests/test_parallel_dispatch.py`:
- `_paths_overlap` truth table (write conflict vs advisory vs disjoint).
- disjoint tasks: real concurrency proven **deterministically** (a shared
  counter shows ≥2 workers inside `run()` at once — not wall-time), and each
  task's `wrote` equals exactly its own paths (no cross-attribution).
- overlapping write tasks fall back to sequential with a `note`.
