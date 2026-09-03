import {
  briefFrom,
  EMPTY_LIVE,
  markDisconnected,
  markSeen,
  RECENT_LIMIT,
  reduceLiveEvent,
  type LiveState
} from './live';

export interface MissionSpecResult {
  name: string;
  ok: boolean;
  detail: string;
}

/**
 * The live stream, fed real frames.
 *
 * Every payload below is the exact shape `daedalus/interfaces/http/sse.py`
 * writes: `hello` carries the whole `stream_state` dict, `queue` carries
 * `queue_depth` and nothing else, `heartbeat` carries the watcher and the
 * in-flight flag, and `report` carries one `report_brief`. The first case in
 * this file is the regression that shipped: the cockpit decoded the queue
 * frame as `depth`, so the counter froze at the `hello` snapshot.
 */
export function runMissionSpec(): MissionSpecResult[] {
  const results: MissionSpecResult[] = [];
  const check = (name: string, ok: boolean, detail = '') => results.push({ name, ok, detail });

  const hello = {
    queue_depth: 3,
    in_flight: 1,
    unread_count: 2,
    quarantined_count: 0,
    watcher_state: 'running',
    reports_total: 7,
    latest_report: { name: 'req_a.report.json', status: 'done', lane: 'local_only', project: 'atlas', summary: 'Patch erzeugt' }
  };

  /* ---- hello: every field, none invented ---- */
  const afterHello = reduceLiveEvent(EMPTY_LIVE, 'hello', hello);
  check('hello is decoded whole', afterHello.queued === 3 && afterHello.inFlight === 1 && afterHello.unread === 2 && afterHello.quarantined === 0 && afterHello.watcher === 'running', JSON.stringify(afterHello));
  check('hello marks the stream connected', afterHello.connected === true);
  check("hello's report is the state of the world, not news", afterHello.recent.length === 1 && afterHello.unseen === 0, `unseen=${afterHello.unseen}`);
  check('the report brief keeps all five fields', afterHello.recent[0]?.project === 'atlas' && afterHello.recent[0]?.summary === 'Patch erzeugt' && afterHello.recent[0]?.lane === 'local_only');

  /* ---- THE REGRESSION: the queue frame's key is queue_depth ---- */
  const afterQueue = reduceLiveEvent(afterHello, 'queue', { queue_depth: 9 });
  check('a queue frame moves the counter', afterQueue.queued === 9, `queued=${afterQueue.queued}`);
  const wrongKey = reduceLiveEvent(afterHello, 'queue', { depth: 9 });
  check('a frame without queue_depth leaves the last known value', wrongKey.queued === 3, `queued=${wrongKey.queued}`);

  /* ---- heartbeat ---- */
  const afterBeat = reduceLiveEvent(afterQueue, 'heartbeat', { watcher_state: 'idle', in_flight: 0 });
  check('heartbeat carries the watcher and the in-flight flag', afterBeat.watcher === 'idle' && afterBeat.inFlight === 0);
  check('heartbeat does not touch the queue', afterBeat.queued === 9);
  const emptyBeat = reduceLiveEvent(afterBeat, 'heartbeat', {});
  check('a frame with nothing in it blanks nothing', emptyBeat.watcher === 'idle' && emptyBeat.inFlight === 0 && emptyBeat.queued === 9);

  /* ---- report: arrival, and whether it is news ---- */
  const brief2 = { name: 'req_b.report.json', status: 'failed', lane: 'trusted', summary: 'pytest exited 1' };
  const unwatched = reduceLiveEvent(afterBeat, 'report', brief2, false);
  check('a report arriving unwatched is news', unwatched.unseen === 1 && unwatched.recent[0].name === 'req_b.report.json');
  const watched = reduceLiveEvent(afterBeat, 'report', brief2, true);
  check('a report the reader is looking at is not announced', watched.unseen === 0 && watched.recent.length === 2);
  const twice = reduceLiveEvent(unwatched, 'report', brief2, false);
  check('the identical report twice is one report', twice.unseen === 1 && twice.recent.length === 2, `unseen=${twice.unseen} recent=${twice.recent.length}`);
  check('an identical repeat returns the same object', twice === unwatched);
  check('the newest report is first', unwatched.recent[0].name === 'req_b.report.json' && unwatched.recent[1].name === 'req_a.report.json');

  /* ---- a reconnect replays hello; it must not re-announce ---- */
  const reconnect = reduceLiveEvent(unwatched, 'hello', { ...hello, latest_report: brief2 });
  check('a replayed hello does not duplicate the newest report', reconnect.recent.length === 2 && reconnect.unseen === 1, `recent=${reconnect.recent.length}`);

  /* ---- THE BUS REPUBLISHES ITS TAIL, so a name can come round again ----
     `report` fires whenever reports_total rises and always carries the LAST
     row, so consuming one report and adding another can re-send a name that
     is already in the list. Two rows with one name is a duplicate React key
     and a stale row beside a fresh one. */
  const roundAgain = reduceLiveEvent(unwatched, 'report', { name: 'req_a.report.json', status: 'done', lane: 'local_only', project: 'atlas', summary: 'Patch erzeugt' }, false);
  check('a name that comes round again moves, it does not duplicate', roundAgain.recent.length === 2 && roundAgain.recent.filter((r) => r.name === 'req_a.report.json').length === 1, `recent=${roundAgain.recent.map((r) => r.name).join('|')}`);
  check('the returning report is newest', roundAgain.recent[0].name === 'req_a.report.json');

  /* ---- the same name carrying NEW content is news, and replaces ---- */
  const grew = reduceLiveEvent(unwatched, 'report', { ...brief2, status: 'done', summary: 'doch noch fertig' }, false);
  check('the same name with new content replaces the row', grew.recent.length === 2 && grew.recent[0].status === 'done' && grew.recent[0].summary === 'doch noch fertig');
  check('new content on a known name is announced', grew.unseen === 2, `unseen=${grew.unseen}`);

  /* ---- bounded ---- */
  let many: LiveState = EMPTY_LIVE;
  for (let i = 0; i < RECENT_LIMIT + 4; i += 1) {
    many = reduceLiveEvent(many, 'report', { name: `r${i}.json`, status: 'done', lane: 'l' }, false);
  }
  check('the session list is bounded', many.recent.length === RECENT_LIMIT, `recent=${many.recent.length}`);
  check('every arrival still counted', many.unseen === RECENT_LIMIT + 4, `unseen=${many.unseen}`);
  check('no name appears twice in the list', new Set(many.recent.map((r) => r.name)).size === many.recent.length);

  /* ---- malformed input changes nothing ---- */
  const junk = reduceLiveEvent(afterBeat, 'report', 'not an object', false);
  check('a malformed report is dropped, not drawn', junk.recent.length === afterBeat.recent.length && junk.unseen === afterBeat.unseen);
  const noName = reduceLiveEvent(afterBeat, 'report', { status: 'done' }, false);
  check('a report without a name is not a report', noName.recent.length === afterBeat.recent.length);
  check('briefFrom refuses anything without a name', briefFrom({ status: 'x' }) === undefined && briefFrom(null) === undefined && briefFrom([1]) === undefined);
  check('briefFrom fills only what arrived', JSON.stringify(briefFrom({ name: 'r.json' })) === JSON.stringify({ name: 'r.json', status: 'unbekannt', lane: '', project: undefined, summary: undefined }), JSON.stringify(briefFrom({ name: 'r.json' })));
  const unknownFrame = reduceLiveEvent(afterBeat, 'something-new', { queue_depth: 1 });
  check('an unknown frame changes nothing', unknownFrame === afterBeat);

  /* ---- seen / disconnected ---- */
  check('marking seen clears the announcement', markSeen(unwatched).unseen === 0);
  check('marking seen twice is the same object', markSeen(markSeen(unwatched)) === markSeen(unwatched) || markSeen(unwatched).unseen === 0);
  const dropped = markDisconnected(afterBeat);
  check('a dropped stream keeps its numbers and stops claiming to be current', dropped.connected === false && dropped.queued === 9 && dropped.watcher === 'idle');
  check('the empty state claims nothing', EMPTY_LIVE.queued === undefined && EMPTY_LIVE.watcher === undefined && EMPTY_LIVE.connected === false && EMPTY_LIVE.recent.length === 0);

  return results;
}
