# Capability map: Hermes/Jarvis-class assistants vs. Ikarus (Gate 1)

Status: BACKLOG input, 2026-09-05. Research memo produced by a read-only
research delegate (Pythia) for the owner's Ikarus development loop, filed by
session cbd944a5. Not a comparison: per Iron Plan §11 (Gate 1, last sentence)
and §4 invariant 9, no frozen-task, equal-budget comparison against Hermes,
OpenAI or Anthropic products is claimed here. Public documentation was read;
repository facts were read from the packets named below. Every external fact
carries its source; details the delegate could not fetch are marked UNVERIFIED.

Iron Plan: ALIGNED (read-only memo; no code, plan or policy change)
Iron Gate: 1

## Capability surface

| Capability | Hermes Agent (documented) | Ikarus today | Attach point / amendment |
| --- | --- | --- | --- |
| Terminal / code exec | Pluggable sandboxed backends: local, Docker, SSH, Singularity, Modal, Daytona [H1][H4] | Missing by design. No generic shell or candidate process; `app.launch` is fixed-argv only (`daedalus/kernel/policy/computer.py`, COMPUTER-01 scope) | New TOOL_SPEC + `ComputerPolicy` row in its own Work Packet with adversarial review (§10); §7.2 already allows policy-scoped tools, so no amendment |
| Files (list/read/write/move) | Implicit via terminal/MCP | Built, Windows-only, handle-anchored adapter (`file.*`, `daedalus/runtimes/computer_files.py`, G1-IKARUS-24/25). Replacing an existing file stays fenced pending crash reconciliation (G1-IKARUS-27 draft) | Existing seam |
| Browser | Full page control via skills/MCP | Partial: navigate/read/click/fill on an explicit origin allowlist; JavaScript, submission and downloads unavailable (G1-IKARUS-18) | Existing `BROWSER_TOOLS` seam |
| Web search | Documented web-control skills [H1] | Missing: browser only reaches configured origins | One search origin on the allowlist seam, not a new subsystem |
| Vision / screen observation | Vision via web-control skills [H1]; Claude computer-use toolset: screenshot/zoom/click/drag/scroll/wait, permission-gated per app, containerised reference implementation [C1]; OpenAI CUA: screenshot-perceive/act loop in its own browser [O1, access-tier details UNVERIFIED] | Built, narrower: `desktop.observe/click/type/key`, OpenCV inspect/match/changes, local Windows OCR, one foreground app, observation tokens only; path-based vision fenced (G1-IKARUS-28 draft). Native input tested against fixtures, never a live app (G1-IKARUS-18) | Existing `DESKTOP_TOOLS`/`vision.*` seam; live-app acceptance is verification, not new surface |
| Memory (persistent notes) | Agent-curated memory with periodic nudges and FTS5 recall [H1] | Built, narrower: explicit owner `/computer remember` and `forget`, bounded notes, versioned through the canonical spine and CAS (G1-IKARUS-CONTEXT-01); no autonomous agent-written memory | Existing `computer_context.py` seam |
| Skills | Self-authored, improved during use, write-approval gate, shareable hub [H2] | Fenced: one selected, inert, untrusted-rendered skill implemented; new skill-directory selection disabled under the v0.1.6 path-read lock (G1-IKARUS-CONTEXT-01) | Reuse the handle-anchored read pattern of G1-IKARUS-24 for skill directories |
| Scheduling / cron | Always-on gateway ticks cron every 60 s [H3] | Built, narrower: one-shot (G1-IKARUS-20) and finite recurrence (G1-IKARUS-21); needs the File-Bridge watcher or manual `run-due`, no OS daemon | Existing watcher seam |
| Messaging gateways | One background process, many platforms, allowlist/DM pairing, permission tiers [H3] | Missing: no Telegram/Discord/Slack/WhatsApp code under `daedalus/` beyond a Slack-token redaction regex in `sensitivity.py` | §7.2 names connectors behind the same admission boundary: a new Work Packet, but a genuinely new inbound-untrusted-instruction and always-on egress surface |
| Sub-agent delegation | `delegate_task`: isolated child conversation/toolset, bounded concurrency, summary returns [H4] | Missing inside the tool loop (`computer_loop.py` is single-model, sequential). Human-invoked second vendor exists one layer up (`daedalus/council`, `daedalus/providers/codex_cli.py`) | §4.1 already names a fan-out concurrency axis; extends Mission/WorkItem/Attempt |
| Model/provider routing | Documented as a feature [H1, page UNVERIFIED] | Partial: chat layer routes Claude/Codex/Ollama; the computer loop is locked to local Ollama (`docs/IKARUS_COMPUTER.md`) | Existing `provider_router` seam into `computer_loop.py` |
| Session persistence/resume | Sessions persist, list and resume, crash redelivery [H3] | Partial: mission-scoped replay of recorded terminal results; interrupted missions require reconciliation, never blind replay; read-only history commands (COMPUTER-LOOP-01, G1-IKARUS-23) | Existing spine/CAS history seam |
| Honesty / success verification | Not documented as an explicit invariant in the fetched pages | Built, a relative strength: `task_success_verified` stays false without independent evidence; identical-observation and identical-plan stall detection; no retry on uncertain effects (G1-IKARUS-22, 26) | Kernel-enforced already |
| Sandboxing / permission model | Pluggable sandbox backends [H4]; Claude: container reference and per-app prompts [C1]; OpenAI: own-browser sandbox with injection monitoring [O1] | Built at host-process level: `ComputerPolicy` admission and `EffectLease` before every effect; no container/VM isolation for desktop or file tools; Windows-only | Real containment is new infrastructure, not a policy change |

## Five gaps ranked by usefulness per unit of new trust-boundary surface

1. Route the computer loop to an already-integrated model instead of only local Ollama. No new effect or egress surface: every proposal still passes the same policy and lease gate. Addresses the standing finding that small local coder models rarely emit valid tool calls (G1-IKARUS-26 negative evidence).
2. One live-application acceptance test for `desktop.click/type/key`. Pure verification of a built, gated capability; requires explicit owner consent because it takes over the desktop.
3. Re-enable skill-directory selection with the handle-anchored read pattern. Reuses a reviewed anti-TOCTOU mechanism; unlocks reusable procedures, Hermes' highest-leverage differentiator.
4. Wire the §4.1 fan-out axis to a bounded, read-only sub-agent WorkItem split inside one Mission. Wiring of existing contracts, not a new control plane.
5. One minimal messaging-gateway adapter behind the existing admission boundary. Highest usefulness ceiling, ranked last because it opens a new inbound-untrusted-instruction channel and an always-on listener.

## Sources

[H1] hermes-agent.nousresearch.com/docs/ · [H2] .../docs/user-guide/features/skills · [H3] .../docs/user-guide/messaging/ · [H4] .../docs/user-guide/features/delegation · [H5] github.com/NousResearch/hermes-agent · [C1] platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool · [O1] openai.com/index/computer-using-agent/ and openai.com/index/introducing-operator/ (search snippets only; direct fetch failed, details UNVERIFIED). Repository: `docs/work-packets/G1-IKARUS-{18,19,20,21,22,23,24,25,26,COMPUTER-01,CV-01,CONTEXT-01}.md`, `docs/work-packets/G1-WP-IKARUS-COMPUTER-LOOP-01.md`, `docs/IKARUS_COMPUTER.md`, `daedalus/runtimes/computer.py` (TOOL_SPECS), `daedalus/kernel/policy/computer.py`.
