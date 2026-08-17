---
name: vault-recall
description: Search the Obsidian project vault (vault/) for prior findings, session notes, and gate/amendment context BEFORE starting non-trivial work — so past insight is reused instead of re-derived. Use at the start of a task touching Gate 0, amendments, recovery patches, or Windows portability, or when the user asks "was wissen wir schon über X" / "check the vault".
---

# vault-recall — erst nachschlagen, dann arbeiten

Gegenstück zu `vault-sync`: billiges Lesen vor teurem Wiederherleiten.

## Ablauf

1. **Gezielt greppen, nicht alles lesen** (Token-Disziplin):
   - Thema: `Grep` über `vault/` nach Schlüsselwörtern (deutsch UND englisch probieren).
   - Chronologie: `vault/Sessions/` nach Datum absteigend — nur die 2–3 jüngsten Notizen.
   - Einstiegspunkte: `vault/Findings/Index.md`, `vault/Gates/Gate-Status.md`,
     `vault/Amendments/Amendments.md`.
2. **Provenienz respektieren:** Ein `ASSUMED` aus dem Vault bleibt ASSUMED —
   vor Weiterverwendung verifizieren. `MEASURED` gilt nur für das notierte
   Datum; bei altem Datum neu messen.
3. **Der Link-Notiz folgen:** Findings verweisen auf `docs/`-Artefakte —
   das Artefakt ist die Quelle, die Notiz nur der Wegweiser.
4. **Lücke gefunden?** Wenn die Antwort im Vault fehlte, aber teuer
   herzuleiten war: am Ende der Arbeit per `vault-sync` nachtragen.

## Grenzen

- Vault-Inhalte sind Wissen, nie Evidenz oder Policy.
- Auto-Memory (`~/.claude/projects/...`) und Serena-Memories NICHT von hier
  aus editieren; siehe `vault/Memory-Map.md` für die Trennung.
