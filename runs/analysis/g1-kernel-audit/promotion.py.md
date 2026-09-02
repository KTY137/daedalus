# daedalus/kernel/promotion.py  (638 lines)

Base 54f09753. Static read-only.

## What the file is for

Implements the D5 "sealed promotion" authorization boundary: binds one
consumed `OwnerApproval`, one passed `EvidencePacket`, an exact ordered
candidate batch, and a freshly-read live target-ref HEAD into a single
`PromotionAuthorization` digest. `authorize_promotion` is a pure primitive
that binds against the demoted HMAC-ledger view; `authorize_persisted_promotion`
is the sole production caller of `promotion_trust_root.evaluate_promotion_trust`
(structurally enforced by `tests/test_promotion_trust_root_single_caller.py`)
and anchors every comparison on the owner-signed tag instead. It performs no
worktree/provider/Git-mutation effect itself except one read-only `git
rev-parse --verify` in `resolve_live_target_revision`.

## Axis 1 — docstring truth

### CONFIRMED
None.

### PLAUSIBLE
None.

### Checked and honest
- `:8-13` "This module is its ONE canonical caller" of the D5 trust root —
  matches the sibling worker's confirmed reading of
  `tests/test_promotion_trust_root_single_caller.py` (see
  `promotion_trust_root.py.md` Axis 1); not re-derived here, cross-referenced.
- `:16-17` "It [the HMAC ledger] is re-authenticated on every promotion" —
  confirmed: `evaluate_promotion_trust` (`promotion_trust_root.py:1213-1221`)
  calls `evaluate_second_factor` unconditionally for any recognized stage
  (only a test seam, `_second_factor is not None`, would skip it, and
  `authorize_persisted_promotion` refuses outright if `decision.seams_used`
  is non-empty, `:543-551`).
- `:16-17` "...and every outcome is written down" — the trust root appends a
  record before returning any verdict (confirmed by the sibling dossier,
  `promotion_trust_root.py:1252-1269`); this file's own additional append
  (`:586-597`) only fires on a second-factor *divergence*, which is a
  narrower claim than "every outcome" but the module-docstring sentence is
  about the trust root's own unconditional record, not this file's
  divergence-only one — read carefully, not an overclaim.
- `:16-17` "...but it cannot grant" — confirmed: `authorize_persisted_promotion`
  decides `decision.promote` purely from the root (`:552-556`); the local
  reproduction of `authorize_promotion` against the HMAC view (`:573-597`)
  only ever sets an advisory `second_factor_binding` string and optionally
  appends a divergence record — it cannot change the already-decided verdict.
- `:110-111` "Empty only for `authorize_promotion`, the pure binding
  primitive, which is never a promotion authority on its own" (about
  `owner_approval_ref`) — confirmed for the two call sites in this file:
  `authorize_promotion` never sets `owner_approval_ref` (dataclass default
  `""`), while `authorize_persisted_promotion` always sets it from
  `decision.root.owner_approval_ref or ""`. Traced one level further (out of
  this file, into `promotion_trust_root.py:507-509,564-572`): on the
  `approved=True` path `owner_approval_ref` is `"artifact-locator:sha256:" +
  sha256(tag_bytes).hexdigest()`, which is a 64-hex digest and therefore never
  falsy — the defensive `or ""` in this file is dead-but-harmless, not a
  masked overclaim.
- `:113-114` "`trust`... Present on every persisted authorization" — the word
  "persisted" is load-bearing: `authorize_promotion` (the unpersisted, pure
  primitive) leaves `trust` at its dataclass default `{}`, but
  `authorize_persisted_promotion` (the only path that is actually persisted
  by `promotion_execution.py`, see that dossier) always sets
  `trust=decision.to_dict()` (`:599-622`), which is never empty for a
  `PROMOTE` decision. Claim scoped correctly.
- `:337-341` "`repo_root` is required because the root is a git-signed tag
  verified against an allowed-signers file read from the COMMITTED tree" —
  matches the sibling worker's confirmed reading of
  `_committed_allowed_signers` (`promotion_trust_root.py:307-323`).
- `:408-415` "Bind the promotion subject to what the OWNER SIGNED, not to a
  receipt" — confirmed: `_authorize_from_root`'s `comparisons` dict (`:439-446`)
  anchors every field on `root.*` (from the signed tag), never on
  `consumed_approval`/`verified.*` (the demoted HMAC receipt).
- `:568-572` "THE SECOND FACTOR, RECORDED AND NEVER OBEYED" — confirmed: the
  `try/except Exception` at `:575-597` only ever sets a string and optionally
  calls `_append_record`; neither branch can change `decision.promote`, which
  was already committed to `body` before this block runs.
- `:502-508` "an unknown caller gets the strict path... rejected at the public
  keyword" — confirmed: `authorize_persisted_promotion` checks
  `str(promotion_stage) not in PROMOTION_STAGES` (`:514-520`) before doing
  anything else, and the error message echoes `promotion_stage!r`.

## Axis 2 — effect surface

| site (file:line) | effect | registry row | covered? |
|---|---|---|---|
| `subprocess.run(["git","rev-parse","--verify",ref], ...)` `:312-319` | PROCESS_SPAWN | `python.promote_candidates` (`daedalus/spine/effect_boundary.py:444-479`, `target="daedalus.kairos.gated_writes:promote_candidates"`) | **yes, explicitly name-anchored** — `GuardAnchor("daedalus.kairos.gated_writes:promote_candidates", "resolve_live_target_revision")` at `:464-467` names this exact function |
| `authorize_promotion`/`authorize_persisted_promotion` call sites | (no direct effect themselves; they gate the effect above and the caller's worktree mutation) | same row | the row also anchors `"authorize_promotion"` at `:460-463` |

### Notes
No row targets `daedalus.kernel.promotion....` (consistent with the brief's
measured fact: only 4 kernel rows exist and none is in this file). The one
process-spawn site in this file is nonetheless covered, by function name, in
the non-kernel `python.promote_candidates` row — stronger than "plausibly
covers" in the other dossiers, because the anchors list the exact function
names `authorize_promotion` and `resolve_live_target_revision`. Per Axis 5,
the covering entrypoint (`daedalus.kairos.gated_writes:promote_candidates`)
has zero production callers, so this coverage is real on paper but currently
unexercised.

No filesystem write, no environment read, and no other subprocess call exist
anywhere in this file — confirmed by scoped grep for
`subprocess\.|os\.system|Popen|socket\.|urllib|requests\.|httpx|open\(.*[wax]|write_text|write_bytes|mkdir|os\.replace|os\.rename|os\.remove|os\.unlink|shutil\.|sqlite3\.connect|tempfile\.|os\.environ|os\.getenv` returning only the one `subprocess.` hit at `:312`.

## Axis 3 — unreleased resources

No findings. The only acquisition-shaped call is `subprocess.run(...)`
(`:312-319`), which is the blocking, synchronous stdlib form — it waits for
the child and returns; there is no `Popen` object outliving the call and
nothing to leak. No file handles, sqlite connections, locks, or temp
directories are opened anywhere in this file.

## Axis 4 — validator gaps (W4 class)

### Cross-vendor lead question (target_ref -> git rev-parse)

Answering `kernel-audit`'s specific lead here since it targets this file:

1. **`_canonical_identifier` is not a local regex copy.** `:73-79` calls
   `daedalus.kernel.contracts.base._identifier` directly and translates
   `TypeError`/`ValueError` into `PromotionAuthorizationError`. It does not
   duplicate `_ID_RE`; it is a thin exception-translation wrapper around the
   canonical validator. Not part of the W1 duplicate-regex count.
2. **`ref` reaches git in argv form, not string interpolation.** The only
   subprocess call in this file is `:312-319`:
   `subprocess.run(["git", "rev-parse", "--verify", ref], cwd=root, ...)`
   with no `shell=True`. `ref` is one element of a list; there is no
   string-concatenation or shell path anywhere reachable from `target_ref`
   in this file (confirmed by grep: the only other uses of `target_ref` in
   this file are dict values and kwarg passthroughs, `:105,123,332,355,365,
   388,405,423,471,483,564,580,617` — none build a path or a shell string).
3. **Regex reading confirmed.** `_ID_RE = r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$"`
   (`contracts/canonical.py:27`) requires the first character to be
   alphanumeric, which blocks a leading `-` and therefore blocks classic
   argv-flag injection (e.g. `--upload-pack=...`) against `git rev-parse`.
   It does admit `..` and `:` after the first character, and does not
   forbid `..` as a path/ref segment.
4. **No explicit `git check-ref-format` call anywhere in `daedalus/`**
   (scoped grep, zero hits). `_identifier`/`_canonical_identifier` is the
   only ref-syntax validation this codebase performs before use; any
   rejection of a malformed ref (`..` components, invalid characters beyond
   what `_ID_RE` already blocks) relies entirely on git's own internal
   `check_refname_format`/revision-parser behavior inside `git rev-parse
   --verify`, which this codebase never names or tests directly.

**Rating: low, not CONFIRMED as an exploit.** The admitted-but-unchecked
characters (`..`, `:`) can make `git rev-parse --verify <target_ref>` parse
the string as a revision *range* (`A..B`) or a *tree-ish:path* expression
(`HEAD:secret`) instead of a plain ref name, which is a semantic-confusion
surface, not a path-traversal or shell-injection one: (a) `--verify` requires
resolution to exactly one object or the call fails closed (non-zero
`returncode` -> `PromotionAuthorizationError`, `:320-323`); (b) whatever text
`git` does emit must still pass `_canonical_revision` (`_REVISION_RE`, 40/64
lowercase hex only, `:74-82` in `contracts/canonical.py`) before this file
accepts it as `live_target_revision`; and (c) even a resolvable, canonical-
looking SHA from a `tree-ish:path` expression would have to *also* equal the
owner-signed `root.source_revision` to pass `_authorize_from_root`'s
`"target_head"` comparison (`:445`), which an attacker does not control. So
the weak validator is compensated in practice by (i) git's own refusal on
unresolvable/ambiguous input and (ii) the downstream revision-format and
owner-signature checks — an honest "weak validator, but the actual harm is
absorbed by the following checks," not a bypass. `target_ref` is also, today,
only reachable via `daedalus.kairos.gated_writes.promote_candidates`, which
has zero production callers (Axis 5), so this is a theoretical surface for
whenever that entrypoint is wired.

### `_canonical_changed_paths` (`:132-159`) — independent strict validator, not the weak class

`artifact.changed_paths` entries are **not** validated by `_identifier`/`_ID_RE`
at all. `_canonical_changed_paths` implements its own strict check: rejects
non-string/empty/`\x00`/backslash-containing values outright, then requires
`PurePosixPath(raw)` to be non-absolute, contain no `""`/`"."`/`".."` part,
and round-trip exactly (`path.as_posix() == raw`). This is structurally close
to `contracts/canonical.py:124-136`'s `_repo_path` (the brief's example of
the *correct* validator) but is a **separate, independently-written
implementation**, not a call to `_repo_path` and not an import of it.

One gap relative to `_repo_path`: `_repo_path` additionally rejects a
drive-qualified first part (`":" in path.parts[0]`, `canonical.py:131-132`);
`_canonical_changed_paths` does not, so a string like `"C:/evil"` would pass
its checks (not absolute under `PurePosixPath`, and no part equals
`""`/`"."`/`".."`). **Not escalated to CONFIRMED**: I traced every production
consumer of `PatchArtifact.changed_paths` (scoped grep across `daedalus/`)
and found it used only as (a) authorization-digest material
(`candidate_batch_sha256`, this file `:282-298`), (b) membership-check input
in `daedalus/spine/receipts.py:591-634`, and (c) display/logging
(`daedalus/spine/picker.py:2760-2761`, `daedalus/cli.py:703`). None of those
sites join it onto a filesystem root with `Path(root) / value` in a way this
audit could find; actual patch application goes through `git apply`, not raw
Python path construction. This is a real, minor duplicate-but-weaker
validator (Axis 5 material) rather than a demonstrated Axis 4 traversal
chain — flagging the gap for whoever owns `spine/receipts.py` or the git-apply
call site, since I did not audit those files.

### `_SHA256_RE` — genuine duplicate, not a gap

`:43` locally defines `_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")`, byte-
identical to `contracts/canonical.py:25`. `_canonical_sha256` (`:56-61`) is a
local reimplementation of `contracts/canonical.py:65-71`'s `_sha256`, which
this file's sibling `promotion_execution.py` imports directly (`from
daedalus.kernel.contracts.base import (..., _sha256, ...)`). This file
imports `_identifier` and `_revision` from the same module but not `_sha256`,
choosing to reimplement instead. Equally strict (identical pattern) — a
duplication/DRY finding, not a security weakening. See Axis 5.

## Axis 5 — dead / duplicate

### CONFIRMED
- **`_SHA256_RE`/`_canonical_sha256` (`:43,56-61`) duplicate
  `contracts/canonical.py:25,65-71`'s `_SHA256_RE`/`_sha256`.** Same regex,
  same semantics, available for import (this file already imports
  `_identifier`/`_revision` from the same `contracts.base` module, and the
  sibling `promotion_execution.py` does import `_sha256` from it). Neither
  copy is stricter; this is pure duplication.
- **`authorize_promotion`, `authorize_persisted_promotion`,
  `resolve_live_target_revision`, `snapshot_promotion_candidates` all have
  real production callers, but through a currently-unreachable chain.**
  `grep -rn "authorize_promotion(\|authorize_persisted_promotion(\|resolve_live_target_revision(\|snapshot_promotion_candidates(" --include=*.py daedalus/` shows each is called from `daedalus/kairos/gated_writes.py`
  (`:216,236,287-288` — `_snapshot_promotion_candidates` is a local rebinding
  of `snapshot_promotion_candidates`, and `authorize_promotion` is locally
  rebound to `authorize_persisted_promotion` at `:284` inside the lock). That
  is a genuine production call, not a test-only one — but the calling
  function, `daedalus.kairos.gated_writes.promote_candidates`, itself has
  **zero** production callers repo-wide (confirmed jointly with the sibling
  `promotion_trust_root.py.md` dossier: `grep -rn "promote_candidates("
  --include=*.py daedalus/` matches only its own `def` line and a comment in
  `daedalus/kairos/scheduler.py:317,329` documenting that it is *not* called
  automatically). So: 0 production callers of the entrypoint, but the
  entrypoint's own body *does* call every one of these functions — "0
  callers at all" is false for these four; "0 *reachable* production
  callers" is true. This is a seam (fully wired one hop down, unwired at the
  top), consistent with the brief's "0 callers is a finding, not a verdict."
- **`candidate_batch_sha256` (`:301-305`) has ZERO production callers, not
  even the one-hop-down kind.** `grep -rn "candidate_batch_sha256("
  --include=*.py daedalus/ tests/ scripts/ tools/ docs/` returns only its own
  `def` line (`:301`), its own internal use of the private
  `_candidate_batch_sha256_from_snapshots` helper (different name, not a
  self-call), and eight hits confined to
  `tests/kernel/test_persisted_promotion_authorization.py`,
  `tests/kernel/test_promotion_material_review.py`, and
  `tests/kernel/test_sealed_promotion.py`. `daedalus/kairos/gated_writes.py`
  does not call the public `candidate_batch_sha256`; it uses the private
  `_snapshot_promotion_candidates` + `authorize_persisted_promotion` path
  instead, which computes the same digest internally via
  `_candidate_batch_sha256_from_snapshots` without going through the public
  wrapper. Docstring (`:302`) says only "Digest the exact ordered, validated
  patch batch intended for promotion" — no promised external reader named.
  Exported in `__all__` (`:635`) as a public API surface with no production
  consumer.

### PLAUSIBLE
None beyond the above.

## OWNED-FLAG

Not applicable — this file is not `offload_lease.py`, the flagged
`attempt_execution.py` string-evidence sites, or `effects.py`.

## What I did not cover

Did not execute or import any code (static read-only). Did not deep-audit
`daedalus/kairos/gated_writes.py` beyond the `promote_candidates` body needed
to trace callers of this file's public functions. Did not trace
`daedalus/spine/receipts.py`'s `changed_paths` membership-check logic beyond
confirming it is a consumer, not a path-construction site — that file is out
of my assigned slice. Did not verify empirically (cannot, static-only) how
`git rev-parse --verify` actually resolves a `target_ref` containing `..` or
`:` on this box's installed git version; the Axis-4 rating above is a
structural/documentation-based argument, not an executed proof.
