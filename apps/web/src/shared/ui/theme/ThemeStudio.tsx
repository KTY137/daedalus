import { useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties, KeyboardEvent, ReactNode } from 'react';
import { motion } from 'framer-motion';
import {
  ArrowLeft,
  ArrowUpRight,
  Check,
  CheckCheck,
  Copy,
  Download,
  FileJson,
  Layers3,
  LayoutTemplate,
  Orbit,
  Palette,
  Pencil,
  RotateCcw,
  Sparkles,
  Trash2,
  Type,
  Upload,
  X
} from 'lucide-react';
import { useThemes } from './ThemeProvider';
import type { SceneEnvironmentId, ThemeColors, ThemeSpec } from './types';
import { drawerVariants, useReducedMotionPref } from '../motion';
import { SCENE_ENVIRONMENTS, sceneEnvironment, sceneEnvironmentProvenance } from '../scene/environments';
import { environmentImage } from '../scene/environmentImages';
import './studio.css';

// The rooms behind the glass (G1-UI-12). "Kein Raum" is a real option, not the
// absence of one: it is what every look had before rooms existed.
const ROOM_OPTIONS: ReadonlyArray<{ id: SceneEnvironmentId | undefined; name: string; note: string }> = [
  { id: undefined, name: 'Kein Raum', note: 'Nur deine Farben.' },
  ...SCENE_ENVIRONMENTS
];

// The existing ThemeProvider remains the only owner of selection and storage.
// Editing a built-in creates a copy; these controls only change presentation.
const COLOR_GROUPS: Array<{ title: string; keys: Array<keyof ThemeColors>; hint: string }> = [
  { title: 'Atmosphäre', keys: ['room', 'room2'], hint: 'Die beiden Farbtöne deines Hintergrunds.' },
  { title: 'Oberflächen', keys: ['surface', 'surface2'], hint: 'Die Materialfarbe deiner Panels und Karten.' },
  { title: 'Typografie', keys: ['ink', 'ink2', 'ink3'], hint: 'Von der Überschrift bis zum kleinen Detail.' },
  { title: 'Konturen', keys: ['line', 'line2'], hint: 'Feine Linien geben dem Glas seine Form.' },
  { title: 'Akzent', keys: ['accent', 'accentInk'], hint: 'Deine Signatur für Aktionen und Auswahl.' },
  { title: 'Status', keys: ['live', 'bad', 'ok'], hint: 'Aktivität, Fehler und bestandene Prüfungen.' },
  {
    title: 'Projektkarte',
    keys: ['node', 'node2', 'edge', 'edgeHot'],
    hint: 'Knoten, Verbindungen und hervorgehobene Pfade.'
  }
];

const COLOR_LABELS: Record<keyof ThemeColors, string> = {
  room: 'Hintergrund',
  room2: 'Verlauf',
  surface: 'Fläche',
  surface2: 'Vertiefte Fläche',
  ink: 'Primäre Schrift',
  ink2: 'Sekundäre Schrift',
  ink3: 'Beschriftungen',
  line: 'Kontur',
  line2: 'Feine Kontur',
  accent: 'Akzentfarbe',
  accentInk: 'Schrift auf Akzent',
  live: 'Aktiv',
  bad: 'Fehler',
  ok: 'Bestanden',
  node: 'Knoten',
  node2: 'Knoten · zweite Ebene',
  edge: 'Verbindung',
  edgeHot: 'Aktiver Pfad'
};

const TABS = [
  { id: 'themes', label: 'Looks', icon: Sparkles },
  { id: 'farbe', label: 'Farben', icon: Palette },
  { id: 'form', label: 'Material', icon: Layers3 },
  { id: 'schrift', label: 'Schrift', icon: Type },
  { id: 'buehne', label: 'Szene', icon: Orbit },
  { id: 'aufbau', label: 'Layout', icon: LayoutTemplate },
  { id: 'daten', label: 'Dateien', icon: FileJson }
] as const;
type StudioTab = (typeof TABS)[number]['id'];
const HEX = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i;

function ThemePreview({ theme, compact = false }: { theme: ThemeSpec; compact?: boolean }) {
  const c = theme.colors;
  const style = {
    '--preview-room': c.room,
    '--preview-room2': c.room2,
    '--preview-accent': c.accent,
    '--preview-ink': c.ink,
    '--preview-surface': c.surface,
    '--preview-line': c.line,
    '--preview-radius': `${Math.min(14, theme.form.radius)}px`
  } as CSSProperties;
  return (
    <span className={`theme-preview${compact ? ' compact' : ''}`} style={style} aria-hidden="true">
      <span className="theme-preview-glow" />
      <span className="theme-preview-orbit" />
      <span className="theme-preview-sphere" />
      <span className="theme-preview-window">
        <span className="theme-preview-dots">
          <i />
          <i />
          <i />
        </span>
        <span className="theme-preview-line long" />
        <span className="theme-preview-line" />
        <span className="theme-preview-button" />
      </span>
    </span>
  );
}

function ColorField({ label, value, onChange }: { label: string; value: string; onChange: (next: string) => void }) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const valid = typeof CSS === 'undefined' || CSS.supports('color', draft.trim());
  const isHex = HEX.test(value.trim());
  const pickerValue =
    value.trim().length === 4
      ? `#${value
          .trim()
          .slice(1)
          .split('')
          .map((c) => c + c)
          .join('')}`
      : value.trim();
  return (
    <label className="field color">
      <span className="field-label">{label}</span>
      <span className="color-row">
        {isHex ? (
          <input
            type="color"
            value={pickerValue}
            onChange={(e) => onChange(e.target.value)}
            aria-label={`${label} wählen`}
          />
        ) : (
          <span className="color-chip" style={{ background: value }} aria-hidden="true" />
        )}
        <input
          type="text"
          value={draft}
          spellCheck={false}
          aria-label={`${label} als CSS-Farbe`}
          aria-invalid={!valid}
          onChange={(e) => {
            setDraft(e.target.value);
            if (CSS.supports('color', e.target.value.trim())) onChange(e.target.value);
          }}
          onBlur={() => {
            if (!valid) setDraft(value);
          }}
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
  suffix = '',
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
          {Number(value.toFixed(3))}
          {suffix}
        </b>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        aria-valuetext={`${Number(value.toFixed(3))}${suffix}`}
        style={{ '--range-fill': `${((value - min) / (max - min)) * 100}%` } as CSSProperties}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  );
}

function moveSelection(
  event: KeyboardEvent<HTMLButtonElement>,
  index: number,
  count: number,
  select: (index: number) => void
) {
  let next: number;
  if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (index + 1) % count;
  else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = (index - 1 + count) % count;
  else if (event.key === 'Home') next = 0;
  else if (event.key === 'End') next = count - 1;
  else return;
  event.preventDefault();
  select(next);
  event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('button')[next]?.focus();
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
        {options.map(([key, text], index) => (
          <button
            key={key}
            type="button"
            role="radio"
            aria-checked={value === key}
            tabIndex={value === key || (!options.some(([k]) => k === value) && index === 0) ? 0 : -1}
            className={value === key ? 'on' : ''}
            onClick={() => onChange(key)}
            onKeyDown={(e) => moveSelection(e, index, options.length, (next) => onChange(options[next][0]))}
          >
            {text}
          </button>
        ))}
      </div>
    </div>
  );
}

function Section({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="studio-section">
      <div className="studio-section-heading">
        <h3>{title}</h3>
        {hint && <p className="studio-hint">{hint}</p>}
      </div>
      {children}
    </section>
  );
}

export function ThemeStudio({ open, onClose }: { open: boolean; onClose: () => void }) {
  const api = useThemes();
  const { theme } = api;
  const [tab, setTab] = useState<StudioTab>('themes');
  const [importText, setImportText] = useState('');
  const [notice, setNotice] = useState('');
  const [renaming, setRenaming] = useState('');
  const panel = useRef<HTMLElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const reduced = useReducedMotionPref();
  const drawer = useMemo(() => drawerVariants(reduced), [reduced]);
  const scene = theme.scene ?? { enabled: false, intensity: 0.7, speed: 0.5 };

  useEffect(() => {
    body.current?.scrollTo({ top: 0 });
  }, [tab]);

  useEffect(() => {
    const node = panel.current;
    if (!node) return;
    node.inert = !open;
    if (!open) {
      setNotice('');
      setRenaming('');
      return;
    }
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeButton.current?.focus({ preventScroll: true });
    return () => {
      if (node.contains(document.activeElement)) trigger?.focus({ preventScroll: true });
    };
  }, [open]);

  const edit = (patch: Parameters<typeof api.update>[0]) => {
    api.update(patch);
    if (api.isBuiltIn) setNotice('Deine eigene Kopie ist angelegt. Änderungen werden automatisch gespeichert.');
  };

  const download = (contents: string, name: string) => {
    const url = URL.createObjectURL(new Blob([contents], { type: 'application/json' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    a.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const importContents = (contents: string) => {
    const result = api.importText(contents);
    setNotice(
      result.added
        ? `${result.added} Theme${result.added === 1 ? '' : 's'} importiert.${result.problems.length ? ' Bitte die Hinweise beachten.' : ''}`
        : 'Kein Theme importiert. Bitte die Hinweise beachten.'
    );
    if (result.added) setImportText('');
  };

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
      role="dialog"
      aria-modal="false"
      onKeyDown={(e) => {
        if (e.key === 'Escape' && !e.defaultPrevented) {
          e.stopPropagation();
          onClose();
        }
      }}
    >
      <header className="studio-head">
        <div>
          <h2>Theme Studio</h2>
        </div>
        <button
          ref={closeButton}
          type="button"
          className="studio-close"
          onClick={onClose}
          aria-label="Studio schließen"
        >
          <X size={19} />
        </button>
      </header>

      <div className="studio-active">
        <ThemePreview theme={theme} compact />
        <div className="studio-active-copy">
          <span className="studio-active-label">Aktueller Look</span>
          <b>{theme.name}</b>
          <span className="studio-active-note">{theme.note}</span>
        </div>
        <span className="studio-live">
          <span /> Live
        </span>
      </div>

      <nav className="studio-tabs" role="tablist" aria-label="Theme bearbeiten">
        {TABS.map(({ id, label, icon: Icon }, index) => (
          <button
            key={id}
            id={`studio-tab-${id}`}
            type="button"
            role="tab"
            aria-selected={tab === id}
            aria-controls={`studio-panel-${id}`}
            tabIndex={tab === id ? 0 : -1}
            className={tab === id ? 'on' : ''}
            onClick={() => setTab(id)}
            onKeyDown={(e) => moveSelection(e, index, TABS.length, (next) => setTab(TABS[next].id))}
          >
            <Icon size={17} strokeWidth={1.7} />
            <span>{label}</span>
          </button>
        ))}
      </nav>

      <div
        ref={body}
        className="studio-body"
        role="tabpanel"
        id={`studio-panel-${tab}`}
        aria-labelledby={`studio-tab-${tab}`}
        tabIndex={0}
      >
        {notice && (
          <p className="studio-note" role="status">
            <CheckCheck size={16} />
            {notice}
          </p>
        )}
        {api.saveError && (
          <p className="studio-note bad" role="alert">
            Speichern fehlgeschlagen: {api.saveError}
          </p>
        )}
        {api.problems.length > 0 && (
          <ul className="studio-problems" aria-label="Theme-Hinweise">
            {api.problems.map((p, i) => (
              <li key={i}>
                <code>{p.id}</code> {p.message}
              </li>
            ))}
          </ul>
        )}

        {tab !== 'themes' && (
          <button type="button" className="studio-back" onClick={() => setTab('themes')}>
            <ArrowLeft size={14} /> Alle Looks
          </button>
        )}

        {tab === 'themes' && (
          <>
            <div className="studio-collection-heading">
              <div>
                <h3>Eingebaute Looks</h3>
                <p>Ein Klick wechselt sofort; das Original bleibt erhalten.</p>
              </div>
              <span>{api.builtIns.length} Looks</span>
            </div>
            <ul className="theme-list built-in-list">
              {api.builtIns.map((t) => (
                <li key={t.id} className={t.id === theme.id ? 'on' : ''}>
                  <button
                    type="button"
                    className="theme-pick"
                    onClick={() => api.select(t.id)}
                    aria-pressed={t.id === theme.id}
                    aria-label={`${t.name} auswählen`}
                  >
                    <ThemePreview theme={t} />
                    <span className="theme-card-copy">
                      <span className="theme-name">{t.name}</span>
                      <span className="theme-note">{t.note}</span>
                    </span>
                    {t.id === theme.id && (
                      <span className="theme-selected">
                        <Check size={12} strokeWidth={3} />
                      </span>
                    )}
                  </button>
                  <button
                    type="button"
                    className="theme-copy"
                    onClick={() => {
                      api.duplicate(t.id);
                      setNotice('Deine Kopie ist bereit zum Gestalten.');
                    }}
                    aria-label={`${t.name} kopieren`}
                    title="Eigene Kopie erstellen"
                  >
                    <Copy size={13} />
                  </button>
                </li>
              ))}
            </ul>
            <div className="studio-collection-heading custom-heading">
              <div>
                <h3>Deine Looks</h3>
                <p>Kopien, die du bearbeitet hast; automatisch gespeichert.</p>
              </div>
              <span>{api.custom.length}</span>
            </div>
            {api.custom.length === 0 && (
              <div className="studio-empty">
                <span className="studio-empty-icon">
                  <Pencil size={18} />
                </span>
                <b>Mach es zu deinem.</b>
                <p>
                  Passe Farben, Glas oder die Szene an.
                  <br />
                  Dein eigener Look entsteht automatisch.
                </p>
                <button type="button" onClick={() => setTab('form')}>
                  Look gestalten <ArrowUpRight size={14} />
                </button>
              </div>
            )}
            <ul className="theme-list custom-theme-list">
              {api.custom.map((t) => (
                <li key={t.id} className={t.id === theme.id ? 'on' : ''}>
                  <button
                    type="button"
                    className="theme-pick"
                    onClick={() => api.select(t.id)}
                    aria-pressed={t.id === theme.id}
                    aria-label={`${t.name} auswählen`}
                  >
                    <ThemePreview theme={t} compact />
                    <span className="theme-card-copy">
                      <span className="theme-name">{t.name}</span>
                      <span className="theme-note">
                        {t.editedAt
                          ? new Date(t.editedAt).toLocaleDateString('de-DE', { day: 'numeric', month: 'short' })
                          : 'Eigener Look'}
                      </span>
                    </span>
                    {t.id === theme.id && <Check size={16} className="theme-custom-check" />}
                  </button>
                  {renaming === t.id && (
                    <input
                      className="theme-rename"
                      autoFocus
                      aria-label="Theme umbenennen"
                      defaultValue={t.name}
                      onBlur={(e) => {
                        if (renaming === t.id) api.rename(t.id, e.target.value);
                        setRenaming('');
                      }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') e.currentTarget.blur();
                        if (e.key === 'Escape') {
                          e.preventDefault();
                          e.stopPropagation();
                          setRenaming('');
                        }
                      }}
                    />
                  )}
                  <div className="theme-acts">
                    <button type="button" onClick={() => setRenaming(t.id)}>
                      <Pencil size={12} /> Name
                    </button>
                    <button type="button" onClick={() => api.duplicate(t.id)}>
                      <Copy size={12} /> Kopieren
                    </button>
                    {t.forkedFrom && api.builtIns.some((b) => b.id === t.forkedFrom) && (
                      <button
                        type="button"
                        onClick={() => {
                          api.revert(t.id);
                          setNotice('Look auf das Original zurückgesetzt.');
                        }}
                        title="Auf das eingebaute Original zurücksetzen"
                      >
                        <RotateCcw size={12} /> Reset
                      </button>
                    )}
                    <button
                      type="button"
                      className="danger"
                      onClick={() => api.remove(t.id)}
                      aria-label={`${t.name} löschen`}
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}

        {tab === 'farbe' &&
          COLOR_GROUPS.map((group) => (
            <Section key={group.title} title={group.title} hint={group.hint}>
              <div className="studio-color-grid">
                {group.keys.map((key) => (
                  <ColorField
                    key={key}
                    label={COLOR_LABELS[key]}
                    value={theme.colors[key]}
                    onChange={(next) => edit({ colors: { [key]: next } })}
                  />
                ))}
              </div>
            </Section>
          ))}

        {tab === 'form' && (
          <>
            <Section title="Material & Licht" hint="Von klarem Glas bis zu ruhigen, matten Flächen.">
              <div className={`studio-material-preview material-${theme.form.material}`} aria-hidden="true">
                <span className="material-orb" />
                <span className="material-sheet">
                  <Layers3 size={23} />
                  <span>
                    {theme.form.material === 'glass'
                      ? 'Liquid clarity.'
                      : theme.form.material === 'paper'
                        ? 'Quietly confident.'
                        : 'Simply focused.'}
                  </span>
                  <i />
                </span>
              </div>
              <Choice
                label="Oberfläche"
                value={theme.form.material}
                options={[
                  ['glass', 'Glas'],
                  ['flat', 'Matt'],
                  ['paper', 'Papier']
                ]}
                onChange={(material) => edit({ form: { material } })}
              />
              {theme.form.material === 'glass' && (
                <>
                  <Range
                    label="Glasunschärfe"
                    value={theme.form.blur}
                    min={0}
                    max={48}
                    step={1}
                    suffix=" px"
                    onChange={(blur) => edit({ form: { blur } })}
                  />
                  <Range
                    label="Deckkraft"
                    value={Math.round(theme.form.alpha * 100)}
                    min={4}
                    max={100}
                    step={1}
                    suffix=" %"
                    onChange={(alpha) => edit({ form: { alpha: alpha / 100 } })}
                  />
                </>
              )}
              <Range
                label="Schattentiefe"
                value={theme.form.elevation}
                min={0}
                max={2}
                step={1}
                onChange={(elevation) => edit({ form: { elevation } })}
              />
            </Section>
            <Section title="Form & Raum">
              <Range
                label="Eckradius"
                value={theme.form.radius}
                min={0}
                max={32}
                step={1}
                suffix=" px"
                onChange={(radius) => edit({ form: { radius } })}
              />
              <Range
                label="Rahmenstärke"
                value={theme.form.border}
                min={0}
                max={3}
                step={0.5}
                suffix=" px"
                onChange={(border) => edit({ form: { border } })}
              />
              <Range
                label="Abstandseinheit"
                value={theme.form.unit}
                min={5}
                max={14}
                step={0.5}
                suffix=" px"
                onChange={(unit) => edit({ form: { unit } })}
              />
              <Choice
                label="Browser-Farbschema"
                value={theme.base}
                options={[
                  ['dark', 'Dunkel'],
                  ['light', 'Hell']
                ]}
                onChange={(base) => edit({ base })}
              />
              <p className="studio-hint">
                Passt native Eingabefelder und Scrollleisten an. Helle und dunkle Farbwelten findest du unter Looks.
              </p>
            </Section>
          </>
        )}

        {tab === 'schrift' && (
          <>
            <div className="studio-type-preview">
              <span>Aa</span>
              <p>Woran arbeiten wir?</p>
              <small>Nachricht an Ikarus … („/“ für Befehle)</small>
            </div>
            <Section title="Schriftfamilien" hint="Verwendet deine lokal verfügbaren Schriften.">
              {(
                [
                  ['display', 'Überschriften'],
                  ['body', 'Fließtext'],
                  ['mono', 'Code & Bezeichner']
                ] as const
              ).map(([key, label]) => (
                <label key={key} className="field">
                  <span className="field-label">{label}</span>
                  <input
                    type="text"
                    value={theme.type[key]}
                    spellCheck={false}
                    onChange={(e) => edit({ type: { [key]: e.target.value } })}
                  />
                </label>
              ))}
            </Section>
            <Section title="Feinschliff">
              <Range
                label="Grundgröße"
                value={theme.type.size}
                min={11}
                max={20}
                step={0.5}
                suffix=" px"
                onChange={(size) => edit({ type: { size } })}
              />
              <Range
                label="Größenverhältnis"
                value={theme.type.scale}
                min={1.05}
                max={1.5}
                step={0.01}
                onChange={(scale) => edit({ type: { scale } })}
              />
              <Range
                label="Stärke der Überschriften"
                value={theme.type.displayWeight}
                min={300}
                max={800}
                step={100}
                onChange={(displayWeight) => edit({ type: { displayWeight } })}
              />
              <Range
                label="Laufweite"
                value={theme.type.displayTracking}
                min={-0.04}
                max={0.08}
                step={0.005}
                suffix=" em"
                onChange={(displayTracking) => edit({ type: { displayTracking } })}
              />
              <Choice
                label="Überschriften mit Serifen"
                value={theme.type.displaySerif ? 'ja' : 'nein'}
                options={[
                  ['ja', 'Ja'],
                  ['nein', 'Nein']
                ]}
                onChange={(v) => edit({ type: { displaySerif: v === 'ja' } })}
              />
            </Section>
          </>
        )}

        {tab === 'buehne' && (
          <>
            <Section title="Dein Raum." hint="Wähle eine Umgebung für dein Glas — als ruhiges Bild oder mit lebendiger 3D-Perspektive.">
              <div className="field choice">
                <span className="field-label">
                  Umgebung
                  <b>{scene.environment ? sceneEnvironment(scene.environment).name : 'Kein Raum'}</b>
                </span>
                <div className="room-grid" role="radiogroup" aria-label="Umgebung">
                  {ROOM_OPTIONS.map((option, index) => {
                    const on = option.id === scene.environment;
                    const thumb = option.id ? environmentImage(option.id, 'thumb') : undefined;
                    const rendered = !option.id || !!thumb;
                    const choose = (next: number) => {
                      const target = ROOM_OPTIONS[next];
                      if (target.id && !environmentImage(target.id, 'thumb')) return;
                      edit({ scene: { ...scene, environment: target.id } });
                    };
                    return (
                      <button
                        key={option.id ?? 'none'}
                        type="button"
                        role="radio"
                        aria-checked={on}
                        aria-disabled={rendered ? undefined : true}
                        aria-label={option.name}
                        tabIndex={on ? 0 : -1}
                        className={`room-tile${on ? ' on' : ''}`}
                        onClick={() => choose(index)}
                        onKeyDown={(e) => moveSelection(e, index, ROOM_OPTIONS.length, choose)}
                      >
                        {option.id ? (
                          thumb ? (
                            <img src={thumb} alt="" loading="lazy" decoding="async" draggable={false} />
                          ) : (
                            <span className="room-missing">noch nicht gerendert</span>
                          )
                        ) : (
                          <span className="room-none" aria-hidden="true" />
                        )}
                        <span className="room-copy">
                          <span className="room-name">{option.name}</span>
                          <span className="room-note">{option.note}</span>
                        </span>
                        {on && (
                          <span className="room-selected">
                            <Check size={12} strokeWidth={3} />
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
              {scene.environment && <>
                <Choice label="Darstellung" value={scene.rendering ?? 'image'}
                  options={[["image", "Bild"], ["interactive", "Interaktives 3D"]]}
                  onChange={(rendering) => edit({ scene: { ...scene, rendering } })} />
                <Range label="Licht" value={Math.round((scene.exposure ?? 1) * 100)} min={50} max={160} step={5} suffix=" %"
                  onChange={(value) => edit({ scene: { ...scene, exposure: value / 100 } })} />
                {scene.rendering === 'interactive' && <p className="studio-hint">Die Perspektive folgt deiner Maus. 3D benötigt mehr Grafikleistung; bei Ladeproblemen bleibt das Bild sichtbar.</p>}
              </>}
              {scene.environment && (() => {
                const room = sceneEnvironment(scene.environment);
                const origin = sceneEnvironmentProvenance(scene.environment);
                const mismatch = room.base !== theme.base;
                return (
                  <>
                    {origin && scene.rendering !== 'interactive' && (
                      <p className="studio-hint room-provenance">
                        {origin.quality === 'draft' ? 'Entwurf' : 'Final'} · Blender {origin.blender ?? '?'} · {origin.samples ?? '?'} Samples ·{' '}
                        {origin.image.width}×{origin.image.height}
                      </p>
                    )}
                    {mismatch && (
                      <p className="studio-hint">
                        {room.base === 'dark' ? 'Ein dunkler Raum hinter einem hellen Look' : 'Ein heller Raum hinter einem dunklen Look'}
                        {' — '}senke die Intensität, wenn Text außerhalb der Panels schwer lesbar wird.
                      </p>
                    )}
                  </>
                );
              })()}
            </Section>
            <Section title="Deine dritte Dimension." hint="Eine räumliche Lichtskulptur hinter deinem Workspace.">
              <div className="studio-scene-preview" aria-hidden="true">
                <ThemePreview theme={theme} />
                <span>Atmosphäre, die sich bewegt.</span>
              </div>
              <Choice
                label="3D-Szene"
                value={scene.enabled ? 'an' : 'aus'}
                options={[
                  ['an', 'An'],
                  ['aus', 'Aus']
                ]}
                onChange={(v) => edit({ scene: { ...scene, enabled: v === 'an' } })}
              />
              {(scene.enabled || scene.environment) && (
                <>
                  <Range
                    label="Intensität"
                    value={Math.round(scene.intensity * 100)}
                    min={0}
                    max={100}
                    step={5}
                    suffix=" %"
                    onChange={(intensity) => edit({ scene: { ...scene, intensity: intensity / 100 } })}
                  />
                  <Range
                    label="Bewegung"
                    value={Math.round(scene.speed * 100)}
                    min={0}
                    max={100}
                    step={5}
                    suffix=" %"
                    onChange={(speed) => edit({ scene: { ...scene, speed: speed / 100 } })}
                  />
                </>
              )}
              {reduced && (
                <p className="studio-hint">Dein System reduziert Bewegung. Die Szene bleibt deshalb ruhig.</p>
              )}
            </Section>
            <Section title="Projektkarte" hint="Gestalte die Darstellung deiner vorhandenen Projektdaten.">
              <Choice
                label="Anordnung"
                value={theme.stage.layout}
                options={[
                  ['forest', 'Wald'],
                  ['stars', 'Sterne'],
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
                label="Verbindungen in Ruhe"
                value={theme.stage.backboneOnly ? 'ja' : 'nein'}
                options={[
                  ['ja', 'Nur Hauptpfade'],
                  ['nein', 'Alle']
                ]}
                onChange={(v) => edit({ stage: { backboneOnly: v === 'ja' } })}
              />
              <Range
                label="Kantenkrümmung"
                value={theme.stage.curve}
                min={0}
                max={1}
                step={0.02}
                onChange={(curve) => edit({ stage: { curve } })}
              />
              <Range
                label="Knotengröße nach Importeuren"
                value={theme.stage.sizeByFanIn}
                min={0}
                max={1.4}
                step={0.05}
                onChange={(sizeByFanIn) => edit({ stage: { sizeByFanIn } })}
              />
              <Range
                label="Leuchten"
                value={theme.stage.glow}
                min={0}
                max={1}
                step={0.05}
                onChange={(glow) => edit({ stage: { glow } })}
              />
            </Section>
          </>
        )}

        {tab === 'aufbau' && (
          <Section title="Alles an seinem Platz." hint="Gib deinem Gespräch den passenden Rahmen.">
            <Choice
              label="Kopfbereich"
              value={theme.composition.chrome}
              options={[
                ['bar', 'Kompakte Leiste'],
                ['masthead', 'Großer Titel']
              ]}
              onChange={(chrome) => edit({ composition: { chrome } })}
            />
            <Choice
              label="Gesprächsseite"
              value={theme.composition.chat}
              options={[
                ['column', 'Mit Seitenspalte'],
                ['flow', 'Ein Textfluss']
              ]}
              onChange={(chat) => edit({ composition: { chat } })}
            />
          </Section>
        )}

        {tab === 'daten' && (
          <>
            <Section
              title="Dein Look. Zum Mitnehmen."
              hint="Sichere deine Themes als JSON oder teile sie über die Zwischenablage."
            >
              <div className="studio-row">
                <button
                  type="button"
                  className="primary"
                  onClick={() => download(api.exportOne(theme.id), `${theme.id}.json`)}
                >
                  <Download size={15} /> Aktuellen Look sichern
                </button>
                <button
                  type="button"
                  onClick={async () => {
                    try {
                      if (!navigator.clipboard) throw new Error('Clipboard unavailable');
                      await navigator.clipboard.writeText(api.exportOne(theme.id));
                      setNotice('Theme-JSON in die Zwischenablage kopiert.');
                    } catch {
                      setNotice('Kopieren nicht möglich. Du kannst den Look als Datei sichern.');
                    }
                  }}
                >
                  <Copy size={15} /> Kopieren
                </button>
                <button
                  type="button"
                  onClick={() => download(api.exportAll(), 'daedalus-themes.json')}
                  disabled={api.custom.length === 0}
                >
                  <Download size={15} /> Alle eigenen sichern ({api.custom.length})
                </button>
              </div>
            </Section>
            <Section title="Looks importieren" hint="Öffne eine Theme-Datei oder füge ihren JSON-Inhalt ein.">
              <input
                ref={fileInput}
                type="file"
                accept=".json,application/json"
                className="studio-file-input"
                tabIndex={-1}
                aria-label="Theme-Datei auswählen"
                onChange={async (e) => {
                  const file = e.target.files?.[0];
                  e.target.value = '';
                  if (!file) return;
                  try {
                    importContents(await file.text());
                  } catch {
                    setNotice('Die Datei konnte nicht gelesen werden.');
                  }
                }}
              />
              <button type="button" className="studio-import-file" onClick={() => fileInput.current?.click()}>
                <Upload size={21} />
                <span>
                  Theme-Datei auswählen<small>JSON-Datei von diesem Gerät</small>
                </span>
                <ArrowUpRight size={16} />
              </button>
              <textarea
                value={importText}
                onChange={(e) => setImportText(e.target.value)}
                placeholder={'{\n  "kind": "daedalus-themes",\n  "version": 1,\n  "themes": […]\n}'}
                rows={6}
                spellCheck={false}
                aria-label="Theme-JSON einfügen"
              />
              <div className="studio-row">
                <button
                  type="button"
                  className="primary"
                  disabled={!importText.trim()}
                  onClick={() => importContents(importText)}
                >
                  <Upload size={14} /> Importieren
                </button>
                <button type="button" onClick={() => setImportText('')} disabled={!importText}>
                  Leeren
                </button>
              </div>
              <p className="studio-hint">Importierte Looks werden als eigene Kopie hinzugefügt.</p>
            </Section>
          </>
        )}
      </div>

      <footer className="studio-footer">
        <span>
          <span className={`studio-save-dot${api.saveError ? ' error' : ''}`} />
          {api.saveError
            ? 'Nicht gespeichert'
            : api.isBuiltIn
              ? 'Original · beim Bearbeiten entsteht eine Kopie'
              : 'Änderungen werden lokal gespeichert'}
        </span>
        <button type="button" onClick={onClose}>
          Fertig <Check size={14} />
        </button>
      </footer>
    </motion.aside>
  );
}
