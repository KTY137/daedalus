# daedalus/kernel/source_trees.py  (695 lines)

Base 54f09753. Static read-only.

## What the file is for

A filesystem-backed, SHA-256 content-addressed store (`SourceTreeStore`) that
captures an immutable regular-file tree from a source directory
(`capture_tree`) into hard-linked CAS objects under `<root>/objects/xx/yy...`,
and later materializes a stored manifest back out into a brand-new destination
directory (`materialize_tree`). It is the write sink at the end of the W4
chain: `IsolatedAttemptCoordinator.prepare` (attempt_workspace.py:249) calls
`materialize_tree` to stand up an Attempt's workspace from a `StoredSourceTree`.

## Axis 1 — docstring truth

### Checked and honest
- Module docstring (:1-7): "extends the existing artifacts identity boundary;
  ... does not define another artifact locator or digest authority" —
  confirmed: `ArtifactRef`/`artifact_locator` are imported from
  `daedalus.kernel.artifacts` (:20), not redefined here.
- Module docstring (:6): "materializes them only into a new destination" —
  `materialize_tree` (:643-646) refuses if `target.exists() or
  target.is_symlink()`, so it never writes into an existing path. True.
- `:52` "every CI host rather than being covered only by a Windows-only
  branch" (re: `_stable_metadata_fields`) — the platform-name parameter and
  the `os.name != "nt"` branch (:58-59) make the field set deterministic and
  testable cross-platform. True as far as this file goes.
- `:207/:465` "ignored_roots must contain top-level names only" — enforced
  immediately after by `"/" in item` checks (:206, :464). True.
- No instance of `authenticated`, `guaranteed`, `enforced`, `impossible` in
  this file.

No overclaim found on Axis 1 for this file.

## Axis 2 — effect surface

| site (file:line) | effect | registry row | covered? |
| --- | --- | --- | --- |
| `SourceTreeStore.put_bytes` tempfile write + `os.link` (:317-332) | FILESYSTEM_WRITE | `kernel.attempt.prepare` (:394, via `materialize_tree`→no, put_bytes is called from `capture_tree`, not `materialize_tree`) / `cli.ignition` (:2563) | yes, transitively — `capture_tree` is only called from `daedalus/ignition/gate1.py` (production) and tests; gate1 runs under `daedalus.ignition.__main__:main`, registered as `cli.ignition` (FILESYSTEM_WRITE, PROCESS_SPAWN, PROCESS_CONTROL) |
| `SourceTreeStore.capture_tree` `os.walk`/`os.stat` reads + `put_bytes` (:437-582) | FILESYSTEM_WRITE | `cli.ignition` (:2563) | yes, same caller chain |
| `SourceTreeStore.materialize_tree` `tempfile.mkdtemp`, `output.open("xb")`, `os.replace`, `shutil.rmtree` (:652-681) | FILESYSTEM_WRITE | `kernel.attempt.prepare` (:394) | yes — sole production caller is `IsolatedAttemptCoordinator.prepare` (attempt_workspace.py:249), which is exactly that registered row |
| `SourceTreeStore.__init__` `Path.mkdir` (:264, :269) | FILESYSTEM_WRITE | same as constructor's caller (`kernel.attempt.prepare` / `cli.ignition`) | yes, same reasoning — store construction happens on the same call path as the writes above |

### Notes
No site in this file is reachable outside the two production callers
(`attempt_workspace.py::IsolatedAttemptCoordinator.prepare` and
`daedalus/ignition/gate1.py`, itself under `cli.ignition`). Both resolve to a
registered row, so this file has no orphaned effect surface — the sink end of
the W4 chain is covered even though the row lives on the caller, not here.
This file itself is a plain library module with no `EntrypointSpec` of its
own, which is expected and correct (it defines no `main`).

## Axis 3 — unreleased resources

### CONFIRMED
- **`materialize_tree` leaves the destination fully materialized and silently
  drops cleanup evidence when the post-rename fsync fails** —
  `source_trees.py:678` (`os.replace(staging, target)`) can succeed, then
  `source_trees.py:679` (`self._fsync_directory(target.parent)`) can raise.
  The handler at `source_trees.py:680-681`
  (`except BaseException: shutil.rmtree(staging, ignore_errors=True); raise`)
  then calls `rmtree` on `staging`, which **no longer exists** — it was
  renamed to `target` at :678 — so `ignore_errors=True` makes the "cleanup"
  a silent no-op. The re-raised exception propagates with `target` left fully
  populated on disk. Caller `attempt_workspace.py:249` catches this in
  `IsolatedAttemptCoordinator.prepare`'s `except Exception` at
  `attempt_workspace.py:257`, and terminalizes the attempt as `"faulted"`
  with `candidate_tree=None` (`attempt_workspace.py:267-273`). The ledger
  therefore records no candidate tree for this attempt, but the workspace
  directory at `self.workspace_parent.joinpath(*relative.split("/"))`
  (`attempt_workspace.py:247`) is left on disk with real materialized
  candidate source, and nothing in `daedalus/kernel/` reaps it: `grep -rn
  "workspace_parent\|IsolatedAttemptCoordinator" daedalus/kernel/*.py` and
  `grep -rn "rmtree\|cleanup\|reap" daedalus/kernel/attempt_ledger.py
  daedalus/kernel/attempt_contracts.py` show no consumer that ever removes a
  materialized-but-faulted workspace. This is a real, reachable defect: it is
  not a trust-boundary breach (the directory stays inside the
  attempt-owned `workspace_parent`, never inside the primary checkout), but it
  is (a) an unbounded disk leak with no visible reaper, and (b) evidence
  inconsistency — the ledger says `outcome=faulted, candidate_tree=None` while
  the filesystem holds a fully materialized tree the ledger never names. `_fsync_directory` (`source_trees.py:283-290`) is a plausible real failure
  mode: it does a bare `os.open`/`os.fsync`/`os.close` on the parent directory
  with no guard against `OSError` (e.g. `ENOSPC`, a remote/network filesystem
  hiccup, or a permissions race), any of which raises past the `try` at
  :655 into the `except BaseException` at :680.
- The same shape does **not** recur elsewhere in this file: `put_bytes`
  (:296-339) uses `tempfile.mkstemp` + `os.fdopen(...) as stream` (closed by
  the context manager) and unconditionally unlinks the temp name in
  `finally: temporary.unlink(missing_ok=True)` (:331-332) — the leftover
  temp file is always removed regardless of exception, and it never becomes
  the published object (that only happens via `os.link`, which leaves the
  original temp file in place until the `finally` clause). No leak there.
- `read_bytes` and `_read_source_file` both `os.open` a descriptor and close
  it in `finally: os.close(descriptor)` (:361-373, :408-422). Correct
  try/finally shape, exception path reachable and closes.

### Checked and honest
- `SourceTreeStore.capture_tree`'s directory walk (:480-563) is read-only; no
  acquisition to release.

## Axis 4 — validator gaps (W4 class)

### Checked and honest
- `SourceTreeEntry.path` (:138, validated at :144 via `_repo_path`, the
  *strict* validator per the W4 sweep) is the only manifest field that reaches
  path construction: `materialize_tree` builds
  `output = staging.joinpath(*entry.path.split("/"))` (:658) from it. Because
  `_repo_path` already rejects `..` segments, absolute paths, and
  drive-qualified paths at construction time (`SourceTreeEntry.__post_init__`,
  :144), and `materialize_tree` *additionally* re-checks containment against
  `staging_root` per entry (:660-664: `parent != staging_root and
  staging_root not in parent.parents`), this is the correct double-checked
  chain the W4 sweep names as the "correct validator" pattern, not the weak
  one. No siblings of the `_ID_RE`/`_identifier` weak-regex chain exist in
  this file.
- `SourceTreeManifest.tree_id` (:177, validated at :184 via `_identifier`,
  the *weak* regex per the W4 sweep) is stored in the manifest and used to
  build the `staging` tempdir *prefix string* (`f".{target.name}.tmp-"` at
  :653 — uses `target.name`, not `tree_id`) — **`tree_id` itself is never
  used to construct a path in this file.** It is carried only as metadata
  (`to_dict`/`from_dict`) and as a `dict`/tuple field. Not a finding per the
  brief's rule ("used only as a dict key or logged is not a finding").
- `ignored_roots` (:180, validated by `_sorted_strings(..., paths=True)`, not
  `_identifier`) is used only as a `casefold()` membership set (:474,
  :502-511), never concatenated into a path. Not a finding.

## Axis 5 — dead / duplicate

### CONFIRMED
- **`StoredSourceTree.locator` (:253-256) is an unwired compatibility shim.**
  Its own docstring says "Compatibility view for the earlier port candidate's
  return shape" — i.e. it names a *former* consumer, not a current one.
  `grep -rn "\.locator\b" daedalus/ tests/` (excluding stale duplicate trees
  under `apps/web/src-tauri/`, `.claude/worktrees/`, etc.) shows every
  production caller of a `StoredSourceTree` (`daedalus/kernel/attempt_ledger.py`,
  `daedalus/kernel/attempt_workspace.py`, `daedalus/ignition/gate1.py`) reaches
  the locator through `.ref.locator` directly (e.g.
  `attempt_ledger.py:274`, `gate1.py:1043/1045/1260/1318/1320`), never through
  `StoredSourceTree.locator`. The property's only caller in the whole repo is
  `tests/kernel/test_source_tree_store_adversarial.py:106`
  (`assert captured.locator == captured.ref.locator`), which merely proves the
  shim is self-consistent, not that anything depends on it. Zero production
  callers, one self-referential test. FINDING per Axis 5's own rule
  ("zero callers is a finding, not a verdict") — the docstring's own words
  confirm the intended reader (an "earlier port candidate") no longer exists
  in this tree, so this is dead code with an honest docstring, not a seam.

### Checked and honest
- `SourceTreeCaptureError`/`SourceTreeCorruptionError`/`SourceTreeStoreError`
  are all raised and caught across this file and re-raised/asserted-on in
  `tests/kernel/test_source_tree_store*.py`; not dead.
- No duplicate regex/validator/digest helper in this file — it imports
  `_sha256`, `_repo_path`, `_identifier`, `_locator_sha256` from
  `contracts/base.py` rather than reimplementing them.

## What I did not cover

- Did not re-derive the atomicity of `materialize_tree`'s staging/rename
  design (staging via `tempfile.mkdtemp`, per-entry containment check,
  `os.replace`) — per instructions, that was already verified upstream and I
  only investigated the post-rename fsync-failure residue.
- Did not run the test suite or exercise `_fsync_directory` failure
  injection; the reachability claim above is static (code-path) reasoning,
  not an executed reproduction.
- Did not audit `daedalus/kernel/artifacts.py` (`ArtifactRef`,
  `artifact_locator`) — out of my assigned slice.
