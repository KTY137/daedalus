---
name: project-gui-check-green-lies
description: tools/gui_check.py counts tests that never ran as PASSED, and apps/web/dist is a tracked bundle nothing rebuilds — two ways a cockpit spec result can be a lie
metadata:
  type: project
---

Two independent traps make a `tools/gui_check.py` result untrustworthy unless both are
checked first. Both were MEASURED 2026-09-11 while reviewing PR #377.

**1. Not-run tests are counted as passed.** `playwright.config.ts` sets
`maxFailures: 1`, so the first failure aborts that invocation. Playwright's JSON report
lists the tests that never started with `ok: true` and `status: "unknown"` (zero
results). `gui_check._specs()` copies `ok` straight through, and the accounting is
`passed = sum(1 for r in rows if r["ok"] and r["status"] != "skipped")` — so every
not-run test counts as a pass. The "a skip is not a pass" INCOMPLETE guard below it only
looks for `status == "skipped"` and never fires. Raw evidence, one spec file against a
stale bundle: Playwright's own line reporter said `1 failed / 2 did not run / 3 passed`,
while the same JSON through gui_check's arithmetic gives `specs: 6, passed: 5, skipped: 0`.

Sharding does not save you: `--shard i/4` splits by FILE, so all 6 tests of
`composer-autosize.spec.ts` land in shard 1/4, and a failure at declaration line 188
means the tests at 211 and 341 never run and are reported green.

**How to apply:** "270/271 passed" from gui_check is not evidence that any particular
spec passed. Before believing a named spec was green, check Playwright's own
`N did not run` line, or re-run that spec alone. If a run reports exactly one failure,
assume every test declared after it in the same FILE is unmeasured.

**2. `apps/web/dist` is tracked and nothing rebuilds it.** 22 files under
`apps/web/dist` are in `git ls-files`; `gui_check` only refuses when `index.html` is
*missing* (`NOT_BUILT_MARKER`) and never runs a build. CI does build
(`npm ci` + `npm run build` in `g1-ikarus-unified-runtime-admission.yml` and
`tauri-desktop.yml`) — so CI and every local run can disagree completely.
On 2026-09-11 **none of the 54 checkouts on this host** had a bundle containing source
merged 2026-09-10 22:00–22:53; every local GUI run was testing a 2026-09-08 build.

**How to apply:** before trusting or debugging any local cockpit spec, grep the served
`dist` for a string unique to the feature under test (a class name or a selector
literal — minifiers preserve string literals) and compare against `src`. A stale bundle
produces *deterministic* failures that read exactly like flakes. Building safely without
disturbing a lane: `git archive <rev> apps/web daedalus | tar -x -C %TEMP%/scratch`,
junction `node_modules` in, `npm run build`, serve with
`.venv/Scripts/python.exe -m daedalus.interfaces.cli.entry web --port N` from the scratch
root (`web_api.ROOT` is module-relative, so cwd + `-m` decides which dist is served).
No git state is touched. See [[project-daedalus-lane-hazards]] and
[[project-cockpit-pin-spec-flake]].
