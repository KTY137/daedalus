# Ikarus als Computerassistent

Ikarus kann mehrstufige Computeraufgaben mit dem lokalen Modell planen und
Werkzeuge ausführen. Jede Aktion läuft durch die Daedalus-Policy und erhält
gespeicherte Ausführungsbelege. In v0.1.6 sind alle dateipfadbasierten
Werkzeuge vor der Freigabe zentral gesperrt; Details stehen unten.

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
Werkzeuge, die aktuelle Konfiguration und die v0.1.6-Pfadsperre. Gespeicherte
ältere Grants können die gesperrten Werkzeuge nicht wieder aktivieren.

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
brauchen den laufenden File-Bridge-Watcher derselben Installation. `run-due`
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

## Temporäre v0.1.6-Pfadsperre

`file.list`, `file.read`, `file.write`, `file.mkdir`, `file.move`,
`vision.match` und `vision.changes` werden weder ausgeführt noch als
Capabilities angeboten. `vision.inspect` und `vision.ocr` akzeptieren nur eine
frische `observation_id` aus `desktop.observe`, keinen Dateipfad. Grund ist ein
reproduzierbares Race: Ein bereits geprüfter Unterordner konnte vor dem
eigentlichen Zugriff gegen einen Link oder Windows-Reparse-Point getauscht
werden. Die Sperre behauptet nicht, Pfadzugriffe sicher gemacht zu haben. Eine
spätere Freigabe braucht separat verifizierte, handle-relative und unter
Windows reparse-sichere I/O.

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
