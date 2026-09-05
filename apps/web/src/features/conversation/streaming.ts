/** A browser-frame scheduler, injected so byte preservation is testable in Node. */
export type FrameScheduler = (callback: () => void) => number;
export type FrameCanceller = (handle: number) => void;

export interface TextBatcher {
  /** Add bytes in arrival order and schedule at most one pending paint. */
  push(text: string): void;
  /** Emit pending bytes now, but keep accepting later chunks. */
  flush(): void;
  /** Emit pending bytes exactly once and refuse later chunks. */
  finish(): void;
  /** Drop pending bytes because their thread/scope is no longer visible. */
  discard(): void;
}

/**
 * Coalesce transport-sized deltas into paint-sized updates. The transport
 * remains authoritative: chunks are concatenated verbatim and terminal paths
 * synchronously drain the buffer before rendering their outcome.
 */
export function createTextBatcher(
  deliver: (text: string) => void,
  schedule: FrameScheduler,
  cancelScheduled: FrameCanceller
): TextBatcher {
  let pending = '';
  let frame: number | null = null;
  let closed = false;

  const drain = () => {
    frame = null;
    if (!pending || closed) return;
    const text = pending;
    pending = '';
    deliver(text);
  };

  const cancelFrame = () => {
    if (frame === null) return;
    cancelScheduled(frame);
    frame = null;
  };

  return {
    push(text) {
      if (closed || !text) return;
      pending += text;
      if (frame === null) frame = schedule(drain);
    },
    flush() {
      if (closed) return;
      cancelFrame();
      drain();
    },
    finish() {
      if (closed) return;
      cancelFrame();
      drain();
      closed = true;
    },
    discard() {
      if (closed) return;
      cancelFrame();
      pending = '';
      closed = true;
    }
  };
}
