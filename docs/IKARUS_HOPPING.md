# Ikarus: Genesis, Tensor-Kernel und Hopping

Stand: G1-IKARUS-HOPPING-01, 11. September 2026. Der neue Code verbindet die
bestehenden Werkzeuge; er ist **kein automatischer Wechsel der laufenden Instanz**.
Quellcodeänderungen müssen in der verwendeten Installation geladen werden; ein
bereits gebauter Desktop-Installer erhält sie nicht durch einen Git-Pull.

## Start und ausdrückliche Werkzeugfreigaben

Aus der Quellcodeinstallation den bisherigen Web-Einstieg starten:

```powershell
python -m daedalus.interfaces.cli.entry web
```

Im Ikarus-Chat, nach Auswahl eines registrierten Projekts:

```text
/computer setup
/computer status
/computer enable daedalus
/computer enable genesis confirm-builds
/computer enable ariadne confirm-campaigns
/computer run Build a local task board with search
```

`setup` gewährt keine Werkzeuge. Die Freigaben sind getrennt: `daedalus` ist
lesend, `genesis` baut isolierte neue Kandidaten, `ariadne` bewertet vorgeschlagene
Änderungen am registrierten Projekt. Bei einem entfernten Planner verlangt die
lesende Projektfreigabe zusätzlich die angezeigte `confirm-remote`-Bestätigung.
Die bestehende Planner- und Egress-Policy gilt auch für die neuen Ergebnisse.
Der Web-Einstieg registriert die beiden Runner; andere Prozesse ohne diese
Komposition melden die Werkzeuge als nicht verfügbar.

Genesis unterstützt die bereits vorhandenen Blueprints (CLI/Web-Item-Collection
und Web-Kanban), keine beliebigen großen Anwendungen und keine Veröffentlichung.
Jeder neue vollständige Genesis-Roundtrip führt zusätzlich den vorhandenen
Sparse-Relation-Tensor-Compiler auf **demselben** Kandidaten-Forest/Fourfold aus.
Eine falsche Revision, partielle Endpunkt-Ebene oder ein Compilerfehler kann nicht
als grüne Tensor-Prüfung durchgehen. Die Beobachtung wird im kanonischen
EvidencePacket gespeichert. Dies belegt die Repräsentation, nicht bessere
Softwarequalität oder eine Überlegenheit gegenüber gewöhnlicher Suche.

## Owner-Testprofil für Ariadne

Standardmäßig bleibt Ariadne beim bisherigen Exaktvergleich. Für `owner-tests`
legt der Owner ein festes Testprofil **außerhalb** des Projektbaums an. Das
Sprachmodell darf weder dessen Befehl noch Pfad oder Freigaben bestimmen.
Den projektbezogenen Speicherort aus derselben Installation ermitteln:

```powershell
python -c "from daedalus.spine.killswitch import control_root; from pathlib import Path; print(control_root(Path(r'C:\Pfad\zu\daedalus').resolve()) / 'ariadne-test-evaluator.json')"
```

Der Pfad ist ein Beispiel und wird durch das tatsächlich registrierte Repository
ersetzt. Im ausgegebenen externen Control-Root lautet ein Profil beispielsweise:

```json
{
  "schema": "daedalus-owner-ariadne-evaluator/1",
  "argv": ["python", "-m", "pytest", "-q", "tests"],
  "timeout_s": 30,
  "test_roots": ["tests/"],
  "acknowledge_unsandboxed_execution": true
}
```

**Das letzte Feld ist eine reale Risiko-Bestätigung:** Der bestehende
Test-Evaluator führt Kandidaten-Python aus, hat keine unabhängige Vertrauensgrenze
gegen manipulierte Testberichte und keine Netzwerk-Sperre für dieses Kind.
Nur auf einem geeigneten isolierten Entwicklungsrechner mit unkritischer
Umgebung verwenden; dies ist keine Freigabe für nicht vertrauenswürdigen Code.
Das Profil nicht durch Ikarus oder Kandidatencode schreiben lassen. Fehlendes,
verlinktes, ungültiges oder im Projekt gelegenes Profil wird abgelehnt; ein
angeforderter Testlauf fällt niemals still auf Exaktvergleich zurück.

Die bestehende Kampagne vergleicht Baseline, Negativkontrolle und Reparatur mit
festem Evaluator und gleichen Budgets. Baseline und Reparatur müssen im
Testmodus bestehen; die Negativkontrolle muss scheitern. Ein grüner Lauf ist
noch kein Nachweis einer Verbesserung oder einer sicheren Selbstaktivierung.

## Hopping-Auftrag

```text
/computer hop Verbessere den Parser ohne dessen öffentliches Verhalten zu ändern
```

Dieser Befehl benutzt die vorhandene Computer-Mission. Für diese Mission werden
nur lesende Daedalus-Werkzeuge und Ariadne angeboten. Ariadne wird zwingend mit
`evaluation=owner-tests` aufgerufen; direkter Dateizugriff, Terminal, Browser,
Genesis und Veröffentlichung stehen in diesem Modus nicht zur Verfügung.
Vorhandene Kill-Switch-, Laufzeit-, Lease- und Abbruchprüfungen bleiben aktiv,
auch während der verschachtelten Kampagnen- und Genesis-Prozesse.

Das Ergebnis nennt Kandidaten- und Quittungshashes, Testmodus, unveränderten oder
veralteten HEAD und konkrete Hopping-Blocker. `activation_permitted` bleibt
**false**. Die vorhandene Ariadne-Reparatur erzeugt einen isolierten Kandidaten,
aber noch kein vollständiges startbares Kernel-Abbild. Sie überschreibt weder
den aktiven Checkout noch ihre Prüfer, Policy oder Freigabemechanismen.

Für einen tatsächlichen Hop fehlen ein vollständiges revisionsgebundenes
Kernel-Abbild, unabhängig kontrollierte Prüfung samt Kindprozess-Isolation,
eine versiegelte Owner-Freigabe und ein getesteter Versionswechsel mit
Zustandsübergabe, Healthcheck und Rollback. Ein endloser oder unbeaufsichtigter
Selbstwechsel ist durch dieses Paket nicht aktiviert. Rücknahme der neuen
Werkzeugfreigaben:

```text
/computer disable genesis
/computer disable ariadne
```
