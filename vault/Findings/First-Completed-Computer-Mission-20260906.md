---
tags: [findings, ikarus, gate-1]
created: 2026-09-06
source: session daedalus-9d (Ikarus-Loop, Owner-Auftrag "besser und autonomer")
---

# Erste abgeschlossene Ikarus-Computer-Mission, und was der lokale Planner dafür noch nicht kann

**Artefakt (autoritativ):** `../../docs/work-packets/G1-IKARUS-32_PLANNER_PROGRESS_PROMPT.md`, Evidenz `../../docs/evidence/G1-IKARUS-32_PLANNER_PROGRESS_LIVE/` (Branch `loop/lane11-planner-progress`, Commits ad794eaf, ea8b2052)

Einordnung: Der Planner-Prompt nennt seit G1-IKARUS-32 den nächsten offenen Advisory-Schritt (`plan_progress`). Damit schlägt qwen2.5-coder:7b nach `browser.navigate` erstmals `browser.read` vor (in sechs früheren Messungen nie), erreicht aber kein `finish`; Codex als Planner über `allow_remote_context` schließt dieselbe Mission in 59,7 s mit byte-genauer Zusammenfassung ab, die erste Computer-Loop-Mission auf diesem Host mit `finish`. Momus fand zwei Fehler der ersten Fassung (Zählerreset bei Planwiederholung, `step_limit` als Artefakt von `max_steps 8`); sein Falsifikationslauf measure-10 zeigte, dass die bestehende Identisch-Plan-Regel den 7B ehrlich beendet. Die drei Folgeideen (beratender finish-Hinweis, `step_done`-Typ, Planner-Routing) sind mit Gründen verworfen; die Planner-Wahl mit Remote-Kontext ist eine Egress-Entscheidung des Owners.

Provenienz: MEASURED (measure-08/09/10 am 2026-09-06, Laufzeiten und Zustände im Paket); die Einordnung "erste Mission mit finish" ist INHERITED aus den retained Läufen G1-IKARUS-26/31.

Offene Prüfschritte:

- [ ] Codex/6e-Antworten zu den Review-Fragen im Raum
- [ ] G1-IKARUS-34 (EXPERIMENT, vorregistriert): ändert die Payload-Form, ob der 7B `finish` erreicht? 5 Läufe je Variante
- [ ] Owner-Entscheidung: Planner-Wahl mit Remote-Kontext in der Desktop-UI, Warnzeile vor der ersten Mission
