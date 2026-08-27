# Handoff — the six-lane cockpit round (2026-08-26/27)

Iron Plan: ALIGNED · Iron Gate: 0 · the cockpit is a read surface over the
canonical kernel; this round added no effectful entrypoint, no state store and
no policy path.

**The cockpit round has landed.** Commits `0d3ea5d1` (the six lanes,
`apps/web/src` and tests) and `3ee17d73` (the rebuilt dist bundle) are in the
tree as of 2026-08-27. One backend commit `0c106b81` landed earlier; the
frontend follows it in chronological order.

## 1. State of the tree

| | |
| --- | --- |
| tree | `C:/Users/nukei/Desktop/agent_env`, branch `main` |
| landed | `0c106b81` — `fix(api): a project's drafts are its own, and help stops naming a moved control` |
| landed | `0d3ea5d1` — `feat(web): the six-lane cockpit round — map, conversation, shell, instruments, material, motion` (18 tracked files, +2987 −1667, plus 13 new files) |
| landed | `3ee17d73` — `build(web): ship the bundle the source now produces` |

Committed in 0d3ea5d1 and 3ee17d73 (18 tracked + 13 new files, manifest below):

    apps/web/src/cockpit/shell.css          391      apps/web/src/cockpit/stage/camera.ts    152
    apps/web/src/cockpit/stage.css          407      apps/web/src/cockpit/stage/paths.ts     308
    apps/web/src/cockpit/conversation.css   897      apps/web/src/cockpit/stage/Glyph.tsx    201
    apps/web/src/cockpit/instruments.css    190      apps/web/src/cockpit/stage/Legend.tsx   131
    apps/web/src/cockpit/overlays.css        96      apps/web/src/cockpit/stage/Reading.tsx  136
    apps/web/src/cockpit/materials.css       48      apps/web/src/cockpit/stage/Tools.tsx     66
    apps/web/src/cockpit/responsive.css      32
    docs/design/COCKPIT_ROUND_2026-08-26.md          docs/design/handoffs-2026-08-26/  (6 lane files)
    docs/design/prototypes/cockpit-2026-08-26/before/  (the before-shots)

Other work committed concurrently (not part of the cockpit round):
`daedalus/langgraph_adapter.py` (commit 8b345413, advisory fleet planning),
opus-fleet experiment (commit dda2eed4, read-only test campaign), plus
various doc updates and architecture inventory patches. These landed via
separate commits and are orthogonal to the cockpit work.

`apps/web/dist` was stale before rebuild but is now in sync (3ee17d73).

## 2. What the round did

Six lanes ran in parallel on file-disjoint ownership (the table is in
`docs/design/COCKPIT_ROUND_2026-08-26.md`, which is the brief they shared and
is worth reading before touching any of this). To make that possible,
`cockpit.css` was first split from one 948-line file into seven modules plus an
index that owns the cascade order — **verified as a no-op: the built CSS
content hash was `index-BijVsy0k.css` before and after.**

- **Kartograph** (map) — canvas fill 52.2 % → **80.0 %** of area; arrowheads so
  edges carry direction; heat as a three-step bar; a legend that states its own
  encoding; a channel router replacing per-edge hashing (min separation between
  overlapping edge runs 0.3 px → **16.6 px**, pairs under 12 px 11 → **0**);
  a Räumlich/Geordnet toggle; a left-rail reading panel; keyboard navigation.
- **Ikarus** (conversation) — the hero sentence and composer as one centred
  group; the runtime picker moved into the composer well as a latency ledger
  (local index 0.6 s vs Claude CLI ~30 s, both timed by the app itself); the
  thread bar reduced to a real thread header that is not rendered when there is
  no thread; the transcript now scrolls inside itself.
- **Rahmen** (shell) — three chrome groups with three treatments; a real project
  dropdown with type-ahead; palette arrow-key traversal; five shortcuts
  (`Strg+K`, `Strg+,`, `1`/`2`, `r`, `Esc`) guarded against firing while typing.
- **Instrumente** — the status line restructured into two deliberate rows with a
  real `pending` tone; three silent state collapses closed (undefined governance
  used to render with the same `warn` styling as a genuine blocked promotion).
- **Material** — new token vocabulary (`--warn`, `--heat-1..5`, `--plane-1..4`,
  type roles, a four-step elevation scale, stage depth); three themes' fonts were
  silently falling through to a system default (Werkstatt→Segoe UI,
  Sternkarte/Depesche→Georgia) and now have their own stacks; glass restricted
  from 5 surfaces to 2 per the owner's ruling.
- **Bewegung** — `src/motion/` was a complete, tested vocabulary the cockpit did
  not import at all. Both drawers now use it; the spec's source guards were
  extended to scan `cockpit/` and `theme/`, which immediately caught a hand-copied
  spring constant in another lane's file.

### Bugs found by doing the work, not by looking for them

1. **`/api/drafts` was unscoped.** The decision card showed **427 pending under
   `agent_env`, which owns 0**. Fixed and committed in `0c106b81` with three
   mutation-checked tests.
2. **A lost-update race in the decision card.** `project` starts `''` and
   resolves a moment later, so two requests overlap; with the backend answering
   in tens of seconds the first (unscoped) could land after the second (scoped)
   and overwrite a correct result. Fixed with a `loadId` guard.
3. **Citations were dead.** Computed once at thread-parse time — before the map
   arrives — so a resumed thread rendered zero. Now derived at render.
4. **Markdown was printed raw** in Claude's answers.
5. **`/api/runtimes/status` exceeds its own client timeout** — see §4.

## 3. Verification — with provenance

Re-run this morning, 2026-08-27, no servers needed:

    [MEASURED 2026-08-27] npx tsc --noEmit          → exit 0, no output
    [MEASURED 2026-08-27] npm run test:motion       → 133/133 passed

Measured 2026-08-26 with the API on 8765 and Vite on 5173, **not re-run since**:

    [MEASURED 2026-08-26] tools/audit.mjs, 6 themes x 2 pages x 4 widths
                          → 0 of 48 combinations below the floor
    [MEASURED 2026-08-26] pytest tests/test_drafts.py  → 9 passed, 4 subtests
    [MEASURED 2026-08-26] pytest -k "web_api or ikarus_os or help"
                          → 122 passed, 6 skipped, 18 subtests, 0 failed
    [MEASURED 2026-08-26] playwright tests/cockpit.spec.ts → 10 passed, 2 FAILED

**The two failures are real and are not flake — see §4.** Both pass in
isolation; both fail inside the full run. Do not report this suite as green.

To reproduce anything above:

    python -m daedalus.web_api --port 8765            # then, in apps/web:
    npm run dev                                       # serves 5173, proxies 8765
    DAEDALUS_GUI_BASE_URL=http://127.0.0.1:5173 npx playwright test tests/cockpit.spec.ts

## 4. Open blockers, measured and deliberately not fixed

**`/api/runtimes/status` cost — RESOLVED 2026-08-27 (owner decision: cache with a
visible measured-at).** [MEASURED 2026-08-26] the probe was 16.6 s under load,
28.0 s on a quiet box, 36.1 s after the Playwright suite, because it launches
each CLI to ask its version. The owner ruled: cache the probe, and every cached
row carries when it was measured so a stale "erreichbar" cannot lie. Shipped in
`768a9e4d` — a per-runtime TTL cache (`DAEDALUS_RUNTIME_STATUS_TTL_S`, default
30 s) with `measured_at`/`measured_age_s` on every cached row, the settings
reachability list showing the age, and the 45 s client ceiling kept as the net
for the first cold probe (MEASURED cold 12.0 s, warm 0.0 s). The two Playwright
failures this caused should now clear with servers up; re-run to confirm (§6.3).

**`/api/structure` emits one plane, so the four-plane view cannot be built.**
`StructureGraphNode` carries `id`, `fan_in`, `loc`, `score` — nothing says which
of Code/Type/Data/Knowledge a node belongs to, and every drawable node is a
Python module. The owner's ruling asks for the ordered four-plane column layout
as an alternative representation. What shipped is an ordered view over the code
plane whose columns are *relation to focus* (Importeure, Fokus, Importe, Zweite
Ebene) sorted by heat — **and the interface says so in words, under the toggle**,
so it cannot be mistaken for the four-plane view. Material's `--plane-1..4`
tokens exist with no consumer until the endpoint emits a plane. The blocker is
upstream, in what `/api/structure` returns.

**`/api/context/plan` returns 0 seeds for a German sentence** and 22 for
`picker attempt lease`. The panel reports this honestly. Backend fix.

**The assistant speaks English inside a German interface.** The deterministic
route's answers come from the backend and were not translated. The client's own
five error strings in `api.ts` were, because they arrive at the moment something
fails. The backend voice is a larger, separate decision.

## 5. Instrument blind spots found this round

Recorded in full in `docs/design/COCKPIT_ROUND_2026-08-26.md` §Errata. The two
that matter beyond this round:

- **`tools/audit.mjs` composites contrast against ANCESTORS only.** A fill
  painted by a *sibling* is invisible to it. Here it failed loudly, but the same
  shape can just as easily produce a **false pass**. Kartograph measured its own
  affected labels by hand rather than trusting the green (worst 5.07:1).
- **The 427-draft lie was measured by nothing** for four review rounds.
  `tests/cockpit.spec.ts` already compares drawn nodes, palette offers and the
  status line against `/api/structure` — the decision card was simply outside
  what it compares. A per-project honesty check has to name every surface that
  shows a count, not only the ones someone thought of.

Also worth keeping: three agents were killed mid-run by transport errors. Each
time the tree was left typecheck-clean, and the half-landed change was found by
diffing classNames in the TSX against rules in the CSS. That check is worth
keeping in mind, **and it must parse every `className=` form** — the first pass
covered 50 of 56 sites and could have hidden a fifth missing rule.

## 6. What to do next, in order

1. ~~Commit the round by pathspec~~ — done, `0d3ea5d1`. [MEASURED 2026-08-27, Mnemosyne: `git log --oneline -- apps/web/tests/cockpit.spec.ts`]
2. ~~Rebuild and commit `apps/web/dist`~~ — done, `3ee17d73`. [MEASURED 2026-08-27, Mnemosyne: `git log --oneline -- apps/web/dist`]
3. Re-run the Playwright suite with servers up and confirm the failure count is
   still 2 and still those two. If a third appears, it is new.
4. Take the owner decision on the runtime probe (§4) — it is the one thing
   blocking a green suite and it is a correctness question, not a perf one.
5. The six lane handoffs in `docs/design/handoffs-2026-08-26/` carry each lane's
   own leftovers and cross-lane requests. Not verified this pass whether they
   have been triaged since.
