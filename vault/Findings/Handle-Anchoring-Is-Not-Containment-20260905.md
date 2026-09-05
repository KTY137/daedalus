---
tags: [findings]
created: 2026-09-05
source: docs/work-packets/G1-IKARUS-24_HANDLE_ANCHORED_WORKSPACE_FILES.md
permalink: main/findings/handle-anchoring-is-not-containment-20260905
---

# Handle-Verankerung ist keine Containment-Garantie (G1-IKARUS-24)

**Artefakt (autoritativ):** `../../docs/work-packets/G1-IKARUS-24_HANDLE_ANCHORED_WORKSPACE_FILES.md` <!-- Link, nie Kopie -->
**Folgepacket:** `../../docs/work-packets/G1-IKARUS-25_FILE_TOOL_FENCE_LIFT.md`
**Code:** `../../daedalus/runtimes/computer_files.py`, `../../tests/runtimes/test_computer_files.py`

Einordnung: Der v0.1.6-Zaun sperrte alle Datei-Werkzeuge, weil `Path.resolve` plus spätere Pfad-Operation keine Write-Root-Grenze ist (Ancestor gegen Junction getauscht). Der neue Adapter öffnet jede Komponente relativ zum Eltern-Handle (`NtCreateFile` + `RootDirectory` + `FILE_OPEN_REPARSE_POINT`) und schließt damit das Link-Pflanzen. Die Reviews (Cerberus BLOCK, Odysseus mit ausgeführtem Escape) zeigten aber: das Verzeichnis-*Objekt* selbst kann bei `FILE_SHARE_ALL` aus dem Workspace hinausbewegt werden, und Read/List prüften gar nichts. Die Antwort ist Pinning: Handles ohne `FILE_SHARE_DELETE` verhindern auf Windows das Verschieben von Elternverzeichnis, Root und Vorfahren für die Dauer der Operation; dazu `policy.admit` und Secret-Floor im Adapter, Checkpoint und Identitätsprüfung für Beobachtungen, Replace-Hold mit Supersede per `FileRenameInformationEx`. POSIX hat keine Share-Modes; dort bleiben Effekte über den öffentlichen Einstieg verweigert.

Provenienz: MEASURED (Windows 11, `.venv` Python 3.13.14: 75 passed, 16/16 Mutationen; Sonden für Pinning und Hold im Session-Scratch, Ergebnisse im Packet) / INHERITED (Codex-Alpine-Messung des POSIX-Backends laut Packet-Doc).

Offene Prüfschritte:

- [ ] Cerberus-Bestätigungsverdikt an den Datei-Hash gebunden ins Packet übernehmen.
- [ ] Replace als atomares Compare-and-Swap gegen feindliche Substitution im Rename-Fenster: Einschränkung im Lift halten oder mit Crash-Evidenz schließen.
- [ ] Service-Verdrahtung (G1-IKARUS-25) mit Service-Ebene-Test „nichts außerhalb `policy.workspace`“ (liegt als xfail-strict vor).
- [ ] Netzlaufwerke, `subst`, macOS und Nicht-NTFS-Volumes bleiben ungemessen; Zaun dort halten oder Volume-Gate messen.
