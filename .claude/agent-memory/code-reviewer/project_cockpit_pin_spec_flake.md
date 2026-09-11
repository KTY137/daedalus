---
name: project-cockpit-pin-spec-flake
description: composer-autosize.spec.ts "moves the transcript..." failing with Received 191 is USUALLY a stale apps/web/dist, not a flake — check the bundle before blaming load or a PR
metadata:
  type: project
---

`apps/web/tests/composer-autosize.spec.ts` → *"moves the transcript and never a scroll
container above it"* fails with:

```
Error: round 0: the transcript stopped following its newest turn
Expected: <= 2      Received: 191
```

**`191` is DETERMINISTIC** — the height of the paragraph the test appends — so the same
`Received` on two branches is *not* evidence of a shared cause.

**The dominant cause is a stale bundle, not load.** MEASURED 2026-09-11: against the
`apps/web/dist` that every checkout on this host actually serves, this test fails 2/2 on
an idle box (CPU 10%), and the "other flake" in the same file
(*"the field and its sizing mirror agree on typography at every breakpoint"*, a 15 s
locator timeout on `.composer-grow`) fails 1/1 for the same reason. Both features landed
in PR #367 (`7048ce07` added `.composer-grow`, `46664c54` added the `:scope > .turn`
pin, both 2026-09-10 evening) and no local bundle was built after 2026-09-08. Against a
freshly built bundle all 6 tests in the file pass in 6.8 s. Details and the safe
scratch-build recipe: [[project-gui-check-green-lies]].

An earlier session recorded a genuine load-induced failure (1 of 6 repetitions under
32-way load, passing 10/10 quiet). Treat that as possible but unconfirmed; it cannot be
distinguished from the stale-bundle failure by the error text alone.

**There is a second, non-load mechanism that produces the identical `191`, and it is a
product bug.** `pinned.current` (`Conversation.tsx`) is armed only by `onScroll`
(gap < 48 px), by the layout effect on a `turns.length` change, or by `jumpToEnd`. When a
long thread opens, the last scroll event the handler sees can be one where the gap was
still large, so the transcript comes to rest at gap 0 with the pin **disarmed**, and the
next streamed delta does not follow. MEASURED 2026-09-11 on a fresh bundle: deleting the
`waitForTimeout(1200)` settle before the precondition poll fails 1 in 6 with
`Received: 191` while the gap traces 0 the whole time, and inserting a scroll whose last
event sees gap 0 rescues it 4/4 — which is only possible if the pin was disarmed rather
than slow. The 1200 ms settle is therefore load-bearing, not dead time, and it is a race
whose margin shrinks under load. **No amount of polling fixes this shape**, so do not
treat a longer timeout as a fix until the disarm is ruled out.

**Measured pin timing** (fresh bundle, `expect.poll` instrumented): the pin is observed
after 105 / 118 / 113 ms across the three rounds.

**How to apply:** when a PR is accused of breaking this spec, in order —
1. grep the served `dist` for `:scope` and `composer-grow`; absent means stale bundle,
   stop, the PR is innocent;
2. check whether the spec actually RAN (`N did not run`, see the memory above);
3. only then check whether the accused diff can reach `/?view=chat`, and reproduce on
   `main` under load.

**Running one Playwright spec by hand:** `tools/gui_check.py` has no spec filter. Start
the server yourself, export `DAEDALUS_GUI_BASE_URL`, and
`node node_modules/playwright/cli.js test <file> -g <title>`. Do **not** pass
`--reporter=...` if you want the JSON report — a CLI reporter replaces the config's and
the JSON file is silently never written. `kill` on the bash job does not stop the server;
match `cli.entry web --port <port>` in `Get-CimInstance Win32_Process` (there are ~4
processes per server including a uv python grandchild) or you leak servers.
