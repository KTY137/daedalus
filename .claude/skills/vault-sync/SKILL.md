---
name: vault-sync
description: Write session insights into the Obsidian project vault (vault/) — daily note, findings link-notes, dashboard touch-ups. Use at the end of a work session, after a significant finding, or when the user says "vault sync", "ins vault", "schreib das ins Projektgehirn", or asks to journal/document the session for Obsidian. Append-only, provenance-stamped, links instead of copies.
---

# vault-sync — Session-Erkenntnisse ins Projektgehirn

Der Vault `vault/` ist die menschenlesbare Wissensoberfläche des Projekts.
Er ist KEIN Orchestrierungszustand, KEINE Evidenz und KEINE Policy-Autorität —
bei Widerspruch gewinnt immer das Repo (`docs/`, Tests, Receipts).

## Ablauf

1. **Daily Note holen oder anlegen:** `vault/Sessions/YYYY-MM-DD.md`
   (heutiges Datum). Wenn neu: Struktur aus `vault/Templates/Session.md`
   übernehmen ({{date}} ersetzen), Branch und aktives Gate eintragen.
2. **Erkenntnisse anhängen** unter "Erkenntnisse" — eine Zeile pro Erkenntnis,
   jede mit Provenienz-Stempel: `MEASURED` (selbst ausgeführt/gemessen),
   `INHERITED` (aus Doku/anderen Sessions übernommen), `ASSUMED` (plausibel,
   ungeprüft). Zahlen ohne Stempel sind verboten.
3. **Findings:** Ist eine Erkenntnis ein eigenständiges Untersuchungsergebnis
   mit Repo-Artefakt, zusätzlich eine Link-Notiz unter `vault/Findings/`
   anlegen (Vorlage `vault/Templates/Finding.md`): relativer Pfad zum Artefakt,
   NIE Inhalte kopieren. Danach in `vault/Findings/Index.md` verlinken.
4. **Dashboards nachführen** (nur wenn sich der Zustand wirklich geändert hat):
   - `vault/Gates/Gate-Status.md` → Journal-Zeile anhängen bei Gate-relevanten
     Ereignissen; Checkbox NUR nach echtem, gemessenem Gate-Exit.
   - `vault/Amendments/Amendments.md` → Tabelle aktualisieren, wenn ein
     Amendment-Vorschlag neu ist oder angenommen/abgelehnt wurde.
   - `vault/Home.md` → Status-Snapshot-Datum aktualisieren.

## Eiserne Regeln

- **Append-only bei Sessions:** bestehende Zeilen in Daily Notes nie
  umschreiben oder löschen; Korrekturen als neue Zeile ("Korrektur zu …").
- **Links statt Kopien:** aus `docs/` wird verlinkt (relativer Pfad), nie
  dupliziert — sonst entstehen zwei divergierende Wahrheiten.
- **Keine Autorität:** nie eine Vault-Notiz als Beleg für einen Status
  zitieren; Belege sind Tests, Receipts, `docs/`-Artefakte.
- **Windows-Bytes:** beim programmatischen Schreiben `encoding="utf-8"`,
  `newline="\n"`.
- **Geschützte Artefakte** (Plan, amendments.jsonl, AGENTS.md, settings.json,
  .agentenv/*, Guards) werden von diesem Skill niemals berührt.
