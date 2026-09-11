# Daedalus — Spatial studies

Sechs echte, bearbeitbare Blender-Szenen. `index.html` öffnet die lokale
Vorschaugalerie. Die PNGs sind Blender-Renderings der mitgelieferten Projekte.

[Alle sechs Szenen in einem Blender-Projekt](blend/Daedalus-Scene-Collection.blend).
Oben rechts in Blender über das Scene-Menü zwischen den Umgebungen wechseln.

| Szene | Projekt | Vorschau |
|---|---|---|
| Porcelain — durchgehendes Glasband im hellen Studio | [porcelain.blend](blend/porcelain.blend) | [PNG](renders/porcelain.png) |
| Graphite Atelier — Rauchglas, Titan, Lichtkontakte | [graphite.blend](blend/graphite.blend) | [PNG](renders/graphite.png) |
| Spatial Daylight — Steinbogen, Meer und Morgenlicht | [daylight.blend](blend/daylight.blend) | [PNG](renders/daylight.png) |
| Spatial Dusk — Abendhimmel und verdecktes Amberlicht | [dusk.blend](blend/dusk.blend) | [PNG](renders/dusk.png) |
| Spatial Studio — gestaffelte Galerie mit Olivenbäumen | [studio.blend](blend/studio.blend) | [PNG](renders/studio.png) |
| Techno Forest — verzweigte Bäume, Lichtfasern, Nebel | [techno-forest.blend](blend/techno-forest.blend) | [PNG](renders/techno-forest.png) |

## Öffnen und bearbeiten

Blender 4.5 LTS verwenden, `.blend` öffnen. **Numpad 0** zeigt die Kamera,
**F12** rendert. Architektur, Skulpturen, Licht und Kameras sind in benannten
Collections organisiert. Materialien lassen sich im Shader Editor bearbeiten.
Die Szenen benötigen keine Add-ons, externen Texturen oder Onlineverbindung.
Die Python-Quellen sind zusätzlich als Textblöcke in jedem Projekt enthalten;
zum Öffnen müssen keine Skripte automatisch ausgeführt werden.

Glas: Base Color verändert die Tönung, Roughness die Mattierung und IOR die
Brechung. Area Lights steuern Helligkeit, Lichtfarbe und Spiegelungen.
Architektur: World-Nodes steuern Horizont- und Himmelsfarben.
Forest: Emission Strength steuert die Lichtfasern, der Volume-Shader den Nebel.

## Reproduzierbar bauen

Alle Szenen entstehen aus `scripts/` mit einem festen Seed. Aus diesem Ordner:

```powershell
$blender = "$env:LOCALAPPDATA/Codex/Tools/blender-4.5.13-windows-x64/blender.exe"
& $blender --background --python scripts/build.py -- --scene porcelain --width 1600 --samples 64
```

Weitere IDs: `graphite`, `daylight`, `dusk`, `studio`, `techno-forest`.
`--device CPU` erzwingt CPU-Rendering. `--draft --width 720 --samples 20`
schreibt kleinere Vorschauen nach `drafts/` und Entwurfsprojekte nach
`drafts/blend/`; finale Projekte bleiben erhalten. `--no-render` erstellt nur das
Projekt. Das Skript überschreibt ausschließlich die gleichnamige Szene im
gewählten Ausgabeordner; `--output PFAD` erlaubt ein separates Ziel.

## Inhalt und Grenzen

- `blend/`: komprimierte, editierbare Projekte.
- `renders/`: finale PNGs und pro Szene gemessene Renderdaten.
- `scripts/`: vollständige prozedurale Quellen.
- `drafts/`: behaltene Entwürfe und frühere Renderstände.
- `logs/`: lokal behaltene Ausführungsprotokolle. Sie bleiben wegen der von
  Blender geschriebenen maschinenlokalen Pfade aus Quellkontrolle und ZIP.
- `verification.json`: Prüfung der erneut geöffneten Projekte.

Daraus erzeugte WebP-Umgebungen kann der Theme Editor als statische Kulisse
anzeigen. Animation, GLB-Export und Echtzeit-3D sind nicht Bestandteil dieses
Pakets. Die Module im Graphite Atelier sind
dekorative Skulpturen und stellen keinen aktuellen Projektzustand dar.

Vor dem Packen entfernt `scripts/sanitize.py` Text- und EXIF-Metadaten aus den
PNGs, ohne deren komprimierte IDAT-Pixelströme zu verändern. Der Aufruf
`python scripts/package.py --check` prüft anschließend Hashes, Datenschutz,
CRC und den deterministischen ZIP-Inhalt.

Toolchain: [Blender 4.5 LTS](https://www.blender.org/releases/4-5/), Cycles,
AgX-Farbmanagement. Das portable Archiv wurde gegen die offizielle SHA-256-Liste
geprüft. Die tatsächliche Blender-Version und Messwerte stehen in den JSONs.
