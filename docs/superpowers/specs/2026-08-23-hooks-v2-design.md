# Hooks v2 — attention-budgeted context hooks for the Claude Code workflow

Date: 2026-08-23 · Author: Athena (coordinator) · Status: BUILT 2026-08-23 (Codex round 1 on the design, round 2 on the implementation; see §9/§10)
Classification: ALIGNED (workflow tooling; no kernel contract, no policy
artifact, no promotion path touched). Gate 0 stays active.
Research appendix: `docs/research/HOOKS_CONTEXT_RESEARCH_2026-08-23.md`.

## 0. One-paragraph summary

Every hook output is a set of key/value pairs that competes with the task for
the model's attention. Two properties of the transformer transfer literally to
hook design (softmax competition: every injected token competes with task tokens for
attention mass — degradation measured even for whitespace padding; positional U-bias: the cached prefix and
the most recent turn are attended, the middle is not). Today's hooks violate
both: four separate processes inject a static block every turn from the WRONG
repository, one of them counts the crew wrongly, and nothing tells a session
or subagent which tree it stands in. Hooks v2 consolidates the per-turn hooks
into one process per event, resolves the repository from the hook payload
(never from `__file__`), injects deltas instead of repeats, measures its own
injection cost in a ledger, and adds the one orientation card that would have
prevented the 2026-08-22 wrong-worktree incident.

## 1. Measured defects (this session, 2026-08-23)

| # | Defect | Evidence |
| --- | --- | --- |
| D1 | User-level hooks point by absolute path at `agent_env/` (archived tree); `shift_hook.py`/`arch_hook.py`/`stream_hook.py` resolve the repo from `__file__` | `~/.claude/settings.json`; the shift line shown in a session ("22h left, goal: Baustellen…") comes from `agent_env/runs/shift.json`; `agent_env_g0/runs/shift.json` does not exist |
| D2 | `serena-first.py` runs twice per Read/Grep (user entry with absolute path + project entry with `${CLAUDE_PROJECT_DIR}` — textually different, so no dedup) | both settings files; docs: "same handler in more than one settings file runs once" — only if identical |
| D3 | `crew_hook.py` counts the newest `tasks/` dir under `%TEMP%/claude`, not this session's; reported 1/3/0 live while 3 scouts were running | three consecutive UserPromptSubmit outputs vs. Agent tool state |
| D4 | `runs/arch_memory.shown` and `runs/council/room.md` are tracked and rewritten every turn → permanent dirty status in both trees | `git ls-files`, `git status` |
| D5 | Room mirror (`stream_hook.py`) runs every turn regardless of whether a room is open | no switch in `stream_hook.py` except a test-only dir override |
| D6 | No SessionStart hook since the iron guard retired; no tree identity reaches a session or subagent | `agent_env_g0/.claude/settings.json` hooks = PreToolUse serena-first + PostToolUse docs-drift only |
| D7 | CREW block (4 lines, identical) every turn; ARCHITECTURE "unchanged" line every turn | this transcript |

## 2. Design principles (each tied to evidence in the appendix)

- **P-budget**: per-injection cap 1,500 chars (turn text, subagent card 600)
  and ≤ 600 chars on a common turn (doc cap is 10,000; claudekit warns > 9,000). Measured, not hoped:
  every hook appends `{chars, ms}` to a ledger.
- **P-delta**: state that rarely changes (architecture, crew targets, tree
  identity) is injected on change only. Silence means "unchanged"; the
  SessionStart card says so once, so silence is readable.
- **P-position**: the orientation card goes to the primacy slot (SessionStart,
  re-seeded on `compact`/`resume`/`fork`); the goal line to the recency slot
  (UserPromptSubmit). Nothing load-bearing is injected mid-history.
- **P-mechanical over textual**: rules that can be a deterministic check leave
  the text channel (serena tree-mismatch guard is a PreToolUse deny, not a
  reminder; "N files edited since the last test run" is a measurement, not a
  "remember to test" line).
- **P-one-process**: one Python process per event (SessionStart,
  UserPromptSubmit, PreToolUse, PostToolUse, SubagentStart/Stop, ConfigChange)
  instead of four per prompt. Measured afterwards: the effect-boundary start,
  not the Python start, is the dominant fixed cost per hook (§6.2).
- **P-right-tree**: the repository is `payload["cwd"]`'s git toplevel, with
  `CLAUDE_PROJECT_DIR` as fallback; never `__file__`.
- **P-fail-open, log-loud**: a hook never breaks a turn (exit 0 on any error),
  but every invocation is one row in `runs/hooks/ledger.jsonl` (rotated) with
  its decision in the `note` field.
- **P-no-guard-revival**: nothing here enforces the plan; the owner retired
  that on 2026-08-22. The only deny is the Serena wrong-tree write guard, which
  protects the owner's files from a measured defect, not the plan from the
  owner.

## 3. Architecture (as built)

```text
daedalus/hooks/                   one package, one process per event
  __init__.py     rationale (why one process, what a hook may say, effect boundary)
  __main__.py     dispatcher: python "${CLAUDE_PROJECT_DIR}/daedalus/hooks/__main__.py" <event>
                  begin_effect inline in main (registry row daedalus.hooks); ledger row per call
  _common.py      payload, repo root from payload cwd (git toplevel) -> CLAUDE_PROJECT_DIR -> cwd,
                  session id sanitiser, locked atomic state, ledger (1 MB rotation), budget trim
  _tree.py        tree facts (branch, HEAD, dirty summary excl. runs/hooks, archive tag,
                  configured Serena root from .mcp.json), source fingerprint (numstat + untracked)
  events.py       session (card), turn (CLOCK, ARCH delta, CREW, CHANGED, CONFIG),
                  subagent_start (tree card to the subagent) / subagent_stop, config_change
  tools.py        pre_tool (Serena advise|deny|off; Serena wrong-tree WRITE deny),
                  post_tool (test-run fingerprint, docs-drift reminder on git commit)
~/.claude/hooks/                  user-global, repo-independent
  orient.py + roots.json          SessionStart + CwdChanged: "ROOT: live tree" / "ROOT: ARCHIVED tree"
  statusline.py, notification_toast.py   copies of .claude/proposals/* (source of truth stays in the repo)
```

Events registered in `agent_env_g0/.claude/settings.json` (all repo-relative):
SessionStart (`startup|resume|clear|compact|fork`), UserPromptSubmit, PreToolUse
(`Read|Grep|mcp__serena__.*`), PostToolUse (`Bash`), SubagentStart, SubagentStop,
ConfigChange, PreCompact (vault audit line, unchanged script). No Stop hook.

User-level `~/.claude/settings.json` after migration: SessionStart + CwdChanged
(orient), Notification (toast), statusLine. Removed there: stream_hook (user +
Stop), shift_hook, arch_hook, crew_hook, serena-first, PreCompact -- all of which
pointed at the archived tree. Backup: `~/.claude/settings.json.bak-2026-08-23`.

Deleted from the repo: `daedalus/shift_hook.py`, `arch_hook.py`, `crew_hook.py`,
`.claude/hooks/serena-first.py`, `.claude/hooks/docs-drift-reminder.py` (their
rationale lives in the package docstrings). `runs/arch_memory.shown` is untracked
and ignored; the per-session cursor is `runs/hooks/arch-<session>.shown`.

### 3.1 Effect boundary

Registry row `daedalus.hooks`: surface CLI, target `daedalus.hooks.__main__:main`,
effects `FILESYSTEM_WRITE, PROCESS_SPAWN, NETWORK_EGRESS`, guard
`budget.process_guard`, anchor `begin_effect` inline in `main`. Conformance: no
blocker for the package; one `review`-level `entrypoint.not_rediscovered`
(cross-module sinks, same class as `tools.guarded_call`). The ledger/state
writer is declared in `envelope.UNCONVERTED_PRODUCERS` as harness
instrumentation keyed by the harness session id.

### 3.2 What each event emits

- **session** (primacy slot): `TREE: <name> | <branch> @<head8> | dirty: N files (top dirs) | configured serena root: this tree / != this tree -> Serena WRITE tools denied`; `ARCHIVED TREE (<tag>)` when applicable; `SHIFT: <shift.render()>`; `DOCS: last mnemosyne sweep at <sha> (<n> commits since)`; the legend `HOOKS v2: silence = unchanged (ARCH, CREW). CHANGED = source tree differs from the last recorded test run. Ledger: runs/hooks/ledger.jsonl`. ASCII only; no clock except the SHIFT line. Measured: 341 chars.
- **turn** (recency slot): shift line (always, the clock); ARCH delta only when changed (first showing is the full block, trimmed to 1,500); `CREW: n live (hook-tracked, min 4): <types>` only when below minimum or changed, the targets line once per session; `CHANGED since last test run (HH:MM, cmd): n source files -- paths` or `CHANGED since session start, no test run recorded: ...`; `CONFIG changed during this session: ...` once. Measured: 60-540 chars after the first turn.
- **pre_tool**: Serena advise (additionalContext, once per file/pattern per session, only when Serena's port answers) / deny / off via `DAEDALUS_SERENA_HOOK`; Serena WRITE tools denied on configured-root mismatch regardless of mode.
- **post_tool** (Bash only): successful test command (regex on the command head) stores the source fingerprint + command + time; `git commit` (not `--dry-run`) returns the docs-drift reminder as additionalContext.
- **subagent_start**: tree card (<= 600 chars) as additionalContext to the subagent, plus the "Serena read tools only" line on mismatch; the agent joins the live set. **subagent_stop** removes it. **config_change** queues one line for the next turn.

## 4. Out of scope (deliberately)

- Any hook that blocks Stop (loop hazard #55754; the owner's mission order on
  2026-08-22 forbade test runs until the final hour — a test-demanding Stop
  hook would fight a direct owner order).
- Prompt/agent-type hooks (a model call per turn is the opposite of the budget
  principle); HTTP hooks.
- Re-introducing any plan/constitution guard.
- Changing CLAUDE.md/AGENTS.md content (the appendix flags that the full master
  plan in the cached prefix is itself the "large static block" anti-pattern;
  that is an owner decision, recorded as a recommendation in §7).

## 5. Testing (`tests/test_hooks_v2.py`, 44 tests, all green 2026-08-23)

- repo root resolves from payload `cwd` (tmp git repo), falls back to
  `CLAUDE_PROJECT_DIR`, never to `__file__`.
- orientation card is byte-identical for identical repo state (cache
  stability) and flags an archived tree / serena mismatch from fixture
  `.mcp.json` + tags.
- crew count uses the session's own tasks dir; stale dir → `≤N`; targets shown
  once.
- ARCH prints nothing when unchanged.
- EDITS tracking: Edit under `daedalus/` adds; docs edit does not; pytest Bash
  clears; failed pytest does not clear.
- budget trim order and `trimmed` ledger note.
- serena tree-mismatch: deny only for write tools, only on mismatch, fail-open
  when `.mcp.json` is absent.
- every hook exits 0 and prints nothing on malformed stdin.
- ledger row shape; rotation at the cap.
- effect boundary: `daedalus.hooks` row present, anchors resolve, conformance
  report has no blocker for the package.

## 6. Verification in proportion to risk (results)

1. `python -m pytest tests/test_hooks_v2.py tests/test_registry_new_doors.py -q` -> 53 passed (2026-08-23 12:50Z). `tests/test_effect_boundary.py` and `tests/test_envelope_coverage.py` carry pre-existing failures at HEAD that are not this change (`daedalus.providers.ollama:OllamaProvider.rollback` effect drift at c0625eac; seven undeclared producers in gate1.py, promotion_trust_root.py, ollama.py, runs/...) -- reported to the lane that owns them.
2. Latency, MEASURED on this box (median of 7, fake payload): old `crew_hook.py` **7,664 ms**, `shift_hook.py` 152 ms, `arch_hook.py` 187 ms, `stream_hook.py` 349 ms -> ~8.3 s per prompt. New: `turn` 240-410 ms, `session` 740-850 ms, `pre_tool` 74-90 ms, `subagent_start` ~500 ms (git). Python start alone: 75 ms. Fixed cost breakdown (quiet box, python start 75 ms): importing the effect boundary + budget ~150 ms, `begin_effect` for this row ~240 ms cumulative -- the kernel rule, not the Python start, is the dominant per-hook cost. A second timing at 13:30Z under load (python start 224 ms, 111 python/node processes) came out ~3x higher across the board and is NOT reported as the number.
3. Empirical hook-visibility probe via `claude -p` in `agent_env_g0` (haiku, then sonnet): the SessionStart card arrives (both layers; user-level `ROOT:` line first, then `TREE:` ...); the subagent quoted the `TREE:` card verbatim (SubagentStart additionalContext confirmed); the PreToolUse advise was emitted (ledger `serena-advise`, 341 chars) -- its text was not captured in the model's reply, so "the model sees the advise" is UNVERIFIED; probe 2 exposed and fixed a false negative in `transcript_mentions` (the deferred-tool list shares the first JSONL line with the prompt).
4. Orientation: `orient.py` with the live cwd prints `ROOT: live tree (agent_env_g0)`, with the archived cwd prints the ARCHIVED line naming the live root, with an unlisted dir prints nothing (measured).
5. Chars per turn before/after: before ~640 chars/turn of which ~520 repeated verbatim (shift 253 + crew 417 + arch 44, this transcript); after: 60 chars on a quiet turn (clock only), 341 once at session start, the ARCH block once (first showing).

## 7. Recommendations that need the owner (not done here)

- R1: the `@docs/IKARUS_ARIADNE_MASTER_PLAN.md` import in CLAUDE.md puts ~3,000
  words into every cached prefix (and every subagent's). Evidence says long
  static instruction blocks get ignored as a whole. Option: keep the plan as a
  file the SessionStart card points to, import only AGENTS.md.
- R2: `runs/council/room.md` is tracked but is a live transcript; decide
  whether it stays a record (then commit it deliberately) or becomes ignored.
- R3: MIN_PARALLEL=4 as a standing order vs. the token-discipline complaint —
  the hook now measures honestly; the number to demand is the owner's call.

## 9. Review round 1 — Codex (codex-cli 0.146.0, read-only sandbox, 2026-08-23 12:00Z)

Verdict: BUILD-WITH-CHANGES. Each point, with what was verified and what the
design now does. Transcript: scratch `athena-codex-review-1.out` (quoted
verbatim in the commit's docs, not re-summarised).

| Codex point | Verified? | Resolution |
| --- | --- | --- |
| B1 serena-first denies Read/Grep; `AGENTS.md` review rules (owner, 2026-08-22) name "a guard that blocks reading or measuring" release-blocking | TRUE — `AGENTS.md:60`. The same owner kit added the hook (amendment 003 harvest), so the owner's two artefacts conflict | Mode switch `DAEDALUS_SERENA_HOOK=advise|deny|off`, default `advise`: the Read/Grep call is ALLOWED and a one-line Serena nudge is attached as `additionalContext`, once per file/pattern per session. `deny` restores amendment-003 behaviour. The wrong-tree Serena WRITE guard stays a deny (it blocks writing, not reading). Owner decision R4 below. |
| B2 one registry row for six mains under-declares effects (git spawn, loopback probe) | TRUE | One real dispatcher `daedalus/hooks/__main__.py` (`main(argv)`, event = argv[1]); one row `daedalus.hooks` with `FILESYSTEM_WRITE, PROCESS_SPAWN, NETWORK_EGRESS`, guard `budget.process_guard`, `begin_effect` before any git/socket/write. |
| B3 the ARCHIVED warning cannot fire: SessionStart is only registered in g0, and the archived HEAD (6225d3e4) is not the tagged commit (b25cc340) | TRUE (both measured) | Orientation becomes a **user-level** hook `~/.claude/hooks/orient.py` with an explicit `~/.claude/hooks/roots.json` (`live`/`archived` lists), registered on `SessionStart` and `CwdChanged`. The tag is a secondary signal only. The repo-level card keeps the repo facts (branch, HEAD, dirty lanes, serena root). |
| B4 room mirroring has no valid ownership path (stdin consumed, `__file__` paths, boundary bypass) | TRUE | Room mirroring is OUT of v2. The user-level Stop/UserPromptSubmit `stream_hook` entries (archived tree) are removed; the `room` skill gets the job of wiring its own mirror in a later design. |
| B5 EDITS can assert a false "tested" state (Serena/Bash/other-agent writes; `echo pytest`) | TRUE | Fingerprint, not tracking: at a successful test command (regex on the command head: `pytest`, `py.test`, `python -m pytest|unittest`, optionally after `cd … &&`), store `sha256(git diff HEAD -- daedalus tools tests scripts)` + the exact command. Per turn: `CHANGED since last test run (HH:MM, cmd)` when the fingerprint differs. Never says "tested". |
| W1 no locking on shared state | TRUE | Lock file (`O_CREAT|O_EXCL`, 2 s, stale > 30 s broken) + `os.replace`; race test with 8 processes. |
| W2 `.mcp.json` proves the configured root, not the live server's | TRUE | Wording: "configured serena root". |
| W3 timestamp in the SessionStart card | TRUE | Sweep shown by HEAD only; no clock in the card. |
| W4 `arch_memory.render_delta` owns a global cursor and prints "unchanged" | TRUE | `render_delta(root, shown_path=…)` gains a parameter; cursor lives in `runs/hooks/`; "unchanged" → empty string. `runs/arch_memory.shown` untracked. |
| W5 user-settings migration is not an acceptance gate | TRUE | `tests/test_hooks_v2.py::test_no_archived_paths_in_effective_hooks` parses both settings files on this machine (skipped elsewhere). |
| U1 "every token displaces" overstates | fair | §0 wording softened to "competes with". |
| U2 SubagentStart `additionalContext` is documented (2.1.233) | accepted (Codex cites the reference) | `subagent_start` event kept; still verified empirically via `claude -p`. |
| U3 10,000-char cap spills to a file, not a cut | TRUE (docs quoted) | Appendix E corrected. |
| U4 `tool_response.is_error` is not generic; failures go to `PostToolUseFailure` | accepted | post_tool treats `PostToolUse` as success; failed pytest (non-zero exit → failure event) therefore never clears the fingerprint — the desired behaviour. |
| U5 stream_hook prints stderr on refusal | TRUE (`stream_hook.py:466-470`) | Wording fixed. |
| D1 delete compatibility shims | accepted | Old scripts deleted, rationale moved into the package docstrings; `shift_ticker.py` docstring updated. |
| D2 delete the bare clock when no shift is declared | REJECTED | The clock is the reason `shift_hook` exists (2026-07-30: an agent announced 10:00 at 03:10). 7 chars. |
| D3 statusline ledger segment until the ledger is proven | accepted | Deferred to v2.1. |
| D4 room mirroring | accepted | see B4. |
| D5 `hooks.log` duplicate | accepted | Ledger only; a `note` field carries decisions. |
| M1 `CwdChanged` orientation | accepted | see B3. |
| M2 `SubagentStart/Stop` lifecycle instead of `%TEMP%` mtime | accepted — and measured: the mtime scan costs **7.7 s per prompt** (median of 7) over 129,434 files | CREW = live set maintained by `subagent_start`/`subagent_stop` in session state (entries pruned after 2 h); no directory scan. |
| M3 `ConfigChange` audit | accepted | `config_change` event appends a ledger row and the next turn prints `CONFIG: <source> changed (<path>)`. |
| M4 tests: race, `session_id` path traversal, settings union, Bash/Serena writes, partial tests | accepted | in §5. |

**R4 (owner):** keep `advise` as the default for the Serena read nudge, or set
`DAEDALUS_SERENA_HOOK=deny` in `.claude/settings.json` `env` to restore the
amendment-003 deny. The design ships `advise` because the newer owner artefact
(`AGENTS.md`, 2026-08-22) is explicit and the older one is a harvest.

## 10. Review round 2 — Codex on the implementation (2026-08-23 13:10Z)

Verdict as given: DO-NOT-SHIP ("core change detection and two harness contracts
are wrong, while production-callable and arbitrary-path write seams bypass the
claimed Gate-0 boundary"). Every point checked; what changed:

| Codex point | Verified? | Resolution |
| --- | --- | --- |
| B1 ConfigChange fields are `source`/`file_path`, not `config_source`/`config_path` | two references disagree (the hooks scout quoted the latter) | accept both spellings; test covers both |
| B2 numstat fingerprint misses `x=2 -> x=3` after a test run | TRUE (reproduced as a test) | content-exact: one `git diff HEAD` split per file and hashed, untracked files hashed by content; test `test_changed_detects_same_line_count_edits_after_a_test_run` |
| B3 malformed stdin becomes `{}` and the turn still runs, writing `state-unknown.json` | TRUE | `payload_is_usable` gate (needs `hook_event_name` + `cwd`); nothing printed, nothing written; test asserts both |
| B4 `CwdChanged` has no context channel; `systemMessage` is user-facing | plausible, UNVERIFIED either way | claim downgraded: on `CwdChanged` the orient line is a user-facing message plus a best-effort `additionalContext`; the model is re-oriented at the next SessionStart |
| S1 `run()` is an effectful seam callable without `begin_effect` | TRUE | renamed `dispatch(event, payload, receipt)`; refuses without the `daedalus.hooks` receipt (`PermissionError`); tests obtain a real receipt via `start_effect()`; test `test_dispatch_refuses_to_run_without_the_effect_receipt` |
| S2 `render_delta(shown_path=...)` can write anywhere | TRUE | confined to the repository; `ValueError` otherwise; test |
| S3 `budget.process_guard` does not cover `socket`/file writes | TRUE, and the same for every registered row that writes files (e.g. `runs.council.stream_hook`) — the contract set is the registry's, not this change's | noted in the row; `orient.py` lives outside the scanned tree by design (user config) |
| W1 two stale-lock breakers can unlink each other's fresh lock | TRUE | break by atomic `os.replace` to a per-pid name, then unlink; test with 6 processes |
| W2 `UnboundLocalError` when the import fails before `EffectBoundaryError` is bound | TRUE | single broad `except` around import + start; `start_effect()` packages it for tests |
| W3 `orient.py` locale decoding | TRUE | `encoding="utf-8", errors="replace"` |
| W4 `TEST_COMMAND` misses quoted `cd`, `py -m`, case variants | TRUE | regex extended, `IGNORECASE`; four more cases in the table test |
| W5 `orient.py` crashes on non-list/non-dict roots | TRUE | shape-checked; verified with `{"live": [], "archived": []}` and `{"live": "x", "archived": ["a"]}` |
| T1 the 1,500 cap is per injection, not per turn; ledger rows lack `prompt_id` | TRUE | ledger rows carry `prompt`; wording fixed here: the cap is per emitted text |
| T2 envelope text "session id is the only correlator" | TRUE | reworded (prompt id named) |
| T3 `off` docstring vs the write guard staying on | TRUE | docstring says so |
| T4 `pytest \|\| true` reaches post_tool | TRUE | docstring says so and explains why the exact command is recorded |
| T5 CREW targets vs count | wording | `CREW: n subagents live` |

Net after round 2: 62 tests green (`tests/test_hooks_v2.py` 53 + `tests/test_registry_new_doors.py` 9).
Still UNVERIFIED and said so: that the model reads the PreToolUse advise text;
that `CwdChanged` reaches the model at all.

## 8. Rollout

One commit on `main` in `agent_env_g0` for the package + tests + registry +
project settings + docs; the `~/.claude/settings.json` edit landed directly
(backup `settings.json.bak-2026-08-23`; every key other than `hooks` and
`statusLine` byte-identical). The archived tree is not touched: its own
project hooks (serena-first deny, docs-drift) keep running there until it is
left. No recovery kit was needed -- the classifier did not refuse the
`.claude/settings.json` write this time.
