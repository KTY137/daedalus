# Gate 0 — Offene Owner-Entscheidungen (Stand 2026-08-17, abends)

Status: **Punkte 1, 4, 5 MOOT** [MEASURED 2026-08-25] — `tools/iron_plan_guard.py` (removed 2026-08-22)
existiert nicht mehr (Retirement 2026-08-22, Plan-Revision 7); jede Frage, die
sich auf `PROTECTED_PATHS` oder den Guard-Text bezieht, hat kein Subjekt mehr.
Punkte 2, 3, 6-9 nicht neu verifiziert, als historische Diagnose belassen.

Vier Entscheidungen blockieren Rest-Failures der Voll-Suite (35 failed / 6428
passed auf Trunk `7c88f72`, MEASURED 17:31). Keine davon ist eine Messung —
alle vier sind Policy- bzw. Identitätsfragen, die nur der Owner treffen durfte.

## 1. Guard-Test-Fixture nach Amendment 005 (NEU diagnostiziert, MEASURED)

**Failure:** `tests/test_iron_plan_guard.py (removed 2026-08-22)::IronPlanContractTests::`
`test_ci_history_check_accepts_adoption_and_rejects_rewrite`

**Diagnose (MEASURED 2026-08-17, Trunk `7c88f72`):** Der Test baut ein
synthetisches Adoption-Repo ausschließlich aus `guard.PROTECTED_PATHS`
(Zeilen 704–711). Seit Amendment 005 prüft der Guard die Retained Source
`daedalus/kairos/_gated_writes_legacy.py.src`, die `gated_writes.py` per
Blob-SHA pinnt — diese Datei ist aber KEIN Protected Path und fehlt daher im
Fixture-Repo. Drei Folge-Errors, eine Ursache:

```
_gated_writes_legacy.py.src is missing while gated_writes.py pins it
AUTO_PROMOTE_LEVELS is declared in neither the promotion strangler nor its retained source
run_write_wave is defined in neither the promotion strangler nor its retained source
```

**Warum ich das nicht selbst fixe:** `tests/test_iron_plan_guard.py (removed 2026-08-22)` steht
selbst in `PROTECTED_PATHS`. Jede Änderung ist Amendment-Territorium.

**Option A (empfohlen, test-only, minimal):** Fixture kopiert die gepinnte
Retained Source mit. Exakter Diff gegen `tests/test_iron_plan_guard.py (removed 2026-08-22)`,
einzufügen nach der `for rel in guard.PROTECTED_PATHS:`-Schleife (vor
`run_git(repo, "add", "-A")`, Zeile 712):

```python
            retained = Path("daedalus/kairos/_gated_writes_legacy.py.src")
            shutil.copy2(ROOT / retained, repo / retained)
```

(Kein `mkdir` nötig — das Verzeichnis existiert durch die Kopie von
`gated_writes.py`.) Begründung: Die Integrität der Retained Source ist bereits
durch den Blob-Pin in der geschützten `gated_writes.py` gesichert; ein echtes
Adoption-Repo trägt die Datei ohnehin, weil sie mit dem Tree ausgeliefert
wird. Die Assertion-Menge des Tests bleibt unverändert — nichts wird
abgeschwächt.

**Option B (prinzipieller, Guard-Änderung):** Retained Source zusätzlich in
`PROTECTED_PATHS` aufnehmen — dann ist "PROTECTED_PATHS = alles, was ein
adoptierendes Repo braucht" wieder selbstkonsistent, und der Test läuft ohne
Fixture-Änderung grün. Kostet: ordentliches Amendment am Guard; gewöhnliche
Edits an der (eingefrorenen) Legacy-Datei brauchen dann das Token — was beim
Strangler-Pattern vertretbar, evtl. sogar erwünscht ist.

**Rollback beider Optionen:** Diff revertieren; der Test fällt exakt auf das
heutige Fehlerbild zurück.

## 2. v3-Scanner-Identität — verkleinert auf Option A (Schema-Bump)

Diagnose abgeschlossen (MEASURED, siehe
`docs/GATE0_V3_SCANNER_IDENTITY_DECISION.md`): Die vermeintliche
Identitäts-Policy-Frage war ein Scanner-Defekt — `.replace`-Klassifikation
kollidiert per Namensvergleich (0 von 197 `.replace`-Calls im Baum sind
echte `Path.replace`-Renames), plus ein Review-Test, der Builtin- und
Attribut-Calls in ein Set mischt. Optionen B (Arity-Gate, ~16 Zeilen, kein
Schema-/Record-Bruch, end-to-end verifiziert) und D (test-only, strikt
stärker) werden als gewöhnliche ALIGNED-Fixes gelandet.

**Beim Owner verbleibt nur Option A:** End-Position-Diskriminator gegen die
Mechanismus-Wurzel (Positions-Identität nicht injektiv bei Call-Ketten) —
erzwingt `daedalus-gate0-repository-write-inventory/1 → /2` über 3 Module
inkl. gepinnter Konstante: ein Artefakt-Identitätswechsel, der ein eigenes
reviewtes Commit verdient. Zusätzlich notiert, nicht entschieden: die
Exception-Vermischung in `report_v3.py:344` (Scanner-kaputt vs.
Repo-hat-Blocker unterscheiden sich nur durch die entkommende Exception).

## 3. Blob-Pin-Fixtures (13 Tests)

Re-Pin-Entscheidung nach den Landing-Wellen; siehe Session-Journal
`vault/Sessions/2026-08-17.md` (Checkpoint-Branch) und den
Blob-Pin-Integration-Review im Gate-Journal. Kein Fix ohne Owner-Beschluss,
welcher Stand der gepinnte ist.

## 4. CENTRAL-Prädikat und K1–K13-Rebase gegen Rev-4-Text

Beide aus dem Amendment-005-Umfeld übernommen (Session-Journal 2026-08-17,
16:00-Nachtrag). K1–K13 sind Kontrakt-Tests, deren Wortlaut noch gegen den
Revision-4-Plantext rebased werden muss — Textabgleich an geschützten
Artefakten, daher Owner.

## 5. CRLF-Schutz für die gepinnte Retained Source (.gitattributes, Owner)

MEASURED 2026-08-17 abends: Ein frisch angelegter Windows-Worktree checkt
`daedalus/kairos/_gated_writes_legacy.py.src` mit CRLF aus
(`git ls-files --eol` → `i/lf w/crlf`), der On-Disk-Blob-Hash weicht dann vom
Pin in `gated_writes.py` ab und `iron_plan_guard.py verify` (replaced by daedalus/hooks/, 2026-08-23) bricht mit 3
Fehlern (eine Ursache). Fail-closed hat gehalten: weder die Watchdog-Session
noch die Koordinatorin durften die Datei normalisieren.

Workaround (agentenseitig, angewendet): Worktree mit
`git -c core.autocrlf=false worktree add …` anlegen — Blob dann byte-exakt
`e31d24ec67f7…`, verify Exit 0 (MEASURED, `gw_watchdog-mission2`).

Dauerhafter Fix (Owner, da `.gitattributes` protected): Zeile
`*.py.src -text` (oder die konkrete Datei) in `.gitattributes` aufnehmen,
damit jede Checkout-Übersetzung für Pin-Subjekte abgeschaltet ist. Gleiche
Fehlerfamilie wie Wave 1 („fixtures stop writing CRLF into byte-exact
files") — dritter Auftritt des CRLF-Dämons heute.

## 6. Zweiter CRLF-Byte-Pin-Rotfall (Retention-Inventar)

MEASURED (Review-Singles-Lane, 2026-08-17 abends):
`tests/gates/test_provider_target_receipt_retention_inventory.py::`
`test_inventory_is_rebound_to_topology_hardened_parent` ist auf JEDEM
Windows-Checkout rot — das Inventar hasht Working-Tree-Bytes eines Moduls,
das mit 678 CRLF ausgecheckt wird, während der Pin auf LF berechnet wurde.
Gleiche Familie wie Punkt 5; der `.gitattributes`-Fix dort sollte beide
Pin-Subjekte abdecken (Liste der Byte-Pin-Subjekte vor dem Amendment
erheben). Positiv: Der Pin hat in der Lane einen Prosa-Edit an einem
gepinnten Modul korrekt verhindert.

## 7. Evidenz-Integrität: Fault-Matrix-Mutationsskripte messen auf Windows nichts

MEASURED (Review-Singles-Lane): `scripts/run_fault_matrix_wire_type_mutations.py`
sandboxt per PYTHONPATH, aber `python -m pytest` stellt cwd (Repo-Root) vor
den Sandbox-Pfad — die mutierte Kopie wird nie importiert, jeder Mutant
„überlebt" unabhängig vom Guard. Drei Schwester-Skripte teilen das Muster
(`run_fault_matrix_contract_mutations.py`, `…_contract_exact_mutations.py`,
`…_exact_durable_mutations.py`). Jede „mutants killed"-Evidenz aus diesen
Skripten auf Windows ist suspekt und muss neu erhoben werden. Dieselben
drei Mutationen in-place ausgeführt: 3/3 killed — die Guards selbst tragen.
Fix läuft als eigene Lane (`grind/fault-harness`); der dort geparkte Stash
enthält einen Kandidaten-Fix (+4 Zeilen je Skript) aus der ersten Welle.

## 8. Zwei Fault-Matrix-Subsysteme — Rekonziliation nötig (Architektur, Owner-Review)

MEASURED (Issuer-Lane, 2026-08-17 spät): `daedalus/gates/fault_matrix.py`
(Manifest/Receipt, 12 Szenarien, eigenes Verdikt `status`/`failure_count`)
und `daedalus/runtimes/fault_matrix.py` (kanonischer Katalog, 24 Szenarien:
13 deterministic-fixture + 9 linux-host + 2 live-runtime) haben KEINEN
Draht zwischen ihren Verdikten — zwei Autoritäten für „die Fault-Matrix"
ist genau der Parallelzustand, den die Verfassung verbietet (§12). Für den
Gate-0-Exit braucht die runtimes-Matrix noch: den deterministic-fixture-
Collector (13 Zeilen — Lane läuft), einen live-runtime-Collector (2
Zeilen), je Spalte eine eigene Issuer-Identität, und einen Driver-Re-Run
am beanspruchten HEAD (Exact-Head-Policy). Danach: eines der beiden
Subsysteme zur Projektion des anderen erklären oder stilllegen — das ist
die Owner-Review-Frage.

## 9. Council-Infrastruktur: vier gemessene Betriebsblocker (Nacht-Council 2026-08-18)

MEASURED (degraded quorum 1/4, Bus `runs/council/council-20260817T220729Z-…`):
(1) Der Secret-Floor verweigert Evidenz mit Dev-Key-Literalen in
Test-Fixtures — 5580f57s Testdatei ist damit nicht voll councilbar;
Entscheidung: Evidenzweg freigeben ODER Dev-Keys aus Testtexten in
Fixtures/Env verlagern. (2) Der claude-Seat braucht ein größeres
Per-Call-Budget (180s-Cap führte zu Timeout in beiden Runden). (3) Das
lokale Ollama beantwortet unter Lanes-Last kein /api/chat (Version-Endpoint
ok — Inference tot). (4) agy weiter ohne Bench-Login, Bench zudem offline.
Die drei inhaltlichen Council-CHECKs laufen bereits als deterministische
Test-Lane (`grind/council-checks`).

## Zusatz: Amendment-005-Kit — ERLEDIGT, kein Owner-Run mehr nötig

KORREKTUR (17:10): Eine frühere Fassung dieses Abschnitts empfahl einen
Owner-Einzeiler. Das war falsch. Das Kit zielt per `--root`-Default auf den
Trunk (`DEFAULT_ROOT = agent_env_g0`, Kit Zeile 35), und dort ist Amendment
005 seit heute Nachmittag vollzogen (`900665e`, Trunk-Verfassung Revision 4,
verify Exit 0). Die ABORTs bei erneuten Läufen ("expected guard block not
found exactly once") sind die Idempotenz-Sicherung des Kits — MEASURED
17:08 durch den Owner-Lauf selbst; der Trunk-Guard trägt den neuen Block
(`_RETAINED_SOURCE_GIT_BLOB_SHA1` vorhanden).

Offen bleibt nur die getrennte Frage, ob der historische Checkpoint-Branch
(Verfassung Revision 1, zwei Amendments hinter dem Trunk) nachgezogen werden
soll. Dafür passt das Kit NICHT (sein OLD_BLOCK stammt aus dem
Trunk-Guard-Text nach der Promotion-Versiegelung; im Rev-1-Guard kommt er
nicht vor). Empfehlung: nicht nachziehen — der Trunk ist die Vorwärtslinie;
wenn doch gewünscht, braucht es ein checkpoint-spezifisches Kit als eigene
Owner-Entscheidung.
