---
tags:
- findings
created: 2026-09-02
source: apps/web, daedalus/conversation.py
permalink: main/findings/ikarus-agent-surface-20260902
---

# Ikarus agent surface (G1-UI-05) — das Protokoll, der Verlauf, die Befehle

**Artefakt (autoritativ):** `../../docs/work-packets/G1-UI-05_IKARUS_AGENT_SURFACE.md`
(Packet mit Builder-Evidenz), `../../docs/superpowers/specs/2026-09-02-ikarus-agent-surface-design.md`
(Design-Record) und `../../docs/design/prototypes/cockpit-2026-09-02/` (Shots der laufenden App).

Der Owner wollte „Ikarus wie Hermes und Claude Code, und besser“. Die Antwort
dieser Runde: Claude Code zeigt, was ein Modell *aufgerufen* hat; Ikarus zeigt,
was der Kernel *quittiert* hat. Jede Antwort trägt ihr Protokoll — Route
(welche Laufzeit, warum, Zeitfenster), Kontext (was gelesen, was zurückgehalten),
Prüfung (Deny-Receipt), Antwort (Stempel + gemessene Wartezeit), Angebot,
Auftrag (Dispatch mit Übergabe-Zustand), Abbruch — ausschließlich aus Frames und
Envelope-Feldern, die das Backend tatsächlich geliefert hat. Dazu ein
Verlaufsrail aus einer neuen Read-only-Route über die kanonische Spine,
`/`-Befehle, die nur auf bestehende Routen und Seitenaktionen zeigen, und der
Aufwand-Schalter, der das seit einem Monat akzeptierte `effort` erstmals sendet.

Provenienz: MEASURED 2026-09-02 (137 pytest, 96/96 App-Spec, 130/130 Motion-Spec,
tsc sauber, Playwright 53/1 übersprungen/1 vorbestehender Fehlschlag, Audit-Floor
24/24, Registry-Digest exakt). Unabhängiger Review in frischem Kontext: keine
Release-Blocker, sechs Findings erledigt. Cross-Vendor-Zweitmeinung: ENTFALLEN
(Council 0/2 degradiert, Codex-Limit erschöpft bis 2026-09-07).

Offene Pruefschritte:

- [ ] Owner sieht sich Protokoll, Verlauf und `/`-Menü an und sagt, was bleibt
- [ ] `cockpit.spec.ts` „settings names the brain …“ erwartet vier Autonomiestufen, Quelle hat zwei — Drift seit 0d3ea5d1, wem gehört sie?
- [ ] `tools/gui_check.py` bricht vor jedem Spec ab (`@loopui` existiert in keinem Spec)
- [ ] Council-Adapter spawnt `codex`, Windows hat nur `codex.cmd`; Anthropic-Sitz braucht mehr als 120 s bei 75k Evidenz-Tokens
- [ ] Kosten/Token pro Turn bleiben ungezeigt, weil das Backend sie nicht pro Turn aufzeichnet — bewusst nicht erfunden
