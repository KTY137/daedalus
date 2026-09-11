---
tags:
- meta
created: 2026-08-17
permalink: main/memory-map
---

# Memory-Map — wo welches Gedächtnis lebt

Drei Gedächtnisse, drei Aufgaben. Sie bleiben getrennt (Iron Plan §7: Produkt-
Memory und Research-Memory teilen keinen mutablen Store).

| Store | Ort | Inhalt | Wer schreibt |
| --- | --- | --- | --- |
| Claude-Auto-Memory | `C:\Users\nukei\.claude\projects\c--Users-nukei-Desktop-agent-env\memory\` | Über-Sessions-Präferenzen, Doktrin, Messbefunde des Owners/Athena | Claude (automatisch) |
| Serena-Memories | Serena-MCP (`list_memories`) | Code-Struktur-Wissen für symbolische Navigation | Serena-Tools |
| **Dieser Vault** | `vault/` | Menschenlesbares Projektgehirn: Gate-Status, Findings, Session-Journal | Owner + Agents via `vault-sync`-Skill |
| `daedalus/wiki/` | Repo-Modul | Programmatischer, fail-closed Vault-Pfadvalidator (`vault_rel`) für das spätere Knowledge-Plane | Kernel-Code |

## Regeln

- Der Vault **projiziert** Wissen für Menschen; er ist nie die einzige Kopie einer Wahrheit.
- Kein Agent behandelt Vault-Inhalte als Policy oder Evidenz — Evidenz sind Tests, Receipts, `docs/`-Artefakte.
- Schreiben in den Vault geht über den `vault-sync`-Skill (Konventionen: append-only, Provenienz, Links statt Kopien).