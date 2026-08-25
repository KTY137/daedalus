import { useCallback, useEffect, useRef, useState } from 'react';
import { askIkarus, getConversation, isBackendDown, newConversation, queueTask, streamIkarus } from '../api';
import type { IkarusAskAction, IkarusAskPayload } from '../types';
import { recordAutonomy, type AutonomyLevel } from './autonomy';
import { ContextPlan } from './ContextPlan';

/**
 * The conversation with Ikarus.
 *
 * Three rules decide everything here:
 *
 * 1. The provenance stamp reports what actually produced the answer. An answer
 *    read off the local structure index is stamped GEMESSEN; an answer a model
 *    wrote is stamped with the model that wrote it. The stamp is never
 *    decoration and never the same word for both, because that is exactly the
 *    collapse ("everything says MEASURED") this project keeps deleting.
 * 2. The composer is live or it is not there. No greyed-out send button that
 *    does nothing, no suggestion chips that are pictures of suggestions.
 * 3. The thread is DURABLE. Every turn carries a `conversation_id`, so the
 *    backend appends it via `daedalus/conversation.py` and the thread survives
 *    a reload — the difference between a chat and a row of one-shot answers.
 *    Agentic-J (arXiv 2606.02080) names the same property "chat history is
 *    preserved across sessions"; the store for it already existed here and
 *    simply had no caller.
 */

export interface Turn {
  role: 'you' | 'ikarus';
  text: string;
  /** set on an Ikarus turn once it settles */
  stamp?: string;
  stampKind?: 'measured' | 'model' | 'failed';
  /** identifiers Ikarus cited, rendered as monospace chips under the answer */
  cites?: string[];
  streaming?: boolean;
  /** an action Ikarus offered on this turn, still awaiting an answer */
  offer?: IkarusAskAction;
  /** what happened to that offer, once something happened */
  offerOutcome?: string;
}

/** One conversation id per project, so switching projects switches threads. */
const THREAD_KEY = 'daedalus-thread';

function loadThreadId(project: string): string {
  try {
    return localStorage.getItem(`${THREAD_KEY}:${project}`) || '';
  } catch {
    return '';
  }
}

function saveThreadId(project: string, id: string): void {
  try {
    localStorage.setItem(`${THREAD_KEY}:${project}`, id);
  } catch {
    /* storage blocked — the thread still holds for this session */
  }
}

/** What produced this answer, in the answer's own terms. */
function stampFor(payload: {
  intent?: string;
  provider_used?: string;
  model_used?: string;
}): { stamp: string; kind: Turn['stampKind'] } {
  const provider = payload.provider_used || '';
  if (payload.intent === 'error') return { stamp: 'FEHLGESCHLAGEN', kind: 'failed' };
  if (provider === 'deterministic' || payload.intent === 'status' || payload.intent === 'distill') {
    return { stamp: 'GEMESSEN · lokaler Index', kind: 'measured' };
  }
  const model = payload.model_used ? ` · ${payload.model_used}` : '';
  return { stamp: `MODELL · ${provider || 'unbekannt'}${model}`, kind: 'model' };
}

/** Pull identifiers out of an answer so the reader can jump to them. */
function citationsFrom(text: string, known: (id: string) => boolean): string[] {
  const found = new Set<string>();
  const re = /[A-Za-z0-9_./\\-]+\.(?:py|ts|tsx|js|jsx|rs|go|json|md)\b/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (known(m[0])) found.add(m[0]);
    if (found.size >= 6) break;
  }
  return [...found];
}

export interface ConversationProps {
  project: string;
  /** used to turn a cited path into a clickable jump */
  resolveModule: (needle: string) => string | undefined;
  onFocusModule: (module: string) => void;
  /** the module the stage currently shows, offered as something to insert */
  contextModule?: string;
  /** which runtime answers; undefined lets the backend route */
  provider?: string;
  /** how much may happen without a click */
  autonomy: AutonomyLevel;
  /** something was queued, so the caller can refresh what depends on it */
  onDispatched?: () => void;
  compact?: boolean;
}

export function Conversation({
  project,
  resolveModule,
  onFocusModule,
  contextModule,
  provider,
  autonomy,
  onDispatched,
  compact
}: ConversationProps) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [thread, setThread] = useState('');
  const [resuming, setResuming] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);
  const stream = useRef<{ close: () => void } | null>(null);
  const autonomyRef = useRef(autonomy);
  autonomyRef.current = autonomy;

  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns]);

  useEffect(() => () => stream.current?.close(), []);

  /* ---- the thread: resume it, or mint one lazily ---- */
  useEffect(() => {
    if (!project) return;
    let alive = true;
    const known = loadThreadId(project);
    setTurns([]);
    setThread(known);
    if (!known) return;

    setResuming(true);
    getConversation(known)
      .then((payload) => {
        if (!alive) return;
        const rows = payload.conversation?.turns || [];
        setTurns(
          rows.flatMap<Turn>((t) => {
            const { stamp, kind } = stampFor({
              intent: t.intent,
              provider_used: t.provider_used,
              model_used: t.model_used
            });
            return [
              { role: 'you', text: t.user_message },
              {
                role: 'ikarus',
                text: t.assistant_text || '',
                stamp: t.provider_used ? stamp : undefined,
                stampKind: kind,
                cites: citationsFrom(t.assistant_text || '', (id) => Boolean(resolveModule(id)))
              }
            ];
          })
        );
      })
      .catch(() => {
        // A thread that cannot be read is not a thread that never existed, and
        // the difference is worth one line rather than a silently empty page.
        if (alive) setError('Der bisherige Verlauf konnte nicht gelesen werden. Neue Turns laufen trotzdem.');
      })
      .finally(() => {
        if (alive) setResuming(false);
      });

    return () => {
      alive = false;
    };
    // resolveModule changes identity with the map; the thread does not need to
    // be re-read for that.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project]);

  const ensureThread = useCallback(async (): Promise<string> => {
    if (thread) return thread;
    try {
      const payload = await newConversation();
      const id = payload.conversation_id;
      setThread(id);
      saveThreadId(project, id);
      return id;
    } catch {
      // No id is not a reason to lose the turn: the backend accepts a turn
      // without one, it just will not remember it.
      return '';
    }
  }, [project, thread]);

  /* ---- offered actions ---- */

  const runAction = useCallback(
    async (action: IkarusAskAction, automatic: boolean, threadId: string) => {
      const objective = action.args?.objective || '';
      const lane = action.args?.lane || 'local_only';
      try {
        await queueTask(action.args?.project || project, objective, lane, threadId || undefined);
        if (automatic) {
          recordAutonomy({
            what: 'Aufgabe eingereiht',
            detail: `${objective} · Lane ${lane}`,
            level: autonomyRef.current
          });
        }
        onDispatched?.();
        return automatic ? `automatisch eingereiht · Lane ${lane}` : `eingereiht · Lane ${lane}`;
      } catch (e) {
        return `nicht eingereiht: ${e instanceof Error ? e.message : 'unbekannter Fehler'}`;
      }
    },
    [onDispatched, project]
  );

  const answerOffer = useCallback(
    async (index: number, accept: boolean) => {
      const turn = turns[index];
      if (!turn?.offer) return;
      const outcome = accept ? await runAction(turn.offer, false, thread) : 'abgelehnt';
      setTurns((prev) => prev.map((t, i) => (i === index ? { ...t, offer: undefined, offerOutcome: outcome } : t)));
    },
    [runAction, thread, turns]
  );

  const settle = useCallback(
    (payload: IkarusAskPayload, threadId: string) => {
      const { stamp, kind } = stampFor(payload);
      const action = payload.action;
      /**
       * `vorschlaege` and above: a proposed TASK starts without a click. The
       * draft that task produces is a separate decision and is deliberately
       * NOT covered here — see Decision.tsx and autonomy.ts.
       */
      const auto = Boolean(action) && autonomyRef.current !== 'aus';

      setTurns((prev) => {
        const next = [...prev];
        const last = next[next.length - 1];
        if (last && last.role === 'ikarus') {
          next[next.length - 1] = {
            ...last,
            text: payload.assistant || last.text,
            stamp,
            stampKind: kind,
            streaming: false,
            offer: action && !auto ? action : undefined,
            cites: citationsFrom(payload.assistant || last.text, (id) => Boolean(resolveModule(id)))
          };
        }
        return next;
      });
      setBusy(false);

      if (action && auto) {
        void runAction(action, true, threadId).then((outcome) =>
          setTurns((prev) => prev.map((t, i) => (i === prev.length - 1 ? { ...t, offerOutcome: outcome } : t)))
        );
      }
    },
    [resolveModule, runAction]
  );

  /**
   * STOP. Taken from Agentic-J (arXiv 2606.02080), whose chat panel offers a
   * Stop "if the agent is heading in the wrong direction or is taking too
   * long" — the one control this conversation was missing. Closing the stream
   * is also the thing that must happen anyway: an EventSource auto-reconnects
   * on close, and this endpoint re-runs (and re-spends) the whole turn if it
   * does. `settle()` in api.ts guarantees exactly one close.
   */
  const stop = useCallback(() => {
    stream.current?.close();
    stream.current = null;
    setBusy(false);
    setTurns((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      if (last && last.role === 'ikarus' && last.streaming) {
        next[next.length - 1] = {
          ...last,
          streaming: false,
          stamp: 'ABGEBROCHEN',
          stampKind: 'failed',
          text: last.text || '(abgebrochen, bevor eine Antwort kam)'
        };
      }
      return next;
    });
  }, []);

  /** A fresh thread. The old one stays in the store; this stops carrying it. */
  const newThread = useCallback(() => {
    stop();
    setTurns([]);
    setThread('');
    setError('');
    try {
      localStorage.removeItem(`${THREAD_KEY}:${project}`);
    } catch {
      /* storage blocked — the fresh thread still holds for this session */
    }
  }, [project, stop]);

  const send = useCallback(async () => {
    const message = draft.trim();
    if (!message || busy || !project) return;
    setDraft('');
    setError('');
    setBusy(true);
    const threadId = await ensureThread();

    /**
     * WHAT IS SENT IS WHAT WAS TYPED.
     *
     * An earlier version prepended a line naming the module on the stage. It
     * read as helpful and was not: the backend classifies intent by substring
     * (daedalus/ikarus_os.py::classify), so a focus on `clones.py` silently
     * routed a plain question down the distillation path, and the turn stored
     * in the conversation was not the sentence the person wrote. Context is
     * offered as something to INSERT, visibly, above the composer.
     */
    setTurns((prev) => [...prev, { role: 'you', text: message }, { role: 'ikarus', text: '', streaming: true }]);

    stream.current = streamIkarus(
      project,
      message,
      provider,
      undefined,
      undefined,
      {
        onDelta: (text) =>
          setTurns((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            if (last && last.role === 'ikarus') next[next.length - 1] = { ...last, text: last.text + text };
            return next;
          }),
        onFinal: (payload) => settle(payload, threadId),
        onError: async () => {
          // The stream died. Fall back to the blocking call rather than leaving
          // a half-written answer on screen pretending to still be arriving.
          try {
            const payload = await askIkarus(project, message, provider, undefined, undefined, threadId || undefined);
            settle(payload, threadId);
          } catch (e) {
            setBusy(false);
            setTurns((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last && last.role === 'ikarus' && !last.text) next.pop();
              return next;
            });
            setError(
              isBackendDown(e)
                ? 'Die Daedalus-API antwortet nicht. Nichts auf diesem Bildschirm wurde von ihr gelesen.'
                : e instanceof Error
                  ? e.message
                  : 'Ikarus hat nicht geantwortet.'
            );
          }
        }
      },
      threadId || undefined
    );
  }, [busy, draft, ensureThread, project, provider, settle]);

  return (
    <section className={compact ? 'convo compact' : 'convo'} aria-label="Gespräch mit Ikarus">
      <div className="convo-bar">
        <span className="convo-thread">
          {thread ? (
            <>
              Verlauf <code>{thread.slice(0, 8)}</code> · {Math.floor(turns.length / 2)} Turns
            </>
          ) : (
            'Neuer Verlauf'
          )}
        </span>
        {busy && (
          <button type="button" className="convo-stop" onClick={stop}>
            Stopp
          </button>
        )}
        <button type="button" onClick={newThread} disabled={!turns.length && !thread}>
          Neuer Chat
        </button>
      </div>

      <div className="convo-scroll" ref={scroller}>
        {resuming && <p className="convo-empty">Verlauf wird gelesen …</p>}
        {!resuming && turns.length === 0 && (
          <p className="convo-empty">
            Frag Ikarus etwas über <b>{project || 'dieses Projekt'}</b>. Antworten aus dem lokalen Index tragen den
            Stempel GEMESSEN, Antworten eines Modells dessen Namen.
          </p>
        )}
        {turns.map((t, i) => (
          <article key={i} className={`turn ${t.role}`}>
            <div className="turn-who">{t.role === 'you' ? 'Du' : 'Ikarus'}</div>
            <div className="turn-body">
              <p className="turn-text">
                {t.text}
                {t.streaming && <span className="caret" aria-hidden="true" />}
              </p>
              {t.stamp && <span className={`stamp ${t.stampKind}`}>{t.stamp}</span>}

              {t.offer && (
                <div className="offer" role="region" aria-label="Vorgeschlagene Aktion">
                  <span className="offer-eyebrow">Ikarus schlägt vor</span>
                  <p className="offer-what">{t.offer.args?.objective}</p>
                  <p className="offer-where">
                    Lane <code>{t.offer.args?.lane}</code> · Projekt <code>{t.offer.args?.project}</code>
                  </p>
                  <div className="offer-acts">
                    <button type="button" className="primary" onClick={() => void answerOffer(i, true)}>
                      Loslegen
                    </button>
                    <button type="button" onClick={() => void answerOffer(i, false)}>
                      Nicht jetzt
                    </button>
                  </div>
                </div>
              )}
              {t.offerOutcome && <span className="offer-outcome">{t.offerOutcome}</span>}

              {t.cites && t.cites.length > 0 && (
                <div className="cites">
                  {t.cites.map((c) => {
                    const module = resolveModule(c);
                    return module ? (
                      <button key={c} type="button" className="cite" onClick={() => onFocusModule(module)}>
                        {c}
                      </button>
                    ) : null;
                  })}
                </div>
              )}
            </div>
          </article>
        ))}
      </div>

      {error && (
        <p className="convo-error" role="alert">
          {error}
        </p>
      )}

      <ContextPlan
        project={project}
        objective={draft}
        onFocusModule={onFocusModule}
        resolveModule={resolveModule}
      />

      {contextModule && (
        <div className="composer-context">
          <span>
            Auf der Bühne: <code>{contextModule}</code>
          </span>
          <button
            type="button"
            onClick={() => setDraft((d) => (d ? `${d.replace(/\s+$/, '')} ${contextModule} ` : `${contextModule} `))}
            title="Den Pfad in deine Frage einfügen"
          >
            Einfügen
          </button>
        </div>
      )}

      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={busy ? 'Ikarus antwortet …' : 'Frag Ikarus …'}
          aria-label="Nachricht an Ikarus"
          disabled={!project}
        />
        <button type="submit" disabled={busy || !draft.trim() || !project} aria-label="Senden">
          {busy ? '…' : '↑'}
        </button>
      </form>
    </section>
  );
}
