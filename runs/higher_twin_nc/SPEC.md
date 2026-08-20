# ExperimentSpec: higher-twin-nc-v1

Experiment-ID: `higher-twin-nc-v1`
Spec-Revision: 2 (Schicht 2: Descent/Geometrie; Revision 1 = 30-Pass-Design vom 2026-08-18)
Status: PILOT — Änderungen nur mit Changelog; Einfrieren bei Confirmation-Registrierung
Iron-Klassifikation: EXPERIMENT (Gate 0 aktiv; kein Produktionspfad, keine Promotion)
Owner: repository owner
Expiry: 2026-10-31 oder früher per Kill-Kriterium
Angelegt: 2026-08-20

## Gegenstand

Eine revisionsgebundene, beweisquotientierte, nichtkommutative Algebra real
ausgeführter Softwareinterventionen über dem evidenzgefärbten Fourfold-Quiver.
Einziger Nutzenmaßstab: führt ein heutiger Source Tree unter versiegelten
zukünftigen Spezifikationsänderungen schneller zu verifizierten Nachkommen.

Schicht 2 (diese Revision) ergänzt: Footprint-Descent (Zertifikat, Anomalie,
Holonomie und OED als eine Obstruktionstheorie über dem Footprint-Site),
Adjunktions-Residuen-Training, History-Replay-Schocks und den
Kryptische-Varianz-Assay als Soundness-Test des Beweisquotienten.

## Scope und Isolation

- Alle Artefakte unter `runs/higher_twin_nc/`; keine Importe aus `daedalus/`;
  nur Python-Stdlib + pytest.
- Operatoren sind deterministische Texttransformationen: keine Modellcalls,
  keine Zufälle, keine Uhrenlesungen im Messpfad.
- Der Evaluator (`evaluate.py`, Ladder L0–L4) ist vom Interventionsmaterial
  versiegelt: Operatoren sehen weder Evaluatorinterna noch -ergebnisse.
- Fixtures werden nie in place mutiert; jeder Lauf kopiert den Baum.
- Kein Auto-Merge, keine Promotion, kein Zugriff auf Policy/Ledger/Evidence.

## Budget

- Pilotphase: ≤ 500 Fixture-Evaluatorcalls pro Tag, Wallclock ≤ 2 h pro Lauf.
- Modelltoken im Assay-Messpfad: 0 (deterministisch). Modelle treten erst in
  späteren, separat registrierten Generierungs-Armen auf.

## Evaluator (versiegelt, deterministisch)

L0 parse → L1 schema (Header/Typen) → L2 docs (Feld-, Typ-, Einheiten-Konsistenz
bidirektional) → L3 checks (Verhaltens-Checks des Fixtures, Subprozess) →
L4 digest (SHA-256 des Pipeline-Outputs als Verhaltensfingerprint).

## Hypothesen und Kill-Kriterien

- **H-NC-cal** (Kalibrierungshypothese, erzeugt KEINEN Befundstatus auf
  Autor-Fixtures): Reihenfolgeeffekte realer Patch-Paare existieren und sind
  prädizierbar (K_tree ≠ K_behave getrennt erhoben; K zusätzlich kontinuierlich
  als Wert-Distanz über dem Pipeline-Output, nicht nur Digest-Flag).
  Befundstatus erst auf extern gezogenen Fixtures (History-Replay-Korpus mit
  Kontaminationsattest). Kill dort: keine reproduzierbare
  Verhaltens-Nichtkommutation auf ≥ 4 externen Fixtures.
- **H-CERT** Footprint-Disjunktheit (Bernstein) ist ein SOUND
  Kommutationszertifikat. **Adjudikationsregel (vorregistriert):** Kommutiert
  ein zertifiziertes Paar messbar nicht, entscheidet der Footprint-Audit
  (gemessene Datei-/Spalten-Änderungen pro Operator, im Receipt) binär:
  weicht der gemessene Footprint von der Deklaration ab → das Paar zählt als
  H-ANOM-Treffer (Falschdeklaration/versteckte Kopplung); stimmt die
  Deklaration → H-CERT-Kill. Nie wahlweise beides.
- **H-ANOM** Kommutator-Anomalien (deklarierte Footprints disjunkt, aber
  K_behave ≠ 0 ODER asymmetrische Komponierbarkeit) detektieren versteckte
  Kopplungen. Validierung über Operatoren/Fixtures mit bekanntem
  Kopplungs-Ground-Truth (Lügner-Operator vs. ehrlicher Zwilling). Kill:
  Detektionsrate < 0,8 auf Ground-Truth-Kopplungen ODER Precision < Baseline
  (Co-Change/Duplikation) bei gleichen Kosten.
- **H-DESC** Descent-Checks pro Überdeckung ersetzen paarweise K-Assays
  (O(n²)→O(M)) ohne Präzisionsverlust und lokalisieren Obstruktionen. Kill:
  (1) nicht präziser als nacktes Footprint-Zertifikat; (2) Descent-Checks
  kosten mehr Evaluatorcalls als sie einsparen; (3) Obstruktionen instabil
  unter Wiederholung.
- **H-HOL** Interventionelle Holonomie auf Spec-Loops (apply;revert und
  kommutierende Quadrate, mit Kontroll-Loops als Null) ist ≠ 0 und prädiziert
  Adaptationskosten. Kill: Holonomie statistisch null — TOST mit
  vorregistrierter Äquivalenzmarge: kontinuierliche K-Wert-Distanz des Loops
  < 0,005 (0,5 % mittlere relative Abweichung) UND kein Baum-/Digest-Effekt —
  oder ohne Vorhersagekraft auf Held-out-Schocks.
- **H-LEAD** K-Profile (relativ zu einer Schockfamilie, nie ein Skalar)
  prognostizieren Adaptationskosten unter versiegelten Schocks besser als
  Duplikations-, Co-Change-, Größen- und Coverage-Baselines. Kill: kein
  Zusatznutzen über diese Baselines.
- **H-CRYPT** (Kryptische-Varianz-Assay) Zertifiziert verhaltensneutrale
  Edit-Wanderungen verändern die Wirkung eines eingefrorenen Probe-Sets
  (Flip-Rate steigt mit Walk-Länge L). Testprotokoll (vorregistriert für die
  Confirmation-Phase): ≥ 3 Basisrevisionen × L ∈ {0,2,4,8,16} × ≥ 8 Walks ×
  ≥ 10 Probes; Trendtest = einseitiger Jonckheere-Terpstra über L;
  positiv nur bei Flip-Rate(16) > 0 in ≥ 2 von 3 Revisionen NACH Abzug der
  footprint-überlappenden Flips. Drei Todesarten: Sampler-Tod (Akzeptanz
  zertifiziert neutraler Edits < 1 %), Null-Tod (Flip-Rate 0 über alle L nach
  Budget-Erschöpfung → liefert Evidenz FÜR einen owner-entschiedenen
  Dedup-Vorschlag; negatives Ergebnis wird archiviert), Artefakt-Tod (> 90 %
  der Flips im footprint-überlappenden Stratum; Schwelle ist eine
  vorregistrierte Konvention, keine kalibrierte Größe — sie wird nach dem
  ersten Ground-Truth-Lauf neu begründet oder das Kriterium fällt).
  Jeder Flip bei L=0 invalidiert den Lauf (Harness-Nichtdeterminismus).
- **H-EMERG** 16-Arm-G/H/N/F-Factorial aus Spec-Revision 1 bleibt unverändert.
  C (Descent/Krümmungs-Features) und O (OED-Assay-Wahl) werden NICHT in das
  Factorial gefaltet, sondern als gestufte, vorregistrierte Add-on-Kontraste
  evaluiert (keine stille 2^6-Inflation). Gegen Winner's Curse: der
  Gewinnerarm wird auf einem Selektions-Split bestimmt; C/O-Kontraste laufen
  auf frischen, nicht zur Selektion benutzten Fixtures/Schocks.
  Familienweise Fehlerkontrolle: hierarchisches Alpha-Budget über die
  Hypothesenfamilie (Reihenfolge H-CERT → H-ANOM → H-DESC → H-HOL → H-LEAD →
  H-CRYPT → H-EMERG; Weiterprüfung nur nach Signifikanz der Vorgänger,
  α = 0,05 pro Stufe).

## Methodische Vorbehalte

- Messkonstruktionsregel (2026-08-18): Autor schreibt Fixture UND Frage —
  fixture-interne Validierung ist Kalibrierung, kein Wirksamkeitsbeweis.
  Effektclaims erfordern externe Fixtures/Repos (History-Replay) mit
  Kontaminationsattest (Modell-Cutoffs vs. Repo-Zeitstempel).
- Kein universeller Krümmungs-/Evolvierbarkeits-Skalar (Masterplan §12):
  Output sind lokalisierte Obstruktionen und aufgabenrelative Profile.
- OED wird als Komposition bekannter Prinzipien (ABCI/FLINT/BAPP-Linie) auf
  ein neues Objekt geframt, nicht als neues OED-Prinzip.
- Negative Evidenz (inkl. degradierter Council-Receipt vom 2026-08-18) wird
  aufbewahrt.

## Stand der Messung

- 2026-08-20: Kalibrierlauf (Pipeline-Smoke, KEIN Effektbefund)
  `runs/pilot-20260820/` — Fixture `sensorlab` (vier Ebenen, echte Data
  Plane), 6 typisierte Operatoren + Sham, 38 Läufe, hash-verkettete Rezepte
  (chain verified; Kette ist Manipulations-INDIKATOR, keine
  Sicherheitsgarantie — ohne externen Anker ist sie rehashbar). Ergebnisse in
  `runs/pilot-20260820/kmatrix.json` und `report.md`: Sham = Verhaltensnull;
  2 asymmetrisch nichtkomponierbare Paare; 1 konstruktionsbedingt erwartete
  Verhaltens-Nichtkommutation (scale+clip; arithmetisch notwendig, kein
  Befund); alle 7 als disjunkt zertifizierten Paare baumidentisch kommutierend
  (konsistent mit Vorhersage; auf Autor-Fixtures konstruktionsnah, kein
  Soundness-Beweis); 5 konservative Zertifikats-Misses, alle strukturell aus
  dem Wildcard-Read von regen_docs (operatormix-abhängig, daher keine
  Prozentangabe als Instrumenteigenschaft); 0 Anomalien = Spezifität bei n=7
  Gelegenheiten, Sensitivität zu diesem Zeitpunkt ungemessen.
  Testsuite: 12/12 grün (TDD, RED zuerst).

- 2026-08-20 (Batch 2, nach adversarischem Doppel-Review Momus/Refuter,
  beide GO-WITH-CHANGES, alle Findings adressiert): Suite 26/26 grün.
  Vier frische Messkampagnen, alle Ketten mit externem Anker
  (receipt_head/receipt_count in den JSON-Artefakten) verifiziert:
  - `runs/pilot2-20260820/` Matrix v2 (38 Läufe): K jetzt kontinuierlich
    (scale+clip k=0.997); 6 konservativere Zertifikate nach
    rename-layout-Fix, alle baumidentisch; 0 Anomalien; gemessene
    Footprints (files_changed je Op) in jedem Receipt.
  - `runs/anomaly-20260820/` Ground-Truth-Kalibrierung: Lügner-Operator
    (liest pressure, deklariert nur voltage) + scale_pressure →
    deklariert-disjunkt, k=0.191 → ANOMALIE erkannt; ehrlicher Zwilling
    (identisches Verhalten, korrekte Deklaration) → conflict, keine
    Anomalie. Detektionsrate 1/1, Falschalarm 0/1 (n=1: Kalibrierung,
    kein Wirksamkeitsbeweis).
  - `runs/loops-20260820/` H-HOL-Pilot: rename-Roundtrip trivial
    (Negativkontrolle); scale-Roundtrip Verhaltens-Holonomie im Digest
    bei k_value=0.0 — reine Format-/Label-Holonomie, Wertebene
    äquivalent. Nichtinvertierbare Ops als ausgeschlossen dokumentiert.
  - `runs/cryptic-20260820/` H-CRYPT-Pilot: L0-Selbsttest bestanden,
    alle Walks neutral-zertifiziert, Flip-Rate 0 über L ∈ {0,2,4} —
    Null-Ergebnis des Piloten, als negative Evidenz archiviert (kein
    Null-Tod: Budget nicht erschöpft, Editfamilie minimal).
  - Depth-3-Vererbung (Descent-Vorhersage 1) als Test verankert: das
    paarweise zertifikat-disjunkte Tripel scale/tighten/add ist über
    alle 6 Permutationen baumidentisch.
- 2026-08-20 (Codex-Adversarial, Owner-Order „jeder Batch"): Erster Convene
  degraded (codex-.CMD-Shim, `not_on_path`; Bus
  `runs/council/council-20260820T172846Z-5ec1632b.jsonl`), Re-Convene mit
  Shim-Runner voll (`runs/council/council-20260820T173055Z-39bb23bc.jsonl`,
  advisory, gated nichts). 25 zeilengenaue Claims; 13 als Code gefixt
  (u. a. CWD-kanonischer Exec-Pfad für den Digest, Bytes-Digest statt
  errors=replace, stdout im Fehler-Digest, authentifiziertes L3,
  NaN-JSON-Sicherheit, Duplikat-Header, leere Verzeichnisse im Baum-Hash,
  Präkonditions-Mutations-Audit, Exception-Footprint,
  harness_alert-Trennung von Anomalie, PYTHONHASHSEED-Pinning,
  deterministisches Timeout-Y, Provenance- und Analysis-Receipts in der
  Kette + `verify_analysis`). Suite danach 39/39; Messkampagnen mit dem
  gehärteten Instrument neu gefahren, Kernzahlen unverändert.
  Dokumentierte Grenzen (akzeptiert, nicht versteckt):
  (a) die Evaluator-Versiegelung ist im Piloten eine Prozess-Konvention,
  keine Isolationsgrenze — Subprozess-/Capability-Isolation ist
  Confirmation-Arbeit; (b) das liar/honest-Paar kalibriert die
  Deklarations-Abweichungs-Mechanik des Detektors, nicht Kopplungsdetektion
  an sich (nicht-zirkuläre Validierung = Kopplung im Fixture-Code, Slice 1
  der Watchdog-Mission; dynamisches Spalten-Read-Tracing BACKLOG);
  (c) Receipts tragen Zeitstempel — Ketten-Heads sind bewusst nicht
  lauf-deterministisch (Provenienz vor Replay-Gleichheit); (d) der externe
  Vertrauensanker von Kette+kmatrix ist der Commit, der beide speichert —
  git ist der Anker, die Kette bleibt Manipulations-Indikator;
  (e) der Footprint-Audit misst Datei-Writes, keine Reads.

## Nächste Schritte (BACKLOG, nicht autoritativ)

Fixtures 2–4 (externe/variierte Profile gegen Autoren-Zirkularität),
reichere Neutral-Edit-Familie + größere L für H-CRYPT, Loop-Familie
erweitern (kommutierende Quadrate), Descent-Check-Prototyp mit
O(n²)→O(M)-Bilanz, History-Replay-Korpusaufbau mit Kontaminationsattest.
