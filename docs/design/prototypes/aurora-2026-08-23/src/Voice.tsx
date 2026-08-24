/* Ikarus, as a column you can actually talk to.
 *
 * A title, the mission it is running, the six stages as one compact line, the
 * thread, two follow-ups the fixture can genuinely answer, and a composer with
 * a visible field, a caret and a Send. Typing and Enter work: the answer comes
 * out of the index word by word, or it is the honest sentence saying that no
 * model is connected. Nothing here is a mock-up of a conversation.
 *
 * The owner asks in italic and a step down in value; Ikarus answers in roman
 * at full value. That is the whole speaker model, and it costs one element per
 * turn — no bubble, no avatar, no name badge repeated over every line. */

import { Fragment, useEffect, useRef } from 'react';
import {
  claimParts, PROV_MEANING, trailingCitations, WITHHELD_RULE_LABEL, withheldTitle,
  type ChatMsg, type Fixture,
} from './data';

export interface VoiceProps {
  fx: Fixture;
  chat: ChatMsg[];
  asking: boolean;
  decision: 'approved' | 'rejected' | null;
  streaming: boolean;
  value: string;
  suggestions: string[];
  onChange: (v: string) => void;
  onSend: () => void;
  onSuggest: (s: string) => void;
  onHoverNode: (id: string | null) => void;
  onSelectNode: (id: string) => void;
  onDecide: (d: 'approved' | 'rejected') => void;
}

function Prov({ p }: { p: 'M' | 'I' | 'A' }) {
  return <button type="button" className="prov" title={PROV_MEANING[p]} aria-label={PROV_MEANING[p]}>{p}</button>;
}

export default function Voice(props: VoiceProps) {
  const {
    fx, chat, asking, decision, streaming, value, suggestions,
    onChange, onSend, onSuggest, onHoverNode, onSelectNode, onDecide,
  } = props;

  const settled = useRef(chat.length).current;
  const fresh = (i: number) => (i >= settled ? ' fresh' : '');
  const thread = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);

  /* the thread always shows the last whole turn, and the field is ready to
     take a sentence the moment the room opens. Settlement finds the last turn
     boundary that still leaves the viewport at least 74% full. */
  useEffect(() => {
    const el = thread.current;
    if (!el) return;

    const settleToTurnBoundary = () => {
      const turns = Array.from(el.querySelectorAll('.turn')) as HTMLElement[];
      if (turns.length === 0) {
        el.scrollTop = el.scrollHeight;
        return;
      }

      const viewportHeight = el.clientHeight;
      const minFillRatio = 0.74;
      const minFill = viewportHeight * minFillRatio;
      const maxScroll = Math.max(0, el.scrollHeight - minFill);

      // Find the last turn that can be shown at the top while keeping the
      // viewport at least 74% full (i.e., turn.offsetTop <= maxScroll).
      // The thread always settles on a turn boundary, never mid-sentence.
      for (let i = turns.length - 1; i >= 0; i--) {
        const turn = turns[i];
        if (turn.offsetTop <= maxScroll) {
          el.scrollTop = turn.offsetTop;
          return;
        }
      }

      // If no turn fits within the 74% constraint, show the last turn anyway.
      // This ensures the first visible line is always the start of a turn.
      el.scrollTop = turns[turns.length - 1].offsetTop;
    };

    settleToTurnBoundary();
    const observer = new ResizeObserver(settleToTurnBoundary);
    observer.observe(el);
    return () => observer.disconnect();
  }, [chat.length]);
  useEffect(() => { input.current?.focus({ preventScroll: true }); }, []);

  const live = fx.mission.stages.findIndex(s => s.state === 'live');
  const build = fx.mission.stages[live];
  const gates = fx.mission.stages.find(s => s.name === 'Gates');
  const decisionText =
    `The build stage is done — ${build?.note ?? ''}. ${fx.rim.evidence.packets} evidence packets are sealed and `
    + `${fx.rim.evidence.receipts_signed} of ${fx.rim.evidence.receipts_total} receipts are signed. The gates `
    + `(${gates?.note ?? ''}) have not run, so nothing past the build is proven. Promotion is sealed: it happens `
    + `if you say so, and not otherwise.`;

  return (
    <section className="panel ikarus">
      <h1 className="ik-name" data-sub="proposes · you decide">Ikarus</h1>
      <p className="ik-mission">
        Mission {fx.mission.id} · {fx.mission.title}
      </p>

      <ol className="steps" aria-label="mission stages">
        {fx.mission.stages.map((s, i) => (
          <li key={s.name} className={'st ' + s.state} data-n={i < live ? '\u2713' : String(i + 1)}
            title={`${s.name} — ${s.state}: ${s.note}`}>{s.name}</li>
        ))}
      </ol>

      <div className="thread" ref={thread}>
        {chat.map((m, i) => {
          if (m.role === 'owner') return <p className={'turn own' + fresh(i)} key={i}>{m.text}</p>;
          if (m.role === 'system') return <p className={'turn sys' + fresh(i)} key={i}>{m.text}{streaming && i === chat.length - 1 ? <i className="caret" /> : null}</p>;
          if (m.role === 'decision') return <p className={'turn done' + fresh(i)} key={i}>{m.text}</p>;
          const parts = claimParts(fx, m);
          const tail = trailingCitations(fx, m);
          return (
            <p className={'turn ik' + fresh(i)} key={i}>
              {parts.map((q, j) =>
                'text' in q ? <Fragment key={j}>{q.text}</Fragment> : (
                  <button type="button" key={j} className="cite"
                    title={`${q.cite.kind} in the index — hover to light it in the room`}
                    onMouseEnter={() => q.cite.node && onHoverNode(q.cite.node)}
                    onMouseLeave={() => onHoverNode(null)}
                    onFocus={() => q.cite.node && onHoverNode(q.cite.node)}
                    onBlur={() => onHoverNode(null)}
                    onClick={() => q.cite.node && onSelectNode(q.cite.node)}
                  >{q.cite.label}</button>
                )
              )}
              {m.withheld ? (
                <button type="button" className="loc" title={withheldTitle(fx, m.withheld)}
                  onMouseEnter={() => onHoverNode('d6')} onMouseLeave={() => onHoverNode(null)}
                  onClick={() => onSelectNode('d6')}>{WITHHELD_RULE_LABEL}</button>
              ) : null}
              {m.provenance ? <Prov p={m.provenance} /> : null}
              {tail.map((c, j) => (
                <button type="button" key={'t' + j} className="loc"
                  title={c.node ? 'evidence locator — hover to light it in the room' : 'evidence locator recorded for this claim'}
                  onMouseEnter={() => c.node && onHoverNode(c.node)}
                  onMouseLeave={() => onHoverNode(null)}
                  onClick={() => c.node && onSelectNode(c.node)}
                >{c.label}</button>
              ))}
              {streaming && i === chat.length - 1 ? <i className="caret" /> : null}
            </p>
          );
        })}

        {asking && !decision ? (
          <p className="turn ik dec fresh">
            {decisionText}
            <Prov p="M" />
            <span className="acts">
              <button type="button" className="act yes" onClick={() => onDecide('approved')}>Approve</button>
              <button type="button" className="act" onClick={() => onDecide('rejected')}>Reject</button>
            </span>
          </p>
        ) : null}
      </div>

      <div className="sugg">
        {suggestions.map(s => (
          <button key={s} type="button" className="sg" onClick={() => onSuggest(s)}
            title="Ikarus answers this out of the index; nothing reaches a service.">{s}</button>
        ))}
      </div>

      <form className="comp" onSubmit={e => { e.preventDefault(); if (value.trim()) onSend(); }}>
        <input id="composer" ref={input} autoComplete="off" spellCheck={false}
          aria-label="Ask Ikarus"
          placeholder="Ask Ikarus — it proposes, you decide"
          value={value} onChange={e => onChange(e.target.value)} />
        <button type="submit" className={'send' + (value.trim() ? ' ready' : '')}
          title={value.trim() ? 'Send' : 'Type a question, then press Enter'}>Send</button>
      </form>
    </section>
  );
}
