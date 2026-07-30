---
title: Tool vetting
type: spec
status: implemented
updated: 2026-07-30
---

# Tool vetting

The gate a skill or MCP server passes before an agent may be given it, in
[[code:daedalus/tools/vet.py]]. Static only: you do not run untrusted code to
decide whether to trust it.

A skill is text that reaches a model, so its surface is prompt injection. An MCP
server is a process with a socket, so its surface is execution and egress.

Fail-closed: "could not scan" is never "clean". An acknowledged capability
downgrades BLOCK to REVIEW and never to CLEAR, because the capability still exists.

The gate caught its own false alarm on the first run -- it blocked a design-rule CSV
over fourteen matches that were prose about environment files.
