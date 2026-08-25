# Amendment proposal 003 — symbol work goes through Serena

Status: **SUPERSEDED HISTORICAL RECORD.** Approved by the repository owner
2026-08-05 and applied in commit `3e758392`. The 2026-08-22 unification
retired the Iron Plan guard entirely, and the Serena-first enforcement hook
this amendment registered was replaced by hooks v2 (2026-08-23). Not current
operating instructions.

Base plan revision: 1. Result revision: 2. Owner: repository owner (@KTY137).
Scope: governance/tooling only — no invariant, prior, gate, or plan sentence
changed.

## What was found

Serena (21 LSP-backed symbol tools) was used rarely. Three causes, only two
in scope for this amendment:

- **Serena reached the session late or not at all** — the configured MCP
  command re-resolved the package over the network on every start; cold start
  measured at 28.35s against a ~30s client timeout, an intermittent race.
  Fixed outside the amendment (`.mcp.json` is not protected): pinned local
  install, direct executable invocation, `context: claude-code`.
- **Nothing stopped the cheaper Grep/Read habit even when Serena was up.**
  Fixed by this amendment: `.claude/hooks/serena-first.py`, registered in the
  protected `.claude/settings.json`, denied a declaration-shaped `Grep` and an
  un-scoped `Read` of a file over 120 lines while Serena was reachable,
  redirecting to `find_symbol` / `get_symbols_overview`. Fail-open by
  construction — denies nothing once Serena is unreachable, and
  `DAEDALUS_SERENA_HOOK=off` was an unconditional escape.
- **No written rule said symbol work goes through Serena.** Fixed by adding a
  "Symbol work goes through Serena" section to `AGENTS.md`, explicit that this
  is a cost/recall rule, not a safety rule.

Evidence at approval time: 14 tests / 24 subtests passing
(`tests/test_serena_first_hook.py`), 4/4 deliberate mutations caught
(reachability check, Read rule, line threshold, env escape hatch each
independently confirmed load-bearing).

Also recorded, not part of this amendment: the guard denied read-only
inspection (`Grep`, `git status`) of protected paths, contradicting Gate 0's
"fail-open read-only inspection" exit criterion. Never separately resolved
before the guard was retired.

## Why it is superseded rather than merely old

The mechanism it registered (`tools/iron_plan_guard.py`'s `settings.json`
hook block) and the file it enforced through no longer exist; the 2026-08-23
hooks v2 rewrite (see `docs/superpowers/specs/2026-08-23-hooks-v2-design.md`)
is a different implementation of the same intent, not a continuation of this
one.
