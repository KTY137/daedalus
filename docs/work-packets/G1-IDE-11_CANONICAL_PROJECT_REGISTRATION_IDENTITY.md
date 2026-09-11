# G1-IDE-11 — Canonical project-registration identity

Status: builder-verified; independently reviewed; held for owner review
Classification: `ALIGNED`
Active gate: **Gate 1 — Renovation ignition slice**
Owner: repository owner; no automatic merge, promotion, or Gate transition
Base revision: `52b4baa5`
Master-plan authority: `docs/IKARUS_ARIADNE_MASTER_PLAN.md` Revision 10
Master-plan SHA-256:
`5e269de9857940cd1d6162eaf9236d4db8e77427d189122db178812b49b259dc`

## Primary claim

The canonical repository root remains the single identity of a project when
multiple local requests register it concurrently. A fixed, OS-held registry
lock serializes the existing scan, name choice, immutable publication, and
verification as one bounded transaction. It is serialization state only, not
a registry, event store, policy authority, or candidate identity.

## Reproduced baselines

- Two synchronized calls registered the same canonical root with names
  `alpha` and `beta`. A delayed publication seam measured two simultaneous
  publishers; both calls returned `created=true`, and the registry contained
  both `alpha.json` and `beta.json`.
- A legacy relative `repo_root` was resolved against the process CWD. The same
  absolute directory was first recognized from one CWD and then published as
  a second row from another. Relative registry roots therefore cannot support
  a process-independent identity.

The per-filename immutable publish correctly prevents overwrite, but neither
baseline can be solved without a registry-wide identity transaction.

## Dependencies and exact scope

This packet depends on the existing G1-IDE-10 `POST /api/projects` contract,
`publish_bytes_once`, and the already-CENTRAL `web.mutations` entrypoint. It
does not depend on the G1-IKARUS-12 reachability projection.

In-scope paths are exactly:

- `.gitignore`;
- `daedalus/atomic.py`;
- `daedalus/projects.py`;
- the project-registration error mapping in `daedalus/web_api.py`;
- `tests/test_project_registration.py`;
- the explicit `daedalus/atomic.py` pin in
  `tests/test_write_surface_coverage.py`;
- this work packet.

## Acceptance matrix

1. Root and explicit-name validation happen before registry state is created.
   Invalid request input retains the existing zero-write behavior.
2. One fixed `projects/.registry.lock` is opened without replacement and held
   across re-scan, name choice, publication, and existing-row verification.
3. Two concurrent registrations of one root under different names produce
   exactly one JSON row. Both callers return the same name/root; one reports
   `created=true`, the other `created=false`.
4. Concurrent HTTP requests preserve the API contract with one `201` and one
   `200`. The CENTRAL `web.mutations` effect start occurs before lock
   acquisition and publication; refusal prevents both.
5. A pre-existing but unlocked lock file is harmless. Kernel-released lock
   ownership after a holder exits or is killed permits the next registration.
6. Lock open/acquisition failure or bounded timeout fails closed, publishes no
   project JSON, and maps to HTTP `503` rather than validation `400`.
7. Unreadable, invalid-UTF-8, invalid-JSON, missing-root, relative-root, or
   requested-root-ambiguous registry rows fail closed without row mutation.
   Absolute foreign-platform paths remain stable stale rows instead of being
   interpreted relative to the current process.
8. Sequential idempotence, explicit-name collision handling, stable derived
   names, immutable publication, sorted project listing, and the Gate-1
   write-surface inventory remain green on Windows and POSIX.

## Frozen inputs and budget

- Storage: the existing authoritative `projects/*.json` registry only.
- Serialization: standard-library `msvcrt` byte-range lock on Windows and
  `fcntl.flock` on POSIX, consolidated as a dependency-free atomic primitive.
- Lock wait: bounded local wall-clock wait; no model call, network request, or
  paid service.
- Evaluation: deterministic thread/API contention, real two-process
  contention, crash release, fault injection, focused Python gates, and a
  read-only-mounted Linux container run.

## Effect-boundary statement and non-claims

`DaedalusHandler.do_POST` already crosses the CENTRAL `web.mutations`
`begin_effect` boundary before routing to registration. This packet adds no
effectful entrypoint and performs no write before that start on the HTTP path.
The ordering test does **not** claim that the existing generic receipt is
payload/slug/target bound, durably stored, or paired with a terminal outcome.
A dedicated registration effect contract is a separate migration.

## Forbidden scope

- no second project registry, identity, event store, or promotion path;
- no stale-lock deletion, PID ownership, inode replacement, or lock recovery
  heuristic;
- no repository copy/upload/move/delete and no registry-row rewrite/repair;
- no policy/lane widening, plan/amendment/evaluator edit, or automatic merge;
- no claim that a filesystem lock coordinates unrelated network filesystems or
  machines.

## Rollback

Remove the registry transaction lock, its ignored fixed filename, and the
concurrency/fault coverage. Existing `projects/*.json` user data is retained
and never deleted automatically.

## Retained negative evidence and residuals

- The exact two-row and relative-root baselines above are retained; passing
  only sequential idempotence is insufficient.
- `control_plane.save_autonomy` still rewrites a row without this registry
  lock. A torn read now refuses registration before publication, but can cause
  a transient `503`. General row-rewrite atomicity is a separate packet.
- The generic web mutation receipt is discarded and does not prove a durable
  operation-specific terminal record.
- Pre-existing duplicate roots are refused when that root is registered; this
  packet does not silently repair or delete ambiguous user data.

## Evidence handoff

- Clean candidate: ignored detached worktree
  `.daedalus_worktrees/g1-ide-11`, exactly on base `52b4baa5`.
- Candidate commit: intentionally none. The reviewed diff is held uncommitted;
  no automatic merge, promotion, or branch publication was performed.
- Windows focused selection: `158 passed, 10 skipped`. The skips are the
  retained missing symlink privilege (`WinError 1314`) and dependent macOS
  bundle fault variants.
- Linux `python:3.12-slim`, with the candidate mounted read-only:
  `43 passed` for project registration and the write-surface contract.
- Independent Windows/Linux review: `43/43 passed`, two final `GO` verdicts,
  no open blocker or High/Medium finding.
- `git diff --check` passed; the diff contains only the seven in-scope paths.
