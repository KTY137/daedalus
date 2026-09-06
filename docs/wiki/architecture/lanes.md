---
title: Schreib-Lanes
type: module
status: living
updated: 2026-09-05
covers: daedalus/lanes
---
# Schreib-Lanes

Eine *Lane* ist der Pfad, auf dem die Ausgabe eines Modells zu einer Datei auf
der Platte wird: die lokale Ollama-Lane, die bezahlte DeepSeek-Lane, die
Claude-CLI-Lane. `daedalus/lanes` haelt die Basispruefungen, die **jede** Lane
vor dem Schreiben laufen lassen muss, dazu zwei Kontext- und Messwerkzeuge um
diesen Schreibpfad herum: den Graph-Brief, der einem Modell zeigt, welche
Symbole tatsaechlich existieren, und die Grounding-Pruefung, die Modell-Prosa
gegen den Baum haelt. Im Kernel/Ikarus/Ariadne-Bild sitzt das Paket auf der
Ikarus-Seite unmittelbar vor dem Effekt: es entscheidet nicht, *ob* eine Lane
schreiben darf (das macht Policy, siehe [Kernel-Policy](kernel-policy.md)),
sondern ob der konkrete Byte-Strom eines Modells als Datei akzeptabel ist. Der
Paket-Docstring nennt den Anlass: am 2026-07-30 lagen zwei neue Guards in
`providers/deepseek.py` und nicht in `providers/ollama.py`, womit die bezahlte
externe Lane strikt sicherer war als die lokale Default-Lane. Der Baseline
wurde deshalb hierher gehoben; eine Lane darf Checks **hinzufuegen**, aber den
Baseline nicht ueberspringen.

Bewusst *nicht* hierher gewandert sind Aussagen ueber ein konkretes Modell: die
Elisions-Marker sind eine Behauptung darueber, was ein Vendor-Modell beim
Abschneiden ausgibt, und kommen als Policy-Parameter herein.

## Module

Gemessen 2026-09-05: 5 Dateien, 2410 Zeilen.

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [`__init__.py`](../../../daedalus/lanes/__init__.py) | Re-Export der Baseline-Oberflaeche; der Docstring begruendet, warum die Guards zentral liegen. | `BASELINE`, `BASELINE_POLICY`, `CheckPolicy`, `WriteAttempt`, `run_checks`, `GraphBrief`, `ReferenceAudit` |
| [`checks.py`](../../../daedalus/lanes/checks.py) | Die Basispruefungen selbst: billigste zuerst, erste Ablehnung gewinnt, fail-closed. | `WriteAttempt`, `CheckPolicy`, `BASELINE`, `run_checks`, `parses`, `not_truncated`, `no_elision`, `not_substituted`, `imports_resolve`, `unresolved_first_party_imports`, `toplevel_defs`, `with_markers` |
| [`fanout.py`](../../../daedalus/lanes/fanout.py) | Begrenzter, wiederaufnehmbarer Fan-out ueber die billige externe Lane; jede Antwort landet als eigene Datei. | `FanoutTask`, `FanoutResult`, `fan_out`, `default_concurrency`, `DEFAULT_CONCURRENCY`, `DEFAULT_TIMEOUT_S` |
| [`graph_brief.py`](../../../daedalus/lanes/graph_brief.py) | Der dreischichtige Graph (Symbole, Importe, Dokumente) als Absatz, den ein Modell lesen kann. | `GraphBrief`, `graph_brief`, `render_brief`, `file_symbols`, `DEFAULT_BUDGET_CHARS`, `DEEP_EDGE_MARK`, `ARTEFACT_ROOTS` |
| [`grounding.py`](../../../daedalus/lanes/grounding.py) | Loest Datei- und Symbolzitate aus Modell-Prosa gegen den Baum auf und widerlegt "X existiert nicht"-Behauptungen. | `ReferenceAudit`, `audit_references`, `judge`, `claim_text`, `candidate_names`, `defined_in`, `imported_in`, `module_names` |

### checks.py im Detail

`WriteAttempt` ist der Eingabesatz eines Checks: `rel`, `proposed`,
`repo_root`, `original` und das separate Flag `creating`. Das Flag wird nicht
aus einem leeren `original` abgeleitet, weil eine Lane, die eine echte Datei
auf Null kuerzt, das sonst als Neuanlage ausgeben und die Edit-Guards
ueberspringen koennte.

`CheckPolicy` sind die Lane-Stellschrauben: `elision_markers`,
`min_size_ratio` (Default 0.5), `min_symbol_survival` (0.5),
`min_symbols_to_judge` (3), `first_party_roots`
(`daedalus`, `tools`, `tests`) und `max_named_imports` (4).

`BASELINE` ist die feste Reihenfolge `not_truncated`, `no_elision`, `parses`,
`not_substituted`, `imports_resolve`. `run_checks` laeuft sie ab und gibt einen
leeren String (schreiben) oder einen Ablehnungsgrund zurueck. Wirft ein Check
eine Ausnahme, wird das als Ablehnung gewertet, nicht als Zustimmung — ein
Guard, der nicht antworten kann, darf keine Erlaubnis sein. Ein Argument zum
*Entfernen* eines Baseline-Checks gibt es absichtlich nicht; `extra` ergaenzt
nur.

`not_substituted` traegt die Messung, die das Paket ausgeloest hat: bei einem
Rewrite von `daedalus/interfaces/cli/shift.py` lieferte das Modell den Inhalt
von `tests/test_shift.py`, der Lauf meldete `status: done`. Groessen- und
Elisionspruefung sehen so etwas nicht; nur die Ueberlebensrate der
Top-Level-Definitionen trennt Edit von Substitution.

`unresolved_first_party_imports` ist rein statisch: den Import auszufuehren, um
seine Aufloesbarkeit zu pruefen, wuerde Modulcode einer nicht vertrauten Lane
ausfuehren. Konservativ gebaut — nur First-Party-Wurzeln, fehlende Namen nur
bei Modulen ohne Star-Import und ohne `__getattr__`, und ein Alias, der auf ein
Submodul zeigt, gilt als aufgeloest.

### graph_brief.py im Detail

Drei Schichten: **symbols** (was existiert, pro Datei), **imports** (wer wen
erreicht, inklusive der Kanten *innerhalb* von Funktionskoerpern, markiert mit
`DEEP_EDGE_MARK`) und **documents** (welche Seite behauptet, diese Datei zu
beschreiben). `GraphBrief` transportiert neben dem Text die Zaehler `counts`
und `dropped`, daraus die Eigenschaften `char_count` und `truncated`: eine
Kuerzung wird benannt, weil ein still abbrechender Brief exakt wie ein Brief
aussieht, der sagt, diese Dateien gaebe es nicht. `ARTEFACT_ROOTS`
(`runs/`, `build/`, `dist/`, `.captures/`) haelt Artefaktkopien aus dem Brief
heraus. `render_brief` ist die Bequemlichkeitsform fuer Provider und faengt
alles ab: ein Brief ist Kontext, kein Gate, und darf nie in eine Lane hinein
werfen.

### grounding.py im Detail

`audit_references` loest jeden im Text genannten Pfad (optional mit
Symbol-Suffix) gegen eine **getrackte** Dateiliste auf — laut Docstring
`git ls-files`, nicht ein Dateisystem-Walk, damit ignorierte Artefakte einen
erfundenen Pfad nicht real aussehen lassen. `ReferenceAudit` trennt die Faelle,
die verschiedene Antworten brauchen: `repaired` (Verzeichnis weggefallen),
`ambiguous` (Basename mehrdeutig), `invented` (Datei existiert nirgends),
`absent_symbols` (Datei real, Symbol nicht darin).

`judge` liefert eines von `false`, `false-elsewhere`, `scoped`, `undecided`.
`undecided` ist ausdruecklich **kein** Bestehen. Der Docstring von
`grounding.py` markiert die Grenze selbst: das ist eine **Grammatik**-Pruefung
("existiert dieser Name"), nie eine semantische ("stimmt diese Behauptung").

## Trust-Grenzen / Effekte

- `daedalus/lanes` schreibt selbst genau an einer Stelle: `fan_out` legt pro
  Task eine Ergebnisdatei unter `out_dir` ab, und zwar ueber
  `write_text_atomic` aus [`daedalus/atomic.py`](../../../daedalus/atomic.py),
  damit ein Leser waehrend eines langen Laufs nie ein halbes JSON-Dokument
  sieht. `checks.py`, `graph_brief.py` und `grounding.py` sind read-only.
- `run_checks` ist kein Policy-Entscheider und keine Trust-Boundary im Sinne
  von Plan Abschnitt 4: es ist die letzte Formpruefung vor dem Schreiben. Ob
  eine externe Lane ueberhaupt schreiben darf, entscheidet
  `resolve_external_write_lanes` in
  [`daedalus/config.py`](../../../daedalus/config.py).
- `fan_out` installiert den Budget-Guard selbst und nicht als Parameter; der
  Modul-Docstring nennt den Grund (rund 170 unpreiste bezahlte Aufrufe am
  2026-07-30). Ausserdem verweigert `fan_out` die Kombination `votes` groesser
  eins mit Temperatur 0.0, weil identische Dekodierungen wie unabhaengige
  Zustimmung aussehen. `FanoutResult` traegt `trace_id` aus
  `current_trace_id` und praegt nie neu: `None` heisst "kein Trace im Scope",
  nicht "hier ist eine frische id".
- `FanoutResult.blocked` unterscheidet "Transport lieferte Antworten" von
  "irgendeine Antwort trug Evidenz" — gemessen am 2026-07-31, als 6 von 6
  Einheiten den Status `blocked` zurueckgaben und die Laufzusammenfassung
  `ok=6` meldete.
- Das `policy`-Argument von `fan_out` wird an den Provider und von dort an die
  Sensitivitaetsklassifikation durchgereicht; laut Docstring kann es den
  Secret-Floor nicht absenken.

## Konsumenten

- [`daedalus/providers/deepseek.py`](../../../daedalus/providers/deepseek.py)
  und [`daedalus/providers/ollama.py`](../../../daedalus/providers/ollama.py)
  importieren `BASELINE_POLICY`, `WriteAttempt`, `run_checks`.
- [`daedalus/providers/_report.py`](../../../daedalus/providers/_report.py)
  nutzt `graph_brief` und `render_brief`.
- [`tools/funnel.py`](../../../tools/funnel.py) und
  [`tools/audit_swarm.py`](../../../tools/audit_swarm.py) fahren `fan_out`;
  [`tools/funnel_report.py`](../../../tools/funnel_report.py) nutzt das
  Grounding.

## Tests

Ermittelt per `grep -rl` ueber `tests/` (gemessen 2026-09-05):

- [`tests/test_lanes_checks.py`](../../../tests/test_lanes_checks.py)
- [`tests/test_lanes_fanout.py`](../../../tests/test_lanes_fanout.py)
- [`tests/test_graph_brief.py`](../../../tests/test_graph_brief.py)
- [`tests/test_reference_audit.py`](../../../tests/test_reference_audit.py)
- [`tests/test_funnel_truth.py`](../../../tests/test_funnel_truth.py)
- [`tests/test_envelope_coverage.py`](../../../tests/test_envelope_coverage.py)
  (fand `fanout.py` als nicht deklarierten Record-Produzenten)
- [`tests/test_ollama_native.py`](../../../tests/test_ollama_native.py)
- [`tests/runtimes/test_provider_helper_hierarchy.py`](../../../tests/runtimes/test_provider_helper_hierarchy.py)

## Verwandt

- [Provider](providers.md) — die Lanes, die diesen Baseline aufrufen.
- [Structcore](structcore.md) — der Index, aus dem `graph_brief` seine Kanten zieht.
- [Orchestrierung](orchestration.md) — wo Briefs und Runbooks komponiert werden.
- [Kernel-Policy](kernel-policy.md) — wer ueberhaupt schreiben darf.
- [Tools](../tooling/tools.md) — `funnel` und `audit_swarm` als Fan-out-Konsumenten.
- [Typgraph](type-graph.md), [Graph delta as fitness](../graph-delta-as-fitness.md),
  [Wiki-Index](../index.md), [Agents hold no state](../decisions/agents-hold-no-state.md).

## Ungeklaert

- **Ungeklaert:** ob die Claude-CLI-Lane den Baseline heute wirklich aufruft —
  gefunden wurden nur DeepSeek und Ollama als Importeure von `run_checks`.
- **Ungeklaert:** ob `fan_out` mit dem kanonischen `EffectLease`-Pfad verbunden
  ist; im Modul selbst taucht nur der Budget-Guard auf, keine Lease.
- **Ungeklaert:** ob die Dokumentenschicht von `graph_brief` bei abgeschalteten
  Index-Flags in der Praxis je gefuellt ist.
