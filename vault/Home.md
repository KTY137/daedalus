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

## Status-Snapshot (manuell gepflegt, Stand 2026-09-05)

| Feld | Wert | Provenienz |
| --- | --- | --- |
| Aktives Gate | **Gate 1 — Renovation, owner-directed Genesis und general computer assistance** | INHERITED (Plan-Text Revision 12, sha256 `12659413…d8fb` laut G1-IKARUS-17) |
| Plan-Revision | 12 (Version 2.3.0, 2026-09-05) | INHERITED (Plan-Metadaten) |
| Nächster Produktbeweis | Renovation Ignition Slice bleibt offen; im Assistant-Strang: Zaun-Lift für `file.*` (G1-IKARUS-25) nach bestätigtem Review von G1-IKARUS-24 | Plan §11/§12, [[Sessions/2026-09-05]] |
| Offene Amendment-Vorschläge | 002, 003, 004 (alt), 013 (neu, ungeprüft) | MEASURED (`docs/`-Listing 2026-09-05) |

Frühere Snapshots: 2026-08-26 (Gate 0 besiegelt, Revision 8) — siehe [[Gates/Gate-Status]].

> [!warning] Kein Dataview nötig
> Alle Dashboards hier sind bewusst mit Bordmitteln gebaut (Links, Tabellen,
> Callouts, Checkboxen), damit der Vault ohne ein einziges Community-Plugin
> vollständig funktioniert.

## Konventionen

1. **Links statt Kopien.** Artefakte unter `docs/` bleiben die Quelle; Notizen hier verweisen per relativem Pfad.
2. **Provenienz stempeln.** Jede Zahl trägt MEASURED / INHERITED / ASSUMED.
3. **Append-only bei Sessions.** Daily Notes werden fortgeschrieben, nicht umgeschrieben.
4. **Vault ≠ Autorität.** Wenn Vault und `docs/`/Code widersprechen, gewinnt das Repo.
