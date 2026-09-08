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
const DISPATCH_IDENTITY_FIELDS = [
  'project', 'objective', 'lane', 'work_item_id', 'attempt_id',
  'agent', 'tool', 'runtime_id', 'phase'
] as const;

function object(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function text(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}

/**
 * Bound identity fields are evidence, not free-form UI text. Accept them only
 * when the recorded bytes are already canonical. Trimming a project/lane/id at
 * read time would silently display a different identity than the producer
 * actually froze on the dispatch fact.
 */
function boundText(value: unknown): string | undefined {
  if (typeof value !== 'string' || !value) return undefined;
  return value === value.trim() ? value : undefined;
}

function integer(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : undefined;
}

function hasOwn(value: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(value, key);
}

function claimsDispatchIdentity(detail: Record<string, unknown>): boolean {
  const schema = typeof detail.schema === 'string' ? detail.schema.trim() : undefined;
  return Boolean(schema?.startsWith(DISPATCH_IDENTITY_PREFIX))
    || DISPATCH_IDENTITY_FIELDS.some((field) => hasOwn(detail, field));
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
 * - identity-shaped detail without a valid schema is unresolved too: it must
 *   never fall through to a causal chat turn and inherit legacy confidence;
 * - recognized identity snapshots must name this exact project and carry a
 *   non-empty objective AND lane, already in canonical byte form, otherwise
 *   they are rejected rather than normalized into plausible bound evidence;
 * - an unsupported or non-canonical identity schema is also rejected instead
 *   of falling back to an older turn whose attribution may no longer describe
 *   the bound dispatch;
 * - project-bound rejected identity snapshots increment `unresolved`, so a
 *   schema drift cannot masquerade as "no open work" in the cockpit;
 * - foreign or unattributed rejected snapshots never increment that counter,
 *   preserving the same fail-closed cross-project boundary as the item list;
 * - execution attribution (agent/tool/runtime/phase/WorkItem/Attempt) is copied
 *   only from canonical bound fields; legacy chat turns never manufacture it;
 * - legacy dispatches with no identity-shaped detail may still derive
 *   lane/objective from their causal turn, with the existing cross-project
 *   checks preserved;
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
    if (claimsDispatchIdentity(detail)) {
      const identityProject = boundText(detail.project);
      if (identityProject !== project) return;

      const rawIdentitySchema = typeof detail.schema === 'string' ? detail.schema : undefined;
      if (rawIdentitySchema !== DISPATCH_IDENTITY_SCHEMA) {
        unresolved += 1;
        return;
      }

      const objective = boundText(detail.objective);
      const lane = boundText(detail.lane);
      if (!objective || !lane) {
        unresolved += 1;
        return;
      }

      accepted.push({
        ref,
        kind: text(link.kind) || 'dispatch',
        startedAt: text(link.created_ts),
        description: objective,
        descriptionSource: 'bound',
        lane,
        workItemId: boundText(detail.work_item_id),
        attemptId: boundText(detail.attempt_id),
        agent: boundText(detail.agent),
        tool: boundText(detail.tool),
        runtimeId: boundText(detail.runtime_id),
        phase: boundText(detail.phase),
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
