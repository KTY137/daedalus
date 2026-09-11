import type { Placed } from '../layout';

/**
 * What the reader is looking at, read out in the rail.
 *
 * The rail measured 281px of nothing between the legend and the controls at
 * 1440×900 — a third of a 330px column holding air. The hole is not a spacing
 * problem: it is a missing job. The drawing already knows which node is under
 * the pointer or under the arrow keys, and the payload already carries that
 * node's path, importers, lines and heat; none of it was anywhere on the page.
 *
 * Four rules this block is built to keep:
 *
 *  - it is never empty and never instructional. An empty panel explaining how
 *    to fill it is chrome pretending to be content.
 *  - at rest it does not repeat the header. The first draft read the FOCUS
 *    when nothing was under the pointer, which printed the module's name, its
 *    path and its three figures a second time, 150px below the first. At rest
 *    it now says how the drawing is COMPOSED — how many of each relation was
 *    actually drawn, and which side of the focus they are on. That convention
 *    ("importers left, imports right") was asserted in the layout's comments
 *    and never once told to the reader.
 *  - the eyebrow reports the state it actually has. "Unter dem Zeiger" and
 *    "Mit den Pfeiltasten" are different facts and a reader navigating by
 *    keyboard needs to see that the map heard them.
 *  - an unmeasured module says so. Printing three zeroes for a node the
 *    backend never scored would be the instrument lying about its coverage.
 */

export type ReadingSource = 'focus' | 'pointer' | 'keyboard';

/** What the drawing actually put on the stage, counted from the layout. */
export interface DrawnCounts {
  ins: number;
  outs: number;
  far: number;
  /** how the three-step heat mark was cut: [ruhig, mittel, hoch] */
  tiers: [number, number, number];
  /** true only where the side of the focus carries meaning */
  sided: boolean;
  /** the ordered view labels its own columns with their own counts */
  ordered: boolean;
}

export interface ReadingProps {
  p: Placed | undefined;
  /** the focus's own short name, for the relation sentence */
  focusLabel: string;
  source: ReadingSource;
  counts: DrawnCounts;
}

const EYEBROW: Record<ReadingSource, string> = {
  focus: 'Gezeichnet',
  pointer: 'Unter dem Zeiger',
  keyboard: 'Mit den Pfeiltasten'
};

function Figures({ rows }: { rows: Array<[string, string | number]> }) {
  return (
    <dl className="stage-figures">
      {rows.map(([term, value]) => (
        <div key={term}>
          <dt>{term}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function relationOf(p: Placed, focusLabel: string): string {
  if (p.kind === 'more') return p.full;
  if (p.level === 0) return 'Die Karte ist um dieses Modul herum gezeichnet.';
  if (p.level === 2) return `Eine Ebene weiter — kein direkter Import von ${focusLabel}.`;
  if (p.via === 'out') return `Wird von ${focusLabel} importiert.`;
  if (p.via === 'mixed') return `Importiert ${focusLabel} und wird von ${focusLabel} importiert.`;
  return `Importiert ${focusLabel}.`;
}

export function Reading({ p, focusLabel, source, counts }: ReadingProps) {
  if (source === 'focus' || !p) {
    /**
     * Say what THIS drawing does not already say.
     *
     * The spatial view has nothing on screen that counts the relations, so it
     * gets the relation counts. The ordered view writes exactly those counts
     * under its own four column headers, so repeating them in the rail would
     * be the caption reading the figure back; it gets the heat cut instead —
     * how many of the drawn modules the three-step bar calls hot, middling and
     * quiet, which is stated nowhere else in either view.
     */
    const rows: Array<[string, number]> = counts.ordered
      ? [
          ['Hoch', counts.tiers[2]],
          ['Mittel', counts.tiers[1]],
          ['Ruhig', counts.tiers[0]]
        ]
      : [
          ['Importeure', counts.ins],
          ['Importe', counts.outs],
          ...(counts.far > 0 ? ([['Zweite Ebene', counts.far]] as Array<[string, number]>) : [])
        ];
    return (
      <section className="stage-reading" aria-live="polite">
        <div className="stage-eyebrow">{EYEBROW.focus}</div>
        <Figures rows={rows} />
        {/* A fact about the drawing, not an instruction for using it. The
            second sentence this line used to carry ("Zeiger oder Pfeiltasten
            lesen einen Knoten") was chrome explaining chrome. */}
        {counts.sided && <p className="stage-reading-rel">Importeure stehen links von {focusLabel}, Importe rechts.</p>}
      </section>
    );
  }
  const n = p.node;
  return (
    <section className="stage-reading" aria-live="polite">
      <div className="stage-eyebrow">{EYEBROW[source]}</div>
      <div className="stage-reading-name">{p.label}</div>
      {p.kind === 'node' && <div className="stage-reading-path">{p.id}</div>}
      <p className="stage-reading-rel">{relationOf(p, focusLabel)}</p>
      {p.kind === 'node' &&
        (n ? (
          <Figures
            rows={[
              ['Importeure', n.fan_in],
              ['Zeilen', n.loc],
              ['Hitze', n.score.toFixed(1)]
            ]}
          />
        ) : (
          <p className="stage-reading-unmeasured">Nicht im Messindex — keine Zahlen zu diesem Modul.</p>
        ))}
    </section>
  );
}
