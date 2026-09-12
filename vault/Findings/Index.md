---
tags:
- findings
- dashboard
created: 2026-08-17
permalink: main/findings/index
---

# Findings — Untersuchungsergebnisse

Jede Notiz hier ist eine **Link-Notiz**: kurze Einordnung + relativer Pfad zum
autoritativen Artefakt im Repo. Nie kopieren — `docs/` bleibt die Quelle.

## Index

- [[Windows-Portability-20260817]] — Windows-Portabilitätsbefunde der Recovery-Session
- [[Branch-Cleanup-20260817]] — Branch-Aufräumaktion: Manifest + absorbierte Branches
- [[Gate0-Recovery-Patches]] — drei Recovery-Patches (fsync/readonly, release-CLI-Import, Fixtures)
- [[Higher-Twin-NC-Erstmessung-20260820]] — erste K-Matrix des Interventions-Assays (38 Läufe, Kette verifiziert)
- [[Vet-Py-Adversarial-Review-20260821]] — vet.py GO-WITH-CHANGES: Frontmatter ungescannt, MCP nie BLOCK, 3 Guards ungetestet

- [[Cockpit-Themes-20260825]] — sechs Gallery-Entwuerfe werden Themes eines laufenden Cockpits (echte Daten, Fake-Data-Test)

- [[Nested-Checkout-Instrumentenausfall-20260826]] — ein Checkout im Checkout schaltete drei Instrumente still ab (573->94, 3242 von 3622)
- [[Vet-Review-20260826]] — vet.py hält unter Sondierung; MCP-Filesystem-Grant ist für das Gate unsichtbar (clear bei Wurzel C:/)
- [[Ikarus-Agent-Surface-20260902]] — Ikarus zeigt, was der Kernel quittiert hat: Protokoll pro Antwort, Verlauf aus der Spine, /-Befehle (G1-UI-05)

- [[Handle-Anchoring-Is-Not-Containment-20260905]] — Datei-Adapter G1-IKARUS-24: Handle-Verankerung schließt Link-Pflanzen, erst Delete-Share-Pinning schließt das Hinausbewegen; Cerberus BLOCK beantwortet, Zaun bleibt

- [[Wiki-Regeneration-20260905]] — docs/wiki mit 10 Autoren regeneriert (74 Seiten, Verify PASS, 88,7 % Modulabdeckung); Planer/Verifier zaehlten Bundle- und Wheel-Kopien als Quelle, G1-WIKI-01 schliesst das mit `treewalk`

- [[First-Completed-Computer-Mission-20260906]] — G1-IKARUS-32: Fortschrittsprompt lässt den 7B lesen, aber nicht abschließen; Codex-Planner erreicht erstmals `finish`; Momus-Review und measure-10 retained

- [[Remote-Planner-Owner-Choice-20260906]] — G1-IKARUS-43: Owner-Freigabe für den Remote-Planner umgesetzt (transiente Bestätigung, Secret-Floor auf Beobachtung und Prompt, Planner-Zeile im Status)

- [[Web-Bundle-Platform-Drift-20260912]] - Vite erzeugt plattformabhaengige JS-Chunk-Hashes; der Linux-PR-Build ist die kanonische Dist-Drift-Pruefung (PR #382)

Neue Findings: Template [[../Templates/Finding|Finding]] nutzen.