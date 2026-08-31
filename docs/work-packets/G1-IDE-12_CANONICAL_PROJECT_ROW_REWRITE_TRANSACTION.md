# G1-IDE-12 - Canonical project-row rewrite transaction

Status: builder-verified on Windows and POSIX; independent review/system acceptance pending
Classification: `ALIGNED`
Active gate: **Gate 1 - Renovation ignition slice**
Owner: repository owner; no automatic merge, promotion, or Gate transition
Base revision: `52b4baa5`
Dependency: independently reviewed G1-IDE-11 candidate
Master-plan authority: `docs/IKARUS_ARIADNE_MASTER_PLAN.md` Revision 10
Master-plan SHA-256:
`5e269de9857940cd1d6162eaf9236d4db8e77427d189122db178812b49b259dc`

## Primary claim

The two live runtime rewrites of an existing authoritative
`projects/*.json` row are linearized under the same G1-IDE-11 registry lock as
one bounded `read -> mutate -> atomic replace` transaction. Concurrent,
disjoint team and autonomy changes are retained. Lock-free readers observe
only the complete old or complete new JSON bytes.

The lock is serialization state only. It is not a second registry, event
store, policy authority, candidate identity, or promotion path.

## Reproduced baselines

- A synchronized `save_team("demo", {"max_workers": 9})` and
  `save_autonomy("demo", {"default": "autonomous"})` made both writers read
  the same initial row and forced autonomy to publish last. Both returned
  without an exception, but the final `max_workers` was `3`; the team update
  was silently lost.
- An instrumented direct rewrite paused after truncating and writing only half
  of a row. Concurrent `load_project` raised `JSONDecodeError` with an
  unterminated string. The writer then completed successfully; a lock-free
  reader can therefore observe torn JSON today.
- With `PROJECT_DIR` isolated in a runtime temporary directory,
  `save_autonomy("../outside", ...)` changed `outside.json` in the parent and
  left the registry empty. The measured result was
  `{"outside_changed": true, "registry_rows": []}`. Because the HTTP router
  splits before URL-decoding, an encoded slash can reach the same project-name
  construction.

These are the retained RED controls. Sequential happy-path saves are not an
adequate baseline for this packet.

## Dependencies and exact scope

This packet stacks on G1-IDE-11's fixed `projects/.registry.lock`, bounded
`ExclusiveFileLock`, strict row identity verification, and atomic publisher.
The two HTTP routes already cross the CENTRAL `web.mutations_put`
`begin_effect` boundary before dispatch.

In-scope paths are exactly:

- `daedalus/projects.py`;
- `daedalus/hierarchy.py`;
- `daedalus/control_plane.py`;
- only the project-row PUT error mapping in `daedalus/web_api.py`;
- `tests/test_project_row_rewrite.py`;
- any required explicit write-surface pin;
- this work packet.

No change to `daedalus/atomic.py`, `.gitignore`, the master plan, or its
amendment chain is required by this packet.

## Canonical transaction contract

1. One projects-layer helper validates the requested project as an exact,
   direct, existing JSON stem. Empty names, separators, traversal components,
   NULs, non-strings, and aliases are refused before target-row I/O.
2. The helper acquires the exact G1-IDE-11 registry lock, then resolves the
   requested stem again from direct `PROJECT_DIR.glob("*.json")` rows.
3. While holding that lock it reads and verifies an object row with a valid
   absolute native or foreign-platform `repo_root` identity.
4. The mutation callback receives only the row's `team` object. It cannot
   reach `name`, `repo_root`, policy, source scope, runtime configuration, or
   other root fields through this API. A pre-existing non-object `team` fails
   closed.
5. The complete row is serialized and published with the canonical
   `write_text_atomic`; the lock covers read, mutation, serialization, and
   replace.
6. `save_team` changes only its existing allowlisted team keys.
   `save_autonomy` preserves the existing replacement semantics for the
   `agents` and `capabilities` maps and normalization semantics for `default`.
7. Every cooperating writer re-reads after lock acquisition. Disjoint patches
   compose; overlapping writes to one property are serialized
   last-writer-wins.
8. Lock-open, bounded-lock-timeout, invalid-row, mutation, serialization, and
   replace failures never report success. Failures before replace preserve the
   exact old target bytes.

## Acceptance matrix

1. The exact disjoint RED probe always finishes with both
   `max_workers=9` and `autonomy.default=autonomous`, including a real
   two-process variant on Windows and POSIX.
2. A writer paused after its complete temp write but before replace leaves
   repeated lock-free reads on the complete old row; after release they read
   the complete new row. No empty, partial, or unparsable JSON is observed.
3. Parallel read/rewrite stress observes only valid complete old/new states.
4. A registration and rewrite contend on the same fixed lock; neither can
   observe a partial row or mint a duplicate canonical-root identity.
5. Lock timeout/open failure and exhausted atomic replace fail closed, preserve
   exact old bytes, leave no successful response, and map to HTTP `503`.
6. Invalid JSON, invalid UTF-8, non-object rows, missing/invalid roots, and a
   non-object `team` are refused without rewriting the target.
7. Empty, encoded or literal traversal, either path separator, NUL, unknown
   project, and non-string identifiers cannot read or write outside the direct
   existing registry row.
8. Root identity, policy, source scope, and unknown extension fields survive
   both save operations unchanged.
9. The HTTP order remains
   `begin:web.mutations_put -> registry lock -> atomic replace`; a refused
   effect start reaches neither lock nor temp/target write.
10. Registration, Web API, effect-boundary, atomic-publisher, and write-surface
    regression selections pass on Windows and in a read-only-mounted Linux
    candidate run.

## Frozen inputs and budget

- Storage: the existing authoritative `projects/*.json` rows only.
- Serialization: the existing local OS-held registry lock and existing
  sibling-temp atomic replace; no model, network, or paid service.
- Lock wait: the existing bounded five-second local wait.
- Evaluation: deterministic thread/process races, HTTP ordering, fault
  injection, focused Python gates, Windows reader contention, and POSIX
  verification.

## Effect-boundary statement and non-claims

`DaedalusHandler.do_PUT` already crosses the CENTRAL `web.mutations_put`
boundary before either live row rewrite. This packet adds no effectful
entrypoint and performs no HTTP-path write before that start.

The packet does not claim a project-, payload-, or target-bound durable
receipt, a terminal operation record, compare-and-swap or stale-client
conflict detection, deep merge of client-supplied maps, crash/power-loss
`fsync` durability, or coordination across machines and non-cooperating
network filesystems.

## Forbidden scope and stop criteria

- no second lock file/protocol, registry, event store, or row identity;
- no reader locking, automatic corrupt/duplicate-row repair, or data migration;
- no schema, policy, lane, receipt, evaluator, plan, or promotion change;
- no widening into Ikarus multi-file apply or unrelated `.agentenv` stores;
- no silent deep-merge change for full client-supplied maps;
- no automatic merge, promotion, or branch publication.

Stop the packet and retain the negative result if a cooperating reader can
observe partial JSON, the deterministic disjoint probe loses a value, rewrite
and registration do not share one lock, bounded failure changes the old bytes
or reports success, or the helper can reach a non-direct row or mutate a root
field.

## Rollback

Remove only this packet's projects-layer rewrite helper, the two caller
wirings, PUT error mapping, and focused tests. G1-IDE-11's lock and registration
fix, all existing project rows, and all unrelated user data remain untouched.
There is no migration and therefore no data rollback.

## Retained residuals

- On Windows, an uncoordinated raw `Path.read_text` can briefly lose its open
  to the atomic `MoveFileEx` replacement and raise `PermissionError`.  The
  contention stress retains that platform result and proves that every
  successful lock-free read is complete old/new JSON; this packet does not
  claim wait-free reader availability.
- `vscode-agent-env/extension.js` contains a raw `saveProjectTeam` definition,
  but there is no production callsite; the webview's `saveTeam` message is not
  handled. This is dead bypass code and a broken UI path, not a live writer in
  this claim. It must be deleted or rewired through the canonical API before
  that UI is enabled.
- `scripts/daedalus_desktop_sidecar.py` has a create-once startup seed outside
  the running server lifecycle. Two overlapping sidecars remain a separate
  packaging race.
- Tauri upgrade migration stages only missing files into a new backend
  generation, but a concurrently changing old generation can yield a stale or
  cross-row-inconsistent source snapshot. That lifecycle problem is separate.
- `agents_registry` and `categories` write repo-local `.agentenv` stores, not
  project rows; their same-file rewrite races need a separate packet.
- Direct Python calls have no operation-specific authorization. In particular,
  `ikarus_chat.chat(apply=True)` can update other files before `save_team`, so
  its multi-artifact apply remains non-atomic.
- Unknown external editors remain non-cooperating writers. Atomic replace
  protects readers only for writers routed through this transaction.

## Evidence handoff

Builder verification on Windows 11 / CPython 3.13.5, stacked on the reviewed
but still owner-held G1-IDE-11 working-tree candidate:

- `python -m pytest -q tests/test_project_row_rewrite.py`:
  `43 passed, 1 skipped`; the retained skip is missing Windows symlink
  privilege (`WinError 1314`).
- `python -m pytest -q tests/test_project_row_rewrite.py
  tests/test_project_registration.py`: `71 passed, 1 skipped`.
- Adding Web API, effect-boundary, atomic-publisher inventory, and write-surface
  regressions: `150 passed, 1 skipped, 2 subtests passed`.
- Network-disabled `python:3.12-slim`, source and test packages mounted
  read-only, `/tmp` as tmpfs: `72 passed`.  Pytest plugin autoload was disabled
  because the read-only Windows package mount lacked Linux `typing_extensions`;
  neither focused file uses the omitted async plugin.  The first failed
  collection attempt is retained as environment evidence rather than reported
  as a product-test failure.
- `git diff --check` passed for the packet implementation and focused tests;
  Git reported only the existing LF-to-CRLF working-tree warnings.

No candidate commit, merge, promotion, push, independent review, full system CI,
or owner decision was performed.  Those remain required before a dependent
Work Packet may enter build.
