export type DispatchDescriptionSource = 'action' | 'turn' | 'none';

export interface DispatchPulseItem {
  ref: string;
  kind: string;
  startedAt?: string;
  description?: string;
  descriptionSource: DispatchDescriptionSource;
  lane?: string;
}

export interface DispatchPulseProjection {
  /** Exact number of project-compatible open dispatches in the conversation view. */
  total: number;
  /** Bounded newest-first projection for the compact JARVIS rail. */
  items: DispatchPulseItem[];
}

const DISPLAY_LIMIT = 3;

function object(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function text(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}

function integer(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : undefined;
}

interface AcceptedDispatch extends DispatchPulseItem {
  order: number;
}

/**
 * Project the canonical conversation spine's `open_dispatches` into the small
 * "what has not reported back yet" view used by the cockpit.
 *
 * This function owns no workflow state. It accepts a read-only conversation
 * projection and refuses to manufacture facts that are not in it:
 *
 * - lifecycle must still be exactly `dispatched`;
 * - a dispatch linked to a turn from another project is rejected;
 * - a queue action explicitly targeting another project is rejected;
 * - lane/objective are shown only when the recorded proposed action carries
 *   them; otherwise the causal turn text is labelled as such by the caller;
 * - malformed rows disappear instead of becoming plausible-looking work.
 */
export function dispatchPulseFromConversation(value: unknown, project: string): DispatchPulseProjection {
  const root = object(value);
  const turns = Array.isArray(root.turns) ? root.turns : [];
  const open = Array.isArray(root.open_dispatches) ? root.open_dispatches : [];

  const turnsById = new Map<number, Record<string, unknown>>();
  for (const raw of turns) {
    const turn = object(raw);
    const id = integer(turn.id);
    if (id !== undefined) turnsById.set(id, turn);
  }

  const accepted: AcceptedDispatch[] = [];
  open.forEach((raw, order) => {
    const row = object(raw);
    const link = object(row.link);
    const latest = object(row.latest);
    if (text(latest.lifecycle) !== 'dispatched') return;

    const ref = text(link.dispatch_ref);
    if (!ref) return;

    const turnId = integer(link.turn_id);
    const turn = turnId === undefined ? undefined : turnsById.get(turnId);
    const turnProject = turn ? text(turn.project) : undefined;
    if (turnProject && turnProject !== project) return;

    const action = turn ? object(turn.proposed_action) : {};
    const actionKind = text(action.kind);
    const args = actionKind === 'queue_task' ? object(action.args) : {};
    const actionProject = text(args.project);
    if (actionProject && actionProject !== project) return;

    const objective = text(args.objective);
    const turnMessage = turn ? text(turn.user_message) : undefined;
    const description = objective || turnMessage;
    const descriptionSource: DispatchDescriptionSource = objective ? 'action' : turnMessage ? 'turn' : 'none';

    accepted.push({
      ref,
      kind: text(link.kind) || 'dispatch',
      startedAt: text(link.created_ts),
      description,
      descriptionSource,
      lane: text(args.lane),
      order
    });
  });

  accepted.sort((a, b) => {
    const aTime = a.startedAt ? Date.parse(a.startedAt) : Number.NaN;
    const bTime = b.startedAt ? Date.parse(b.startedAt) : Number.NaN;
    if (Number.isFinite(aTime) && Number.isFinite(bTime) && aTime !== bTime) return bTime - aTime;
    return b.order - a.order;
  });

  return {
    total: accepted.length,
    items: accepted.slice(0, DISPLAY_LIMIT).map(({ order: _order, ...item }) => item)
  };
}
