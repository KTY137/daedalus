# Kartograph → other lanes, 2026-08-26

What the map lane needs from files it does not own, and what it now consumes
from files other lanes do own.

## → Rahmen (`cockpit/Cockpit.tsx`)

**The counts line under the module name wraps mid-figure.** `stageHeaderInner`
renders one run-on sentence:

```
<b>{nh.direct}</b> direkt · <b>{nh.reach}</b> über zwei Ebenen
<span className="muted"> · {fan_in} Importeure · {loc} Zeilen · Hitze {score}</span>
```

In the reading rail that breaks between a number and its unit — "2807 /
Zeilen" — which reads as a broken number. `stage.css` now gives the `.muted`
run its own line, a smaller size and a hanging separator, which stops the worst
of it, but the real fix is markup: the caption wants to be a row of labelled
figures rather than a sentence, e.g.

```tsx
<dl className="stage-figures">
  <div><dt>Importeure</dt><dd>{nh.focusNode.fan_in}</dd></div>
  <div><dt>Zeilen</dt><dd>{nh.focusNode.loc}</dd></div>
  <div><dt>Hitze</dt><dd>{nh.focusNode.score.toFixed(1)}</dd></div>
</dl>
```

If that lands, drop the `.stage-counts .muted` block from `stage.css` and I
will style `.stage-figures` instead.

**The stage is now a two-part composition** (`.stage-rail` + `.stage-field`),
not one absolute canvas with a floating header. `Stage` still takes `header`,
`overlay` and `panel` with the same meanings; `header` is rendered at the top
of the rail rather than over the drawing, and `overlay`/`panel` still float
over the field. Nothing in `Cockpit.tsx` needs to change for that.

## → Material (`theme/presets.ts`)

The stage now consumes four of the new knobs. Values a preset does not carry
fall back defensively (`parallax` → 1, `depthFog` → 0.35, `depthBlur` → 0), so
nothing breaks, but the knobs are dead until the presets set them.

| Knob | What the stage does with it |
| --- | --- |
| `stage.parallax` | scales the per-plane camera lag: focus +9 %, level 1 fixed, level 2 −15 % of the pan, all × this. `0` = a flat diagram that still pans. |
| `stage.depthFog` | fades the level-2 **glyph** toward the room. Never applied to a label — an opacity on text is a contrast reduction `tools/audit.mjs` cannot see, so the label's recession is the designed `--ink2` step instead. |
| `stage.depthBlur` | depth of field on level-2 glyphs only, gated by `data-dof` so `0` costs no filter layer. |
| `colors.heat[1..4]` | the heat rank's three-step mark takes `--heat-2`, `--heat-3`, `--heat-5`. |
| `form.elevationPane` | read as a NUMBER (0…4) and turned into an SVG `feDropShadow` on the near planes. `--shadow-pane` itself cannot be used: it is a multi-layer box-shadow with an `inset` component, and no SVG mark can wear one. At `0` (Depesche) the filter is not emitted at all. |

One standing request, and one withdrawn:

1. **Keep the heat ramp distinguishable from `accent`.** Still live, and the
   re-hued ramps were verified by eye in Kammer, Sternkarte, Nachtfenster and
   Leitstand on 2026-08-26: the focus node reads as the focus in all four.
2. **Withdrawn: the `backboneOnly` request.** Your ruling stands and, measured,
   the lever it asked about is nearly empty. At `attempt.py` on `agent_env`,
   Leitstand draws 41 edges: **11 focus, 27 backbone, 3 context.** Flipping
   `backboneOnly` to `true` would remove three of forty-one. The reason is in
   `graph.ts`: the backbone is every edge that TOUCHES the focus or a direct
   neighbour, not only the edges between them, so on a two-level neighbourhood
   almost everything is backbone by definition. The density at rest is
   structure, not noise, and it had to be answered by routing instead —
   see "What changed on the stage" below.

`colors.plane[]` is **not** used by the map, and this is a measured blocker
rather than a missing feature. `/api/structure` returns an import graph:
`StructureGraphNode` carries `id`, `fan_in`, `loc` and `score`, and no node or
edge in the payload says which of Code / Type / Data / Knowledge it belongs to.
Every node the map can draw is a Python module, i.e. the code plane. A
four-plane view cannot be drawn honestly from a single-plane payload; painting
one in four plane colours would be a caption claiming coverage the data does
not have. The tokens are correct and ready — the blocker is upstream, in what
`/api/structure` emits.

## → Bewegung (`motion/*`)

The cockpit now imports the motion vocabulary: `cockpit/stage/camera.ts` uses
`useReducedMotionPref`, `DURATION_MS.move` and `EASE.glass` for the camera
glide, and the same preference switches the parallax off. Direct manipulation
(wheel, drag) stays un-eased on purpose — easing under the reader's own hand
reads as lag, not as calm.

## What changed on the stage, 2026-08-26 (second pass)

For anyone reading the map's markup from another lane:

- `.stage` now carries `data-lift="on"` when the theme's `form.elevationPane`
  is above 0, alongside the existing `data-mode` and `data-dof`.
- the rail has a fourth block, `.stage-reading`, between the legend and the
  controls. It reads the node under the pointer or under the arrow keys, and
  at rest it reads the composition (how many of each relation were drawn, or
  in the ordered view how the heat rank was cut). It is hidden below 900px
  along with the legend.
- `.stage-tools` gained `.stage-tools-note`, one line saying what the selected
  representation is.
- edge corridors are laid out by a channel router over the whole edge set
  (`edgeLanes` in `stage/paths.ts`) rather than a per-edge hash.

## Left undone in this round

- **The four-plane view is blocked upstream, not unimplemented.** The ordered
  view is four columns of the *relation to the focus* (Importeure / Fokus /
  Importe / Zweite Ebene), sorted within each column by the hot-list `score`
  the cards print as "Hitze". It is not the four Project-Twin planes and must
  not be read as them. When `/api/structure` can say which plane a node belongs
  to, the column set is the natural place for it — the layout already emits
  labelled columns with their own counts.
- The card layout drops the second level entirely below ~940px of field width
  (four columns of ~110px cards left 57px gutters, and the elbows crossing them
  measured 3px apart at 1024px). The dropped neighbours are still counted in
  `hidden2` and still reachable through "Alle auflisten", but a wide window and
  a narrow one now show a different number of planes.
- Level-2 nodes in the radial layouts still land wherever the outer ellipse has
  room, so the far field is unbalanced on a focus with many distant neighbours.
- One elbow corridor pair at 1440px still comes within 9.5px of another; the
  router keeps a corridor inside its own gutter rather than drawing an elbow
  that doubles back, and that edge had nowhere else to go.

Iron Plan: ALIGNED · Iron Gate: 0 · read surface over the canonical kernel;
no effectful entrypoint touched.
