---
tags: [amendments, dashboard]
created: 2026-08-17
---

# Amendments — Verfassungsänderungen

Autoritative Kette: `../../docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl`
(append-only, hash-verkettet). Diese Seite ist nur der Überblick.

## Offene Vorschläge (Stand 2026-08-17, MEASURED aus `docs/`-Listing)

| Nr. | Titel | Artefakt |
| --- | --- | --- |
| 002 | Guard Repairability | `../../docs/AMENDMENT_PROPOSAL_002_GUARD_REPAIRABILITY.md` |
| 003 | Serena First | `../../docs/AMENDMENT_PROPOSAL_003_SERENA_FIRST.md` |
| 004 | Byte-Exact Resource EOL | `../../docs/AMENDMENT_PROPOSAL_004_BYTE_EXACT_RESOURCE_EOL.md` |
| 005 | Promotion Guard Rot | `../../docs/AMENDMENT_PROPOSAL_005_PROMOTION_GUARD_ROT.md` (Kit: `../../docs/recovery/amendment_005_kit.py`) |

## Protokoll-Merkzettel (Plan §15)

1. Exakten Diff + Begründung + Rollback vorschlagen.
2. Explizite Owner-Freigabe einholen.
3. Session mit `DAEDALUS_IRON_PLAN_AMENDMENT=<plan sha256>` starten.
4. Revision monoton erhöhen, genau EINEN Record an die Kette anhängen.
5. Plan, Ledger, abgeleitete Controls und Tests atomar aktualisieren.

Neue Vorschläge: Template [[../Templates/Amendment-Proposal|Amendment-Proposal]] nutzen.
