import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ApiError,
  getLoopArchitecture,
  getLoopAttempts,
  getLoopQueue,
  type LoopArchitecturePayload,
  type LoopAttemptsPayload,
  type LoopQueuePayload
} from '../api';

/**
 * One in-flight read of one endpoint, with the failure KIND preserved.
 *
 * `error` is not a string here on purpose: "nothing answered" and "the
 * endpoint refused" have to reach the renderer as different facts, because
 * they render as different health states (unknown vs degraded) and one of them
 * comes with "start the backend" as the remedy.
 */
export interface Fetched<T> {
  data?: T;
  loading: boolean;
  error: { kind: string; message: string } | null;
  loadedAt: number | null;
}

const IDLE = { loading: false, error: null, loadedAt: null } as const;

function toFailure(err: unknown): { kind: string; message: string } {
  if (err instanceof ApiError) return { kind: err.kind, message: err.message };
  return { kind: 'http', message: err instanceof Error ? err.message : String(err) };
}

export interface LoopData {
  queue: Fetched<LoopQueuePayload>;
  attempts: Fetched<LoopAttemptsPayload>;
  architecture: Fetched<LoopArchitecturePayload>;
  reload: () => void;
  /** True while ANY of the three is in flight. */
  busy: boolean;
}

/**
 * The self-improvement loop's three read-only surfaces, fetched together.
 *
 * Together on purpose: the architecture snapshot is the thing the queue's
 * highest bands are ranked FROM, so reading one without the other produces the
 * classic half-truth — a short queue with no visible reason. Each keeps its own
 * failure, so one dead endpoint never blanks the other two.
 */
export function useLoop(project: string, enabled: boolean): LoopData {
  const [queue, setQueue] = useState<Fetched<LoopQueuePayload>>(IDLE);
  const [attempts, setAttempts] = useState<Fetched<LoopAttemptsPayload>>(IDLE);
  const [architecture, setArchitecture] = useState<Fetched<LoopArchitecturePayload>>(IDLE);
  // Monotonic guard: a slow first response must never overwrite a fast second.
  const serial = useRef(0);

  const reload = useCallback(() => {
    const mine = ++serial.current;
    const commit = <T,>(set: (v: Fetched<T>) => void) => ({
      ok: (data: T) => { if (mine === serial.current) set({ data, loading: false, error: null, loadedAt: Date.now() }); },
      fail: (err: unknown) => { if (mine === serial.current) set({ loading: false, error: toFailure(err), loadedAt: null }); }
    });

    setQueue((p) => ({ ...p, loading: true }));
    setAttempts((p) => ({ ...p, loading: true }));
    setArchitecture((p) => ({ ...p, loading: true }));

    const q = commit(setQueue);
    getLoopQueue(project || undefined, 10).then(q.ok, q.fail);
    const a = commit(setAttempts);
    getLoopAttempts(20).then(a.ok, a.fail);
    const c = commit(setArchitecture);
    getLoopArchitecture(project || undefined).then(c.ok, c.fail);
  }, [project]);

  useEffect(() => {
    if (!enabled) return;
    reload();
  }, [enabled, reload]);

  return {
    queue,
    attempts,
    architecture,
    reload,
    busy: queue.loading || attempts.loading || architecture.loading
  };
}
