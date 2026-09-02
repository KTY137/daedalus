import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import {
  ApiError,
  cancelConversationTurn,
  createConversationTurn,
  getConversation,
  getEditorContext,
  getRuntimeStatus,
  newConversation,
  observeConversationTurn,
  queueTask,
  streamTask
} from '@/shared/api';
import type { ConversationCancellationStatus, EditorContextReceipt, TaskSnapshot } from '@/shared/api';
import type { EffortLevel, IkarusAskAction, RuntimeRow } from '@/shared/contracts';
import { armVariants, bubbleVariants, pressProps, revealVariants, useReducedMotionPref } from '@/shared/ui/motion';
import { recordAutonomy, type AutonomyLevel } from '@/features/settings/autonomy';
import { ContextPlan } from '@/features/knowledge/ContextPlan';
import { shortLabel } from '@/features/twin/graph';
import { MarkdownMessage } from './MarkdownMessage';
import { BrainPicker, type RuntimeState, type WaitLedger } from './BrainPicker';
import { CommandMenu } from './CommandMenu';
import { EffortPicker } from './EffortPicker';
import { Ledger } from './Ledger';
import { helpText, looksLikeCommand, matchCommands, parseCommand, type CommandAction, type CommandSpec } from './commands';
import {
  citationsFrom,
  elapsedLabel,
  ledgerFor,
  openDispatchesFrom,
  positiveTurnId,
  resumedTurns,
  settleTurn,
  stampForTurn,
  type Citation,
  type OpenDispatch,
  type Turn
} from './model';

/**
 * The conversation with Ikarus.
 *
 * Four rules decide everything here:
 *
 * 1. Every answer carries its PROTOKOLL — the kernel's own receipts for that
 *    turn (route, context, refusal, provenance, offer, dispatch), derived in
 *    model.ts from frames the backend actually sent. An answer read off the
 *    local structure index is stamped GEMESSEN; one a model wrote is stamped
 *    with the model that wrote it. Never the same word for both.
 * 2. The composer is live or it is not there. No greyed-out send button that
 *    does nothing, no suggestion chips that are pictures of suggestions. A
 *    `/` command is a shortcut to something this page can already do.
 * 3. The thread is DURABLE and it is one of many. Every turn carries a
 *    `conversation_id`; the spine appends it; the rail lists this project's
 *    threads from the same spine and any of them can be resumed here.
 * 4. ONE effectful transition: `POST /api/conversations/{id}/turns`. The
 *    stream is observation; closing it is not cancellation; cancellation is
 *    a separate POST with its own receipt. Nothing here replays a POST.
 */

/* ------------------------------------------------------------- storage */

/** One conversation id per project, so switching projects switches threads. */
const THREAD_KEY = 'daedalus-thread';
/** Measured waits per route, per project. */
const WAIT_KEY = 'daedalus-waits';
/** The effort sent with the next turn, per project. */
const EFFORT_KEY = 'daedalus-effort';

function loadThreadId(project: string): string {
  try {
    return localStorage.getItem(`${THREAD_KEY}:${project}`) || '';
  } catch {
    return '';
  }
}

function saveThreadId(project: string, id: string): void {
  try {
    if (id) localStorage.setItem(`${THREAD_KEY}:${project}`, id);
    else localStorage.removeItem(`${THREAD_KEY}:${project}`);
  } catch {
    /* storage blocked — the thread still holds for this session */
  }
}

function loadWaits(project: string): WaitLedger {
  try {
    const raw = localStorage.getItem(`${WAIT_KEY}:${project}`);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return {};
    const out: WaitLedger = {};
    for (const [id, seconds] of Object.entries(parsed as Record<string, unknown>)) {
      // Anything that is not a plausible number is dropped rather than drawn:
      // storage is writable by anything, and this column is read as evidence.
      if (typeof seconds === 'number' && Number.isFinite(seconds) && seconds >= 0 && seconds < 3600) {
        out[id] = seconds;
      }
    }
    return out;
  } catch {
    return {};
  }
}

function saveWaits(project: string, waits: WaitLedger): void {
  try {
    localStorage.setItem(`${WAIT_KEY}:${project}`, JSON.stringify(waits));
  } catch {
    /* storage blocked — the ledger still holds for this session */
  }
}

function loadEffort(project: string): EffortLevel {
  try {
    const raw = localStorage.getItem(`${EFFORT_KEY}:${project}`);
    return raw === 'medium' || raw === 'high' ? raw : 'low';
  } catch {
    return 'low';
  }
}

function saveEffort(project: string, level: EffortLevel): void {
  try {
    localStorage.setItem(`${EFFORT_KEY}:${project}`, level);
  } catch {
    /* storage blocked — the level still holds for this session */
  }
}

function clientId(prefix: string): string {
  try {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return `${prefix}_${crypto.randomUUID()}`;
  } catch { /* a timestamp fallback remains an idempotency key for this page */ }
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2)}`;
}

type EditorAttachment =
  | { state: 'idle' }
  | { state: 'loading'; ref: string }
  | { state: 'attached'; ref: string; context: EditorContextReceipt }
  | { state: 'withheld'; ref: string; reason: string; context?: EditorContextReceipt }
  | { state: 'unavailable'; ref: string; reason: string };

function editorContextRefFromUrl(): string {
  try { return new URLSearchParams(window.location.search).get('context_ref')?.trim() || ''; } catch { return ''; }
}

/* Two glyphs, drawn rather than typed, so they take the theme's colour and
   keep one stroke weight in every theme. */
function SendGlyph() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false">
      <path d="M8 13V3.6M4.2 7.4 8 3.6l3.8 3.8" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function StopGlyph() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false">
      <rect x="5" y="5" width="6" height="6" rx="1" fill="currentColor" />
    </svg>
  );
}

/* ---------------------------------------------------------------- props */

export interface ConversationProps {
  project: string;
  /** used to turn a cited path into a clickable jump */
  resolveModule: (needle: string) => string | undefined;
  onFocusModule: (module: string) => void;
  /** switch to the map after a focus (`/karte`) */
  onGoMap?: () => void;
  /** the module the stage currently shows, offered as something to insert */
  contextModule?: string;
  /** which runtime answers; undefined lets the backend route */
  provider?: string;
  /** picking a brain from inside the conversation, where the wait happens */
  onProvider?: (id: string) => void;
  /** how much may happen without a click */
  autonomy: AutonomyLevel;
  /** something was queued, so the caller can refresh what depends on it */
  onDispatched?: () => void;
  compact?: boolean;
  /** a thread chosen in the rail; a new serial makes the same id a fresh request */
  pickThread?: { id: string; serial: number };
  /** what this page holds, for the rail: the open thread, how many turns
   *  settled, the runtime names this page has learned, and the dispatches
   *  this thread started that have not reported back */
  onThreadState?: (state: {
    id: string;
    settled: number;
    labels: Record<string, string>;
    openDispatches: OpenDispatch[];
  }) => void;
}

/* ------------------------------------------------------------ component */

export function Conversation({
  project,
  resolveModule,
  onFocusModule,
  onGoMap,
  contextModule,
  provider,
  onProvider,
  autonomy,
  onDispatched,
  compact,
  pickThread,
  onThreadState
}: ConversationProps) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [copiedTurn, setCopiedTurn] = useState<string | null>(null);
  const [thread, setThread] = useState('');
  const [resuming, setResuming] = useState(false);
  const [runtimes, setRuntimes] = useState<RuntimeRow[]>([]);
  const [runtimeState, setRuntimeState] = useState<RuntimeState>('laden');
  /** seconds the current turn has been running; a caret is not a progress report */
  const [elapsed, setElapsed] = useState(0);
  /** what actually served the last turn, so a canned answer can say it was canned */
  const [lastProvider, setLastProvider] = useState('');
  const [editorAttachment, setEditorAttachment] = useState<EditorAttachment>({ state: 'idle' });
  const [activeRequest, setActiveRequest] = useState<{ conversationId: string; requestId: number; localTurnId: string } | null>(null);
  const [waits, setWaits] = useState<WaitLedger>({});
  const [effort, setEffort] = useState<EffortLevel>('low');
  /** the highlighted row of the `/` menu */
  const [cmdActive, setCmdActive] = useState(0);
  /** Esc closed the menu for this draft */
  const [cmdDismissed, setCmdDismissed] = useState(false);
  /** bumps open the runtime picker (`/modell`) and the context plan (`/plan`) */
  const [brainSignal, setBrainSignal] = useState(0);
  const [planSignal, setPlanSignal] = useState(0);
  /** text arrived below the fold while the reader was scrolled up */
  const [unread, setUnread] = useState(false);
  /** how many turns settled on this page — the rail re-reads on it */
  const [settled, setSettled] = useState(0);
  /** dispatches this thread started that have not reported back */
  const [openDispatches, setOpenDispatches] = useState<OpenDispatch[]>([]);

  const sentAt = useRef(0);
  const scroller = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  /** true while the reader is at the bottom; only then may new text scroll */
  const pinned = useRef(true);
  const lastSent = useRef('');
  const reduced = useReducedMotionPref();
  const youArrive = useMemo(() => bubbleVariants(reduced, 'right'), [reduced]);
  const ikarusArrive = useMemo(() => bubbleVariants(reduced, 'left'), [reduced]);
  const reveal = useMemo(() => revealVariants(reduced), [reduced]);
  const arm = useMemo(() => armVariants(reduced), [reduced]);
  /** The index from which a turn is NEW and may animate in. */
  const freshFrom = useRef(0);
  const stream = useRef<{ close: () => void } | null>(null);
  /** Invalidates chat callbacks that outlive their project or thread. */
  const chatScope = useRef(0);
  /** Synchronous claim: React's `busy` state cannot close a same-render double submit. */
  const chatSendClaim = useRef<symbol | null>(null);
  /** Every queued task has its own one-shot stream until final/error/teardown. */
  const taskStreams = useRef<Map<string, { close: () => void }>>(new Map());
  /** Invalidates a queue response that arrives after its thread/project left. */
  const taskScope = useRef(0);
  /** Invalidates a resume read that lands after the thread or project moved on. */
  const resumeScope = useRef(0);
  const turnSerial = useRef(0);
  /** Synchronous claim guard: React state alone cannot stop a double-click. */
  const claimedOffers = useRef<Set<string>>(new Set());
  const autonomyRef = useRef(autonomy);
  autonomyRef.current = autonomy;
  const projectRef = useRef(project);
  projectRef.current = project;
  const threadRef = useRef(thread);
  threadRef.current = thread;

  /* ---- following the stream without yanking the reader ---- */

  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    if (pinned.current) {
      el.scrollTop = el.scrollHeight;
      setUnread(false);
    } else if (turns.length > 0) {
      setUnread(true);
    }
  }, [turns]);

  const onScroll = useCallback(() => {
    const el = scroller.current;
    if (!el) return;
    pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
    if (pinned.current) setUnread(false);
  }, []);

  const jumpToEnd = useCallback(() => {
    const el = scroller.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
    pinned.current = true;
    setUnread(false);
  }, []);

  // The box grows with the text and shrinks back when it is sent.
  useEffect(() => {
    const el = composer.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(200, el.scrollHeight)}px`;
  }, [draft]);

  // Focus lands where typing goes, on arrival and after every turn.
  useEffect(() => {
    if (!busy) composer.current?.focus();
  }, [busy, project]);

  // A dismissed menu comes back the moment the draft changes shape.
  useEffect(() => {
    setCmdDismissed(false);
    setCmdActive(0);
  }, [draft]);

  const closeTaskStreams = useCallback(() => {
    taskScope.current += 1;
    taskStreams.current.forEach((taskStream) => taskStream.close());
    taskStreams.current.clear();
  }, []);

  const invalidateChat = useCallback(() => {
    chatScope.current += 1;
    chatSendClaim.current = null;
    stream.current?.close();
    stream.current = null;
  }, []);

  useEffect(
    () => () => {
      invalidateChat();
      closeTaskStreams();
    },
    [closeTaskStreams, invalidateChat]
  );

  /* ---- who can answer — and this request is itself slow enough to fail ---- */

  const readRuntimes = useCallback(async (): Promise<void> => {
    setRuntimeState('laden');
    try {
      const payload = await getRuntimeStatus();
      setRuntimes(payload.runtimes || []);
      setRuntimeState('ok');
    } catch {
      setRuntimes([]);
      setRuntimeState('fehler');
    }
  }, []);

  useEffect(() => {
    let alive = true;
    let retry = 0;
    const attempt = () => {
      getRuntimeStatus()
        .then((p) => {
          if (!alive) return;
          setRuntimes(p.runtimes || []);
          setRuntimeState('ok');
        })
        .catch(() => {
          if (!alive) return;
          if (retry === 0) {
            retry = 1;
            attempt();
            return;
          }
          setRuntimes([]);
          setRuntimeState('fehler');
        });
    };
    attempt();
    return () => {
      alive = false;
    };
  }, []);

  /* The editor owns the selection artifact; chat only reads its public receipt.
     A URL ref that belongs to another checkout is shown as withheld and is never
     sent across the project boundary. */
  useEffect(() => {
    const ref = editorContextRefFromUrl();
    if (!ref) {
      setEditorAttachment({ state: 'idle' });
      return;
    }
    if (!project) {
      setEditorAttachment({ state: 'withheld', ref, reason: 'Kein Projekt für den Editor-Anhang ausgewählt.' });
      return;
    }
    let alive = true;
    setEditorAttachment({ state: 'loading', ref });
    getEditorContext(ref)
      .then((payload) => {
        if (!alive) return;
        const context = payload.context;
        if (!context || context.context_ref !== ref) {
          setEditorAttachment({ state: 'unavailable', ref, reason: 'Der Editor-Anhang hat keine prüfbare Referenz geliefert.' });
        } else if (context.project !== project) {
          setEditorAttachment({ state: 'withheld', ref, context, reason: `Der Anhang gehört zu Projekt ${context.project}, nicht zu ${project}.` });
        } else if (context.expired) {
          setEditorAttachment({ state: 'withheld', ref, context, reason: 'Der Editor-Anhang ist abgelaufen und wird nicht gesendet.' });
        } else if (context.inclusion_report?.accepted === false) {
          setEditorAttachment({ state: 'withheld', ref, context, reason: context.inclusion_report.reason || 'Der Kontext wurde bei der Prüfung nicht aufgenommen.' });
        } else {
          setEditorAttachment({ state: 'attached', ref, context });
        }
      })
      .catch(() => {
        if (alive) setEditorAttachment({ state: 'unavailable', ref, reason: 'Der Editor-Anhang konnte nicht gelesen werden und wird nicht gesendet.' });
      });
    return () => { alive = false; };
  }, [project]);

  // A running clock while a turn is out. 45 seconds of blinking caret reads as
  // a hang; 45 seconds of a counter reads as work.
  useEffect(() => {
    if (!busy) {
      setElapsed(0);
      return;
    }
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 500);
    return () => window.clearInterval(timer);
  }, [busy]);

  /* ---- the thread: resume one, mint one lazily, switch to another ---- */

  /**
   * Open a thread: everything on screen from the old one goes, the id is
   * held, and if it names a stored conversation its turns are read. Used by
   * the project change, by the rail, and by "Neuer Chat" (with an empty id).
   */
  const openThread = useCallback((id: string) => {
    invalidateChat();
    closeTaskStreams();
    claimedOffers.current.clear();
    resumeScope.current += 1;
    const scope = resumeScope.current;
    const forProject = projectRef.current;
    setBusy(false);
    setActiveRequest(null);
    setError('');
    setLastProvider('');
    setTurns([]);
    setThread(id);
    setOpenDispatches([]);
    freshFrom.current = 0;
    if (!id) {
      setResuming(false);
      return;
    }
    const isCurrent = () => scope === resumeScope.current && projectRef.current === forProject;
    setResuming(true);
    getConversation(id)
      .then((payload) => {
        if (!isCurrent()) return;
        const view = payload.conversation;
        const rows = resumedTurns(view || { conversation_id: id, exists: false, turn_count: 0, turns: [], turns_returned: 0 }, id);
        // Everything already in the store was not just said; it does not arrive.
        freshFrom.current = rows.length;
        const lastIkarus = [...rows].reverse().find((t) => t.role === 'ikarus');
        if (lastIkarus?.origin?.provider_used) setLastProvider(lastIkarus.origin.provider_used);
        setTurns(rows);
        setOpenDispatches(openDispatchesFrom(view));
      })
      .catch(() => {
        // A thread that cannot be read is not a thread that never existed, and
        // the difference is worth one line rather than a silently empty page.
        if (isCurrent()) setError('Der bisherige Verlauf konnte nicht gelesen werden. Neue Turns laufen trotzdem.');
      })
      .finally(() => {
        if (isCurrent()) setResuming(false);
      });
  }, [closeTaskStreams, invalidateChat]);

  useEffect(() => {
    if (!project) {
      openThread('');
      return;
    }
    setWaits(loadWaits(project));
    setEffort(loadEffort(project));
    openThread(loadThreadId(project));
    return () => {
      closeTaskStreams();
    };
  }, [closeTaskStreams, openThread, project]);

  const runtimeLabels = useMemo(() => {
    const out: Record<string, string> = {};
    for (const r of runtimes) if (r.label) out[r.id] = r.label;
    return out;
  }, [runtimes]);

  useEffect(() => {
    onThreadState?.({ id: thread, settled, labels: runtimeLabels, openDispatches });
  }, [onThreadState, openDispatches, runtimeLabels, settled, thread]);

  const ensureThread = useCallback(async (scope: number): Promise<string> => {
    if (threadRef.current) return threadRef.current;
    try {
      const payload = await newConversation();
      if (scope !== chatScope.current || projectRef.current !== project) return '';
      const id = payload.conversation_id;
      setThread(id);
      threadRef.current = id;
      saveThreadId(project, id);
      return id;
    } catch {
      // No id is not a reason to lose the turn: the backend accepts a turn
      // without one, it just will not remember it.
      return '';
    }
  }, [project]);

  /* ---- offered actions ---- */

  const updateDispatch = useCallback((turnId: string, dispatch: TaskSnapshot) => {
    setTurns((prev) => prev.map((turn) => (turn.localId === turnId ? { ...turn, dispatch } : turn)));
  }, []);

  const runAction = useCallback(
    async (
      action: IkarusAskAction,
      automatic: boolean,
      threadId: string,
      localTurnId: string,
      backendTurnId?: number,
      conversationPersisted?: boolean
    ) => {
      const objective = action.args?.objective || '';
      const lane = action.args?.lane || 'local_only';
      const scope = taskScope.current;
      const requestProject = project;
      const actionProject = action.args?.project || requestProject;
      const isCurrentRequest = () => scope === taskScope.current && projectRef.current === requestProject;
      const durableTurnId = positiveTurnId(backendTurnId);
      const hasDurableAttribution = conversationPersisted === true && Boolean(threadId) && durableTurnId !== undefined;
      try {
        const queued = await queueTask(
          actionProject,
          objective,
          lane,
          hasDurableAttribution ? threadId : undefined,
          hasDurableAttribution ? durableTurnId : undefined
        );
        if (!isCurrentRequest()) return null;
        const taskId = typeof queued.id === 'string' ? queued.id : '';
        const link = queued.conversation_link;
        const linkedAsRequested = hasDurableAttribution
          && Boolean(taskId)
          && link?.linked === true
          && link.conversation_id === threadId
          && link.turn_id === durableTurnId
          && link.dispatch_ref === taskId;
        let attributionNote = '';
        if (!hasDurableAttribution) {
          attributionNote = ' · ohne dauerhafte Turn-Zuordnung';
        } else if (!linkedAsRequested) {
          attributionNote = ` · dauerhafte Turn-Zuordnung fehlgeschlagen${link?.error ? `: ${link.error}` : ''}`;
        } else if (link?.projection_pending || link?.projection?.state === 'pending') {
          attributionNote = ' · Turn-Zuordnung gespeichert; Ergebnisprojektion wartet';
        } else if (link?.projection?.state === 'error') {
          attributionNote = ` · Turn-Zuordnung gespeichert; Ergebnisprojektion fehlgeschlagen${link.projection.error ? `: ${link.projection.error}` : ''}`;
        }
        if (!taskId) {
          updateDispatch(localTurnId, {
            id: '', found: false, state: 'unknown', source: 'queue_response', lane,
            requested_lane: lane, actual_providers: [],
            summary: null, error: 'Die Queue hat keine Task-ID zurückgegeben.',
            applied: null, applied_reason: null, stalled: false, timed_out: false
          });
          onDispatched?.();
          return `eingereiht; Fortschritt nicht adressierbar · Lane ${lane}${attributionNote}`;
        }

        let latest: TaskSnapshot = {
          id: taskId, found: true, state: 'queued', source: 'queue_response', lane,
          requested_lane: lane, actual_providers: [],
          summary: null, error: null, applied: null, applied_reason: 'noch nicht abgeschlossen',
          stalled: false, timed_out: false
        };
        updateDispatch(localTurnId, latest);

        const receive = (snapshot: TaskSnapshot) => {
          if (!isCurrentRequest()) return;
          latest = snapshot;
          updateDispatch(localTurnId, snapshot);
        };
        try {
          const taskStream = streamTask(taskId, {
            onHello: receive,
            onProgress: receive,
            onFinal: (snapshot) => {
              if (!isCurrentRequest()) return;
              taskStreams.current.delete(taskId);
              receive(snapshot);
              onDispatched?.();
            },
            onError: (streamError) => {
              if (!isCurrentRequest()) return;
              taskStreams.current.delete(taskId);
              updateDispatch(localTurnId, {
                ...latest,
                state: 'unknown',
                source: 'stream_error',
                error: `Fortschritt nicht mehr erreichbar: ${streamError.message}`,
                applied: null,
                applied_reason: 'Der Task kann weiterlaufen; sein Ergebnis ist hier nicht belegt.',
                timed_out: false
              });
            }
          });
          if (!isCurrentRequest()) {
            taskStream.close();
            return null;
          }
          taskStreams.current.get(taskId)?.close();
          taskStreams.current.set(taskId, taskStream);
        } catch (streamError) {
          if (!isCurrentRequest()) return null;
          updateDispatch(localTurnId, {
            ...latest,
            state: 'unknown',
            source: 'stream_error',
            error: `Fortschritt nicht erreichbar: ${streamError instanceof Error ? streamError.message : 'unbekannter Fehler'}`,
            applied: null,
            applied_reason: 'Der Task wurde eingereiht; sein Ergebnis ist hier nicht belegt.'
          });
        }
        if (!isCurrentRequest()) return null;
        if (automatic) {
          recordAutonomy({ what: 'Aufgabe eingereiht', detail: `${objective} · Lane ${lane}`, level: autonomyRef.current });
        }
        onDispatched?.();
        return automatic
          ? `automatisch eingereiht · Lane ${lane}${attributionNote}`
          : `eingereiht · Lane ${lane}${attributionNote}`;
      } catch (e) {
        if (!isCurrentRequest()) return null;
        return `Einreihung nicht bestätigt: ${e instanceof Error ? e.message : 'unbekannter Fehler'}. `
          + 'Nicht automatisch wiederholt; der Server könnte die Aufgabe bereits angenommen haben.';
      }
    },
    [onDispatched, project, updateDispatch]
  );

  const answerOffer = useCallback(
    async (localTurnId: string, accept: boolean) => {
      const turn = turns.find((t) => t.localId === localTurnId);
      if (!turn?.offer) return;
      const action = turn.offer;
      if (claimedOffers.current.has(localTurnId)) return;
      claimedOffers.current.add(localTurnId);

      // Clear the offer before any network await. The ref above closes the
      // same-render double-click window before React can paint this change.
      setTurns((prev) => prev.map((t) => (
        t.localId === localTurnId ? { ...t, offer: undefined, offerOutcome: accept ? 'wird eingereiht …' : 'abgelehnt' } : t
      )));
      if (!accept) {
        claimedOffers.current.delete(localTurnId);
        return;
      }
      try {
        const outcome = await runAction(action, false, thread, localTurnId, turn.backendTurnId, turn.conversationPersisted);
        if (outcome === null) return;
        setTurns((prev) => prev.map((t) => (t.localId === localTurnId ? { ...t, offerOutcome: outcome } : t)));
      } finally {
        claimedOffers.current.delete(localTurnId);
      }
    },
    [runAction, thread, turns]
  );

  /* ---- settling a turn ---- */

  const settle = useCallback(
    (
      payload: Parameters<typeof settleTurn>[1],
      threadId: string,
      localTurnId: string,
      scope: number,
      requestProject: string,
      sendClaim: symbol
    ) => {
      if (chatSendClaim.current === sendClaim) chatSendClaim.current = null;
      if (scope !== chatScope.current || projectRef.current !== requestProject) return;
      stream.current = null;
      const route = payload.provider_used || '';
      setLastProvider(route);
      /* The wait is timed here and nowhere else: the whole round trip the
         reader sat through, including minting the thread. */
      const seconds = sentAt.current ? (Date.now() - sentAt.current) / 1000 : undefined;
      if (route && seconds !== undefined) {
        setWaits((prev) => {
          const next = { ...prev, [route]: seconds };
          saveWaits(projectRef.current, next);
          return next;
        });
      }
      const action = payload.action;
      /* `vorschlaege` and above: a proposed TASK starts without a click. The
         draft that task produces is a separate decision (Decision.tsx). */
      const auto = Boolean(action) && autonomyRef.current !== 'aus';
      const backendTurnId = positiveTurnId(payload.turn_id);
      const conversationPersisted = payload.conversation_persisted;

      setTurns((prev) => prev.map((turn) => (
        turn.localId === localTurnId && turn.role === 'ikarus' ? settleTurn(turn, payload, seconds, !auto) : turn
      )));
      setBusy(false);
      setSettled((n) => n + 1);

      if (action && auto) {
        void runAction(action, true, threadId, localTurnId, backendTurnId, conversationPersisted).then((outcome) => {
          if (outcome === null || scope !== chatScope.current || projectRef.current !== requestProject) return;
          setTurns((prev) => prev.map((t) => (t.localId === localTurnId ? { ...t, offerOutcome: outcome } : t)));
        });
      }
    },
    [runAction]
  );

  /** Close only this browser's observation. The generation request remains
   * server-owned; cancelling it is an explicit, separately recorded POST. */
  const closeObservation = useCallback(() => {
    stream.current?.close();
    stream.current = null;
    // The claim was taken for the observed request; with the stream closed no
    // callback will release it, and an unreleased claim silently refuses every
    // later send (review 2026-09-02, pre-existing).
    chatSendClaim.current = null;
    setBusy(false);
    setTurns((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      if (last && last.role === 'ikarus' && last.streaming) {
        next[next.length - 1] = {
          ...last,
          streaming: false,
          halted: true,
          text: last.text || 'Die Beobachtung wurde geschlossen; ob der Server weiterarbeitet, ist hier nicht bestätigt.'
        };
      }
      return next;
    });
  }, []);

  const requestCancellation = useCallback(async () => {
    const target = activeRequest;
    if (!target) return;
    const mark = (status: ConversationCancellationStatus) => {
      setTurns((prev) => prev.map((turn) => (turn.localId === target.localTurnId ? { ...turn, cancellation: status } : turn)));
    };
    try {
      const payload = await cancelConversationTurn(target.conversationId, target.requestId, clientId('cancel'));
      const status = payload.cancellation?.status || 'unknown';
      mark(status);
      if (status === 'already_terminal' || status === 'unknown') setActiveRequest(null);
    } catch (reason) {
      const notSupported = reason instanceof ApiError
        && reason.kind === 'notfound'
        && /unknown endpoint|kennt .* nicht/i.test(reason.message);
      const status: ConversationCancellationStatus = notSupported ? 'not_supported' : 'unknown';
      mark(status);
      if (status !== 'not_supported') setActiveRequest(null);
    }
  }, [activeRequest]);

  /** A fresh thread. The old one stays in the store; this stops carrying it. */
  const newThread = useCallback(() => {
    closeObservation();
    saveThreadId(project, '');
    openThread('');
  }, [closeObservation, openThread, project]);

  // The rail picked a thread — or asked for a new one (empty id). Same id
  // twice is still a request (the serial moved), so re-picking the open
  // thread re-reads it.
  const handledPick = useRef(0);
  useEffect(() => {
    if (!pickThread || pickThread.serial === handledPick.current) return;
    handledPick.current = pickThread.serial;
    if (!project) return;
    if (!pickThread.id) {
      newThread();
      return;
    }
    saveThreadId(project, pickThread.id);
    openThread(pickThread.id);
  }, [newThread, openThread, pickThread, project]);

  /** A note the surface wrote itself: rendered, stamped OBERFLÄCHE, never sent. */
  const addNote = useCallback((text: string) => {
    turnSerial.current += 1;
    setTurns((prev) => [...prev, { role: 'note', text, localId: `note-${turnSerial.current}` }]);
  }, []);

  /* ---- sending ---- */

  const sendMessage = useCallback(async (message: string) => {
    if (!message || busy || chatSendClaim.current !== null || !project) return;
    const scope = chatScope.current;
    const requestProject = project;
    const sendClaim = Symbol('ikarus-chat-send');
    chatSendClaim.current = sendClaim;
    const releaseSendClaim = () => {
      if (chatSendClaim.current === sendClaim) chatSendClaim.current = null;
    };
    lastSent.current = message;
    setDraft('');
    setError('');
    setBusy(true);
    pinned.current = true;
    sentAt.current = Date.now();

    /* WHAT IS SENT IS WHAT WAS TYPED. The turns go up BEFORE the thread id is
       awaited: minting a thread is a round trip measured at 17-26s under load,
       and doing it first left the box empty and the page silent that long. */
    turnSerial.current += 1;
    const exchangeId = `turn-${turnSerial.current}`;
    const replyId = `${exchangeId}-ikarus`;
    const sentEffort = effort;
    setTurns((prev) => [
      ...prev,
      { role: 'you', text: message, localId: `${exchangeId}-you` },
      { role: 'ikarus', text: '', streaming: true, localId: replyId, effort: sentEffort }
    ]);

    const threadId = await ensureThread(scope);
    if (scope !== chatScope.current || projectRef.current !== requestProject) {
      releaseSendClaim();
      return;
    }

    if (!threadId) {
      releaseSendClaim();
      setBusy(false);
      setTurns((prev) => prev.map((turn) => (
        turn.localId === replyId
          ? { ...turn, streaming: false, halted: true, text: 'Der Verlauf konnte nicht angelegt werden; es wurde keine Anfrage gestartet.' }
          : turn
      )));
      setError('Ikarus-Turn nicht gestartet, weil kein dauerhafter Verlauf verfügbar ist.');
      return;
    }

    const contextRefs = editorAttachment.state === 'attached' ? [editorAttachment.ref] : [];
    const isCurrent = () => scope === chatScope.current && projectRef.current === requestProject;
    const patchReply = (patch: (turn: Turn) => Turn) => {
      setTurns((prev) => prev.map((turn) => (turn.localId === replyId ? patch(turn) : turn)));
    };
    const failCreation = (creationError: Error) => {
      releaseSendClaim();
      if (!isCurrent()) return;
      setBusy(false);
      patchReply((turn) => ({
        ...turn,
        streaming: false,
        halted: true,
        text: turn.text || 'Der Turn konnte nicht eindeutig angelegt werden; sein Serverzustand ist unbekannt.'
      }));
      setError(`Ikarus-Turn konnte nicht bestätigt werden (${creationError.message}). Die POST-Anfrage wird nicht automatisch wiederholt.`);
    };

    try {
      // This is the single effectful transition. Its client_request_id binds
      // retries to the same canonical request; EventSource below only observes
      // the returned request id and can safely reconnect without another POST.
      const created = await createConversationTurn(threadId, {
        client_request_id: clientId('turn'),
        project: requestProject,
        message,
        provider,
        effort: sentEffort,
        context_refs: contextRefs
      });
      const request = created.turn_request;
      if (!isCurrent()) {
        releaseSendClaim();
        return;
      }
      if (!request || !Number.isSafeInteger(request.request_id) || request.request_id <= 0) {
        throw new Error('Der Server hat keine gültige Turn-Request-ID geliefert.');
      }
      setActiveRequest({ conversationId: threadId, requestId: request.request_id, localTurnId: replyId });
      patchReply((turn) => ({ ...turn, requestId: request.request_id, contextRefs }));

      const endUnconfirmed = (text: string, cancellation?: ConversationCancellationStatus) => {
        releaseSendClaim();
        if (!isCurrent()) return;
        stream.current = null;
        setActiveRequest((current) => (current?.requestId === request.request_id ? null : current));
        setBusy(false);
        patchReply((turn) => ({ ...turn, streaming: false, halted: true, cancellation: cancellation ?? turn.cancellation, text: turn.text || text }));
      };

      stream.current = observeConversationTurn(threadId, request.request_id, {
        onStart: (data) => {
          if (!isCurrent()) return;
          const started = {
            intent: typeof data.intent === 'string' ? data.intent : undefined,
            shell: typeof (data as { shell?: unknown }).shell === 'string' ? String((data as { shell?: unknown }).shell) : undefined,
            provider_used: typeof data.provider_used === 'string' ? data.provider_used : undefined
          };
          patchReply((turn) => ({ ...turn, started }));
        },
        onDelta: (text) => {
          if (!isCurrent()) return;
          patchReply((turn) => ({ ...turn, text: turn.text + text }));
        },
        onFinal: (payload) => {
          setActiveRequest((current) => (current?.requestId === request.request_id ? null : current));
          settle(payload, threadId, replyId, scope, requestProject, sendClaim);
        },
        onCancelled: (cancellation) => {
          endUnconfirmed('Der Server hat den Abbruch bestätigt.', cancellation.status);
        },
        onError: (observationError) => {
          endUnconfirmed('Der Server meldet für diesen Turn keinen bestätigten Abschluss.');
          if (isCurrent()) setError(`Ikarus-Turn beendet mit unbestätigtem Ergebnis: ${observationError.message}`);
        },
        onState: (status) => {
          if (!isCurrent()) return;
          if (status.cancellation?.status) {
            const cancellation = status.cancellation.status;
            patchReply((turn) => ({ ...turn, cancellation }));
          }
          if (status.state === 'final' && status.final) {
            setActiveRequest((current) => (current?.requestId === request.request_id ? null : current));
            settle(status.final, threadId, replyId, scope, requestProject, sendClaim);
          } else if (status.state === 'cancelled') {
            endUnconfirmed('Der Server hat den Abbruch bestätigt.', 'confirmed');
          } else if (status.state === 'unknown') {
            endUnconfirmed('Der Turn-Zustand ist nach der Beobachtung unbekannt.', status.cancellation?.status || 'unknown');
          }
        }
      });
    } catch (creationError) {
      failCreation(creationError instanceof Error ? creationError : new Error('Der Turn konnte nicht angelegt werden.'));
    }
  }, [busy, editorAttachment, effort, ensureThread, project, provider, settle]);

  /* ---- commands ---- */

  const chooseEffort = useCallback((level: EffortLevel) => {
    setEffort(level);
    if (project) saveEffort(project, level);
  }, [project]);

  const runCommand = useCallback((action: CommandAction): boolean => {
    switch (action.kind) {
      case 'send':
        void sendMessage(action.message);
        return true;
      case 'unknown':
        void sendMessage(action.message);
        return true;
      case 'plan':
        setDraft(action.text);
        setPlanSignal((n) => n + 1);
        return true;
      case 'map': {
        const found = resolveModule(action.module);
        if (found) {
          setDraft('');
          onFocusModule(found);
          onGoMap?.();
        } else {
          setError(`Kein Modul in der Karte passt zu „${action.module}“.`);
        }
        return true;
      }
      case 'new':
        setDraft('');
        newThread();
        return true;
      case 'model':
        setDraft('');
        setBrainSignal((n) => n + 1);
        return true;
      case 'effort':
        setDraft('');
        chooseEffort(action.level);
        return true;
      case 'cancel':
        setDraft('');
        if (activeRequest) void requestCancellation();
        else setError('Kein Turn läuft, den man abbrechen könnte.');
        return true;
      case 'help':
        setDraft('');
        addNote(helpText());
        return true;
      case 'incomplete':
        // The menu already shows the hint; the draft stays where it is.
        return true;
      default:
        return false;
    }
  }, [activeRequest, addNote, chooseEffort, newThread, onFocusModule, onGoMap, requestCancellation, resolveModule, sendMessage]);

  const send = useCallback(async () => {
    const message = draft.trim();
    if (!message) return;
    const action = parseCommand(message);
    if (action && runCommand(action)) return;
    await sendMessage(message);
  }, [draft, runCommand, sendMessage]);

  const pickCommand = useCallback((spec: CommandSpec) => {
    if (spec.arg) {
      setDraft(`/${spec.name} `);
      composer.current?.focus();
      return;
    }
    const action = parseCommand(`/${spec.name}`);
    if (action) runCommand(action);
  }, [runCommand]);

  /* ---- derived ---- */

  /** Nothing said yet — the page becomes an invitation rather than a form. */
  const empty = !resuming && turns.length === 0;
  /** The identifying part of the thread id (`conv_2026…_e90e07e2` → `e90e07e2`). */
  const threadTag = thread ? /_([0-9a-f]{6,})$/i.exec(thread)?.[1] || thread.slice(-8) : '';
  /** A runtime id in the reader's words, or nothing when that is not known. */
  const labelOf = useCallback(
    (id: string): string | undefined =>
      id === 'deterministic' ? 'lokaler Index' : runtimes.find((r) => r.id === id)?.label || undefined,
    [runtimes]
  );
  /** DERIVED, not stored: the ledger, stamp and citations of every turn. */
  const receipts = useMemo(
    () => turns.map((t) => ({
      stamp: stampForTurn(t, labelOf),
      ledger: ledgerFor(t, labelOf),
      cites: t.role === 'ikarus' && !t.streaming ? citationsFrom(t.text, resolveModule) : ([] as Citation[])
    })),
    [labelOf, resolveModule, turns]
  );
  const showNudge = Boolean(!busy && !provider && lastProvider === 'deterministic' && runtimes.some((r) => r.available));
  const armed = Boolean(draft.trim()) && !busy && Boolean(project);
  const exchanges = turns.filter((t) => t.role === 'you').length;
  const hasThread = Boolean(thread) || turns.length > 0;
  const lastIkarusId = [...turns].reverse().find((t) => t.role === 'ikarus')?.localId;

  const commandMode = !busy && looksLikeCommand(draft) && !cmdDismissed;
  const hasArg = /^\/[a-zäöü]+\s+\S/i.test(draft);
  const commands = commandMode && !hasArg ? matchCommands(draft) : [];
  const parsed = commandMode ? parseCommand(draft) : null;
  const cmdHint = parsed?.kind === 'incomplete' ? parsed.hint : undefined;
  const menuOpen = commandMode && (commands.length > 0 || Boolean(cmdHint) || !hasArg);
  const activeCommand = commands[Math.min(cmdActive, Math.max(0, commands.length - 1))];

  const onComposerKey = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.nativeEvent.isComposing) return;
    if (menuOpen && commands.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setCmdActive((i) => Math.min(i + 1, commands.length - 1));
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setCmdActive((i) => Math.max(i - 1, 0));
        return;
      }
      if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey)) {
        e.preventDefault();
        if (activeCommand) pickCommand(activeCommand);
        return;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        setCmdDismissed(true);
        return;
      }
    }
    if (e.key === 'Escape' && menuOpen) {
      e.preventDefault();
      setCmdDismissed(true);
      return;
    }
    if (e.key === 'ArrowUp' && !draft && lastSent.current) {
      e.preventDefault();
      setDraft(lastSent.current);
      return;
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  }, [activeCommand, commands.length, draft, menuOpen, pickCommand, send]);

  /* ---------------------------------------------------------------- view */

  return (
    <section
      className={['convo', compact ? 'compact' : '', empty ? 'at-rest' : ''].filter(Boolean).join(' ')}
      aria-label="Gespräch mit Ikarus"
    >
      {hasThread && (
        <motion.div className="convo-bar" data-motion="bar" variants={reveal} initial="hidden" animate="visible">
          <span className="convo-thread">
            <span className="convo-thread-role">Verlauf</span>
            <span>
              {exchanges} {exchanges === 1 ? 'Turn' : 'Turns'}
            </span>
            {threadTag && <code>{threadTag}</code>}
          </span>
          <span className="convo-bar-rule" aria-hidden="true" />
          {busy && (
            <span className="convo-elapsed" role="status">
              antwortet · {elapsedLabel(elapsed)}
            </span>
          )}
          <button type="button" onClick={newThread}>
            Neuer Chat
          </button>
        </motion.div>
      )}

      <div className="convo-body">
        <div className={empty ? 'convo-scroll empty' : 'convo-scroll'} ref={scroller} onScroll={onScroll} role="log" aria-live="polite" aria-busy={busy}>
          {resuming && <p className="convo-reading">Verlauf wird gelesen …</p>}

          {empty && (
            <div className="convo-open">
              <h2 className="convo-open-line">
                Frag Ikarus etwas über <b>{project || 'dieses Projekt'}</b>.
              </h2>
              <p className="convo-open-note">
                Ikarus wählt automatisch ein verfügbares LLM. Gemessene lokale Antworten bleiben klar von Modellantworten getrennt,
                und jede Antwort trägt ihr Protokoll: Route, Kontext, Prüfung, Auftrag.
              </p>
              <div className="convo-suggestions" aria-label="Vorschläge">
                {['Erklär mir die Architektur dieses Projekts.', 'Wo würdest du als Nächstes refactoren?', '/status'].map((suggestion) => (
                  <button key={suggestion} type="button" onClick={() => setDraft(suggestion)}>{suggestion}</button>
                ))}
              </div>
            </div>
          )}

          {turns.map((t, i) => {
            const receipt = receipts[i];
            const id = t.localId || `turn-${i}`;
            return (
              <motion.article
                key={id}
                className={`turn ${t.role}`}
                data-motion="bubble"
                variants={t.role === 'you' ? youArrive : ikarusArrive}
                initial={i >= freshFrom.current ? 'hidden' : false}
                animate="visible"
              >
                <span className="visually-hidden">{t.role === 'you' ? 'Du' : t.role === 'note' ? 'Hinweis der Oberfläche' : 'Ikarus'}</span>
                <div className="turn-body">
                  {t.role === 'you' ? (
                    <p className="turn-text">{t.text}</p>
                  ) : (
                    <MarkdownMessage text={t.text} streaming={t.streaming} elapsed={t.streaming ? elapsed : undefined} />
                  )}

                  {t.role === 'note' && receipt.stamp && (
                    <span className="stamp note">
                      <span className="stamp-word">{receipt.stamp.word}</span>
                      <span className="stamp-origin">{receipt.stamp.origin}</span>
                    </span>
                  )}

                  {t.role === 'ikarus' && (
                    <>
                      <Ledger rows={receipt.ledger} />

                      {receipt.cites.length > 0 && (
                        <div className="turn-cites" aria-label="Genannte Module">
                          {receipt.cites.map((c) => (
                            <button key={c.seen} type="button" className="cite" onClick={() => onFocusModule(c.module)}>
                              {c.seen}
                            </button>
                          ))}
                        </div>
                      )}

                      {t.offer && (
                        <div className="offer-acts" role="group" aria-label="Vorgeschlagene Aktion beantworten">
                          <button type="button" className="primary" onClick={() => void answerOffer(id, true)}>
                            Loslegen
                          </button>
                          <button type="button" onClick={() => void answerOffer(id, false)}>
                            Nicht jetzt
                          </button>
                        </div>
                      )}

                      {(Boolean(t.text && !t.streaming) || activeRequest?.requestId === t.requestId) && (
                        <div className="turn-actions" aria-label="Antwortaktionen">
                          {t.text && !t.streaming && (
                            <button
                              type="button"
                              onClick={() => {
                                void navigator.clipboard.writeText(t.text).then(() => {
                                  setCopiedTurn(id);
                                  window.setTimeout(() => setCopiedTurn((current) => (current === id ? null : current)), 1200);
                                });
                              }}
                            >
                              {copiedTurn === id ? 'Kopiert' : 'Antwort kopieren'}
                            </button>
                          )}
                          {activeRequest?.requestId === t.requestId && t.requestId !== undefined && (
                            <button
                              type="button"
                              className="turn-cancel"
                              onClick={() => void requestCancellation()}
                              disabled={t.cancellation === 'requested'}
                            >
                              {t.cancellation === 'requested' ? 'Abbruch angefordert' : 'Abbruch anfordern'}
                            </button>
                          )}
                        </div>
                      )}

                      {showNudge && id === lastIkarusId && (
                        <p className="turn-nudge">
                          <span>Ohne Modell beantwortet. Nächste Frage an</span>
                          {runtimes.filter((r) => r.available).map((r) => (
                            <button key={r.id} type="button" onClick={() => onProvider?.(r.id)}>
                              {r.label || r.id}
                            </button>
                          ))}
                        </p>
                      )}
                    </>
                  )}
                </div>
              </motion.article>
            );
          })}
        </div>

        <AnimatePresence>
          {unread && (
            <motion.button
              type="button"
              className="convo-jump"
              data-motion="jump"
              variants={reveal}
              initial="hidden"
              animate="visible"
              exit="hidden"
              onClick={jumpToEnd}
            >
              Neue Antwort ↓
            </motion.button>
          )}
        </AnimatePresence>
      </div>

      {error && (
        <p className="convo-error" role="alert">
          {error}
        </p>
      )}

      {/* ONE CONTROL: the box, what will be read with it, and send share a
          border, a radius and a focus ring. The rail under the input reads in
          the order the facts matter: who answers, how hard, what is on the
          stage, what would be read. */}
      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <div className="composer-line">
          <AnimatePresence>
            {menuOpen && (
              <CommandMenu
                id="cmd-menu"
                commands={commands}
                activeIndex={Math.min(cmdActive, Math.max(0, commands.length - 1))}
                onActive={setCmdActive}
                onPick={pickCommand}
                hint={cmdHint}
              />
            )}
          </AnimatePresence>
          <textarea
            ref={composer}
            value={draft}
            rows={1}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onComposerKey}
            placeholder={busy ? 'Du kannst schon weiterschreiben …' : 'Nachricht an Ikarus … („/“ für Befehle)'}
            aria-label="Nachricht an Ikarus"
            aria-autocomplete={menuOpen ? 'list' : undefined}
            aria-controls={menuOpen && commands.length > 0 ? 'cmd-menu' : undefined}
            aria-activedescendant={menuOpen && activeCommand ? `cmd-menu-${activeCommand.name}` : undefined}
            autoComplete="off"
            disabled={!project}
          />
          <motion.button
            type={busy ? 'button' : 'submit'}
            className={busy ? 'composer-send stopping' : 'composer-send'}
            data-motion="send"
            variants={arm}
            initial={false}
            animate={armed || busy ? 'armed' : 'idle'}
            whileTap={pressProps(reduced)}
            onClick={busy ? closeObservation : undefined}
            disabled={!armed && !busy}
            aria-label={busy ? 'Beobachtung schließen' : 'Senden'}
            title={busy ? 'Schließt nur diese Browser-Beobachtung. Ein Server-Abbruch wird separat angefordert.' : undefined}
          >
            {busy ? <StopGlyph /> : <SendGlyph />}
          </motion.button>
        </div>

        {/* THE PRE-FLIGHT RAIL, one wrapping row: who answers, how hard, what
            is on the stage, what would be read. It wraps rather than
            overlapping — at 550px the four facts do not fit on one line. */}
        <div className="composer-rail">
          <BrainPicker
            runtimes={runtimes}
            state={runtimeState}
            value={provider || ''}
            onChange={onProvider}
            waits={waits}
            lastRoute={lastProvider}
            labelOf={labelOf}
            onRecheck={readRuntimes}
            openSignal={brainSignal}
          />

          <EffortPicker value={effort} onChange={chooseEffort} disabled={!project} />

          {contextModule && (
            <div className="composer-stage">
              <span className="composer-stage-label">Bühne</span>
              <code title={contextModule}>{shortLabel(contextModule)}</code>
              <button
                type="button"
                onClick={() => setDraft((d) => (d ? `${d.replace(/\s+$/, '')} ${contextModule} ` : `${contextModule} `))}
                title="Den Pfad in deine Frage einfügen"
              >
                Einfügen
              </button>
            </div>
          )}

          <ContextPlan
            project={project}
            objective={draft}
            onFocusModule={onFocusModule}
            resolveModule={resolveModule}
            openSignal={planSignal}
          />
        </div>

        {editorAttachment.state !== 'idle' && (
          <div
            className={`editor-attachment ${editorAttachment.state}`}
            role={editorAttachment.state === 'attached' || editorAttachment.state === 'loading' ? 'status' : 'note'}
            aria-label="Editor-Anhang"
          >
            <span className="editor-attachment-label">Editor-Anhang</span>
            {editorAttachment.state === 'loading' ? (
              <span>Kontext wird geprüft …</span>
            ) : editorAttachment.state === 'attached' ? (
              <>
                <code title={editorAttachment.context.path}>{shortLabel(editorAttachment.context.path)}</code>
                <span>{editorAttachment.context.selection_chars} Zeichen</span>
                <span className="editor-attachment-status">
                  Inclusion-Status: akzeptiert · {editorAttachment.context.inclusion_report?.reason || 'validierter lokaler Kontext'}
                </span>
              </>
            ) : (
              <>
                {'context' in editorAttachment && editorAttachment.context?.path && (
                  <code title={editorAttachment.context.path}>{shortLabel(editorAttachment.context.path)}</code>
                )}
                <span className="editor-attachment-status">Inclusion-Status: nicht enthalten · {editorAttachment.reason}</span>
              </>
            )}
          </div>
        )}
      </form>
    </section>
  );
}
