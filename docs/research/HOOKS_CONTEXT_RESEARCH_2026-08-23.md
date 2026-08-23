# Hook & context-engineering research — 2026-08-23

Provenance: three read-only research scouts (web), collected by the coordinator
for `docs/superpowers/specs/2026-08-23-hooks-v2-design.md`. Every claim carries
the URL the scout read it from and an evidence stamp: MEASURED (a number from
an experiment), REPORTED (vendor/practitioner statement), METAPHOR (no
evidence, an analogy). Secondary summaries are marked as such.

## A. Principles that bear on what a hook should inject

| # | Principle | Evidence | Source | Hook implication |
| --- | --- | --- | --- | --- |
| P1 | Context is a finite attention budget; length itself degrades performance, even with perfect retrieval and even for whitespace padding | MEASURED (18 models incl. Claude Opus 4/Sonnet 4; 13.9–85 % loss with perfect retrieval) | https://www.trychroma.com/research/context-rot · https://arxiv.org/abs/2510.05381 · https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents | every injected token must justify itself against the task tokens it displaces |
| P2 | Primacy/recency are attended; the middle is lost; the U-bias is intrinsic to attention, not instruction tuning | MEASURED (>20 pp drop GPT-3.5; U-shape in base and instruct MPT-30B; calibration recovers up to 15 pp) | https://ar5iv.labs.arxiv.org/html/2307.03172 · https://arxiv.org/abs/2406.16008 | the two slots that work are the cached prefix (SessionStart) and the latest turn (UserPromptSubmit); mid-history injections are wallpaper by construction |
| P3 | Restating the query/goal after the data fixes retrieval, not reasoning | MEASURED (near-perfect KV retrieval; "minimally affects" multi-doc QA) | https://ar5iv.labs.arxiv.org/html/2307.03172 | a late one-line goal restatement is cheap and helps the model *find* the goal |
| P4 | Recitation of the relevant evidence late in context converts a long task into a short one | MEASURED (+≤4 % on RULER) / REPORTED (Manus todo.md) | https://arxiv.org/abs/2510.05381 · https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/long-context-tips · https://dev.to/contextspace_/context-engineering-for-ai-agents-key-lessons-from-manus-3f83 | the best per-turn injection is the model's own current plan/evidence, not a static rulebook |
| P5 | Long data at the top, instructions and query at the bottom | REPORTED (vendor) | https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/long-context-tips | SessionStart dumps early, per-turn directives last |
| P6 | Distractors compound; similar-but-wrong material is worse than noise; coherent irrelevant text is worse than shuffled | MEASURED | https://www.trychroma.com/research/context-rot | narrative status injections (old handoffs, adjacent-lane reports) are the most harmful class; a terse table beats a paragraph |
| P7 | Focused context beats full context on the same facts by a wide margin | MEASURED (~300 tokens near-perfect vs ~113k significant drops; Claude 4 shows the largest gaps) | https://www.trychroma.com/research/context-rot | inject the 3 relevant lines, not the file they came from |
| P8 | Multi-turn degradation is mostly unreliability; a single recap recovers ~15–20 pp, repeated bouncing does not | MEASURED (−39 % avg; unreliability +112 %) | https://arxiv.org/html/2505.06120 · https://arxiv.org/pdf/2605.12922 · https://arxiv.org/html/2511.03508v1 | one consolidation (SessionStart on compact) helps; a Stop hook that bounces 8× is wallpaper after the first bounce |
| P9 | Constraint violation under pressure is not forgetting: models restate the rule and break it anyway | MEASURED (knows-but-violates 8–99 % across 7 models) | https://arxiv.org/abs/2604.28031 | repeating a rule every turn attacks the wrong failure; mechanical gates address the right one |
| P10 | Hooks are for what must happen with zero exceptions; a bloated CLAUDE.md gets ignored as a whole | REPORTED (vendor: "If you emphasize many lines, none of them stands out") | https://code.claude.com/docs/en/best-practices | every rule that can be a deterministic check leaves the text channel |
| P11 | Stable prefix, append-only, no timestamps in the prefix: cache is the cost floor (10× cached/uncached) | MEASURED-as-cost | https://dev.to/contextspace_/context-engineering-for-ai-agents-key-lessons-from-manus-3f83 (secondary; Manus original offline) · https://claude.com/blog/lessons-from-building-claude-code-prompt-caching-is-everything | SessionStart output must be deterministic for a given repo state; dynamic facts go to per-turn messages |
| P12 | Mask, don't remove (tool churn invalidates the cache and confuses references) | REPORTED | same Manus summary | PreToolUse deny is the masking equivalent; never rewrite the tool list mid-session |
| P13 | Filesystem as restorable context: keep the pointer, drop the payload | REPORTED | same · https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents | inject paths and one-line summaries; the agent can Read |
| P14 | Keep errors in; they are evidence the next step conditions on | REPORTED | same Manus summary | PostToolUseFailure must not sanitise |
| P15 | Avoid few-shot ruts: uniform repeated observations make the model mimic the pattern | REPORTED | same Manus summary | an identical reminder block every turn is exactly the uniform pattern; gate on state or vary form |
| P16 | Premature termination, not window exhaustion, is how agents fail under long context | MEASURED (4 flagship models, 3 benchmarks) | https://arxiv.org/abs/2606.29718 | a measurement of "what is still open" targets the real failure; "be thorough" text does not |
| P17 | Subagents are context isolation: 10k+ tokens of exploration returning 1–2k; token usage explains 80 % of variance | MEASURED (internal; 90.2 % over single-agent at 15× tokens) | https://www.anthropic.com/engineering/multi-agent-research-system | never echo a subagent transcript into the parent |
| P18 | Tool results are the biggest injection channel; cap and filter them | REPORTED (25k-token truncation; concise format ≈ ⅓ tokens) | https://www.anthropic.com/engineering/writing-tools-for-agents | PostToolUse is where a hook can *remove* bytes |
| P19 | Evolving itemised playbooks beat monolithic rewrites; context collapse is one rewrite away (18,282 tokens/66.7 → 122 tokens/57.1) | MEASURED | https://arxiv.org/html/2510.04618 (ACE) | a memory file a hook injects is appended and pruned by counters, never regenerated wholesale |
| P20 | Curated concise snippets beat transcripts (Dynamic Cheatsheet: GPT-4o Game of 24 10 % → 99 %) | MEASURED | https://arxiv.org/abs/2504.07952 | in tension with P19 — see open questions |
| P21 | Compaction: recall first, precision second; clearing old tool results is the safe minimum | REPORTED | https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents | PreCompact names what must survive; SessionStart(compact) re-seeds |
| P22 | Claude Code channels: SessionStart + UserPromptSubmit stdout become context before the prompt; all injected strings capped at 10,000 chars; Stop can block ≤ 8× | REPORTED (docs) | https://code.claude.com/docs/en/hooks | per-turn hooks sit physically at the recency slot; the cap is a budget, not a target |

## B. "Attention Is All You Need" → hook design, skeptically

Mechanism source: https://arxiv.org/abs/1706.03762

| Transformer property | Transfers literally? | Evidence | Verdict |
| --- | --- | --- | --- |
| Softmax competition (weights sum to 1; more keys → mass spreads) | Yes | MEASURED: degradation even with whitespace padding; α-entmax fixes it by zeroing irrelevant tokens — https://arxiv.org/abs/2510.05381 · https://arxiv.org/pdf/2506.16640 | every injected token competes with the task. Literal. |
| Attention sinks (first tokens take mass regardless of meaning) | Yes, mechanically | MEASURED — https://arxiv.org/abs/2309.17453 | prefix material is "seen", not necessarily used; do not read primacy as comprehension |
| Positional encoding + causal mask → U-shaped bias | Yes | MEASURED — https://arxiv.org/abs/2406.16008 | per-turn injections last; prefix first; nothing load-bearing in the middle |
| Query-dependent weighting (Q·K) | Partly | MEASURED on KV retrieval, negligible on QA — https://ar5iv.labs.arxiv.org/html/2307.03172 | restating the goal late gives the query a key to match |
| Multi-head diversity → "parallel reviewers with distinct lenses" | No — heads share one residual stream, trained jointly, do not vote | METAPHOR; the real analogue is orchestrator–workers with separate contexts (MEASURED 90.2 %) | parallel reviewers are justified by context isolation and variance, not by multi-head attention |
| Residual connections → "keep the original instructions reachable" | No | METAPHOR; the cross-turn analogue is recitation (P4) | — |
| Layer norm → "normalise injected format" | No | METAPHOR; format consistency is justified by P11/P15 | — |
| Recitation/todo.md → re-injecting goals late | Yes, via positional bias + query awareness | MEASURED (P3, P4) | the one mapping where mechanism and agent-level measurement agree |

Net: two properties transfer literally (softmax competition, positional bias
incl. sinks), one partially (query dependence), three are metaphors. The paper
is a reason to *minimise* injection, not a licence to design "heads".

## C. Anti-patterns with evidence

1. Same reminder every turn (P15, P2, P9). No source shows a gain from verbatim per-turn repetition; a recap helped only as a single consolidation (P8).
2. Large static blocks at SessionStart / in CLAUDE.md (P1, P10). The current CLAUDE.md chain (constitution + full master plan) is this pattern.
3. Non-deterministic prefix (timestamps, shuffled tool order) — breaks cache (P11).
4. Removing/adding tools mid-session (P12).
5. Coherent narrative status injections (P6).
6. Monolithic LLM rewrite of a memory/playbook file (P19).
7. Emphasising many lines with IMPORTANT (P10).
8. Stop hook bouncing without a runnable check (P9, P22); issue https://github.com/anthropics/claude-code/issues/55754 — a prompt-type Stop hook looped ~50 min while Claude awaited background subagents, burning the session quota; `stop_hook_active` is advisory only.
9. Echoing full tool output or subagent transcripts into the parent (P17, P18).
10. claude-mem injected a ~40-line static block on every message — complaints: token burn, and "Claude Code treats hook output as user instructions, causing unintended model behavior" — https://github.com/thedotmack/claude-mem/issues/1079

## D. Hook pattern catalogue (practice, 2025–2026) — entries rated for this repo

| Pattern | Event | Evidence | Fit |
| --- | --- | --- | --- |
| SessionStart "git status + TODO" (Anthropic's canonical example) | SessionStart | https://claude.com/blog/how-to-configure-hooks · https://code.claude.com/docs/en/hooks | HIGH |
| Inject context after the tool that needs it, not every prompt | PostToolUse (Edit/Write) | https://www.augmentedswe.com/p/guide-to-claude-code-hooks | HIGH |
| Per-turn recitation of priorities, small payload (<1 KB, idempotent) | UserPromptSubmit | https://claude.com/blog/how-to-configure-hooks | MED |
| PreCompact save → PostCompact/SessionStart(compact) re-inject a delta, not the dump | PreCompact / SessionStart | https://dev.to/mikeadolan/claude-code-compaction-kept-destroying-my-work-i-built-hooks-that-fixed-it-2dgp | HIGH |
| Context cost measurement (tokens per call, "30 % of context stale within 5 turns", "tool I/O 60 %+") | PostToolUse → JSONL | https://github.com/manavgup/context-analyzer | HIGH |
| Bundled guard pack in ONE process (~35 ms vs 200+ ms for six processes) | PreToolUse | https://github.com/karanb192/claude-code-hooks | HIGH |
| Exit 1 is the wrong guardrail code; only exit 2 / permissionDecision deny blocks | PreToolUse | https://blog.boucle.sh/posts/how-to-write-a-claude-code-pretooluse-hook/ | HIGH |
| `permissions.deny` overrides hook allow (v2.1.101); `if` field fails open | PreToolUse | https://claudefa.st/blog/guide/changelog | HIGH |
| ConfigChange / InstructionsLoaded audit (Lightning PyPI compromise persisted via a SessionStart hook in `.claude/settings.json`, 2026-04-30) | ConfigChange | https://lord.technology/2026/05/02/claude-codes-hook-system-just-got-weaponised.html | HIGH (noted; not in v2 scope) |
| Role-charter injection by `agent_type` via SubagentStart `additionalContext` (lands as system-reminder in the subagent; task prompt not in input) | SubagentStart | https://github.com/anthropics/claude-code/issues/24176 · #87411 · #23885 | MED — verify empirically |
| Hooks in agent frontmatter (per-role gates, no global duplication; needs workspace trust since 2.1.230) | any | https://code.claude.com/docs/en/hooks | HIGH |
| Fleet ledger from SubagentStart/Stop → JSONL | SubagentStart/Stop | https://github.com/karanb192/claude-code-hooks · https://github.com/disler/claude-code-hooks-multi-agent-observability | MED |
| Every-event JSONL logger | all | https://github.com/disler/claude-code-hooks-mastery | HIGH |
| `duration_ms` in PostToolUse input (v2.1.119) | PostToolUse | https://claudefa.st/blog/guide/changelog | HIGH |
| Statusline: `context_window.used_percentage`, `cost.total_cost_usd`, `rate_limits.*` (v2.1.80), `worktree` (v2.1.69), `refreshInterval` (v2.1.97) | statusLine | https://code.claude.com/docs/en/statusline | HIGH |
| dead-rules audit: score CLAUDE.md rules chronically ignored → convert to hooks | Edit/Write async | https://github.com/karanb192/claude-code-hooks | HIGH (later) |
| Stop hook running tests with exit 2 until green | Stop | https://claudefa.st/blog/tools/hooks/stop-hook-task-enforcement | rejected here (loop hazard + owner order) |

## E. Hook API facts relied on (docs, fetched 2026-08-23)

- Events used: SessionStart (`startup|resume|clear|compact|fork`), UserPromptSubmit, PreToolUse, PostToolUse, Stop, SubagentStart, PreCompact. Source: https://code.claude.com/docs/en/hooks.md
- "All matching hooks run in parallel. If you define the same handler in more than one settings file, it runs once." A plugin's or skill's copy stays separate. (Textually different commands are different handlers.)
- Plain stdout on exit 0 becomes context for UserPromptSubmit, UserPromptExpansion and SessionStart only; all injected strings capped at 10,000 chars.
- Command-hook fields: `async` (background, non-blocking), `asyncRewake` (background, wakes Claude on exit 2), `once` (skill frontmatter only), `shell` (`bash`|`powershell`; default bash, powershell on Windows without Git Bash), `args` (exec form, no shell), `statusMessage`, `timeout` (UserPromptSubmit default 30 s; `MessageDisplay` 10 s).
- SubagentStart: exit 2 not honoured; docs page does not document `additionalContext` for it (community reports it lands as a system-reminder in the subagent) → empirical check.
- Settings: hooks from user/project/local/managed all run (union); `disableAllHooks` switches all off; `${CLAUDE_PROJECT_DIR}` resolves the project root; relative paths resolve against cwd.
- Windows: Git Bash is the default hook shell; forward slashes; CRLF breaks `.sh` shebangs; exec-form needs a real `.exe`; jq absent on this box (hooks are Python). Measured elsewhere: 11 node-spawning hooks ≈ 18–21 s/prompt vs 4.8 s without — https://github.com/ruvnet/ruflo/issues/1530

## F. Open questions / contested

- Brevity (P20, Anthropic "minimal viable information") vs evolving comprehensive playbooks (P19): measured on different tasks; no head-to-head on coding agents with hooks.
- Whether a late goal restatement helps *coding* turns: evidence is on retrieval and RULER; no controlled study on Claude Code injections. The ledger built here is the instrument to measure it locally.
- Claude-4-family U-shape strength vs GPT-3.5: Chroma shows Claude 4 degrades but abstains rather than hallucinates. Position advice is safer than it is precisely quantified.
- "Habituation/wallpaper" as a mechanism is not directly measured anywhere found; closest: few-shot rut (REPORTED) and knows-but-violates (MEASURED, about pressure not repetition).
- Delta-only / on-change injection: obvious design, no measured report found (gap this repo can fill with its ledger).
