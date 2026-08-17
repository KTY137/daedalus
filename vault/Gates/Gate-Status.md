---
tags: [gates, dashboard]
created: 2026-08-17
---

# Gate-Status

Quelle der Wahrheit: `../../docs/IKARUS_ARIADNE_MASTER_PLAN.md` §10. Diese Seite
ist eine Projektion; bei Widerspruch gewinnt der Plan.

## Leiter

- [ ] **Gate 0 — Canonical Kernel** ← AKTIV (Plan-Revision 1)
- [ ] Gate 1 — Ignition Slice (`Event.voltage -> bias_voltage` über Python/Markdown/CSV)
- [ ] Gate 2 — Forest v2
- [ ] Gate 3 — Baseline Lab
- [ ] Gate 4 — Eine Forschungshypothese (Graph-conditioned Representation Search)
- [ ] Gate 5 — Public Proof

## Gate 0 — Exit-Kriterium

> Exit nur, wenn eine Fault-Injection-Matrix **fail-closed** für geschützte
> Effekte und **fail-open** für read-only-Inspektion demonstriert.

### Relevante Artefakte (Links, keine Kopien)

- Recon-Befunde: `../../docs/GATE0_RECON_20260817_FINDINGS.md`
- Trunk-Failure-Taxonomie: `../../docs/GATE0_TRUNK_FAILURE_TAXONOMY.md`
- Sealed-Promotion-Owner-Approval: `../../docs/GATE0_SEALED_OWNER_APPROVAL.md`
- Promotion-Trust-Root-Konflikt: `../../docs/GATE0_PROMOTION_TRUST_ROOT_CONFLICT.md`
- Fixture-Fixes (Patches): siehe [[../Findings/Gate0-Recovery-Patches|Gate0-Recovery-Patches]]

## Journal

- 2026-08-17 — Vault angelegt; Gate 0 weiterhin aktiv (MEASURED: SessionStart-Hook meldet Gate 0, Plan-sha256 `a47d84ee…26d4`).
- 2026-08-17 (nachm.) — Amendment 005 vollzogen (`900665e`): Guard-Promotion-Checks lesen die Retained Source; Trunk-Verfassung Revision 4. Trunk nimmt wieder Commits an (MEASURED: verify Exit 0).
- 2026-08-17 (nachm.) — Vier Landing-Wellen (`05eb06f`…`7c88f72`): Kernsuiten 245 → 34 Failures (MEASURED); Exit-Pfad-Defekte lesende Inspektion + Evidenz-Projektion + exakte Zustandsgleichheit geschlossen.
- 2026-08-17 (nachm.) — Boundary-Inventar gelandet: wahre Migrationspopulation 165 Targets / 114 unregistriert (MEASURED, Floor); Gate-0-Rest ist Migrations-Grind + Linux-Fault-Run.
- 2026-08-17 17:31 — Saubere Voll-Suite-Bilanz auf committetem Trunk `7c88f72` (MEASURED): **35 failed / 6428 passed / 51 skipped** in 19:57 — Tagesbogen 265 → 199 → 35. Rest ist langer Schwanz (27 Module, meist 1 Failure): v3-Report-Familie (Owner: Scanner-Identität), Blob-Pin-Integration-Review (Owner: Re-Pin), claude_runtime_broker (4, undiagnostiziert), Release-CLI-Subprozess (3), Review-Einzelfälle.
