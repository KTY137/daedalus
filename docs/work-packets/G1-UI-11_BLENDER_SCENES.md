# G1-UI-11 — Editable Blender scene collection

Packet ID: G1-UI-11
Artifact role: primary
Active gate: 1
Classification: ALIGNED
Owner: repository owner
Base revision: 61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0
Dependencies: G1-UI-10; master plan revision 12

## Primary acceptance claim

Six selected visual directions are delivered as real, editable Blender
projects with reproducible procedural sources and Blender-rendered previews:
Porcelain, Graphite Atelier, Spatial Daylight, Spatial Dusk, Spatial Studio and
Techno Forest. This is an offline presentation-asset delivery, not a runtime,
policy, graph-authority or promotion change.

## Scope

Owned paths are `docs/design/blender-scenes/`, the portable
`docs/design/Daedalus-Blender-Scenes.zip`, and this packet. Each scene includes
geometry, named materials, lights, camera, reproducible Python source and an
actual PNG render. Existing owner changes and application code are preserved.
Portable Blender lives outside the repository and is not shipped.

## Contracts and behavior

All projects use procedural materials without add-ons, external textures or
network access. Final and draft renders stay distinguishable. PNG textual and
EXIF metadata is stripped before publication while compressed IDAT pixel
streams remain byte-identical. Raw Blender logs remain local because they carry
machine-local paths and are excluded from both source control and the portable
archive. The archive has fixed metadata, a canonical member order and no
`logs`, `__pycache__` or Blender backup files.

The owner rejected the earlier spatial UI despite green functional tests. That
negative result remains recorded in G1-UI-10; passing scene verification does
not imply owner approval of the art direction or real-time performance.

## Acceptance matrix

- Six `.blend` files reopen with editable geometry, materials and an active
  camera, without missing linked libraries or external textures.
- Six 1600 × 1000 Cycles previews correspond to the verified projects.
- Combined `Daedalus-Scene-Collection.blend` reopens with all six scenes.
- `sanitize.py --check` validates all final and draft PNGs and their recorded
  final hashes; `package.py --check` recreates the archive byte-for-byte and
  validates CRC, privacy and membership.
- Draft renders and projects retain negative authoring evidence. No automatic
  merge or promotion occurs.

## Migration and rollback

There is no saved-state migration. Rollback removes this packet, the scene
directory and the portable ZIP. Local raw logs may remain as ignored evidence;
no existing application state needs conversion.

## Evidence, expected failures and review

Blender 4.5.13 LTS portable came from the official Windows x64 archive whose
published SHA-256 was checked before extraction:
`b5fdf800ce65fa2f209e8f68d02667e4d720fa1c42f247c72d1882ab04decba6`.

Authoring retained these negative findings: Windows archive extraction was
unexpectedly slow; the first Porcelain ribbon pinched; initial architecture
was distant and flat; Dusk's reflection was displaced from its visible sun;
Studio planting left the frame; draft output initially overwrote final
projects; collection assembly initially omitted unreferenced source texts; and
legacy compositor controls warned under Blender 4.5. The retained drafts and
procedural-source fixes make those outcomes inspectable.

Final local verification on 2026-09-05 reopened all six individual projects
and the combined collection. The finals use Cycles at 1600 × 1000, at most 64
samples, fixed seed 20260905, AgX and denoising on an NVIDIA GeForce MX330.
Measured per-scene build plus render times were 81.88 s, 191.41 s, 106.61 s,
66.70 s, 96.86 s and 151.38 s; these are local timings, not a controlled speed
comparison. Object, geometry and artifact hashes are in `verification.json`.

Independent release review found that all 12 PNGs carried Blender text/EXIF
metadata, including a local absolute workspace path, and that the first ZIP
also included raw logs. `sanitize.py` removed 144 metadata chunks while
asserting byte-identical IDAT streams. Final check: 12 PNGs, zero private
chunks or absolute paths. A clean Windows checkout then exposed mixed CRLF/LF
source bytes in the first archive. The complete scene-source subtree is now
pinned `-text`, and a fresh byte-stable checkout rebuilds the same payload on
every host. The deterministic ZIP contains 46 files, 19,859,546 bytes; CRC and
privacy checks pass; SHA-256 is
`35478e9793882aa2b341d1d661557d4f3e1cab08a795813a6e0f62a6cc682613`.

All six final previews were visually inspected, including corrected Dusk and
Studio compositions. No owner art-direction approval, animation, GLB export,
real-time rendering, provider execution or production release is claimed.
