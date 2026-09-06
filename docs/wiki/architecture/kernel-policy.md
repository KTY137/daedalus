---
title: Kernel Policy
type: module
status: living
updated: 2026-09-05
covers: daedalus/kernel/policy
---
# Kernel Policy

`daedalus/kernel/policy` haelt die kernel-eigenen Policy-Vertraege: die
owner-kontrollierte Ausfuehrungs-Limit-Policy, die Vorab-Bepreisung eines
deklarierten Vendor-Aufrufs, das persistente Geld-Ledger mit Reservierungen und
Spend-Envelopes, sowie die Policy fuer den kanonischen Computer-Use-Effekt.
Fuenf Dateien, 2366 Zeilen (gemessen 2026-09-05), davon 1470 im Ledger. Im
Kernel/Ikarus/Ariadne-Bild ist das der Trust-Kernel (Masterplan Abschnitt 4,
Invariante 8 und Abschnitt 4.1): hier entsteht die Antwort auf "darf diese
Arbeit ueberhaupt zugelassen werden", bevor irgendeine Runtime einen Effekt
ausfuehrt.

Wichtig fuer das Gesamtbild: dieses Paket ist **Policy, kein Effekt**.
`pricing` persistiert nichts, reserviert nichts, installiert keinen
Prozess-Interposer und ruft keinen Provider. Das Netz, das Ausgaben ueberhaupt
erst sichtbar macht, liegt in [Runtimes Execution](runtimes-execution.md);
`daedalus/budget.py` bleibt die historische Kompatibilitaets- und Effektfassade
und reexportiert genau diese Objekte.

## Module

| Datei | Zweck | Wichtige Symbole |
| --- | --- | --- |
| [`__init__.py`](../../../daedalus/kernel/policy/__init__.py) | Lazy Reexport-Fassade. `_EXPORT_GROUPS` haelt die Exportreihenfolge von vor der Aufspaltung als Vertrag fest; `__getattr__` laedt genau den Besitzer, dessen Name angefragt wurde. Das Anfordern eines Limit-Namens zog vorher Ledger und Preistabellen in jeden Prozess, der Policy anfasste. | `__getattr__`, `__dir__` |
| [`limits.py`](../../../daedalus/kernel/policy/limits.py) | Die owner-kontrollierte Ausfuehrungs-Limit-Policy. Beantwortet genau eine enge Frage: welche Daedalus-eigenen *Ressourcen*-Deckel gelten fuer neu zugelassene Arbeit. | `ExecutionLimitPolicy`, `LimitAxes`, `LimitPolicyError`, `LimitMode`, `LIMIT_AXES`, `LIMIT_MODES`, `MODE_BOUNDED`, `MODE_CUSTOM`, `MODE_UNBOUNDED_EXECUTION`, `ENV_EXECUTION_LIMIT_POLICY`, `load_from_env`, `store_in_env` |
| [`pricing.py`](../../../daedalus/kernel/policy/pricing.py) | Obergrenzen-Bepreisung vor dem Aufruf. Liefert nur fuer nachweislich freien Transport null. | `VendorPrice`, `Estimate`, `price_call`, `subscription_vendors`, `BudgetError`, `UnknownPrice`, `UNKNOWN_CALL_USD`, `FREE_VENDORS`, `ENV_MAX_CALLS`, `ENV_ON_UNKNOWN`, `ENV_SUBSCRIPTIONS` |
| [`ledger.py`](../../../daedalus/kernel/policy/ledger.py) | Der persistente Periodenzustand, sein prozessuebergreifendes Lock, Reservierungen und Spend-Envelopes. Groesste Datei des Pakets. | `Ledger`, `BudgetState`, `Reservation`, `SpendEnvelope`, `BudgetRefused`, `BudgetUnavailable`, `ledger`, `reserve`, `open_envelope`, `reset_default_ledger`, `DEFAULT_CEILING_USD`, `DEFAULT_MAX_CALLS`, `DEFAULT_ENVELOPE_TTL_S`, `DEFAULT_LEDGER_PATH`, `PERIODS` |
| [`computer.py`](../../../daedalus/kernel/policy/computer.py) | Owner-gescopte Policy fuer den Computer-Use-Effekt: Werkzeugliste, Workspace-Wurzel, erlaubte Origins und Anwendungen, plus die Release-Sperre der Version 0.1.6. | `ComputerPolicy`, `ComputerRefused`, `admit_operation`, `load_policy`, `policy_path`, `origin`, `enforce_release_tool_fence`, `refuse_workspace_path_io`, `FILE_TOOLS`, `VISION_TOOLS`, `DESKTOP_TOOLS`, `BROWSER_TOOLS`, `ALL_COMPUTER_TOOLS`, `RELEASE_REPLACE_FENCED` |

## Die acht Limit-Achsen

`LIMIT_AXES` nennt genau acht Achsen: `period_usd`, `billable_calls`,
`mission_spend`, `tokens`, `wall_time`, `attempts`, `concurrency`,
`work_scope`. Drei Modi sind erlaubt: `bounded` (Voreinstellung), `custom` und
`unbounded_execution`. Zwei Eigenschaften sind Absicht und stehen im
Masterplan Abschnitt 4.1:

1. Die gespeicherte Darstellung behaelt die Wahl des Owners je Achse in
   **jedem** Modus. `bounded` und `unbounded_execution` leiten ihre wirksamen
   Werte ab, ohne die Konfiguration zu ueberschreiben -- ein Wechsel zurueck
   nach `custom` stellt sie wieder her.
2. Ein abgeschalteter Deckel wird durch ein explizites `False` in der
   Durchsetzungs-Flagge dargestellt, nie durch einen numerischen Platzhalter.
   In `BudgetState` sind die wirksamen Werte entsprechend `None` statt
   `Infinity` oder Null.

`_require_exact_dict` verweigert sowohl fehlende als auch unbekannte
Schluessel: eine Policy mit einer neuen, unbekannten Achse wird nicht
stillschweigend als "alles erlaubt" gelesen. `fingerprint_sha256` liefert den
kanonischen Abdruck, den Reservierungen und Zustaende als Evidenz mitfuehren.

Nicht Achse und damit nicht abschaltbar: Kill-Switch, Egress-Admission,
Schreibwurzeln, Secret- und Werkzeug-Policy, Authentifizierung,
Evaluator-Isolation, Provenienz, Evidence-Gates und das Verbot automatischer
Promotion.

## Bepreisung

`price_call` liefert eine `Estimate` mit Vendor, Modell, Betrag, Anzahl, Basis
und Detail. Regeln, die man beim Lesen des Codes nicht raten soll:

- Ein *unbekannter* Preis ist nicht frei. `UNKNOWN_CALL_USD` liegt bei 5,00 USD
  und uebersteigt damit bewusst den teuersten hier gemessenen Einzelaufruf.
  `ENV_ON_UNKNOWN` schaltet zwischen `worst_case` und `refuse` um; alles andere
  faellt auf `worst_case` zurueck.
- CLI-Sitzungen sind mit gemessenen bzw. angenommenen Obergrenzen gefuehrt
  (Anthropic-CLI 3,00 USD, OpenAI-CLI und Google 2,00 USD je Aufruf), nicht mit
  Live-Preisen.
- Der Host schlaegt das Vendor-Etikett: ist der Host Loopback, ist der Aufruf
  `free_local`. Das ist Bepreisung **nach** dem kanonischen Egress-Klassifizierer,
  keine zweite Host-Trust-Autoritaet.
- `subscription_vendors` liest `ENV_SUBSCRIPTIONS` und akzeptiert nur Namen,
  die in der Preistabelle stehen -- der Owner kann keinen unbekannten Vendor
  zum Pauschaltarif erklaeren.

## Ledger, Reservierung, Envelope

Der Standardpfad ist `runs/budget/ledger.json`, ueberschreibbar mit
`ENV_LEDGER`. Die Voreinstellung ist eine Tagesperiode mit 5,00 USD und 40
abrechenbaren Aufrufen; die zweite Achse existiert, weil der Preis das
Unsicherste und die Aufrufzahl das Sicherste ist, was gemessen werden kann.

- `Reservation` ist Geld, das dem Ledger bereits zugesagt ist fuer einen
  Aufruf, der **noch nicht stattgefunden hat**. Sie zu halten ist das, was den
  Aufruf legal macht. `settle(None)` bucht die Schaetzung -- ein unbekannter
  Ist-Wert ist kein freier Ist-Wert.
- `release(reason)` ist der einzige fail-open-Hebel des Moduls und verlangt
  einen Grund, der im Ledger-Eintrag landet. Legal nur, wenn beweisbar keine
  Vendor-Bytes geflossen sind.
- `SpendEnvelope` ist eine **zweite, engere** Decke fuer die Dauer eines
  geleasten Scopes. Vorher verglich die Effekt-Schicht nur zwei *Behauptungen*
  miteinander (Deklaration der Ausfuehrung gegen Deklaration der Lease); die
  einzige echte Decke war die Periodendecke, die mit dem vom Operator
  getippten Wert nichts zu tun hat. Ein nicht geschlossener Envelope laeuft
  nach `DEFAULT_ENVELOPE_TTL_S` (sechs Stunden) ab. Der Ablauf gibt **nur den
  ungenutzten Halt** frei: bereits verbuchte Ausgaben bleiben verbucht, und ein
  Abruf, der einem abgelaufenen Envelope zugerechnet wird, wird verweigert.
- `ENV_ENVELOPE` traegt die aktiven Envelope-Ids in die Umgebung und damit in
  jeden Kindprozess. Geschrieben wird sie von `SpendEnvelope.__enter__`, nie
  von Hand.

`BudgetState.as_dict` veroeffentlicht sowohl die konfigurierten als auch die
wirksamen Deckel plus den Policy-Abdruck, damit eine Quittung die geleaste
Decke neben der realisierten Ausgabe nennen kann, ohne die Ledger-Datei erneut
zu lesen.

## Computer-Policy und die v0.1.6-Sperre

`ComputerPolicy` ist eine eingefrorene Datenklasse mit Workspace-Wurzel,
Werkzeugliste, erlaubten Origins, owner-fixierten Anwendungen, Planer-Provider
und Groessen-/Zeitgrenzen. Die Konfiguration liegt **ausserhalb** von
Kandidaten-Workspaces, unter `<control_root>/computer-policy.json`. Das ist
ausdruecklich eine Policy fuer einen vertrauenswuerdigen Host-Adapter und
**keine** Containment beliebigen Python- oder Kindprozess-Codes.

Was `__post_init__` und `path` fail-closed ablehnen: relative Workspaces, Links
und Reparse-Punkte irgendwo in der Ahnenkette, unbekannte oder doppelte
Werkzeuge, Pfade mit `..`, Doppelpunkt, fuehrendem Trennzeichen oder
nachlaufenden Punkten und Leerzeichen, Windows-Geraetenamen, hartverlinkte
Dateien, sowie die geschuetzten Namen (`.git`, `.agentenv`, `.codex`,
`AGENTS.md`, die Policy-Datei selbst, der Masterplan und seine
Amendment-Kette). `load_policy` verlangt zusaetzlich, dass Workspace und
Kernel-Control-State disjunkt sind und dass der Workspace nicht in der
Daedalus-Installation liegt.

`enforce_release_tool_fence` ist die ausdrueckliche Release-Sperre der Version
0.1.6 und ausdruecklich **keine** Behauptung, Pfadnamen-Pruefungen seien
rennfrei geworden. Gesperrt bleiben `vision.match` und `vision.changes` (sie
oeffnen einen Workspace-Pfadnamen) sowie das Ersetzen einer bestehenden Datei
(`file.write` mit `expected_sha256`), solange
`RELEASE_REPLACE_FENCED` gesetzt ist -- das Zwei-Rename-Protokoll des Adapters
hat noch keine dienst-eigene Absturz-Rekonsiliation. `vision.inspect` und
`vision.ocr` sind auf genau die Argumentform `{"observation_id": ...}`
gebunden: die blosse Abwesenheit eines `path`-Schluessels wuerde sonst
leere oder pfad-aliasierte Operationen eine kanonische Lease erhalten lassen.
Die fuenf Datei-Werkzeuge sind wieder zugelassen, seit die handle-verankerte
Umsetzung in `daedalus/runtimes/computer_files.py` die pfadnamen-basierten
Helfer ersetzt hat.

## Trust-Grenzen / Effekte

- **Writer:** `Ledger._store` ist der einzige Schreiber des Ledger-Zustands;
  jede Mutation laeuft unter `_BudgetLock` (Standard-Timeout 30 Sekunden,
  maximal 500 Eintraege).
- **Kein `begin_effect` hier.** Dieses Paket entscheidet, es fuehrt nicht aus.
  Der registrierte Effekt-Eintritt liegt an den Runtime-Tueren; siehe
  [Spine](spine.md) und [Runtimes Admission](runtimes-admission.md).
- **Read-only:** `pricing` vollstaendig, `limits` vollstaendig (bis auf
  `store_in_env`, das nur die Prozessumgebung setzt),
  `Ledger.state_readonly`, `ComputerPolicy.admit` und `load_policy`.
- `admit_operation` verlangt, dass die Operation exakt die Schluessel `tool`,
  `arguments` und `policy_sha256` traegt und dass der Abdruck der **aktuell
  geladenen** Policy entspricht. Eine Operation gegen eine veraltete Policy
  wird abgelehnt, nicht angepasst.

## Tests

- [`tests/kernel/test_budget_ledger_hierarchy.py`](../../../tests/kernel/test_budget_ledger_hierarchy.py) und [`tests/kernel/test_budget_pricing_hierarchy.py`](../../../tests/kernel/test_budget_pricing_hierarchy.py)
- [`tests/kernel/test_computer_policy.py`](../../../tests/kernel/test_computer_policy.py)
- [`tests/kernel/test_kernel_lazy_facade.py`](../../../tests/kernel/test_kernel_lazy_facade.py) und [`tests/test_registry_facade_order.py`](../../../tests/test_registry_facade_order.py)
- [`tests/kernel/test_contract_hierarchy.py`](../../../tests/kernel/test_contract_hierarchy.py)
- [`tests/test_budget.py`](../../../tests/test_budget.py), [`tests/test_uncapped_budget_consumers.py`](../../../tests/test_uncapped_budget_consumers.py)
- [`tests/interfaces/test_computer_configuration.py`](../../../tests/interfaces/test_computer_configuration.py) und [`tests/interfaces/test_desktop_configuration_owner.py`](../../../tests/interfaces/test_desktop_configuration_owner.py)
- [`tests/runtimes/test_computer_service.py`](../../../tests/runtimes/test_computer_service.py), [`tests/runtimes/test_computer_files.py`](../../../tests/runtimes/test_computer_files.py), [`tests/runtimes/test_computer_vision_paths.py`](../../../tests/runtimes/test_computer_vision_paths.py), [`tests/runtimes/test_computer_browser.py`](../../../tests/runtimes/test_computer_browser.py), [`tests/runtimes/test_computer_desktop.py`](../../../tests/runtimes/test_computer_desktop.py)
- [`tests/test_ikarus_computer_schedule.py`](../../../tests/test_ikarus_computer_schedule.py) und [`tests/test_ikarus_autonomy_review.py`](../../../tests/test_ikarus_autonomy_review.py)

## Verwandt

- [Kernel](kernel.md) und [Kernel-Contracts](kernel-contracts.md) -- der uebrige Kernel
- [Runtimes Execution](runtimes-execution.md) -- das Prozessnetz, das `reserve` fuettert
- [Runtimes Admission](runtimes-admission.md) -- Lease-Seite derselben Zulassung
- [Providers](providers.md) -- Konsumenten von `ExecutionLimitPolicy` und `Estimate`
- [Runtimes](runtimes.md) -- der Computer-Use-Adapter hinter `ComputerPolicy`
- [Spine](spine.md) -- `control_root`, Effect-Registry, Kill-Switch
- [Gates](gates.md) -- Gate-Berichte lesen den Policy-Abdruck als Evidenz
- [Tools](../tooling/tools.md) -- `tools/operability_drill.py` trippt die Ausgaben-Kontrolle absichtlich
- [Wiki-Index](../index.md)

## Ungeklaert

- **Ungeklaert:** ob alle acht Achsen aus `LIMIT_AXES` heute auch wirklich
  durchgesetzt werden. Im Ledger sind `period_usd`, `billable_calls` und
  `mission_spend` sichtbar verdrahtet; `tokens`, `wall_time`, `attempts`,
  `concurrency` und `work_scope` werden von anderen Modulen gelesen, deren
  Vollstaendigkeit hier nicht ablesbar ist.
- **Ungeklaert:** wie die vier Rekonsiliationsfaelle des Zwei-Rename-Protokolls
  aussehen sollen. `FILE_REPLACE_RELEASE_REFUSAL` verweist auf ein noch offenes
  Work Packet.
- **Ungeklaert:** ob `daedalus/budget.py` ausser Reexport noch eigene Logik
  traegt. Diese Seite deckt nur `daedalus/kernel/policy` ab.
