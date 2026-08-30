// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-License-Identifier: Apache-2.0

import type { ThemeSpec } from '../../theme/types';
import type { Placed } from '../layout';

/**
 * What one node looks like.
 *
 * Four glyph families, because a theme chooses one; but all four now answer
 * the same three questions from the payload rather than drawing every module
 * at one weight:
 *
 *   how big     fan-in, through the layout's radius / box (theme-scaled)
 *   how hot     the three-step heat rank, spent on WEIGHT and one neutral
 *               rule — never on a second hue, because the one accent family
 *               belongs to selection and two loud colours mean nothing
 *   how far     the plane: the focus is lifted, the second level recedes to an
 *               outline in the room's own tone
 *
 * Nothing here invents a colour. `--ink`/`--ink2`/`--ink3` and
 * `--surface`/`--room2` are the theme's own tones, so a theme that wants a
 * flat map gets one by choosing tones that are close together.
 */

export type GlyphKind = ThemeSpec['stage']['glyph'];

/**
 * The heat rank, as a colour.
 *
 * The theme carries a five-step sequential ramp (`--heat-1…5`, one hue, low
 * step near the room tone) which is exactly what a magnitude wants; three
 * ranks take steps 2, 3 and 5 so the lead tier is a jump rather than one more
 * notch. The `var(…, …)` fallbacks are the neutral ink ramp, so a theme that
 * has not been given the sequential steps still draws a legible three-step
 * mark instead of a black one.
 */
export function tierInk(tier: 0 | 1 | 2): string {
  if (tier === 2) return 'var(--heat-5, var(--ink))';
  if (tier === 1) return 'var(--heat-3, var(--ink2))';
  return 'var(--heat-2, var(--ink3))';
}

/** Label weight by heat rank. Weight is free of contrast risk; opacity is not. */
export function tierWeight(tier: 0 | 1 | 2): number {
  return tier === 2 ? 620 : tier === 1 ? 480 : 400;
}

function strokeFor(tier: 0 | 1 | 2): number {
  return tier === 2 ? 1.5 : tier === 1 ? 1.1 : 0.8;
}

export interface GlyphProps {
  p: Placed;
  kind: GlyphKind;
  /** the theme's own corner radius, in px — never a constant */
  radius: number;
  glow: number;
  /**
   * How far the second plane fades toward the room, 0..1, from the theme.
   *
   * Spent on the GLYPH and never on the label. An `opacity` on a text run is a
   * contrast reduction the audit cannot see — it reads `fill`, not the
   * composited alpha — so a fogged label would quietly trade away the floor
   * and report itself clean. The label's recession is a designed token step
   * (`--ink2`) instead.
   */
  fog: number;
  selected: boolean;
  dimmed: boolean;
}

export function Glyph({ p, kind, radius, glow, fog, selected, dimmed }: GlyphProps) {
  const opacity = (dimmed ? 0.3 : 1) * (p.level === 2 ? 1 - 0.55 * fog : 1);

  // The aggregate glyph is deliberately not a node: it is a pill that says how
  // many neighbours it stands for, in every theme, so it can never be mistaken
  // for one module with a strange name.
  if (p.kind === 'more') {
    const w = p.label.length * 7.6 + 26;
    return (
      <g className="stage-glyph" opacity={opacity}>
        <rect
          x={p.x - w / 2}
          y={p.y - 15}
          width={w}
          height={30}
          rx={15}
          fill="none"
          stroke="var(--accent)"
          strokeWidth={1.2}
          strokeDasharray="4 3"
        />
      </g>
    );
  }

  if (kind === 'card') {
    const w = p.boxW ?? 96;
    const h = p.boxH ?? 34;
    const x = p.x - w / 2;
    const y = p.y - h / 2;
    const far = p.level === 2;
    /**
     * A panel, not a swatch — and the far plane is not a panel at all.
     *
     * Filling every card with `--surface` put the second level on the same
     * shelf as the first and the picture went flat. A distant card is an
     * outline in the room's own tone: it is visibly behind the near ones, and
     * an edge crossing it still reads.
     */
    return (
      <g className="stage-glyph" opacity={opacity}>
        <rect
          x={x}
          y={y}
          width={w}
          height={h}
          rx={radius}
          fill={p.level === 0 ? 'var(--surface2)' : far ? 'var(--room2)' : 'var(--surface)'}
          stroke={selected || p.level === 0 ? 'var(--accent)' : far ? 'var(--line2)' : 'var(--line)'}
          strokeWidth={selected || p.level === 0 ? 1.6 : strokeFor(p.tier)}
        />
        {/* The heat rank as a rule on the card's leading edge. One mark, one
            idea: how heavy this module is among the ones on screen. */}
        {p.node && (
          <rect
            x={x + 3}
            y={y + 3}
            width={3}
            height={h - 6}
            rx={Math.min(1.5, radius / 2)}
            fill={p.level === 0 ? 'var(--accent)' : tierInk(p.tier)}
          />
        )}
      </g>
    );
  }

  const fill = p.level === 2 ? 'var(--node2)' : 'var(--node)';
  // The plane's own occlusion. Without it every edge in the field runs visibly
  // THROUGH the discs it connects, which is what made the forest read flat.
  const cut = (
    <circle cx={p.x} cy={p.y} r={p.r + 2.5} fill="var(--room2)" />
  );

  if (kind === 'star') {
    // A star chart whose stars are two pixels across is a dark rectangle. The
    // floor is what keeps a level-2 node visible at 100%.
    const r = Math.max(p.level === 2 ? 5 : 8, p.r);
    const spikes = `M ${p.x - r * 1.5} ${p.y} L ${p.x + r * 1.5} ${p.y} M ${p.x} ${p.y - r * 1.5} L ${p.x} ${p.y + r * 1.5}`;
    return (
      <g className="stage-glyph" opacity={opacity}>
        {p.level === 0 && <path d={spikes} stroke="var(--accent)" strokeWidth={1} opacity={0.7} />}
        <circle cx={p.x} cy={p.y} r={r * 0.42} fill={p.level === 0 ? 'var(--accent)' : fill} />
        {p.level !== 2 && (
          <circle cx={p.x} cy={p.y} r={r * 0.9} fill="none" stroke={fill} strokeWidth={strokeFor(p.tier) * 0.7} opacity={0.5} />
        )}
        {p.tier === 2 && p.level !== 0 && (
          <circle cx={p.x} cy={p.y} r={r * 1.45} fill="none" stroke={tierInk(2)} strokeWidth={0.9} opacity={0.5} />
        )}
      </g>
    );
  }

  if (kind === 'pearl') {
    return (
      <g className="stage-glyph" opacity={opacity}>
        {p.level === 0 && glow > 0 && <circle cx={p.x} cy={p.y} r={p.r * 2.6} fill="url(#stage-halo)" />}
        {cut}
        <circle cx={p.x} cy={p.y} r={p.r} fill={p.level === 2 ? 'var(--node2)' : 'url(#stage-pearl)'} />
        {p.tier === 2 && p.level !== 0 && (
          <circle cx={p.x} cy={p.y} r={p.r + 3.5} fill="none" stroke={tierInk(2)} strokeWidth={1} opacity={0.45} />
        )}
        {(selected || p.level === 0) && (
          <circle cx={p.x} cy={p.y} r={p.r + 7} fill="none" stroke="var(--accent)" strokeWidth={1.4} opacity={0.85} />
        )}
      </g>
    );
  }

  // 'disc': flat fill, hairline ring, no gloss. The pearl gradient read as a
  // toy; a shipped interface draws a shape and lets the size carry the number.
  return (
    <g className="stage-glyph" opacity={opacity}>
      {p.level === 0 && glow > 0 && <circle cx={p.x} cy={p.y} r={p.r * 2.1} fill="url(#stage-halo)" />}
      {cut}
      <circle
        cx={p.x}
        cy={p.y}
        r={p.r}
        fill={p.level === 0 ? 'var(--accent)' : fill}
        stroke={p.level === 0 ? 'var(--accent)' : p.level === 2 ? 'var(--line2)' : 'var(--line)'}
        strokeWidth={strokeFor(p.tier)}
      />
      {p.tier === 2 && p.level !== 0 && (
        <circle cx={p.x} cy={p.y} r={p.r + 3.5} fill="none" stroke={tierInk(2)} strokeWidth={1} opacity={0.5} />
      )}
      {selected && p.level !== 0 && (
        <circle cx={p.x} cy={p.y} r={p.r + 6} fill="none" stroke="var(--accent)" strokeWidth={1.5} />
      )}
    </g>
  );
}
