# Ergebnisse `tensor-embedding-v4` — das Gewinn-Regime existiert, und es ist Algebra, nicht Lernen

Datum der Auswertung: 2026-08-26 (Athena). Läufe: 2026-08-25.
Artefakte: `arm_n.json`, `arm_p.json`, `arm_q.json` in diesem Verzeichnis.
Substrat: `project_tct`, 411 Kandidaten-Quelldateien, 168 Anfragen
(135 zurückgehalten / 33 im Training), Split identisch zu Arm J
(`rng(31)`, 20 % keep). Alle Zahlen `[MEASURED]`, direkt aus den JSONs.

**Dieses Verdikt wertet die VOR dem Lauf eingefrorenen Win-Conditions aus.
Es ist noch NICHT unabhängig adversarial gegengelesen — die Verifikation, die
die SPEC verlangt, steht aus und dieses Dokument ersetzt sie nicht.**

---

## 1. Verdikt gegen die eingefrorenen Win-Conditions

| Bedingung | Schwelle | Gemessen | Verdikt |
| --- | --- | --- | --- |
| **A** — Tensor-Familie schlägt BM25 allein (R@10, 135 Holdout) | > 0,474 | Arm P, f1-Kontraktion allein: **0,652** | **ERFÜLLT** |
| **B** — Fusion mit Tensor schlägt Fusion mit roher Struktur (R@10, 168) | > 0,601 | RRF(f1, BM25): **0,667** | **ERFÜLLT** |
| **C** — Abkürzungs-Regime (Arm L/O) | 3× Trigramm UND R@10 ≥ 0,15 | — | **NICHT GELAUFEN** |
| Q1 — BM25+Expansion > BM25 (R@10, 168) | > 0,482 | 0,506 | erfüllt, knapp |
| Q2 — BM25+Expansion hebt R@1 | > 0,167 | 0,161 | **VERFEHLT** |

Zwei der drei Hauptbedingungen sind erfüllt; eine ist nicht gelaufen und
bleibt offen, nicht bestanden. Arm M (Pfad-Materialisierung) ist ebenfalls
nicht gelaufen (Skript existiert, kein Artefakt).

## 2. Die Zahlen nebeneinander (R@10, alle 168 Anfragen)

| Verfahren | @1 | @10 | @25 | Familie |
| --- | --- | --- | --- | --- |
| Zufall | — | 0,024 | — | — |
| BM25 (Referenz, reproduziert) | 0,167 | 0,482 | 0,643 | lexikalisch |
| `doc_neighbour` (v3) | 0,060 | 0,333 | 0,464 | anfrageunabhängiger Prior |
| BM25 + Struktur (v3-Fusion) | 0,095 | 0,601 | 0,768 | Fusion |
| **Arm P: f1-Kontraktion allein** | **0,196** | 0,643 | 0,804 | **Tensor-Algebra, kein Lernen** |
| **Arm P: RRF(f1, BM25)** | 0,185 | **0,667** | **0,857** | Fusion |
| Arm N: PPR (uniform) allein | 0,196 | 0,673 | 0,804 | Graph-Diffusion, KEIN Tensor |
| Arm Q: BM25 + Feld-Expansion | 0,161 | 0,506 | 0,631 | Anfrage-Expansion |
| ComplEx gelernt (v3, Arm J) | 0,007 | 0,022 | 0,052 | gelerntes Embedding |

Auf den 135 Holdout-Paaren hält alles: f1 0,652 / RRF 0,682 / PPR 0,593
gegen BM25 0,474.

## 3. Was das Ergebnis IST — und was nicht

**Was gewonnen hat, ist geschlossene Tensor-Algebra über dem deterministischen
Twin.** Arm P behandelt den Twin als Tensor X[h,r,t] und bildet typisierte
Zwei-Hop-Pfadzählungen durch Kontraktion von Relations-Slices
(f1 = mentions ∘ documents ∘ in_module) — kein Gewicht, kein Training, kein
Hyperparameter. Das schlägt BM25 deutlich und hebt — anders als jede Fusion
zuvor — auch R@1 (0,196 > 0,167): genau das, was Q2 wollte und die
Popularitäts-Fusion nachweislich nicht konnte.

**Was verloren bleibt, ist das gelernte Tensor-Embedding.** ComplEx auf
derselben Aufgabe: 0,022. v1–v3 bleiben als negative Evidenz stehen; v4
widerlegt sie nicht, v4 zeigt, dass der Wert des Twins in seiner *Struktur*
liegt, nicht in einem daraus gelernten latenten Raum.

**Der beste Einzelwert gehört keinem Tensor.** PPR (uniform) allein erreicht
0,673 — Graph-Diffusion, anfrageabhängig, ebenfalls ohne Lernen. Die
Tensor-Lesart darf diese Zahl nicht absorbieren: Kontraktion und PPR sind hier
zwei Formen desselben Befundes, *anfrageabhängige Strukturausbreitung schlägt
lexikalische Suche*, und die Algebra-Form ist die typisierte, erklärbare davon
(f1 sagt, WELCHER Pfad zählt; ein PPR-Score sagt das nicht).

## 4. Selbstkontrollen der Läufe (bestanden, aus den Artefakten)

- Leak-Control Arm P: volles M4 als Feature ⇒ R@25 = 1,0 wie konstruiert
  (`passed: true`); Leak-Audit: 0 Test-Kanten in M4-Train, 0 in M5,
  0 `.py`-Ziele in `links_to`.
- Kandidatensymmetrie: 411 Kandidaten für alle Verfahren; BM25-Referenz
  in Arm P und Arm Q unabhängig reproduziert (0,482).
- Arm N: 0 Treffer aus Restart-Masse allein (`zero_restart_hits_at_25: 0`).
- Arm Q Leckage-Verriegelung: Anfrage-Knoten samt aller Kanten vor der
  Expansion entfernt.

## 5. Offen — in dieser Reihenfolge

1. **Unabhängige adversariale Lesung** (SPEC-Pflicht) mit der Fehlerliste vom
   2026-08-25. Bis dahin ist dieses Verdikt eine Autoren-Auswertung.
2. **Ein zweites Substrat.** Alles hier ist EIN Repository, EIN Split-Seed.
   Die Kill-Kriterien des Masterplans (§14) verlangen Held-out-Repositories,
   bevor irgendetwas hiervon ein PRIOR-Update begründet.
3. Arm C/L/O (Abkürzungs-Regime) und Arm M — nicht gelaufen, nicht gestrichen.
4. Erst danach die Produktfrage: f1-Kontraktion als Retrieval-Baustein im
   Atlas wäre ALIGNED-Arbeit (§9.1, regenerierbare Query-Schicht), aber sie
   beginnt nicht vor 1.–2.

Iron Plan: EXPERIMENT (v4-SPEC, eingefroren 2026-08-25)
Iron Gate: 0
Evidence: die drei JSONs in diesem Verzeichnis; jede Zahl oben ist daraus.
