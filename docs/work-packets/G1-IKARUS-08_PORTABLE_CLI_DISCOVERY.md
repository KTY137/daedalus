# G1-IKARUS-08 — Portable CLI discovery and provider admission

Status: review packet
Classification: `ALIGNED`
Active gate: Gate 1 — Renovation ignition slice
Master-plan authority: `docs/IKARUS_ARIADNE_MASTER_PLAN.md` Revision 8
Base revision: `98833bf7`

## Primary claim

Ikarus selects a CLI-backed voice only when the executable it will actually
spawn can be resolved on Windows, Linux, or macOS, and it never selects an
Ollama endpoint that the canonical `provider.egress_policy` will later refuse.

This packet consolidates discovery and child-process environment binding in the
existing runtime registry. It adds no scheduler, provider registry, state store,
or effect path. The existing `ikarus_os.provider_call` boundary remains the
only voice transport start.

## Baseline reproduced

- Claude Code was installed inside a VS Code extension but absent from `PATH`,
  so every `shutil.which("claude")` caller reported it missing.
- Codex was found, but the child could not load its state until `CODEX_HOME`
  named the existing Codex home.
- Ollama CLI returned exit zero for `--version` while also reporting that its
  server was unreachable.
- an undeclared remote `OLLAMA_HOST` could pass a reachability probe and win
  automatic selection, then be refused at `ikarus_os.provider_call`.

## Acceptance matrix

1. CLI resolution prefers an explicit per-runtime path, then `PATH`, then a
   bounded list of standard install/editor-extension locations on all three
   supported OS families.
2. The exact resolved path is used by status probes and live Ikarus transports.
3. Codex children receive an existing `CODEX_HOME` without mutating the parent
   process environment; authentication state is never copied or exposed.
4. Ollama HTTP and CLI status run endpoint admission before any reachability
   probe; an undeclared remote endpoint is unavailable with an actionable
   `egress_refused` status.
5. Ollama CLI is either a real guarded subprocess transport or unavailable; it
   is never relabelled and sent through the HTTP implementation.
6. Claude, Codex, Ollama, egress-refusal, blocking chat, and streaming fallback
   tests remain green.

## Forbidden scope

- no weakening of `provider.egress_policy`;
- no automatic remote-host trust or broad egress flag;
- no copying `auth.json`, sharing live SQLite files, or implementing Codex
  laptop synchronization in this packet;
- no new orchestration state or promotion path;
- no plan, amendment-chain, or policy-guard edit.

## Verification

Focused unit and boundary tests plus live, non-model readiness probes on the
current host. No automatic merge or promotion.
