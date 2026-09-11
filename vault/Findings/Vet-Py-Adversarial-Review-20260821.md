---
tags:
- findings
created: 2026-08-21
source: daedalus/tools/vet.py
permalink: main/findings/vet-py-adversarial-review-20260821
---

# vet.py — adversarische Review (Odysseus)

**Artefakt (autoritativ):** `../../daedalus/tools/vet.py`
(sha256 `41bd693e…120e`, 1151 Zeilen); Repros unter dem Job-Scratchpad
`odysseus-vet-attack{,,2}.py` / `-mutate.py`.

Einordnung: Session-Ziel „vet.py reviewed" erfüllt. Verdikt
**GO-WITH-CHANGES**: statisch, deterministisch, schreibt/führt nichts aus,
fail-closed bei Lesefehlern (Invariante 1 STATIC ONLY bestätigt via
addaudithook: 0 write/process/network events), 5 von 8 Guards testgepinnt.
NICHT als geschlossenes Trust-Gate zählbar, solange F1–F3 offen sind (sonst
wird eine Mitigation berichtet, die es nicht gibt — Review-Regel „hook
advertised as complete security guarantee"). vet hat heute keinen produktiven
Konsumenten (nur tools/__init__, inventory, Tests).

Belegte Befunde (RAW-Repros ausgeführt):

- **F1 MAJOR** — `vet_skill` scannt nur `skill.body`; Frontmatter
  `description`/`compatibility` (das laut `render_catalog` „am ehesten ein
  Modell erreichende" Feld) erreicht `scan_text` nie. Injection-Payload in
  Description = CLEAR, dieselben Bytes im Body = BLOCK.
- **F2 MAJOR** — alle vier `mcp.*`-Regeln fest auf REVIEW; ein MCP-Server
  kann nie BLOCK werden, obwohl er die härtere Klasse ist (Prozess + Socket).
- **F3 MAJOR** — weil F2 gilt, ist `mcp_spec_digest` + der Byte-Pin-Pfad
  unerreichbar (falscher Pin = kein Pin). Strukturell derselbe Defekt wie
  `docs/archive/TODO_2026-07-30_SESSION.md:43`, an neuer Stelle wieder da.
  Mildernd: `load_allowances` warnt korrekt.
- **F4 MAJOR** — Mutationsmatrix 8 Guards: M3 (strict-UTF-8→replace),
  M4 (`_defang` aus), M7 (`MAX_FILE_BYTES` aus) bleiben GRÜN = ungetestet;
  genau die Guards mit „aus adversarischem Review"-Kommentaren.
- **F5 MAJOR** — Regeltabelle unter-reportet trotz „over-reports on purpose":
  `builtins.exec(`, `subprocess.getoutput`, `urlopen`, PowerShell-IEX u.a.
  ohne Finding (negatives Lookbehind `(?<![\w.])` schließt qualifizierte
  Schreibweisen aktiv aus).
- **F6–F10 MINOR** — BOM-Falschtreffer (skills.py behandelt BOM, vet nicht);
  `.psm1/.psd1/.mdx` fehlen in Textsuffixen; Binärheuristik nur 4 KiB;
  Egress liest nur 3 Felder; `_shell_tokens` trennt nicht an Quotes.
- Refutiert/positiv: F12 (Zeilendrift), TOCTOU (fail-safe, nicht fail-open),
  F14 (Effekt-Deklaration sauber), load_allowances fail-closed (10/10).

Provenienz: MEASURED (Odysseus, 2026-08-21; Baseline 119 passed/10 subtests;
vet.py byte-identisch zurückgerollt, `git status --porcelain daedalus/` leer).

Folgearbeit: Minos-Lane (F1/F2+F3/F4/F6, TDD) → Cerberus-Veto → Gate.