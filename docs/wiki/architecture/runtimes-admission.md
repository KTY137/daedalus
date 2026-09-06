---
title: Runtimes Admission
type: module
status: living
updated: 2026-09-05
covers: daedalus/runtimes/admission
---
# Runtimes Admission

`daedalus/runtimes/admission` ist der Kompositions-Wurzelpunkt fuer
runtime-gebundene Effekt-Autoritaet. Es ist bewusst das kleinste Paket der
Runtime-Schicht: drei Dateien, 325 Zeilen (gemessen 2026-09-05). Es *praegt*
eine Faehigkeit (`RuntimeBoundEffectAuthorization`) aus checkout-externen
Zutaten und liefert eine neutrale Egress-Beobachtung fuer Offload-Wellen. Es
fuehrt selbst keinen Effekt aus: kein Prozess-Spawn, kein Provider-Aufruf,
keine Registry-Erweiterung. Im Kernel/Ikarus/Ariadne-Bild (Masterplan
Abschnitt 3 und 4, Invariante 1 und 8) sitzt es zwischen dem kanonischen
Kernel, dem die Lease-Autoritaet gehoert (siehe [Kernel](kernel.md)), und den
konkreten Runtimes und Providern, die den Effekt danach ausfuehren.

Der Modul-Docstring von `authorization.py` nennt den Grund, aus dem das Paket
ueberhaupt existiert: gemessen 2026-08-26 konstruierte **keine**
Produktionsdatei eine `RuntimeBoundEffectAuthorization` -- alle
Konstruktionsstellen lagen unter `tests/`. Ohne einen Produktions-Praeger gibt
es keinen Live-Runtime-Start, keine `live-runtime`-Konformanzhuelle und keinen
Weg fuer die Registry-Zeile `provider.claude` aus `INVENTORY_ONLY` heraus.

## Module

| Datei | Zweck | Wichtige Symbole |
| --- | --- | --- |
| [`__init__.py`](../../../daedalus/runtimes/admission/__init__.py) | Produktions-Komposition fuer Runtime-Trust und Effekt-Admission. Reexportiert genau die fuenf Namen aus `authorization`; `offload_egress` wird bewusst **nicht** reexportiert, sondern direkt importiert. | `RUNTIME_AUTHORITY_KEY_ID`, `RUNTIME_LEASE_KEY_ID`, `acquire_runtime_bound_authorization`, `runtime_trust_ledger`, `runtime_trust_ledger_path` |
| [`authorization.py`](../../../daedalus/runtimes/admission/authorization.py) | Praegt fuer genau eine Anfrage die runtime-gebundene Faehigkeit -- oder verweigert. Verwaltet drei getrennte Schluesseldateien im checkout-externen Control-Root und oeffnet das Runtime-Trust-Ledger. | `acquire_runtime_bound_authorization`, `runtime_trust_ledger`, `runtime_trust_ledger_path`, `RUNTIME_LEASE_KEY_ID`, `RUNTIME_AUTHORITY_KEY_ID` |
| [`offload_egress.py`](../../../daedalus/runtimes/admission/offload_egress.py) | Loest die deklarierten Endpunkte der Dispatch-Lanes auf und delegiert die Ollama-Admission an die bestehende Provider-Policy. Liefert eine `EgressAdmissionObservation` an den Kernel-Issuer -- eine Beobachtung, keine Lease-Autoritaet. | `resolve_lane_endpoint`, `admit_offload_egress` |

## Trust-Grenzen / Effekte

**Was hier praegt, und was anderswo verweigert.**
`acquire_runtime_bound_authorization` ist eine Fassade, die fail-closed *durch
Komposition* ist: jede Verweigerung erhebt die Schicht, der die Regel gehoert.

- Eine Registry-Zeile, die nicht `CENTRAL` ist, lehnt `issue_effect_lease` ab
  ("is inventory_only, not central; migration is required first"). Gegen die
  echte Registry verweigert dieser Issuer daher heute fuer **jede**
  Provider-Zeile.
- Fehlende Manifest- und Konformanz-Digests, eine vom Trust-Ledger nicht
  zugelassene, quarantaenisierte oder abgelaufene Huelle sowie eine Lease, die
  ihren Trust-Eintrag ueberlebt, verweigert
  `issue_runtime_bound_effect_lease`.
- Leere `guard_decisions` verweigert die Autorisierung selbst.
- Ein eingelegter oder unlesbarer Kill-Switch verweigert in
  `kill_switch_generation`, bevor irgendeine Signatur entsteht.

Zusaetzlich prueft das Modul selbst genau eine Sache, die sonst erst spaeter
und mit der falschen Fehlermeldung auffiele: stimmt
`request.kill_switch_generation` nicht mit der Live-Generation ueberein, wird
vor beiden Signaturen und vor dem Ledger-Oeffnen mit dem echten Grund
abgelehnt. Die Lebensdauer wird auf 30 bis 3600 Sekunden geklemmt.

**Schluesselverwahrung.** Drei Schluessel, drei Dateien, weil sie drei
verschiedene Fragen beantworten: der Lease-Issuer-Schluessel signiert "diese
Faehigkeit wurde erteilt", der Runtime-Authority-Schluessel signiert "diese
Faehigkeit ist an genau diese verifizierte Runtime gebunden", und der
Integritaetsschluessel authentifiziert die persistierten Admission-Zeilen. Ein
gemeinsamer Schluessel wuerde diese Autoritaeten ineinander kollabieren
lassen. Die Schluessel sind **Dateien** im checkout-externen Control-Root
(`control_root`, siehe [Spine](spine.md)), nie Umgebungsvariablen: ein im
Environment getragenes Geheimnis erbt jeder Kindprozess, und dazu zaehlt der
Worker des Kandidaten. `_load_or_create_key` oeffnet mit `O_EXCL` -- zwei
Prozesse koennen nicht beide glauben, sie haetten die Datei erzeugt -- und mit
`O_BINARY`, weil ein Windows-Text-Mode-Write `0x0A` zu `0x0D 0x0A` uebersetzt
und damit etwa jeden achten Zufallsschluessel unbrauchbar macht.

**Ledger-Ort.** `runtime_trust_ledger_path` legt die Trust-Datenbank unter
`<control_root>/runtime-trust/trust.sqlite3` ab -- checkout-extern aus dem
gleichen Grund wie jedes andere Ledger hier: der Kandidat, den eine
Runtime-Lease autorisiert, kann einen schreibbaren Checkout halten.
`runtime_trust_ledger` ist getrennt exportiert, weil zwei Aufrufer denselben
Store brauchen: der Konformanz-Admissionsschritt schreibt hinein, dieser
Issuer liest daraus. Zwei getrennte Stores saehen beide vollstaendig aus.

**Egress.** `admit_offload_egress` sortiert und dedupliziert die angefragten
Lanes, loest je Lane einen Endpunkt auf und gibt eine
`EgressAdmissionObservation` mit genau einer `GuardDecision` unter dem Namen
`provider.egress_policy` zurueck. Nur die Ollama-Lane hat heute einen echten
Admissionsvertrag (`ollama_endpoint_admission`, siehe
[Providers](providers.md)); DeepSeek wird ausdruecklich nur als Deklaration
geleast, und sowohl eine Lane ohne Endpunkt als auch eine leere Endpunktmenge
setzen die Entscheidung auf nicht erlaubt. Der Ollama-Endpunkt kommt aus der
Umgebungsvariable `OLLAMA_HOST`, sonst aus `DEFAULT_HOST`.

## Tests

- [`tests/kernel/test_runtime_authorization_issuer.py`](../../../tests/kernel/test_runtime_authorization_issuer.py)
- [`tests/kernel/test_runtime_trust_ledger_port_guard.py`](../../../tests/kernel/test_runtime_trust_ledger_port_guard.py)
- [`tests/kernel/test_runtime_trust_port_boundary.py`](../../../tests/kernel/test_runtime_trust_port_boundary.py)
- [`tests/kernel/test_effect_lease_issuer_rule.py`](../../../tests/kernel/test_effect_lease_issuer_rule.py)
- [`tests/kernel/test_lease_authority_subject_split.py`](../../../tests/kernel/test_lease_authority_subject_split.py)
- [`tests/kernel/test_effect_limit_policy.py`](../../../tests/kernel/test_effect_limit_policy.py)
- [`tests/kernel/test_offload_lease_outer_ports.py`](../../../tests/kernel/test_offload_lease_outer_ports.py)
- [`tests/kernel/test_write_evidence_records.py`](../../../tests/kernel/test_write_evidence_records.py)
- [`tests/gates/test_write_evidence_producer.py`](../../../tests/gates/test_write_evidence_producer.py)
- [`tests/gates/test_write_surface_lease_dominance.py`](../../../tests/gates/test_write_surface_lease_dominance.py)
- [`tests/test_loop_lease.py`](../../../tests/test_loop_lease.py) und [`tests/test_loop_lease_policy.py`](../../../tests/test_loop_lease_policy.py)
- [`tests/test_wave_spend_reservation_concurrency.py`](../../../tests/test_wave_spend_reservation_concurrency.py)
- [`tests/contracts/test_import_scc_hierarchy.py`](../../../tests/contracts/test_import_scc_hierarchy.py)

## Verwandt

- [Kernel](kernel.md) -- Besitzer von `EffectLeaseRequest`, `PolicyDecision` und `EffectLeaseLedger`
- [Kernel-Contracts](kernel-contracts.md) -- die Vertragsformen, die hier gebunden werden
- [Spine](spine.md) -- Effect-Registry, Kill-Switch und `control_root`
- [Runtimes](runtimes.md) -- `RuntimeTrustLedger` und der Broker, der die Faehigkeit konsumiert
- [Runtimes Provider](runtimes-provider.md) und [Providers](providers.md) -- die Egress-Gegenseite
- [Kernel-Policy](kernel-policy.md) -- Geld- und Limit-Policy derselben Admission
- [Runtimes Execution](runtimes-execution.md) -- das Prozessnetz, das dieselben Wellen bepreist
- [Tools](../tooling/tools.md) -- `tools/effect_boundary_check.py` misst die Registry, auf die sich dieses Paket stuetzt
- [Wiki-Index](../index.md)

## Ungeklaert

- **Ungeklaert:** ob heute ein Produktionspfad `acquire_runtime_bound_authorization`
  tatsaechlich aufruft. Der Docstring beschreibt die Kette
  (`runtime_effects` -> `broker` -> `claude_cli`) als vollstaendig und wartend;
  ob die zweite Haelfte -- `provider.claude` auf `CENTRAL` -- inzwischen
  erfolgt ist, laesst sich aus diesem Paket allein nicht ablesen.
- **Ungeklaert:** wer `EgressAdmissionObservation` konsumiert und ob eine
  nicht erlaubte Beobachtung dort hart verweigert oder nur protokolliert wird.
  Das entscheidet der Kernel-Issuer in `daedalus/kernel/offload_lease.py`,
  nicht dieses Paket.
- **Ungeklaert:** ob die Endpunkt-Tabelle in `offload_egress.py` (heute nur
  DeepSeek neben Ollama) absichtlich unvollstaendig ist oder ob weitere Lanes
  existieren, die schweigend eine leere Zeichenkette und damit eine
  Verweigerung erhalten.
