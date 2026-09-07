import { expect, test } from '@playwright/test';
import { liveExecutionStatus } from '../src/cockpit/liveExecution';

test.describe('live execution evidence', () => {
  test('renders current counters as live execution evidence', () => {
    expect(liveExecutionStatus({ streamLive: true, inFlight: 2, queued: 3 })).toEqual({
      text: 'Ausführung live · 2 aktiv · 3 wartend',
      tone: 'ok',
      stale: false
    });
    expect(liveExecutionStatus({ streamLive: true, inFlight: 0, queued: 0 })).toEqual({
      text: 'Ausführung live · nichts aktiv',
      tone: 'ok',
      stale: false
    });
  });

  test('marks cached counters stale as soon as the event stream is gone', () => {
    expect(liveExecutionStatus({ streamLive: false, inFlight: 2, queued: 1 })).toEqual({
      text: 'Ereignisstrom getrennt · letzter Stand: 2 aktiv · 1 wartend',
      tone: 'warn',
      stale: true
    });
  });

  test('does not invent execution state when no observation exists', () => {
    expect(liveExecutionStatus({ streamLive: false })).toEqual({
      text: 'kein Ereignisstrom · Ausführungsstand unbekannt',
      tone: 'muted',
      stale: true
    });
  });

  test('rejects invalid counters instead of rendering impossible task counts', () => {
    expect(liveExecutionStatus({ streamLive: true, inFlight: -1, queued: Number.NaN })).toEqual({
      text: 'Ausführung live · Zähler unbekannt',
      tone: 'warn',
      stale: false
    });
    expect(liveExecutionStatus({ streamLive: true, inFlight: 1.9, queued: 0.2 })).toEqual({
      text: 'Ausführung live · 1 aktiv · 0 wartend',
      tone: 'ok',
      stale: false
    });
  });
});
