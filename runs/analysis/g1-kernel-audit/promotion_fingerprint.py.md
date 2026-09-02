# daedalus/kernel/promotion_fingerprint.py  (155 lines)

Base 54f09753. Static read-only.

## What the file is for

Computes a stable content digest (`fingerprint_primary_checkout`) of a
checkout's source-visible file tree, meant to detect whether the primary
working checkout changed underneath a promotion attempt (its
`before`/`after` digests are the fields
`PromotionExecutionStart.primary_checkout_before_sha256`/
`PromotionExecutionReceipt.primary_checkout_after_sha256` are named for in
the sibling `promotion_execution.py`). It excludes `.git`/`.daedalus`,
double-observes the tree to catch concurrent mutation, and hashes path,
size, content sha256, and the executable bit per file.

## What exactly a "fingerprint" binds

Per `_observe` (`:76-114`) and `fingerprint_primary_checkout` (`:117-149`),
the digest binds, for every regular file under the root except `.git`/
`.daedalus` at the top level: its **repo-relative POSIX path**, its **byte
size**, its **SHA-256 of its raw bytes**, and its **owner-execute bit**
(`S_IXUSR`), all folded through `canonical_sha` with
`schema=daedalus-primary-checkout-fingerprint/1`. It does **not** bind:
directory identity/permissions, timestamps (`mtime` is used only as a
same-file check during the read, never hashed into the digest — see
`_same_file`, `:26-33`, and the row dict at `:106-113`, which has no time
field), other permission bits (group/other, setuid/setgid/sticky — only
`S_IXUSR`), ownership (uid/gid), or extended attributes. The module docstring
(`:1-8`) claims exactly this scope ("binds executable bits and raw bytes")
and does not overclaim binding permissions, ownership, or timestamps beyond
what the code does — checked, no gap on that specific question.

## Axis 1 — docstring truth

### CONFIRMED
None.

### PLAUSIBLE
- **"It follows no symlink" (`:1-4`) is true only on Python >= 3.13, but
  this repository declares `requires-python = ">=3.10"`
  (`pyproject.toml:10`).** `_observe` (`:79-82`) calls `root.rglob("*")` with
  no arguments beyond the pattern. `pathlib.Path.rglob` gained a
  keyword-only `recurse_symlinks` parameter in Python 3.13 (confirmed on
  this box's venv: `.venv/Scripts/python.exe --version` -> `Python 3.13.5`;
  `inspect.signature(pathlib.Path.rglob)` -> `(self, pattern, *,
  case_sensitive=None, recurse_symlinks=False)`), and that parameter
  defaults to `False` — meaning on 3.13+ `rglob("*")` does **not** descend
  into a directory reached via a symlink, which is what makes "follows no
  symlink" true on the currently installed interpreter. Prior to 3.13,
  `Path.rglob` had no such parameter and (per the documented CPython
  behavior change introducing it) recursive globbing **did** traverse
  symlinked directories by default. Since this file calls `rglob("*")`
  without ever passing `recurse_symlinks=False` explicitly, its correctness
  is entirely dependent on running under Python 3.13+, which the project's
  own `pyproject.toml` does not require. On Python 3.10-3.12 (a supported
  version per that file), a symlinked *directory* placed inside the checkout
  root would have its contents silently walked and hashed into the
  fingerprint as if it were part of the tree, contradicting the "follows no
  symlink" claim.
  - Individual symlinked **files** matched directly by the `"*"` pattern are
    still caught regardless of Python version: `path.lstat()` on a symlink
    returns `S_IFLNK` mode, which fails `stat.S_ISREG` and raises
    `PrimaryCheckoutFingerprintError` (`:98-104`). Only symlinked
    **directories**, encountered during recursive descent, are affected by
    the version-dependent default.
  - Not escalated to CONFIRMED because I could not execute Python 3.10-3.12
    in this sandbox (only the 3.13.5 venv is available, and the hard rules
    forbid running code anyway) to observe the pre-3.13 behavior directly —
    this is a documented cross-version stdlib behavior change, not something
    directly visible by reading only this file's bytes. High confidence, not
    executed proof.
  - Impact if true: since this function has zero production callers today
    (see Axis 5), there is no live exploit path yet. If ever wired as
    intended (binding `PromotionExecutionStart`/`Receipt`'s
    `primary_checkout_*_sha256` fields), a checkout containing an
    attacker-plantable symlinked directory under Python <3.13 could pull
    arbitrary out-of-tree file content into the "primary checkout" digest,
    or be used to make two genuinely different trees fingerprint
    identically by pointing the same symlink target from both — undermining
    exactly the "requires two identical observations... stable file tree"
    guarantee the digest exists to provide.

### Checked and honest
- `:1-4` "excludes only repository-control roots that are not candidate
  source material (`.git` and `.daedalus`)" — confirmed:
  `_EXCLUDED_ROOTS = frozenset({".git", ".daedalus"})` (`:19`), checked
  against `relative.parts[0].casefold()` (`:90-91`), i.e. only the
  top-level path component, matching "roots."
  - Case-insensitive to Windows-style casing (`casefold()`), consistent with
    running on this Windows box, but this also means a directory literally
    named `.GIT` (not the real repo metadata dir but a candidate-authored
    directory with that name) would be silently excluded from the
    fingerprint too — narrower than the literal ".git and .daedalus"
    wording implies, but in the conservative direction (excludes slightly
    more than a case-sensitive match would, never includes less than
    intended) — not a security weakening, so not filed as a defect.
- `:4-5` "accepts only regular files" — confirmed: `if not
  stat.S_ISREG(metadata.st_mode): raise PrimaryCheckoutFingerprintError(...)`
  (`:100-104`), no silent skip.
- `:5` "binds executable bits and raw bytes" — confirmed, see the dedicated
  section above.
- `:6-7` "requires two identical observations before returning" — confirmed:
  `first = _observe(directory); second = _observe(directory); if first !=
  second: raise` (`:138-143`).
- `:7-8` "The helper performs no repository mutation and owns no promotion
  policy." — confirmed: scoped grep for
  `open\(.*[wax]|write_text|write_bytes|mkdir|touch|os\.replace|os\.rename|
  os\.remove|os\.unlink|shutil\.` in this file returns zero hits; the only
  `os.open` call (`:43`) uses `os.O_RDONLY` (plus `O_BINARY`/`O_NOFOLLOW`
  where available, `:38-41`).
- `:117-118` "Return a stable digest of one checkout's source-visible file
  tree" — the root itself is explicitly checked not to be a symlink
  (`stat.S_ISLNK(submitted_metadata.st_mode)`, `:121-125`) before
  `resolve(strict=True)`, so the top-level root cannot itself be a redirect
  — consistent with the stated intent even though internal directory
  symlinks are the gap noted above.

## Axis 2 — effect surface

| site (file:line) | effect | registry row | covered? |
|---|---|---|---|
| `os.open(path, os.O_RDONLY \| ...)` `:43` (per matched file, inside `_read_regular_file`) | FILESYSTEM read | none targets `daedalus.kernel.promotion_fingerprint....` | **no** |
| `path.lstat()` / `root.rglob("*")` (`:79-97`) | FILESYSTEM read/stat/traversal | none | **no** |

### Notes
No filesystem **write** exists anywhere in this file (confirmed above) —
every effect is a read/stat, the lowest-risk category in the axis-2 list.
No row in `effect_boundary.py` targets this file (scoped grep for
`promotion_fingerprint` in that file: zero hits, consistent with the
brief's measured fact of only 4 kernel rows, none here). Per Axis 5,
`fingerprint_primary_checkout` has zero production callers, so there is
currently no live path through which this read surface (or the symlink gap
above) is reachable outside tests.

## Axis 3 — unreleased resources

No findings — this file is the other exemplary case in my slice.
- `_read_regular_file` (`:36-73`): `os.open` (`:43`) is called *outside* any
  try/finally; if it raises `OSError`, there is nothing to release yet, and
  the exception is caught and converted (`:44-47`). Once the descriptor is
  obtained, everything — the identity re-check (`before`/`after` `fstat`),
  the read loop, and the post-read `lstat` — is inside a `try:` whose
  `finally: os.close(descriptor)` (`:48-73`) runs on every exit path,
  including a raised `PrimaryCheckoutFingerprintError` from inside the body.
  This is the exact "acquire outside, guard everything after with
  try/finally" shape the brief's canonical fixed pattern describes, applied
  to a raw OS file descriptor rather than sqlite.
- No other resource acquisition (no sqlite, no tempfile, no subprocess, no
  locks, no sockets) exists in this file.

## Axis 4 — validator gaps (W4 class)

No findings — and a genuinely different (stronger) shape than `_identifier`.
- The only "identifier"-shaped value handled here is the caller-supplied
  `root` parameter to `fingerprint_primary_checkout` (`:117-149`), which is
  an operator-supplied filesystem root, not a value validated by
  `_identifier`/the weak `_ID_RE` regex at all — out of the W4 threat shape
  this axis targets (same carve-out as `repo_root` in the sibling
  `promotion_trust_root.py.md`/`promotion_execution_reader.py.md` dossiers).
  It is, however, defended more strongly than a bare path: the root must
  resolve to an existing directory (`resolve(strict=True)`, `:126`) and must
  not itself be a symlink (`:121-125`) before any traversal begins.
- `path` values produced *inside* `_observe` come from `root.rglob("*")`
  (real filesystem entries under an already-resolved root), not from
  attacker-supplied strings run through a regex validator — there is no
  `_identifier`/weak-regex-validated value anywhere in this file that then
  reaches path construction, so the specific W4 sibling-chain shape (weak
  regex -> `Path(...) / value`) does not apply here. The relevant risk in
  this file is the symlink-traversal gap documented under Axis 1, which is a
  different defect class (TOCTOU/symlink-following, not identifier
  under-validation).

## Axis 5 — dead / duplicate

### CONFIRMED
- **`fingerprint_primary_checkout` has ZERO production callers anywhere in
  the repository.** `grep -rn "fingerprint_primary_checkout("
  --include=*.py daedalus/ tests/ scripts/ tools/ docs/` matches only this
  file's own `def` (`:117`) and ten call sites, all confined to
  `tests/kernel/test_promotion_fingerprint.py`. No file under `daedalus/`
  (production code) calls it.
- **It has a promised reader, and that reader does not call it.** The
  module docstring frames the helper as existing specifically "for promotion
  execution accounting" (`:1`, "Read-only primary-checkout identity for
  promotion execution accounting"), and the sibling `promotion_execution.py`
  defines `primary_checkout_before_sha256`/`primary_checkout_after_sha256`
  fields on exactly the contracts this helper would feed
  (`PromotionExecutionStart`/`PromotionExecutionReceipt`). I confirmed by
  scoped grep that `promotion_execution.py` **does not import
  `daedalus.kernel.promotion_fingerprint` or call
  `fingerprint_primary_checkout` anywhere** — those fields are plain `str`
  parameters on `begin()`/`complete()` (`promotion_execution.py:876-878,
  966-967`), so some caller is expected to compute the fingerprint and pass
  it in, but no production code does either half of that (compute it, or
  call the ledger methods that would consume it — see the
  `promotion_execution.py.md` dossier's Axis 5, which independently found
  `PromotionExecutionLedger` itself has zero production callers). This is a
  seam with a named consumer role (the promotion-execution accounting
  layer) that itself is also unwired — a two-level unwired chain, not
  ordinary dead code.
- No duplicate regex/validator/digest helper: `_same_file`,
  `_read_regular_file`, and `_observe` are specific to this file's
  file-tree-fingerprinting concern; I found no equivalent implementation in
  `promotion.py`, `promotion_execution.py`, or
  `promotion_execution_reader.py` (checked, not found). `canonical_sha` is
  the shared canonical digest primitive from `daedalus.spine.envelope`
  (imported, not reimplemented) — consistent use, not a duplicate.

### PLAUSIBLE
None beyond the above.

## OWNED-FLAG

Not applicable — this file is not `offload_lease.py`, the flagged
`attempt_execution.py` string-evidence sites, or `effects.py`.

## What I did not cover

Did not execute or import any code (static read-only, and the hard rules
forbid running promotion code specifically). Did not empirically verify the
pre-3.13 `pathlib.Path.rglob` symlink-following behavior by running Python
3.10-3.12 — that finding rests on the documented CPython 3.13 changelog
description of the `recurse_symlinks` parameter's introduction, not on
execution in this sandbox; rated PLAUSIBLE rather than CONFIRMED for exactly
that reason. Did not audit `daedalus/spine/envelope.py`'s `canonical_sha`
beyond confirming it is imported and used as a black-box digest primitive —
out of my assigned slice.
