export type DispatchDescriptionSource = 'bound' | 'action' | 'turn' | 'none';

export interface DispatchPulseItem {
  ref: string;
  kind: string;
  startedAt?: string;
  description?: string;
  descriptionSource: DispatchDescriptionSource;
  lane?: string;
  /** Optional execution attribution copied only from durable bound evidence. */
  workItemId?: string;
  attemptId?: string;
  agent?: string;
  tool?: string;
  runtimeId?: string;
  phase?: string;
}

export interface DispatchPulseProjection {
  /** Exact number of project-compatible open dispatches in the conversation view. */
  total: number;
  /** Project-bound dispatch rows whose versioned identity cannot be interpreted safely. */
  unresolved: number;
  /** Bounded newest-first projection for the compact JARVIS rail. */
  items: DispatchPulseItem[];
}

const DISPLAY_LIMIT = 3;
const DISPATCH_IDENTITY_SCHEMA = 'conversation.dispatch.identity.v1';
const DISPATCH_IDENTITY_PREFIX = 'conversation.dispatch.identity.';

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
 * - a versioned identity snapshot bound to the dispatch is preferred because
 *   it survives the bounded conversation-turn window;
 * - recognized identity snapshots must name this exact project and carry a
 *   non-empty objective, otherwise they are rejected rather than guessed;
 * - an unsupported identity schema is also rejected instead of falling back to
 *   an older turn whose attribution may no longer describe the bound dispatch;
 * - project-bound rejected identity snapshots increment `unresolved`, so a
 *   schema drift cannot masquerade as "no open work" in the cockpit;
 * - foreign or unattributed rejected snapshots never increment that counter,
 *   preserving the same fail-closed cross-project boundary as the item list;
 * - execution attribution (agent/tool/runtime/phase/WorkItem/Attempt) is copied
 *   only from the bound snapshot; legacy chat turns never manufacture it;
 * - legacy dispatches with no identity schema may still derive lane/objective
 *   from their causal turn, with the existing cross-project checks preserved;
 * - `descriptionSource` keeps bound evidence distinct from that legacy
 *   reconstruction so the UI cannot present both with equal confidence;
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
  let unresolved = 0;
  open.forEach((raw, order) => {
    const row = object(raw);
    const link = object(row.link);
    const latest = object(row.latest);
    if (text(latest.lifecycle) !== 'dispatched') return;

    const ref = text(link.dispatch_ref);
    if (!ref) return;

    const detail = object(latest.detail);
    const identitySchema = text(detail.schema);
    if (identitySchema?.startsWith(DISPATCH_IDENTITY_PREFIX)) {
      const identityProject = text(detail.project);
      if (identityProject !== project) return;

      if (identitySchema !== DISPATCH_IDENTITY_SCHEMA) {
        unresolved += 1;
        return;
      }

      const objective = text(detail.objective);
      if (!objective) {
        unresolved += 1;
        return;
      }

      accepted.push({
        ref,
        kind: text(link.kind) || 'dispatch',
        startedAt: text(link.created_ts),
        description: objective,
        descriptionSource: 'bound',
        lane: text(detail.lane),
        workItemId: text(detail.work_item_id),
        attemptId: text(detail.attempt_id),
        agent: text(detail.agent),
        tool: text(detail.tool),
        runtimeId: text(detail.runtime_id),
        phase: text(detail.phase),
        order
      });
      return;
    }

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
    unresolved,
    items: accepted.slice(0, DISPLAY_LIMIT).map(({ order: _order, ...item }) => item)
  };
}
