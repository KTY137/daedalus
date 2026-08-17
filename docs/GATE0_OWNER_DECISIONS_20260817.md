# Gate 0 — Offene Owner-Entscheidungen (Stand 2026-08-17, abends)

Vier Entscheidungen blockieren Rest-Failures der Voll-Suite (35 failed / 6428
passed auf Trunk `7c88f72`, MEASURED 17:31). Keine davon ist eine Messung —
alle vier sind Policy- bzw. Identitätsfragen, die nur der Owner treffen darf.

## 1. Guard-Test-Fixture nach Amendment 005 (NEU diagnostiziert, MEASURED)

**Failure:** `tests/test_iron_plan_guard.py::IronPlanContractTests::`
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

**Warum ich das nicht selbst fixe:** `tests/test_iron_plan_guard.py` steht
selbst in `PROTECTED_PATHS`. Jede Änderung ist Amendment-Territorium.

**Option A (empfohlen, test-only, minimal):** Fixture kopiert die gepinnte
Retained Source mit. Exakter Diff gegen `tests/test_iron_plan_guard.py`,
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

## 2. v3-Scanner-Identität

Blockiert die v3-Report-Familie (3 Failures). Entscheidungsvorlage mit
Optionen + Diffs entsteht in Lane `grind/v3-scanner-owner-prep`
(`docs/GATE0_V3_SCANNER_IDENTITY_DECISION.md`), Diagnose läuft.

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
Pin in `gated_writes.py` ab und `iron_plan_guard.py verify` bricht mit 3
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
