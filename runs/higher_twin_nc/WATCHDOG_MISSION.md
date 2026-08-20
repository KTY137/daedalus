# Watchdog-Mission: higher-twin-nc-v1 Ausbau (EXPERIMENT, Gate 0)

Du arbeitest ausschließlich am isolierten Iron-Plan-EXPERIMENT
`runs/higher_twin_nc/` (Spec: `runs/higher_twin_nc/SPEC.md` — zuerst lesen,
danach `docs/research/HIGHER_TWIN_NC_LAYER2_2026-08-20.md`). Klassifikation
jeder Handoff-Meldung: `Iron Plan: EXPERIMENT`, `Iron Gate: 0`.

## Harte Grenzen (nicht verhandelbar)

- Schreibe NUR unter `runs/higher_twin_nc/**`, `docs/research/HIGHER_TWIN_NC*`,
  `vault/Sessions/` und `vault/Findings/` (vault append-only, Provenienz
  stempeln: MEASURED/INHERITED/ASSUMED).
- Niemals: Policy-Artefakte (Masterplan, AGENTS.md, .agentenv/, .githooks/,
  Guards), `daedalus/`-Produktionscode, Promotion irgendeiner Art, git push.
- TDD ist Pflicht: kein Produktionscode ohne vorher roten Test.
- Jeder Messlauf in ein FRISCHES out_dir unter `runs/higher_twin_nc/runs/`
  (die Harness ist fail-closed gegen Receipt-Append); receipt_head/count
  müssen im JSON-Artefakt verankert und mit
  `assay.verify_chain(path, expected_head=..., expected_count=...)` geprüft
  werden.
- Deterministisch bleiben: keine RNG, keine Uhrzeit im Messpfad, keine
  Modellcalls im Assay.
- Vor jedem Commit: `python tools/iron_plan_guard.py verify` und die volle
  Suite `python -m pytest runs/higher_twin_nc/tests -q` (muss grün sein).
  Committe nur Experiment-Dateien; niemals fremde Arbeitsbaum-Änderungen.

## Arbeitsliste (in dieser Reihenfolge, je Slice: Test → Code → Messlauf → Commit)

1. **Fixture 2 `pumplab`**: gleiche Dateistruktur wie `fixtures/sensorlab`,
   aber 5 Felder und eine ECHTE versteckte Kopplung im Fixture-Code selbst
   (calib.py liest eine zweite Spalte in die Kalibrierung ein, z. B.
   Druckkorrektur). Operatoren generisch parametrisieren (Feldnamen als
   Parameter, `standard_ops(profile)`), Matrix + Anomalie-Assay laufen lassen.
   Erwartung dokumentieren, Ergebnis MEASURED stempeln.
2. **Fixture 3 `chemlab`**: rein additiv-kommutatives Profil (erwartete
   Anomalie-Null, viele Zertifikate) als Spezifitäts-Fixture.
3. **Fixture 4 `textlab`**: knowledge-lastiges Profil (mehr Docs-Operatoren,
   regen-Varianten) als Vollständigkeits-Stressor der Footprint-Regel.
4. **H-CRYPT ausbauen**: Neutral-Edit-Familie erweitern (Whitespace-,
   Kommentar-, Reorder-Varianten in calib.py UND checks.py), L ∈ {0,2,4,8,16},
   pro L mehrere deterministisch nummerierte Walk-Varianten; Flip-Raten je
   Fixture in `runs/cryptic-<datum>/cryptic.json`.
5. **Loop-Familie erweitern**: kommutierende Quadrate (zwei disjunkte Ops
   hin, in vertauschter Reihenfolge zurück) als Holonomie-Messung zweiter
   Ordnung; Klassifikation wie in loops.py.
6. **Descent-Prototyp**: für jede Überdeckung (Partition der Felder) EIN
   Check-Assay statt aller Paare; Bilanz gemessene Assays vs. eingesparte
   Paare in ein JSON-Artefakt.
7. Nach jedem abgeschlossenen Slice: `vault/Sessions/<datum>.md` um eine
   MEASURED-Zeile ergänzen (append-only).

## Definition of done

Alle 6 Slices committed, Suite grün, alle Ketten anker-verifiziert, SPEC
"Stand der Messung" fortgeschrieben. Dann MISSION_COMPLETE schreiben (Pfad
siehe Watchdog-Protokoll). Wenn nur noch Owner-Entscheidungen offen sind:
BLOCKED mit exakter Frage.
