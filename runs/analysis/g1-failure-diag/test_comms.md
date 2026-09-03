# Diagnosis: tests/test_comms.py::VsCodeExtensionTests::test_extension_dashboard_supports_team_and_environment_controls

All measurements taken at `HEAD=54f0975398fd77120383c3af0ac5bb9291ef7064` (main).
`git rev-parse HEAD` checked before AND after the full session — unchanged. No VOID declaration needed.

## Status

**REPRODUCES SOLO, DETERMINISTICALLY.** Unlike the calibration warning in the task
brief, this is not a case of "cannot reproduce solo" — the failure is a plain,
stable content assertion against a real file, insensitive to `-n auto`/xdist,
worker count, or ordering.

## Verdict + 3-run table (solo, file-only invocation)

Command each time:
```
cd /c/Users/Administrator/daedalus && .venv/Scripts/python.exe -m pytest tests/test_comms.py -q > /tmp/diag_comms/runN.txt 2>&1; echo "RC=$?"
```

| Run | RC | Result line | Failing test |
|---|---|---|---|
| 1 | 1 | `1 failed, 25 passed in 0.67s` | `test_extension_dashboard_supports_team_and_environment_controls` |
| 2 | 1 | `1 failed, 25 passed in 0.63s` | same |
| 3 | 1 | `1 failed, 25 passed in 0.67s` | same |

Identical failure, identical line (`tests/test_comms.py:189: AssertionError`), identical
message (`AssertionError: 'active_agents' not found in '<extension.js source>'`) all
three times.

**Verdict: deterministic.** Not order-dependent, not load-dependent (all three runs on
an otherwise idle-for-this-file solo invocation), not environment-dependent in any
sense that varied across the three runs. [MEASURED]

## Path-length probe

**Not applicable — skipped.** Read the test body (`tests/test_comms.py:175-189`): it does
`src = EXTENSION_MAIN.read_text(...)` where `EXTENSION_MAIN = ROOT / "vscode-agent-env" /
"extension.js"` — a fixed repo-relative path. No `tmp_path`, no `tempfile`, no xdist
`popen-gwN` component anywhere in this test method. (Other tests in the same file, e.g.
`InitRepoToolInstructionTests`, do use `tempfile.TemporaryDirectory()`, but not this
subject test.) [MEASURED via Read of tests/test_comms.py]

## What the test does

`tests/test_comms.py:175-189` reads `vscode-agent-env/extension.js` as raw text and does
a literal-substring `assertIn` for 10 needles — no parsing, no AST, straight `str in str`.

## Enumerated expected-vs-actual identifier sets

Expected set (size 10), each checked with `grep -c -F -- "<needle>" vscode-agent-env/extension.js`:

| # | Needle | Present? | Count | Location (line) |
|---|---|---|---|---|
| 1 | `max_workers` | present | 2 | 1500, 1519 |
| 2 | `active_agents` | **ABSENT** | 0 | — |
| 3 | `default_lane` | present | 2 | 1500, 1518 |
| 4 | `Claude extension` | present | 1 | 1457 |
| 5 | `Codex/OpenAI extension` | present | 1 | 1458 |
| 6 | `Ollama` | present | 1 | 1459 |
| 7 | `daedalusDashboard` | present | 1 | 2050 |
| 8 | `daedalusDashboardView` | present | 1 | 2050 |
| 9 | `Enforce Harness` | present | 1 | 1268 |
| 10 | `enforceProject` | present | 1 | 515 |

Present: 9/10 — {max_workers, default_lane, Claude extension, Codex/OpenAI extension,
Ollama, daedalusDashboard, daedalusDashboardView, Enforce Harness, enforceProject}.
Absent: 1/10 — {active_agents}. [MEASURED]

Critically, needles 1, 3-9 (all 9 that pass) live at lines 1268-1519 and 2050, which are
**inside a JavaScript block comment** (`/* ... */`, lines 1029-1881) explicitly labelled:

```js
// The live surface remains the canonical React cockpit. The old template is
// retained below only as inactive source history; it cannot be rendered or
// receive webview messages from this adapter.
/*
function legacyDashboardHtmlSource(n) {
  ...
*/
```

`legacyDashboardHtmlSource` (defined line 1030) has exactly one occurrence in the whole
file — its own definition. It is never called. Its own body's comment states plainly it
"cannot be rendered." `grep -F` still finds these needles as literal text inside the
comment, which is why 9/10 pass despite the code being dead.

The one absent needle, `active_agents` (snake_case), never existed in `extension.js` even
inside that dead comment block — the dead block only ever used camelCase `activeAgents`
(a JS variable name built from DOM toggle state, `extension.js:1784`). The snake_case
conversion `activeAgents -> active_agents` happened in a function called
`saveProjectTeam`, which wrote it directly into the project JSON file — and that function
was **fully deleted** (not commented out) in the same commit that retired the legacy
template.

## `git log -S` archaeology on `active_agents` in `vscode-agent-env/extension.js`

```
git log -S "active_agents" --oneline -- vscode-agent-env/extension.js
151b8d18 chore(wip): freeze Gate-1 dirty tree before hierarchy refactor
46a4d45b feat: rebrand agent_env -> daedalus + Mission Control cockpit + dynamic agent configurator
```

`git show 151b8d18 -- vscode-agent-env/extension.js` [MEASURED, pure read] shows the
deleted hunk:

```diff
-function saveProjectTeam(context, payload) {
-  const project = projects(context).find((p) => p.name === payload.project);
-  if (!project) throw new Error(`Unknown project '${payload.project}'`);
-  const data = project.data || {};
-  data.team = Object.assign({}, data.team || {}, {
-    max_workers: Math.max(1, Math.min(32, Number(payload.maxWorkers) || 1)),
-    default_lane: payload.defaultLane || "local_only",
-    active_agents: Array.isArray(payload.activeAgents) ? payload.activeAgents.map(String).filter(Boolean) : [],
-    model_assignments: (data.team || {}).model_assignments || {},
...
```

`saveProjectTeam` was the local, direct-file-write handler for the webview's `saveTeam`
message (still posted today at `extension.js:1785`:
`vscode.postMessage({ type: 'saveTeam', ..., activeAgents })`). The same commit
(`151b8d18`) rewired the extension to an API-first model: the live dashboard binder
(`bindDashboardWebview`, `extension.js:1883-1917`) sets
`webview.html = agentOsHtml(project, activeContextRef)` — an iframe pointing at the
external React/Vite web app (`http://127.0.0.1:8765/...`) — and its *only*
`onDidReceiveMessage` handler (`extension.js:1906-1908`) responds to nothing but
`"retryBackend"`. The `saveTeam` message the (dead) template still posts has **no
listener anywhere in the current file** — confirmed by `grep -n "onDidReceiveMessage"
vscode-agent-env/extension.js`, exactly one hit, the `retryBackend`-only handler.

## Does the capability exist elsewhere under a new name? (checked, not assumed)

```
grep -rn "active_agents|activeAgents|max_workers|maxWorkers|default_lane|defaultLane" apps/web/src/
```
0 hits anywhere in the React cockpit source (`apps/web/src/**`, including
`apps/web/src/cockpit/Settings.tsx`, which is the plausible home for such controls and
was touched this week per `git status`). [MEASURED]

The backend still computes and returns `active_agents` (`daedalus/core.get_squads`,
`daedalus/hierarchy.py`, `daedalus/control_plane.py` all reference the field), so the
*data contract* survives — but **no UI surface currently reachable by a user** (neither
the VS Code extension's live webview, which now only embeds the React app, nor the React
app itself) exposes a control to view or edit `max_workers` / `active_agents` /
`default_lane`. The only place those controls exist as markup+handlers is the dead
`legacyDashboardHtmlSource` comment block.

## (a)/(b)/(c) classification

**(a) — the controls are genuinely missing from the reachable dashboard.** This is a
real product/UI regression, not a stale-test/rename issue and not a blinded instrument.

- Not (b): there is no live location, under any name, where a user can set
  `active_agents`/`max_workers`/`default_lane`. It isn't renamed; the whole editing
  surface (webview form + `saveProjectTeam` handler) was deleted when the dashboard
  moved to the API-first React cockpit, and the React cockpit never got an equivalent
  control. Enumerated: 0 hits for any active/max-workers/lane spelling in
  `apps/web/src/**`.
- Not (c): the instrument is not blinded. It reads a real, non-empty 2106-line
  `extension.js` (verified `wc -l` and byte size before running), and **would fail on
  every needle**, not silently pass, if the file were empty or absent — `assertIn`
  against `""` fails immediately on the first needle (`max_workers`). The instrument
  correctly detected a real absence; it just happens that 9 of its 10 needles are
  satisfied only by dead/commented-out text, which is itself worth flagging separately
  (see Remaining/Fix sketch) but does not make this occurrence a blinded-instrument
  case — the test *did* fail, correctly, on the one thing that is actually gone.

## First failing commit

**Pre-existing — predates the entire given first-parent chain.** Per the task's
calibration note ("two siblings today PREDATED the whole range... verify with
`git show f60ffd3d:<path>`"), the same pattern holds here:

```
git show f60ffd3d:vscode-agent-env/extension.js | grep -c "active_agents"   -> 0
git cat-file -e f60ffd3d:vscode-agent-env/extension.js                      -> exists (rc 0)
git merge-base --is-ancestor 151b8d18 f60ffd3d                              -> rc 0 (true: 151b8d18 IS an ancestor of f60ffd3d)
```

`f60ffd3d` — the **oldest** commit in the given 26-commit first-parent chain
(`54f09753 ... f60ffd3d`) — already has `active_agents` absent, `legacyDashboardHtmlSource`
already wrapped in the same `/* ... it cannot be rendered ... */` comment, and
`saveProjectTeam`/the `saveTeam` handler already gone. The removal happened at `151b8d18`
("chore(wip): freeze Gate-1 dirty tree before hierarchy refactor"), which is a verified
ancestor of `f60ffd3d` and therefore outside (before) the entire chain given for
bisection. **Not bisectable within the given range** — every commit in
`54f09753..f60ffd3d` (first-parent) postdates the actual root cause. [MEASURED, pure
reads: `git show`, `git cat-file -e`, `git merge-base --is-ancestor`, no checkout/bisect
used]

This also means the `d9baa6c0` ("the catalogue names only live source") and `1959cda4`
("repair pages that still name the retired Classic surface") commits named in the task
context are **not** the cause here — they postdate `151b8d18`/`f60ffd3d` and, per the
identical state observed at `f60ffd3d`, did not touch this dead block further in a way
that changed `active_agents` presence.

## Root cause

**PRODUCT/UI regression**, not a test-expectation staleness and not a blinded instrument.
The team/environment-controls capability (edit max workers, active agent roster, default
lane from the dashboard) was retired along with the "Classic" inline-webview dashboard
template during the API-first Agent OS refactor (commit `151b8d18`, itself downstream of
`1da0c0df feat: API-first Agent OS`) and was never rebuilt in the replacement React
cockpit (`apps/web/src/cockpit/**`). The test's other 9 needles still pass only because
they happen to be literal substrings inside the now-dead, explicitly-commented-out
`legacyDashboardHtmlSource` block — those 9 assertions are themselves testing dead code
and would not currently catch a regression in the *live* surface; they are not this
failure's cause, but they are collateral evidence the whole test class is checking the
wrong (retired) surface for 9/10 of its needles.

## Fix sketch

Two independent, separable fixes:

1. **Product**: rebuild a team/environment-controls surface (max workers, active agent
   roster, default lane) in the live React cockpit (`apps/web/src/cockpit/`, likely
   `Settings.tsx` or a new `Team.tsx`), wired through the existing backend contract that
   already returns/accepts `active_agents` (`daedalus/core.py: get_squads`,
   `save_team`-equivalent endpoint if one exists in `daedalus/control_plane.py` /
   `web_api`). Confirm whether an HTTP endpoint for saving team config exists at all in
   the API-first backend before assuming only the frontend is missing.
2. **Test**: once (1) lands, `tests/test_comms.py::VsCodeExtensionTests` should assert
   against the live surface, not `vscode-agent-env/extension.js`'s dead comment block —
   either delete `legacyDashboardHtmlSource` entirely (it is inert, 850+ lines of dead
   weight per this file) and rewrite the test to check `apps/web/src/**` for the
   equivalent controls, or explicitly mark the legacy block's needles as historical/
   deprecated-source assertions distinct from a "dashboard supports X" claim.

## Owner

- Product/UI gap: `extension-dev` (Perdix, owns `vscode-agent-env/`) jointly with
  whoever owns `apps/web/src/cockpit/` (the React cockpit is outside Perdix's stated
  ownership per `.claude/agents` — needs an explicit owner; git blame on
  `apps/web/src/cockpit/Settings.tsx` was not run here, out of scope for a read-only
  diagnosis).
- Test staleness: `test-dev` (Talos, owns `tests/`) for `tests/test_comms.py` once the
  product decision (rebuild vs. formally retire the team-editing feature) is made by the
  owner.

## Remaining / open questions (not resolved by this diagnosis, read-only scope)

- Whether team/environment editing is *intended* to still exist as a product feature
  post-API-first-refactor, or was a deliberate scope cut, is a product decision this
  diagnosis cannot make. That decision determines whether the fix is "rebuild the UI" or
  "delete the test's `active_agents` needle and the dead legacy block together."
- Not verified: whether an HTTP endpoint to *save* team config exists in the current
  `web_api`/`control_plane` backend at all — `daedalus/core.py:100` shows `active_agents`
  is *read* into the dashboard payload, but a write path was not traced in this
  read-only session.

## Addendum 2026-09-03, a later session — both open questions measured

Answers to the two items above, so the owner decision is not made on a guess.
Measured at `1865a753`; this addendum is appended, nothing above it was edited.

**The write path EXISTS.** `daedalus/interfaces/http/effects.py:52-53`:

```python
if len(parts) == 4 and parts[:2] == ["api", "projects"] and parts[3] == "team":
    self._send_json(hierarchy.save_team(parts[2], body))
```

`PUT /api/projects/<name>/team` reaches `hierarchy.save_team`, and it sits in
the *effects* handler, so it is already on the policy-guarded side of the seam.
The read side is live too: `daedalus/core.py:100` normalises `active_agents`,
`core.py:302/327` uses it to pick agents, and `build.py:526-539` uses
`max_workers`/`active_agents` for wave sizing and routing. [MEASURED]

**No surface calls it.** `apps/web/src/**` contains zero occurrences of
`max_workers`, `active_agents`, `default_lane`, or `projects/<n>/team`
(ripgrep, case-insensitive, whole subtree). The live extension has none either
— the strings survive only inside the commented-out `legacyDashboardHtmlSource`
block. [MEASURED]

**What that changes.** This diagnosis framed the fix as "rebuild a
team/environment-controls surface ... wired through the existing backend
contract *if one exists*". It does exist, complete, on both read and write
sides. So the product fork is not "build a feature" versus "drop a feature" —
it is "add a form to the cockpit that calls an endpoint already written" versus
"delete a backend capability nobody can reach". That is a materially cheaper
rebuild than this document assumed, and the owner should be asked in those
terms.

**Owner decision, same day: REBUILD.** Asked in the terms above, the owner
chose to rebuild rather than retire. It landed in the React cockpit as
`apps/web/src/features/settings/Team.tsx` (packet `g1-team-controls`), sourcing
its lane choices and worker ceiling from the hierarchy payload rather than
hardcoding them.

Making the endpoint reachable turned up a second thing this diagnosis had no
reason to look for: `save_team` key-filtered but validated no VALUES, and two
of the three fields are read in ways that turn a bad write into damage rather
than a bad setting. `int(team.get("max_workers", 3) or 3)` in `core.team_config`
raises on a stored `"abc"`, so every read path for that project fails and the
UI cannot undo it because the undo path reads first; `active_agents` is read as
`[str(a) for a in value]`, so a stored string becomes one agent per character.
Every field is validated now, and rejections come back as HTTP 400 with the
field and the reason.

**Test staleness: done, separately.** `tests/test_comms.py` no longer asserts
capabilities against the comment block (packet `g1-ext-honest-tests`, merged as
`e1ad6493`). Needle-by-needle measurement of the two old tests: 3 live / 6
comment / 1 nowhere, and 2 live / 7 comment / 0 nowhere respectively — so the
GREEN one was reading a comment for seven of its nine assertions. The gap this
document describes is now pinned as an explicit measured gap
(`test_team_controls_are_absent_from_the_live_extension`) rather than a red
test, so it stays visible without blocking the suite. The retained legacy block
was NOT deleted: the comment above it records a deliberate decision, and a
test-repair packet does not overrule that.
