---
title: Tools (Capability-Schicht)
type: module
status: living
updated: 2026-09-05
covers: daedalus/tools
---
# Tools (Capability-Schicht)

`daedalus/tools` beantwortet zwei Fragen und sonst keine: *welche Werkzeuge
existieren auf dieser Maschine* und *wofür sind sie freigegeben*. Es ist die
Capability-Schicht neben dem Kernel, nicht darin: nichts hier installiert,
aktiviert, startet oder routet etwas. Bereitstellung ist eine eigene Spur, und
Capability-Routing gehört dem Provider-Router, der die Lane-Policy bereits
besitzt -- diese Trennung steht so im Paket-Docstring und ist genau das, was
frühere Architekturentscheidungen wieder herausreißen mussten.

Zwei Module, eine Naht:

- **`vet`** ist das Gate. Statisch, fail-closed, ohne Ausführung. Es liefert
  Befunde mit Beweisstelle, nie eine Punktzahl.
- **`inventory`** ist die abgeleitete Liste jedes Skills und jedes
  MCP-Servers, den ein Projekt sieht, jeder mit seinem Verdikt. Abgeleitet,
  nie handgepflegt -- derselbe Vertrag, den [Structcore](structcore.md) für
  den Code-Index hält.

Gemessen 2026-09-05: 3 Python-Module, 1952 Zeilen, davon 1668 in `vet.py`.

## Module

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [__init__.py](../../../daedalus/tools/__init__.py) | Paketfassade; exportiert die vier Ergebnisse, die Versionskonstanten und beide Vet-Einstiege. | `CLEAR`, `REVIEW`, `BLOCK`, `UNSCANNABLE`, `VET_VERSION`, `INVENTORY_VERSION` |
| [inventory.py](../../../daedalus/tools/inventory.py) | Sammelt Skills aus den Projekt- und Nutzer-Scopes und MCP-Server aus den Konfigurationsdateien, vettet jeden Eintrag und liefert ein deterministisch sortiertes Inventar plus Terminaltabelle. Lesefehler werden nie in die Zusammenfassungszahlen gefaltet. | `ToolRecord`, `collect_skills`, `collect_mcp_servers`, `build`, `render`, `main`, `SKILL_SCOPES`, `MCP_SCOPES`, `USER_SKILL_DIRS` |
| [vet.py](../../../daedalus/tools/vet.py) | Das Gate selbst: Regeltabelle, Unsichtbarkeits-Normalisierung, Skill- und MCP-Prüfung, Allowance-Anwendung, Zusammenfassung. | `Finding`, `Verdict`, `scan_text`, `vet_skill`, `vet_mcp_server`, `skill_identity`, `mcp_spec_digest`, `load_allowances`, `apply_allowances`, `summarise`, `RULE_SEVERITY`, `ALLOWANCE_PATH`, `MAX_FILE_BYTES`, `MAX_FILES_SCANNED`, `TEXT_SUFFIXES` |

## Die fünf Invarianten des Gates

Der Docstring von `vet.py` schreibt sie aus; sie sind der Grund für fast jede
Designentscheidung darin.

1. **Nur statisch.** Vetting führt das Geprüfte nie aus, importiert es nie,
   löst es nie über das Netz auf und startet keinen MCP-Server, um ihn zu
   fragen, was er tut. Das Modul besteht aus Dateilesungen und regulären
   Ausdrücken.
2. **Fail-closed, und "unbekannt" ist nicht "sauber".** Eine unlesbare Datei,
   ein Binärblob, ein abgeschnittener Read und ein fehlendes Verzeichnis
   ergeben `UNSCANNABLE`, nie `CLEAR`. Die Eigenschaft `Verdict.cleared` ist
   der ganze Vertrag: wahr nur bei vollständigem Scan ohne Befund und ohne
   übersprungene Stelle. Aufrufer dürfen sie nicht aus einer leeren
   Befundliste neu ableiten.
3. **Befunde, keine Punktzahlen.** Ein `Finding` trägt Datei, Zeile und den
   getroffenen Text, damit ein Mensch durch Hinsehen widersprechen kann.
4. **Keine eigene Host-Policy.** Ob Bytes die Maschine verlassen dürfen, hat
   genau eine Implementierung -- `lane_for_host` in
   [sensitivity.py](../../../daedalus/sensitivity.py) -- und dieses Modul ruft
   sie auf, statt neu zu entscheiden.
5. **Eine Deklaration ist eine Bitte, nie eine Bewilligung.** Ein
   `allowed-tools`-Feld im Frontmatter eines Skills wird als Anfrage protokolliert
   und eskaliert die Prüfung; es autorisiert nichts.

## Angriffsflächen, die der Code ausdrücklich unterscheidet

- Ein **Skill** ist Text, der ein Modell erreicht: die Fläche ist
  Prompt-Injection und Instruktionsschmuggel, plus alles, was sein
  mitgeliefertes `scripts/`-Verzeichnis täte, wenn es jemand ausführte.
  `vet_skill` scannt deshalb ausdrücklich auch das Frontmatter, nicht nur den
  Body -- ein adversarialer Review vom 2026-08-17 hat gemessen, dass eine
  Injection in der `description` vorher `CLEAR` ergab, während derselbe Satz
  im Body auf drei Regeln blockte.
- Ein **MCP-Server** ist ein Prozess mit einem Socket: die Fläche ist
  Ausführung und Egress. `vet_mcp_server` startet und kontaktiert nichts.
  Ein fehlgeformtes Feld wird als `UNSCANNABLE` gemeldet und nicht gecastet --
  ein `args`-Wert, der ein String statt einer Liste ist, iterierte früher pro
  Zeichen und ergab dadurch ein leeres Kommando und ein `CLEAR`.
- **Unsichtbare Codepoints** werden für den Abgleich entfernt *und* gemeldet:
  ein per Zero-Width-Zeichen zerteiltes Schlüsselwort sieht für die Regex wie
  zwei Tokens aus, für einen Parser wie ein Identifier und für ein Modell wie
  das Original.

## Allowances

Manche Werkzeuge existieren, um genau das zu tun, was eine Regel meldet. Dafür
gibt es `.agentenv/tool-allowances.json` (`ALLOWANCE_PATH`), gelesen von
`load_allowances` und angewandt von `apply_allowances`. Die Eigenschaften sind
bewusst eng:

- eine Allowance muss **Subjekt und exakte Regel-ID** nennen; es gibt keinen
  Platzhalter;
- sie **stuft auf `REVIEW` herab, nie auf `CLEAR`** -- die Fähigkeit besteht
  weiter und wird bei jedem Lauf mit ihrer Begründung gemeldet;
- eine Allowance, die auf einen Namen statt auf ein Digest gepinnt ist, wird
  als solche markiert, weil sonst jedes Werkzeug, das auf diesen Namen hört,
  sie erbt;
- eine unparsbare Allowance-Datei ist ein Fehler, der den Bericht als
  *degraded* markiert, nie eine leere Allowance-Menge, die still alles blockt;
- eine Allowance, die eine Regel nennt, die gar kein `BLOCK` ist, ist inert und
  wird gemeldet -- `RULE_SEVERITY` existiert genau für diese Prüfung.

## Trust-Grenzen / Effekte

- **Keine registrierte Effekt-Tür.** Beide Module lesen Dateien und geben
  Daten zurück. `inventory.main` ist eine dünne CLI, die auf stdout druckt;
  ein Grep nach `begin_effect` in `daedalus/tools` findet nichts (gemessen
  2026-09-05).
- **Keine Ausführung des Geprüften**, siehe Invariante 1. Der einzige
  Fremdcode, den dieses Paket berührt, sind seine eigenen regulären Ausdrücke.
- **Lesegrenzen sind Teil des Verdikts.** `MAX_FILE_BYTES` und
  `MAX_FILES_SCANNED` begrenzen den Scan; wird eine Grenze erreicht, landet
  das in `Verdict.skipped` und damit im Ergebnis, statt als stiller Teilscan
  durchzugehen.
- **Der Nutzer-Scope ist sichtbar, nicht implizit.** `collect_skills` und
  `collect_mcp_servers` nehmen `include_user`; ein durch einen Projekt-Skill
  verdeckter Nutzer-Skill wird beidseitig gemeldet statt verschwiegen.
- Für den Rest der Kette -- welcher Provider welches Werkzeug tatsächlich
  bekommt -- ist [Runtime-Provider](runtimes-providers.md) bzw. der
  Provider-Router zuständig, nicht dieses Paket.

## Tests

- [tests/test_tools_vet.py](../../../tests/test_tools_vet.py) -- Regeltabelle,
  Fail-closed-Verhalten, Frontmatter-Scan, Allowances, MCP-Spezifikationen.
- [tests/test_inventory_shadowing.py](../../../tests/test_inventory_shadowing.py) --
  Verdeckung zwischen Projekt- und Nutzer-Scope.
- [tests/contracts/test_import_scc_hierarchy.py](../../../tests/contracts/test_import_scc_hierarchy.py) --
  die Importlage des Pakets.

## Verwandt

- [Tool vetting](../tool-vetting.md) -- die kürzere Erzählfassung dieser Seite.
- [Claude-Skills und Proposals](../tooling/claude-proposals.md) sowie
  [ui-ux-pro-max-Skripte](../tooling/claude-skills-ui-ux-pro-max-scripts.md) --
  konkrete Subjekte, die durch dieses Gate gehen.
- [Foundation](foundation.md) -- `skills.load_skill`, der einzige
  `SKILL.md`-Parser, dessen Dataclass `vet_skill` entgegennimmt.
- [Runtime-Provider](runtimes-providers.md), [Runtimes](runtimes.md) --
  wohin ein freigegebenes Werkzeug danach geroutet wird.
- [Kernel-Policy](kernel-policy.md) -- die mechanische Veto-Schicht.
- [Structcore](structcore.md) -- derselbe "derive, don't maintain"-Vertrag.
- [Tools-Verzeichnis](../tooling/tools.md) -- die Skripte unter `tools/`, die
  nicht mit diesem Paket zu verwechseln sind.
- [Wiki-Index](../index.md).

## Ungeklärt

- Wer `inventory.build` in der laufenden Anwendung aufruft, habe ich nicht
  ausgemessen; der Docstring beschreibt das Modul als Naht zwischen zwei
  vorher konsumentenlosen Hälften, nennt aber keinen Aufrufer.
- Die im Docstring zitierten Erhebungszahlen zu Community-Skills stammen aus
  einer externen Quelle vom 2026-07-30 und sind hier nicht nachgeprüft.
