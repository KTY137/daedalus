# Work Packet G1-IKARUS-08 — Hermes kernel runtime adapter

**Status:** IMPLEMENTIERT / FIXTURE-VERIFIZIERT; Remote-Admission und Live-Upstream-
Nachweis ausstehend. **Klassifikation:** `ALIGNED`.  
**Gate:** 1. **Base revision:** `61832c9b2e13cad4be399af00c78ccdc49ef7648`.  
**Arbeitslinie:** `g1/ikarus-runtime-invocation-binding-07d3`.  
**Abhängigkeiten:** G1-IKARUS-02 bis -07D4, insbesondere die vendor-neutrale
Runtime-Bindung, der policy-gebundene Toolscope, die kanonische Effect-Bridge und
der callbackfreie versiegelte Provider-Broker.

## Eine Behauptung

Ein exakt gepinnter Hermes-Agent-Loop kann als austauschbarer Ikarus-Userspace-
Worker laufen, ohne Mission, Attempt, Policy, Memory, Toolscope, Effekt,
Receipt, Artifact oder Promotion von Daedalus zu übernehmen.

Hermes erhält ausschließlich explizite Prompts, explizite Kontextfragmente, eine
read-only Memory-Projektion und Daedalus-definierte Toolbeschreibungen. Jeder
verschachtelte Toolaufruf kehrt über einen authentifizierten, budgetierten,
caller-eigenen Loopback-Gateway zur Daedalus-Grenze zurück.

Dieses Paket behauptet **keine** produktive Live-Hermes-Freigabe. Es liefert den
vollständigen Adapter- und Test-Schnitt und lässt die produktiven Evidence-Bits
standardmäßig geschlossen.

## Architektur

```text
MissionSupervisor / TaskAttempt
        |
RuntimeRoleRegistry + RuntimeInvocation binding
        |
sealed ProviderRuntimeOperation (07D4)
        |
HermesKernelProvider
        |
HermesRuntimeAdapter
        |
pinned isolated Hermes worker
        |
authenticated caller-owned tool gateway
        |
Daedalus tool/capability/effect boundary
        |
observation + invocation + receipt digests
```

`MissionSupervisor` und `TaskAttempt` werden nicht ersetzt. Der Hermes-Adapter
ist ein Runtime-Worker hinter dem bestehenden Harness.

## Scope

### Neu

- `daedalus/integrations/__init__.py`
- `daedalus/integrations/hermes/__init__.py`
- `daedalus/integrations/hermes/configuration.py`
- `daedalus/integrations/hermes/context_provider.py`
- `daedalus/integrations/hermes/memory_provider.py`
- `daedalus/integrations/hermes/protocol.py`
- `daedalus/integrations/hermes/event_adapter.py`
- `daedalus/integrations/hermes/tool_provider.py`
- `daedalus/integrations/hermes/tool_gateway.py`
- `daedalus/integrations/hermes/worker.py`
- `daedalus/integrations/hermes/runtime_adapter.py`
- `daedalus/integrations/hermes/kernel_provider.py`
- `daedalus/integrations/hermes/session.py`
- `daedalus/integrations/hermes/conformance.py`
- `daedalus/providers/hermes_agent.py`
- `tests/integrations/test_hermes_runtime_adapter.py`
- `tests/integrations/test_hermes_tool_gateway.py`
- `tests/integrations/test_hermes_kernel_provider.py`
- `tests/integrations/test_hermes_conformance.py`
- `docs/adrs/023-hermes-agent-kernel-adapter.md`
- `docs/research/hermes-agent-kernel-adapter-v1-provenance.json`
- `.github/workflows/g1-ikarus-hermes-runtime-admission.yml`
- dieses Dokument

### Ausdrücklich nicht verändert

- `MissionSupervisor`-Kontrollfluss;
- `TaskAttempt`-Lebenszyklus;
- Daedalus-Kernel-, Spine-, Gate-, Promotion- und Artifact-Autorität;
- Claude-/Codex-Providersemantik;
- bestehende Runtime-Rollen und Fixture-Kompatibilität;
- Upstream-Hermes-Quellcode.

## Exakter Upstream

```text
repository        NousResearch/hermes-agent
release           v0.20.5
tag               v2026.8.19
commit            fcbd1076a93841fa88855acce810e342a5b78101
tree              cc9f987a403a1d02b8b17cc527a57b54402e864b
run_agent.py sha   b8e0244cfdbdce9328040d92adb9b89d78351000ee88bafae35d71b3e33fb8a1
LICENSE sha        821556e6336796450ab852d375117b48a4887e71d255794fd6318d99982a5ab6
archive sha        b7a86a237c11b4b5b439c6b803cc9837f1eab4861c3470a0b7f00651e18a5654
license            MIT
```

Vor jedem Lauf werden Commit, Tree, beide Dateien und ein sauberer Checkout
geprüft. Der Worker prüft `run_agent.py` unmittelbar vor dem Import erneut.

## Kanonische Grenzen

### Versiegelter Provider

`register_hermes_runtime_operation()` registriert genau eine feste
`ProviderRuntimeOperation`. `invoke` und `output_digests` sind modulweite,
closurefreie Funktionen. Callbacks und `tool_invoker` werden am öffentlichen
Facade ausdrücklich verweigert.

### Tool-Gateway

Der Tool-Invoker bleibt beim Caller. Der versiegelte Provider erhält nur einen
Descriptor mit:

- Loopback-Adresse;
- zufälligem Bearer in einer exklusiven Token-Datei;
- Request-/Task-ID;
- Toolscope-Digest;
- Ablaufzeit;
- maximaler Aufrufzahl.

Unbekannte Tools, ungültige Argumente, Budgetüberschreitung und Kernel-Fehler
werden als benannte, digest-gebundene Refusals zurückgegeben.

### Prozess und Umgebung

- Checkout, Workspace und ephemeres Runtime-Root müssen disjunkt sein.
- `HOME`, `USERPROFILE`, `HERMES_HOME` und Temp-Verzeichnisse sind ephemer.
- Die Umgebung entsteht ausschließlich aus Ordinary- und Secret-Allowlist.
- Memory, Learning, Gateway, Cron und Checkpoints werden deaktiviert.
- Iterationen, Laufzeit, Toolaufrufe und Ausgabe sind begrenzt.
- Timeout und Cancellation terminieren die Prozessgruppe.
- Ein äußerer Sandbox-Befehl ist für Produktion verpflichtend.
- Der uncontained-Modus ist ausschließlich als Testprofil markiert.

### Zustand

Context und Memory sind caller-authentifizierte Daten. Der Memory-Provider ist
read-only; `remember()` verweigert. Upstream-Sessions, Datenbanken, Learning und
Hintergrundarbeit werden nicht zu Ikarus-State.

### Protokoll

Parent und Worker sprechen ein strikt begrenztes JSONL-Protokoll mit exakten
Feldern, fortlaufender Sequenz, Tool-Call-Korrelation und terminaler
Vollständigkeit. Upstream-stdout wird nach stderr umgeleitet. stderr bleibt eine
begrenzte Beobachtung und wird nur als Digest in das Resultat aufgenommen.

## Akzeptanzmatrix

| # | Behauptung | rot wenn |
| --- | --- | --- |
| 1 | falscher Commit, Tree, `run_agent.py`, LICENSE oder dirty Checkout verweigert vor Lauf | ein ähnlicher oder modifizierter Checkout startet |
| 2 | Worker besitzt kein kanonisches Memory, Learning, Gateway, Cron oder Checkpointing | Upstream-State überlebt den Attempt |
| 3 | Environment und Secrets sind explizit allowlisted | ein nicht deklarierter Wert wird im Worker sichtbar |
| 4 | Toolname und Argumente werden gegen immutable Daedalus-Schemas geprüft | Hermes kann einen undeclared Effekt anfordern |
| 5 | jeder Toolaufruf trägt Observation-, Receipt- und Invocation-Digest | ein Effekt ist nur durch Hermes-Text belegt |
| 6 | 07D4-Operation ist fest und closurefrei | ein Caller injiziert ausführbaren Provider-Code |
| 7 | Gateway ist task-, scope-, zeit- und budgetgebunden | ein anderer Worker oder Scope kann ihn wiederverwenden |
| 8 | Timeout und Cancellation beenden die Prozessgruppe | ein Worker läuft nach Attempt-Ende weiter |
| 9 | Protokolldrift und Identitätsdrift failen geschlossen | malformed stdout wird als Erfolg behandelt |
| 10 | bestehende Ikarus-/Claude-/Codex-/Broker-Verträge bleiben grün | Hermes erfordert einen zweiten Kontrollpfad |
| 11 | Import der Integration startet nichts | Package-Import öffnet Prozess, Socket oder Modellverbindung |
| 12 | Produktionsfreigabe bleibt evidence-driven geschlossen | Fixture-Parität wird als Live-Produktionsreife bezeichnet |

## Lokale Evidenz vor Remote-Upload

Die fokussierte Adapter-Suite wurde gegen den vollständigen 07D4-Repository-
Stand ausgeführt:

```text
python -m pytest -q -p no:cacheprovider tests/integrations
16 passed
```

Sie umfasst:

- Worker-/Gateway-/Tool-Roundtrip;
- unbekannten Tool-Refusal;
- Timeout und Cancellation;
- Checkout-Drift;
- Environment-Allowlist;
- Request-/Result-Digestbindung;
- Gateway-Authentifizierung, Cleanup und Call-Budget;
- echte `ProviderExecutableObjectRegistry`-Registrierung;
- Callback-Bypass-Verweigerung;
- Forbidden-Import-Scan;
- standardmäßig geschlossene Production-Admission.

Zusätzlich liefen die berührten Ikarus-, Claude-, Codex-, Broker-, Runtime-
Authorization-, Provider-Registry-, Conformance- und Adapter-Suiten lokal grün.
Die reproduzierbaren Plattform-/Python-Matrix-Ergebnisse werden durch
`g1-ikarus-hermes-runtime-admission.yml` erzeugt und nach dem Remote-Lauf in
diesem Packet nachgetragen.

## Ausdrücklich verschobene Produktionsarbeit

1. Installation/Materialisierung des exakt gepinnten Upstream-Checkouts als
   Daedalus-eigener, byte-verifizierter Artifact-Prozess.
2. Verifizierter äußerer Container/User-Namespace auf allen freigegebenen Hosts.
3. Live-Modell-Kompatibilitätslauf ohne Secrets in Logs oder Receipts.
4. Netzwerk-/Egress-Fault-Matrix einschließlich DNS, Proxy und Loopback-Bypass.
5. Unknown-outcome-Reconciliation bei Parent-, Worker- oder Gateway-Abbruch.
6. Erst danach eine executable `hermes_agent`-RuntimeRole-Zeile und eine
   produktive Provider-Effect-Klassifikation.
7. Selektives Entfernen duplizierter Ikarus-Agent-Loop-Pfade erst nach gemessener
   Parität und Rollback-Evidence.

## Keine Überbehauptung

Dieses Packet beweist eine funktionierende, streng begrenzte Adapterarchitektur
und einen Fixture-basierten vertikalen Slice. Es beweist noch nicht:

- produktive Sandbox-Gleichwertigkeit;
- Live-Hermes-Modellzugriff;
- vollständige Hermes-Parität;
- Gate-1-Abschluss;
- Produktionsfreigabe.

Iron Plan: ALIGNED
Iron Gate: 1
