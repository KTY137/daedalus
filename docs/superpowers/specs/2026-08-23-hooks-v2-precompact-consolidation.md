# Work Packet: Hooks v2 PreCompact consolidation

- Packet ID: `G0-HOOKS-V2-PRECOMPACT-CONSOLIDATION`
- Classification: `ALIGNED`
- Active gate: Gate 0 — Canonical Kernel
- Base revision: `67ec9ebf97913b0bed6b7b85f789d703967c3b34`
- Primary claim: every effectful project hook enters through the registered
  `daedalus.hooks` dispatcher.
- Invariants: One kernel, Provenance, Bounded effects.

## Scope

Allowed: `.claude/settings.json`, the PreCompact proposal and snippet,
`daedalus/hooks/`, `tests/test_hooks_precompact.py`, and hooks-v2 design evidence.
Forbidden: `daedalus/spine/effect_boundary.py`, Watchdog files, plan/policy,
promotion, evaluator, and unrelated generated documentation.

## Frozen acceptance matrix

1. Every project-relative command hook in `.claude/settings.json` invokes the
   registered `daedalus/hooks/__main__.py` dispatcher.
2. PreCompact consumes Claude Code's documented `trigger` field (`manual` or
   `auto`) and retains `compaction_trigger` only as a compatibility fallback.
3. It preserves the append-only daily-note marker, uses the payload-derived Git
   root, creates frontmatter at most once under concurrent creation, emits no
   model context, and records its result in the hooks ledger.
4. Missing vaults, malformed payloads, and diary write failures remain
   fail-open and do not block compaction.
5. The direct proposal entrypoint is deleted and active configuration and design
   references point to the canonical dispatcher. Frozen historical inventories
   retain the old path as evidence rather than being silently rewritten.

## Baseline and verification

Baseline on 2026-08-23: one direct repository hook command remained and a
documented `{"trigger": "manual"}` payload was recorded as
`[compaction:unknown]`; both acceptance probes failed. Verification is the
focused hooks suite, entrypoint-registry tests, JSON parsing, reference scan,
and independent review. Rollback is the inverse diff; no data migration is
required because the daily-note format is unchanged.

Revision 7 retired `tools/iron_plan_guard.py` by recorded owner amendment, so
no mechanical guard receipt is claimed. This packet was checked directly
against the active plan, the Gate-0 entrypoint registry, and the frozen matrix
above. Independent review found no ship blocker; its permissive command-hook
substring check was tightened to the exact event-to-dispatcher matrix before
commit.
