---
name: crlf-text-pin-trap
description: Editing a `-text`-pinned daedalus/*.py file with a CRLF-writing tool silently commits a whole-file line-ending flip that no repo test catches
metadata:
  type: project
---

`.gitattributes` pins ~254 Gate-1 evaluator-bundle closure members (including
`daedalus/health.py` and `daedalus/status.py`) with `-text`. On this host
`core.autocrlf=true`, so the working tree is CRLF for everything — but `-text`
means git does **not** normalise on `git add`. Editing one of those files with a
tool that rewrites the file with CRLF therefore commits CRLF **into the index**,
where every other pinned module is `i/lf`.

**Why:** it happened on `fix/health-latency-20260910` (commit `41775299`): a
93-line change to `health.py` + `status.py` was committed as a 4053-line diff,
`git blame` for 2267 lines moved to that commit, and `bundle.py`'s
`running_bytes_sha256` for two closure members changed for no functional reason.
`tests/test_byte_pin_eol_durability.py` and `tests/test_ignition_bundle.py` both
stayed green — the guards check that a closure member is *listed*, never that its
committed bytes are LF. The `.gitattributes` prose itself predicts this family
recurs ("every new byte-pin subject arrives unlisted"); this is the other half of
it, where a *listed* subject gets flipped.

**How to apply:** on any diff touching `daedalus/**.py`, run
`git ls-files --eol <changed files>` before approving. Anything reporting
`i/crlf` where its neighbours report `i/lf` is a defect to renormalise, not a
style nit. A suspiciously huge `--stat` for a small change is the tell; confirm
with `git show <sha> --ignore-cr-at-eol --numstat` to see the real size.

Related: [[pin-failure-attribution]].
