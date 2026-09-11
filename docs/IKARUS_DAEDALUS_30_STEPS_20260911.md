# Daedalus durch Ikarus bedienen: 30-Stufen-Ausfuehrungsplan

Datum: 2026-09-11. Klassifikation: ALIGNED. Abgeleiteter Arbeitsplan, keine
Aenderung der Verfassung und kein Ersatz fuer den Masterplan.

## Ziel und Liefergrenze

Ikarus soll die fuer einen Auftrag erlaubten Daedalus-Funktionen finden,
ueber den kanonischen Kernel benutzen und das Ergebnis anhand von Evidenz
erklaeren. Ein Tool-Callback, ein Plan oder eine Modellantwort ist kein
Nachweis eines abgeschlossenen Benutzerauftrags. Keine pauschalen Toolrechte,
kein zweiter Executor/Scheduler, kein automatisches Merge oder Release.

Semantische Referenz ist der auf main gelesene Masterplan Revision 13 / 2.4.0
bei 217d5edc2b5e59441051b9cb0df60a5fbca93fe2. Die bestehende Ikarus-Linie
hat einen aelteren Masterplan und Paketaufbau; dieser Arbeitsplan ueberschreibt
beides nicht. Weiterer Produktbau muss die Abweichung zuerst selektiv aufloesen.

OFFEN bedeutet nicht vollstaendig abgenommen, nicht notwendig unimplementiert.
TEIL und MODUL bezeichnen nur die explizit genannten Messungen. Kein Status
hier schliesst Gate 1. Abhaengige Produktstufen benoetigen gruene oder explizit
als Blocker eingefrorene Vorgaenger, Fehlerproben, Revision, Evidenz und Review.

## Die 30 Stufen

| Nr. | Arbeit | Abnahme | Lieferstand |
|---|---|---|---|
| 01 | Basis, Autoritaet und Integrationslinie klaeren. | Selektive Integration ohne Verlust fremder Arbeit; keine zweite Produktionsbasis. | TEIL: Arbeit auf bestehender Ikarus-Linie, main-Integration offen. |
| 02 | Reproduzierbaren Start von Installation, CLI, Backend und Desktop pruefen. | Frischer Checkout; doctor/selftest melden reale Abhaengigkeitsfehler. | OFFEN |
| 03 | Projektbindung und Revision absichern. | Projektwechsel bleibt im richtigen Repository; fehlende/veraltete Basis blockiert. | OFFEN |
| 04 | Echten Modell-/Runtime-Betrieb nachweisen. | Erlaubter Provider-Roundtrip mit strukturierten Antworten, Tool- und Fehlerereignissen. | OFFEN |
| 05 | Faehigkeiten aus bestehenden Manifests und Policy projizieren. | Nur deklarierte und erlaubte Tools angeboten; Sperrgruende sichtbar. | OFFEN |
| 06 | Chat, CLI und API an denselben Ausfuehrungspfad binden. | Gleiche Vertrags-/Zustandsregeln; kein Chat als Workflow-Datenbank. | OFFEN |
| 07 | Auftrag, Frage, Zitat, Bestaetigung und Widerruf trennen. | Kein Zitat/Fragezeichen erzeugt Freigabe; Bestaetigung bindet den Auftrag; Frische separat pruefen. | TEIL: 124 Eingabetests plus 15 Quellcode-Routingproben, Frische/NL-Abnahme offen. |
| 08 | Absicht in Mission und WorkItems uebersetzen. | Renovation, Genesis und allgemeine Assistenz unterscheiden; fehlend ist nicht unzutreffend. | OFFEN |
| 09 | Policy an jeder Wirkung durchsetzen. | Pfad-, Projekt-, Egress- und Secret-Verletzung scheitert vor Wirkung. | OFFEN |
| 10 | Tool-Argumente und begrenzte Korrektur pruefen. | Ungueltiges Schema erzeugt klare Ablehnung statt Zusatzrechte/Endlosschleife. | OFFEN |
| 11 | Callbacks eindeutig korrelieren. | Gleichnamige parallele Tools bleiben an Plan/Call-ID gebunden. | TEIL: Modul-/Replay-Gegenproben; Live-Adapter offen. |
| 12 | Statuszeilen an Ereignisse binden; Snapshots unveraenderlich machen. | Erfundenes succeeded, widerspruechliche Historie und veraenderliche Eingabelisten scheitern. | MODUL: implementiert und getestet. |
| 13 | Gespeicherte Projektionen streng einlesen. | Exakte Felder, Schema, Typen, Historie und Digest bei /1-Wire-Roundtrip. | MODUL: from_dict; striktes Raw-JSON-Parsing bleibt beim Aufrufer. |
| 14 | Wiederaufnahme an externen Plan binden. | Keine ausgelassenen Aufgaben und keine erneute Wirkung beim Replay. | TEIL: from_events/from_projection; echte Mission-Recovery offen. |
| 15 | Abbruch, Timeout und unbekannte Wirkung behandeln. | Fehler bleiben erhalten; spaete Callbacks scheitern; Abgleich statt blindem Retry. | TEIL: Callback-Abbruch/Races; Live-Timeout/Kill offen. |
| 16 | Ehrlich ueber Ergebnisse berichten. | Geplant, eingereiht, laufend, Callback-Erfolg und geprueftes Ziel unterscheiden. | TEIL: Statuskonsistenz; Chat-/UI-Abnahme offen. |
| 17 | Daedalus-Status ueber Ikarus beobachten. | Projekt-, Git-, Watcher- und Queue-Fakten aus der gewaehlten Umgebung. | OFFEN; vorhandenes daedalus.status nutzen. |
| 18 | Struktur und Project Twin revisionsgebunden lesen. | Vier Ebenen passen zur Quelle; partielle/veraltete Ansichten sichtbar. | OFFEN |
| 19 | Relevanten Kontext sicher zusammensetzen. | Begrenzte belegte Slices; Egress-Grenzen und Secret-Filter; Zurueckhaltung sichtbar. | OFFEN |
| 20 | Aufgaben, Dokumentverweise und Historie erschliessen. | Bestehende tasks/docrefs-Beobachtungen liefern nachvollziehbare Befunde ohne Mutation. | OFFEN |
| 21 | Datei-, Browser- und Desktop-Arbeit vertikal pruefen. | Aktuelle Beobachtung plus gepruefter Zielzustand; Fokus/Scope/Ungewissheit blockieren. | OFFEN |
| 22 | Build-/Testausfuehrung ueber vorhandene sichere Runner anbinden. | Echte Testausgabe; kein Host-Fallback bei Sandbox-Ausfall. | OFFEN |
| 23 | Echte Renovation durch Ikarus abschliessen. | Event.voltage -> bias_voltage ueber Python/Markdown/CSV mit Kandidat, Tests und Wiederaufnahme. | OFFEN |
| 24 | Genesis ueber dieselben Vertraege bedienen. | Unterstuetztes Projekt baut/laeuft; Anforderungen, Preview und Roundtrip geprueft. | OFFEN |
| 25 | Ariadne kontrolliert einsetzen. | Feste Evaluatoren/Budgets, negative Arme erhalten; Nominierung ist keine Promotion. | OFFEN |
| 26 | Budgets, Kosten und Not-Aus im ganzen Pfad pruefen. | Effektgrenzen verbindlich; Settings loeschen weder Ledger noch Evidenz. | OFFEN |
| 27 | Produktgedaechtnis und wiederverwendbare Skills nutzen. | Herkunft/Revision; keine Wiederverwendung alter Rechte oder Geheimnisse. | OFFEN |
| 28 | Frontend mit Mission, Fortschritt und geplanter Arbeit verbinden. | Gleicher Kernel-Zustand; Reconnect dupliziert nichts; bestehender Scheduler. | OFFEN |
| 29 | Integrations-/Plattformmatrix schliessen. | Legacy-, Fehler-, Installations-, Provider- und GUI-Tests mit benannten Skips. | TEIL: 242 isolierte Modul-/Routingproben; Gesamtmatrix offen. |
| 30 | End-to-End-Abnahme und Owner-Freigabe. | Echter Benutzerauftrag bis verifiziertem Ergebnis; danach Review/Freigabe. | OFFEN |

Die Reihenfolge ist produktseitig abhaengig: Basis/Start vor Projekt-/Runtime-
Aufbau, diese vor Dispatch/Policy, diese vor effektvollen Werkzeugen, diese vor
Renovation/Genesis/Ariadne und schliesslich System-/Release-Abnahme. Die kleinen
reinen Reparaturen 07 und 11-16 sind isoliert vom eingefrorenen Integrationsblocker.

## Gelieferte Pakete

[Runtime-Replay](work-packets/G1-IKARUS-REPLAY-20260911.md) ist in
97a2b54a8beaf289605123ad14b8165ff91b8838 auf der bestehenden Linie committed.
103 Modultests wurden in dieser Fortsetzung erneut ausgefuehrt. Decoder/Replay
ist noch keine echte Provider- oder Mission-Wiederaufnahme.

[Literal-Intent-Grenze](work-packets/G1-IKARUS-LITERAL-20260911.md) sichert das
bestehende may_act und seinen vorhandenen Shell-Dispatch ab. Baseline: 75 der
124 neuen Predicate-Proben scheitern. Reparatur: 124 bestanden; dazu 15
Routing-Seam-Proben mit kontrollierten Abhaengigkeiten. Insgesamt 242 Tests
bestanden bei drei Hash-Seeds unter Linux/CPython 3.13.5. Drei absichtlich
entfernte Schutzpruefungen wurden von den Tests erkannt. 2,640 erzeugte
Kombinationen zeigten keine neu erlaubte Aktion; keine allgemeine Sprachgarantie.

Die lokale Umgebung hatte keine DNS-Verbindung fuer git clone. Quelltext wurde
ueber den GitHub-Connector gelesen und soweit vollstaendig kopiert gegen Git-
Blobs geprueft. Die Routingproben laden genau drei gelesene Shell-Funktionen,
nicht das initialisierte Gesamtpaket. Keine Aussage ueber System-CI, echte
Provider, Windows/macOS, HTTP, GUI oder vollstaendige Legacy-Tests.

## Integration und Rollback

Keine neue Remote-Branch, kein Force-Push und keine Aenderung am eingefrorenen
archive/legacy-20260830. Kein pauschaler Merge der divergenten Ikarus-Linie.
main hat neuere Paketpfade und Sprachunterstuetzung; beim selektiven Transfer
muessen nur die Aenderungen portiert werden, nicht die alten Dateien kopiert.
Kernel, Policy, Evaluator, Ledger und Owner-Promotion bleiben unveraendert.

Die naechste Produktabnahme bleibt der reale Pfad Auftrag -> freigegebenes Tool
-> kanonische Ereignisse -> nachweisbares Ergebnis -> Anzeige, einschliesslich
Fehler, Abbruch und Neustart. Unabhaengiger Review und main-Integration bleiben
offen. Rollback erfolgt durch selektives Revert der Pakete, nicht Branch-Reset.
