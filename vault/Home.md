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

## Status-Snapshot (manuell gepflegt, Stand 2026-08-26)

| Feld | Wert | Provenienz |
| --- | --- | --- |
| Aktives Gate | **Gate 0 — Canonical Kernel** | MEASURED (Iron-Plan-Hook, sha256 `a47d84ee…26d4`) |
| Plan-Revision | 1 | MEASURED |
| Nächster Produktbeweis | Gate 1 Ignition Slice (`Event.voltage -> bias_voltage`) | Plan §10 |
| Offene Amendment-Vorschläge | 002, 003, 004, 005 | MEASURED (`docs/`-Listing 2026-08-17) |

> [!warning] Kein Dataview nötig
> Alle Dashboards hier sind bewusst mit Bordmitteln gebaut (Links, Tabellen,
> Callouts, Checkboxen), damit der Vault ohne ein einziges Community-Plugin
> vollständig funktioniert.

## Konventionen

1. **Links statt Kopien.** Artefakte unter `docs/` bleiben die Quelle; Notizen hier verweisen per relativem Pfad.
2. **Provenienz stempeln.** Jede Zahl trägt MEASURED / INHERITED / ASSUMED.
3. **Append-only bei Sessions.** Daily Notes werden fortgeschrieben, nicht umgeschrieben.
4. **Vault ≠ Autorität.** Wenn Vault und `docs/`/Code widersprechen, gewinnt das Repo.