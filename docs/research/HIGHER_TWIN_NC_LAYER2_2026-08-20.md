# higher-twin-nc, Schicht 2: Von der Algebra zur Obstruktionstheorie

Datum: 2026-08-20
Experiment: `higher-twin-nc-v1`, Spec-Revision 2 (`runs/higher_twin_nc/SPEC.md`)
Status: EXPERIMENT (Gate 0), Design + Erstmessung; keine Produktionsberührung

## 1. Der Schnitt von Schicht 2

Schicht 1 (30 Pässe, 2026-08-18) lernte eine statische Algebra der
Interventionen: beweisquotientierte nichtkommutative Pfadalgebra, Patches als
Bimodule, Kausalität aus A/B/AB/BA/Sham. Schicht 2 macht daraus eine
*Geometrie mit Selbstkalibrierung* — und kollabiert dabei Apparate statt neue
hinzuzufügen:

1. **Faserung.** Implementierungen sind über Spezifikationen gefasert
   (π: Impl → Spec ist eine Obligations-Anzeige, keine strikte Faserung;
   kartesische Lifts sind Hypothese, nicht Axiom). Adaptation = Lifting-Problem;
   die gelernte Policy ist ein approximativer Transport.
2. **Footprint-Descent (Vereinheitlichung).** Über dem Verband der
   Read/Write-Footprints einer Revision wird das Verhalten eine Prägarbe.
   Dann gilt: das Footprint-Disjunktheits-Zertifikat = Descent-Prädikat auf
   disjunkten Überdeckungen; eine Kommutator-Anomalie = lokalisierte
   Čech-1-Obstruktion (mit Adresse: welche Verklebung scheitert); Holonomie
   auf Spec-Loops = Kozykel-Bedingung derselben Verklebungsdaten; OED =
   maximale Spaltung des Identified Sets konsistenter Verklebungsdaten pro
   Evaluatorcall. Vier Mechanismen, eine prüfbare Gleichung. Cash-out:
   O(n²) paarweise K-Assays → O(M) Descent-Checks, plus zwei neue
   Vorhersagen (Überdeckungs-Vererbung der Kommutation auf ungetestete
   Paare; Residuen-Additivität genau auf Descent-Überdeckungen).
3. **Lens-Gesetze als Nullhypothesen.** PutGet/GetPut werden nicht gefordert,
   sondern ihre Verletzungsraten auf realen Ko-Änderungen gemessen.
4. **Adjunktions-Residuen.** propose ⊣ predict mit Unit/Counit-Residuen als
   Trainingssignal; zertifizierte Äquivalenz (nicht Stringgleichheit) ist der
   Gleichheitsbegriff. Residual-Hotspots steuern die Assay-Auswahl.
5. **History-Replay-Schocks.** Versiegelte Zukunft = reale Commitfolgen
   externer Repos nach Cutoff; Metrik = Adaptationskurve (Best-so-far-AUC
   über die Schockfolge), gemessen an PAAREN verhaltensgleicher Snapshots.
6. **Kryptische-Varianz-Assay (H-CRYPT).** Testet die Kernannahme des
   Beweisquotienten: Ist zertifizierte Verhaltensneutralität transitiv, oder
   verändert neutrale Drift die Wirkung zukünftiger Patches (Flip-Rate über
   Walk-Länge)? Liefert Evidenz für einen owner-entschiedenen Vorschlag zur
   Ariadne-Archivfrage (Fingerprint-Dedup vs. Neutralitäts-Diversität als
   Ressource) — entscheidet sie nicht.

Leitgedanke (Motivations-Metapher, KEINE Definition und kein Skalar):
Nichtkommutation lebt dort, wo Patches lesen, was sie schreiben; rein additive
Wörter kommutieren. „Krümmung" ist immer relativ zu einer benannten
Schockfamilie und einem deklarierten Änderungsverkehr — H-LEAD behauptet, dass
billige lokale K-Profile (aufgabenrelativ, nie ein einzelner Repo-Score)
heutige Bäume nach morgigen Adaptationskosten ordnen.

## 2. Ehrliche Neuheitsverengung (Sweep 2026-08-20, alle URLs verifiziert)

| Feld | Besetzt durch | Bleibt offen |
| --- | --- | --- |
| Patch-Kommutation strukturell | darcs-Patch-Theorie; [Mimram/Di Giusto](https://arxiv.org/abs/1311.3903); Pijul/[jneem](https://jneem.github.io/merging/); Mazurkiewicz-Traces; OT/CRDT | Verhaltenskommutation unter versiegeltem Evaluator als kontinuierliche Messgröße und Quotientenrelation |
| Semantische Interferenz | [SafeMerge](https://arxiv.org/abs/1802.06551); [SAM](https://arxiv.org/abs/2310.02395) (ausgeführte Base/Left/Right/Merge-Assays, binäres Flag) | geordneter Kommutator K(A,B) aus AB vs. BA; K_tree/K_behave-Trennung; Akkumulation im Beweisquotienten. (Kontinuierliches K ist erst beansprucht, seit die Wert-Distanz-Metrik implementiert ist — ein Digest-Flag allein wäre SAM-Terrain.) |
| Aktionen-Kommutation | Lipton-Movers, [dynamische Reduktionen](https://arxiv.org/abs/1611.09318) | Patches als Evolutionseinheiten statt Programmschritte |
| Lens-Gesetze | [Nakano](https://arxiv.org/abs/1910.10421); [Diskin ala-Lenses](https://arxiv.org/abs/1911.12904); Benchmarx ([SoSyM](https://link.springer.com/article/10.1007/s10270-019-00752-x)); [Bifrons](https://arxiv.org/abs/2502.18954) | Gesetze als empirische Nullhypothesen mit Verletzungsraten über reale Commit-Historien |
| Hidden-Coupling-Detektion | Co-Change-Mining; [CPDA](https://arxiv.org/abs/2104.09107); [SSHOM](https://arxiv.org/abs/2104.11005) | Kommutator-Anomalie (Footprints disjunkt, K≠0) als interventioneller Detektor |
| OED in Software | [ABCI](https://arxiv.org/abs/2206.02063); [Zhang et al.](https://arxiv.org/abs/2209.04744); FLINT (10.1145/2491509.2491513); [BAPP](https://arxiv.org/abs/2212.13773) | OED über Patch-PAAR-Assays zur Eingrenzung algebraischer Relationen (als Komposition geframt) |
| Temporale Repo-Evaluation | [SWE-bench](https://arxiv.org/abs/2310.06770); [SWE-rebench](https://arxiv.org/abs/2505.20411); [SWE-MERA](https://arxiv.org/abs/2507.11059); [Time-Consistent Benchmark](https://arxiv.org/abs/2603.26137); [SWE-Future](https://arxiv.org/abs/2606.18733); [LiveCodeBench](https://arxiv.org/abs/2403.07974) | Paare verhaltensgleicher Snapshots unter identischer versiegelter Commit-SEQUENZ; Adaptationskurven statt Einzel-Issues |
| Descent/Obstruktion | Abramsky–Brandenburger (Kontextualität als Garben-Obstruktion); Separation-Logic-Frame-Rule; Goguen | Descent als budgetierte, falsifizierbare MESSHYPOTHESE auf Patch-Interferenz; Scheitern selbst ist das Produkt (Kopplungs-Adresse) |
| Neutrale Varianten | Schulte/Forrest (Mutational Robustness); Harrand/Baudry (Neutral Variants); Wagner; Paaby/Rockman | zweite Ordnung: kausaler Effekt zertifizierter Neutralität auf ein eingefrorenes Probe-Set (Dosis-Wirkung, Sham-kalibriert) |

Vault/Repo-Recon: Der Faden ist neu (Absence-Befund über vault/ und
docs/research/); nächste hausinterne Verwandtschaft ist das verblindete
A/B-Harness `runs/ab/` (Muster für versiegelte Arm-Zuordnung).

## 3. Refinement-Pässe 31–45

31. Kommutatornorm gelernter Matrizen erneut verworfen; nur interventionelle
    Holonomie auf zertifizierten Loops zählt (Basisunabhängigkeit).
32. Strikte Faserung verworfen; π ist Obligations-Anzeige, kartesische Lifts
    sind Hypothese.
33. Lens-Gesetze von Axiomen zu Nullhypothesen degradiert; Verletzungsrate
    wird Messgröße.
34. 2^6-Factorial verworfen; C und O nur als gestufte, vorregistrierte
    Add-on-Kontraste auf dem Gewinnerarm.
35. Patch-Reihenfolge ≠ Ausführungs-Reihenfolge: rein additive Editpaare
    kommutieren trivial; Nichtkommutation lebt, wo Patches lesen, was sie
    schreiben (Generatoren, Werttransformationen, Anker).
36. Daraus: Footprint-Disjunktheit (Bernstein) als erste Beweisregel für den
    Quotienten — Trace-Theory/darcs/Pijul-Vorarbeit anerkannt; Neuheit nur
    evaluator-semantische Kommutation plus Anomalienutzung.
37. Anomalie-Instrument: disjunkte Footprints + K_behave ≠ 0 = versteckte
    Kopplung mit Adresse; Kandidat für ein produktnahes Nebenprodukt —
    Status erst nach Ground-Truth-Validierung, Übernahme nur owner-entschieden.
38. Descent-Vereinheitlichung akzeptiert: Zertifikat/Anomalie/Holonomie/OED
    sind eine Obstruktionstheorie; Streichung von vier Apparaten zugunsten
    einer Gleichung — mit eigenen Kill-Kriterien.
39. Adjunktion exakt verworfen; nur Residuen-Training mit zertifizierter
    Äquivalenz als Gleichheit.
40. OED über vollem Posterior verworfen; nur die entscheidungsrelevante
    Partition (nominate/abstain) zählt; als Komposition bekannter Prinzipien
    geframt (ABCI/FLINT/BAPP-Linie), nicht als neues OED.
41. Loop-Assays brauchen Sham-Loops (apply;revert) als Null; K_tree und
    K_behave werden getrennt erhoben, Quotient nur nach unabhängigem Beweis.
42. History-Replay nur mit Kontaminationsattest je Modell und Repo-Zeitstempel
    (Anschluss an Two-Judge-Expedition); eng verteidigen gegen SWE-Future und
    das A/B-Design des Time-Consistent Benchmarks.
43. Universeller Krümmungsskalar verboten (Masterplan §12); K-Profile bleiben
    aufgabenrelativ, Obstruktionen lokalisiert.
44. H-LEAD muss statische Duplikations-/Co-Change-Baselines schlagen, nicht
    nur Größe/Coverage.
45. Der heutige Lauf ist Pipeline-Smoke plus erste Dateneinspeisung, kein
    Effektclaim (Messkonstruktionsregel: Autor schreibt Fixture und Frage).

## 4. Kalibrierlauf (Pipeline-Smoke, 2026-08-20 — kein Effektbefund)

`runs/higher_twin_nc/runs/pilot-20260820/` — Fixture `sensorlab`, 6 Operatoren
+ Sham, 38 Läufe, Rezeptkette verifiziert (Kette ist Manipulations-Indikator,
keine Sicherheitsgarantie). Auf einem autorenkonstruierten Fixture sind diese
Zellen konstruktionsnah — sie kalibrieren das Instrument, sie beweisen nichts:

- Sham ist exakte Verhaltensnull (Baum ändert sich, Y nicht).
- J_noncomp zeigt sich asymmetrisch: rename→scale und rename→clip scheitern
  an Präkonditionen, die Gegenrichtung komponiert.
- scale∘clip ≠ clip∘scale im Digest — arithmetisch erwartet, dient als
  Positivkontrolle der Messkette, nicht als Entdeckung.
- Alle 7 als disjunkt zertifizierten Paare kommutieren baumidentisch
  (konsistent mit der Zertifikatsvorhersage); die 5 konservativen Misses
  stammen sämtlich aus dem Wildcard-Read von regen_docs — die
  Vollständigkeitsquote ist operatormix-abhängig und wird nicht als
  Instrumenteigenschaft beziffert.
- 0 Anomalien = Spezifität bei 7 Gelegenheiten; Sensitivität war zu diesem
  Zeitpunkt ungemessen (Ground-Truth-Kopplung folgt im Anomalie-Assay).

Testsuite: 12/12 grün (TDD; RED per ModuleNotFoundError dokumentiert).
Sweep-Auditierbarkeit: Titel/URLs/Verifikationsflags der Prior-Art-Recherche
liegen als Receipt in `runs/higher_twin_nc/receipts/priorart-sweep-20260820.json`.
