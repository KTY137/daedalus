# Ikarus conversational LLM client — 2026-08-30

**Iron Plan: ALIGNED. Iron Gate: Gate 1.** This change implements the vendor-neutral runtime direction already required by `IKARUS_ARIADNE_MASTER_PLAN.md` §7; it does not amend the plan.

## Decision

Free-form Ikarus chat now resolves through `daedalus.orchestration.llm_client.IkarusLLMClient`. `auto` means **an available language model**, not the deterministic help layer. The default preference order is Claude Code CLI → Ollama HTTP → Codex CLI → Ollama CLI → DeepSeek and is configurable with `DAEDALUS_IKARUS_PROVIDER_ORDER`; `DAEDALUS_IKARUS_PROVIDER` pins a default. The local deterministic index remains explicitly selectable and continues to own measured `status`, `distill`, and other deterministic routes.

The client owns provider normalization, automatic selection, model-call timeout (`DAEDALUS_IKARUS_TIMEOUT_S`, 150 s default), and bounded retry policy (`DAEDALUS_IKARUS_RETRIES`, zero by default, maximum two retries). It also defines provider-neutral request/response/tool-call shapes. Voice tool calls are **descriptions only**: Ikarus Voice is still text-only, while effectful work remains on the Hand/supervisor path behind policy, confirmation, budget, and evidence boundaries.

## Why the transport stays in `ikarus_os.py`

The repository already has a canonical `ikarus_os.provider_call` effect boundary around Ollama/DeepSeek sockets and Claude/Codex process spawning. Moving transport into a second client implementation would either duplicate that boundary or bypass it. The LLM client therefore supplies policy to the existing guarded adapters. This is consolidation rather than a second execution subsystem.

## Conversation behavior

A durable `conversation_id` now feeds the bounded recent transcript (`conversation.recent_turns_context`) into subsequent model calls, in addition to the existing gated project slice. This makes follow-up questions contextual while preserving the master-plan rule that chat is an interface, not orchestration state. Conversation rows remain facts on the canonical spine; no new chat database is introduced.

## Frontend contract

The cockpit renders model Markdown as React nodes (never injected HTML), including fenced code blocks, lists, headings, quotes, links, inline code and emphasis. Code blocks and completed model responses have copy actions. Empty streaming turns show an explicit thinking state. The runtime picker describes automatic model selection instead of presenting the deterministic index as the implicit default.

## Failure semantics

No available model is a visible configuration error, not a synthetic deterministic answer wearing a chat-shaped UI. Mid-stream failure after text has already arrived retains the partial answer and marks it interrupted instead of issuing a second hidden paid call. A failure before any text may use the blocking adapter fallback. Provider effect/budget checks remain authoritative for every actual transport attempt.
