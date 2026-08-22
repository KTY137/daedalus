# Der Giga-Plan in Klartext (2026-08-22)

Die Langfassung (`GIGA_PLAN_2026-08-22.md`) ist für Agenten geschrieben. Das hier ist
dieselbe Sache für Menschen. Status: Entwurf, Codex-Runde 2 steht noch aus.

## Die Lage in drei Sätzen

1. Es gibt **zwei Versionen des Projekts**, die beide behaupten, die offizielle zu sein:
   dieses Repo (Regelbuch-Revision 2) und der `agent_env_g0`-Ordner (Revision 6, mit
   einem zweiten Kern und einem anderen Freigabe-Schloss). Die eigene HANDOFF.md sagt
   seit dem 17.08.: „dieses Repo ist nicht mehr die Wahrheit."
2. Die gesamte Inventur von gestern Nacht lief auf der **vermutlich veralteten** Version.
   Bevor irgendwer Module löscht, Docs umbaut oder Gate 0 stempelt, muss klar sein,
   welche Version gilt.
3. Die Kategorientheorie-Forschung ist **kein neuer Plan** — sie läuft schon als sauberes
   Experiment (`higher_twin_nc`, 63 Tests grün) und braucht dafür keine Tensoren.

## Die eine Entscheidung, die zuerst fällt

**Welches Repo gilt?** Das entscheidest nur du. Aber nicht aus dem Bauch: Phase 0 misst
vorher beide Versionen mit denselben Befehlen, und du entscheidest aus der Tabelle.
Die Verlierer-Version wird nicht gelöscht, sondern eingefroren und abgeerntet.

## Der Plan in acht Schritten

| # | Was | Warum | Fertig wenn | Wer |
|---|-----|-------|-------------|-----|
| 0 | **Messen statt raten** (läuft gerade) — beide Versionen in Wegwerf-Kopien prüfen: Regelbuch-Ketten intakt? Tests grün? Gibt es wirklich zwei Kerne, oder liegen nur Ordner nebeneinander? Hält das Freigabe-Schloss Angriffen stand? Was ginge bei jeder Wahl verloren? | Alle fünf Codex-Prüfer sagten: erst messen, dann entscheiden | Ein Entscheidungs-Paket mit allen Zahlen, jede Zahl mit Befehl und Commit | Agenten |
| 0b | **Forschung anmelden** (parallel) — die längst geplante „Ceiling"-Messung fest vorregistrieren, eine Tabelle „was ist wirklich neu vs. in der Literatur bekannt", und das Tensor-Experiment nur als Kalibrierung, noch ohne Training | Sonst misst man hinterher das, was man sehen will | Protokoll committed, bevor ein einziges Datum angeschaut wurde | Agenten + du unterschreibst die Schwelle |
| 1 | **Du entscheidest**, welches Repo gilt — per **Nachtrag** im Regelbuch, nichts wird umgeschrieben; die andere Version bekommt ein Tag „eingefroren" | Zwei Wahrheiten sind keine | Genau eine gültige Kette, die andere als Geschichte erhalten | **Du** |
| 2 | **Ernte** — alles Gute der Verlierer-Version in die Gewinner-Version holen (in beide Richtungen: z. B. Serena-Hook, vet.py-Härtung, Freigabe-Prüfer vs. forest_v2, Ceiling-Werkzeuge), mit Tests | Nichts Bewährtes darf verloren gehen | Jede Änderung: übernommen, überarbeitet oder mit Grund verworfen — null „offen" | Agenten, du nickst die Liste ab |
| 3 | **Schnelle Reparaturen** im ungeschützten Code: den unbewachten Startpunkt `daedalus.loop` registrieren, die Architektur-Karte im Lauf regenerieren, Geheimnis-Effekte modellieren, das offene Embedding-Leck nach draußen schließen | Das sind die realen Sicherheits-/Verlässlichkeitslücken, egal wer gewinnt | Ein Loop-Durchlauf läuft durch die zentrale Wache, ohne Leck | Agenten |
| 4 | **Gate 0 ehrlich schließen** — alle 24 Fehler-Tests wirklich **ausführen** (heute: 18 ausgeführt, 6 nur „erklärt"), die 13 offenen Türen einzeln entscheiden, das Freigabe-Schloss wählen (**zuletzt**, nach Angriffstests), dann der Stempel | Ein Stempel auf Erklärungen statt Messungen wäre eine Übertreibung | Bericht sagt: ausgeführt=24, blockiert=0, Türen entschieden, Angriffe abgewehrt | **Du** (Türen, Schloss) |
| 5 | **Docs aufräumen** — nur verschieben, nie löschen; HANDOFF einfrieren, eine STATUS-Datei für den aktuellen Stand; Ziel: die Wahrheit in fünf Klicks | 109 aktive Dateien reichen noch nicht, es fehlt die Landkarte | Ein Leser findet Regelbuch, Stand, Plan, Inventar, Experimente von einer Seite aus | Docs-Agent |
| 6 | **Erste echte Mission** — die geplante Probe-Aufgabe (`voltage → bias_voltage` quer durch Python, Markdown, CSV): erst als Probe, dann nach dem Stempel richtig | Das ist Gate 1; beweist, dass der Kern eine Aufgabe end-to-end trägt | Ein Beweis-Paket mit Mission, zwei Arbeitspaketen, Versuchen, Prüfungen | Agenten |
| 7 | **Forschung** — Ceiling-Messung laufen lassen; das Kategorientheorie-Experiment mit **fremden Repos** bestätigen (bisher nur eigene Spielzeug-Fixtures); Tensor-Arme nur, wenn die Zahlen es hergeben | So bleibt die Forschung falsifizierbar statt Wunschdenken | Jeder Arm hat Ergebnis oder eine datierte Absage mit Zahl | Agenten, du als Schiedsrichter |
| 8 | **Werkzeuge für die Crew** — strukturelle Suche (`daedalus brief`) zuerst, Serena-Nutzung messen, Embeddings zuletzt | Die Crew nutzt das Vorhandene nicht, nicht weil es fehlt, sondern weil kein Anschluss da ist | Das Kommando existiert und wird in mehr als der Hälfte der Sessions benutzt | Agenten |

## Deine wichtigsten Entscheidungen (6 von 18)

- **D1 – Welches Repo gilt.** Zuerst. Aus dem Phase-0-Paket, nicht aus dem Commit-Zähler.
- **D2 – Regelbuch-Pause.** Bis zum Nachtrag keine weiteren Amendments auf keiner der beiden Linien (auch 004 wartet).
- **D4 – Die 13 Türen.** Jede einzeln: schließen oder mit Begründung offenlassen — erst nach der Nachmessung auf dem Gewinner.
- **D5 – Das Freigabe-Schloss.** Geheimschlüssel-Variante (g0) oder signiertes Git-Tag (hier) — erst nach den Angriffstests. Wenn ein normaler Kandidaten-Prozess den Geheimschlüssel lesen kann, ist die g0-Variante tot.
- **D6 – Der Guard.** Er schlägt bei harmlosen Lese-Befehlen an, sobald ein Dateiname im Text steht (8 gemessene Fehlalarme). Regel ändern: Schreibabsicht prüfen, nicht Wortlaut.
- **D16 – Die Forschungs-Schwelle.** Die 15 %-Schwelle für „Tensoren lohnen sich" war nicht vorregistriert; du legst sie fest, bevor jemand die Daten sieht.

## Was den Plan stoppt

- Eine der beiden Regelbuch-Ketten ist in sich kaputt → kein sauberer Nachtrag möglich, erst reparieren.
- Ein Wegwerf-Experiment kann das Freigabe-Schloss aushebeln → die Variante ist raus.
- Beim Aufräumen wird irgendwo etwas gelöscht statt verschoben → der Commit wird zurückgenommen.
- Das Kategorientheorie-Experiment überlebt fremde Repos nicht → der Strang stoppt, Nachtrag statt Leugnen.

## Der „Schizo-Check" zur Tensor/Kategorientheorie-Idee, in Klartext

Nicht verrückt — aber kleiner, als es klingt. Die Kategorientheorie-Seite ist schon
deine beste Forschung und braucht keine Embeddings (genau deshalb hat sie Angriffe
überlebt). Jede benannte Mathematik (Tensor-Faktorisierung, Garben, Descent, Lens-Gesetze)
existiert in der Literatur. Das einzige, was hier wirklich neu sein könnte: die Idee,
aus deinen gemessenen Eingriffs-Kommutatoren vorherzusagen, welche Patches sich vertragen.
Mit ~40 selbstgebauten Paaren lässt sich das noch nicht trainieren — erst mit fremden
Repo-Historien. „Tensorisierter Descent" und „Tensorprodukt zweier Node Cards" sind
Wortsalat, bis jemand sagt, was gemessen wird und wann es gescheitert wäre.

## Was gerade läuft, was du tun kannst

- Läuft: Phase 0 (zehn Agenten messen beide Versionen) → Entscheidungs-Paket.
- Du: `.\claude-docs-watchdog.ps1` (Docs-Wache im Hintergrund) und das Codex-Runde-2-Skript
  über diesen Plan. Dann Entscheidung D1 aus dem Paket.
