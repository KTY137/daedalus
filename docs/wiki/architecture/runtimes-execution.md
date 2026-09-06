---
title: Runtimes Execution
type: module
status: living
updated: 2026-09-05
covers: daedalus/runtimes/execution
---
# Runtimes Execution

`daedalus/runtimes/execution` ist das prozessweite Netz, das Geld-Ausgaben
sichtbar macht, ohne dass eine einzige Aufrufstelle geaendert werden muss.
Zwei Dateien, 565 Zeilen (gemessen 2026-09-05), davon 564 in
`budget_process.py`. Die Aufgabenteilung ist ausdruecklich: **das Ledger im
Kernel besitzt den Geldzustand** (siehe [Kernel-Policy](kernel-policy.md)),
dieses Paket adaptiert Prozess-Spawns und `urllib`-Anfragen an dieses Ledger.
Im Kernel/Ikarus/Ariadne-Bild gehoert es zur Runtime-Schicht (Masterplan
Abschnitt 4, Invariante 8: gebundene Effekte), nicht zur Policy: es entscheidet
nicht, was ein Aufruf kosten darf, sondern nur, dass ein Aufruf ueberhaupt als
Ausgabe *gesehen* wird.

Der Grund, aus dem das Netz existiert, steht im Docstring von
`install_process_guard`: das Repository hat keinen einzelnen Engpass. Bezahlte
Aufrufe verlassen die Maschine unabhaengig voneinander aus `daedalus/providers`
(siehe [Providers](providers.md)), `daedalus/council/vendors.py`,
`daedalus/orchestration/ikarus/shell.py` und `runs/`. Der Guard ist grob -- er
bepreist nach Vendor, nicht nach Aufgabe -- und opt-in. Er ist ein **Netz**,
kein Ersatz fuer eine explizite Reservierung an einer Stelle, die ihre eigenen
Kosten kennt.

## Module

| Datei | Zweck | Wichtige Symbole |
| --- | --- | --- |
| [`__init__.py`](../../../daedalus/runtimes/execution/__init__.py) | Einzeiliger Paket-Docstring ("Runtime execution adapters"). Kein Reexport; Aufrufer importieren `budget_process` direkt. | -- |
| [`budget_process.py`](../../../daedalus/runtimes/execution/budget_process.py) | Klassifikation und Interposition. Enthaelt den expliziten Kontextmanager, die beiden Klassifizierer, die drei Wrapper, Installation und Deinstallation sowie das Ausgabenregister. | `guard`, `classify_argv`, `classify_url`, `install_process_guard`, `uninstall_process_guard`, `BILLABLE_SITES` |

## Was als Ausgabe zaehlt

`classify_argv` liefert eine Vendor-Kennung, wenn ein `argv` Geld kostet, sonst
`None`. Konservativ in genau die Richtung, die zaehlt: ein unbekanntes Binary
wird **nicht** verbucht -- wuerde `git` bepreist, waere der Guard unbenutzbar
und jemand wuerde ihn abschalten -- aber ein erkannter Vendor **durch einen
Wrapper hindurch** wird verbucht.

- Direkte Vendor-Binaries werden ueber den Basename erkannt, inklusive
  `claude-code`: gemessen 2026-07-29 lieferte die Klassifikation vorher fuer
  `npx @anthropic-ai/claude-code ...` nichts, weil der Basename der Paketangabe
  `claude-code` und nicht `claude` ist. Die OpenAI-Angabe ueberlebte nur durch
  Zufall, weil ihr Basename exakt `codex` lautet.
- Wrapper werden mitgescannt, weil `ssh bench agy -p ...` und
  `cmd /c claude -p ...` genau so viel Geld kosten wie der direkte Aufruf. Die
  zweite Wrapper-Reihe (`uv`, `uvx`, `timeout`, `nohup`, `xargs`, `winpty`,
  `setsid` und weitere) wurde 2026-07-29 ergaenzt, nachdem gemessen wurde, dass
  jeder davon einen Vendor am Guard vorbeitrug. Ein Wrapper allein kann nicht
  ueberbuchen: der Scan verlangt weiterhin ein echtes Vendor-Token in den
  Argumenten.
- `_READ_ONLY_VENDOR_PROBES` ist eine exakte Argv-Allowlist, keine
  Praefix-Allowlist: `claude --version` sowie `codex --version` und
  `codex login status` erzeugen nichts und werden nicht verbucht; jede andere
  Variante bleibt bezahlt.

`classify_url` liefert Vendor und Host. Zwei Wege, abrechenbar zu sein: ein
bekannter bezahlter API-Host, oder ein *Inferenz*-Pfad auf einem Host, den
`lane_for_host` nicht als diese Maschine zertifiziert. Der zweite Fall ist der
Remote-Ollama-Fall -- gleicher Providername, gleicher Codepfad, fremde GPU.
Freie Proben wie `/api/tags` und `/api/version` sind ausdruecklich nicht in
der Inferenzpfad-Liste und werden nicht verbucht.

## Trust-Grenzen / Effekte

**Der Writer ist das Ledger, nicht dieses Modul.** Jede Buchung laeuft ueber
`reserve` aus [Kernel-Policy](kernel-policy.md); `budget_process` haelt keinen
eigenen Zustand ausser dem thread-lokalen Rekursionszaehler und dem
Installationsregister.

**Settle statt Release im Fehlerfall.** `guard` besiedelt (`settle`) auch bei
einer Ausnahme. Eine Ausnahme waehrend eines laufenden Vendor-Aufrufs sagt
nichts darueber, ob die Anfrage den Vendor erreicht hat -- ein Timeout nach der
Token-Erzeugung sieht genauso aus wie ein abgelehnter Verbindungsversuch.
Ueberzaehlen kostet hoechstens einen Aufruf, Unterzaehlen ist unbegrenzt.

**Die eine fail-open-Ausnahme.** `_release_never_spawned` gibt eine
Reservierung frei, wenn `FileNotFoundError` aus `CreateProcess` bzw. `execve`
kam: dann existierte nie ein Kindprozess. Gemessen 2026-09-05 wurde ein aus dem
Suchpfad fehlender Sitz mit seinem Worst-Case von 2,00 USD verbucht und schloss
mit einem weiteren die Tagesgrenze fuer Aufrufe, die nie stattfanden. Der Grund
landet im Ledger-Eintrag, damit der freigegebene Aufruf pruefbar bleibt.

**`Popen` wird als Klasse ersetzt, nicht als Funktion.** Gemessen: eine
Funktion an dieser Stelle liess jedes spaetere `import asyncio` scheitern, weil
`asyncio.windows_utils` zur Importzeit von `subprocess.Popen` ableitet. Der
Wrapper ist deshalb eine Unterklasse und behaelt `isinstance`, Ableitbarkeit
und Klassenmethoden. Ist der vorgefundene Wert **keine** Klasse -- etwa ein
`MagicMock` aus einem Test -- wird er unveraendert zurueckgegeben.

**Deinstallation restauriert nur die eigenen Wrapper.**
`uninstall_process_guard` schreibt den gemerkten Originalwert nur zurueck, wenn
im Attribut noch genau dieser Wrapper steht, und meldet die uebrigen Namen als
Liste. Gemessen 2026-08-23: ohne diese Identitaetspruefung schrieb ein
Teardown einen Test-Mock ueber die echte Funktion, und danach lieferte jeder
Prozess-Spawn im Interpreter eine Attrappe; die prozessuebergreifende Probe des
Kill-Switch verweigerte 119-mal die Scharfschaltung aus einem Grund, der nichts
damit zu tun hatte.

**Das Ausgabenregister.** `BILLABLE_SITES` listet jede bekannte abrechenbare
Stelle im Baum mit Datei, Funktion, Vendor, Mechanismus und der Angabe, ob die
Stelle selbst reserviert. Mehrere Zeilen sind mit `static_visible: False`
markiert, weil ein Textscan sie nicht finden kann: der Vendor entsteht erst zur
Laufzeit aus `base_url` oder `host`, oder das Argv wird in
`daedalus/council/vendors.py` gebaut und in `daedalus/spine/cancel.py`
gespawnt. Zwei Zeilen unter `runs/council/summarize.py` fand nicht die
Handauditierung, sondern der Drift-Detektor in `tests/test_budget.py` beim
ersten Lauf -- das ist das Argument dafuer, den Detektor zu behalten.

## Tests

- [`tests/test_budget.py`](../../../tests/test_budget.py) -- Klassifikation, Interposition, Drift-Detektor gegen `BILLABLE_SITES`
- [`tests/runtimes/test_budget_process_hierarchy.py`](../../../tests/runtimes/test_budget_process_hierarchy.py) -- Import-Grenzen dieses Pakets
- [`tests/test_registry_new_doors.py`](../../../tests/test_registry_new_doors.py)
- [`tests/test_budget_is_installed.py`](../../../tests/test_budget_is_installed.py) -- ob der Guard an den Einstiegspunkten tatsaechlich installiert wird
- [`tests/test_spend_coverage.py`](../../../tests/test_spend_coverage.py)
- [`tests/test_uncapped_budget_consumers.py`](../../../tests/test_uncapped_budget_consumers.py)

## Verwandt

- [Kernel-Policy](kernel-policy.md) -- `Ledger`, `Reservation`, `price_call`, die Limit-Achsen
- [Providers](providers.md) -- die Vendor-Aufrufe, die dieses Netz sieht
- [Runtimes](runtimes.md) und [Runtimes Provider](runtimes-provider.md) -- die uebrige Runtime-Schicht
- [Runtimes Admission](runtimes-admission.md) -- die Lease-Seite derselben Welle
- [Spine](spine.md) -- `cancel.ManagedProcess` spawnt die Council-Vendoren, die hier als statisch unsichtbar gefuehrt werden
- [Council](council.md) -- der groesste Block statisch unsichtbarer Ausgabenstellen
- [Tools](../tooling/tools.md) -- `tools/guarded_call.py` ist die Prozess-Variante desselben Vertrags
- [Wiki-Index](../index.md)

## Ungeklaert

- **Ungeklaert:** wo `install_process_guard` in der Produktion tatsaechlich
  aufgerufen wird. Der Docstring nennt "the CLI entry point" und
  `ikarus_os`; die vollstaendige Aufruferliste steht nicht in diesem Paket.
- **Ungeklaert:** ob `BILLABLE_SITES` heute noch vollstaendig ist. Der
  Drift-Detektor lebt in `tests/test_budget.py`, nicht hier, und sein
  Erkennungsbereich (statisch sichtbare Spawns) deckt die als
  `static_visible: False` markierten Faelle definitionsgemaess nicht ab.
- **Ungeklaert:** wie sich der Guard verhaelt, wenn ein Vendor ueber
  `asyncio.create_subprocess_exec` statt ueber `subprocess` gestartet wird --
  dieser Pfad wird nicht ersetzt.
