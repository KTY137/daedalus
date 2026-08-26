# Work Packet G1-IKARUS-01 — der Ikarus-Supervisor-Slice nach Agentic-J-Form

**Status:** IN BAU (2026-08-26). **Klassifikation:** `ALIGNED`.
**Gate:** 1 (aktiv seit Revision 8). **Owner-Anweisung:** „Orchestration und
Ikarus nach AgentJ aufbauen" (2026-08-26) + „ja mach".
**Vorbild:** `docs/research/AGENTIC_J_NOTES_20260826.md` §3.1 (Supervisor +
state ledger + Rollen-Subagenten).
**Base revision:** `9e05ed98`.

## Eine Behauptung

Es gibt eine wiederverwendbare Supervisor-Komponente, die ein Ziel in eine
`MissionContract`-getriebene Ausführung über Rollen-Attempts übersetzt und
dabei einen **geteilten, manipulationsevidenten State-Ledger** führt — ohne
neuen Event-Store, ohne neue effektbehaftete Tür, ohne Chat als Zustand.

## Scope (exakt)

- NEU `daedalus/ikarus_supervisor.py` — Bibliothek, KEIN CLI-Tail (keine neue
  Tür; Anbindung an bestehende Türen ist ein Folgepaket).
- NEU `tests/test_ikarus_supervisor.py`.
- Dieses Dokument.

**Verboten:** `daedalus/spine/*`, `daedalus/kernel/*`, `daedalus/build.py`,
Registry, Plan, Evaluatoren. Der Slice KONSUMIERT die kanonischen Produzenten
(`BuildSession` bindet Mission-/WorkItem-Ids, `mission_contract_for_build_session`
bindet den Policy-Digest, `TaskAttempt` fährt den Attempt), er dupliziert
keinen.

## Abbildung Agentic-J → dieser Slice

| Agentic-J | hier |
| --- | --- |
| Supervisor-Deep-Agent | `MissionSupervisor.run()` — deterministischer Treiber, v1 ohne LLM (wie `ikarus_chat` v1: erst reviewbar, dann klug) |
| state ledger, geteilt | `runs/…/ledger/` — **unveränderliche, content-adressierte Revisionen**, jede nennt `previous_ledger_sha256`; Wahrheit bleibt SpineLedger + Contracts, der Ledger ist Projektion |
| Subagenten mit Toolsets | `RoleHarness`-Registry: Rolle → (runner_factory, gate_factory); v1 EINE Rolle („coder"), injizierbar — Provider-Anbindung kommt mit Caller-Injection Hälfte 2 |
| QA advisory | ausgelassen (Folgepaket; Evaluator-Grenze §4.4 bleibt) |

## Akzeptanzmatrix (eingefroren)

| # | Behauptung | rot wenn |
| --- | --- | --- |
| 1 | gleicher Plan ⇒ gleiche `mission_id`/`work_item_ids` (Replays möglich) | Ids wandern mit der Uhr |
| 2 | jede Ledger-Revision nennt Vorgänger-Digest; `verify_state_ledger` erkennt Manipulation UND Lücken | ein editiertes/entferntes Glied bleibt unbemerkt |
| 3 | unbekannte Rolle ⇒ Refusal VOR jedem Attempt, im Ledger benannt | Dispatch trotz unbekannter Rolle |
| 4 | fail-fast: bounct Item N, wird N+1 nie dispatcht und der Ledger sagt warum | stiller Weiterlauf |
| 5 | ein grüner Lauf hinterlässt: MissionContract-Artefakt, Ledger-Kette, pro Item AttemptReceipt-Digests | ein Baustein fehlt |
| 6 | der Supervisor nimmt kein Transkript und speichert keins (Chat ≠ Zustand) | ein Prosa-Verlauf taucht im Ledger auf |

## Verifikation

pytest-Suite (Matrix oben) + Mutationsprobe an der Kette (Glied editieren).
Momus-Review des Designs: OFFEN, nachgereicht — als eigener Review-Schritt
benannt, nicht übersprungen-und-verschwiegen.

Iron Plan: ALIGNED
Iron Gate: 1
