---
title: Observation layer
type: spec
status: implemented
updated: 2026-09-05
---

# Observation layer

Was eine Debug-Konsole zeigt, als Datum festgehalten: `ndarray float64
(1000, 3) C-contiguous`. Form, nie Wert -- ein Wert kann Gigabytes groß sein,
ein Wert kann ein Geheimnis sein, und der Graph will die Form. Nach Plan §5 ist
Beobachtung ausdrücklich **keine fünfte semantische Ebene**, sondern eine
orthogonale Linie neben Provenienz, Evidenz und Zeit.

Implementiert in
[daedalus/observe/shape.py](../../../daedalus/observe/shape.py), die Fassade in
[daedalus/observe/__init__.py](../../../daedalus/observe/__init__.py). Symbole:
`Shape`, `describe`, `ShapeConflict`, `compare_declared`, `SHAPE_VERSION`,
`MAX_NAMES`, `MAX_NAME_CHARS`, `MAX_DEPTH` sowie die neun Familien `ARRAY`,
`TABLE`, `RECORD`, `SEQUENCE`, `TREE`, `SCALAR`, `TEXT`, `BINARY`, `OPAQUE`.

## Warum außerhalb von Structcore

Weil ein lebendes Objekt zu bekommen heißt, dass das Programm **lief**.
[Structcore](structcore.md) ist konstruktionsbedingt ein statischer Pass, und
`daedalus/tools/vet.py` schreibt die Regel offen aus: man führt keinen
nicht vertrauenswürdigen Code aus, um etwas über ihn zu entscheiden.
Beobachtung ist deshalb eine eigene, ausdrücklich einzuschaltende Spur, die den
Graphen mit Kanten *füttert*, die `provenance="observed"` tragen. Sie ist nie
Teil eines Index-Baus und läuft nur auf Bäumen, die der Betreiber besitzt.

Sie löst dabei eine benannte Blindheit auf: der Index von `structcore` reist
selbst als nacktes `dict`, die wichtigste Datenstruktur im Baum ist für jeden
Deklarationspass also unsichtbar. Eine beobachtete Instanz nennt ihre echten
Schlüssel.

## Form, nie Wert

Nichts hier liest ein Element, eine Zelle, eine Zeile oder eine skalare
Nutzlast. Aufgezeichnet werden Metadaten: konkrete Klasse, `dtype`, `dims`,
`nbytes`, `layout`, `length` und Schlüssel- beziehungsweise Spaltennamen. Drei
unabhängige Gründe, die alle schon jemandem geschadet haben -- ein Wert kann
Gigabytes groß sein und ein kopierender Beobachter ist ein Speicherfehler; ein
Wert kann ein Geheimnis sein; und der Graph will ohnehin die Form.

Selbst Namen sind nicht automatisch harmlos: eine Spalte `patient_id` ist eine
Offenlegung. `describe` nimmt deshalb einen `redact`-Haken, und wer eine
Beobachtung in die Nähe eines Modells schickt, soll ihn setzen. Das Modul
besitzt keine eigene Sensitivitäts-Policy -- die liegt bei
`daedalus.sensitivity`, und beide werden absichtlich getrennt gehalten.

Grenzen sind Zahlen, keine Absicht: ein `dict` mit 40 000 Schlüsseln wird durch
die ersten `MAX_NAMES` (64) plus einen echten Gesamtzähler beschrieben, nie
durch alle -- ein unbegrenzter Deskriptor ist der Weg, auf dem ein Beobachter
zu dem Speicherproblem wird, das er diagnostizieren sollte. `n_names` trägt die
wahre Anzahl auch dann, wenn `names` gekürzt wurde, und `truncated` sagt es.

Die Bibliotheken werden durchgehend nach Attributen abgeklopft, nie importiert:
numpy, pandas, h5py und uproot müssen nicht vorhanden sein: ein Baum ohne sie
fällt auf die generischen Familien zurück und sagt das.

## Der Abgleich mit der Deklaration

`compare_declared` stellt eine Beobachtung neben deklarierte Feldnamen und
liefert einen `ShapeConflict`. Die beiden Richtungen sind unterschiedlich
scharf: `missing_in_observation` ist das weiche Signal -- diese Eingaben haben
das Feld nicht angefasst. `undeclared_in_observation` ist das scharfe -- das
Objekt trägt etwas, das der Code nie deklariert hat, also ist entweder die
Deklaration unvollständig oder die Nutzlast hat undokumentierte Form. Und die
Funktion **verweigert lieber den Vergleich, als Befunde herzustellen**: eine
Beobachtung ohne Namen (ein Skalar, ein unstrukturiertes Array, ein opakes
Objekt) ist `comparable=False` mit Begründung, statt jedes deklarierte Feld als
"fehlend" zu melden.

## Eine Beobachtung ist eine Stichprobe, kein Beweis

`(1000, 3)` ist die Form, die *diese* Eingabe erzeugt hat, nicht die Form, die
die Funktion verlangt. Ein nie gesehenes Feld ist kein Feld, das nicht
auftreten kann. Jeder Datensatz trägt `provenance="observed"` und den Lauf, aus
dem er stammt; ein Konsument, der ihn als Tatsache meldet, liegt falsch. Das
ist dieselbe Disziplin, die `daedalus/eval/ceiling.py` anwendet, wenn es seinen sauberen
vom undichten Arm trennt -- und im Masterplan Invariante 4: Modelle und
Beobachtungen schlagen vor, Evaluatoren entscheiden.

## Tests

[tests/test_observe_shape.py](../../../tests/test_observe_shape.py) deckt das
Modul ab; [tests/test_reference_audit.py](../../../tests/test_reference_audit.py)
nennt es zusätzlich.

## Verwandt

- [Structcore](structcore.md) -- der statische Gegenpol, der ein Objekt zur
  Laufzeit ausdrücklich nicht ansehen darf.
- [Type graph](type-graph.md) -- die deklarierte Seite dessen, was hier
  beobachtet wird.
- [Data layer](data-layer.md) -- getragene Schemata von Artefakten; derselbe
  Join, nur auf Dateien statt auf lebenden Objekten.
- [Knowledge layer](knowledge-layer.md), [Twin](twin.md),
  [Twin-Extraktoren](twin-extractors.md).
- [Observe](observe.md) -- das Paket im Detail.
- [Eval](eval.md) -- der Ort, an dem saubere und undichte Arme getrennt
  werden.
- [Tools (Capability-Schicht)](tools.md) und [Tool-Vetting](../tool-vetting.md)
  -- die Regel, dass man nicht ausführt, um zu entscheiden.
- [Forest v2 — Tensor-Embeddings](../experiments/forest-v2-tensor-embeddings.md)
  -- Node Cards, die Beobachtungen als Provenienz mitführen könnten.
- [Wiki-Index](../index.md).
