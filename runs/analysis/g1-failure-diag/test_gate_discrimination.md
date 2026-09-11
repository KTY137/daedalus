# Diagnosis: tests/test_gate_discrimination.py::CorpusDesignTests::test_anchors_are_present_and_unique_in_the_current_tree

Interpreter used throughout: `/c/Users/Administrator/daedalus/.venv/Scripts/python.exe` (per rule 5).

## Environment

- HEAD before measurement: `851ff43cc63dd788d1da63a6f7fa44fcc6ed0291` (matches assignment base).
- HEAD after measurement: `b3cc415b6b15d3461a8d79ae372d96ee533047f0`. HEAD moved *during* this
  session (another agent committed `fix(architecture): record the offload debt in the field the
  instrument counts` on this shared branch). MEASURED: `git show --stat b3cc415b` touches only
  `docs/architecture/import-boundaries.json` and `tests/test_architecture_boundaries.py` — neither
  `tools/gate_discrimination.py`, `daedalus/file_bridge.py`, nor
  `daedalus/interfaces/bridge/queue.py`. The subject test's inputs did not change; the measurement
  is not void, but flagging per "background mutators invalidate foreground runs."
- `git status --porcelain | wc -l`: 1 before and after (unchanged; the pre-existing dirty `runs/`
  tracked in the session's git status, not touched by this diagnosis — read-only per rule 1).
- Nested worktree count (`.claude/worktrees/agent-*` + `.daedalus_worktrees/*`): 6 before and after
  (unchanged).

## Leading hypothesis (nested-worktree duplication via tree walk): REFUTED for this test

MEASURED: `grep -n "rglob\|os.walk\|glob(" tools/gate_discrimination.py` — no output. There is no
filesystem walk anywhere in `tools/gate_discrimination.py`.

Read `tools/gate_discrimination.py:630-648` (`check_anchors`, the function the failing assertion
calls): for each `Mutation` it does exactly `Path(repo_root) / m.file` — a single, fixed, per-mutation
relative path (e.g. `daedalus/file_bridge.py`) — reads that one file's text, and calls
`validate_unique_anchor(text, m.find)` (lines 599-614), which does `text.count(find)` on that one
file's content. It never enumerates directories, never touches `.claude/worktrees/` or
`.daedalus_worktrees/`, and has nothing resembling `_SKIP_PARTS`. The sibling bug pattern
(`test_spend_coverage.py`'s `Path(ROOT).rglob("*.py")` walking into nested checkouts) does not exist
in this test's code path at all — the hypothesis, stated as leading for this specific target, is
**wrong** for this file, and I am not force-fitting it. (It may well still describe
`test_spend_coverage.py`/`test_egress_coverage.py`, which is outside this diagnosis's scope.)

## Reproduction: DETERMINISTIC, 3/3 identical

Command (repeated verbatim 3×):
```
.venv/Scripts/python.exe -m pytest tests/test_gate_discrimination.py -q > /tmp/diag_gatediscrim/rN.txt 2>&1; echo "RC=$?"
```

| run | RC | result line |
|---|---|---|
| 1 | 1 | `1 failed, 41 passed, 2 skipped in 14.02s` |
| 2 | 1 | `1 failed, 41 passed, 2 skipped in 13.09s` |
| 3 | 1 | `1 failed, 41 passed, 2 skipped in 12.71s` |

Same single failing test, same failure detail, all 3 runs:
```
FAILED tests/test_gate_discrimination.py::CorpusDesignTests::test_anchors_are_present_and_unique_in_the_current_tree
AssertionError: Lists differ: [{'id': 'bridge_enqueue_collision', 'file': 'daedalus/file_bridge.py',
'ok': False, 'detail': 'LookupError: mutation anchor not present'}] != []
```

**Verdict: deterministic.** Not order-dependent (single file, single worker, no `-n auto` per rule
3), not load-dependent (identical across 3 runs on this shared box), not environment-dependent in
the sense the hypothesis proposed (no tree-walk into worktrees). It is a genuine, stable anchor
drift.

## Full enumeration of the "bad" (non-unique/non-present) anchors

Total anchors checked: all entries of `gd.MUTATIONS` (12 corpus entries, confirmed via
`tools/gate_discrimination.py`'s `MUTATIONS` tuple). Bad-row count from the actual assertion
failure: **1 of 12**.

| bucket | count |
|---|---|
| inside a nested worktree (`.claude/worktrees/*`, `.daedalus_worktrees/*`) | 0 |
| in the canonical tree | 1 |
| **total** | **1** |

The one bad row:
- `id`: `bridge_enqueue_collision`
- `file`: `daedalus/file_bridge.py` (canonical path, not worktree-prefixed)
- failure mode: **`LookupError: mutation anchor not present`** — i.e. the anchor is *missing*, not
  *duplicated*. This is a different failure shape than the "unique" collision the leading hypothesis
  predicted (which would show `mutation anchor is not unique (N occurrences)`); `validate_unique_anchor`
  (`tools/gate_discrimination.py:599-614`) raises `LookupError` on `count == 0` for "not present" and
  a distinct message for `count > 1`. This run hits the `count == 0` branch. There is no duplication
  to bucket by worktree vs canonical — the anchor simply does not exist anywhere in the canonical
  file any more.

## Canonical-only re-run

Given the hypothesis is inapplicable (no tree walk exists to filter), the "canonical-only" re-run
degenerates to the already-canonical single-file check `check_anchors` performs. Confirmed directly
by reading the target file:

```
grep -n "base = f\"{_stamp" /c/Users/Administrator/daedalus/daedalus/file_bridge.py   -> no match
grep -n "def enqueue"      /c/Users/Administrator/daedalus/daedalus/file_bridge.py   -> line 413
```

`daedalus/file_bridge.py::enqueue` (line 413-477) no longer builds the collision-resistant filename
itself. It now delegates to `bridge_queue.publish_request(..., clock=_stamp,
unique_hex=lambda: uuid.uuid4().hex, ...)`. The actual filename construction now lives in
`daedalus/interfaces/bridge/queue.py:150`:

```python
base = f"{clock()}-{slug or 'task'}-{unique_hex()[:8]}"
```

— the same *shape*, but a different *file*, with `_stamp()`/`uuid.uuid4().hex[:8]` replaced by the
injected `clock()`/`unique_hex()[:8]` ports. The corpus entry's `find` string
(`tools/gate_discrimination.py:390-397`) still says:

```python
find='    base = f"{_stamp()}-{slug or \'task\'}-{uuid.uuid4().hex[:8]}"'
```

targeting `file="daedalus/file_bridge.py"`. That literal text is gone from that file. The assertion
would fail on any clean canonical checkout, worktree noise or not — this is a real drift, not a scan
artifact.

## First failing commit — archaeology

Traced the code move: `git log --oneline -- daedalus/interfaces/bridge/queue.py` shows the file was
created by:

```
bb33e72c refactor(bridge): extract queue document owner   (2026-08-31 17:55:17 +0200)
```//
`git show --stat bb33e72c`: moves collision-safe filename construction out of
`daedalus/file_bridge.py` (101 lines removed) into the new `daedalus/interfaces/bridge/queue.py`
(105 lines added), consistent with the observed current-tree shape.

The corpus entry itself (`bridge_enqueue_collision` in `tools/gate_discrimination.py`) was added
earlier, in `70f10666 feat(web): serve the health surface, so the browser stops re-deriving it`, and
`git log -S"bridge_enqueue_collision" -- tools/gate_discrimination.py` shows no commit has touched
that string since — the anchor was never updated to follow the refactor.

Checked against the given first-parent archaeology list (851ff43c … f60ffd3d, newest→oldest):
`git merge-base --is-ancestor bb33e72c <each-of-24-commits>` returns true for **every** commit in
the list, including the oldest, `f60ffd3d` (dated 2026-09-01 12:49:00). `bb33e72c` itself is dated
2026-08-31 17:55:17 — **one day before** `f60ffd3d`, i.e. strictly outside (older than) the entire
supplied range.

Confirmed directly: `git show f60ffd3d:daedalus/file_bridge.py | grep 'base = f"{_stamp'` returns no
match (RC=1) — the anchor was already absent from `file_bridge.py` at the oldest commit in the given
range. `git show f60ffd3d:tools/gate_discrimination.py` still carries the stale
`bridge_enqueue_collision` anchor at that revision too.

**No commit in the given 24-commit range introduces this failure.** The introducing commit is
`bb33e72c` (2026-08-31), which predates the entire supplied archaeology window. The test was already
red at every commit in the given range, including `f60ffd3d`, `74008fab` (where it was reported
failing under `-n auto --dist loadfile`), and `851ff43c`.

## Root cause

**PRODUCT/TEST-CORPUS drift, not environment.** `tools/gate_discrimination.py`'s `bridge_enqueue_collision`
mutation anchor was never updated when commit `bb33e72c` moved the collision-safe filename
construction (`base = f"{_stamp()}-{slug}-{uuid...}"`) from `daedalus/file_bridge.py` into
`daedalus/interfaces/bridge/queue.py::publish_request` (as `base = f"{clock()}-{slug}-{unique_hex()...}"`,
with `_stamp`/`uuid.uuid4().hex` now injected as `clock`/`unique_hex` ports). The mutation's `file`
field still points at `daedalus/file_bridge.py` and its `find` string still contains the pre-refactor
literal names. This is exactly the "drifted mutation anchor" class `check_anchors` exists to catch
(see its own docstring, `tools/gate_discrimination.py:632-636`) — it is doing its job correctly; the
corpus entry is stale.

This is deterministic and reproducible on a clean read of the canonical tree; it has nothing to do
with `-n auto`, load, or the ~110 worktrees on this box. The `-n auto --dist loadfile` framing in the
task description is a red herring for this particular test — it fails identically single-process,
serial, 3/3.

## Fix sketch

Update the `bridge_enqueue_collision` `Mutation` entry in `tools/gate_discrimination.py`
(around line 389-409) to target the current owner of the logic:
- `file="daedalus/interfaces/bridge/queue.py"`
- `find='    base = f"{clock()}-{slug or \'task\'}-{unique_hex()[:8]}"'`
- `replace='    base = f"{clock()}-{slug or \'task\'}"  # SEEDED DEFECT: uuid suffix dropped, same-second enqueues collide'`

The `incident` and `covering_tests` fields (referencing `tests/test_bridge_signals.py`'s two
same-second-collision tests) likely still apply if those tests still exercise `enqueue()` end-to-end
through `publish_request` — worth a quick check that they still cover the new location before
closing, but that is a one-file, mechanical edit; no product code change needed since the guarded
behavior (collision-safe filenames) is still present, just relocated.

## Owner

`tools/gate_discrimination.py`'s corpus entries — this is test/corpus-infrastructure maintenance
tied to `daedalus/interfaces/bridge/` (the G1-IFACE-BRIDGE-03 packet, per
`bb33e72c`'s own commit message and its companion doc
`docs/.../G1-IFACE-BRIDGE-03_QUEUE_DOCUMENT_OWNER.md`). Whoever owns the bridge interface
extraction packets should carry the anchor update alongside future refactors of this area, since
`check_anchors` will keep catching (correctly) every future move that isn't accompanied by a corpus
update.
