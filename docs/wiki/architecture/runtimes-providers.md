---
title: Runtimes — Providers (Roster)
type: module
status: living
updated: 2026-09-05
covers: daedalus/runtimes/providers
---
# Runtimes — Providers (Roster)

`daedalus/runtimes/providers` ist die **Gestalt** eines Modellanbieters, nicht
sein Aufruf: der Katalog, die Vertrauensflags, der abstrakte Vertrag, die
Personas, die Prompt- und Token-Politik, die Spend-Zulassung und die Form des
zurückkommenden Berichts. Das Paket daneben,
[Runtimes — Provider](runtimes-provider.md) (Singular), ist die Ausführung.
Der Paket-Docstring dort zieht die Grenze in einem Satz: *Singular ist der Akt,
Plural ist die Aufstellung.* Ein Buchstabe Unterschied, aber zwei
Verantwortungen.

Im Kernel/Ikarus/Ariadne-Bild sitzt das Paket unter der Laufzeitschicht: es
entscheidet keine Policy, sondern übersetzt Kernel-Policy in
provider-taugliche Form. Alles Effektvolle -- Reservierung, Sensitivität,
Graph-Kontext -- wird als injizierter Port hereingereicht, nie hier
konstruiert. Deshalb heißt der Kommentar im Katalog: konkrete
Provider-Konstruktion ist eine effektvolle Kompatibilitätstür, und der Katalog
nimmt Verfügbarkeit als *Probe* entgegen, statt sie selbst herzustellen.

Gemessen 2026-09-05: 9 Python-Module, 799 Zeilen.

## Module

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [__init__.py](../../../daedalus/runtimes/providers/__init__.py) | Fassade: Katalog und Vertrag. | `PROVIDER_CATALOGUE`, `Provider`, `ProviderCapabilities`, `ProviderMetadata`, `list_providers` |
| [contracts.py](../../../daedalus/runtimes/providers/contracts.py) | Der abstrakte Vertrag jedes Backends: `available()` plus `run(...)`, das immer denselben validierten Bericht liefert. Trägt außerdem die beiden geteilten Hilfen -- die Rollback-Schleife und die Read-only-Durchsetzung. | `ProviderCapabilities`, `Provider` |
| [catalogue.py](../../../daedalus/runtimes/providers/catalogue.py) | Die deterministische Aufstellung: sechs Einträge mit Anzeigename, Lokalität, Vertrauensflag, Schreibrecht, Agentik, Schlüsselbedarf und Implementierungsstand, plus die Projektion auf einen Gesundheitsbericht. | `ProviderMetadata`, `PROVIDER_CATALOGUE`, `AvailableProvider`, `list_providers`, `configured`, `probe_provider`, `provider_health`, `available_from_health` |
| [personas.py](../../../daedalus/runtimes/providers/personas.py) | Der Personenkatalog einer Lane: welcher Schattenname zu welcher Rolle gehört, welche Kultur die Lane hat, wer sonst noch im Pool ist. Liest die gepackte Ressource und prüft sie gegen den Checkout-Spiegel. | `persona_for`, `culture`, `roster`, `LEGACY_PERSONAS_PATH` |
| [token_policy.py](../../../daedalus/runtimes/providers/token_policy.py) | Prompt-Präfix und die harten Formzahlen: Zusammenfassungslänge, Todo-Länge, Pfade pro Anfrage, Standardmodelle. `trim_paths` wendet die erfasste Work-Scope-Politik an. | `STATIC_PROMPT_PREFIX`, `MAX_SUMMARY_CHARS`, `MAX_TODO_CHARS`, `MAX_PATHS_PER_REQUEST`, `DEFAULT_MODEL`, `HIGH_RISK_MODEL`, `CHEAP_MODEL`, `trim_paths`, `trim_text` |
| [execution_policy.py](../../../daedalus/runtimes/providers/execution_policy.py) | Die Formung der Execution-Limit-Policy für Provider: einmal an der Zulassung erfassen, danach nie wieder aus der Umgebung nachladen. | `admit_execution_limit_policy`, `bounded_execution_limit_policy`, `attempt_numbers`, `provider_http_timeout` |
| [context.py](../../../daedalus/runtimes/providers/context.py) | Kontextvorbereitung hinter injizierten Sensitivitäts- und Graph-Ports. Ist die Token-Achse abgeschaltet, wird die Kapazität aus den tatsächlichen Dateigrößen berechnet statt durch eine große Zahl ersetzt. | `read_provider_context`, `render_provider_brief`, `ReadContextPort`, `RenderBriefPort`, `GraphBriefPort` |
| [reporting.py](../../../daedalus/runtimes/providers/reporting.py) | Prompt-Bau, JSON-Extraktion mit genau zwei verlustfreien Rettungen, Vervollständigung fehlender Berichtsschlüssel und die Form eines blockierten Berichts. | `report_instructions`, `build_prompt`, `extract_json`, `coerce_report`, `blocked_report` |
| [budget_admission.py](../../../daedalus/runtimes/providers/budget_admission.py) | Fail-closed Spend-Zulassung: entweder eine Reservierung oder ein gültiger blockierter Bericht -- nie ein stiller Aufruf. | `reserve_or_report`, `budget_refusal_report` |

## Der Katalog und seine Flags

`PROVIDER_CATALOGUE` führt sechs Einträge (gemessen 2026-09-05). Fünf Flags je Eintrag, und jedes
hat eine Konsequenz:

| Flag | Bedeutung laut `ProviderCapabilities` |
| --- | --- |
| `local` | läuft auf dieser Maschine, kein Netz-Egress |
| `trusted_with_ip` | freigegeben, proprietären oder sensiblen Quelltext zu empfangen |
| `can_write` | darf das Repository verändern (Edits anwenden, Werkzeuge laufen lassen) |
| `agentic` | liest das Repository selbst, statt eingebetteten Kontext zu brauchen |
| `requires_key` / `env_keys` | braucht einen Schlüssel; `configured` prüft, ob mindestens einer gesetzt ist |

Dazu `implemented`: `openai_api` und `anthropic_api` stehen im Katalog, sind
aber Platzhalter. `probe_provider` gibt für sie ohne Konstruktionsversuch
`"provider placeholder; implementation pending"` zurück, und
`available_from_health` lässt sie ganz aus der Verfügbarkeitsprojektion fallen.
Der Docstring von `ProviderCapabilities` sagt die wichtigste Eigenschaft
selbst: das sind **strukturelle Garantien der Harness, keine Versprechen, die
das Modell halten muss.**

Die Flags sind nicht nur Beschriftung. `codex_cli` trägt `trusted_with_ip=False`
mit dem Kommentar, dass es nie Inhalte der Denylist bekommt, und
[tests/runtimes/test_trust_flags_agree.py](../../../tests/runtimes/test_trust_flags_agree.py)
existiert, weil dieselbe Frage im Baum zweimal beantwortet wird und beide
Antworten übereinstimmen müssen.

## Trust-Grenzen / Effekte

- **Kein Writer, keine Effekt-Tür.** Kein Modul des Pakets schreibt eine
  Datei, öffnet eine Verbindung oder ruft `begin_effect`. Selbst dort, wo
  Effekte offensichtlich nötig wären, kommen sie als Port herein:
  `read_provider_context` bekommt `read_inlined_context`,
  `render_provider_brief` bekommt `render_brief` und `graph_brief`,
  `probe_provider` bekommt eine Factory. Die tatsächliche
  Sensitivitäts-Policy liegt bei `daedalus.sensitivity`, das Ledger bei
  `daedalus.kernel.policy.ledger`.
- **`_rollback_writes` ist *die* Undo-Schleife.** Sie steht genau einmal, im
  abstrakten `Provider`. Ihr Docstring nennt den Grund: dieselbe Funktion lag
  einst AST-identisch in DeepSeek und Ollama, und das ist der Undo-Pfad jener
  externen Schreib-Lane, die am 2026-07-30 den Inhalt einer Datei in eine
  andere schrieb und drei von fünf Modulen zerstörte, während sie Erfolg
  meldete. Zwei Kopien wären zwei Stellen, an denen genau das schiefgehen
  kann, was funktionieren muss, wenn schon alles andere schiefging.
  `tests/test_provider_rollback_single_source.py` hält die Kopie fern. Der
  Mechanismus ist tragend über Ordnung hinaus: `offload` verweigert einem
  Provider ohne aufrufbares `rollback()` überhaupt das Schreibrecht -- wer es
  verliert, wird still auf beratend heruntergestuft.
- **`_enforce_read_only` verschiebt statt zu verwerfen.** Ein Provider ohne
  `can_write` kann weder Dateien ändern noch Tests laufen lassen; sein
  Vorschlag wandert nach `handoff.suggested_files`, `files_changed` und
  `tests_run` werden geleert, und ein `status: done` wird zu `needs_review`
  heruntergestuft -- wer nicht schreiben kann, kann eine Änderung nicht
  legitim "fertig" nennen.
- **Spend ist fail-closed.** `reserve_or_report` gibt entweder eine
  `Reservation` oder ein vollständiges, gültiges Bericht-Envelope zurück; es
  gibt keinen dritten Ausgang, in dem der Aufruf trotzdem stattfindet. Der
  blockierte Bericht nennt die gemessenen Zahlen und drei konkrete Auswege.
- **Die Limit-Policy wird einmal erfasst.** `admit_execution_limit_policy`
  liest die Umgebung nur an der direkten Zulassung eines Providers; jede
  interne Hilfe geht über `bounded_execution_limit_policy` und fällt damit auf
  begrenztes Verhalten zurück. Der Docstring nennt den Grund: sonst könnte ein
  Aufruf mitten in der Anfrage veränderte Prozesskonfiguration einfangen. Das
  ist die Modulseite von Plan §4.1.
- **Abgeschaltete Achsen sind nie eine große Zahl.** `attempt_numbers` gibt
  bei abgeschalteter Attempt-Achse einen offenen `itertools.count`-Iterator
  zurück statt eines endlichen Ersatzwerts; `provider_http_timeout` gibt
  `None` zurück statt einer Frist, die keine ist. Genauso in `context.py`: ist
  die Token-Achse aus, wird die Kapazität aus den echten Dateilängen
  aufaddiert beziehungsweise so lange verdoppelt, bis der Graph-Brief nicht
  mehr abgeschnitten ist.
- **Personas sind Konfiguration mit Driftprüfung.** `read_builtin_text` liest
  die gepackte Ressource und vergleicht sie mit
  [daedalus/providers/personas.json](../../../daedalus/providers/personas.json);
  weichen beide voneinander ab, verweigert es, statt still eine zweite
  Konfigurationswahrheit zu wählen.

## Zwei Docstring-Korrekturen im Code selbst

Beide stehen als Warnung in `contracts.py` und sind wörtlich lesbar:

- `_enforce_read_only` sagte über seine ganze Lebensdauer `handoff.suggestions`,
  sieben Zeilen über der Zuweisung, die `suggested_files` schreibt. Ein Leser,
  der dem Docstring folgte, suchte einen Schlüssel, den es nie gab.
- Die Rollback-Duplikation wurde nicht nur entfernt, sondern mit einem Test
  gegen ihre Rückkehr abgesichert.

Beides ist ein nützlicher Maßstab für den Rest des Wikis: der Code hier
korrigiert seine eigene Dokumentation ausdrücklich, statt sie zu überschreiben.

## Fassaden nach außen

`daedalus/providers/` ist heute überwiegend Kompatibilitätsfassade auf dieses
Paket: [base.py](../../../daedalus/providers/base.py) re-exportiert `Provider`
und `ProviderCapabilities`, [_report.py](../../../daedalus/providers/_report.py)
bündelt Reporting, Budget-Zulassung, Kontext und Limit-Politik zu einer
Kontextfassade, [personas.py](../../../daedalus/providers/personas.py) zeigt
auf den Katalog hier. Die konkreten Implementierungen
([claude_cli.py](../../../daedalus/providers/claude_cli.py),
[codex_cli.py](../../../daedalus/providers/codex_cli.py),
[deepseek.py](../../../daedalus/providers/deepseek.py),
[ollama.py](../../../daedalus/providers/ollama.py)) erfüllen den Vertrag aus
`contracts.py`. Weitere Konsumenten sind
[provider_router.py](../../../daedalus/provider_router.py),
[claude_bridge.py](../../../daedalus/claude_bridge.py) sowie
[kairos/orchestrate.py](../../../daedalus/kairos/orchestrate.py) und
[kairos/scheduler.py](../../../daedalus/kairos/scheduler.py).

## Tests

Gemessen 2026-09-05 nennen 14 Dateien unter `tests/` dieses Paket. Die direkt
zuständigen:

- [tests/runtimes/test_provider_catalogue_hierarchy.py](../../../tests/runtimes/test_provider_catalogue_hierarchy.py)
  -- Katalog und Gesundheitsprojektion, inklusive der Frage, was die
  Legacy-Fassade noch selbst tun darf.
- [tests/runtimes/test_provider_contracts_hierarchy.py](../../../tests/runtimes/test_provider_contracts_hierarchy.py)
  -- der Vertrag gegen alle vier realen Implementierungen, gekoppelt an den
  Digest der Effekt-Registry.
- [tests/runtimes/test_provider_helper_hierarchy.py](../../../tests/runtimes/test_provider_helper_hierarchy.py)
  -- Reporting, Budget-Zulassung, Token- und Execution-Policy.
- [tests/runtimes/test_provider_persona_resource.py](../../../tests/runtimes/test_provider_persona_resource.py)
  -- Quell-/Wheel-Parität des Personenkatalogs.
- [tests/runtimes/test_trust_flags_agree.py](../../../tests/runtimes/test_trust_flags_agree.py)
  -- die beiden Registraturen müssen sich einig sein, wer Quelltext sehen darf.
- [tests/runtimes/test_claude_provider_strangler_architecture.py](../../../tests/runtimes/test_claude_provider_strangler_architecture.py)
  -- die Richtung der Ablösung von der Legacy-Fassade hierher.
- [tests/test_execution_limit_consumers.py](../../../tests/test_execution_limit_consumers.py)
  -- dass abgeschaltete Achsen nirgends als Zahl auftauchen.
- [tests/test_hardening.py](../../../tests/test_hardening.py) und
  [tests/test_agent_env.py](../../../tests/test_agent_env.py) -- Berichtform
  und Umgebungsvertrag.
- [tests/contracts/test_no_dangling_daedalus_imports.py](../../../tests/contracts/test_no_dangling_daedalus_imports.py),
  [tests/test_registry_retired_rows.py](../../../tests/test_registry_retired_rows.py)
  -- dass die Fassaden nicht ins Leere zeigen.

## Verwandt

- [Runtimes](runtimes.md) und [Runtimes — Provider](runtimes-provider.md) --
  die Laufzeitschicht und der Ausführungsteil.
- [Providers](providers.md) -- die konkreten Backends hinter dem Vertrag.
- [Runtimes — Contracts](runtimes-contracts.md) -- `validate_report` und
  `REPORT_KEYS`, gegen die `coerce_report` prüft.
- [Runtimes — Admission](runtimes-admission.md) und
  [Runtimes — Execution](runtimes-execution.md) -- Zulassung und begrenzte
  Ausführung.
- [Kernel-Policy](kernel-policy.md) -- Ledger, Preise und
  `ExecutionLimitPolicy`.
- [Lanes](lanes.md) -- `render_brief` und `graph_brief`, die als Ports
  hereinkommen.
- [Spine](spine.md) -- Effekt-Registry und Kill-Switch.
- [Council](council.md) -- der andere große Konsument mehrerer Vendoren.
- [Agents hold no state](../decisions/agents-hold-no-state.md),
  [Tool-Vetting](../tool-vetting.md), [Wiki-Index](../index.md).

## Ungeklärt

- `MAX_TODO_CHARS` wird in `token_policy.py` exportiert; ob es innerhalb
  dieses Pakets noch einen Aufrufer hat, konnte ich nicht feststellen --
  `blocked_report` kürzt nur die Zusammenfassung, nicht das Todo.
- Der Katalog nennt `deepseek` mit `can_write=True` und `agentic=False`. Wie
  sich das mit `_enforce_read_only` verträgt, hängt an der konkreten
  Implementierung und ist aus diesem Paket allein nicht ablesbar.
- `catalogue.py` definiert `AvailabilityProbe` und `ProviderFactory` als
  Typen, konstruiert aber selbst keine. Welcher Aufrufer die effektvolle
  Konstruktionstür stellt, ist von hier aus nicht ablesbar.
