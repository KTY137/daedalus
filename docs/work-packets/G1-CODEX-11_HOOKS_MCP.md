# Work Packet: G1-CODEX-11 Hooks and MCP setup

Status: review packet  
Classification: `ALIGNED`  
Active gate: Gate 1 — Renovation ignition slice  

## Primary claim

Codex receives repo orientation and verification context from the existing
Daedalus hook dispatcher and gains narrowly scoped documentation MCP servers,
without presenting hooks as an enforcement boundary.

## Evidence

- `.codex/hooks.json` is valid JSON and declares SessionStart,
  UserPromptSubmit, PostToolUse, and PreCompact handlers with Windows and POSIX
  commands.
- Global Codex configuration lists `openaiDeveloperDocs` and `context7` as
  enabled; the first is read-only and OpenAI-hosted.
- Hook trust remains an explicit owner action through Codex `/hooks`.

## Forbidden

- No broad filesystem MCP, browser automation MCP, credentials, or stale paths
  copied from the previous user's `.mcp.json`.
- No claim that a hook is a complete security guarantee.
