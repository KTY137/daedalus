import type { ThemeSpec } from '../../theme/types';
import { tierInk } from './Glyph';

/**
 * What the drawing encodes, said once, next to the drawing.
 *
 * The map now spends size, weight, a neutral rule and an arrowhead on data.
 * An encoding nobody can decode is decoration, so the samples here are drawn
 * with the SAME primitives the stage uses — a card theme's legend shows cards,
 * a disc theme's shows discs — and a row only appears when that channel is
 * actually carrying something. `sizeByFanIn: 0` is a real theme choice, and a
 * legend that claimed "Größe — Importeure" on a map where every glyph is the
 * same size would be the interface lying about its own drawing.
 */

export interface LegendProps {
  stage: ThemeSpec['stage'];
  /** the theme's own corner radius */
  radius: number;
  /** whether the drawing currently holds any second-level node */
  hasFar: boolean;
  /** the ordered view routes relations left to right; the wording follows */
  ordered: boolean;
}

function Card({ x, w, h, fill, stroke, radius, bar }: { x: number; w: number; h: number; fill: string; stroke: string; radius: number; bar?: string }) {
  return (
    <g>
      <rect x={x} y={(24 - h) / 2} width={w} height={h} rx={Math.min(radius, h / 2)} fill={fill} stroke={stroke} strokeWidth={1} />
      {bar && <rect x={x + 2} y={(24 - h) / 2 + 2} width={2.5} height={h - 4} rx={1} fill={bar} />}
    </g>
  );
}

export function Legend({ stage, radius, hasFar, ordered }: LegendProps) {
  const card = stage.glyph === 'card' || ordered;
  const rows: Array<{ sample: React.ReactNode; term: string; gloss: string }> = [];

  // The ordered view draws every row at one height so it can hold a 44px
  // target, so size carries nothing there and the row would be a lie.
  if (stage.sizeByFanIn > 0 && !ordered) {
    rows.push({
      sample: card ? (
        <>
          <Card x={2} w={16} h={10} fill="var(--surface)" stroke="var(--line)" radius={radius} />
          <Card x={22} w={20} h={16} fill="var(--surface)" stroke="var(--line)" radius={radius} />
        </>
      ) : (
        <>
          <circle cx={9} cy={12} r={3.5} fill="var(--node)" stroke="var(--line)" strokeWidth={0.8} />
          <circle cx={30} cy={12} r={8} fill="var(--node)" stroke="var(--line)" strokeWidth={0.8} />
        </>
      ),
      term: 'Größe',
      gloss: 'Importeure'
    });
  }

  rows.push({
    // Drawn as a literal head rather than through the stage's marker: a legend
    // that silently loses its arrow when the reference fails to resolve would
    // be worse than no legend.
    sample: (
      <>
        <path d="M 3 12 L 30 12" stroke="var(--edge)" strokeWidth={1.4} fill="none" />
        <path d="M 30 8.8 L 38 12 L 30 15.2 z" fill="var(--edge)" />
      </>
    ),
    term: 'Pfeil',
    gloss: 'importiert'
  });

  rows.push({
    sample: card ? (
      <>
        <Card x={2} w={12} h={16} fill="var(--surface)" stroke="var(--line)" radius={radius} bar={tierInk(0)} />
        <Card x={17} w={12} h={16} fill="var(--surface)" stroke="var(--line)" radius={radius} bar={tierInk(1)} />
        <Card x={32} w={12} h={16} fill="var(--surface)" stroke="var(--line)" radius={radius} bar={tierInk(2)} />
      </>
    ) : (
      <>
        <circle cx={9} cy={12} r={4.5} fill="var(--node)" stroke="var(--line)" strokeWidth={0.8} />
        <circle cx={26} cy={12} r={4.5} fill="var(--node)" stroke="var(--line)" strokeWidth={0.8} />
        <circle cx={26} cy={12} r={8} fill="none" stroke={tierInk(2)} strokeWidth={1} opacity={0.5} />
      </>
    ),
    term: card ? 'Balken' : 'Ring',
    // The samples run quiet → hot left to right; a ramp whose direction is not
    // stated is three colours, not a scale.
    gloss: 'Hitze, ruhig bis hoch'
  });

  // In the ordered view the second level is a labelled column with its own
  // count; it does not also need a legend row saying it is further away.
  if (hasFar && !ordered) {
    rows.push({
      sample: card ? (
        <>
          {/* the ratio the layout actually draws: a far card is ~0.82 of a
              near one in both axes, not the same card in a lighter fill */}
          <Card x={2} w={20} h={17} fill="var(--surface)" stroke="var(--line)" radius={radius} />
          <Card x={26} w={16} h={14} fill="var(--room2)" stroke="var(--line2)" radius={radius} />
        </>
      ) : (
        <>
          <circle cx={9} cy={12} r={6} fill="var(--node)" stroke="var(--line)" strokeWidth={0.8} />
          <circle cx={28} cy={12} r={4} fill="var(--node2)" stroke="var(--line2)" strokeWidth={0.8} />
        </>
      ),
      term: 'Kleiner',
      gloss: 'zweite Ebene, weiter hinten'
    });
  }

  return (
    <div className="stage-legend">
      <div className="stage-eyebrow">Legende</div>
      <dl>
        {rows.map((r) => (
          <div className="stage-legend-row" key={r.term}>
            <svg width={48} height={24} viewBox="0 0 48 24" aria-hidden="true">
              {r.sample}
            </svg>
            <dt>{r.term}</dt>
            <dd>{r.gloss}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
