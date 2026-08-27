# Work Packet G1-IKARUS-02 — vendor-neutraler Role-Runtime-Port

**Status:** IMPLEMENTIERT / REVIEWED (2026-08-27); Owner-Handoff, Merge und
Promotion ausstehend. **Klassifikation:** `ALIGNED`.
**Gate:** 1. **Base revision:** `749ee3deb57e03bc02726c4373e4f90a4aeeb1af`.
**Abhängigkeit:** `G1-IKARUS-01` (gelandet in `1b272b58`) und die aus der
Gate-0-Closure übernommene Caller-Injection-Verpflichtung.

## Eine Behauptung

Jedes Ikarus-WorkItem kann vor dem Dispatch genau eine versionierte
`(role, runtime_id)`-Bindung tragen. Ein Runtime-Wechsel ändert keine
Supervisor-Verzweigung; unbekannte, deaktivierte oder seit der Planung
gedriftete Bindungen werden vor `TaskAttempt` verweigert. Dieses Paket öffnet
keinen Provider-Effekt.

Die Bindung ist zunächst ein **Port**, keine Produktionsfreigabe. Nur
injizierte Fixture-Runner sind ausführbar. `claude_cli`, `codex_cli` und
`hermes_agent` bleiben source/design-only, bis ihre separaten Broker-,
Runtime-Trust-, Observation- und Exact-Target-Pakete vollständig gelandet sind.

## Scope (exakt)

- NEU `daedalus/ikarus_runtime_role.py`
- ÄNDERN `daedalus/ikarus_supervisor.py`
- NEU `tests/test_ikarus_runtime_role.py`
- ÄNDERN `tests/test_ikarus_supervisor.py` nur für die neue Ledger-Projektion
- NEU `docs/adrs/022-hermes-agent-bounded-reuse.md`
- NEU `docs/research/hermes-agent-v2026.8.19-provenance.json`
- dieses Dokument

**Verboten:** `daedalus/kernel/**`, `daedalus/spine/**`,
`daedalus/runtimes/**`, `daedalus/providers/**`,
`daedalus/adapters/subprocess_adapter.py`, Registry-Wiring, Plan,
Amendment-Chain, vendierter Hermes-Code, Installer, Gateway, Scheduler,
Session-/Memory-Store, Evaluator oder Promotion.

## Kanonische Naht

`MissionSupervisor` bleibt der einzige Ikarus-Harness und `TaskAttempt` der
einzige Attempt-Pfad. `RuntimeRoleRegistry` ist eine immutable, caller-lokale,
rein datenförmige Dispatch-Tabelle ohne Callables, **keine** Policy-,
Runtime-Trust- oder Effect-Registry. Ausführbare Fixture-Callables bleiben auf
der bestehenden `RoleHarness`-Naht und werden unter einem Composite-Key mit
vollem Binding-Digest injiziert. Die strukturelle Binding-ID wird in
Missionsidentität, Build-Task-Builder,
State-Ledger und `TaskSpec.metadata` gebunden. Dadurch bindet der kanonische
`AttemptContract.task_sha256` die Auswahl indirekt; sein derzeit generisches
TaskAttempt-`runtime_manifest_sha256` ist ausdrücklich noch kein Live-Provider-
Manifest. Diese letzte Bindung ist ein Folgepaket, nicht eine Behauptung hier.

## Akzeptanzmatrix (eingefroren)

| # | Behauptung | rot wenn |
| --- | --- | --- |
| 1 | gleicher Plan + gleiche Runtime-Bindung ⇒ gleiche Mission-/WorkItem-IDs; Runtime-/Versionswechsel ⇒ andere IDs | eine Backend-Änderung bleibt identisch |
| 2 | Supervisor und Port enthalten keine Claude-/Codex-/Hermes-Verzweigung; Runtime-Bindings sind data-only und starten keinen Prozess | ein Binding trägt Callables, ein Vendorname steuert Code oder `subprocess` erscheint |
| 3 | zwei injizierte Fixture-Runtimes führen dieselbe Rolle ohne Supervisor-Änderung über `TaskAttempt` aus | ein Runtime-Wechsel braucht einen Supervisor-Hunk |
| 4 | unbekannte Runtime verweigert vor Attempt/Effekt und landet benannt im State-Ledger | stiller Fallback auf die Rollen-Default-Runtime |
| 5 | source-only Runtime verweigert vor Attempt/Effekt | Hermes/Codex/Claude wird durch Deklaration ausführbar |
| 6 | doppelte oder unversionierte Bindung wird beim Registry-Bau verweigert | late-wins oder leere Versionsidentität |
| 7 | Descriptor-Drift zwischen Planung und Dispatch verweigert vor Attempt | geplant wurde v1, ausgeführt wird v2 |
| 8 | Runtime-ID und Binding-Digest reisen in Ledger und `TaskSpec.metadata` | die ausgeführte Fixture-Auswahl ist nicht nachweisbar |
| 9 | bestehende rollenbasierte `inprocess`-Missionen bleiben kompatibel | G1-IKARUS-01 wird unbrauchbar |
| 10 | kein Provider-Import, keine neue Effect-Tür, kein zweiter Store | der Port umgeht Caller-Injection/Broker |

## Baseline vor Änderung

```text
python -m pytest tests/test_ikarus_supervisor.py tests/test_codex_provider.py \
  tests/providers/test_claude_runtime_broker.py tests/test_adapters.py -q
69 passed in 156.94s
```

Zusätzliche read-only Vertragsbaseline des Packet-Reviews:

```text
122 passed in 135.59s
```

Sie deckte Claude-Broker, Broker-Bypass-Inventar, Runtime-Authorization,
Conformance-Profile und Provider-Invocation-Registry ab.

## Evidenz nach Änderung

```text
python -m py_compile daedalus/ikarus_runtime_role.py \
  daedalus/ikarus_supervisor.py tests/test_ikarus_runtime_role.py \
  tests/test_ikarus_supervisor.py
exit 0

python -B -m pytest -q -p no:cacheprovider \
  tests/test_ikarus_runtime_role.py tests/test_ikarus_supervisor.py
32 passed in 70.13s

python -B -m pytest -q -p no:cacheprovider \
  tests/test_ikarus_runtime_role.py tests/test_ikarus_supervisor.py \
  tests/test_codex_provider.py \
  tests/providers/test_claude_runtime_broker.py tests/test_adapters.py
95 passed in 214.59s

python -B -m pytest -q -p no:cacheprovider \
  tests/providers/test_claude_runtime_broker.py \
  tests/providers/test_claude_bypass_inventory.py \
  tests/runtimes/test_runtime_provider_broker.py \
  tests/kernel/test_runtime_authorization_issuer.py \
  tests/test_codex_provider.py \
  tests/kernel/test_runtime_conformance_harness.py \
  tests/runtimes/test_runtime_conformance_profiles.py \
  tests/runtimes/test_provider_invocation_registry.py \
  tests/runtimes/test_provider_invocation_authority.py
122 passed in 170.45s
```

Die adversarielle Nachprüfung deckte zusätzlich Registry-Digest-Manipulation,
Mission-/Session-/Binding-TOCTOU, mutierbare Callback-`TaskSpec`s,
BuildTask-Statusfälschung, vertauschte ordinale WorkItem-IDs, stale
`mission.json`, malformed paths und Konstruktor-Kompatibilität ab. Am finalen
Stand wurden keine verbleibenden Release-Blocker im Packet-Scope gemeldet.
`python -m json.tool` für den Provenienzrecord und `git diff --check` für den
Packet-Scope waren erfolgreich.

## Ausdrücklich verschobene Produktionsarbeit

1. Codex übernimmt die Claude-Broker-Naht; bis dahin kein Live-Codex.
2. Der Broker konsumiert einen exact-head verifizierten Executable Target statt
   eines beliebigen Callbacks.
3. Ein Produktionscaller präprovisioniert Observation/Receipt-Speicher,
   erwirbt Runtime-Autorität und persistiert das vollständige Receipt-Bundle.
4. Erst dann werden die jeweiligen `provider.*`-Zeilen separat auf `CENTRAL`
   gesetzt und echte Runtime-Manifeste in den Attempt-Vertrag gebunden.
5. Hermes benötigt zusätzlich die in ADR-022 genannten Container-, Memory- und
   Side-effect-Conformance-Nachweise.

Iron Plan: ALIGNED
Iron Gate: 1
