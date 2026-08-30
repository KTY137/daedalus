# G1-BUDGET-12 — Desktop spend controls

Status: implementation packet
Classification: `AMENDMENT` with implementation aligned to accepted Revision 9
Active gate: Gate 1 — Renovation ignition slice
Master-plan authority: `docs/IKARUS_ARIADNE_MASTER_PLAN.md` Revision 9
Base revision: `98833bf7`

## Primary claim

The desktop Settings UI can persist an explicit period USD ceiling and can
switch the global monetary period ceiling completely off without bypassing the
canonical budget ledger. In uncapped monetary mode, cumulative period USD does
not refuse reservations. The existing call ceiling, egress policy, and any
explicit Mission/SpendEnvelope limits remain independent.

This packet wires configuration into `daedalus.budget`; it creates no second
ledger, budget authority, settings server, or effect path.

## Baseline reproduced

- The desktop has no GUI control for `DAEDALUS_BUDGET_USD`.
- The installed backend reports a fully committed default `$5.00` period
  ceiling and refuses even `codex --version` before spawning it.
- The current source classifies exact `codex --version`, `codex login status`,
  and `claude --version` probes as zero-cost, but that correction has not yet
  reached the installed desktop build.
- The spend ledger contains the evidence for prior calls and must not be reset
  merely because configuration changes.

## Acceptance matrix

1. The existing desktop settings document persists `budget.period_ceiling_usd` as a
   finite value greater than zero; invalid, boolean, NaN, and infinite values
   fail closed.
2. `budget.period_ceiling_enabled=false` removes the global period USD
   comparison; status reports no effective global ceiling or numeric remaining
   USD instead of inventing a hidden replacement cap.
3. The independent call ceiling, egress guard, and explicitly configured
   Mission/SpendEnvelope limits continue to refuse at their own boundaries.
4. Switching from capped to uncapped mode or raising the configured ceiling
   requires a transient, server-validated risk confirmation that is never
   persisted. No save silently widens authority, rewrites spend, releases
   reservations, or resets the period/call ledger.
5. `GET/PUT /api/desktop/settings` remains the only settings route and reports
   configured controls plus measured spend, reservations, calls, period, and
   nullable effective/remaining USD values without exposing secrets.
6. The GUI edits a draft and changes runtime configuration only after an
   explicit Save click. It continuously labels uncapped monetary mode as having
   no global USD limit and displays validation/save errors.
7. Focused Python, frontend build, and UI tests cover valid saves, malformed
   input, capped refusal, uncapped reservation, persistence, and reload.

## Forbidden scope

- no disabling the independent call ceiling, egress policy, kill switch, or an
  explicitly bounded Mission/SpendEnvelope;
- no second ledger, configuration file, HTTP server, or budget enforcement
  path;
- no automatic ceiling increase, ledger deletion, period reset, or reservation
  release;
- no API-key, CLI-auth, or credential material in the settings response;
- no evaluator, promotion, or unrelated runtime edit beyond accepted Amendment
  009 and its implementation.

## Rollback

Re-enable the period ceiling at `$5.00` in persisted settings and remove the
desktop projection. Existing ledgers remain intact; absence of the desktop
projection returns the canonical `$5.00` and 40-call defaults. Reverting the
accepted plan decision itself requires a new owner amendment.

## Verification

Focused budget and desktop-runtime tests, frontend production build, and a
desktop API/UI round trip. A separate review checks fail-closed validation,
atomic save behavior, honest uncapped reporting, and preservation of every
non-monetary boundary.
