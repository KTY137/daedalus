---
tags: [findings, ikarus, gate-1, egress]
created: 2026-09-06
source: session daedalus-6c (Ikarus-Loop), Owner-Antwort Blatt-Zeile 10 via Review-Session 08:48
---

# Remote-Planner als ausdrückliche Owner-Wahl, Secret-Floor vor jedem Planner-Call

**Artefakt (autoritativ):** `../../docs/work-packets/G1-IKARUS-43_REMOTE_PLANNER_OWNER_CHOICE.md` (Commit d4e4b834 auf `loop/lane11-planner-progress`), Entscheidungsblatt `../../docs/decisions-pending/OWNER_DECISIONS_20260906.md` Zeile 10

Einordnung: Der Owner hat den stärksten allgemeinen Planner (Codex über `allow_remote_context`) unter drei Bedingungen freigegeben. Umgesetzt als `/computer planner <provider> [Modell]` mit transienter `confirm-remote`-Bestätigung (nie gespeichert, kein Default bewegt), Planner-Zeile in `/computer status` vor der ersten Mission, und Secret-Floor auf jeder Beobachtung direkt nach der Ausführung sowie auf jedem Prompt vor jedem Planner-Call, lokal wie remote; ein Treffer beendet die Mission `blocked`, bevor ein Planner das Material sieht, die Beobachtung bleibt lokal als Evidenz. Damit ist der erste Weg zu abgeschlossenen Missionen (measure-09, G1-IKARUS-32) regulär erreichbar; C2 (G1-IKARUS-36, reproduziertes `finish`, n≥5 je Arm) referenziert den Floor-Test statt ihn zu bauen.

Provenienz: MEASURED (fünf gepinnte Tests, 187 passed am 2026-09-06); die Owner-Antwort ist INHERITED aus dem Raum 08:48.

Offene Prüfschritte:

- [ ] Odysseus-Bericht zu G1-IKARUS-32..35 einarbeiten (Fix-forward)
- [ ] C2/G1-IKARUS-36: zehn Läufe je Arm nach A3-Merge
- [ ] Cockpit (C8): Planner-Zeile und Watcher-Status vor der ersten Mission sichtbar machen
