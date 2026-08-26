# Gate-0-Closure — Owner-Entscheidung, 2026-08-26

Status: **BESIEGELT** durch ausdrückliche Owner-Anweisung vom 2026-08-26
(„ich will dass du jetzt gate 0 besiegelst, damit wir mal langsam weiter
gehen können"), ausgeführt durch Athena als Schreiber im §16-Protokoll.
Amendment: Revision 7 → 8, Record in
`docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl`.
Closure-Revision: der Commit, der dieses Dokument einführt.

## 1. Was dieses Dokument ist — und was nicht

Der Masterplan (§11, Revision 3 Punkt 4) macht den Gate-0-Ausgang von einer
**expliziten Owner-Closure-Entscheidung** abhängig. Dieses Dokument IST diese
Entscheidung: eine benannte, vollständige Disposition der 11 Blocker, die der
maschinelle Report am Closure-Tag meldet.

Es ist ausdrücklich **keine Umdeutung des Instruments**:
`python -m daedalus.gates report --gate 0` meldet weiterhin `closed:false`,
solange die gescopten Zeilen offen sind — das Instrument bleibt wahr, die
Entscheidung liegt als Owner-Akt DARÜBER, genau wie der Docker-Präzedenzfall
(`docs/GATE0_LINUX_FAULT_SCOPING_DECISION.md`) es vorgemacht hat. Kein
Szenario wird gelöscht, keine Zeile als „passed" umdeklariert, kein Guard
aufgeweicht.

## 2. Was Gate 0 geliefert hat (die Basis der Entscheidung, `[MEASURED]`)

- **Ein Kernel.** Event-Store + CAS, kanonische Contracts (Mission, Attempt,
  Evidence, Policy, Receipt, Fourfold-Snapshot, GraphProposal,
  RoundTripReport), eine Registry mit 100+ Zeilen und abgeleiteten (nie
  gemalten) Effekt-Spalten.
- **Zentralisierte Starts.** `unregistered_effectful_entrypoints: []`,
  `unguarded_entrypoints: []`, `missing_guard_contracts: []` — alle drei
  Kategorien LEER am Closure-Tag (Report an `d0ff5863`).
- **Fault-Matrix.** Ganzes-Matrix-Verdikt bei `bcc0feaf`: **24/24 Szenarien
  beobachtet, `fault.missing` = 0**, drei Spalten
  (fixture / linux-host / live-runtime) unter Produktions-Schlüsselmaterial
  (Owner-Key-Zeremonie 2026-08-18, Fingerprints veröffentlicht). Windows-Lauf
  22/22; Linux-Container-Lauf mit echtem Katalog gelaufen.
- **Leases mit beiden Hälften.** `python.offload` UND `python.attempt` halten
  Leases; seit `4f71c020` retainiert die Produktion auch die Terminal-Records
  (Consumer-Hälfte des Write-Evidence-Stores).
- **Sealed Promotion.** `owner_approval_enforced: true`;
  Promotion nur gegen konsumierte, authentifizierte Einmal-Approval.
- **Produktions-Minter.** Seit `7b813a88` existiert
  `daedalus/kernel/runtime_authorization_issuer.py` — fail-closed gegen die
  echte Registry, grün gegen eine CENTRAL-Zeile, mutationsgeprüft.
- **Fail-open Read-only-Inspektion.** Drift-Gate, Gate-Report, Reach — alle
  lesend, alle laufen ohne Lease.

Unabhängige Prüfung, soweit vorhanden und mit Grenzen benannt: Momus-NO-GO
gegen die Approval-Lane (2026-08-18, verhinderte einen zweiten
Promotion-Pfad), Cross-Vendor-Councils (codex, 10 Slices, rc=0),
Odysseus-Adversarialpässe, Funnel-Audits. Das ist Review-Evidenz, kein
formales externes Audit; niemand behauptet Letzteres.

## 3. Disposition der 11 Blocker am Closure-Tag

| # | Blocker (Report `d0ff5863`) | Disposition | Fällt, wenn |
| --- | --- | --- | --- |
| 1 | `fault_injection…whole-matrix:unbound:no-verdict-at-cited-revision` | **GESCOPED.** Das Verdikt existiert vollständig bei `bcc0feaf` (24/24, 0 missing). Ein Re-Binding an jedes neue HEAD erforderte Docker-Host + Live-Envelope pro Commit. Die 6 `fault.blocked`-Zeilen darin sind #2/#3. | ein docker-fähiger Host + Live-Envelope einen frischen 3-Spalten-Lauf am dann aktuellen HEAD erzeugen |
| 2 | darin: 4 Zeilen `docker-cli-unavailable` (`egress.unauthorized-endpoint`, `process.oom`, `sandbox.daemon-unavailable`, `secrets.undeclared-access`) | **GESCOPED nach Docker-Präzedenzfall.** Beschaffung, kein Engineering. Sichtbar, benannt, nicht umdeklariert. | der Owner einen Linux/Docker-Host bereitstellt und den Katalog fährt |
| 3 | darin: 2 Zeilen `live-envelope-unavailable` (`live-envelope.expiry`, `.binary-drift`) | **VERPFLICHTUNG, in Gate 1 getragen.** Ursache ist die fehlende Caller-Injection (Hälfte 2). Refusal-Logik existiert und ist unit-getestet; die Treiber liefen. | der erste produktionsgeminte Runtime-Start einen `live-runtime`-Envelope in `runtime_trust_ledger()` admittiert |
| 4 | `runtime-conformance-receipts:unbound:no-persisted-receipt-bundle` | **VERPFLICHTUNG, in Gate 1 getragen.** Echte Receipts (3 Runtimes × 8 Checks) existieren bei `bcc0feaf`; am Closure-HEAD liegt kein gebundenes Bundle. Derselbe erste Live-Start persistiert es. | wie #3 — dieselbe eine Arbeit |
| 5–12 | 8× `inventory_only` (`provider.claude/codex/deepseek(+rollback)/ollama.rollback/ollama_native`, `runs.gate0_matrix.verify_whole_matrix`, `runtimes.fault_attestation_issuer`) | **ANGENOMMEN ALS INVENTAR, mit den in der Registry SELBST eingetragenen Gründen und Fall-Bedingungen.** Mehrere Zeilen argumentieren gegen ihre eigene Migration (Konsolidierung statt Verdrahtung; datierte Evidenz-Verzeichnisse; fehlender Key-Custody-Contract). Ein Flip ohne erfüllte Vorbedingung wäre „routing around a guard". | pro Zeile deren eigene `notes=`/`migration=`-Bedingung; für `provider.claude`: Caller-Injection Hälfte 2 + Exact-Head-Verifikation (nächstes benanntes Paket) |
| — | `security_boundary_claimed:false` | **BLEIBT FALSE, absichtlich.** AGENTS.md zählt „a hook or instruction advertised as a complete security guarantee" zu den release-blockierenden Defekten. Diese Closure behauptet fail-closed-Verhalten NUR für die gemessenen Flächen und erhebt keinen Vollständigkeitsanspruch. Das Flag zu setzen wäre der Defekt, nicht das Offenlassen. | nie durch Behauptung; nur durch ein Evidenzregime, das den Anspruch trägt |

## 4. Die getragenen Verpflichtungen (verbindlich, Gate-1-Ära)

1. **Caller-Injection Hälfte 2:** ein Produktionspfad baut
   Request/Policy/Guards + Workspace-Grant + Observation-Authority und reicht
   den Mint durch `claude_bridge.ask_claude`; erster Live-Start admittiert den
   Envelope und persistiert das Receipt-Bundle (löst #3/#4, ermöglicht
   `provider.claude`-Flip).
2. **Kein neuer Effektpfad außerhalb der kanonischen Contracts** — die
   Gate-0-Invariante bleibt Prüfmaßstab jedes Reviews, sie endet nicht mit dem
   Gate.
3. Die gescopten Zeilen werden bei jedem Gate-Report weiter GEZÄHLT und
   berichtet; diese Entscheidung wird im Report nicht eingebaut, sondern nur
   hier zitiert.
4. Docker-Host-Beschaffung bleibt eine offene Owner-Position (#2).

## 5. Rollback

Rollback dieser Closure = ein neues Amendment, das die aktive Gate-Zeile auf
Gate 0 zurücksetzt — nie ein History-Rewrite (§16). Kein Code muss dafür
angefasst werden; nichts wurde aufgeweicht.

Iron Plan: AMENDMENT (Owner-Entscheidung, §16)
Iron Gate: 0 → 1
Evidence: Gate-Report an `d0ff5863` (11 Blocker, 3 leere Kategorien);
Whole-Matrix-Verdikt `runs/gate0-matrix-20260818-closure/` (24/24);
`runs/gate0-closure-20260818/` (Receipts, Attestationen);
`tests/kernel/test_runtime_authorization_issuer.py` (5/5).
