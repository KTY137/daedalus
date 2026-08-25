import { useCallback, useEffect, useRef, useState } from 'react';
import { askIkarus, isBackendDown, streamIkarus } from '../api';
import type { IkarusAskPayload } from '../types';

/**
 * The conversation with Ikarus.
 *
 * Two rules decide everything here:
 *
 * 1. The provenance stamp reports what actually produced the answer. An answer
 *    read off the local structure index is stamped GEMESSEN; an answer a model
 *    wrote is stamped with the model that wrote it. The stamp is never
 *    decoration and never the same word for both, because that is exactly the
 *    collapse ("everything says MEASURED") this project keeps deleting.
 * 2. The composer is live or it is not there. No greyed-out send button that
 *    does nothing, no suggestion chips that are pictures of suggestions.
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
}

const STORAGE_KEY = 'daedalus-cockpit-transcript';

function loadTurns(): Turn[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    return Array.isArray(parsed) ? (parsed as Turn[]).filter((t) => t && typeof t.text === 'string').slice(-40) : [];
  } catch {
    return [];
  }
}

function saveTurns(turns: Turn[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(turns.slice(-40)));
  } catch {
    /* storage blocked — the transcript still lives for this session */
  }
}

/** What produced this answer, in the answer's own terms. */
function stampFor(payload: IkarusAskPayload): { stamp: string; kind: Turn['stampKind'] } {
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
  /** a one-line hint of what the stage currently shows, put in front of the question */
  contextLine?: string;
  compact?: boolean;
}

export function Conversation({ project, resolveModule, onFocusModule, contextLine, compact }: ConversationProps) {
  const [turns, setTurns] = useState<Turn[]>(loadTurns);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const scroller = useRef<HTMLDivElement>(null);
  const stream = useRef<{ close: () => void } | null>(null);

  useEffect(() => saveTurns(turns), [turns]);

  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns]);

  useEffect(() => () => stream.current?.close(), []);

  const settle = useCallback(
    (payload: IkarusAskPayload) => {
      const { stamp, kind } = stampFor(payload);
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
            cites: citationsFrom(payload.assistant || last.text, (id) => Boolean(resolveModule(id)))
          };
        }
        return next;
      });
      setBusy(false);
    },
    [resolveModule]
  );

  const send = useCallback(async () => {
    const message = draft.trim();
    if (!message || busy || !project) return;
    setDraft('');
    setError('');
    setBusy(true);
    const asked = contextLine ? `${contextLine}\n\n${message}` : message;
    setTurns((prev) => [...prev, { role: 'you', text: message }, { role: 'ikarus', text: '', streaming: true }]);

    stream.current = streamIkarus(project, asked, undefined, undefined, undefined, {
      onDelta: (text) =>
        setTurns((prev) => {
          const next = [...prev];
          const last = next[next.length - 1];
          if (last && last.role === 'ikarus') next[next.length - 1] = { ...last, text: last.text + text };
          return next;
        }),
      onFinal: settle,
      onError: async () => {
        // The stream died. Fall back to the blocking call rather than leaving a
        // half-written answer on screen pretending to still be arriving.
        try {
          const payload = await askIkarus(project, asked);
          settle(payload);
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
    });
  }, [busy, contextLine, draft, project, settle]);

  return (
    <section className={compact ? 'convo compact' : 'convo'} aria-label="Gespräch mit Ikarus">
      <div className="convo-scroll" ref={scroller}>
        {turns.length === 0 && (
          <p className="convo-empty">
            Frag Ikarus etwas über <b>{project || 'dieses Projekt'}</b> — zum Beispiel, was passiert, wenn du das Modul
            in der Mitte änderst. Antworten aus dem lokalen Index tragen den Stempel GEMESSEN, Antworten eines Modells
            den Namen des Modells.
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

      {error && <p className="convo-error" role="alert">{error}</p>}

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
