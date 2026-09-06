---
tags: [findings, wiki, knowledge-plane]
created: 2026-09-05
source: docs/wiki, docs/work-packets/G1-WIKI-01_TREEWALK_FROZEN_BUNDLES.md
---

# Wiki-Regeneration und Instrumentenbefund 2026-09-05

**Artefakt (autoritativ):** [docs/wiki/index.md](../../docs/wiki/index.md), [G1-WIKI-01](../../docs/work-packets/G1-WIKI-01_TREEWALK_FROZEN_BUNDLES.md), [runs/wiki_findings_20260905.md](../../runs/wiki_findings_20260905.md), [runs/wiki_verify.json](../../runs/wiki_verify.json)

Einordnung: Zehn parallele Opus-Autoren haben `docs/wiki` von Juli auf den heutigen Code gebracht (63 Modulseiten, eine je Quellverzeichnis, relative Links statt Wikilinks, „Ungeklaert"-Abschnitt je Seite); der deterministische Verifier gibt PASS. Dabei zeigte sich, dass Planer und Verifier eingefrorene Kopien des Pakets (PyInstaller-Bundles, Wheel-Builds) als Quelle zaehlten -- ein Instrumentenfehler derselben Klasse wie der [Nested-Checkout-Ausfall vom 26.08.](Nested-Checkout-Instrumentenausfall-20260826.md), jetzt mit einem gemeinsamen Walker (`treewalk`) und Positivkontroll-Tests geschlossen. Die Abweichungsliste der Autoren ist gemeldet, nicht verifiziert; ihr Abschnitt A wurde von der Review-Session gegen das Effekt-Register gemessen und ist keine Registry-Luecke.

Provenienz: MEASURED (Verify, Tests, Laufzeiten), INHERITED (Autoren-Abweichungen B-F)

Offene Pruefschritte:

- [ ] Abweichungen B-F der Findings-Datei je Lane nachmessen (B1 Mutationsskript, D1 security.py-Vertraege, D5 Konstantenname)
- [ ] Entscheiden, ob Testmodule als `uncovered_module` zaehlen sollen (777 Module im Nenner)
- [ ] Eigene Zeile `cli.canary` mit `begin_effect` als Folgepacket (heute unter `cli.daedalus`, gate0.not_central)
