# Gallery round — shared contract (2026-08-24)

Six designers, six genuinely different designs of the SAME product moment. The owner has rejected
five rounds as "AI slop / cluttered / underscoped / all the same"; this round exists to break a
design local minimum, so **divergence is the deliverable**. Each design must be unmistakably
different from the other five in COMPOSITION, not just palette.

## The product moment every design must show (same content, invent nothing else)

Daedalus, project "Daedalus", revision r7c2e1a, Gate 0. On screen simultaneously:

1. **The conversation with Ikarus** (this exact exchange, German):
   - Du: "Was passiert, wenn ich enforce.write_root() ändere?"
   - Ikarus: "Direkt betroffen sind 23 Aufrufer in 9 Modulen; über zwei Ebenen 61 Dateien. Der
     teuerste Pfad läuft über Attempt.run() in die Gates." — stamped GEMESSEN, citing
     `Attempt.run()` and `enforce.write_root()` inline.
2. **The stage**: the neighbourhood of `enforce.write_root()` — 6 named level-1 nodes
   (Attempt.run(), vet.py, promote_sealed(), Ledger.charge(), EvidencePacket.seal(),
   tool-allowances.json), ~8 dimmer level-2 nodes, one dashed unverified edge. Header numbers:
   17 direkt · 61 über zwei Ebenen. HOW the stage renders (3D room, flat map, table hybrid,
   arc diagram, columns…) is the designer's choice — but every label legible, nothing clipped,
   no text over a body.
3. **The decision**: "Attempt 18 wartet auf dich — auf der Claude-Lane fertig, für die Gates
   vorgeschlagen. Beides widerrufbar." with Annehmen / Ablehnen / Warum.
4. **State, once**: Lane Claude · api.anthropic.com · $0.41 von $2.00 heute · 2 zurückgehalten
   (secret-bearing paths) · Kill switch scharf · 3 live · 17 done. Plus projects Daedalus (149),
   TCT scan planner (62), Lehrstuhl wiki (—), and the six mission stages Intent✓ Plan✓ Build●
   Gates· Delivery· Digestion·.

## Owner's taste, distilled from five rounds (binding)

- Rejected: sci-fi HUD, radar, scanlines, neon, purple/pink AI palettes, status pills, four-tile
  metric rows, suggestion chips, flat dark card grids, doctrine copy in chrome ("Ikarus proposes.
  You decide." as decoration), stray provenance letters, grey placeholder 3D, dead pages without
  a visible input, walls of explanation text, Inter-by-default.
- Loved at some point: visionOS glass over a dark room (round 2), Keynote's calm and air,
  Sequoia's panel composition, the amber-lit pearl material of Aurora i1, a real chat with a
  blinking caret.
- The oscillation to avoid: cluttered ↔ underscoped. Rule: one region carries full weight, one
  half, the rest rests — and EVERYTHING is operable-looking (visible input, visible controls).

## Hard rules (each design, measured by the shooter)

- 1440×900, static HTML, one self-contained file, system font stack only (no webfonts — the
  screenshot sandbox has no egress), inline SVG/CSS for the stage, no JS frameworks (vanilla JS
  allowed for nothing-critical flourishes; the page must render complete without JS).
- Sentence case; AA contrast; no horizontal overflow; no text clipped or overlapped; the chat
  input visible with caret; ≥ 44 px controls.
- German UI copy matching the content above; monospace only for identifiers.
- One accent colour family; no second accent. No emoji as icons.

## File contract

Write exactly one file: `C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/c46c7615-e718-4fa6-8756-9c4b7ccdd61b/scratchpad/gallery/<key>.html`
(your key is in your prompt). First line a comment: `<!-- <key> · <design name> · <one-line thesis> -->`.
Do not touch any other file. Do not read other designers' files.
