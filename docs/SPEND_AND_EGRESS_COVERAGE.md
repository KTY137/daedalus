---
title: Spend and egress coverage
status: reconstruction
reconstructed: 2026-08-22
reconstructed_from: executed measurement, not from the citing tests
cited_by: tests/test_spend_coverage.py, tests/test_egress_coverage.py
citations: 9
authority: history/evidence — not policy, not a guard
---

# Spend and egress coverage

> **`status: reconstruction`, and the label is load-bearing.** This document was
> cited nine times as "the decision record" and **never existed**: `git log
> --all --diff-filter=A -- docs/SPEND_AND_EGRESS_COVERAGE.md` returns nothing
> [MEASURED 2026-08-22]. The citations were a promise, not a pointer.
> `tests/test_spend_coverage.py:216` says so in its own words. What follows was
> rebuilt on 2026-08-22 by **running the code**, not by transcribing the
> docstrings that cite it — a receipt authored from the tests that cite it
> would only prove the tests agree with themselves. Every number below names
> the command that produced it. Nothing here is recovered original text; the
> original never was.

Measurement base: `HEAD 41173032` (docs-only commits ahead of `b52f5f9a`),
working tree carrying 6 modified tracked files and 6 untracked paths from
other lanes at measurement time. The static census ran against a clean
`git archive HEAD` export of `b52f5f9a`; the executed replays ran in the
working tree. Both are named per row in §6.

## 1. The two questions

`tests/test_budget.py` asks "is every billable site in the register". This
surface asks the two it cannot:

1. **Does the ceiling exist in the process that spends?** It is not a syscall
   hook. It is three monkeypatched Python functions (`subprocess.run`,
   `subprocess.Popen`, `urllib.request.urlopen`) installed by
   `daedalus.budget.install_process_guard()`. A process that never calls it
   spends unmetered.
2. **Does anything ship file BODIES to a vendor without the secret floor?**
   `daedalus.sensitivity.secret_floor_rule` is unconditional and fail-closed:
   a hit is REFUSE, there is no redact-and-send.

## 2. The classifier, and the 14/14 deletion experiment

The guard bills only what `classify_argv` names, so a vendor behind a process
shepherd is the cheapest possible bypass. The widening landed 2026-07-29 in
**commit `390f75e5`** ("feat(budget,egress): declared trust boundary,
subscription axis, close 5 unmetered spawn sites"), which added the second row
of `daedalus/budget.py:_WRAPPERS` (`uv`, `uvx`, `timeout`, `nohup`, `xargs`,
`stdbuf`, `winpty`, `start`, `sudo`, `doas`, `time`, `script`, `nice`,
`setsid`) and `claude-code` to `_PAID_EXECUTABLES`.

**Deletion experiment, replayed 2026-08-22 [MEASURED].** The additions were
reverted *in memory* (`_WRAPPERS` and `_PAID_EXECUTABLES` rebound to their
pre-`390f75e5` contents inside one Python process; the tree was not edited,
the originals were restored in a `finally`):

| arm | result |
| --- | --- |
| as shipped | 14 / 14 wrapped-vendor argv classified correctly |
| additions reverted | 0 / 14 — `classify_argv` returned `None` for **all 14** |
| innocent argv, reverted arm | 7 / 7 still unbilled |

That is the RED verification `tests/test_spend_coverage.py:74` claims, executed
rather than asserted: without those two lines the guard spawns `uv run claude
-p ...` for free. The innocent-argv arm is what stops the fix from becoming a
guard that bills `git status` and therefore gets deleted at 3am.

## 3. The entry-point census — independently generated

The requirement is an *independent* denominator: the tests find their entry
points with regexes over raw text, so this census parses the tree instead
(`ast`: a real `If __name__ == "__main__"` node, effect calls as `Call` nodes
with a resolved dotted callee, vendor tokens in string **constants** only).
Script: `penelope_effect_census.py`, run against a clean export of `b52f5f9a`.

| scan | method | rows | of which unguarded |
| --- | --- | ---: | ---: |
| independent census | AST | **9** | 4 |
| `runnable_spend_entrypoints()` (the tests') | regex | **17** | 10 |
| the same, minus `tests/` (excluded by `_EXCLUDED_TEST_DIRS`) | regex | **10** | 5 |
| `KNOWN_UNGUARDED_ENTRYPOINTS` ledger | declared | 5 | 5 |

**The denominators do not match: 9 against 10.** The plan asked that they be
equal; they are not, and the single divergent row is named rather than
smoothed over:

- `tools/gate_discrimination.py` — counted by the regex scan, rejected by the
  AST census. Its only `agy` token lives *inside a string literal* holding a
  seeded-defect fixture (`"...BENCH_SSH, \"--\", \"agy\", \"-p\", \"-\"]..."`,
  5 constants contain the substring, **0** constants *are* a vendor token
  [MEASURED]); its real spawns are `git` and `pytest`. Both methods agree it is
  not billable — the regex reaches that answer through a hand-written ledger
  entry, the AST census through the structure. The ledger entry stays, because
  it is also the file's protected-artifact disposition: installing the guard
  inside it would be an edit to a guard, which plan sec. 15 forbids.

The 7 rows the regex scan finds under `tests/` are excluded by policy, not by
accident: test modules are not run as `python <file>`, they name vendors in
order to mock them. The residual risk that exclusion carries is in §5.

The five unguarded production rows and their dispositions (all NOT BILLABLE,
each inspected, unchanged by this reconstruction):

| path | why it is in the ledger rather than guarded |
| --- | --- |
| `daedalus/doctor.py` | `--version` / `login status` probes generate no tokens |
| `daedalus/health.py` | git, `shutil.which`, local `/api/tags` |
| `daedalus/claude_bridge.py` | since `448969d` the `__main__` fail-closes via `parser.error` before any effect; the one vendor spawn is private and brokered |
| `tools/system_check.py` | spawns `daedalus.cli web` / `file_bridge watch`; its `claude` token is a room SPEAKER NAME |
| `tools/gate_discrimination.py` | vendor token inside a fixture string; protected artifact (see above) |

## 4. Who installs the ceiling

The census excludes the generated frozen-sidecar backend and Cargo target
directories beneath `apps/web/src-tauri/`. Measured on
2026-08-30 after a desktop build, scanning those outputs counted the same
`daedalus/budget.py`, `cli.py`, `loop.py`, and sealed `claude_bridge.py` a
second time. They are derived packaging artifacts, not independent executable
source owners; authoritative source remains covered by the repository-wide
walk.

Independently reproduced 2026-08-22 [MEASURED] by scanning every non-test
`*.py` for a *call* to `install_process_guard()` — **8 files**, exactly the set
the test pins, with no drift:

`daedalus/budget.py`, `daedalus/cli.py`, `daedalus/orchestration/loop.py`,
`runs/ab/run_arm.py`, `runs/council/room.py`, `runs/council/room_server.py`,
`runs/council/summarize.py`, `tools/operability_drill.py`.

Two of those matter structurally. `daedalus/orchestration/loop.py` is the only entry point
that spends **repeatedly by design**. `daedalus/budget.py` entered the set on
2026-08-18 when `process_guard_boundary_decision()` began installing the
ceiling for roughly forty centrally-wired entrypoints through one function —
the reason this list stopped growing one file at a time, and the reason a
count alone is no longer the coverage story.

## 5. Egress — bodies, not argv

Scan: files that read a body off disk (`read_text`/`read_bytes`/`open().read()`)
**and** name a paid vendor destination, scoped to `daedalus.budget.BILLABLE_SITES`
(8 python paths). MEASURED 2026-08-22, working tree:

| rows in billable scope | consult a fence | do not |
| ---: | ---: | ---: |
| 6 | 4 | 2 |

Floored: `daedalus/council/vendors.py`, `daedalus/providers/codex_cli.py`,
`runs/council/room.py`, `runs/council/summarize.py`.

- **`runs/ab/run_arm.py` — CRITICAL, open.** `distilled_context()` inlines
  whole file bodies from `C:/Users/nukei/Desktop/PnP_App` — a *different* repo,
  chosen by `plan_context`, not by a human — into a `claude` prompt. If the
  planner selects a `.env`, it ships verbatim. Open because the fix is a design
  decision: dropping a selected file silently would change what the two A/B
  arms are comparing.
- **`daedalus/orchestration/ikarus_os.py` — inspected, not egress.** `_claude_stream` reads
  the vendor's *response* file; prompt input is assembled separately. Bytes
  flow vendor -> disk -> caller.
- **Out-of-repo witness.** `~/.claude/skills/room/room.py` exists here (26 990
  bytes), still has `def _attach`, and still contains **no** `secret_floor_rule`
  and no `classify_data` [MEASURED 2026-08-22]. It is outside this repo, so no
  test here can gate it; the witness records that we knew.
- The whole-tree scan (no billable scoping) reports 27 rows, 19 of them
  unfloored [MEASURED]. That number is an over-approximation by construction —
  a config read and a vendor name in one large module are not a data flow — and
  is recorded only so the narrowing to 6 is visible as a *choice* rather than
  as the natural size of the problem.

## 6. Residual risk, stated because it is real

- `pytest` runs **without** the ceiling installed. A test that genuinely
  spawned a vendor would spend unmetered. None does today (verified by
  inspecting every unmocked `subprocess.run(["claude"...])` match under
  `tests/`), but nothing prevents one.
- The ceiling is monkeypatched Python functions in one process. Anything that
  is not that process — an external client, a direct `os.execv`, a spawned
  shell that re-enters Python — is outside it. Per plan sec. 1: no prompt and
  no local hook is a security boundary.
- Both ledgers are **drift detectors with declared contents**, green today
  against a named list of known holes. They go red when a new one appears; they
  do not prove the list is complete.

## 7. Provenance of every number

| number | value | how | where |
| --- | ---: | --- | --- |
| citations of this file | 9 | `grep -rn SPEND_AND_EGRESS_COVERAGE --include=*.py` | working tree, 41173032 |
| commits that ever added this file | 0 | `git log --all --diff-filter=A` | all refs |
| wrapped-vendor argv cases | 14 | executed `classify_argv` | working tree |
| deletion experiment, reverted arm | 0/14 pass, 14 `None` | in-memory revert of `_WRAPPERS`/`_PAID_EXECUTABLES` | working tree |
| innocent argv, reverted arm | 7/7 unbilled | executed `classify_argv` | working tree |
| independent AST census | 9 rows, 4 unguarded | `penelope_effect_census.py` | `git archive b52f5f9a` export |
| tests' regex scan | 17 rows (10 outside `tests/`) | `runnable_spend_entrypoints()` | same export |
| unguarded-entrypoint ledger | 5 entries | module constant | `tests/test_spend_coverage.py` |
| guard installers | 8 files | independent `install_process_guard()` call scan | working tree |
| egress rows in billable scope | 6 (2 unfloored) | `body_inlining_vendor_paths()` + `BILLABLE_SITES` | working tree |
| egress rows, whole tree | 27 (19 unfloored) | same, unscoped | working tree |
| the two test modules | 34 passed, 0 failed, 2.92 s | `pytest -q tests/test_spend_coverage.py tests/test_egress_coverage.py` | working tree |
| out-of-repo room skill | fence absent | file read | `~/.claude/skills/room/room.py` |

Not delivered by this reconstruction, so nobody counts it as present: the
doc-to-doc reference **report** the Phase-5 spec pairs with this file (failing
on unresolved receipt links) is not built here, and no runtime effect census
exists for the *egress* half comparable to §3's — the egress denominator above
is the tests' own scoping function, which is exactly the circularity §3 avoids.
