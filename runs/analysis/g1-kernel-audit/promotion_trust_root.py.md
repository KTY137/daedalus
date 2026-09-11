# daedalus/kernel/promotion_trust_root.py  (1343 lines)

Base 54f09753. Static read-only.

## What the file is for

Implements the D5 "hybrid-B-as-root" sealed-promotion trust root: authenticates
a git-signed `promote/<candidate-sha>` tag against a committed allowed-signers
file as the primary authority ("root" B via `verify_promotion_approval`),
re-authenticates the demoted HMAC approval-ledger consumption as an advisory
"second factor" (`evaluate_second_factor`) that can add a divergence note but
never grant, reads the precommitted `TRUTH_TABLE` to decide PROMOTE/REJECT
(`evaluate_promotion_trust`), writes a mandatory second-factor record before
returning any verdict, and enforces single-use consumption of a valid root
approval (`claim_approval`) via an atomic `O_CREAT|O_EXCL` marker file plus a
hash-chained `claims.jsonl` ledger.

## Axis 1 — docstring truth

### CONFIRMED
None. Every universal/authority claim I traced against the code held.

### PLAUSIBLE
None.

### Checked and honest
- `:6-9` "verified with `git verify-tag` against an allowed-signers file read
  from the COMMITTED tree" — `_committed_allowed_signers` (`:307-323`) reads via
  `git show HEAD:<rel>`, never the working tree; re-read every call, no cache
  (`:99` "no cache" matches — no module-level or instance cache anywhere).
- `:45` "the signing key never enters this process" — the module reads/writes
  only the *public* allowed-signers blob (`:307-323`) and calls `git
  verify-tag`; grep of the file shows no private-key material handled anywhere.
- `:455-461` "`git verify-tag`'s EXIT CODE is the only authority... Nothing
  here reads that text for a verdict" — confirmed at `:527` (`if
  verified.returncode != 0`); the only other read of `_err(verified)` is the
  `_SIGNER_RE` extraction at `:531-532`, which feeds only the audit-trail
  `signer` field, never a branch.
- `:449` "Returns a verdict; never raises" — `verify_promotion_approval` wraps
  its whole body in `try/except _Refused/except Exception` (`:580-590`) and
  every branch returns an `ApprovalVerdict`.
- `:64-66` "It performs no repository mutation. It decides; the caller
  promotes." — the only `git` subcommands invoked anywhere in the file are
  `show`, `cat-file -t`, `cat-file tag`, `verify-tag`, `rev-parse --verify`
  (`:283-296`, call sites `:314,489,503,518-520,536`) — all read-only.
- `:58` "the attempt path uses [`scrubbed_child_env`]... to strip every
  approval secret out of a child environment" — confirmed real caller:
  `daedalus/kernel/attempt_execution.py:489-491,1032-1043` both do `from
  daedalus.kernel.promotion_trust_root import scrubbed_child_env; env =
  scrubbed_child_env()`.
- `:1183` "The single-use claim happens only in the sealed stage" —
  `evaluate_promotion_trust` gates `claim_approval(...)` behind `if promote and
  stage == SEALED_STAGE` (`:1290-1294`); confirmed by tracing the live caller
  chain (`daedalus/kairos/gated_writes.py:236-252` calls with
  `PREAUTHORIZATION_STAGE` before any lock, `:271-298` calls with
  `SEALED_STAGE` only inside `_PromotionLock`).
- `:1118-1129` "stage... was only ever compared with `== SEALED_STAGE`... every
  other string fell through... a stage this module cannot interpret is not a
  promotion to evaluate" — confirmed: `evaluate_promotion_trust` checks `stage
  not in PROMOTION_STAGES` (`:1197`, `PROMOTION_STAGES = (SEALED_STAGE,
  PREAUTHORIZATION_STAGE)` at `:1111`) and refuses via
  `_unknown_stage_decision` before the root verifier is even called (`:1198`).
- `:34-38` "the second-factor outcome is appended... before any verdict is
  returned. If that append fails, the decision is REJECT" — confirmed at
  `:1252-1269`: `record_error` from a failed `_append_record`/sink forces
  `promote = outcome == "PROMOTE" and record_error is None`.
- `:807-825` two-record replay table (marker × chain → verdict) — confirmed
  exactly matches the code path `:864-891`: `key in spent` (chain says spent)
  refuses regardless of marker; `present` without a chain entry refuses as
  "marker without ledger"; only absent+unspent reaches the atomic
  `os.open(..., O_CREAT|O_EXCL)` at `:894`.

## Axis 2 — effect surface

| site (file:line) | effect | registry row | covered? |
|---|---|---|---|
| `_git` → `subprocess.run` `:289-291` (called from `:314,489,503,518-520,536`) | PROCESS_SPAWN | `python.promote_candidates` (`daedalus/spine/effect_boundary.py:444-452`, `target="daedalus.kairos.gated_writes:promote_candidates"`) declares `Effect.PROCESS_SPAWN` | plausibly yes, non-kernel target |
| `tempfile.mkstemp` + `os.fdopen(...,"wb")` write `:514-516` | FILESYSTEM_WRITE | same row, declares `Effect.FILESYSTEM_WRITE` | plausibly yes |
| `os.unlink(signers_path)` `:523` | FILESYSTEM_WRITE (delete) | same row | plausibly yes |
| `os.environ.get("LOCALAPPDATA")` `:644` | ENV_READ | none named | no row targets this helper directly; low-risk read |
| `root.mkdir(...)` `:751,859,955` | FILESYSTEM_WRITE | same row | plausibly yes |
| `open(path,"a")` + `fsync` `:752-755,956-959` (claim ledger, second-factor ledger) | FILESYSTEM_WRITE | same row | plausibly yes |
| `os.open(marker, O_CREAT\|O_EXCL\|O_WRONLY)` `:894` (the single-use claim) | FILESYSTEM_WRITE | same row; also `guard_contracts=("...","promotion.owner_approval")` at `:456` | plausibly yes, and this is the row's namesake guard |
| `os.stat(marker)` `:767`, `os.stat(legacy/name)` `:666` | FILESYSTEM read/stat | same row | plausibly yes |

### Notes
No row has `target="daedalus.kernel.promotion_trust_root...."` — consistent
with the brief's measured fact that only 4 rows target `daedalus.kernel....`
and none is this file. The one row that plausibly covers everything here is
`python.promote_candidates` (`target="daedalus.kairos.gated_writes:promote_candidates"`),
because `daedalus/kernel/promotion.py:10-13` enforces structurally (via
`tests/test_promotion_trust_root_single_caller.py`) that `promotion.py` is the
*only* caller of this module's root, and `promotion.py` is in turn only called
by `gated_writes.promote_candidates` per that function's own docstring
(`_gated_writes_legacy.py.src:907-909`: "NOT called automatically by anything
in this module or by `KairosScheduler`; an explicit, separate call"). See
Axis 5: that entrypoint currently has **zero** production callers repo-wide, so
today this registry coverage is theoretical, not exercised — but the row does
exist and does declare the right effect set for when it is wired.

## Axis 3 — unreleased resources

No findings. Every acquire has a bounded release:
- `tempfile.mkstemp` (`:514`): the fd is wrapped in `with os.fdopen(fd,
  "wb") as fh:` (`:516`), which closes it on both normal exit and exception;
  the temp *file* is then removed in an outer `finally: os.unlink(signers_path)`
  (`:521-525`), so no fd or file leaks even if `fh.write` raises.
- `os.open(marker, O_CREAT|O_EXCL|O_WRONLY)` (`:894`): the returned fd is
  immediately wrapped in `with os.fdopen(fd, "w", ...) as fh:` (`:906`), a
  context manager, so the fd closes whether or not `fh.write` raises; the
  `except OSError: pass` (`:908-911`) only swallows the *annotation* write
  failure, not a leak — the marker's existence (not its contents) is what
  makes the approval spent, per the module's own comment.
- Every `open(path, ...)` call (`:708` read, `:752` append, `:956` append) uses
  a `with` block. No bare `open()`/`os.open()` without a matching close or
  context manager anywhere in the file.
- No sqlite, no `Popen`, no `threading.Lock`/`filelock`, no socket, no
  `ExitStack` in this file (sqlite lives in `approvals.py`).

## Axis 4 — validator gaps (W4 class)

No findings; one near-miss checked and closed by construction:
- `nonce` is validated at parse time by `_NONCE_RE = r"^[0-9A-Za-z._:/-]{8,200}$"`
  (`:161`) — the same weak shape as the W4-flagged `_ID_RE` (admits `.` and `/`
  with no `..`-segment check). However the raw nonce is **never** used to build
  a path: `replay_key(nonce, candidate_sha256)` (`:676-679`) always hashes it
  through `sha256(...)` first, and only that 64-hex digest becomes the marker
  filename `f"{key}.claimed"` (`:851`). A value validated by the weak regex
  never reaches path construction unhashed — checked, not a finding.
- `candidate_sha256` / `evidence_sha256` are validated by strict `_SHA256_RE`
  (`^[0-9a-f]{64}$`, `:159`) before being used to build the tag ref
  `f"refs/tags/promote/{candidate_sha256}"` (`:468,488`) — no traversal chars
  possible.
- `source_revision` is validated by strict `_REVISION_RE` (40/64 hex only,
  `:160`) before any use.
- `repo_root` is operator-supplied input to this boundary (not derived from
  attacker-controlled approval fields), so it is out of the W4 threat shape
  this axis targets.

## Axis 5 — dead / duplicate

### CONFIRMED
- `PromotionTrustRootError` (`:183-188`, exported in `__all__` at `:1322`) is
  **never raised** anywhere. Grep `raise PromotionTrustRootError` across the
  whole repository (excluding stale copy directories) returns zero hits. The
  class is referenced only by its own definition and by
  `tests/test_promotion_trust_root_single_caller.py:58`, which merely asserts
  it appears in the module's `__all__` list (a shape check, not a
  raise-behavior test). Every actual refusal path in this module (`_Refused`
  is caught internally and converted, `evaluate_promotion_trust` never raises)
  returns a verdict/decision object with `approved=False`/`promote=False`
  instead — consistent with the module's own "never raises" design principle
  at `:449`, which appears to have superseded whatever earlier design used
  this exception class. Dead code with no promised reader in its own
  (near-absent) docstring.
- The whole chain this module implements (`evaluate_promotion_trust`,
  `claim_approval`, `verify_promotion_approval`) is reachable in production
  only through `daedalus.kairos.gated_writes.promote_candidates`
  (structurally enforced single-caller test, see Axis 2 Notes), and that
  function itself has **zero** production callers anywhere in `daedalus/`
  (verified: `grep -rn "promote_candidates(" --include=*.py daedalus/` matches
  only its own `def` line, its own docstring/comments, and
  `daedalus/loop.py:14` which documents *by design* that the loop never calls
  it). `daedalus/kernel/approvals.py`'s dossier covers the parallel finding for
  `ApprovalLedger.consume()`. This is a seam (fully built, heavily tested,
  unwired), not dead code by the brief's definition — reported jointly across
  both dossiers because it is one finding spanning two owned files.

### PLAUSIBLE
None beyond the above.

## OWNED-FLAG

Not applicable — this file is not `offload_lease.py`, the flagged
`attempt_execution.py` string-evidence sites, or `effects.py`.

## What I did not cover

Did not execute or import any code (static read only, per hard rules); did not
empirically verify `git verify-tag`/`cat-file` exit-code semantics claimed in
the docstring, only that the code branches solely on `returncode`; did not
deep-audit `daedalus/kairos/gated_writes.py` or
`daedalus/kairos/_gated_writes_legacy.py.src` beyond what was needed to trace
the promotion-entry ordering and the Axis-5 caller question (out of my
assigned slice); did not read `daedalus/spine/killswitch.py`'s
`control_root`/`profile_root_disagreement` internals beyond confirming they
are imported and called (also out of slice).
