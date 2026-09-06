---
title: Foundation
type: module
status: living
updated: 2026-09-05
covers: daedalus/foundation
---
# Foundation

`daedalus/foundation` ist die Blatt-Schicht: Module, von denen jede andere
Schicht abhaengen darf, ohne eine Abhaengigkeit umzukehren. Der
Paket-Docstring formuliert dafuer einen messbaren Aufnahmetest statt eines
Namensgefuehls: ein Modul gehoert hierher, wenn es **gar keinen**
`daedalus.*`-Import hat oder nur einen, der weiter nach unten in dieses Paket
zeigt. Im Kernel/Ikarus/Ariadne-Bild gehoert nichts hiervon zur
Trust-Grenze — das Paket faellt keine Policy-Entscheidung und promotet nichts.

Der Docstring haelt ausserdem eine bewusste Inkonsistenz fest: sieben flache
Module auf oberster Paketebene (`atomic`, `budget`, `config`, `limit_policy`,
`primary_tree`, `sensitivity`, `storage`) sind nach demselben Test Foundation,
bleiben aber oben, weil `docs/architecture/import-boundaries.json` sie
namentlich in den `allowed_target_prefixes` der Kernel-, Spine- und
Twin-Regeln fuehrt. Ein Umzug waere eine Migration des Boundary-Vertrags mit
eigenem Review, kein Rename.

Gemessen 2026-09-05: 9 `.py`-Dateien, 3200 Zeilen.

## Module

| Datei | Was sie tut | Wichtige Symbole |
| --- | --- | --- |
| [`__init__.py`](../../../daedalus/foundation/__init__.py) | Nur der Docstring mit dem Aufnahmetest und der Begruendung fuer die sieben oben gebliebenen Module. Kein Code. | — |
| [`text_integrity.py`](../../../daedalus/foundation/text_integrity.py) | Presentation-only: kollabiert einen beliebigen Wert auf eine Zeile druckbares ASCII und begrenzt ihn danach. Zurueckbehaltene Evidenz bleibt woertlich; das Terminal ist die verlustbehaftete Projektion. | `safe_terminal_text`, `TERMINAL_FIELD_MAX_CHARS` |
| [`claude_detect.py`](../../../daedalus/foundation/claude_detect.py) | Liest die Subagent-Definitionen aus `.claude/agents/*.md` eines Repos. Minimaler Frontmatter-Leser ohne YAML-Laufzeit, tolerant gegenueber gefalteten Bloecken. | `detect_claude_crew`, `parse_frontmatter` |
| [`env.py`](../../../daedalus/foundation/env.py) | Serverseitiges Laden der Umgebungsdatei plus **redigierte** Bereitschaftsmetadaten fuer Statusflaechen. Web-UI und Editor-Wrapper bekommen nie einen Geheimniswert. | `load_env`, `env_status`, `SECRET_KEYS`, `PUBLIC_KEYS`, `ENV_PATH` |
| [`dotenv.py`](../../../daedalus/foundation/dotenv.py) | Der strengere Zwilling von `env.py`: laedt nur Luecken, verweigert laut bei einer git-verfolgten Datei, und gibt ausschliesslich die gesetzten Namen zurueck. | `load`, `parse`, `describe`, `DotEnvRefused`, `DEFAULT_ENV_PATH` |
| [`projects.py`](../../../daedalus/foundation/projects.py) | Die Projekt-Registry: kanonischer Repository-Pfad als Identitaet, ein Zeilendokument pro Projekt, exklusiv-atomare Publikation unter einem OS-Lock. | `register_project`, `list_projects`, `load_project`, `rewrite_project_team`, `resolve_repo_root`, `resolve_registered_project_root`, `ProjectRegistrationError`, `ProjectRegistryUnavailable`, `ProjectRowUpdateError`, `ProjectRowNotFound` |
| [`preservation.py`](../../../daedalus/foundation/preservation.py) | Asymmetrischer Stolperdraht auf der Prosa-Spur: welche faktentragenden Marker des Vorher-Textes im Nachher-Text nicht mehr vorkommen. | `check_preservation`, `PreservationResult`, `Finding`, `project`, `is_prose_path`, `LOST`, `REDUCED`, `DEMOTED`, `SECTION`, `RECASED`, `STRUCTURE`, `SEVERITY_ORDER`, `BLOCKING` |
| [`accelerators.py`](../../../daedalus/foundation/accelerators.py) | Evidenzbasiertes Inventar optionaler GPU-Spuren. Trennt drei Fragen, die sonst verschwimmen: sichtbare Hardware, installiertes und CUDA-faehiges Backend, und Anwendbarkeit auf eine konkrete Daedalus-Operation. | `accelerator_status`, `nvidia_hardware_status`, `deep_framework_status`, `capability_lanes`, `ComputeLane`, `RTX_OLLAMA_ENV`, `RTX_TOKEN_ENV`, `RTX_SSH_ENV`, `NVOF_SDK_ENV` |
| [`skills.py`](../../../daedalus/foundation/skills.py) | Liest das Agent-Skills-Format als **Daten**. Startet nichts, oeffnet keinen Socket, faellt keine Dispatch-Entscheidung. | `load_skill`, `discover`, `find_skill`, `parse_frontmatter`, `validate_frontmatter`, `render_untrusted`, `render_catalog`, `describe`, `skill_field_names`, `Skill`, `SkillDefect`, `LoadReport`, `SkillError`, `SKILL_FILENAME`, `SPEC_URL`, `SPEC_SHA256`, `MAX_SKILL_MD_BYTES`, `SKILL_DATA_NOTICE` |

## Zwei Lader fuer dieselbe Datei

`env.py` und `dotenv.py` lesen beide die Umgebungsdatei, aber mit
unterschiedlichem Anspruch. `env.py` fuellt die Prozessumgebung und liefert
`env_status` — ein Dict, das pro Geheimnis nur `configured: true/false` traegt,
nie den Wert. `dotenv.py` ist die spaetere, strengere Fassung mit drei Regeln,
von denen der Docstring die mittlere ausdruecklich als die
Sicherheitseigenschaft markiert:

1. eine echte Umgebungsvariable gewinnt immer; die Datei fuellt nur Luecken,
   was den Lader idempotent macht;
2. eine **git-verfolgte** Umgebungsdatei wird laut verweigert
   (`DotEnvRefused`) — ein verfolgtes Geheimnis ist bereits ein Leck, und sie
   zu laden wuerde das Leck bequem statt sichtbar machen; dies ist die einzige
   Bedingung, die wirft statt zu degradieren;
3. Werte werden nie geloggt, gespiegelt oder zurueckgegeben; `load` liefert
   die gesetzten **Namen**.

Der Docstring sagt auch, was `dotenv.py` nicht ist: keine dotenv-Bibliothek,
sondern genau die Teilmenge, die die Beispieldatei tatsaechlich benutzt —
Schluessel-Wert, Kommentare, ein optionales `export`-Praefix, umschliessende
Anfuehrungszeichen. Keine Interpolation.

## Der Praeservations-Stolperdraht

`preservation.py` beginnt mit einer Warnung an den Leser: "This is a tripwire,
not a gate. It raises the floor without moving the ceiling. Human review
remains the gate." Bewiesen wird eine einzige, syntaktische, gerichtete
Aussage — faktentragende Tokens aus dem Vorher-Text stehen irgendwo im
Nachher-Text. Ueber Richtigkeit, Vollstaendigkeit oder Ehrlichkeit einer
Umschreibung sagt das nichts.

Sechs Schweregrade sind definiert, aber nur einer blockiert: `BLOCKING` ist
absichtlich einelementig und enthaelt nur `LOST`. `REDUCED`, `DEMOTED`,
`SECTION`, `RECASED` und `STRUCTURE` werden berichtet, nicht durchgesetzt.
`check_preservation` ist rein und offline; `PreservationResult.summary` liefert
eine Zeile, die direkt in ein Verifier-Detail passt.

Der Docstring nennt den Anlass beim Namen: die Verifier-Kette verzweigte auf
Python, JSON/YAML, JavaScript und HTML — eine Markdown-Schreibung fiel hinten
heraus und wurde auf der Staerke von "der Report parste und eine Datei hat sich
geaendert" akzeptiert. Genau das "empty green", das der Rest der Maschinerie
verhindern soll.

## Skills als Daten

`skills.py` ist die Umsetzung einer eng gefassten Uebernahme: von einem
evaluierten Fremd-Framework wurde ausschliesslich das `SKILL.md`-**Format**
uebernommen, nicht dessen Scheduler, Ledger, Sicherheitspraedikat oder
Transkript-Speicher. Das Modul parst eine Textdatei und gibt eine Dataclass
zurueck.

Die Spezifikation ist gepinnt, obwohl sie selbst keine Version fuehrt: der
Docstring haelt fest, dass das Upstream-Repository zum Lesezeitpunkt null Tags
und null Releases hatte, und pinnt deshalb Bytes — Commit, Blob-SHA und
`SPEC_SHA256`. Das ist die im Masterplan geforderte Provenienz auf einer
externen Quelle.

> **Extern:** Das Agent-Skills-Format (`SKILL.md` mit YAML-Frontmatter,
> Feldern `name` und `description`) ist die uebernommene Struktur; die im Code
> gepinnten Laengengrenzen (64 Zeichen Name, 1024 Zeichen Beschreibung, 500
> Zeichen Kompatibilitaet) stammen woertlich aus dieser Spezifikation.
> Quelle: https://agentskills.io/specification

Sicherheitsrelevant ist die Ausgabeseite, nicht die Eingabeseite:
`render_untrusted` rahmt jeden Skill-Inhalt zwischen `SKILL_OPEN` und
`SKILL_CLOSE` mit einem `SKILL_DATA_NOTICE` und entschaerft Zeilen, die wie
ein Rahmen-Marker aussehen. Der Text eines Skills bleibt damit Daten und wird
nicht zur Anweisung. Dazu kommen harte Obergrenzen (`MAX_SKILL_MD_BYTES`,
`MAX_FRONTMATTER_LINES`, `MAX_SKILLS_PER_ROOT`) und eine Traversal-Sperre auf
Skill-Namen und gebuendelten Pfaden.

## Trust-Grenzen / Effekte

Der Paket-Docstring sagt: "This package holds no policy, opens no store, and
spawns nothing." Das stimmt fuer sieben der neun Module. Zwei weichen ab, und
beide Abweichungen sind anderswo im Baum bereits als Ausnahme verbucht:

**`projects.py` schreibt.** `register_project` publiziert eine JSON-Zeile unter
`projects/` per `publish_bytes_once` — ein exklusiv-atomares Anlegen, damit
eine gleichzeitige Namenskollision keine fremde Konfiguration ueberschreiben
kann — unter einem `ExclusiveFileLock` aus
[`daedalus/atomic.py`](../../../daedalus/atomic.py) mit
`PROJECT_REGISTRY_LOCK_TIMEOUT_S`. Identitaet ist der kanonische Pfad, nicht
der Name: eine erneute Registrierung desselben Wurzelverzeichnisses schreibt
nichts. Der Docstring von `register_project` betont "without adding policy" —
die Zeile enthaelt nur Anzeigename und Wurzel. Namensbildung normalisiert
Unicode und sperrt die reservierten Windows-Geraetenamen.

**`accelerators.py` spawnt und geht ins Netz.** Drei Spawn-Stellen und eine
Egress-Stelle: `nvidia-smi` lokal, ein Python-Kindprozess fuer die tiefe
Framework-Sonde, `ssh` zu einem konfigurierten entfernten Ziel, und ein
`urllib`-Aufruf auf den Modell-Endpunkt eines konfigurierten Remote-Hosts. Es
gibt in diesem Verzeichnis kein `begin_effect` und keine eigene Zeile in der
Effect-Registry unter
[`daedalus/spine/effect_boundary.py`](../../../daedalus/spine/effect_boundary.py)
(gemessen 2026-09-05). Das ist **keine Registry-Luecke, sondern
Docstring-Drift**: die Registry ist tuerbasiert, und `accelerators.py` wie
`projects.py` sind Bibliothekscode ohne `main`; ihre Effekte werden der
aufrufenden registrierten Tuer zugerechnet (Messung der Review-Session
2026-09-05 gegen die Registry-Discovery). Falsch ist nur der Satz
"spawns nothing" im Paket-Docstring. Die Ausnahme ist in
[`tests/test_budget.py`](../../../tests/test_budget.py) namentlich eingetragen,
mit der Begruendung "nvidia-smi and a local /api/tags probe"; in
[`tests/test_host_predicate.py`](../../../tests/test_host_predicate.py) ist das
Modul als bekannte Duplikat-Stelle des Lokalitaets-Praedikats gefuehrt, mit der
Notiz "Not an egress lane". Beide Netz-/SSH-Pfade sind hinter den
Schaltern `deep` beziehungsweise `probe_remote` von `accelerator_status`
verriegelt und laufen ohne diese nicht.

Verantwortlich fuer Redaktion ist `_redacted_endpoint`: Endpunkte werden nicht
roh in den Status geschrieben. Der optionale Bearer-Token wird aus der
Umgebung gelesen und als Header gesetzt, aber nicht zurueckgegeben.

`claude_detect.py`, `skills.py`, `preservation.py`, `text_integrity.py` und
`env_status` sind lesend beziehungsweise rein.

## Tests

Gemessen 2026-09-05 referenzieren 25 Dateien unter `tests/` dieses Paket. Die
direkt zugeordneten sind:

- [`tests/test_dotenv.py`](../../../tests/test_dotenv.py) — Lueckenfuellung,
  Verweigerung bei verfolgter Datei, Namensrueckgabe.
- [`tests/test_preservation.py`](../../../tests/test_preservation.py) — die
  Schweregrad-Klassifikation.
- [`tests/test_skills.py`](../../../tests/test_skills.py) — Parser, Grenzen und
  die Daten-statt-Anweisung-Rahmung.
- [`tests/test_accelerators.py`](../../../tests/test_accelerators.py) — die
  Statuszeilen inklusive Sondenfehler-Diagnostik.
- [`tests/test_claude_detect.py`](../../../tests/test_claude_detect.py) — der
  Frontmatter-Leser.
- [`tests/test_project_registration.py`](../../../tests/test_project_registration.py)
  und
  [`tests/test_project_row_rewrite.py`](../../../tests/test_project_row_rewrite.py)
  — Registry-Identitaet und Zeilen-Umschreibung.
- [`tests/contracts/test_no_dangling_daedalus_imports.py`](../../../tests/contracts/test_no_dangling_daedalus_imports.py)
  und
  [`tests/contracts/test_repo_root_derivation_depth.py`](../../../tests/contracts/test_repo_root_derivation_depth.py)
  — die Blatt-Eigenschaft und die Tiefe der Wurzelableitung als Vertrag.
- [`tests/test_budget.py`](../../../tests/test_budget.py) und
  [`tests/test_host_predicate.py`](../../../tests/test_host_predicate.py) —
  fuehren `accelerators.py` als benannte Ausnahme.

## Verwandt

- [Daedalus-Paketwurzel](daedalus-package-root.md) — die sieben flachen
  Foundation-Module, die oben geblieben sind.
- [Kernel](kernel.md) und [Spine](spine.md) — die Schichten, die von hier
  importieren duerfen und nicht umgekehrt.
- [Runtimes](runtimes.md) — Konsument von `skills.py` und `env.py`.
- [Council](council.md) — teilt sich mit `accelerators.py` die Frage, ob ein
  Host lokal ist.
- [Tool-Vetting](../tool-vetting.md) — das Verfahren, das ueber eine externe
  Uebernahme wie das Skill-Format entscheidet.
- [Agenten halten keinen Zustand](../decisions/agents-hold-no-state.md)
- [Wiki-Index](../index.md)

## Ungeklaert

- **Ungeklaert:** `env.py` und `dotenv.py` sind zwei Lader fuer dieselbe Datei
  mit unterschiedlicher Strenge. Welcher der kanonische ist und ob `env.py`
  abgeloest werden soll, steht in keinem der beiden Docstrings.
- **Ungeklaert:** `accelerators.py` liest ausser der Ollama- auch eine
  SSH-Zielvariable mit einem zweiten, aelteren Fallback-Namen. Welche der
  beiden die aktuelle ist, geht aus dem Code nicht hervor.
- **Abweichung (Docstring-Drift):** Der Paket-Docstring behauptet "spawns
  nothing", und `accelerators.py` spawnt drei Prozesse. Eine Registry-Luecke
  ist das nicht (Bibliothekscode, keine Tuer); der Docstring ist aelter als
  das Modul.
- **Ungeklaert:** `claude_detect.py` beschreibt in seinem Docstring eine
  Mission-Control-Oberflaeche, die die gefundenen Subagenten zusaetzlich
  anzeigt. Ob dieser Konsument noch existiert, ist aus dem Verzeichnis nicht
  entscheidbar.
