/* The frame: one toolbar, one sidebar, one ornament, one inspector, one status
 * line. The skeleton is Sequoia's — every thing has its own place, so nothing
 * has to be laid over anything else — and the material is visionOS glass: the
 * panels are windows floating over the room, not tiles on a surface.
 *
 * Codex's objections to the glass are treated as a specification: full project
 * names and no placeholder glyphs, nothing truncated, one navigation system
 * and no second dock, text on glass at medium weight and measured AA contrast,
 * hierarchy from layering rather than from atmosphere. */

import { useMemo } from 'react';
import {
  allEdges, measuredCost, PLANE_LABEL, projectViews, wikiPathFor,
  type Depth, type Fixture, type Lens, type ViewMode,
} from './data';
/* eslint-disable @typescript-eslint/no-unused-vars */

/* ---------------------------------------------------------------- top bar */

export function TopBar({ fx, spendText, onSearch }:
  { fx: Fixture; spendText: string; onSearch: () => void }) {
  return (
    <header className="topbar">
      <p className="tb-id">{fx.projects.find(p => p.active)?.name ?? fx.project} · revision {fx.revision} · {fx.gate}</p>
      <button type="button" className="tb-search" onClick={onSearch} data-kbd="⌘K">Search or run a command</button>
      <p className="tb-spend">{spendText}</p>
    </header>
  );
}

/* ---------------------------------------------------------------- sidebar */

export function Sidebar({ fx, projectId, view, screen, onProject, onView, onScreen, onSettings }: {
  fx: Fixture; projectId: string; view: ViewMode; screen: 'cockpit' | 'library';
  onProject: (id: string) => void; onView: (v: ViewMode) => void;
  onScreen: (s: 'cockpit' | 'library') => void; onSettings: () => void;
}) {
  const ps = projectViews(fx);
  return (
    <nav className="panel side">
      <p className="grp">Projects</p>
      {ps.map(p => (
        <button key={p.id} type="button"
          className={'row' + (p.id === projectId ? ' on' : '')}
          onClick={() => onProject(p.id)}
          title={p.indexed
            ? `${p.modules} modules indexed · ${p.islands} islands · ${p.dark} dark`
            : 'No index has been compiled for this project.'}>
          {p.name}<span className="ct">{p.indexed ? p.modules : '—'}</span>
        </button>
      ))}
      <p className="grp">Views</p>
      <button type="button" className={'row' + (screen === 'cockpit' && view === 'spatial' ? ' on' : '')}
        onClick={() => { onScreen('cockpit'); onView('spatial'); }}
        title="The four planes as four bodies of nodes, turning in the room.">Constellation</button>
      <button type="button" className={'row' + (screen === 'cockpit' && view === 'ordered' ? ' on' : '')}
        onClick={() => { onScreen('cockpit'); onView('ordered'); }}
        title="The same nodes, ranked into one ordered column.">Ordered</button>
      <button type="button" className={'row' + (screen === 'library' ? ' on' : '')}
        onClick={() => onScreen('library')}
        title="Pages this project and the global library carry.">Knowledge library</button>
      <button type="button" className="row foot" onClick={onSettings}
        title="Route, lanes, memory, motion.">Settings<span className="ct">⌘,</span></button>
    </nav>
  );
}

/* -------------------------------------------------------------- ornament */

export interface OrnProps {
  view: ViewMode; lens: Lens; depth: Depth; hasSelection: boolean;
  reason: string | null;
  setView: (v: ViewMode) => void;
  setLens: (l: Lens) => void;
  cycleDepth: () => void;
  reset: () => void;
  say: (text: string | null) => void;
}

/** Controls float below the stage and overlap its lower edge, the way a
 *  visionOS ornament does. They are visible at rest: an affordance you have to
 *  discover by hovering is an affordance most readers never find. */
export function Ornament(c: OrnProps) {
  const depthWord = c.depth === 0 ? 'all' : String(c.depth);
  const depthWhy = c.hasSelection
    ? 'How far the neighbourhood reaches from the selected node.'
    : 'Depth needs a selected node: the neighbourhood is drawn around it.';
  return (
    <div className="orn">
      <button type="button" className={c.view === 'spatial' ? 'w on' : 'w'} onClick={() => c.setView('spatial')}
        title="The four planes as four bodies of nodes.">Spatial</button>
      <button type="button" className={c.view === 'ordered' ? 'w on' : 'w'} onClick={() => c.setView('ordered')}
        title="The same nodes, ranked into one ordered column.">Ordered</button>
      <span className="sep" />
      <button type="button" className={c.hasSelection ? 'w' : 'w off'} title={depthWhy}
        onMouseEnter={() => !c.hasSelection && c.say(depthWhy)}
        onFocus={() => !c.hasSelection && c.say(depthWhy)}
        onMouseLeave={() => c.say(null)}
        onClick={() => (c.hasSelection ? c.cycleDepth() : c.say(depthWhy))}>Depth {depthWord}</button>
      <button type="button" className="w" onClick={c.reset} title="Back to the composed view.">Reset</button>
    </div>
  );
}

/* ------------------------------------------------------------- inspector */

export function Inspector({ fx, id, onOpenPage, onAsk, say, reason }: {
  fx: Fixture; id: string | null;
  onOpenPage: (path: string) => void;
  onAsk: (label: string) => void;
  say: (text: string | null) => void;
  reason: string | null;
}) {
  const edges = useMemo(() => allEdges(fx), [fx]);
  const cost = useMemo(() => measuredCost(fx), [fx]);
  const n = id ? fx.graph.nodes.find(x => x.id === id) : null;
  const kp = fx.knowledge_page;

  if (!n) {
    return (
      <aside className="panel insp">
        <p className="ip-eyebrow">Knowledge</p>
        <p className="ip-title">{kp.title}</p>
        <p className="ip-kind">{kp.plane} · {kp.kind}</p>
        <p className="ip-body">{kp.body}</p>
        <p className="ip-meta">{kp.provenance}</p>
        <p className="ip-meta">Open question: {kp.open_question}.</p>
        <p className="ip-eyebrow2">Linked from</p>
        <p className="ip-links">{kp.backlinks.join(' · ')}</p>
      </aside>
    );
  }

  const mine = edges.filter(e => e.s === id || e.t === id);
  const verified = mine.filter(e => e.verified).length;
  const c = cost[n.id];
  const page = wikiPathFor(fx, n);
  const noPage = 'The index holds no page for this node.';
  const note = fx.library.module_pages.find(m => m.module === n.label)?.notes;
  return (
    <aside className="panel insp">
      <p className="ip-eyebrow">Selection</p>
      <p className="ip-title mono">{n.label}</p>
      <p className="ip-kind">{PLANE_LABEL[n.plane]} · {n.kind}</p>
      <p className="ip-body">
        {mine.length} relations in the index — {verified} verified
        {mine.length - verified ? `, ${mine.length - verified} proposed and not yet checked` : ', none proposed'}.
        {' '}{c
          ? `Fan-in ${c.fan_in}, fan-out ${c.fan_out}, ${c.churn_30d} changes in 30 days, complexity ${c.complexity}.`
          : 'The index records no measured cost for it.'}
      </p>
      {note ? <p className="ip-note">{note}</p> : null}
      <p className="ip-acts">
        <button type="button" className={page ? 'w' : 'w off'} title={page ? 'Open its page in the library.' : noPage}
          onMouseEnter={() => !page && say(noPage)} onFocus={() => !page && say(noPage)} onMouseLeave={() => say(null)}
          onClick={() => (page ? onOpenPage(page) : say(noPage))}>Open page</button>
        <button type="button" className="w" title="Puts the question in the composer; it does not send it for you."
          onClick={() => onAsk(n.label)}>Ask about this</button>
      </p>
      {reason ? <p className="reason">{reason}</p> : null}
    </aside>
  );
}

/* ------------------------------------------------------------ status bar */

export function StatusBar({ fx, killArmed, localMayLeave, indexed, name }: {
  fx: Fixture; killArmed: boolean; localMayLeave: boolean; indexed: boolean; name: string;
}) {
  if (!indexed) {
    return (
      <footer className="statusbar">
        <span>{name} — no lane is running and no index has been compiled</span>
        <span className="dim">Nothing measured on the indexed project is shown here</span>
      </footer>
    );
  }
  return (
    <footer className="statusbar">
      <span>{fx.gate}</span>
      <span>Lane {fx.status.lane} · {fx.status.resolved_host}{localMayLeave ? ' · local traffic may leave this machine' : ''}</span>
      <span>Attempts {fx.rim.attempts.live} live · {fx.rim.attempts.queued} queued · {fx.rim.attempts.done} done · {fx.rim.attempts.rejected} rejected</span>
      <span title={`The index records the kind and the count, not the paths. The rule is .agentenv/tool-allowances.json.`}>
        Withheld {fx.rim.withheld.count} · {fx.rim.withheld.reason}
      </span>
      <span>Receipts {fx.rim.evidence.receipts_signed}/{fx.rim.evidence.receipts_total} signed</span>
      <span className={killArmed ? 'armed' : 'dim'}>Kill switch {killArmed ? 'armed' : 'off'}</span>
    </footer>
  );
}
