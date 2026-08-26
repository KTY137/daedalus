# `tensor-embedding-v3`, Arme F–I: der Tensorraum auf echten Daten

Datum: 2026-08-25. Fortsetzung von `RESULTS.md` (Arme D, E).
Werkzeuge: PyKEEN 1.11.1, torch 2.13.0+cpu, in einem isolierten venv unter dem
Scratchpad — die Python-Umgebung des Repositories wurde **nicht** verändert.
Owner-Freigabe zur Installation: 2026-08-25.

---

> **KORREKTUR 2026-08-25, nach der Erstfassung.** Der zentrale Befund unten —
> „der lernbare Kern enthält keine einzige Cross-Plane-Kante" — war **falsch**.
> Er war ein Artefakt meines Knotenentwurfs, keine Eigenschaft des
> Repositories. Ich hatte Doku-Erwähnungen **pro Datei** modelliert
> (`knowledge:mention:DOC#danger_gate`); damit hat jede Erwähnung genau zwei
> Kanten und stirbt in jedem 3-Kern zwangsläufig, unabhängig vom Korpus. Ein
> Konzept ist eine Sache, die an vielen Stellen erwähnt wird. Nach der Umstellung
> auf konzeptbasierte Knoten (`knowledge:concept:danger_gate`):
>
> | | pro Datei (Artefakt) | pro Konzept (korrigiert) |
> | --- | --- | --- |
> | Daedalus, 3-Kern | 11,4 % | **20,3 %** |
> | Daedalus, Wissensebene im Kern | 6 | **3 332** |
> | Daedalus, `documents` überlebend | 0 / 1368 | **618 / 1368 = 28,3 %** |
> | project_tct, 3-Kern | 5,8 % | **13,3 %** |
> | project_tct, Wissensebene im Kern | 0 | **968** |
> | project_tct, `documents` überlebend | 0 / 3059 | **300 / 1153 = 26,0 %** |
>
> **Was nach der Korrektur stehen bleibt:** die **Datenebene** stirbt wirklich.
> `realises_field` überlebt in beiden Repositories mit 0 von 816 bzw. 0 von 0,
> und die Datenebene taucht in keinem der beiden 3-Kerne auf. Der tote Punkt ist
> also real, aber er liegt bei Daten und Typen, nicht beim Wissen.
>
> Abschnitte 1 und 3 unten sind in ihrer Zahlenlage überholt; sie bleiben als
> aufbewahrte Fehlmessung stehen (§2 zählt die Irrtümer, das hier ist der
> siebte). Abschnitt 4 gilt unverändert und wird durch die Korrektur eher
> gestützt: der Hebel ist die Kantendichte, und konzeptbasierte Knoten waren
> bereits ein Hebel, der 0 % auf 26–28 % gehoben hat, ohne dass eine einzige
> Zeile Dokumentation dazugekommen wäre.

## 1. Urteil (überholt, siehe Korrektur oben)

Nach v1 (Bindung verliert gegen Slots) und v2 (Stelligkeit kauft nichts) war die
offene Frage: kauft ein **gelernter** Tensorraum etwas für Cross-Plane-Retrieval?

**Die Antwort ist gemessen, und sie ist unbequem:** Der Teil des echten Twins,
auf dem ein gelerntes Embedding überhaupt arbeiten kann, enthält **keine
einzige Cross-Plane-Kante**.

```
Echter Fourfold-Graph dieses Repositories:  225 468 Entitäten, 355 390 Tripel, 16 Relationen
                                            Ø-Grad 3,15, Median 1, 59,1 % genau einmal gesehen

Lernbarer 3-Kern:                            25 696 Entitäten = 11,4 % des Twins
                                            Ø-Grad 8,15
                                            Ebenen: code 24 695 | type 995 | knowledge 6 | data 0
                                            Cross-Plane erhalten: documents 0, realises_field 0
```

Die Cross-Plane-Kanten — `documents` (7534) und `realises_field` (1322) im
Vollgraphen — sitzen ausnahmslos auf Knoten mit Grad 1 oder 2 und fallen beim
Ausdünnen komplett weg. Genau das, was die Vier-Ebenen-Hypothese ausmacht, ist
der Teil, den ein Embedding nicht sehen kann.

## 2. Der Weg dorthin, mit den Irrtümern

Vier Arme, jeder hat einen Fehler des vorherigen aufgedeckt.

| Arm | Was gemessen wurde | Ergebnis |
| --- | --- | --- |
| **F** | PyKEEN ComplEx, synthetischer Twin-Korpus, binär vs. n-är reifiziert | beide auf Zufallsniveau (hits@10 0,003–0,006) |
| **F-Kontrolle** | Standard-Zufallssplit auf demselben Graphen | ebenfalls Zufallsniveau (0,0024 gegen 0,0028) |
| **G** | ComplEx auf dem **echten** Import-Graphen | hits@10 = 0,0176 gegen Zufall 0,0036 → **5× Lift** |
| **H** | Extraktion des echten Fourfold-Graphen, 16 Relationen | Ø-Grad 3,15, 59,1 % Knoten einmal gesehen |
| **I** | 3-Kern des echten Graphen + ComplEx | Kern = 11,4 % des Twins, **null Cross-Plane** |

**Der Wendepunkt war die F-Kontrolle.** Als auch der Standard-Split scheiterte,
war klar: nicht die Aufgabe war schuld, sondern das Substrat. Die Messung
danach:

| Graph | Entitäten | Tripel | Ø-Grad |
| --- | --- | --- | --- |
| mein synthetischer Korpus | 3 623 | 4 875 | 2,7 |
| echter Import-Graph | 2 794 | 13 946 | **9,98** |
| FB15k-237 (KGE-Standard) | 14 541 | ~310 000 | ~42 |

**Mein Substrat war viermal zu dünn.** Damit sind Arm E und Arm F keine
Aussagen über Tensoren, sondern über meinen Korpus. Sie sind hier als
Negativevidenz aufbewahrt, nicht als Ergebnis.

## 3. Was das für den Tensorraum heißt

Drei Aussagen, in absteigender Sicherheit:

1. **Gemessen:** Auf der Code-Ebene allein lernt ComplEx etwas — 5× über
   Zufall auf dem Import-Graphen. Absolut bleibt es schwach (hits@10 0,018,
   wo dasselbe Modell auf WN18RR ~0,50 erreicht), mit **Standard-Hyper-
   parametern und zwei Relationstypen**. Die PyKEEN-Großevaluation sagt, dass
   genau diese Konfiguration den Ausschlag gibt; die Zahl ist daher eine
   Untergrenze, kein Urteil über das Modell.
2. **Gemessen:** Der lernbare Kern des Twins ist 11,4 % seiner Knoten und
   praktisch reine Code-Ebene. Datenebene 0, Wissen 6, Cross-Plane 0.
3. **Folgerung, nicht gemessen:** Ein Embedding-basierter Retrieval-Dienst über
   den Twin würde heute die Code-Ebene bedienen und bei jeder
   Cross-Plane-Frage auf Namensähnlichkeit zurückfallen — also auf das
   Verfahren, das v1 und v2 bereits als Sieger gemessen haben.

## 4. Was den Kern dichter machen würde — die eigentliche Arbeit

Das Problem ist **nicht das Modell und nicht die Repräsentation**. Es ist die
Kantendichte auf den Nicht-Code-Ebenen. Vier Hebel, alle am Twin, alle
messbar an derselben Kennzahl (Anteil der Cross-Plane-Kanten, die einen 3-Kern
überleben):

1. **Feldebene für Code und Wissen.** Arm D hat gezeigt, dass das heutige
   Claim-Vokabular sie nur auf Dateiebene bindet. 3 von 9 realen
   Manifestationen sind unbenennbar. Jede benennbare Manifestation ist eine
   Kante mehr.
2. **Mehr als eine Kante je Cross-Plane-Knoten.** Eine Doku-Erwähnung hat heute
   genau zwei Kanten (`mentions`, `documents`). Abschnittszugehörigkeit,
   Revisionsbindung, Evidenzlokator und Verifier wären je eine weitere — und
   ein Knoten mit fünf Kanten überlebt jeden Kern.
3. **Der n-äre Claim aus §2 der SPEC** erzeugt genau solche Kanten: ein
   Claim-Knoten mit einer typisierten Kante je Slot bindet alle Beteiligten
   aneinander statt paarweise über einen Hub.
4. **Lineage und Testabdeckung als echte Extraktion**, nicht als Fiktion. Beides
   existiert im Repository und ist heute nicht im Graphen.

## 5. Was ich nicht behaupte

- Nicht, dass gelernte Tensor-Embeddings für Cross-Plane-Retrieval untauglich
  sind. Gemessen ist, dass der heutige Twin ihnen **kein Substrat bietet**.
- Nicht, dass 5× Lift das Maximum ist. Die Hyperparameter sind ungetunt, und
  die Literatur sagt ausdrücklich, dass das den größten Anteil ausmacht.
- Nicht, dass die Extraktion in Arm H vollständig ist. Sie ist ast + json +
  regex über Markdown, ein billiger Stellvertreter für einen Forest. Aufrufe,
  Vererbungsauflösung, echte Typinferenz und SQL-Lineage fehlen — und jede
  davon würde den Kern dichter machen.

## 6. Reproduktion

```
venv:   <scratchpad>/venv-tensor   (torch 2.13.0+cpu, pykeen 1.11.1)
Arm H:  python experiments/tensor_embedding/arm_h_real_fourfold.py
        -> runs/tensor_embedding_v3/arm_h_graph.json, arm_h_triples.tsv
Arm I:  siehe arm_i.json / arm_i.log
```

Nichts davon promoviert etwas, verändert kein Produktionsartefakt und schreibt
außerhalb von `runs/tensor_embedding_v3/` nur die Experimentskripte unter
`experiments/tensor_embedding/`.
