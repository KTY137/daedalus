# Token Efficiency Notes

Research date: 2026-07-05.

## Sources Checked

- Anthropic Claude Code cost guide:
  https://code.claude.com/docs/en/costs
- Anthropic prompt caching:
  https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
- Anthropic token counting:
  https://docs.anthropic.com/en/docs/build-with-claude/token-counting
- Anthropic structured/consistent outputs:
  https://docs.anthropic.com/en/docs/test-and-evaluate/strengthen-guardrails/increase-consistency
- OpenAI prompt caching:
  https://developers.openai.com/api/docs/guides/prompt-caching
- OpenAI structured outputs:
  https://developers.openai.com/api/docs/guides/structured-outputs

## Rules For This Daedalus

1. Keep static prompt text at the beginning of prompts.
   OpenAI prompt caching depends on exact prefix matches; static instructions
   should precede variable task data. Claude also benefits from repeated content
   through prompt caching in Claude Code and API prompt caching.

2. Keep task context small.
   Claude Code's cost guide says token usage scales with context size. Pass
   objective, paths, constraints, and tiny state; do not pass full chat history.

3. Use structured outputs.
   OpenAI recommends Structured Outputs over JSON mode when possible because they
   enforce schema adherence. Anthropic recommends Structured Outputs when valid
   JSON/schema conformance is required. In CLI mode, use `claude -p` with
   `--json-schema`.

4. Prefer small models for routine work.
   Claude Code docs recommend Sonnet for most coding and reserving Opus for
   complex architecture or multi-step reasoning. Use Haiku only for summaries or
   very cheap classification when quality risk is low.

5. Avoid tool/context bloat.
   Disable unused MCP servers; prefer CLI tools when they are more compact than
   loading large tool schemas. Keep bridge requests path-scoped.

6. Compact aggressively between unrelated tasks.
   Claude Code recommends `/clear` between unrelated tasks and custom compaction
   instructions to preserve code changes/test output. Our external memory
   replaces replaying long history.

7. Record TODOs outside model context.
   Persist TODOs in `memory/events.local.jsonl` and regenerate
   `memory/todos.local.md`. Do not ask either model to remember long-running
   task state in chat.

## Prompt Shape

Good:

```text
static protocol
agent role
repo root
objective
paths
constraints
JSON schema
```

Bad:

```text
full conversation
entire git diff
all docs
all tool definitions
open-ended "what do you think?"
```

## Output Shape

Use compact JSON with bounded strings:

```json
{
  "status": "done",
  "summary": "max 600 chars",
  "files_changed": [],
  "tests_run": [],
  "risks": [],
  "todos": [],
  "handoff": {}
}
```
