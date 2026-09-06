---
title: GUI-Lint
type: module
status: living
updated: 2026-09-05
covers: daedalus/gui
---
# GUI-Lint

`daedalus/gui` ist die kleinste Messstelle im Baum: sie verwandelt die Aussage
"das sieht nach generierter Oberflaeche aus" in Zahlen. Der Browser-Teil
(`probe.js`) nimmt einen DOM/CSSOM-Snapshot einer laufenden Seite auf, der
Python-Teil (`lint.py`) rechnet darauf Metriken aus. Es werden keine Pixel
angeschaut; jede Zahl stammt aus Geometrie und Computed Style und ist deshalb
reproduzierbar und auf die verursachenden Elemente zurueckfuehrbar. Im
Kernel/Ikarus/Ariadne-Bild ist das ein Evaluator-Zulieferer, kein Evaluator mit
Gate-Autoritaet: Ergebnisse sind Beobachtungen, die ein Mensch oder eine
Verifikationsstufe bewertet. Der Master-Plan nennt das ausdruecklich
(Abschnitt 13, "treating visual similarity or an LLM critique as sufficient UI
acceptance" ist eine verbotene Default-Richtung).

Das Modul unterscheidet zwei Klassen von Metriken selbst:

- **Tier A** — objektiv wahr/falsch: `horizontal_overflow`, `contrast_failures`,
  `small_targets`, `banned_faces`, `console_errors`. Diese koennen gaten.
- **Tier B** — Proxys fuer ein Urteil, das keine Regel faellen kann:
  `visible_elements`, `framed_panels`, `distinct_radii`, `panel_nesting_depth`,
  `allcaps_text_share`, `status_pills_visible`, `largest_equal_tile_row`,
  `accent_hue_families`, `identifier_leaks`. Jede Tier-B-Metrik liefert neben
  ihrer Zahl die verursachenden Elemente, damit ein Widerspruch inspizierbar
  statt argumentativ ist.

Der Docstring stempelt die Schwellwerte als ASSUMED und nennt den Korpus
ausdruecklich mit n=4 (drei abgelehnte Oberflaechen, eine angenommene) — zu
wenig, um darauf zu gaten.

## Module

| Datei | Was sie tut | Wichtige Symbole |
| --- | --- | --- |
| [`__init__.py`](../../../daedalus/gui/__init__.py) | Leer (0 Zeilen, gemessen 2026-09-05); markiert nur das Paket. | — |
| [`lint.py`](../../../daedalus/gui/lint.py) | Liest eine `probe.js`-Aufnahme als JSON, berechnet Tier-A- und Tier-B-Metriken, vergleicht mehrere Aufnahmen als Tabelle und schreibt den vollstaendigen Evidenz-Report. stdlib-only, per Design. | `analyse`, `compare`, `contrast_ratio`, `Metric`, `BANNED_FACES`, `main` |

Nicht-Python im selben Verzeichnis: [`probe.js`](../../../daedalus/gui/probe.js)
— der Capture-Teil, der im Browser laeuft. Die Aufteilung ist Absicht: das
Capture braucht einen Browser, die Regeln duerfen keinen brauchen.

`Metric` traegt `key`, `value`, `unit`, `tier`, `note` und `offenders`;
`Metric.to_dict` schneidet die Offender-Liste bei zwoelf Eintraegen ab.
`analyse` gibt ein Dict mit `label`, `url`, `viewport`, `truncated` und der
Metrikliste zurueck. `contrast_ratio` implementiert das WCAG-Verhaeltnis ueber
relative Luminanz; die Schwellen im Code sind 4.5 fuer Fliesstext und 3.0 fuer
grossen Text.

> **Extern:** Die Kontrast- und Zielgroessen-Schwellen stammen aus WCAG 2.2
> (Erfolgskriterien 1.4.3 Contrast (Minimum) und 2.5.8 Target Size (Minimum)).
> Der Code haelt 4.5:1 / 3.0:1 und 44x44 CSS-Pixel fest.
> Quelle: https://www.w3.org/TR/WCAG22/

## Trust-Grenzen / Effekte

`lint.py` liest ausschliesslich die als Argument genannten JSON-Aufnahmen und
schreibt genau eine Datei: `runs/gui/report.json`. Dieser Schreibpfad ist als
Effekt registriert. `main` ruft **vor** jeder Datei-Operation

```
begin_effect("cli.gui_lint", REGISTRY_BY_ID["cli.gui_lint"].effects,
             (process_guard_boundary_decision(),))
```

auf. Die Registry-Zeile steht in
[`daedalus/spine/effect_boundary.py`](../../../daedalus/spine/effect_boundary.py)
als `EntrypointSpec(id="cli.gui_lint", ...)` mit `Effect.FILESYSTEM_WRITE`,
`guard_contracts=("budget.process_guard",)`, `Wiring.CENTRAL` und einem
`GuardAnchor` auf `daedalus.gui.lint:main`. `analyse` und `compare` sind rein;
sie oeffnen nichts, spawnen nichts und rufen keinen Provider auf.

## Tests

- [`tests/test_cli_effect_boundary.py`](../../../tests/test_cli_effect_boundary.py)
  — `test_gui_lint_refuses_fail_closed_without_the_contract` prueft, dass bei
  verweigertem Boundary kein `runs/gui/report.json` entsteht.
- [`tests/test_graph_brief.py`](../../../tests/test_graph_brief.py) und
  [`tests/test_deepseek_substitution_guard.py`](../../../tests/test_deepseek_substitution_guard.py)
  benutzen `daedalus.gui.lint` als bekannten korrekten Modulpfad gegen die
  gemessene Halluzination "daedalus.linting"; sie testen das Modul selbst nicht.

Ein dedizierter Metrik-Test fuer `analyse` existiert nicht (gemessen
2026-09-05).

## Verwandt

- [Kernel](kernel.md) — wo Effekt-Leases und Evidence tatsaechlich entschieden werden.
- [Spine](spine.md) — Registry der Effekt-Einstiege, in der `cli.gui_lint` steht.
- [Tools](../tooling/tools.md) — `tools/gui_check.py` als der Treiber, der Capture und Lint zusammenfuehrt.
- [Tool-Vetting](../tool-vetting.md) — das Gate, das ein Werkzeug bestehen muss.
- [Wiki-Index](../index.md)

## Ungeklaert

- **Ungeklaert:** Wer `probe.js` in einem Browser ausfuehrt und wie die Dateien
  unter `runs/gui/` erzeugt werden, ist aus diesem Verzeichnis allein nicht
  ablesbar; `lint.py` konsumiert die Aufnahmen nur.
- **Ungeklaert:** Das Format der Capture-Datei (`els`, `scrollWidth`,
  `elementsKept`, `bgEff`, `borderSides` ...) ist nirgends als Schema fixiert;
  `analyse` greift direkt per Schluessel zu und wuerde bei einer
  Formataenderung mit `KeyError` scheitern.
- **Ungeklaert:** Die "Agreement Records" pro Proxy, die der Docstring fuer
  jede Tier-B-Metrik verspricht, sind im Code nicht als Datenstruktur
  vorhanden.
