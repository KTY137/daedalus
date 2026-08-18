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
- 2026-08-17 abends — Sieben Grind-Lanes gefahren und geportet (`a179b6f`…`d186d59`): alle 36 delegierbaren Failures gefixt; ein echter Produktionsbug (Lifecycle-Clock lief dem Ledger 654–6749 µs voraus, geklemmt + mutationsgetestet, `592eef4`); v3-„Identitätsfrage" per Messung auf Scanner-Defekt reduziert (Papier `docs/GATE0_V3_SCANNER_IDENTITY_DECISION.md`, B+D gelandet, nur Schema-Bump beim Owner); **Windows-Fault-Matrix 22/22** (MEASURED, scoped „102 passed").
- 2026-08-17 abends — **Kanonischer Docker-Sandbox-Pfad konnte nie einen Container starten** (ungültiges `rw`-Feld im --mount, Exit 125 las sich als Refusal; falscher Pass im Sandbox-Unavailable-Szenario). Gefixt + erster echter Linux-Fault-Katalog-Lauf: 3 passed / 2 failed (stale Fixtures) / 4 blocked (Policy, korrekt), Evidence `runs/gate0-linux-container-fault/` (`d186d59`); Attestation-Boundary verweigert mangels Issuer — nächste ehrliche Lücke.
- 2026-08-17 21:04 — Voll-Suite auf committetem Trunk `220de7c` (MEASURED): **2 failed / 6468 passed / 51 skipped / 1992 Subtests** in 43:16 — Tagesbogen 265 → 199 → 35 → 2. Rest: Guard-Fixture (Owner-Diff liegt vor) + Kill-Switch-Latenz 607 ms vs. 600 ms Budget unter Volllast (3/3 grün auf ruhiger Box → load-sensitiv, nicht kaputt). Artefakt `runs/full_suite_20260817_evening.txt` (`5482e19`).
- 2026-08-17 abends — Evidenz-Integrität: die 4 Fault-Matrix-Mutationsskripte messen auf Windows nichts (sys.path-Ordnung, Sandbox nie importiert) — „mutants killed"-Evidenz daraus suspekt; Guards selbst tragen (3/3 in-place killed). Fix-Lane läuft. CRLF-Dämon 4× aufgetreten; dauerhafter Fix = `.gitattributes`-Pin (Owner, Punkte 5/6 der Vorlage).
- 2026-08-17 abends — Watchdog (Owner-ps1, Clean-Env-Launcher) grindet die Effect-Boundary-Migration auf `grind/watchdog-mission2`: unregistrierte Targets 114 → 91 (MEASURED je Commit-Message, `812ca60`…`74c10b0`).
- 2026-08-17 23:24 — **Owner-Amendment 006 committet** (`7dce95c`): Guard-Fixture trägt die Retained Source, Byte-Pin-Subjekte bekommen `-text`; Verfassung Revision 5 (sha `ce4335e1…`). Der letzte echte Suite-Failure des Tages ist damit grün (MEASURED „1 passed"). Mixed-Commit-Provenienz (3 Spine-Writer-Dateien ritten mit) als git note dokumentiert.
- 2026-08-18 morgens — **Maschinenseite von Gate 0 fertig.** Nacht-Lanes gelandet: Council-Checks (`ee286b5d`: Reconciliation-Deadline-Guard mutationsgetestet, Issuer-Kontrakt gepinnt, Clock-Completion-Order-Fenster + Inversions-Remnant dokumentiert), Watchdog-Mission 2 komplett (`1e681b9b`: Conformance-Receipt-Persistenz, FaultMatrixEvidence-Brücke, live-envelope-Owner-Memo `docs/GATE0_LIVE_RUNTIME_DECISION.md`, 2 G1-Checklist-Items, Forest-v2-Attribution 15,5→30,3 %), Morning-Finisher (`35172501`: Matrix 22/24 bei `1e681b9b` OHNE overdue, erste echte Conformance-Receipts 3 Runtimes × 8 Checks, gebundener v3-Report). **Endstand MEASURED: v2-Blocker 73 = 70 inventory_only (CENTRAL-Owner-Entscheidung) + 2 live-envelope (Memo liegt) + 1 unclaimed boundary line. fault_injection nur noch die 2 live-envelope-Zeilen, conformance leer, unregistered 0.** Bekannte kleine Lücke dokumentiert: CLI-Flag für Conformance-receipt_dir fehlt (gebundener Report via Builder-API). Rest ist Owner-Paket.
- 2026-08-18 08:40 — **Owner-Direktive „generellere Option" umgesetzt.** live-envelope per Option A GEBAUT statt gescoped (`81ce74b9`): dritte Collector-Spalte + dritter Issuer + zwei Live-Probe-Treiber mit Positiv-Kontrollen — **erstmals 24/24 Zeilen beobachtet, fault.missing = 0** (die zwei Zeilen ehrlich blocked-mit-Grund auf dieser Box; Drift-Messhälfte real: installiertes ollama.exe gehasht und gedriftet). Owner-Key-Zeremonie-Kit liegt (`docs/recovery/production_key_ceremony_kit.py`, selftest ALL PASS, HMAC-Secrets außerhalb jedes Working Trees, ACL-Bug im Bau gefunden und gefixt). CLI-Flag `--conformance-receipts` gelandet (`237a413e`) — gebundener Report allein per CLI reproduzierbar. CENTRAL-Grind läuft als Watchdog-Mission 3 (echte begin_effect-Ketten, kein Registry-Euphemismus).
- 2026-08-18 10:35 — **Maschinenseite abgeschlossen, Stift liegt beim Owner.** CENTRAL-Grind geportet (`bcc0feaf`: 58 Türen echt verdrahtet, 12 begründete Rest-Zeilen; Report 73 → 18 Blocker). Closure-Lauf gesammelt und geportet (`89f95ad1`): alle 24 Matrix-Zeilen + 3 frische Conformance-Receipts bei `bcc0feaf`, UNATTESTIERT — kein Agent-Key hat den Lauf berührt. Attest-Wrapper gegen die echten CLIs validiert (8 Korrekturen, Trockentest exit 0/0/0). **Owner-Endspiel: ① Settings-Klick, ② `docs\recovery\gate0_production_attest.ps1 -RunDir runs\gate0-closure-20260818` (attestiert produktiv + erzeugt Verdikt + gebundenen Report), ③ versiegelter Stempel — dabei entscheidet der Owner über die 13 begründeten inventory_only-Restzeilen (annehmen oder nachverdrahten lassen).**
- 2026-08-18 09:11 — **Owner-Key-Zeremonie vollzogen** (Kit-Selftest 16/16 ALL PASS, MEASURED im Owner-Terminal): drei Produktions-HMAC-Keys unter `%USERPROFILE%\.daedalus-keys\gate0-runtime-fault\`, ACL-gelockt auf den Owner, Fingerprints (veröffentlichbar): fixture `c8d2fa62…`, linux-host `cc7f8652…`, live-runtime `a3f22875…`. Schlüssel verbleiben in Owner-Custody — Agenten laden sie nicht; die finale Produktions-Attestation läuft als Owner-Befehl. CENTRAL-Grind parallel bei 70 → 12 inventory_only (MEASURED je Commit, Mutationsprobe je Familie).
- 2026-08-18 00:05 — Welle 5 + Endspiel gelandet (`8d0d945` Boundary-Deklarationen, `4fb2251` Matrix-Report-Bindung mit Revisions-Zwang, `80440c0` HEAD-Sammlung): Gate-Report am Trunk MEASURED **closed:false, 74 Blocker in 4 Klassen, 0 unregistrierte Entrypoints** — 70× inventory_only (CENTRAL-Owner-Entscheidung), 2× live-envelope fault.missing, 1× Conformance-Persistenz, 1× security_boundary_claimed. Fault-Matrix revisionsaktuell 22/24 attestiert bei `4fb2251` (Verdikt `1c3654f2…`, Dev-Keys deklariert). Nacht-Stränge: Watchdog-Mission 2 (5 Phasen), Cross-Vendor-Council (Codex-Fokus) laufen.
