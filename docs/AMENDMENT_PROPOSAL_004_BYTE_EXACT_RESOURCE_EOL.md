# Amendment proposal 004 — byte-exact resources must not be EOL-normalized

Status: **proposed, not applied**. Awaiting explicit repository-owner approval
per master plan section 15.

Author: Athena (coordinator)
Date: 2026-08-17
Severity: **blocks Gate 0 exit on Windows**
Affected invariant: 5 (sealed promotion), 8 (bounded effects — the guarded
promotion path cannot load)

## Summary

At `origin/integration/g0-consolidated-20260807`, the sealed promotion seam
cannot be imported on Windows. `daedalus/kairos/gated_writes.py` verifies a
retained source resource against a pinned Git blob identity; Git's
`core.autocrlf=true` checkout rewrites that resource's line endings, so the
verification fails and raises at import time.

This is **not** a corrupt tree and **not** a bad merge. The committed content is
correct. Only the working-tree materialization is wrong.

## Evidence `[MEASURED]` 2026-08-17

Worktree: `C:/Users/nukei/.claude/jobs/3cdf2088/tmp/integ` at `60b2bfe`, clean
(`git status --porcelain` empty).

```
python -m pytest tests/ --collect-only -q
  -> 6451 tests collected, 7 errors in 34.74s
  -> RuntimeError: retained gated-write source integrity mismatch:
     expected Git blob e31d24ec67f7c208ace34f5dd2e9fefe4e654a86,
     got      d91ecc8fcadde2851dea2e1bbe1c8ae1addca91f
```

Failing collections. **Six** share this root cause; the seventh
(`test_gate0_release_cli.py`) is an independent defect documented at the end of
this file and is *not* part of this amendment:

```
tests/gates/test_gate0_release_cli.py          <- independent, see below
tests/kernel/test_live_promotion_legacy_retirement.py
tests/kernel/test_live_promotion_seam.py
tests/kernel/test_live_promotion_seam_review.py
tests/kernel/test_persisted_promotion_authorization.py
tests/kernel/test_promotion_material_review.py
tests/kernel/test_sealed_promotion.py
```

Root cause proof for `daedalus/kairos/_gated_writes_legacy.py.src`:

| measurement | value |
| --- | --- |
| blob stored in Git (`git rev-parse HEAD:<file>`) | `e31d24ec…` |
| working-tree bytes hashed as-is | `d91ecc8f…` |
| working-tree bytes with `CRLF -> LF`, hashed | `e31d24ec…` |
| CRLF sequences in working tree | 1245 |
| bare LF in working tree | 0 |

`git hash-object <file>` also returns `e31d24ec…` because Git applies the
reverse clean filter before hashing. Python's `Path.read_bytes()` does not.
That divergence is the entire bug.

Configuration: `core.autocrlf=true`. `.gitattributes` contains exactly one
rule — `.githooks/* text eol=lf` — which does not cover `*.src`.

### Scope: 9 pinned files across 3 pinning sites

An initial search of `daedalus/` for `_git_blob_sha1` found only one pinned
resource. **That was wrong** — two further pinning sites live in `tests/` and
were missed. An independent Codex audit found them; all eight additional pins
were then re-verified here directly. Every one exhibits the same defect.

Site 1 — `daedalus/kairos/gated_writes.py` (import-time, `exec()`s the resource):

| file | CRLF | raw blob | LF blob = pin |
| --- | ---: | --- | --- |
| `daedalus/kairos/_gated_writes_legacy.py.src` | 1245 | `d91ecc8f…` | `e31d24ec…` |

Site 2 — `tests/gates/test_provider_target_receipt_retention_inventory.py:18`:

| file | CRLF | raw blob | LF blob = pin |
| --- | ---: | --- | --- |
| `daedalus/runtimes/provider_target_receipt_ledger.py` | 678 | `bb5bf7aa…` | `a5e3d132…` |

Site 3 — `tests/gates/test_repository_head_revision_integration_review.py:14-22`:

| file | CRLF | raw blob | LF blob = pin |
| --- | ---: | --- | --- |
| `configs/schemas/repository-head-revision-receipt.schema.json` | 185 | `9a37496e…` | `ef7eb06c…` |
| `daedalus/gates/repository_head_revision.py` | 570 | `d5d0a507…` | `bbdb2808…` |
| `scripts/run_repository_head_revision_mutations.py` | 108 | `984a8968…` | `8637be13…` |
| `tests/gates/test_repository_head_revision.py` | 297 | `8437f2eb…` | `91522b3c…` |
| `tests/gates/test_repository_head_revision_review.py` | 121 | `081ae10d…` | `a6a274a9…` |
| `tests/gates/test_repository_head_revision_schema.py` | 78 | `3d966d9f…` | `9171bd5b…` |
| `tests/gates/test_repository_head_revision_wire.py` | 72 | `acd77993…` | `88767051…` |

For all nine, `CRLF -> LF` alone reproduces the pinned value, and the LF hash
equals `git rev-parse HEAD:<file>`. Sites 2 and 3 fail as ordinary test
failures rather than collection errors, so they are invisible in the
collection-error count.

No other static checkout-byte pins exist. Other hashing sites either compute
dynamic content-addressed identities with no hardcoded expectation, or record
provenance constants without loading the pinned file from disk.

Comparison: the checkpoint line (`8647091`) collects 4455 tests with **0
errors** and does not contain the retained-source strangler at all. The defect
was introduced with the strangler in the consolidated line.

### Platform: configuration-dependent, not OS-dependent

| environment | result |
| --- | --- |
| Linux, normal LF checkout | passes |
| Windows, `core.autocrlf=true` | **fails** |
| Windows, `autocrlf=false`/`input`, or with the proposed attributes | passes |
| Linux configured to check out CRLF | would fail |
| wheel built on a CRLF Windows checkout, imported on Linux | **fails** |

That last row matters: the defect is packageable. A release artifact built on
an unconfigured Windows machine carries CRLF into the wheel and then fails
everywhere, so this is not merely a local developer annoyance.

CI exposure — the relevant workflows matrix Ubuntu *and* Windows without
setting any EOL policy, so the Windows leg is vulnerable wherever checkout
produces CRLF:

- `.github/workflows/g0-live-promotion-seam.yml:35` (exact wheel verification, lines 76-100)
- `.github/workflows/g0-repository-head-receipt-integration.yml:27`
- `.github/workflows/g0-provider-target-receipt-retention-inventory-refresh.yml:25`

This is why the defect survived integration: the Ubuntu leg is green.

## Proposed change

Add to `.gitattributes` (a protected artifact) — one rule per pinned path:

```
daedalus/kairos/_gated_writes_legacy.py.src              text eol=lf
daedalus/runtimes/provider_target_receipt_ledger.py      text eol=lf
configs/schemas/repository-head-revision-receipt.schema.json text eol=lf
daedalus/gates/repository_head_revision.py               text eol=lf
scripts/run_repository_head_revision_mutations.py        text eol=lf
tests/gates/test_repository_head_revision.py             text eol=lf
tests/gates/test_repository_head_revision_review.py      text eol=lf
tests/gates/test_repository_head_revision_schema.py      text eol=lf
tests/gates/test_repository_head_revision_wire.py        text eol=lf
```

`text eol=lf` is preferred over `-text`. Both yield an LF worktree, but
`eol=lf` matches the already-reviewed LF blobs and keeps the clean filter
active, so a CRLF file can never be staged as a *new* blob. A bare `-text`
would treat the bytes as opaque and silently accept a CRLF version into the
index. Path-specific rules are used rather than a repository-wide `* text=auto`
to avoid mass renormalization churn across 4665 files.

Migration for existing checkouts — the attribute alone does not rewrite files
already materialized with CRLF:

```
git rm --cached -r .
git reset --hard
```

or, per file, `git rm --cached <path> && git checkout -- <path>`.

## Alternatives considered

**Normalize newlines in `_verify_retained_source` before hashing — rejected,
and it is worse than it first appears.** Two independent reasons:

1. Hashing a normalized form means many distinct byte streams satisfy one
   pin, degrading the property from "these exact bytes" to "these bytes up to
   line endings".
2. Decisively: `gated_writes.py:43` compiles `_retained_source_bytes`, which
   is the *original* buffer. Normalizing only the hashed copy would mean the
   module **verifies one byte stream and executes a different one** — breaking
   the core guarantee that the bytes checked are the bytes run. For a sealed
   promotion path (invariant 5) that is a security regression, not a fix.

Master plan section 15 also forbids routing around a guard.

**Set `core.autocrlf=false` locally — rejected as the primary fix.** It is
per-machine, unversioned, and leaves every fresh clone broken. `.git/config` is
also itself a locally protected path.

**Do nothing — rejected.** Gate 0 exit requires a fault-injection matrix
demonstrating fail-closed protected effects. A promotion path that raises at
import cannot be exercised at all, so the matrix cannot be run on the owner's
platform.

## Rollback

Remove the single `.gitattributes` line and re-run the migration commands. No
data migration, no schema change, no history rewrite.

## Verification — already performed `[MEASURED]`

The fix was proven *before* requesting approval, without modifying any tracked
file. A disposable worktree was checked out with LF endings, which is exactly
the state the proposed `.gitattributes` rule produces:

```
git -c core.autocrlf=false -c core.eol=lf worktree add --detach <tmp> \
    origin/integration/g0-consolidated-20260807
```

Results in that worktree:

| check | result |
| --- | --- |
| CRLF / bare LF in the resource | 0 / 1245 (inverted, as intended) |
| computed blob | `e31d24ec…` — matches the pin |
| `import daedalus.kairos.gated_writes` | **succeeds** |
| `pytest --collect-only` | 6496 collected, **1** error (was 7) |
| after also fixing the unrelated import defect below | 6501 collected, **0** errors |

Collection-error progression: **7 → 1 → 0**.

Remaining steps after approval:

1. `git check-attr text -- daedalus/kairos/_gated_writes_legacy.py.src`
   reports `text: unset`.
2. Re-run the migration commands in existing checkouts.
3. Run the 6 previously-uncollectable promotion modules and record real
   pass/fail (collection succeeding is not the same as passing).
4. `python tools/iron_plan_guard.py (removed 2026-08-23) verify`.

---

## Independent defect 1 — wrong import path (ALIGNED, no amendment needed)

`tests/gates/test_gate0_release_cli.py:12` reads

```python
from daedalus.gates.evidence import load_gate_evidence_index
```

but that symbol is defined in `daedalus/gates/evidence_io.py:111` and re-exported
from `daedalus/gates/__init__.py:17`. Sibling tests
(`test_exact_head_evidence_io.py`, `test_exact_head_evidence_canonical_wire.py`)
already use the correct `from daedalus.gates import load_gate_evidence_index`.

This is a genuine integration break at the consolidated tip: a test left behind
when the loader moved modules. It is a real answer to "did the `merge(probe)`
commits produce a coherent tree" — overwhelmingly yes, with this one exception.

Fix is the one-line import correction, verified to bring collection to 0 errors.
`tests/` is governed but not protected, so this needs no amendment. It is *not*
yet landed on any branch, because the canonical trunk is still undecided.

## Independent defect 2 (separate, lower severity)

`tools/iron_plan_guard.py (removed 2026-08-22)` — `git_command_is_mutating` (~line 1176) — classifies
read-only `git merge-base` and `git branch --merged` as mutating, because the
invocation parser reduces the token `merge-base` to `merge`. This blocks
ordinary read-only repository inspection with a protected-artifact denial.

Not folded into this amendment: it is independent, non-blocking, and has a
workaround (`git rev-list --count A..B`). Listed here so it is not lost.

## Further blockers reported, not yet investigated

When the Iron Plan guard ran inside the consolidated worktree it reported two
additional blockers, neither examined in this pass:

1. **automatic-promotion exposure in `gated_writes.py`** — if accurate this
   touches invariant 5 (sealed promotion, no auto-merge) directly and would be
   more severe than the EOL defect. Needs its own investigation.
2. **local `core.hooksPath` unset** — the commit-time guards are therefore not
   installed in that worktree.

Recorded here so they are not lost between sessions.

---

Iron Plan: AMENDMENT (proposed — not applied)
Iron Gate: 0
Evidence: pytest collection at `60b2bfe` under three checkout conditions
(CRLF 6451/7 errors; LF 6496/1; LF + import fix 6501/0) and at `8647091`
(4455/0); three-way blob comparison (stored / Python-read / CRLF→LF) proving
EOL causation for all 9 pinned files, each re-verified against
`git rev-parse HEAD:<file>`; `import daedalus.kairos.gated_writes` succeeding
in an LF worktree. Blast radius independently established by a Codex audit
after a first-pass search of `daedalus/` alone **wrongly** reported a single
pinned resource; the corrected figure is 9 files across 3 pinning sites.
No protected artifact was modified.
