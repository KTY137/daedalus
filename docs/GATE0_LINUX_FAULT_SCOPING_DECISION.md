# Gate 0 — Scoping-Entscheidung: Linux-Fault-Spalte auf Container-Ebene

Status: ANGENOMMEN (Owner, Konversation 2026-08-17 ~21:18, „ich akzeptiere
alles mach ma" auf das Schlusspaket, das diese Entscheidung explizit als
Punkt 2c benannte).

## Entscheidung

Die vier Fault-Szenarien, die einen Docker-Daemon INNERHALB des Containers
verlangen würden (`docker-cli-unavailable`-blocked im Lauf
`runs/gate0-linux-container-fault/`), werden für den Gate-0-Exit auf
**Container-Ebene gescoped**: Ihre `blocked`-Beobachtungen mit benanntem
Grund („Socket-Mount von Policy verboten") sind die akzeptierte Evidenz —
das Verbot des Docker-Socket-Mounts ist selbst fail-closed-Verhalten der
Sandbox-Policy und wird nicht für einen Testlauf aufgeweicht.

## Was das NICHT bedeutet

- Kein Szenario wird gelöscht oder als passed umdeklariert; die vier Zeilen
  bleiben als `blocked` mit Grund in der Matrix sichtbar.
- Ein späterer Lauf auf einem echten Linux-Host (RTX-Bench oder CI) bleibt
  möglich und wünschenswert; er ERSETZT diese Scoping-Entscheidung, sobald
  er existiert, und wird als eigene Evidenz gelandet.

## Rollback

Diese Datei löschen und einen Linux-Host-Lauf als Evidenz verlangen —
keine Code-Änderung nötig, da nichts aufgeweicht wurde.
