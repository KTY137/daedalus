---
tags:
- findings
created: 2026-08-25
source: apps/web
permalink: main/findings/cockpit-themes-20260825
---

# Cockpit 2026-08-25 — die sechs Entwuerfe werden Themes einer laufenden Oberflaeche

**Artefakt (autoritativ):** `../../docs/design/prototypes/cockpit-2026-08-25/`
(README, index.html, sechs Screenshots, manifest.json) und
`../../apps/web/src/cockpit/` + `../../apps/web/src/theme/`.

Die Gallery-Runde vom 24.08. war als Auswahlentscheidung angelegt: sechs
Entwuerfe, einer gewinnt. Der Owner hat stattdessen einen Theme-Editor mit
mehreren Themes verlangt, und das aufloest die Runde: ein Theme traegt hier
Farbe, Schrift, Material **und Aufbau**, also genau die Achse, auf der die sechs
Entwuerfe verschieden sein sollten. Alle sechs sind eingebaut, alle sechs
editierbar, ein siebtes braucht keine neue Design-Runde. Die Screenshots im
Artefaktordner sind Aufnahmen der laufenden Anwendung gegen die lokale API, mit
Manifest — keine Mockups.

Provenienz: MEASURED (7/7 Cockpit-Specs gruen gegen das gebaute Bundle und den
laufenden Server; tsc sauber; Mutationsprobe am Fake-Data-Guard)

Offene Pruefschritte:

- [ ] Owner sieht sich die sechs Themes an und sagt, welche bleiben
- [ ] `/api/capabilities` und `/api/context/plan` haben weiterhin keinen Aufrufer
- [ ] Depesche (Bogenfigur) ist die unfertigste der sechs
- [ ] `degraded.spec.ts` der alten Oberflaeche: Fehler werden erst nach der
      langsamsten Quelle derselben Fan-out-Runde gemeldet