# Gate 0 — Entscheidungsvorlage: die zwei live-runtime-Fault-Zeilen

Status: ENTWURF — ENTSCHEIDUNG STEHT AUS (nur der Owner entscheidet).
Erstellt: 2026-08-18, Nachtschicht watchdog-mission3. Dieses Dokument
entscheidet nichts und baut nichts; es benennt die Optionen und ihren Preis.

## Kontext

Nach der Container-Spalte (`linux-host`) und der Fixture-Spalte
(`deterministic-fixture`) bleiben genau zwei `fault.missing`-Zeilen im
Gesamt-Matrix-Verdikt offen:

| Szenario | Erwartung | Executor |
| --- | --- | --- |
| `runtime.live-envelope.expiry` | abgelaufene Live-Evidenz kann keine Produktions-Lease autorisieren (`refused-before-start`) | `live-probe:runtime-envelope-expiry` |
| `runtime.live-envelope.binary-drift` | Binary-/Image-Drift nach der Konformanz quarantäniert den exakten Envelope ohne Fallback (`refused-before-start`) | `live-probe:runtime-binary-drift` |

Beide Zeilen tragen die Authority `live-runtime`
(`daedalus/runtimes/fault_matrix.py:500-501`). Eine dritte Collector-Spalte
mit dieser Authority existiert nicht, und sie ist nicht mit Repo-Bordmitteln
herstellbar: die Spalte verlangt eine Signatur-Autorität, deren
Schlüsselmaterial *nicht* in diesem Repository liegt.

## Was ein live-envelope-Collector konkret bräuchte

1. **Einen echten Provider-Lauf.** Ein `RuntimeConformanceEnvelope` mit
   `authority="live-runtime"` entsteht nur über
   `bind_conformance_envelope(manifest, identity, receipt, ...)`
   (`daedalus/runtimes/profiles.py:474`): reale `RuntimeProbeIdentity`
   (u. a. `executable_sha256`, `environment_sha256`) eines wirklich
   installierten Providers (Claude/Codex/Ollama) plus ein Konformanz-Receipt
   aus Live-Beobachtungen. Auf dieser Windows-Box ist die Sandbox-Hälfte
   nicht demonstrierbar; realistisch ist der Linux-/RTX-Host oder CI.
2. **Eine unabhängige Signatur-Autorität in Produktions-Custody.** Die
   Verdikt-Spalten verlangen je Spalte eine eigene Issuer-Identität
   (`WholeRuntimeFaultMatrixVerdict`: ein Issuer pro Spalte, `key_class`
   pro Spalte). Für einen Closure-tauglichen Lauf muss die dritte Spalte
   unter `production`-Schlüsseln attestieren. Dieses Schlüsselmaterial darf
   per Isolations-Invariante nicht im Repo oder beim Kandidaten liegen —
   es braucht eine Owner-seitige Key-Zeremonie und geschützte Ablage
   (dev-Keys existieren im Issuer-Pfad, Produktions-Keys bewusst nicht).
3. **Zwei Live-Probe-Treiber.**
   - *expiry*: einen echten Envelope über `max_age` altern lassen (bzw. mit
     kontrolliertem `now` gegen `verify_current_conformance`,
     `daedalus/kernel/runtime_conformance.py:125`) und die Refusal an der
     Lease-Grenze beobachten — nicht nur den Unit-Pfad, sondern den
     Effekt-Boundary-Pfad.
   - *binary-drift*: nach der Konformanz die Provider-Binary/Image-Identität
     ändern, `executable_sha256` neu messen und die Quarantäne des exakten
     Envelopes ohne Fallback beobachten (`verify_runtime_envelope`-Pfad,
     `daedalus/runtimes/profiles.py:517`).
4. **Persistenz + dritte Spalte.** Beobachtungen content-addressiert ablegen,
   Attestation-Bundle der neuen Autorität einsammeln, Verdikt mit drei
   Spalten neu erzeugen. Der Verdikt-Contract unterstützt die
   `live-runtime`-Spalte bereits; hier ist nur Collector-Arbeit nötig,
   kein Contract-Umbau.

Aufwandsschätzung: die Refusal-Logik selbst existiert und ist unit-getestet;
der Preis liegt fast vollständig in (a) Host/CI-Verfügbarkeit mit echten
Providern und (b) der Produktions-Key-Custody. Punkt 3 ist danach moderat
(zwei Treiber im bestehenden Probe-Muster), Punkt 4 mechanisch.

## Option A — bauen

Die vier Schritte oben umsetzen; die Matrix wird ohne Scoping vollständig.

- Vorteil: `fault.missing` verschwindet durch Evidenz, nicht durch Beschluss.
  Revision 3 Punkt 4 (Gate-0-Closure braucht Live-Runtime-Receipts und die
  vollständige Fault-Matrix) wird direkt bedient.
- Preis: Owner-Key-Zeremonie + Linux-Host-Zeit + Live-Provider-Kosten;
  nichts davon ist aus diesem Worktree heraus leistbar.

## Option B — Scoping-Entscheidung nach Docker-Muster

Analog zu `docs/GATE0_LINUX_FAULT_SCOPING_DECISION.md` die zwei Zeilen
scopen. Wortlaut-Vorschlag für die Entscheidung (nur bei Owner-Annahme):

> Die zwei Fault-Szenarien der Authority `live-runtime`
> (`runtime.live-envelope.expiry`, `runtime.live-envelope.binary-drift`)
> werden für den Gate-0-Exit auf **Contract-Ebene gescoped**: Ihre
> `fault.missing`-Zeilen mit benanntem Grund („keine Signatur-Autorität in
> Produktions-Custody im Repo; Live-Spalte erfordert Owner-Key-Zeremonie und
> Live-Host") bleiben als akzeptierte, sichtbare Evidenz in der Matrix.
> Kein Szenario wird gelöscht oder als passed umdeklariert. Ein späterer
> Live-Lauf ERSETZT diese Entscheidung, sobald er existiert.

- Vorteil: ehrlich, sichtbar, rollback-frei; deckungsgleich mit dem
  angenommenen Docker-Präzedenzfall.
- Preis: sie berührt Revision 3 Punkt 4 („complete fault matrix") und ist
  darum ausdrücklich owner-gated; und sie ersetzt NICHT die weiterhin
  geforderten Live-Runtime-Conformance-Receipts (Revision 3 Punkt 2/4) —
  gescoped würden nur die zwei Fault-Injektions-Zeilen, nicht die
  Live-Evidenz-Pflicht insgesamt.

## Empfehlung

Kurzfristig Option B als explizite, sichtbare Owner-Entscheidung — mit dem
Wortlaut oben und der ausdrücklichen Markierung, dass die Live-Receipt-Pflicht
unberührt bleibt. Option A bleibt der Zielzustand und gehört als eigener
Arbeitsblock auf den Linux-/RTX-Host eingeplant, beginnend mit der
Key-Zeremonie (der langlaufende Teil, der alles andere blockiert).

## Rollback

Option B rückgängig machen = die Scoping-Datei löschen und einen Live-Lauf
als Evidenz verlangen; keine Code-Änderung nötig, da nichts aufgeweicht wird.
