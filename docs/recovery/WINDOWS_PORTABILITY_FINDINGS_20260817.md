# Windows portability defects at the consolidated tip — 2026-08-17

Target: `origin/integration/g0-consolidated-20260807` (`60b2bfe`).
All measurements taken in an LF worktree so line endings are *not* a confound
except where stated.

The consolidated tip is Linux-green and Windows-red. The CI matrix runs Ubuntu
and Windows, but the defects below survived ~200 integration merges, so the
Windows leg is either not blocking or not running these paths.

## Full-suite baseline

```
268 failed, 6183 passed, 51 skipped, 1 xfailed, 1982 subtests passed  (29:54)
```

Caveat on this figure: the run was piped through `tail`, so only the last 44
`FAILED` lines were retained. **224 failures remain uncharacterised.** Repeated
attempts to re-run with `--junitxml` were killed at ~3 minutes by an unrelated
process, so the complete list is still outstanding.

## Defect 1 — byte-exact resources destroyed by EOL normalization

9 pinned files across 3 pinning sites. Full detail and the proposed fix are in
`docs/AMENDMENT_PROPOSAL_004_BYTE_EXACT_RESOURCE_EOL.md`. Requires an
amendment (`.gitattributes` is protected).

Effect: 6 test modules cannot even be collected on a stock Windows checkout,
including the sealed-promotion path.

## Defect 2 — `fsync` on a read-only descriptor `[FIXED, patch attached]`

`daedalus/runtimes/provider_observation_store.py:435` — `_fsync_file` opens the
target `O_RDONLY` and calls `os.fsync()`.

POSIX permits flushing a read-only descriptor. Windows flushes via
`FlushFileBuffers`, which requires write access, and returns `EBADF`.

Isolated proof on this machine (`os.name == 'nt'`):

| open flags | `os.fsync()` |
| --- | --- |
| `O_RDONLY \| O_BINARY` | `OSError errno=9 Bad file descriptor` |
| `O_RDWR \| O_BINARY` | OK |

The surfaced symptom was misleading — every failure presented as
`ProviderObservationStoreError: provider-observation store initialization
failed`, because line 558 catches `OSError` and re-raises a generic store
error. The real cause was two frames down.

Note the sibling `_fsync_directory` already branches on `os.name == "nt"`; only
`_fsync_file` was missed.

Fix (`docs/recovery/fix_fsync_readonly_windows.patch`), matching the sibling's
existing style:

```python
flags = os.O_WRONLY if os.name == "nt" else os.O_RDONLY
```

### Independent review of this fix

An adversarial Codex review (read-only) was asked to find reasons *not* to land
it. Findings, adopted:

- `O_RDWR` was the first version; Codex argued for **`O_WRONLY`** as least
  privilege, since `fsync` needs write access but never reads. Adopted and
  re-measured: identical result (49 failed / 687 passed), so the narrower flag
  is free.
- The change acquires no file lock and does not weaken durability; the
  descriptor never escapes the helper.
- Skipping the flush on Windows — the approach the sibling directory helper
  takes — would be **worse**: the database is flushed before publication and
  again after linking, and the directory helper only skips because directory
  syncing is a genuinely unsupported path on Windows. That does not justify
  dropping a valid file flush.
- Residual, pre-existing and not caused by this patch: a deny-write-sharing
  race after publication, where the second open can fail and cleanup suppresses
  an unlink failure, potentially leaving the target behind after initialisation
  reports failure. Deserves a Windows contention test. Codex explicitly did not
  consider it grounds to block the corrective patch.
- Caveat on that review: Codex could not run pytest in its sandbox, so its
  verdict is source and API analysis only. The pass/fail numbers here are mine.

Measured effect on `tests/runtimes/`:

| | failed | passed |
| --- | ---: | ---: |
| before | 57 | 679 |
| after | **49** | **687** |

**8 failures resolved.** An earlier reading of the repeated error signature
suggested this was the dominant cause of the 268; the measured delta refutes
that. It is a real, proven bug with a narrow blast radius.

`daedalus/runtimes/` is governed but not protected, so this is an ALIGNED fix
needing no amendment. It is **not landed** — the canonical trunk is undecided,
so the patch is held rather than committed to an arbitrary branch.

## Defect 3 — editable install shadows the worktree for subprocesses

`daedalus` is installed **editable, pointing at `C:\Users\nukei\Desktop\agent_env`**
(the primary checkout). Any test that spawns a subprocess therefore imports
`daedalus` from the primary checkout, not from the worktree under test. The
primary checkout has no `daedalus.gates`, so those subprocesses die with
`ModuleNotFoundError: No module named 'daedalus.gates'`.

Confirmed by toggling `PYTHONPATH` on one file: 3 failed → 3 passed.

**Measured blast radius: 6 failures**, all subprocess-CLI tests.

An intermediate reading generalised the single-file result to the whole
122-failure `tests/gates/` cluster. The like-for-like run refutes that:

| same 6 subdirectories, fsync fix applied | failed | passed |
| --- | ---: | ---: |
| without `PYTHONPATH` | 246 | 1701 |
| with `PYTHONPATH` | **240** | 1707 |

Consequence for methodology, not for the tip: no worktree other than the
primary can be validly measured for subprocess behaviour while the editable
install points elsewhere. Either run `pip install -e .` from the worktree under
test, or export `PYTHONPATH` for every run.

## Where the failure count actually stands

| measurement | failed |
| --- | ---: |
| whole suite, no fixes, no `PYTHONPATH` | 268 |
| 6 subdirs, fsync fix, no `PYTHONPATH` | 246 |
| 6 subdirs, fsync fix, `PYTHONPATH` set | **240** |

The two environment defects together account for roughly 14 failures
(8 fsync + 6 path). **The consolidated tip has on the order of 240 genuine
test failures that are not explained by environment.** The original conclusion —
that the tip is substantially red and not a drop-in trunk — survives all three
corrections.

Root-level `tests/test_*.py` (197 files) contributes comparatively few
failures, since the whole-suite figure (268) is close to the subdirectory
figure (246) under equivalent conditions.

### Confound check: were the measurements polluted by my own edits?

The dominant remaining error messages (`surface` ×54, `effectful` ×29,
`write-capable` ×25, mostly `ValueError`) come from the repository-write
inventory scanner, which pins exact source digests. Since two files had been
edited in the measured worktree, those edits could plausibly have caused the
digest failures.

Tested against a freshly created, byte-clean LF worktree of the same commit:

| worktree, same 6 subdirs, `PYTHONPATH` set | failed | passed |
| --- | ---: | ---: |
| pristine `60b2bfe`, unmodified | 243 | 1699 |
| same tip + the two fixes from this session | **240** | **1707** |

**The confound did not materialise.** The edits reduced failures by 3 and
added 8 passes; they did not manufacture any. The ~240 figure is a property of
the tip, not of the measuring setup.

### Final verified position

The consolidated tip carries roughly **240 genuine test failures** across its
six test subdirectories, after controlling for line endings, the editable
install, the fsync defect, and edit pollution. Every environmental explanation
tested accounts for ~14 failures in total. The tip is substantially red on
Windows and is not a drop-in trunk.

## Correction: the largest cluster is NOT a Windows problem

The framing "Linux-green, Windows-red" holds for defects 1–3. It does **not**
hold for the largest failure cluster, and that changes the conclusion.

`tests/gates/test_repository_write_inventory_v2.py:191` feeds the scanner this
fixture source:

```python
"from pathlib import Path\nPath('state').write_text('x')\n"
```

and then asserts at line 64-67 that the detected surfaces include
`pathlib.Path.write_text`.

The scanner resolves a call node via `_syntactic_name` (lines 381-387), which
handles only `ast.Name` and chains of `ast.Attribute`, returning `None` for
anything else. In `Path('state').write_text(...)` the receiver is an
`ast.Call`, so resolution returns `None` and the surface is recorded as an
unresolved `<expression>`. `os.write` resolves because it is a plain
module-attribute chain.

Satisfying that assertion requires **inferring the type of the receiver**, not
syntactic name resolution. The scanner does not do type inference.

**This is platform-independent.** No Windows behaviour is involved — the same
AST, the same result, on any OS. The cluster therefore fails on Linux CI too.

Consequence: the consolidated tip is not merely un-portable to Windows; a large
share of its failures are a genuine functional gap between what the scanner
implements and what its tests demand. The earlier inference that Ubuntu CI was
green — used to explain how these defects survived integration — is **not
supported** for this cluster and should not be relied on.

Not established: whether this single mechanism accounts for most of the ~112
`ValueError` failures or only some. A Codex triage run timed out before
delivering a verdict, and no Linux machine was available to confirm directly.

## Still uncharacterised

- 49 remaining failures in `tests/runtimes/` after defect 2 is fixed
- 224 failures elsewhere in the suite, never captured
- whether any of the above are further Windows-portability issues of the same
  family, or genuine logic defects

Next step: a complete `--junitxml` run that is not killed mid-flight, then
group failures by root exception rather than by test name.

---

Iron Plan: ALIGNED
Iron Gate: 0
Evidence: `tests/runtimes/` measured twice at `60b2bfe` in the same LF worktree,
toggling only `_fsync_file`'s open flags: 57 failed/679 passed before, 49
failed/687 passed after. Root cause isolated to
`provider_observation_store.py:441` by traceback, then reproduced standalone
(`O_RDONLY` fsync → errno 9; `O_RDWR` → OK). Full-suite figure 268/6183 from a
prior complete run whose failure list was truncated by `tail`.
No protected artifact modified; no branch deleted; no fix committed.
