/* Everything that arrives on demand and leaves completely.
 *
 * One door: ⌘K. It carries every action by name, `@` finds a node, and the
 * library and the settings are rows inside it rather than a second chrome.
 * A project without a compiled index offers no nodes and no pages — that is
 * not a styling choice, it is what fakedata.cjs refuses the build over. */

import { useEffect, useMemo, useRef, useState } from 'react';
import { fmt, projectViews, type Fixture, type GNode } from './data';
import type { Prefs } from './state';

export interface Row {
  key: string;
  verb: string;
  hint: string;
  disabled?: string;         // the reason, when it cannot run
  run: () => void;
}

/* ---------------------------------------------------------------- palette */

export function Palette({ fx, projectId, rows, nodes, onClose, onPick, seedText }: {
  fx: Fixture; projectId: string; rows: Row[]; nodes: GNode[];
  onClose: () => void; onPick: (r: Row) => void; seedText: string;
}) {
  const [q, setQ] = useState(seedText);
  const [i, setI] = useState(0);
  const ref = useRef<HTMLInputElement>(null);
  const indexed = projectId === fx.project;
  const name = fx.projects.find(p => p.id === projectId)?.name ?? projectId;

  useEffect(() => { ref.current?.focus(); }, []);

  const list = useMemo<Row[]>(() => {
    if (q.startsWith('@')) {
      if (!indexed) return [];
      const t = q.slice(1).trim().toLowerCase();
      return nodes
        .filter(n => !t || n.label.toLowerCase().includes(t))
        .slice(0, 7)
        .map(n => ({ key: n.id, verb: n.label, hint: `${n.plane} · ${n.kind}`, run: () => {} }));
    }
    const t = q.trim().toLowerCase();
    return rows.filter(r => !t || (r.verb + ' ' + r.hint).toLowerCase().includes(t)).slice(0, 7);
  }, [q, rows, nodes, indexed]);

  useEffect(() => { setI(0); }, [q]);

  const commit = (r: Row | undefined) => { if (r) onPick(r); };

  return (
    <div className="ov pal" onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <input
        id="palette-input" ref={ref} value={q} placeholder="What should happen?"
        aria-label="Command palette" autoComplete="off" spellCheck={false}
        onChange={e => setQ(e.target.value)}
        onKeyDown={e => {
          if (e.key === 'ArrowDown') { e.preventDefault(); setI(v => Math.min(list.length - 1, v + 1)); }
          else if (e.key === 'ArrowUp') { e.preventDefault(); setI(v => Math.max(0, v - 1)); }
          else if (e.key === 'Enter') { e.preventDefault(); commit(list[i]); }
        }}
      />
      <div className="plist">
        {list.length === 0 ? (
          <p>{q.startsWith('@')
            ? `No index has been compiled for ${name}, so it offers no nodes.`
            : 'Nothing here answers to that.'}</p>
        ) : list.map((r, k) => (
          <button
            key={r.key} type="button"
            className={'prow' + (k === i ? ' on' : '') + (r.disabled ? ' off' : '')}
            title={r.disabled ?? r.hint}
            onMouseEnter={() => setI(k)}
            onClick={() => commit(r)}
          >
            <span className="verb">{r.verb}</span>
            <span className="hint">{r.disabled ?? r.hint}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- library */

export function Library({ fx, projectId, page, setPage, onClose }: {
  fx: Fixture; projectId: string; page: string; setPage: (p: string) => void; onClose: () => void;
}) {
  const indexed = projectId === fx.project;
  const name = fx.projects.find(p => p.id === projectId)?.name ?? projectId;
  const kp = fx.knowledge_page;

  const body = useMemo(() => {
    if (page.startsWith('module:')) {
      const m = fx.library.module_pages.find(x => 'module:' + x.module === page);
      if (!m) return null;
      return {
        title: m.module,
        lines: [
          `Fan-in ${m.auto.fan_in}, fan-out ${m.auto.fan_out}, ${m.auto.churn_30d} changes in 30 days, complexity ${m.auto.complexity}. Measured by the indexer.`,
          m.notes || 'No note has been written on this module yet.',
        ],
      };
    }
    const w = fx.library.project_wiki.find(x => x.path === page);
    if (w && w.title === kp.title) {
      return { title: kp.title, lines: [kp.body, `${kp.provenance}. Open question: ${kp.open_question}.`, `Backlinks: ${kp.backlinks.join(', ')}.`] };
    }
    if (w) return { title: w.title, lines: [`${w.backlinks} pages link here. The fixture carries this page's title and its backlink count, not its text.`] };
    const g = fx.library.global.find(x => x.path === page);
    if (g) return { title: g.title, lines: ['This page is read by every project. The fixture carries its title and its path, not its text.'] };
    return null;
  }, [page, fx, kp]);

  return (
    <div className="ov lib" onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="libtree">
        <p className="tg" data-group="global">Read by every project</p>
        {fx.library.global.map(g => (
          <button key={g.path} type="button" className={'treeitem' + (page === g.path ? ' on' : '')} onClick={() => setPage(g.path)}>{g.title}</button>
        ))}
        <p className="tg" data-group="wiki">{name} wiki</p>
        {indexed
          ? fx.library.project_wiki.map(w => (
            <button key={w.path} type="button" className={'treeitem' + (page === w.path ? ' on' : '')} onClick={() => setPage(w.path)}>{w.title}</button>
          ))
          : <p className="empty">No pages for {name} yet.</p>}
        {indexed ? <p className="tg" data-group="modules">{name} modules</p> : null}
        {indexed ? fx.library.module_pages.map(m => (
          <button key={m.module} type="button" className={'treeitem' + (page === 'module:' + m.module ? ' on' : '')} onClick={() => setPage('module:' + m.module)}>{m.module}</button>
        )) : null}
      </div>
      <div className="libpage">
        {body ? <p className="lp-title">{body.title}</p> : <p className="lp-title">Nothing is open.</p>}
        {body ? body.lines.map((l, i) => <p key={i} className="lp-line">{l}</p>) : null}
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- settings */

export function Settings({ fx, prefs, setPrefs, onClose, say, reason }: {
  fx: Fixture; prefs: Prefs; setPrefs: (p: Partial<Prefs>) => void;
  onClose: () => void; say: (s: string | null) => void; reason: string | null;
}) {
  const p = projectViews(fx);
  return (
    <div className="ov set" onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="setcol">
        <p className="s-line">Route is <button type="button" className="w on" title="Which lane a mission goes to when you do not name one."
          onClick={() => setPrefs({ route: prefs.route === 'Auto' ? 'Claude' : prefs.route === 'Claude' ? 'Ollama (local)' : 'Auto' })}>{prefs.route}</button>, spending stops at <button type="button" className="w on"
            title="The ledger refuses the next charge once the ceiling is reached."
            onClick={() => setPrefs({ ceiling: prefs.ceiling === 2 ? 5 : prefs.ceiling === 5 ? 0.5 : 2 })}>${prefs.ceiling.toFixed(2)}</button>, and autonomy is {fx.settings.autonomy}.</p>

        <p className="s-line">Local models {prefs.localMayLeave ? 'may' : 'may not'} leave this machine — <button type="button" className="w"
          title="When off, a local lane resolves only to 127.0.0.1 and nothing it produces is sent anywhere."
          onClick={() => setPrefs({ localMayLeave: !prefs.localMayLeave })}>{prefs.localMayLeave ? 'keep them here' : 'let them out'}</button>.</p>

        <p className="s-line">Motion is <button type="button" className="w on" title="Off stills the room completely: no drift and no travelling light."
          onClick={() => setPrefs({ motion: prefs.motion === 'Calm' ? 'Off' : prefs.motion === 'Off' ? 'Full' : 'Calm' })}>{prefs.motion}</button>, and the kill switch is <button type="button" className="w on"
            title="Armed: every effect stops at the effect boundary on one keystroke."
            onClick={() => setPrefs({ killArmed: !prefs.killArmed })}>{prefs.killArmed ? 'armed' : 'off'}</button>.</p>

        <p className="s-line">Ikarus {prefs.rememberAcross ? 'remembers' : 'forgets'} across sessions, keeps {prefs.retention.toLowerCase()}, and {prefs.doNotRemember ? 'remembers nothing about this project' : 'remembers this project'} — <button type="button" className="w"
          title="Product memory only. Research adaptive memory is a separate store and this control does not reach it."
          onClick={() => setPrefs({ doNotRemember: !prefs.doNotRemember })}>change</button>.</p>

        {fx.lanes.map(l => (
          <p className="s-line lane" key={l.runtime}>
            {l.runtime} reads and proposes; writing is{' '}
            <button type="button" className={l.locked ? 'w off' : 'w on'}
              title={l.locked ? l.reason : 'This lane may write inside a mission; it is asked once per mission.'}
              onMouseEnter={() => l.locked && say(l.reason!)} onFocus={() => l.locked && say(l.reason!)} onMouseLeave={() => say(null)}
              onClick={() => l.locked && say(l.reason!)}>{l.write}</button>
            {l.host ? ` on ${l.host}` : ''}.
          </p>
        ))}

        {fx.settings.statements.map(s => <p className="s-said" key={s}>{s}</p>)}

        <p className="s-line">{p.filter(x => !x.indexed).length} of {p.length} projects carry no compiled index: {p.filter(x => !x.indexed).map(x => x.name).join(' and ')}. Nothing measured here is shown for them.</p>
        <p className="s-line">{fmt(fx.rim.budget.spent_tokens)} of {fmt(fx.rim.budget.cap_tokens)} tokens spent under the cap.</p>
        {reason ? <p className="reason">{reason}</p> : null}
      </div>
    </div>
  );
}
