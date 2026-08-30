// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-License-Identifier: Apache-2.0

export type StageMode = 'spatial' | 'ordered';

/**
 * The stage's own controls: which representation, and where the camera is.
 *
 * The previous version was three unlabelled boxes with a percentage floating
 * outside them, so the reader could not tell what the third box did and the
 * number belonged to nothing. Every control here says what it does, the
 * readout is INSIDE the group it reports on, and the readout is itself the
 * reset — a control that reports a state and can restore it, rather than a
 * caption sitting next to two buttons.
 */
export interface ToolsProps {
  mode: StageMode;
  onMode: (m: StageMode) => void;
  zoom: number;
  onZoom: (factor: number) => void;
  onHome: () => void;
}

/**
 * What each representation actually is, in one line.
 *
 * "Geordnet" has been mistaken for the four-plane Project-Twin view it is not:
 * its four columns are the four RELATIONS to the focus, and this graph is one
 * plane (code). The line says what it sorts by so nobody has to guess, and it
 * changes with the state rather than describing both at once.
 */
const NOTE: Record<StageMode, string> = {
  spatial: 'Nachbarn um den Fokus; die zweite Ebene liegt kleiner und blasser dahinter.',
  ordered: 'Vier Spalten nach Beziehung zum Fokus — Importeure, Fokus, Importe, zweite Ebene — je Spalte nach Hitze sortiert.'
};

export function Tools({ mode, onMode, zoom, onZoom, onHome }: ToolsProps) {
  const pct = Math.round(zoom * 100);
  return (
    <div className="stage-tools">
      <div className="stage-tools-group" role="group" aria-label="Darstellung">
        <button type="button" aria-pressed={mode === 'spatial'} onClick={() => onMode('spatial')}>
          Räumlich
        </button>
        <button type="button" aria-pressed={mode === 'ordered'} onClick={() => onMode('ordered')}>
          Geordnet
        </button>
      </div>
      <p className="stage-tools-note">{NOTE[mode]}</p>
      <div className="stage-tools-group" role="group" aria-label="Ansicht">
        <button type="button" onClick={() => onZoom(1 / 1.25)} aria-label="Weiter weg">
          <span aria-hidden="true">−</span>
        </button>
        <button
          type="button"
          className="stage-zoom"
          onClick={onHome}
          aria-label={`Zoom ${pct} Prozent — Ansicht zurücksetzen`}
          title="Ansicht zurücksetzen"
        >
          {pct} %
        </button>
        <button type="button" onClick={() => onZoom(1.25)} aria-label="Näher">
          <span aria-hidden="true">+</span>
        </button>
      </div>
    </div>
  );
}
