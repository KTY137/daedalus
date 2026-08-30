// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useMemo, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { useThemes } from './ThemeProvider';
import type { ThemeColors, ThemeSpec } from './types';
import { drawerVariants, useReducedMotionPref } from '../motion';
import './studio.css';

/**
 * The Theme Studio.
 *
 * Six designs came out of the gallery round and choosing one meant throwing
 * five away. This panel is the answer to that: every design is a theme, a
 * theme is data, and the owner can fork one, change any part of it, and keep
 * both. Editing a built-in never destroys it — the first edit forks it and
 * says so.
 *
 * A theme decides how true things LOOK. It cannot change a number, hide a
 * withheld path, or make an inert control look live, and there is deliberately
 * no knob here that could.
 */

const COLOR_GROUPS: Array<{ title: string; keys: Array<keyof ThemeColors>; hint: string }> = [
  { title: 'Raum', keys: ['room', 'room2'], hint: 'Der Hintergrund. Zwei Töne — die Bühne blendet zwischen ihnen.' },
  { title: 'Flächen', keys: ['surface', 'surface2'], hint: 'Panels und vertiefte Flächen.' },
  { title: 'Schrift', keys: ['ink', 'ink2', 'ink3'], hint: 'Primär, sekundär, Bildunterschrift.' },
  { title: 'Linien', keys: ['line', 'line2'], hint: 'Rahmen und feinere Innenlinien.' },
  { title: 'Akzent', keys: ['accent', 'accentInk'], hint: 'Eine Akzentfamilie. Ein zweiter Akzent ist die häufigste Ursache für „sieht KI-gemacht aus“.' },
  { title: 'Zustand', keys: ['live', 'bad', 'ok'], hint: 'Läuft gerade · verweigert · bestanden.' },
  { title: 'Graph', keys: ['node', 'node2', 'edge', 'edgeHot'], hint: 'Knoten Ebene 1 und 2, Kante, hervorgehobener Pfad.' }
];

const COLOR_LABELS: Record<keyof ThemeColors, string> = {
  room: 'Raum Mitte',
  room2: 'Raum Rand',
  surface: 'Fläche',
  surface2: 'Fläche vertieft',
  ink: 'Schrift',
  ink2: 'Schrift sekundär',
  ink3: 'Schrift tertiär',
  line: 'Linie',
  line2: 'Linie fein',
  accent: 'Akzent',
  accentInk: 'Schrift auf Akzent',
  live: 'Läuft',
  bad: 'Verweigert',
  ok: 'Bestanden',
  node: 'Knoten',
  node2: 'Knoten Ebene 2',
  edge: 'Kante',
  edgeHot: 'Kante hervorgehoben'
};

const HEX = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i;

function Swatch({ theme }: { theme: ThemeSpec }) {
  const c = theme.colors;
  return (
    <span
      className="swatch"
      style={{ background: `radial-gradient(120% 120% at 30% 25%, ${c.room} 0%, ${c.room2} 100%)`, borderColor: c.line }}
      aria-hidden="true"
    >
      <i style={{ background: c.node }} />
      <i style={{ background: c.accent }} />
      <i style={{ background: c.ink }} />
    </span>
  );
}

function ColorField({
  label,
  value,
  onChange
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
}) {
  const isHex = HEX.test(value.trim());
  return (
    <label className="field color">
      <span className="field-label">{label}</span>
      <span className="color-row">
        {isHex ? (
          <input type="color" value={value.trim()} onChange={(e) => onChange(e.target.value)} aria-label={`${label} wählen`} />
        ) : (
          <span className="color-chip" style={{ background: value }} title="rgba() — als Text bearbeiten" />
        )}
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          spellCheck={false}
          aria-label={`${label} als CSS-Farbe`}
        />
      </span>
    </label>
  );
}

function Range({
  label,
  value,
  min,
  max,
  step,
  suffix,
  onChange
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  suffix?: string;
  onChange: (n: number) => void;
}) {
  return (
    <label className="field range">
      <span className="field-label">
        {label}
        <b>
          {value}
          {suffix || ''}
        </b>
      </span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  );
}

function Choice<T extends string>({
  label,
  value,
  options,
  onChange
}: {
  label: string;
  value: T;
  options: Array<[T, string]>;
  onChange: (v: T) => void;
}) {
  return (
    <div className="field choice">
      <span className="field-label">{label}</span>
      <div className="choice-row" role="radiogroup" aria-label={label}>
        {options.map(([key, text]) => (
          <button key={key} type="button" role="radio" aria-checked={value === key} className={value === key ? 'on' : ''} onClick={() => onChange(key)}>
            {text}
          </button>
        ))}
      </div>
    </div>
  );
}

export function ThemeStudio({ open, onClose }: { open: boolean; onClose: () => void }) {
  const api = useThemes();
  const { theme } = api;
  const [tab, setTab] = useState<'themes' | 'farbe' | 'schrift' | 'form' | 'buehne' | 'aufbau' | 'daten'>('themes');
  const [importText, setImportText] = useState('');
  const [notice, setNotice] = useState('');
  const [renaming, setRenaming] = useState('');
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) {
      setNotice('');
      setRenaming('');
    }
  }, [open]);

  const forkedNotice = useMemo(
    () =>
      api.isBuiltIn
        ? 'Das ist ein eingebautes Theme. Die erste Änderung legt automatisch eine Kopie an — das Original bleibt erhalten.'
        : '',
    [api.isBuiltIn]
  );

  const edit = (patch: Parameters<typeof api.update>[0]) => {
    const wasBuiltIn = api.isBuiltIn;
    const id = api.update(patch);
    if (wasBuiltIn) setNotice(`Kopie angelegt: ${id}. Das eingebaute Theme ist unverändert.`);
  };

  const download = (text: string, name: string) => {
    const blob = new Blob([text], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  };

  const reduced = useReducedMotionPref();
  const drawer = useMemo(() => drawerVariants(reduced), [reduced]);

  return (
    <motion.aside
      className={open ? 'studio open' : 'studio'}
      data-motion="drawer"
      variants={drawer}
      initial={false}
      animate={open ? 'open' : 'closed'}
      aria-hidden={!open}
      ref={panel}
      aria-label="Theme-Studio"
    >
      <header className="studio-head">
        <h2>Themes</h2>
        <button type="button" className="studio-close" onClick={onClose} aria-label="Studio schließen">
          ✕
        </button>
      </header>

      <div className="studio-active">
        <Swatch theme={theme} />
        <div>
          <b>{theme.name}</b>
          <span>{theme.note}</span>
        </div>
      </div>

      {forkedNotice && <p className="studio-note">{forkedNotice}</p>}
      {notice && <p className="studio-note ok">{notice}</p>}
      {api.saveError && <p className="studio-note bad">Speichern fehlgeschlagen: {api.saveError}</p>}
      {api.problems.length > 0 && (
        <ul className="studio-problems">
          {api.problems.map((p, i) => (
            <li key={i}>
              <code>{p.id}</code> {p.message}
            </li>
          ))}
        </ul>
      )}

      <nav className="studio-tabs" role="tablist">
        {(
          [
            ['themes', 'Themes'],
            ['farbe', 'Farbe'],
            ['schrift', 'Schrift'],
            ['form', 'Form'],
            ['buehne', 'Bühne'],
            ['aufbau', 'Aufbau'],
            ['daten', 'Daten']
          ] as const
        ).map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key} className={tab === key ? 'on' : ''} onClick={() => setTab(key)}>
            {label}
          </button>
        ))}
      </nav>

      <div className="studio-body">
        {/* One way back that is always in the same place. The tab row above is
            the other, and it was the one that got squeezed flat. */}
        {tab !== 'themes' && (
          <button type="button" className="studio-back" onClick={() => setTab('themes')}>
            ← Zurück zur Theme-Liste
          </button>
        )}

        {tab === 'themes' && (
          <>
            <div className="studio-group-title">Eingebaut · aus der Gallery-Runde vom 24.08.2026</div>
            <ul className="theme-list">
              {api.builtIns.map((t) => (
                <li key={t.id} className={t.id === theme.id ? 'on' : ''}>
                  <button type="button" className="theme-pick" onClick={() => api.select(t.id)}>
                    <Swatch theme={t} />
                    <span className="theme-name">{t.name}</span>
                    <span className="theme-note">{t.note}</span>
                  </button>
                  <div className="theme-acts">
                    <button type="button" onClick={() => api.duplicate(t.id)}>Kopieren</button>
                  </div>
                </li>
              ))}
            </ul>

            <div className="studio-group-title">Eigene</div>
            {api.custom.length === 0 && (
              <p className="studio-empty">
                Noch keine eigenen Themes. Kopier eines der eingebauten oder ändere einfach etwas — die Kopie entsteht
                dann von selbst.
              </p>
            )}
            <ul className="theme-list">
              {api.custom.map((t) => (
                <li key={t.id} className={t.id === theme.id ? 'on' : ''}>
                  <button type="button" className="theme-pick" onClick={() => api.select(t.id)}>
                    <Swatch theme={t} />
                    {renaming === t.id ? (
                      <input
                        className="theme-rename"
                        autoFocus
                        defaultValue={t.name}
                        onClick={(e) => e.stopPropagation()}
                        onBlur={(e) => {
                          api.rename(t.id, e.target.value);
                          setRenaming('');
                        }}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
                          if (e.key === 'Escape') setRenaming('');
                        }}
                      />
                    ) : (
                      <span className="theme-name">{t.name}</span>
                    )}
                    <span className="theme-note">
                      {t.forkedFrom ? `Kopie von ${t.forkedFrom}` : 'importiert'}
                      {t.editedAt ? ` · zuletzt ${new Date(t.editedAt).toLocaleString('de-DE')}` : ''}
                    </span>
                  </button>
                  <div className="theme-acts">
                    <button type="button" onClick={() => setRenaming(t.id)}>Umbenennen</button>
                    <button type="button" onClick={() => api.duplicate(t.id)}>Kopieren</button>
                    {t.forkedFrom && (
                      <button type="button" onClick={() => api.revert(t.id)} title="Auf den Stand des eingebauten Themes zurücksetzen">
                        Zurücksetzen
                      </button>
                    )}
                    <button type="button" className="danger" onClick={() => api.remove(t.id)}>
                      Löschen
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}

        {tab === 'farbe' &&
          COLOR_GROUPS.map((group) => (
            <section key={group.title} className="studio-section">
              <div className="studio-group-title">{group.title}</div>
              <p className="studio-hint">{group.hint}</p>
              {group.keys.map((key) => (
                <ColorField
                  key={key}
                  label={COLOR_LABELS[key]}
                  value={theme.colors[key]}
                  onChange={(next) => edit({ colors: { [key]: next } as Partial<ThemeColors> })}
                />
              ))}
            </section>
          ))}

        {tab === 'schrift' && (
          <section className="studio-section">
            <label className="field">
              <span className="field-label">Display-Schrift</span>
              <input
                type="text"
                value={theme.type.display}
                spellCheck={false}
                onChange={(e) => edit({ type: { display: e.target.value } })}
              />
            </label>
            <label className="field">
              <span className="field-label">Fließtext</span>
              <input type="text" value={theme.type.body} spellCheck={false} onChange={(e) => edit({ type: { body: e.target.value } })} />
            </label>
            <label className="field">
              <span className="field-label">Monospace — nur für Bezeichner</span>
              <input type="text" value={theme.type.mono} spellCheck={false} onChange={(e) => edit({ type: { mono: e.target.value } })} />
            </label>
            <Range label="Grundgröße" value={theme.type.size} min={11} max={20} step={0.5} suffix="px" onChange={(size) => edit({ type: { size } })} />
            <Range label="Stufenverhältnis" value={theme.type.scale} min={1.05} max={1.5} step={0.01} onChange={(scale) => edit({ type: { scale } })} />
            <Range label="Display-Gewicht" value={theme.type.displayWeight} min={300} max={800} step={100} onChange={(displayWeight) => edit({ type: { displayWeight } })} />
            <Range
              label="Display-Laufweite"
              value={theme.type.displayTracking}
              min={-0.04}
              max={0.08}
              step={0.005}
              suffix="em"
              onChange={(displayTracking) => edit({ type: { displayTracking } })}
            />
            <Choice
              label="Display ist eine Serifenschrift"
              value={theme.type.displaySerif ? 'ja' : 'nein'}
              options={[
                ['ja', 'Ja'],
                ['nein', 'Nein']
              ]}
              onChange={(v) => edit({ type: { displaySerif: v === 'ja' } })}
            />
            <p className="studio-hint">
              Die Schriftfamilien sind CSS-Stacks und werden lokal aufgelöst. Es wird nichts nachgeladen — die Oberfläche
              holt keine Schrift aus dem Netz.
            </p>
          </section>
        )}

        {tab === 'form' && (
          <section className="studio-section">
            <Range label="Eckradius" value={theme.form.radius} min={0} max={32} step={1} suffix="px" onChange={(radius) => edit({ form: { radius } })} />
            <Range label="Rahmenstärke" value={theme.form.border} min={0} max={3} step={0.5} suffix="px" onChange={(border) => edit({ form: { border } })} />
            <Range label="Dichte (Grundeinheit)" value={theme.form.unit} min={5} max={14} step={0.5} suffix="px" onChange={(unit) => edit({ form: { unit } })} />
            <Range label="Erhebung" value={theme.form.elevation} min={0} max={2} step={1} onChange={(elevation) => edit({ form: { elevation } })} />
            <Choice
              label="Material"
              value={theme.form.material}
              options={[
                ['flat', 'Flach'],
                ['glass', 'Glas'],
                ['paper', 'Papier']
              ]}
              onChange={(material) => edit({ form: { material } })}
            />
            {theme.form.material === 'glass' && (
              <>
                <Range label="Unschärfe" value={theme.form.blur} min={0} max={48} step={1} suffix="px" onChange={(blur) => edit({ form: { blur } })} />
                <Range label="Deckkraft" value={theme.form.alpha} min={0.04} max={1} step={0.01} onChange={(alpha) => edit({ form: { alpha } })} />
              </>
            )}
            <Choice
              label="Grundton"
              value={theme.base}
              options={[
                ['dark', 'Dunkel'],
                ['light', 'Hell']
              ]}
              onChange={(base) => edit({ base })}
            />
          </section>
        )}

        {tab === 'buehne' && (
          <section className="studio-section">
            <Choice
              label="Anordnung"
              value={theme.stage.layout}
              options={[
                ['forest', 'Knotenwald'],
                ['stars', 'Sternkarte'],
                ['cards', 'Karten'],
                ['arcs', 'Bögen']
              ]}
              onChange={(layout) => edit({ stage: { layout } })}
            />
            <Choice
              label="Knotenform"
              value={theme.stage.glyph}
              options={[
                ['pearl', 'Perle'],
                ['disc', 'Scheibe'],
                ['star', 'Stern'],
                ['card', 'Karte']
              ]}
              onChange={(glyph) => edit({ stage: { glyph } })}
            />
            <Choice
              label="In Ruhe nur das Rückgrat zeichnen"
              value={theme.stage.backboneOnly ? 'ja' : 'nein'}
              options={[
                ['ja', 'Ja'],
                ['nein', 'Nein']
              ]}
              onChange={(v) => edit({ stage: { backboneOnly: v === 'ja' } })}
            />
            <Range label="Kantenkrümmung" value={theme.stage.curve} min={0} max={1} step={0.02} onChange={(curve) => edit({ stage: { curve } })} />
            <Range label="Größe folgt Importeuren" value={theme.stage.sizeByFanIn} min={0} max={1.4} step={0.05} onChange={(sizeByFanIn) => edit({ stage: { sizeByFanIn } })} />
            <Range label="Leuchten" value={theme.stage.glow} min={0} max={1} step={0.05} onChange={(glow) => edit({ stage: { glow } })} />
            <p className="studio-hint">
              Die Bühne zeichnet immer dieselben gemessenen Kanten. Diese Regler ändern, wie sie aussehen, nie welche
              vorhanden sind.
            </p>
          </section>
        )}

        {tab === 'aufbau' && (
          <section className="studio-section">
            <Choice
              label="Kopf"
              value={theme.composition.chrome}
              options={[
                ['bar', 'Leiste'],
                ['masthead', 'Titelkopf']
              ]}
              onChange={(chrome) => edit({ composition: { chrome } })}
            />
            <Choice
              label="Gesprächsseite"
              value={theme.composition.chat}
              options={[
                ['column', 'Mit Spalte daneben'],
                ['flow', 'Ein Textfluss']
              ]}
              onChange={(chat) => edit({ composition: { chat } })}
            />
            <p className="studio-hint">
              Karte und Gespräch sind seit dem 25.08.2026 zwei Seiten. Über der Karte liegt nichts mehr, deshalb gibt es
              hier auch keinen Regler mehr dafür, wo die Entscheidung schwebt — sie steht auf der Gesprächsseite oben.
            </p>
          </section>
        )}

        {tab === 'daten' && (
          <section className="studio-section">
            <div className="studio-group-title">Ausgeben</div>
            <div className="studio-row">
              <button type="button" onClick={() => download(api.exportAll(), 'daedalus-themes.json')} disabled={api.custom.length === 0}>
                Alle eigenen sichern
              </button>
              <button type="button" onClick={() => download(api.exportOne(theme.id), `${theme.id}.json`)}>
                Aktuelles sichern
              </button>
              <button
                type="button"
                onClick={() => {
                  void navigator.clipboard?.writeText(api.exportOne(theme.id));
                  setNotice('Aktuelles Theme als JSON in die Zwischenablage kopiert.');
                }}
              >
                In die Zwischenablage
              </button>
            </div>
            {api.custom.length === 0 && <p className="studio-hint">Eingebaute Themes lassen sich einzeln sichern; „alle eigenen“ wird erst aktiv, wenn es welche gibt.</p>}

            <div className="studio-group-title">Einlesen</div>
            <textarea
              value={importText}
              onChange={(e) => setImportText(e.target.value)}
              placeholder='{"kind":"daedalus-themes","version":1,"themes":[ … ]}'
              rows={6}
              spellCheck={false}
              aria-label="Theme-JSON einfügen"
            />
            <div className="studio-row">
              <button
                type="button"
                disabled={!importText.trim()}
                onClick={() => {
                  const result = api.importText(importText);
                  setNotice(
                    result.added
                      ? `${result.added} Theme(s) übernommen.${result.problems.length ? ` ${result.problems.length} Hinweis(e) unten.` : ''}`
                      : 'Nichts übernommen — sieh dir die Hinweise an.'
                  );
                  if (result.added) setImportText('');
                }}
              >
                Übernehmen
              </button>
              <button type="button" onClick={() => setImportText('')} disabled={!importText}>
                Feld leeren
              </button>
            </div>
            <p className="studio-hint">
              Eingelesene Themes landen immer als Kopie mit eigener id. Ein Import kann ein eingebautes Theme nicht
              überschreiben.
            </p>
          </section>
        )}
      </div>
    </motion.aside>
  );
}
