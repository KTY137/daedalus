---
tags:
- dashboard
created: 2026-08-17
permalink: main/home
---

# Daedalus — Projektgehirn

> [!info] Was dieser Vault ist
> Die menschenlesbare Wissensoberfläche des Daedalus-Projekts. Er **ergänzt**
> `daedalus/wiki/` (das programmatische Vault-Modul) und das Claude-Auto-Memory —
> er ersetzt keins von beiden. Er ist **kein** Orchestrierungszustand, kein
> Event-Store und keine Policy-Autorität (Iron Plan, Abschnitt 0 und 7).

## Bereiche

- [[Gates/Gate-Status|Gate-Status]] — wo das Projekt auf der Gate-0…5-Leiter steht
- [[Amendments/Amendments|Amendments]] — Verfassungsänderungen: Kette + offene Vorschläge
- [[Findings/Index|Findings]] — Recovery-Artefakte und Untersuchungsergebnisse (verlinkt, nie kopiert)
- [[Sessions/2026-08-17|Sessions]] — Daily Notes, eine pro Arbeitstag
- [[Memory-Map]] — wo welches Gedächtnis lebt (Auto-Memory, Serena, dieser Vault)
- [[SETUP]] — was der Owner einmalig einrichten muss
- [[ENVIRONMENT_REPORT]] — was gebaut wurde, mit Quellen

## Status-Snapshot (manuell gepflegt, Stand 2026-09-10)

| Feld | Wert | Provenienz |
| --- | --- | --- |
| Aktives Gate | **Gate 1 — Renovation, owner-directed Genesis, general computer assistance, Hardware-Targets, Self-Renovation** | INHERITED (Plan-Text Revision 13) |
| Plan-Revision | 13 (Version 2.4.0, 2026-09-06; Amendment 013 angenommen) | INHERITED (Plan-Metadaten, Kette Sequenz 12/13) |
| Nächster Produktbeweis | Chat-Zündung: Imperative Arbeitsaufträge („verbessere Daedalus”, improve/extend/develop) werden als `computer_task` angeboten (G1-IKARUS-46, MEASURED 2026-09-10, Worktree-Lauf 3 mit Claude-Planner); Loop kann Projekt über fünf read-only daedalus.*-Werkzeuge beobachten (daedalus.status, structure, slice, docrefs, tasks); `/computer run`, `/computer enable|disable daedalus` verfügbar. Renovation Ignition Slice bleibt offen (Codex-Lane, PRs #319/#321 gemerged) | Plan §8.1/§11/§12; MEASURED [[Sessions/2026-09-10]] |
| Offene Amendment-Vorschläge | 002, 003, 004 (alt) | MEASURED (`docs/`-Listing 2026-09-05, 013 seit 2026-09-06 angenommen) |
| Offene Gate-3-Vorarbeit | PR #320 (G3-BASE-01), Draft-PR #322 (Tokenizer); Usage/Corpus WIP; Seal wartet auf Owner-Entscheidung | INHERITED [[Sessions/2026-09-08]] |

Frühere Snapshots: 2026-09-05 (Amendment 012, G1-IKARUS-24), 2026-08-26 (Gate 0 besiegelt, Revision 8) — siehe [[Gates/Gate-Status]].

> [!warning] Kein Dataview nötig
> Alle Dashboards hier sind bewusst mit Bordmitteln gebaut (Links, Tabellen,
> Callouts, Checkboxen), damit der Vault ohne ein einziges Community-Plugin
> vollständig funktioniert.

## Konventionen

1. **Links statt Kopien.** Artefakte unter `docs/` bleiben die Quelle; Notizen hier verweisen per relativem Pfad.
2. **Provenienz stempeln.** Jede Zahl trägt MEASURED / INHERITED / ASSUMED.
3. **Append-only bei Sessions.** Daily Notes werden fortgeschrieben, nicht umgeschrieben.
4. **Vault ≠ Autorität.** Wenn Vault und `docs/`/Code widersprechen, gewinnt das Repo.
