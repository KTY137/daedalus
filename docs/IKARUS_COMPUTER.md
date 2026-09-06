# Ikarus als Computerassistent

Ikarus kann mehrstufige Computeraufgaben mit dem lokalen Modell planen und
Werkzeuge ausführen. Jede Aktion läuft durch die Daedalus-Policy und erhält
gespeicherte Ausführungsbelege. In v0.1.6 sind die Dateiwerkzeuge
über einen handle-verankerten Adapter wieder ausführbar; zentral gesperrt
bleiben das Ersetzen vorhandener Dateien und die pfadbasierten Vision-Formen.
Details und der offene Review-Stand stehen unten.

## Starten

Für einen Start aus diesem Quellcode im verwendeten Python-Environment:

```powershell
python -m pip install -e ".[computer]"
python -m playwright install chromium
python -m daedalus.interfaces.cli.entry web
```

Das Computer-Extra und Chromium wurden im Entwicklungsenvironment installiert.
Diese Installationsbefehle gelten für Quellcode- und Wheel-Umgebungen. Die
nativen v0.1.6-Desktop-Installer bündeln das optionale `computer`-Extra nicht;
betroffene Capture-, Vision-/OCR- und Browser-Capabilities werden dort als
nicht verfügbar gemeldet. Bereits gebaute Desktop-Anwendungen übernehmen
Quellcodeänderungen erst mit
einem neuen Build. Die Funktionen verwenden zunächst das lokale Ollama-Modell;
Ollama muss laufen und ein Chatmodell installiert haben. Die normale
Modellauswahl für Chat ändert die Computer-Policy nicht.

Im Ikarus-Chat:

```text
/computer setup
/computer status
```

Setup legt einen eigenen Arbeitsordner und die Steuerdaten an, aktiviert aber
zunächst kein Werkzeug. Status zeigt den Ordner, tatsächlich verfügbare
Werkzeuge, die aktuelle Konfiguration und die verbliebene v0.1.6-Pfadsperre.
Gespeicherte ältere Grants für die Dateiwerkzeuge werden mit der verengten
Sperre wieder wirksam; die weiterhin gesperrten Werkzeuge kann kein Grant
reaktivieren, weil die Sperre keine Grant-Frage ist.

## Notizen, Skills und Termine

Beispiele:

```text
/computer remember Antworte auf Deutsch und verwende für Tabellen das CSV-Format.
/computer notes
/computer skill off
/computer schedule 2026-09-06T18:00:00+02:00 Lies die erlaubte statische Statusseite.
/computer scheduled
/computer run-due
```

Das Datum ist ein Beispiel und muss in der Zukunft liegen. Automatische Termine
brauchen den laufenden File-Bridge-Watcher derselben Installation für genau
diesen Ordner (`python -m daedalus.file_bridge watch --repo-root <Ordner>`);
jede Antwort auf `schedule`, `queue`, `every`, `scheduled` und `run-due` sagt,
ob ein solcher Watcher gerade läuft, und nennt sonst den Startbefehl. `run-due`
prüft manuell; pro Durchlauf wird höchstens ein fälliger Auftrag ausgeführt.
Einzelne Termine verfallen 24 Stunden nach Fälligkeit. Geänderte
Policy, Abbruch oder unklare Ausführung führen zur Sperre; unterbrochene Effekte
werden nicht blind wiederholt. Die Anwendung muss für automatische Ausführung
laufen.

## Mehr selbstständige Aufgabenbearbeitung

Ikarus kann einen Arbeitsplan festhalten und lokal fehlerhafte Modellantworten
korrigieren, bevor ein Werkzeug startet. Planung und Korrektur verbrauchen
dieselben freigegebenen Aufruf- und Zeitbudgets wie die eigentliche Aufgabe.
Bei wiederholt unveränderten Beobachtungen meldet er Stillstand. Ein abgelehntes
Werkzeug oder eine unklare Wirkung wird nicht automatisch wiederholt.

Der Bericht jeder Mission nennt den Planner, der die Schritte vorgeschlagen hat, und ob die Beobachtungen den Rechner verlassen haben (`Planner: … · Kontext hat den Rechner verlassen: ja|nein`); dieselben Angaben stehen in `/computer task` und `/computer tasks`. Ein entfernter Planner (`planner_provider` mit `allow_remote_context: true`) ist eine ausdrückliche Owner-Konfiguration; die Zeile macht sie nachträglich sichtbar und ersetzt keine Freigabe.

Der Planner wird mit `/computer planner <ollama_http|codex_cli|claude_code_cli|deepseek> [Modell]`
gewählt. Ein entfernter Anbieter wird erst nach einer sichtbaren Warnung und der
ausdrücklichen Wiederholung mit `confirm-remote` gespeichert; die Bestätigung gilt
nur für diesen Befehl. Beobachtungstexte verlassen dann den Rechner. Unabhängig vom
Planner prüft die Secret-Floor jede Beobachtung und jeden Prompt: bei einem Treffer
endet die Mission als `blocked`, bevor ein Planner die Beobachtung sieht; die
Beobachtung selbst bleibt lokal als Evidenz erhalten. Das lokale Modell braucht keine
Bestätigung. Gemessen am 2026-09-06: Codex als Planner beendete die Messmission als
erste mit `finish`, das lokale 7B-Modell liest, schließt aber nicht ab.

```text
/computer queue Öffne die freigegebene Statusseite und lies den aktuellen Status.
/computer every 30m 4 Öffne die freigegebene Statusseite und lies den aktuellen Status.
/computer scheduled
/computer cancel <schedule_id>
/computer tasks
/computer task <mission_id>
```

`queue` reiht einen sofort fälligen Auftrag dauerhaft ein. `every 30m 4`
autorisiert vier Ausführungen mit mindestens 30 Minuten Abstand. Unterstützte
Einheiten sind `s`, `m`, `h` und `d`; das Intervall beträgt mindestens eine
Minute, die Anzahl 2 bis 1.000. Die erste Ausführung wird nach dem Intervall
fällig. Die nächste wird erst nach nachgewiesen erfolgreicher Werkzeugausführung
eingeplant; Fehlversuche, unbestätigte Wirkungen oder Abbrüche stoppen die Serie.
Versäumte Intervalle werden nicht in einem Schub nachgeholt.

Die Antwort zeigt die `schedule_id`. Ein Abbruch unter dieser ID gilt für die
ganze Serie, einschließlich eines laufenden Auftrags. Er wird an den nächsten
Prüfpunkten wirksam und kann bereits ausgeführte Aktionen nicht zurücknehmen.
Die bestehenden Watcher- und Policy-Voraussetzungen gelten auch für die Queue;
es wurde kein weiterer Hintergrunddienst installiert.

`tasks` zeigt eine Seite der jüngsten Missionen. Wenn `has_more` wahr ist,
zeigt `/computer tasks <next_cursor>` die ältere Seite. `task` prüft die
gespeicherten Belege einer einzelnen Mission. Ein offener Eintrag bedeutet
"ausstehend oder unterbrochen" und ist kein Beweis für einen noch laufenden
Prozess. Historische Einträge ohne zugeordneten Arbeitsbereich bleiben als
`legacy_unscoped` gekennzeichnet. Die
[Autonomie-Arbeitspakete](work-packets/G1-IKARUS-23_AUTONOMY_COMMANDS.md)
enthalten Prüfungen und bekannte Grenzen.

Notizen bleiben über Neustarts erhalten. `/computer forget <note_id>` nimmt
eine Notiz aus dem aktiven Kontext; ihre Historie bleibt erhalten. Bis zu
20 Notizen mit insgesamt 8.000 Zeichen sind möglich. Die Auswahl neuer lokaler
Skill-Ordner ist in v0.1.6 gesperrt, weil auch sie einen pfadbasierten Leseweg
öffnen würde. Bereits gespeicherte Skill-Metadaten werden nur als nicht
verfügbar angezeigt und können mit `/computer skill off` entfernt werden.

## Dateiwerkzeuge und die verbleibende v0.1.6-Sperre

`file.list`, `file.read`, `file.mkdir`, `file.move` und `file.write` für
neue Dateien laufen seit G1-IKARUS-24/25 über einen handle-verankerten
Adapter: Jede Pfadkomponente wird relativ zum geprüften Eltern-Handle
geöffnet, Links, Junctions und Hardlinks werden verweigert, und unter
Windows werden Elternverzeichnis, Arbeitsordner und Vorfahren für die Dauer
der Operation gegen Verschieben gesperrt. Lesen und Auflisten laufen durch
denselben Prüfpunkt wie Effekte; die Secret-Floor gilt für Lesen, Schreiben
und Verschieben. Dateiwerkzeuge sind in diesem Release nur unter Windows
verfügbar, andere Hosts melden sie als nicht verfügbar. Details und Grenzen:
[G1-IKARUS-24](work-packets/G1-IKARUS-24_HANDLE_ANCHORED_WORKSPACE_FILES.md),
[G1-IKARUS-25](work-packets/G1-IKARUS-25_FILE_TOOL_FENCE_LIFT.md).
Stand 2026-09-05 abends: Die unabhängige Phase-2-Review dieses Lifts stand um
17:40 auf **BLOCK** (F1: ein nach dem Effekt beobachteter Abbruch wurde als
„kein Effekt" verbucht); nach den test-first-Reparaturen und einer
adversarischen Verifikation lautet die Bestätigung um 20:44
**PASS-WITH-FINDINGS**, gebunden an `computer.py` `81931eb9…`,
`kernel/policy/computer.py` `1b3bc7e2…`, `computer_files.py` `7120cf2a…`.
Akzeptierte Residuen: POSIX-Lesen/Listen nur vom Service gesperrt (F4, mit
dem latenten POSIX-Rename-Befund N-1 als Grund), Failure-Record filtert Inhalt,
nicht Pfadnamen (O-2), Fehlertext der Antwort ungefiltert, ohne Datei-Bytes
(O-3). Kein Merge, keine Promotion; die Review spricht nur über Receipts und
Zaun.

Gesperrt bleiben: das Ersetzen einer vorhandenen Datei (`file.write` mit
`expected_sha256`), bis das Zwei-Rename-Ersetzungsprotokoll eine
service-eigene Absturz-Reconciliation hat, sowie `vision.match`,
`vision.changes` und jede Pfadform von `vision.inspect`/`vision.ocr`; diese
akzeptieren nur eine frische `observation_id` aus `desktop.observe`. Grund
war ein reproduzierbares Race: Ein bereits geprüfter Unterordner konnte vor
dem eigentlichen Zugriff gegen einen Link oder Windows-Reparse-Point getauscht
werden; der Adapter schließt genau dieses Fenster, die Sperre der Restfälle
behauptet nicht mehr als das.

## Programme und Browser

Programme, Desktop-Eingaben und Browser-Ursprünge werden über
[`/computer configure`](IKARUS_COMPUTER_CONFIGURATION.md) in der vollständigen
Konfiguration freigegeben. Desktop-Beobachtungen können anschließend über ihre
flüchtige `observation_id` direkt an OpenCV und OCR übergeben werden. Klicks
brauchen eine frische Beobachtung
des freigegebenen Vordergrundfensters.

Der aktuelle Browser unterstützt isolierte statische Seiten, Lesen, Textfelder
und erlaubte Links. JavaScript-Webapps, Formularabsenden und Downloads sind
noch nicht verfügbar. Es gibt keinen uneingeschränkten Terminalzugang. Die
native Windows-Eingabe ist implementiert, aber noch nicht gegen ein echtes
Vordergrundprogramm geprüft. Beliebige Programmabläufe oder eine vollständige
Hermes-Funktionsgleichheit sind damit nicht nachgewiesen.

Die gemessenen Ergebnisse, Fehlerfälle und Tests stehen im
[Arbeitspaket](work-packets/G1-IKARUS-COMPUTER-01.md). Ein früherer lokaler
Entwicklungstest mit Qwen2.5-Coder 7B hat Schreiben und Lesen tatsächlich
ausgeführt; er ist nach dem Race-Befund nur historische Negativ- und
Integrations-Evidenz, keine freigegebene v0.1.6-Dateifunktion. Eine
Modellantwort allein gilt nicht als Erfolgsbeweis.
