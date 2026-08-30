// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useRef, useState } from 'react';
import { openEventStream } from '../api';
import type { LiveHeartbeat, LiveHello, LiveQueue, LiveReport } from '../types';

/** SSE connection health. `down` is the signal to fall back to polling. */
export type EventStatus = 'live' | 'connecting' | 'down';

export interface EventStreamHandlers {
  onHello?: (data: LiveHello) => void;
  onReport?: (data: LiveReport) => void;
  onHeartbeat?: (data: LiveHeartbeat) => void;
  onQueue?: (data: LiveQueue) => void;
}

/**
 * Subscribe to the live `/api/events` stream for a project.
 *
 * Dispatches `hello|report|heartbeat|queue` to the supplied callbacks and
 * returns a `status` the caller uses to drive a live/polling chip and gate a
 * degraded polling fallback. The stream self-heals (`EventSource` auto-
 * reconnects when the server recycles it) — on any error we flip to `down` so
 * the caller can poll, then back to `live` once messages resume.
 *
 * Handlers are read through a ref so passing fresh closures each render never
 * tears down and reopens the connection.
 */
export function useEventSource(project: string, handlers: EventStreamHandlers): { status: EventStatus } {
  const [status, setStatus] = useState<EventStatus>('connecting');
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  useEffect(() => {
    if (!project || typeof EventSource === 'undefined') {
      setStatus('down');
      return;
    }
    setStatus('connecting');
    let closed = false;
    let es: EventSource | undefined;

    try {
      es = openEventStream(project, (name, data) => {
        if (closed) return;
        setStatus('live');
        const h = handlersRef.current;
        if (name === 'hello') h.onHello?.(data as LiveHello);
        else if (name === 'report') h.onReport?.(data as LiveReport);
        else if (name === 'heartbeat') h.onHeartbeat?.(data as LiveHeartbeat);
        else if (name === 'queue') h.onQueue?.(data as LiveQueue);
      });
      es.onopen = () => {
        if (!closed) setStatus('live');
      };
      es.onerror = () => {
        // EventSource keeps retrying on its own; reflect the degraded state so
        // the UI shows `polling` and the caller's fallback interval kicks in.
        if (!closed) setStatus('down');
      };
    } catch {
      setStatus('down');
      return;
    }

    return () => {
      closed = true;
      es?.close();
    };
  }, [project]);

  return { status };
}
