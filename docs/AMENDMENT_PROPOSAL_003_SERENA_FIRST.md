# Amendment proposal 003 — symbol work goes through Serena

Status: **SUPERSEDED HISTORICAL RECORD — do not apply.** The repository owner
approved this proposal on 2026-08-05, and commit `3e758392` applied its
then-current form. The 2026-08-22 unification retired the Iron Plan guard, and
the Serena-first registration was subsequently replaced by hooks v2. The
sections below preserve the proposal and evidence as they were written; they
are not current operating instructions and must not be replayed.

Any renewed change to `AGENTS.md`, the master plan, or owner-managed settings is
a new owner decision recorded under the current manual amendment process.

They cannot be performed in the approving session. The guard's PreToolUse hook
runs as a child of the harness process and reads its environment; exporting the
token inside a shell command does not reach it. Verified: `DAEDALUS_IRON_PLAN_AMENDMENT`
was unset for the approving session. The amendment requires a fresh session
started with the token.

Base plan revision: 1
Base plan sha256: `a47d84ee736fcaebd76f4309f4e0653f536415b9bda9e04940920ca1896026d4`
Proposed result revision: 2
Owner: repository owner (@KTY137)
Scope: `governance` — tooling discipline only. **No invariant, prior, gate, or
plan sentence changes.**

> **Revision collision — resolved.** Amendment proposal 002 also proposes
> revision 2. 003 was approved first (2026-08-05) and therefore takes revision 2.
> **Proposal 002 must be renumbered to result revision 3 before it is applied**,
> and its base sha256 updated to the digest of the revision-2 plan this amendment
> produces — its current base (`a47d84ee…`, the revision-1 plan) will be stale
> the moment this lands.
>
> The two do not conflict in content: 002 touches `tools/iron_plan_guard.py` (removed 2026-08-22) and
> `tests/test_iron_plan_guard.py` (removed 2026-08-22), 003 touches `.claude/settings.json` and
> `AGENTS.md`.

---

## Summary

Serena exposes 21 LSP-backed symbol tools to this repository. They were used
rarely. The owner read this as agent drift from the workflow, which it partly
is — but measurement found a mechanical cause underneath it, and the mechanical
cause is fixed outside this amendment.

| # | Cause | Status |
|---|---|---|
| A | Serena reached the session late or not at all | **fixed, ALIGNED** — no amendment needed |
| B | nothing stopped the cheaper Grep/Read habit | needs a hook registration → protected file |
| C | no written rule said symbol work goes through Serena | needs `AGENTS.md` → protected file |

Only B and C are in scope here. A is recorded because it changes what the rule
in C is allowed to claim.

---

## What was measured

### Serena was absent from the session that reported the problem

The session began at 11:14. `claude mcp list` reported serena `✔ Connected`,
but that health check spawns its own process and says nothing about the session.
Two independent `ToolSearch` queries — one name-filtered (`+serena`), one
semantic (`find symbol references code editing language server`) — returned zero
serena tools while returning playwright, context7, shadcn, and Drive tools
normally.

`~/.serena/logs/2026-08-05/` contained exactly two files, both timestamped
11:15:1x. Both were produced by the health check. **The session never spawned a
serena process at all.**

### Why: startup sat on the timeout boundary

Driving the configured MCP command directly over stdio and timing the
`initialize` round-trip:

```
[MEASURED] cold (first run after install):   28.35 s
[MEASURED] warm (3 consecutive runs):         2.95 s / 3.13 s / 3.02 s
```

Cold start is 28.35 s. The MCP client's startup timeout default is **30 s**
[ASSUMED — taken from the documented default, not measured in this harness].
After a boot or a long idle the OS file cache is cold, which is precisely when a
new session starts. Serena was losing a race it won most of the time — the
signature of an intermittent absence, and indistinguishable from "this tool does
not exist" from inside the session.

The old command re-resolved the package over the network on every start:

```
"command": "uvx",
"args": ["--from", "git+https://github.com/oraios/serena", "serena", ...]
```

### Fixed already, without an amendment

`.mcp.json` is not a protected artifact, so cause A was repaired as ordinary
`ALIGNED` work:

- `uv tool install git+https://github.com/oraios/serena` — local pinned install
  (serena-agent 1.6.2.dev0), no network resolution at startup;
- `.mcp.json` now invokes `C:/Users/nukei/.local/bin/serena.exe` directly;
- context `ide-assistant` → `claude-code`; the old name is deprecated and was
  emitting a WARNING on every start.

Verified by stdio handshake: `initialize` OK, `tools/list` → 21 tools.

**This does not remove the margin.** A local install still pays interpreter
startup and package import. Raising `MCP_TIMEOUT` is the part that needs this
amendment, because `.claude/settings.json` is protected.

---

## Point B — register the enforcement hook

### Why a hook and not an instruction

Cause C alone would be an instruction, and an instruction is what already failed:
the plan, `AGENTS.md`, and five lifecycle hooks were all active during the
sessions in which the drift occurred. The cheap habit wins whenever nothing
stops it. §1 is explicit that a prompt is not a boundary.

The hook is additive. It weakens no existing guard, touches no protected content,
and runs alongside the Iron Plan hook rather than in place of it.

### The artifact

`.claude/hooks/serena-first.py` (replaced by daedalus/hooks/, 2026-08-23) — **already written and tested; not yet
registered.** `.claude/hooks/` is not protected, so the script itself is ordinary
work. Only the `settings.json` line that arms it is protected.

Denies exactly two things, and only while Serena is reachable:

| Denied | Redirected to |
|---|---|
| `Grep` whose pattern names a declaration keyword (`def`, `class`, `function`, `interface`, `struct`, `enum`, `fn`, `trait`) | `find_symbol`, `find_referencing_symbols` |
| `Read` of a source file over 120 lines with no `offset`/`limit` | `get_symbols_overview`, then `find_symbol` |

### Fail-open by construction

The hook probes Serena's dashboard port and **denies nothing when Serena is
down.** This is the load-bearing design decision, and it is a direct consequence
of proposal 002 point B: a guard whose failure mode is "no symbol lookup is
possible at all" is a defect, not a protection. If Serena is unreachable, every
Grep and Read passes untouched.

Four graded escapes, narrowest first:

1. targeted reads (`offset`/`limit`) always pass;
2. files at or under 120 lines always pass;
3. a full `Read` passes once any Serena tool has touched that file this session
   — the "overview first, then read" order, not a ban on reading;
4. `DAEDALUS_SERENA_HOOK=off` disables the hook entirely.

### Proposed diff — `.claude/settings.json`

```diff
   "env": {
-    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
+    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
+    "MCP_TIMEOUT": "120000"
   },
```

```diff
     "PreToolUse": [
       {
         "hooks": [
           {
             "type": "command",
             "command": "python \"$(git rev-parse --show-toplevel)/tools/iron_plan_hook_runner.py (removed 2026-08-22)\" || exit 2",
             "timeout": 10,
             "statusMessage": "Guarding the Iron Plan..."
           }
         ]
+      },
+      {
+        "matcher": "Grep|Read",
+        "hooks": [
+          {
+            "type": "command",
+            "command": "python \"${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/serena-first.py (replaced by daedalus/hooks/, 2026-08-23)\"",
+            "timeout": 10,
+            "statusMessage": "Routing symbol work through Serena..."
+          }
+        ]
       }
     ],
```

`MCP_TIMEOUT` at 120 s gives the 28.35 s cold start a 4× margin. It cannot mask
a failure: a server that never answers still fails, only later.

### Alternatives considered

- **Reminder instead of deny.** Offered to the owner and rejected in favour of
  blocking. A reminder is ignorable, and being ignorable is the reported problem.
- **Raise `MCP_TIMEOUT` only, no hook.** Also offered and rejected. It fixes
  availability and leaves the habit. Worth noting it would have been the
  measurement-first choice; the owner chose enforcement directly.
- **Deny `Read` of source files outright.** Rejected: whole-file reading is
  correct often enough (short modules, unfamiliar structure, review) that a flat
  ban would trade one bad default for another.
- **Detect drift after the fact and report it.** Rejected: a `PostToolUse`
  observation cannot un-spend the tokens it observed.

---

## Point C — write the rule down

### Why write it at all, given the hook

The hook enforces at one interface. The rule states the intent, survives the
hook being off, and applies to subagents whose tool access differs. It must
claim no more than the hook delivers — in particular it must not promise
enforcement that a session without Serena cannot provide.

### Proposed diff — `AGENTS.md`

Inserted after the `## Mandatory workflow` section, before
`## Non-negotiable boundaries`:

```diff
+## Symbol work goes through Serena
+
+When Serena is reachable, resolve symbols with it rather than by text search:
+`get_symbols_overview` before reading an unfamiliar source file,
+`find_symbol` instead of grepping for a declaration, `find_referencing_symbols`
+instead of guessing at call sites. Reach for `Grep` when you want text and for a
+whole-file `Read` when you have already seen the file's shape.
+
+This is a cost and recall rule, not a safety rule. `.claude/hooks/serena-first.py`
+enforces it at the Grep/Read boundary and deliberately enforces nothing when
+Serena is down; that hook is not a boundary in the §1 sense. When Serena is
+unavailable, text search is the correct tool and no rule is being bent.
+
```

### Alternatives considered

- **Put it in `CLAUDE.md` instead.** `CLAUDE.md` is equally protected, and it is
  a four-line loader; the constitution is the right home for a working rule.
- **State it as an invariant in §4 of the plan.** Rejected as overreach. This is
  a tooling preference that a future language server change could obsolete.
  §4 invariants require an amendment to move; this should not.

---

## Affected invariants and priors

None. §4 invariants 1–10 are untouched; no gate definition, kill criterion, or
research prior changes. Invariant 10 is the reason this is an amendment rather
than a fix: the two files are protected, so the change is recorded even though
the plan's meaning does not change.

## Migration

None. No stored artifact, receipt, ledger record, or event changes shape. The
hook and its tests are additive. `.mcp.json` and the local Serena install are
already in place and are not part of this amendment.

## Rollback

Remove the `Grep|Read` entry from `PreToolUse` and the `AGENTS.md` section; the
hook script may stay on disk unarmed. `DAEDALUS_SERENA_HOOK=off` is an immediate
runtime rollback that needs no amendment. Per §15, a recorded rollback is a new
amendment, never a history rewrite.

## Evidence

Already produced:

1. `python -m pytest tests/test_serena_first_hook.py -q`
   → **[MEASURED] 14 passed, 24 subtests passed**. Covers both deny paths, all
   four escapes, malformed payloads, missing files, and unrelated tools.
2. Mutation check — four deliberate breaks, each run against the suite:

   ```
   [MEASURED] CAUGHT  reachability check removed (always enforce)
   [MEASURED] CAUGHT  Read rule disabled
   [MEASURED] CAUGHT  line threshold ignored
   [MEASURED] CAUGHT  env escape hatch removed
   ```

   The first line is the important one: if the hook ever stops checking whether
   Serena is reachable, the suite fails.
3. Serena stdio handshake against the new `.mcp.json` command → `initialize` OK,
   21 tools.
4. `python tools/iron_plan_guard.py (removed 2026-08-23) verify` → OK.

Required before acceptance, and **not yet done** because they need the amended
`settings.json` live:

5. A session started with the hook armed: a definition-shaped `Grep` is denied,
   the denial names `find_symbol`, and the subsequent Serena call succeeds.
6. The same session with Serena stopped: the identical `Grep` passes.
7. `python -m pytest tests/ -q` → no new failures against the pre-amendment
   baseline.

---

## Recorded, not proposed: the guard denies read-only tools

Observed while preparing this proposal; **not part of this amendment.**

Two read-only inspections were denied. First a `Grep` over
`tools/iron_plan_guard.py (removed 2026-08-22)`:

```
Protected Iron Plan artifact(s) cannot change in ordinary work:
tools/iron_plan_guard.py (removed 2026-08-22). Follow the owner-approved amendment protocol.
```

Then, while gathering evidence for this proposal, a `git status`:

```
$ git status --short tests/test_iron_plan_guard.py (removed 2026-08-23) tools/iron_plan_guard.py \
      docs/IKARUS_ARIADNE_MASTER_PLAN.md
Protected Iron Plan artifact(s) cannot change in ordinary work:
tests/test_iron_plan_guard.py (removed 2026-08-23), tools/iron_plan_guard.py,
docs/IKARUS_ARIADNE_MASTER_PLAN.md. Follow the owner-approved amendment
protocol.
```

`git status` is a pure query — it is the command one runs *to check whether a
protected file changed*. Denying it means the guard refuses the very inspection
that would confirm the guard's own invariant holds. Note also that the bare
`git status --short` over the whole repository passes; naming the paths
explicitly is what trips it, which is the same risk inversion as proposal 002
point C2 (`git add -A` allowed, `git add docs/` denied).

Gate 0's exit criterion requires "fail-closed protected effects and **fail-open
read-only inspection**". `Grep` mutates nothing. The guard appears to match
protected paths in `tool_input` without distinguishing a reading tool from a
writing one, which makes the protected artifacts unreadable by the narrow tools
while `Read` and `Bash` alternatives may still reach them — protection that
costs inspection without buying containment.

This is adjacent to proposal 002 point C (paths guessed from command text) but
distinct: 002 fixes *which strings count as paths*, this concerns *which tools
should be path-checked at all*. It is amendment-shaped, belongs in its own
proposal, and is recorded here so it is not lost.
