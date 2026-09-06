---
title: Skill-Skripte ui-ux-pro-max
type: tooling
status: living
updated: 2026-09-05
covers: .claude/skills/ui-ux-pro-max/scripts
---
# Skill-Skripte ui-ux-pro-max

`.claude/skills/ui-ux-pro-max/scripts/` ist die Ausführungsschicht eines
Claude-Code-Skills, nicht Teil des Daedalus-Kernels. Der Skill beantwortet
UI/UX-Fragen aus einer lokalen CSV-Datenbank unter
`.claude/skills/ui-ux-pro-max/data/` (gemessen 2026-09-05: 13 Domain-Dateien
plus 22 Stack-Dateien unter `data/stacks/`) und erzeugt daraus optional ein
vollständiges Designsystem. Die Skripte sind reine Standardbibliothek — kein
`requirements.txt`, kein Modellaufruf, kein Netz — und laufen als eigenständige
Prozesse, die Claude über die Skill-Anweisung `SKILL.md` startet.

Einordnung im Plan-Bild: Der Skill ist eine *derived projection* im Sinne von
Masterplan §0 (Root-Instructions, Skills und Hooks). Er hat keine Autorität
über Policy, Evaluator oder Promotion und schlägt nur vor. Für den
Genesis-Strang (Masterplan §7.1, §9) ist er ein Retrieval-Werkzeug für den
`DesignContract`, kein Verifizierer: eine visuelle Ähnlichkeit oder eine
CSV-Empfehlung ist nach Masterplan §13 ausdrücklich *keine* ausreichende
UI-Abnahme.

## Module

| Datei | Zweck | Öffentliche Symbole |
| --- | --- | --- |
| [core.py](../../../.claude/skills/ui-ux-pro-max/scripts/core.py) | BM25-Suchmaschine über die CSV-Datenbank. Enthält die Domain-/Stack-Konfiguration, Tokenisierung mit Stopwort- und Synonymliste, mtime-gestützte Caches für CSV-Zeilen und gefittete Indizes, die Domain-Erkennung und die beiden Suchfunktionen. | `BM25` (`tokenize`, `fit`, `score`, `vocabulary`), `detect_domain`, `search`, `search_stack`, `CSV_CONFIG`, `STACK_CONFIG`, `AVAILABLE_STACKS`, `UNTRUNCATED_COLS`, `DATA_DIR`, `MAX_RESULTS` |
| [search.py](../../../.claude/skills/ui-ux-pro-max/scripts/search.py) | Kommandozeilen-Frontend. Parst Domain-, Stack-, Format- und Persistenz-Flags sowie die drei Design-Regler und druckt entweder formatierten Text oder JSON. Erzwingt UTF-8 auf stdout/stderr, weil Windows sonst cp1252 benutzt. | `format_output`, `TRUNCATE_AT` |
| [design_system.py](../../../.claude/skills/ui-ux-pro-max/scripts/design_system.py) | Aggregiert mehrere Domänensuchen zu einem Designsystem, wendet Regeln aus `ui-reasoning.csv` an, rendert ASCII-Box oder Markdown und schreibt optional MASTER.md plus Seiten-Overrides. Der größte Teil des Verzeichnisses (1371 Zeilen, gemessen 2026-09-05). | `DesignSystemGenerator`, `generate_design_system`, `persist_design_system`, `safe_slug`, `format_ascii_box`, `format_markdown`, `format_master_md`, `format_page_override_md`, `hex_to_ansi`, `ansi_ljust`, `section_header`, `DIAL_TIERS`, `SEARCH_CONFIG`, `REASONING_FILE`, `BOX_WIDTH` |
| [validate_data.py](../../../.claude/skills/ui-ux-pro-max/scripts/validate_data.py) | Datenintegritäts-Guardrail ohne pytest-Abhängigkeit: prüft je konfigurierter CSV die Existenz, dass jede in `search_cols`/`output_cols` referenzierte Spalte im Header steht, dass die Indexspalte `No` eindeutig ist und dass JSON-Spalten parsen. Sammelt alle Probleme und beendet mit Code 1, statt beim ersten abzubrechen. | `main` |
| [tests/test_core.py](../../../.claude/skills/ui-ux-pro-max/scripts/tests/test_core.py) | Mitgelieferte Regressionstests auf `unittest`-Basis für `core.py` und `design_system.py`; ohne externe Abhängigkeit lauffähig. | `TestTokenizer`, `TestSearchDomains`, `TestDomainDetection`, `TestPersistence`, `TestReasoningMatch` |

### Suchpfad

`search(query, domain=None)` erkennt die Domäne selbst, wenn keine angegeben
ist. `detect_domain` gewichtet Treffer nach Wortanzahl des Schlüsselworts
(längere Phrasen sind spezifischer) und bricht Gleichstände über eine feste
Prioritätsliste `_DOMAIN_TIEBREAK_ORDER`, ausdrücklich nicht über die
Dict-Reihenfolge. Fällt der beste Score auf null, ist die Rückfall-Domäne
`style`.

Zwei Details sind bewusst gegen stille Fehler gebaut:

- Bei null Treffern liefert `_suggest_terms` die nächstliegenden bekannten
  Vokabeln, und `format_output` schreibt explizit, dass *kein* Datenbanktreffer
  vorlag — statt eine leere Antwort wie ein Ergebnis aussehen zu lassen.
- `UNTRUNCATED_COLS` schützt Codebeispiele, Checklisten und Konfigblöcke vor
  der 300-Zeichen-Kürzung; ein mitten im Snippet abgeschnittenes Beispiel wäre
  wertlos.

### Design-Regler

`DIAL_TIERS` definiert drei optionale 1–10-Regler, die nur mit
`--design-system` wirken: `variance` (zentriert/minimal bis
bold/asymmetrisch), `motion` (Subtle/Standard/Complex, zieht einen passenden
GSAP-Schnipsel aus `motion.csv`) und `density` (spacious bis dense, überschreibt
die Spacing-Skala). `_resolve_dial` klemmt den Wert auf 1–10 und bucketiert ihn.
Der Kommentar im Code nennt als Vorbild ausdrücklich die Regler eines anderen
Skills; die Regler *biasen* die bestehende Suche, sie ersetzen sie nicht.

## Trust-Grenzen / Effekte

Die Skripte laufen als eigener Prozess außerhalb des Daedalus-Kernels und
kennen weder `begin_effect` noch die Effekt-Registry. Gemessen 2026-09-05
referenziert kein Modul unter `daedalus/`, `tools/`, `scripts/` oder `tests/`
diesen Skill. Damit gilt:

- **Lesende Effekte:** `core.py` und `validate_data.py` lesen ausschließlich
  CSV-Dateien unterhalb von `DATA_DIR`, also
  `.claude/skills/ui-ux-pro-max/data/`.
- **Der einzige Writer ist `persist_design_system`** in `design_system.py`. Er
  legt `design-system/<projekt-slug>/MASTER.md` und optional
  `design-system/<projekt-slug>/pages/<seite>.md` unterhalb von `output_dir`
  an (Vorgabe: aktuelles Arbeitsverzeichnis). Alle anderen Funktionen geben
  Strings oder Dicts zurück.
- **Pfad-Traversal ist strukturell ausgeschlossen:** `safe_slug` reduziert
  Projekt- und Seitennamen auf `[a-z0-9_-]`; Schrägstriche, Backslashes und
  Punkte kollabieren zu `-`, ein Name wie `../../etc` kann sein Elternverzeichnis
  also nicht verlassen.
- **Kein stiller Überschreiber:** Existiert MASTER.md bereits und ist `force`
  nicht gesetzt, gibt `persist_design_system` den Status `skipped_exists`
  zurück, ohne zu schreiben. Frühere Designentscheidungen gehen damit nicht
  verloren.
- **Kein Netz, keine Modellaufrufe, keine Secrets.** Die einzigen Importe sind
  `csv`, `json`, `os`, `re`, `sys`, `io`, `argparse`, `datetime`, `pathlib`,
  `math` und `collections`.

Weil `search.py` und `design_system.py` Dateien schreiben können, gilt für sie
dieselbe Überlegung wie für jedes Skript unter [tools](tools.md): sobald ein
solcher Einstiegspunkt aus dem Kernel heraus aufgerufen würde, bräuchte er eine
Zeile in der Effekt-Registry und einen `begin_effect`-Aufruf. Heute wird er es
nicht — der Aufruf kommt vom Skill-Harness, nicht aus `daedalus/`.

> **Extern:** BM25 ist eine probabilistische Ranking-Funktion mit den
> Parametern k1 (Termfrequenz-Sättigung) und b (Längennormalisierung); `core.py`
> setzt k1 = 1.5 und b = 0.75, die üblichen Standardwerte.
> Quelle: https://en.wikipedia.org/wiki/Okapi_BM25

## Tests

Im Repository-Testbaum `tests/` existiert keine Abdeckung (gemessen
2026-09-05: `grep -rln "ui-ux-pro-max" tests/` liefert nichts). Der Skill bringt
seine Prüfungen selbst mit, beide ohne externe Abhängigkeit:

- [tests/test_core.py](../../../.claude/skills/ui-ux-pro-max/scripts/tests/test_core.py)
  — 134 Zeilen `unittest` (ausdrücklich nicht pytest, weil der Skill mit null
  externen Abhängigkeiten ausgeliefert wird). Fünf Testklassen decken
  Tokenisierung (kurze Fachbegriffe wie "ui", "ux", "3d" bleiben suchbar),
  Domänensuche, Domänenerkennung, Persistenz und den Regel-Match aus
  `ui-reasoning.csv` ab. Lauf: `python -m unittest discover -s scripts/tests`.
- [validate_data.py](../../../.claude/skills/ui-ux-pro-max/scripts/validate_data.py)
  — das Datenintegritäts-Guardrail, eigenständig per `python validate_data.py`,
  endet mit Exit-Code 1 plus vollständiger Problemliste. Sein Docstring nennt
  sich selbst "pre-publish/CI check"; ob er in einer CI-Definition dieses
  Repositories aufgerufen wird, ist unten als offen vermerkt.

Ein bemerkenswerter Selbstbefund im Guardrail: fehlt einer Stack-CSV die
Indexspalte `No`, meldet er das als Schema-Drift und nennt es im Text
ausdrücklich "harmless for search, but inconsistent" — die Prüfung
unterscheidet also zwischen Defekt und Inkonsistenz.

## Verwandt

- [Tools](tools.md) — die Effekt-Registry-Regel für schreibende Skripte
- [Claude-Proposals](claude-proposals.md) — weitere Artefakte unter `.claude/`
- [Skripte](scripts.md) — Repository-Skripte mit vergleichbarer Rolle
- [Orchestration Genesis](../architecture/orchestration-genesis.md) — der `DesignContract`-Konsument
- [GUI](../architecture/gui.md), [Interfaces Desktop](../architecture/interfaces-desktop.md) — die UI-Flächen des Projekts
- [Tool-Vetting](../tool-vetting.md), [Feature-Backlog](../feature-backlog.md), [Wiki-Index](../index.md)

## Ungeklärt

- **Ungeklärt:** Ob `validate_data.py` irgendwo automatisch läuft. Ich habe
  keine CI-Definition gefunden, die es aufruft; der Docstring behauptet nur die
  Eignung dafür.
- **Ungeklärt:** Herkunft und Lizenz der CSV-Datenbestände unter `data/`. Die
  Skripte lesen sie nur; woher die Zeilen stammen, steht nicht in den Skripten.
- **Ungeklärt:** Ob der Skill zum Repository gehört oder mit dem
  Claude-Code-Harness ausgeliefert wird. Er liegt unter `.claude/skills/`, wird
  aber von keinem Repository-Code referenziert.
- **Ungeklärt:** `design_system.py` importiert `os` und `datetime`, aber ich
  habe die Nutzungsstellen nicht vollständig abgelesen; die Rendering-Hälfte des
  Moduls (Zeilen 333–668 und 792–1371) habe ich nur überblicksweise gelesen.
