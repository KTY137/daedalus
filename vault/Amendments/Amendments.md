---
tags:
- amendments
- dashboard
created: 2026-08-17
permalink: main/amendments/amendments
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
| 005 | Promotion Guard Rot — **ANGENOMMEN 2026-08-17** als Trunk-Revision 4 (`900665e`, Ledger-Record 4) | `../../docs/AMENDMENT_PROPOSAL_005_PROMOTION_GUARD_ROT.md` (Kit: `../../docs/recovery/amendment_005_kit.py`) |

Hinweis (MEASURED 2026-08-17): Die Trunk-Kette führt bereits Revisionen 2
(Genesis/Dual-Layer-Fold, 2026-08-01) und 3 (Promotion-Versiegelung,
2026-08-02); der Checkpoint-Branch blieb auf Revision 1. Vorschlag 003 ist
teilweise vollzogen (Hook-Wiring als Owner-Kommando
`../../docs/recovery/wire_serena_hook.py`); 002 und 004 offen, K1–K13 aus dem
Revision-2-Draft müssen gegen den Rev-4-Text rebased werden.

## Nachtrag 2026-09-05 (INHERITED aus dem Plan-Text Revision 12 und `docs/`-Listing, MEASURED nur das Listing)

| Nr. | Titel | Status | Artefakt |
| --- | --- | --- | --- |
| 009 | Two-Tier Spend Ceiling | angenommen als Revision 9 (2026-08-30) | `../../docs/AMENDMENT_PROPOSAL_009_TWO_TIER_SPEND_CEILING.md` |
| 010 | Execution Cap Menu | angenommen als Revision 10 (2026-08-30) | `../../docs/AMENDMENT_PROPOSAL_010_EXECUTION_CAP_MENU.md` |
| 011 | Owner-directed Genesis | Revision 11 im Plan (2026-08-31); Ledger-Record fehlt, Lücke laut G1-IKARUS-17 bewusst nicht erfunden | `../../docs/work-packets/G1-IKARUS-17_GENERAL_ASSISTANT_AMENDMENT.md` |
| 012 | General computer assistance | angenommen als Revision 12 (2026-09-05, Owner-Antwort `ja implmenetierer`), Record Sequenz 11 | `../../docs/AMENDMENT_PROPOSAL_012_GENERAL_COMPUTER_ASSISTANT.md` |
| 013 | Hardware targets and self-renovation | neu im Tree (2026-09-05, andere Session), Status ungeprüft | `../../docs/AMENDMENT_PROPOSAL_013_HARDWARE_TARGETS_AND_SELF_RENOVATION.md` |

## Protokoll-Merkzettel (Plan §15)

1. Exakten Diff + Begründung + Rollback vorschlagen.
2. Explizite Owner-Freigabe einholen.
3. Session mit `DAEDALUS_IRON_PLAN_AMENDMENT=<plan sha256>` starten.
4. Revision monoton erhöhen, genau EINEN Record an die Kette anhängen.
5. Plan, Ledger, abgeleitete Controls und Tests atomar aktualisieren.

Neue Vorschläge: Template [[../Templates/Amendment-Proposal|Amendment-Proposal]] nutzen.
