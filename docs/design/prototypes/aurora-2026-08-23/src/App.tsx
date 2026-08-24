/* The room is one dark space with a lit back wall and four turning bodies in
 * it. Over that float five pieces of glass — a toolbar, a sidebar, Ikarus, an
 * ornament and the knowledge inspector — each a window onto the room rather
 * than a tile on a surface. Every thing has its own place, which is why no
 * text has to be laid over the object. */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Canvas } from '@react-three/fiber';
import Scene from './room/Scene';
import Labels from './room/Labels';
import { buildLayouts } from './room/layout';
import { bus, touch } from './room/bus';
import Voice from './Voice';
import { Inspector, Ornament, Sidebar, StatusBar, TopBar } from './ui';
import { Library, Palette, Settings, type Row } from './overlays';
import { AppProvider, useApp, type Api } from './state';
import {
  allEdges, conversationNodes, fmt, projectViews, wikiPathFor,
  type Depth, type Lens, type ViewMode,
} from './data';

const LENSES: Lens[] = ['structure', 'evidence', 'cost'];

function Room() {
  const api = useApp();
  const {
    fx, ps, patch, prefs, setPrefs, overlay, setOverlay, reason, setReason, say, ask,
    seed, setSeed, projectId, setProjectId, libPage, setLibPage, motionOn, screen, setScreen, streaming,
  } = api;

  const edges = useMemo(() => allEdges(fx), [fx]);
  const L = useMemo(() => buildLayouts(fx, edges), [fx, edges]);
  const indexed = projectId === fx.project;
  const lit = useMemo(() => (indexed ? conversationNodes(fx, ps.chat) : []), [fx, ps.chat, indexed]);
  const me = projectViews(fx).find(p => p.id === projectId)!;
  const [composed, setComposed] = useState('');

  useEffect(() => {
    if (seed) { setComposed(seed); setSeed(''); document.getElementById('composer')?.focus(); }
  }, [seed, setSeed]);

  const setView = (v: ViewMode) => { touch(); patch({ view: v, camView: v === 'ordered' ? 'flat' : 'room' }); };
  const reset = () => { touch(); patch({ resetReq: ps.resetReq + 1, selected: null, depth: 1, camView: ps.view === 'ordered' ? 'flat' : 'room' }); };
  const select = (id: string) => { touch(); patch({ selected: id }); };
  const openPage = (path: string) => { setLibPage(path); setOverlay('library'); };

  const decide = (d: 'approved' | 'rejected') => {
    patch({ decision: d, asking: false });
    say({
      role: 'decision',
      text: `You ${d} ${fx.mission.id}. Nothing merged: this prototype records the decision and stops there, which is what sealed promotion means.`,
    });
  };

  /* two follow-ups the index can genuinely answer, derived from the thread */
  const suggestions = useMemo(() => {
    if (!indexed) return [];
    const last = lit[0];
    const n = last ? fx.graph.nodes.find(x => x.id === last) : null;
    return [
      n ? `Was weißt du über ${n.label}?` : 'Was weißt du über daedalus/policy/enforce.py?',
      'Wieviel wurde heute ausgegeben?',
    ];
  }, [fx, lit, indexed]);

  /* ------------------------------------------------------------- palette */
  const rows: Row[] = useMemo(() => {
    const sel = ps.selected ? fx.graph.nodes.find(n => n.id === ps.selected) : null;
    const needNode = 'Select a node first, or type @ to find one.';
    const noService = 'No model or runner is connected in this prototype, so nothing would run.';
    const out: Row[] = [];
    for (const v of fx.palette) {
      if (v.verb === 'Distill' || v.verb === 'Focus') {
        out.push({
          key: v.verb, verb: v.verb, hint: v.hint, disabled: sel ? undefined : needNode,
          run: () => {
            if (!sel) { setReason({ text: needNode }); return; }
            patch({ selected: sel.id, camView: 'room', resetReq: ps.resetReq + 1 });
            say({
              role: 'ikarus',
              text: `The slice is focused on ${sel.label}. It is ${fx.slice.state}, refreshed at ${fx.slice.refreshed}: ${fmt(fx.slice.tokens_in_slice)} of ${fmt(fx.slice.tokens_full)} tokens, ${fx.slice.withheld_paths} paths withheld for ${fx.rim.withheld.reason}.`,
              provenance: 'M', evidence: ['slice', 'rim.withheld'],
            });
          },
        });
      } else if (v.verb === 'Doctor') {
        out.push({
          key: v.verb, verb: v.verb, hint: v.hint,
          run: () => say({
            role: 'ikarus',
            text: fx.lanes.map(l => `${l.runtime}: reads, proposes, writes ${l.write}${l.host ? ` on ${l.host}` : ''}.`).join(' '),
            provenance: 'M', evidence: ['lanes'],
          }),
        });
      } else if (v.verb === 'Canary') {
        out.push({ key: v.verb, verb: v.verb, hint: v.hint, disabled: noService, run: () => setReason({ text: noService }) });
      } else if (v.verb === 'Council') {
        out.push({
          key: v.verb, verb: v.verb, hint: v.hint,
          run: () => { for (const c of fx.council) say({ role: 'system', text: `${c.vendor} — “${c.text}”` }); },
        });
      } else if (v.verb === 'Open page') {
        out.push({ key: v.verb, verb: v.verb, hint: v.hint, run: () => setOverlay('library') });
      } else {
        out.push({ key: v.verb, verb: v.verb, hint: v.hint, run: () => { /* reached with the @ prefix */ } });
      }
    }
    out.push({ key: 'ordered', verb: ps.view === 'ordered' ? 'Constellation' : 'Ordered', hint: 'the same nodes, arranged the other way', run: () => setView(ps.view === 'ordered' ? 'spatial' : 'ordered') });
    out.push({ key: 'raking', verb: 'Raking view', hint: 'look along the constellation', run: () => { touch(); patch({ camView: 'along' }); } });
    out.push({ key: 'decision', verb: 'The decision', hint: `${fx.mission.id} is waiting on you`, run: () => patch({ asking: true }) });
    out.push({ key: 'settings', verb: 'Settings', hint: 'route, lanes, memory, motion', run: () => setOverlay('settings') });
    for (const p of fx.projects) {
      if (p.id === projectId) continue;
      out.push({ key: 'p:' + p.id, verb: p.name, hint: p.id === fx.project ? 'indexed project' : 'no compiled index', run: () => setProjectId(p.id) });
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fx, ps.selected, ps.view, ps.resetReq, projectId]);

  /* ------------------------------------------------------------ keyboard */
  const step = useCallback((dx: number, dy: number) => {
    const cur = ps.selected ?? lit[0] ?? null;
    const here = cur ? bus.pts.get(cur) : null;
    let best: string | null = null, score = -1e9;
    for (const [id, p] of bus.pts) {
      if (id === cur) continue;
      if (!here) { if (score < 0) { best = id; score = 0; } continue; }
      const vx = p.x - here.x, vy = p.y - here.y;
      const along = vx * dx + vy * dy, off = Math.abs(vx * dy - vy * dx);
      if (along < 10) continue;
      const s = -(along + off * 1.9);
      if (s > score) { score = s; best = id; }
    }
    if (best) { touch(); patch({ selected: best }); }
  }, [ps.selected, lit, patch]);

  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      const typing = t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA');
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault(); setOverlay(overlay === 'palette' ? null : 'palette'); return;
      }
      if (e.key === 'Escape') {
        if (overlay) { setOverlay(null); return; }
        if (typing) { (t as HTMLInputElement).blur(); return; }
        patch({ selected: null, hovered: null }); setReason(null); return;
      }
      if (typing || overlay) return;
      if (e.key === 'ArrowLeft') { e.preventDefault(); step(-1, 0); }
      else if (e.key === 'ArrowRight') { e.preventDefault(); step(1, 0); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); step(0, -1); }
      else if (e.key === 'ArrowDown') { e.preventDefault(); step(0, 1); }
      else if (e.key === 'Enter' && ps.hovered) { e.preventDefault(); select(ps.hovered); }
    };
    window.addEventListener('keydown', on);
    return () => window.removeEventListener('keydown', on);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overlay, ps.hovered, step]);

  const spendText = indexed
    ? `${fmt(fx.status.tokens_today)} tokens · $${fx.status.spend_today_usd.toFixed(2)} of $${prefs.ceiling.toFixed(2)} today`
    : 'Nothing spent on this project today';

  return (
    <>
      <Canvas
        className="room"
        dpr={[1, 2]}
        shadows
        gl={{ antialias: true, alpha: false }}
        camera={{ fov: 26, near: 0.6, far: 60, position: [2, 1, 15] }}
        role="img"
        aria-label={`Four bodies of nodes: ${fx.graph.nodes.length} nodes across the code, type, data and knowledge planes. Move with the arrow keys, select with Enter.`}
      >
        <Scene
          fx={fx} view={ps.view} camView={ps.camView} resetReq={ps.resetReq}
          selected={ps.selected} hovered={ps.hovered} lit={lit} depth={ps.depth}
          lens={ps.lens} motion={motionOn} shift={0}
          onHover={id => patch({ hovered: id })}
          onSelect={select}
        />
      </Canvas>

      <Labels fx={fx} view={ps.view} lit={lit} selected={ps.selected} hovered={ps.hovered} deg={L.deg} />

      <div className="grid">
        <TopBar fx={fx} spendText={spendText} onSearch={() => setOverlay('palette')} />
        <div className="lensbar">
          {LENSES.map(l => (
            <button key={l} type="button" className={ps.lens === l ? 'seg on' : 'seg'}
              onClick={() => { touch(); patch({ lens: l }); }}
              title={l === 'structure' ? 'Containment and calls, the spine of the index.'
                : l === 'evidence' ? 'Proposed relations become visible, drawn dashed.'
                  : 'Only the modules whose cost the index measured stay solid.'}>
              {l[0].toUpperCase() + l.slice(1)}
            </button>
          ))}
        </div>

        <Sidebar fx={fx} projectId={projectId} view={ps.view} screen={screen}
          onProject={setProjectId} onView={setView}
          onScreen={s => { setScreen(s); if (s === 'library') setOverlay('library'); }}
          onSettings={() => setOverlay('settings')} />

        <Voice
          fx={fx} chat={ps.chat} asking={ps.asking} decision={ps.decision}
          streaming={streaming} value={composed} suggestions={suggestions}
          onChange={setComposed}
          onSend={() => { ask(composed.trim()); setComposed(''); }}
          onSuggest={s => { ask(s); }}
          onHoverNode={id => patch({ hovered: id })}
          onSelectNode={select}
          onDecide={decide}
        />

        <div className="stage">
          <Ornament
            view={ps.view} lens={ps.lens} depth={ps.depth} hasSelection={!!ps.selected}
            reason={reason?.text ?? null}
            setView={setView}
            setLens={(l: Lens) => { touch(); patch({ lens: l }); }}
            cycleDepth={() => patch({ depth: (ps.depth === 1 ? 2 : ps.depth === 2 ? 0 : 1) as Depth })}
            reset={reset}
            say={t => setReason(t ? { text: t } : null)}
          />
        </div>

        <Inspector fx={fx} id={indexed ? ps.selected : null}
          onOpenPage={openPage}
          onAsk={label => setSeed(`Was weißt du über ${label}?`)}
          say={t => setReason(t ? { text: t } : null)}
          reason={reason?.text ?? null} />

        <StatusBar fx={fx} killArmed={prefs.killArmed} localMayLeave={prefs.localMayLeave}
          indexed={indexed} name={me.name} />
      </div>

      {overlay === 'palette' ? (
        <Palette
          fx={fx} projectId={projectId} rows={rows} nodes={indexed ? fx.graph.nodes : []}
          seedText="" onClose={() => setOverlay(null)}
          onPick={r => {
            if (r.key.length <= 3 && fx.graph.nodes.some(n => n.id === r.key)) { setOverlay(null); select(r.key); return; }
            if (r.disabled) { setReason({ text: r.disabled }); return; }
            setOverlay(null); r.run();
          }}
        />
      ) : null}

      {overlay === 'library' ? (
        <Library fx={fx} projectId={projectId} page={libPage} setPage={setLibPage}
          onClose={() => { setOverlay(null); setScreen('cockpit'); }} />
      ) : null}

      {overlay === 'settings' ? (
        <Settings fx={fx} prefs={prefs} setPrefs={setPrefs} onClose={() => setOverlay(null)}
          say={t => setReason(t ? { text: t } : null)} reason={reason?.text ?? null} />
      ) : null}
    </>
  );
}

export default function App() {
  return <AppProvider>{(_api: Api) => <Room />}</AppProvider>;
}

export { wikiPathFor };
