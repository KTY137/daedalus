---
title: Ariadne
type: module
status: living
updated: 2026-09-05
covers: daedalus/ariadne
---
# Ariadne

`daedalus/ariadne` ist die dritte der drei oeffentlichen Konzepte des
Masterplans (Abschnitt 3): die kontrollierte Evolutions-Last. Im heutigen Baum
ist davon genau *eine* Kampagne implementiert — eine deterministische
Reparatur-Kampagne ohne Modell, ohne Suche, ohne Population. Der Modul-Docstring
sagt, worum es geht: "One bounded deterministic repair campaign; nomination is
the terminal ceiling." Die Kampagne darf nominieren und sonst nichts. Kein
Merge, keine Promotion, kein Schreiben in den primaeren Checkout. Das ist
Invariante 5 (Sealed promotion) als Code statt als Absichtserklaerung.

Der Wert dieses kleinen Verzeichnisses liegt nicht im Reparatur-Operator — er
ist ein exakter Textersatz — sondern in der Kontrollstruktur darum herum: drei
Arme unter gleichem Budget, ein eingefrorener Evaluator, eine Negativkontrolle,
und die Weigerung, ein Ergebnis zu melden, dessen Effektspur nicht vollstaendig
zurueckbehalten wurde.

Gemessen 2026-09-05: 3 `.py`-Dateien, 1984 Zeilen; davon 1926 in `campaign.py`.

## Module

| Datei | Was sie tut | Wichtige Symbole |
| --- | --- | --- |
| [`__init__.py`](../../../daedalus/ariadne/__init__.py) | Re-Export der vier oeffentlichen Namen. Sonst nichts. | `run_campaign`, `AriadneCampaignError`, `AriadneRequestError`, `AriadneConflictError` |
| [`__main__.py`](../../../daedalus/ariadne/__main__.py) | Die CLI-Tuer. Ruft `begin_effect` fuer `cli.ariadne_campaign` **vor** dem Argument-Parsing, parst dann Repo-Wurzel, Revision, Kampagnen-ID, Zielpfad, Vorher-/Nachher-Text und Timeout und druckt das Ergebnis als JSON. | `main` |
| [`campaign.py`](../../../daedalus/ariadne/campaign.py) | Die gesamte Kampagne: Validierung, Lease, Kampagnen-Vertrag, drei Arme, Evaluator-Verifikation, Budget-Gleichheitsnachweis, Nominierung und Abbruchpfade. | `run_campaign`, `ENTRYPOINT_ID`, `EVALUATOR_SOURCE`, `EVALUATOR_SHA256`, `MAX_REPAIR_FRAGMENT_BYTES`, `MAX_CAMPAIGN_FILE_BYTES`, `AriadneCampaignError`, `AriadneRequestError`, `AriadneConflictError` |

## Die Kampagne

`run_campaign` nimmt Repo-Wurzel, exakte 40-stellige Git-Revision,
Kampagnen-ID, Zielpfad, `before`-Text, `after`-Text und ein Timeout. Vor jedem
Effekt laeuft eine lange Kette von Ablehnungsgruenden:

- die Kampagnen-ID muss dem eingefrorenen Muster entsprechen;
- `before` und `after` muessen sich unterscheiden und duerfen
  `MAX_REPAIR_FRAGMENT_BYTES` (1 MB) nicht ueberschreiten;
- der Zielpfad wird gegen die Repo-Wurzel aufgeloest und darf nicht
  herauszeigen;
- `verify_repository_head_revision` bindet die angegebene Revision an den
  tatsaechlichen HEAD; eine Abweichung wird als `AriadneConflictError`, eine
  unlesbare HEAD-Form als `AriadneRequestError` unterschieden;
- das Ziel muss striktes UTF-8 sein und `before` muss darin **genau einmal**
  vorkommen;
- Reparatur- und Kontroll-Ausgabe duerfen `MAX_CAMPAIGN_FILE_BYTES` (16 MB)
  nicht ueberschreiten.

Der Kampagnen-Vertrag ist ein `ExperimentSpec` mit
`seeds=(0, 1, 2)`, `metrics=("exact_match",)`, `operator_axis="repair_variant"`
und `selection_policy="best_passed_trial"`. Das Feld `frozen_components` bindet
Compiler, Evaluator, Fixture, Generator, Modell, Operator und die
HEAD-Quittung je als Digest — Masterplan Abschnitt 8, Schritt 1 ("Freeze an
ExperimentSpec") woertlich genommen. Der Spec hat ein `expires_at` von 15
Minuten.

### Drei Arme, eine Achse

Die Armliste ist im Code hart und geordnet: `baseline` (Rolle `baseline`,
Seed 0), `negative-control` (Rolle `candidate`, Seed 1), `repair` (Rolle
`candidate`, Seed 2). Der Kontrollarm ersetzt `before` durch `before` plus
einen festen Suffix; faellt dieser Mutant zufaellig mit der gewuenschten
Reparatur zusammen, wird der Suffix ein zweites Mal angehaengt, damit die
Kontrolle deterministisch verschieden bleibt.

Am Ende wird die Erwartung nicht abgeschwaecht, sondern erzwungen: Baseline und
Negativkontrolle muessen `failed` sein und die Reparatur `passed`. Andernfalls
bricht die Kampagne mit "controlled repair requires failed baseline and negative
control plus a passed repair" ab. Ein Evaluator, der alle drei Arme akzeptiert,
diskriminiert nicht — und ein nicht diskriminierender Evaluator liefert hier
kein Ergebnis.

### Der eingefrorene Evaluator

`EVALUATOR_SOURCE` ist ein vierzeiliges Python-Skript, das den SHA-256 einer
Datei mit einem erwarteten Digest vergleicht und JSON auf stdout schreibt.
`EVALUATOR_SHA256` ist sein Digest und geht in `frozen_components` ein. Die
Beobachtung wird nicht geglaubt, sondern nachgeprueft: die Ausgabe muss der
Schluesselmenge `_EVALUATOR_OBSERVATION_KEYS` entsprechen, ihr Schema muss eines
der beiden retained Observationsschemata sein, und `variant_id`, `seed` sowie
der Evaluator-Digest muessen zum Trial passen. Schema `/2` traegt zusaetzlich
die pfadfreie Interpreter-Identitaet aus
[`daedalus/kernel/interpreter.py`](../../../daedalus/kernel/interpreter.py).

Der Kandidat sieht seinen Evaluator nicht als aenderbares Artefakt: er wird aus
dem CAS in einen Attempt-Workspace ausserhalb des Checkouts materialisiert und
in einem contained Kindprozess ausgefuehrt (Invariante 3).

### Budget-Gleichheit als Datensatz

`CampaignBudgetEqualityEvidence` haelt fest, dass alle Arme unter derselben
`ResourceBudget` (`max_wall_time_s=timeout_s`, `max_attempts=1`) liefen, mit
`trial_keys` aus Variante und Seed. Ueberschreitet ein zurueckbehaltener Trial
seine Decke, stoppt die Kampagne *vor* dem naechsten Seed und schreibt eine
Quittung mit Blocker statt einer Nominierung. Das ist die Umsetzung von
Invariante 9 (Honest claims) und Abschnitt 14 ("identical problem definitions
and compute/token budgets").

### Nominierung ist die Decke

Bei Erfolg entsteht ein `NominationReceipt` mit Status `nominated`, das
Kandidaten-Baum, Evidence-Paket und Policy-Entscheidung per Digest bindet, plus
ein `CampaignReceipt` mit `outcome="nominated"`. Danach ist Schluss. Es gibt in
diesem Verzeichnis keinen Aufruf einer Promotion-, Merge- oder Approval-Funktion.

## Trust-Grenzen / Effekte

Zwei ineinanderliegende Effektgrenzen, bewusst getrennt:

1. **Aussen, `cli.ariadne_campaign`** — die Modul-Tuer in `__main__.py`. Ihr
   Kommentar begruendet die Reihenfolge: "argument handling must not be able to
   precede the process-wide spend/process guard". Sie deckt nur den
   Prozess-Guard ab.
2. **Innen, `python.ariadne_campaign`** — `run_campaign` selbst. Die
   Registry-Zeile in
   [`daedalus/spine/effect_boundary.py`](../../../daedalus/spine/effect_boundary.py)
   deklariert `Effect.FILESYSTEM_WRITE`, `Effect.PROCESS_SPAWN` und
   `Effect.PROCESS_CONTROL` mit den Guard-Vertraegen `provider.write_policy`,
   `budget.process_guard`, `containment.attempt` und `containment.worktree`,
   Wiring `CENTRAL`. Die Notiz sagt ausdruecklich: "it has no approval, merge,
   promotion, repository-mutation, egress, spend, or secret authority."

`run_campaign` erwirbt vor jedem Schreibzugriff ein `acquire_effect_lease` mit
`writable_paths=(relative,)`, `tools=("python",)`, `max_spend_usd=None`,
`contained=True` und einer `Policy(write_allow=(relative,))`. Eine
`WaveLeaseDenied` beendet den Lauf. Danach kommt `begin_effect`, danach ein
`ExclusiveFileLock` auf `candidate-execution.lock` — derselbe Lock, den Genesis
benutzt, damit nicht zwei Kandidaten-Ausfuehrungen gleichzeitig laufen.

Bemerkenswert ist die Retentionsdisziplin. `_outer_effect_binding` verweigert
**vor** `begin_effect`, dem Lock, dem CAS und der SQLite-Datei, wenn die exakte
Subject/Execution-Kette nicht verfuegbar ist; der Kommentar nennt das
ausdruecklich "part of this product boundary, not best-effort telemetry".
`_require_campaign_inner_effect_terminals` prueft nach jedem Ausgang, dass jede
innere Effektspur ihren Terminal-Datensatz hat.

Der Ausnahmepfad ist die interessanteste Stelle der Datei: ist die Quittung
bereits kanonisch und dauerhaft (`campaign_committed`), wird der aeussere
Effekt **nicht** nachtraeglich auf FAILED umgeschrieben. Der Aufrufer bekommt
stattdessen sichtbare Abstimmungsschuld. Andernfalls wird von innen nach aussen
terminalisiert: Attempt, innerer Effekt, Kampagne, aeusserer Effekt — und
Aufraeumfehler werden bewusst verschluckt, damit der urspruengliche Fehler die
gemeldete Ursache bleibt.

Der Kill-Switch aus
[`daedalus/spine/killswitch.py`](../../../daedalus/spine/killswitch.py) wird an
den Lease uebergeben; der Zustand liegt unterhalb von `control_root(root)`,
also ausserhalb des Repositorys.

## Tests

Gemessen 2026-09-05:

- [`tests/test_ariadne_campaign_v0.py`](../../../tests/test_ariadne_campaign_v0.py)
  — 26 Testfunktionen auf 1326 Zeilen, die Haupt-Abdeckung des Verzeichnisses.
- [`tests/interfaces/test_http_ariadne.py`](../../../tests/interfaces/test_http_ariadne.py)
  — 8 Testfunktionen fuer die HTTP-Seite der Kampagne.
- [`tests/test_cli_effect_boundary.py`](../../../tests/test_cli_effect_boundary.py)
  — die CLI-Tuer als registrierter Effekt-Einstieg.
- [`tests/test_registry_new_doors.py`](../../../tests/test_registry_new_doors.py)
  — die Registry-Zeilen selbst.

## Verwandt

- [Kernel](kernel.md) — Attempts, Effect-Leases, Campaigns, Source-Trees.
- [Kernel-Vertraege](kernel-contracts.md) — `ExperimentSpec`, `CampaignReceipt`,
  `NominationReceipt`, `EvidencePacket`.
- [Spine](spine.md) — die Effect-Registry und der Kill-Switch.
- [Gates-Repository](gates-repository.md) — die HEAD-Bindung, an der die
  Kampagne ihre Revision verifiziert.
- [Orchestrierung](orchestration.md) — die Missions-Seite, gegen die Ariadne
  ausdruecklich abgegrenzt ist.
- [Graph-Delta als Fitness](../graph-delta-as-fitness.md) — die aeltere
  Ueberlegung, warum ein Graph-Delta keine Fitness ist.
- [Wiki-Index](../index.md)

## Ungeklaert

- **Ungeklaert:** Der Masterplan (Abschnitt 8) beschreibt Ariadne als Suche
  ueber Motive, Operatoren, Kontextstrategien und Orchestrierungs-Rezepte. Im
  Code existiert nur die Achse `repair_variant` mit exaktem Textersatz. Ob
  weitere Operatoren geplant, verworfen oder anderswo implementiert sind, geht
  aus dem Verzeichnis nicht hervor.
- **Ungeklaert:** `_EVALUATOR_OBSERVATION_SCHEMAS` fuehrt zwei Versionen, und
  der Kommentar sagt, `/1` sei aelter als die Interpreter-Provenienz. Ob noch
  Datensaetze mit `/1` existieren oder ob die Akzeptanz nur historisch ist, ist
  nicht ablesbar.
- **Ungeklaert:** Die 15-Minuten-Ablauffrist des `ExperimentSpec` wird beim
  Erzeugen gesetzt; wo sie beim Replay geprueft wird, ist in diesem Verzeichnis
  nicht sichtbar.
- **Ungeklaert:** `run_campaign` gibt ein `dict` zurueck (die Quittung als
  `to_dict`), nicht den Datensatz selbst. Ob das ein bewusster Serialisierungs-
  Vertrag fuer die HTTP-Seite ist, steht nirgends.
