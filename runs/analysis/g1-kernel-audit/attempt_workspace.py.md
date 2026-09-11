# daedalus/kernel/attempt_workspace.py  (280 lines)

Base 54f09753. Static read-only. Auditor: parent (W6 slice, subagent cap hit).

## What the file is for

`IsolatedAttemptCoordinator` admits one pre-provisioned, checkout-external
workspace parent directory, retains its identity, and materializes one Attempt's
input source tree under it. It refuses to *create* the root itself — the root
must be provisioned by the deployment boundary — and re-validates the retained
identity before each materialization seam.

## Axis 1 — docstring truth

### Checked and honest — and unusually well-earned

- `:62-69` `_resolve_workspace_parent` claims a TOCTOU window was closed by not
  creating the root. Verified: there is no `mkdir` in the function, and the
  ordering it describes (disjointness check on `prospective` → strict resolve →
  disjointness check again on `parent`) is exactly what `:81-113` does.
  `tests/kernel/test_isolated_attempt_lifecycle_review.py:100-128` pins this
  mechanically by AST — including stripping the docstring first (`:106-110`)
  precisely so the docstring cannot satisfy the check that the code must. That
  is the correct construction of an anti-overclaim test and worth naming as
  positive evidence.
- `:30-36` `_workspace_root_identity` explains why directory timestamps are
  excluded from the identity. Verified: the hashed dict at `:46-53` contains
  only `schema`, `path`, `st_dev`, `st_ino` — no mtime. Claim matches code.
- `:216-220` `prepare` — "``started_at`` remains a compatibility-only
  predecessor argument. The coordinator does not forward it." Verified: `:221`
  is `del started_at`, and the `self.ledger.begin(...)` call at `:237-243` passes
  no `started_at`. Honest.
- `:174` `_require_stable_workspace_parent` — "Revalidate retained root identity
  before each materialization seam." Enumerated the seams: called at `:222`
  (entry to `prepare`) and `:246` (immediately before `joinpath` + materialize).
  Two seams, two calls. The universal "each" holds.

### No overclaims found

No `authenticated`, `guaranteed`, or `always` appears in this module. The
strongest word used is "must", consistently in refusal messages. Clean.

## Axis 2 — effect surface

| site | effect | registry row | covered |
| --- | --- | --- | --- |
| `:249` `source_store.materialize_tree(...)` | FILESYSTEM_WRITE | `effect_boundary.py:391` `kernel.attempt.prepare` | yes |
| `:264` `source_store.put_bytes(...)` (fault report) | FILESYSTEM_WRITE | same row | yes |
| `:237` `self.ledger.begin(...)` | FILESYSTEM_WRITE | `:348` `kernel.attempt.begin` | yes (nested registered row) |
| `:267` `self.ledger.complete(...)` | FILESYSTEM_WRITE | `:370` `kernel.attempt.complete` | yes (nested registered row) |
| `:38` `os.stat(follow_symlinks=False)`, `:45/:73/:93/:181` `resolve()`, `:100/:188` `is_dir` | read-only | n/a | n/a |

`__init__` (`:119-171`) performs only read-only inspection — no writes. Correctly
unregistered. No subprocess, no network, no `os.environ` read anywhere in the file.

This is one of only four kernel files with a registry row at all
(`effect_boundary.py:348, 370, 391, 2304` out of 108 rows), and its effect
surface genuinely matches its row. Positive evidence.

## Axis 3 — unreleased resources

### Checked — no leak, and the half-state concern is refuted

The obvious worry is `:248-276`: if `materialize_tree` raises mid-way, is a
partially materialized workspace left behind? **No.**
`source_trees.py:650-680` materializes into a `tempfile.mkdtemp` staging
directory, writes every entry there, and only then does `os.replace(staging,
target)`, wrapped in `except BaseException: shutil.rmtree(staging,
ignore_errors=True); raise` (`:678-680`). The destination is created atomically
or not at all.

### PLAUSIBLE — one narrow residue window (belongs to source_trees.py, W7)

In `source_trees.py:677-680`, `os.replace(staging, target)` is followed by
`self._fsync_directory(target.parent)` **inside** the same `try`. If the fsync
raises, the `except BaseException` handler runs `shutil.rmtree(staging, ...)` —
but `staging` no longer exists (it was renamed), so `ignore_errors=True` makes
the cleanup a silent no-op while `target` remains fully materialized on disk.
`prepare`'s handler at `:257-276` then terminalizes the attempt as `"faulted"`
and raises, leaving a materialized workspace for an attempt the ledger records
as faulted. Low severity; flagged to W7 as it is that file's line.

## Axis 4 — validator gaps (W4 class)

### CONFIRMED — W4's F-W4-01 `..` traversal is **blocked**; the report needs correcting

W4 (`runs/analysis/g1-security-sweep/W4-findings.md`) files F-W4-01 as a
CONFIRMED defect chain: weak `_identifier` on `attempt_id` →
`_workspace_relative_path` → `prepare` `:236,247,249-252` →
`materialize_tree`. I traced the ordering and the `..` cannot reach `joinpath`:

1. `:236` `relative = _workspace_relative_path(attempt)` — untrusted string,
   as W4 says.
2. `:237` `begin = self.ledger.begin(..., workspace_relative_path=relative)`.
3. Inside `begin`, `attempt_ledger.py:257-281` constructs `AttemptStartRecord`,
   whose `__post_init__` runs `_repo_path(...)` at `attempt_contracts.py:135`
   and then requires the result to start with `"attempts/"` (`:136-137`).
   `_repo_path` (`contracts/canonical.py:127-128`) rejects any `..` part.
4. `:244` `if not begin.execute: return` — reaching `:247` therefore requires
   step 3 to have succeeded.
5. Only then `:247` `workspace = self.workspace_parent.joinpath(*relative.split("/"))`.

Measured with `.venv/Scripts/python.exe`:
`PurePosixPath('attempts/x/../../../tmp/e-d').parts` ==
`('attempts','x','..','..','..','tmp','e-d')` → `any(part=='..')` is True → the
record constructor raises `ValueError` at step 3. The raise is outside the
`try` at `:248`, so it propagates uncaught: **fail-closed**.

Note the construction at `:257` also precedes `_intent_for` (`:282`) and
`record_intent` (`:287`), so the refusal happens before any ledger write too.

I am not calling W4 wrong about the *shape* — `_identifier` is genuinely too
weak and `_workspace_relative_path` genuinely interpolates it into a path — but
the "CONFIRMED defect chain" verdict does not survive tracing the callee. This
correction matters because a fix aimed at F-W4-01 as written would be aimed at
the wrong line.

### CONFIRMED — the real residual gap: `_repo_path` only checks `:` in segment 0

`_repo_path` (`contracts/canonical.py:129`) rejects drive-qualification with
`if path.parts and ":" in path.parts[0]`. Only the **first** segment. `_ID_RE`
(`canonical.py:27`) explicitly permits `:` in an identifier, and
`_workspace_relative_path` places `attempt_id` in segment **1**
(`"attempts/{attempt_id}-..."`), so segment 0 is always the literal `"attempts"`
and the check can never fire on attacker-controlled input.

Measured: `PurePosixPath('attempts/x:evil-d')` → not absolute, no `..` part,
`':' in parts[0]` is False → **`_repo_path` accepts it**, and it starts with
`"attempts/"` so `:136` accepts it too. The value reaches `joinpath` at `:247`.

Impact, measured honestly rather than assumed — I probed the actual filesystem
(`runs/analysis/g1-kernel-audit/_probe/`, since removed):
`Path(r'...\attempts\x:evil-abc123').mkdir()` fails with
`FileNotFoundError [WinError 3]`. So on Windows this is a **refusal, not a write
escape**: materialization faults, `prepare` terminalizes the attempt, no
traversal. On POSIX `:` is a legal filename character, so it would simply create
an oddly named directory still inside the workspace parent — also contained.

So: CONFIRMED validator asymmetry, **no CONFIRMED exploit**. I am filing it as a
correctness gap in `_repo_path` (its drive-qualification check does not do what
its error message claims for any segment but the first), not as a traversal.

### `attempt_id` is the only weak-validated value reaching a path here

`mission_id`, `task_id`, `campaign_id` do not appear in this file. `start_id`
and `receipt_id` are `_identifier`-validated but are used only as record fields
and SQL bound parameters, never in path construction.

## Axis 5 — dead / duplicate

- `_is_same_or_within` (imported at `:13`): 6 call sites, all inside
  `_assert_disjoint` at `:22-26`, which is itself called 6 times (`:81, :86,
  :103, :108, :190, :195`). **W4's soundness precondition holds at all 6**: every
  candidate is a resolved path — `prospective` = `resolve(strict=False)` (`:73`),
  `parent` = `resolve(strict=True)` (`:93`), `current` = `resolve(strict=True)`
  (`:181`); the protected sides `primary` (`:139`) and `cas_root` (`:150`) are
  both `resolve(strict=True)`. The two `strict=False` uses at `:81/:86` are
  benign because `:93` independently requires the parent to already exist.
  No unresolved-path caller exists. This is an enumeration, not a spot check.
- `tests/kernel/test_isolated_attempt_lifecycle_review.py:123` asserts
  `source.count("_assert_disjoint") == 4`. I checked whether this stale-looking
  count is a broken guard: it is **not** — `:105-107` scopes `source` to
  `_resolve_workspace_parent` alone, which contains exactly 4 of the 6 calls.
  Correct test.
- No dead code in this file. Everything defined is called.

## What I did not cover

`attempt_execution.py`, which may construct workspaces on a second path, is
owned by the running chip-refusal packet — flagged, not audited.
