/**
 * What a Daedalus theme IS.
 *
 * Six designers drew the same product moment six ways (docs/design/prototypes/
 * gallery-2026-08-24) and the round asked for divergence in COMPOSITION, not
 * just palette. So a theme here is not a colour scheme with a nice name: it
 * carries the structural choices too — where the conversation sits, how the
 * stage draws a graph, whether the chrome is a bar, a rail or a masthead.
 *
 * That is the whole point. A palette-only theme system would have forced the
 * old "pick one of six and throw five away" decision anyway; this one lets all
 * six exist, and lets the owner build a seventh without another design round.
 *
 * Every field is editable in the Theme Studio. Nothing here reaches into data:
 * a theme cannot change a number, hide a withheld path, or make an inert
 * control look live. It decides how true things look, never whether they are.
 */

/** How the stage lays the code graph out. */
export type StageLayout =
  /** free force layout, depth by plane — the spatial node forest */
  | 'forest'
  /** the same force layout drawn as a star chart, labels along the arcs */
  | 'stars'
  /** rings of labelled cards around the focus — readable over beautiful */
  | 'cards'
  /** one axis, relations as arcs above it — the printed figure */
  | 'arcs';

/**
 * How the conversation page is laid out.
 *
 * It used to say where the conversation sat RELATIVE TO THE MAP — a card over
 * it, a drawer under it, a column beside it. The map is its own page since
 * 2026-08-25 and nothing floats over it any more, so only the two arrangements
 * that still describe something real survive. `card` and `drawer` are migrated
 * to `column` on read; a knob that no longer moves anything is worse than no
 * knob at all.
 */
export type ChatPlacement =
  /** the conversation with a side column for the map reference and the hot list */
  | 'column'
  /** one centred measure, everything stacked (Depesche) */
  | 'flow';

/** The top chrome. */
export type Chrome =
  /** one horizontal bar: projects left, state right */
  | 'bar'
  /** a vertical rail on the left, state in a right column */
  | 'rail'
  /** a centred masthead with rules above and below */
  | 'masthead';

/** The surface material panels are made of. */
export type Material =
  /** opaque fill, hairline border */
  | 'flat'
  /** backdrop blur + translucency */
  | 'glass'
  /** opaque, no blur, rules instead of borders */
  | 'paper';

export interface ThemeColors {
  /** the page behind everything */
  room: string;
  /** a second room tone; the room is a gradient between the two */
  room2: string;
  /** panel fill */
  surface: string;
  /** recessed / secondary panel fill */
  surface2: string;
  /** primary text */
  ink: string;
  /** secondary text */
  ink2: string;
  /** tertiary text, captions, axis labels */
  ink3: string;
  /** hairlines, borders */
  line: string;
  /** softer hairlines, inner rules */
  line2: string;
  /** the one accent family — actions, selection, the focus node */
  accent: string;
  /** text/glyph colour on top of accent */
  accentInk: string;
  /** something is happening right now */
  live: string;
  /** refused, failed, withheld */
  bad: string;
  /** verified, passed */
  ok: string;
  /** graph node fill at rest */
  node: string;
  /** graph node fill for a second-level (dimmer) node */
  node2: string;
  /** verified edge */
  edge: string;
  /** the highlighted path */
  edgeHot: string;
}

export interface ThemeType {
  /** display face stack — headings, the focus symbol, the masthead */
  display: string;
  /** body face stack — everything the reader reads */
  body: string;
  /** monospace stack — identifiers only, never prose */
  mono: string;
  /** body size in px; everything else scales from it */
  size: number;
  /** ratio between steps of the type scale */
  scale: number;
  /** display weight (100..900) */
  displayWeight: number;
  /** display letter-spacing in em, e.g. -0.02 */
  displayTracking: number;
  /** true when the display face is a serif — switches a few compositional details */
  displaySerif: boolean;
  /**
   * humanist voice face — Ikarus's own words only. Never chrome, a label, or
   * a datum. Standing law for this product: "cold glass, warm voice" — every
   * other face in a theme is instrument-cold on purpose; this is the one
   * warm face in the room.
   *
   * Optional (unlike `display`/`body`/`mono`): `theme/store.ts` repairs a
   * stored theme field-by-field and does not yet know this key, so a custom
   * theme saved before this field existed must still satisfy this type
   * without it. `apply.ts` falls back to `body` when unset. Every BUILT_IN
   * preset sets it explicitly — treat the optionality as a migration seam,
   * not permission to skip it in a new preset.
   */
  voice?: string;
  /** weight for the voice role; usually lighter than displayWeight. Optional — see `voice`. */
  voiceWeight?: number;
  /** label role: eyebrows, field names, axis captions — usually uppercase. Optional — see `voice`. */
  labelWeight?: number;
  /** label role tracking, in em. Optional — see `voice`. */
  labelTracking?: number;
  /** datum role: a number read as a number — counts, scores, sizes, tabular. Optional — see `voice`. */
  datumWeight?: number;
  /** datum role tracking, in em. Optional — see `voice`. */
  datumTracking?: number;
}

export interface ThemeForm {
  /** corner radius in px; 0 is a real choice (depesche) */
  radius: number;
  /** border width in px */
  border: number;
  /** base spacing unit in px — the density knob */
  unit: number;
  /**
   * 0 = no shadow, 1 = soft, 2 = lifted. The base/card level of a four-step
   * scale — a modal, a drawer, a card and a pane over a lit stage are four
   * different heights; see elevationPane / elevationDrawer / elevationModal.
   * Drives `--shadow`, unchanged, so nothing that already reads it moves.
   */
  elevation: number;
  /**
   * shadow depth for a mid pane (a sidebar, a docked column), 0..4. Optional
   * for the same reason as `ThemeType.voice` — `theme/store.ts` repairs a
   * stored theme field-by-field and predates this key. `apply.ts` falls back
   * to `elevation` when unset. Every BUILT_IN preset sets it explicitly.
   */
  elevationPane?: number;
  /** shadow depth for a drawer that slides over content, 0..4. Optional — see `elevationPane`. */
  elevationDrawer?: number;
  /** shadow depth for a modal that owns the whole surface, 0..4. Optional — see `elevationPane`. */
  elevationModal?: number;
  material: Material;
  /** backdrop blur in px, only meaningful for material 'glass' */
  blur: number;
  /** panel translucency 0..1, only meaningful for material 'glass' */
  alpha: number;
}

export interface ThemeStage {
  layout: StageLayout;
  /** node glyph: a lit sphere, a flat disc, a star, or a labelled card */
  glyph: 'pearl' | 'disc' | 'star' | 'card';
  /** draw only the backbone at rest; the rest appears on selection */
  backboneOnly: boolean;
  /** curvature of edges, 0 = straight lines */
  curve: number;
  /** how strongly node size follows fan-in, 0 = all nodes the same size */
  sizeByFanIn: number;
  /** ambient glow behind lit nodes, 0..1 */
  glow: number;
  /**
   * how strongly nodes shift with camera/pointer parallax, 0 = none.
   * Optional for the same reason as `ThemeType.voice` — `theme/store.ts`
   * predates this key and `apply.ts` falls back to 0 when unset. Every
   * BUILT_IN preset sets it explicitly.
   */
  parallax?: number;
  /** how much a farther-plane node fades toward the room tone, 0..1. Optional — see `parallax`. */
  depthFog?: number;
  /** max blur in px on the farthest-plane nodes — depth of field, 0 = none. Optional — see `parallax`. */
  depthBlur?: number;
}

export interface ThemeComposition {
  chrome: Chrome;
  chat: ChatPlacement;
}

export interface ThemeSpec {
  /** stable key, used in localStorage and the URL */
  id: string;
  /** what the owner sees in the picker */
  name: string;
  /** one line: what this theme is for */
  note: string;
  /** 'light' or 'dark' — drives the browser's own form controls and scrollbars */
  base: 'light' | 'dark';
  /** the round this theme came from, or 'custom' for one the owner made */
  origin: string;
  colors: ThemeColors;
  type: ThemeType;
  form: ThemeForm;
  stage: ThemeStage;
  composition: ThemeComposition;
  /**
   * alert/blocker tone — a gate that is closed ("Promotion gesperrt") is not
   * the same claim as a check that failed (`colors.bad`) or an action the
   * owner can take (`colors.accent`). Distinct hue from all three, in every
   * theme.
   *
   * Lives at the top level, sibling to `colors`, rather than inside it, on
   * purpose: `theme/store.ts` repairs a stored theme with one generic loop
   * over `Object.keys(colors)` that assumes — and `theme/ThemeStudio.tsx`'s
   * `Record<keyof ThemeColors, string>` swatch list separately assumes —
   * that ThemeColors' key set is exactly what it was when those files were
   * written. Adding a key there breaks both without touching either. An
   * optional top-level field breaks neither: `theme/store.ts`'s per-field
   * `repair()` simply omits a key it doesn't know yet (valid — the field is
   * optional), and `ThemeStudio.tsx` never enumerates `keyof ThemeSpec`, so
   * it never notices. `apply.ts` falls back to `colors.bad` when unset.
   * Every BUILT_IN preset sets it explicitly.
   */
  warn?: string;
  /** text/glyph colour on top of `warn`. Optional — see `warn`. Falls back to `colors.accentInk`. */
  warnInk?: string;
  /**
   * sequential heat ramp, FIVE comma-separated hex colours, low -> high, ONE
   * hue per theme (the exception is Nachtfenster's deliberate thermal-camera
   * arc — see its comment). A comma-joined string, not an array, for the
   * same reason `warn` sits at this level: keeps `ThemeColors` exactly the
   * flat, uniformly-typed bag `theme/store.ts` and `ThemeStudio.tsx` already
   * assume it is. Split on read — see `splitRamp` in apply.ts. Encodes a
   * continuous magnitude — fan_in, loc, the hot-list score — never identity.
   * The anchor flips by base: a dark theme's low step sits near `room` and
   * climbs to a light, saturated high step; a light theme's low step sits
   * near `room` and climbs to a dark, saturated high step. Low magnitude
   * recedes toward the room tone on purpose. Optional — see `warn`.
   */
  heat?: string;
  /**
   * the four-plane categorical set, FOUR comma-separated hex colours, FIXED
   * ORDER [Code, Type, Data, Knowledge] — identity, not magnitude. Same
   * placement and string-not-array reasoning as `heat`. A node's plane, not
   * its heat, says what it is; never derive one from the other. Optional —
   * see `warn`.
   */
  plane?: string;
}

/** A theme the owner made or edited, as stored. */
export interface StoredTheme extends ThemeSpec {
  /** the built-in this was forked from, if any */
  forkedFrom?: string;
  /** ms epoch of the last edit */
  editedAt: number;
}
