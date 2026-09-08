import { expect, test } from '@playwright/test';
import { projectDispatches } from '../src/features/conversation/dispatch';
import { boundExecutionLine, dispatchEvidenceLabel } from '../src/features/conversation/dispatch';

const PROJECT = 'jarvis-project';

function dispatch(ref: string, turnId: number, detail?: Record<string, unknown>) {
  return {
    link: {
      conversation_id: 'conv_jarvis',
      turn_id: turnId,
      dispatch_ref: ref,
      kind: 'queue_task',
      created_ts: '2026-09-07T12:00:00Z'
    },
    latest: {
      lifecycle: 'dispatched',
      detail
    }
  };
}

test('bound dispatch identity is distinguishable from legacy reconstruction', () => {
  const conversation = {
    turns: [
      {
        id: 42,
        project: PROJECT,
        user_message: 'Legacy-Auftrag ausführen',
        proposed_action: {
          kind: 'queue_task',
          args: {
            project: PROJECT,
            objective: 'Legacy-Auftrag',
            lane: 'local_only',
            agent: 'legacy-agent-must-not-be-promoted',
            runtime_id: 'legacy-runtime-must-not-be-promoted'
          }
        }
      }
    ],
    open_dispatches: [
      dispatch('bound-ref', 7, {
        schema: 'conversation.dispatch.identity.v1',
        project: PROJECT,
        objective: 'Parser härten',
        lane: 'claude',
        work_item_id: 'work-parser-42',
        attempt_id: 'attempt-parser-7',
        agent: 'qa-critic',
        tool: 'read-file',
        runtime_id: 'claude-code',
        phase: 'executing'
      }),
      dispatch('legacy-ref', 42)
    ]
  };

  const pulse = projectDispatches(conversation, PROJECT);
  expect(pulse.total).toBe(2);
  expect(pulse.unresolved).toBe(0);

  const bound = pulse.items.find((item) => item.ref === 'bound-ref');
  const legacy = pulse.items.find((item) => item.ref === 'legacy-ref');
  expect(bound).toMatchObject({
    description: 'Parser härten',
    descriptionSource: 'bound',
    lane: 'claude',
    workItemId: 'work-parser-42',
    attemptId: 'attempt-parser-7',
    agent: 'qa-critic',
    tool: 'read-file',
    runtimeId: 'claude-code',
    phase: 'executing'
  });
  expect(legacy).toMatchObject({
    description: 'Legacy-Auftrag',
    descriptionSource: 'action',
    lane: 'local_only'
  });
  expect(legacy?.agent).toBeUndefined();
  expect(legacy?.runtimeId).toBeUndefined();

  expect(dispatchEvidenceLabel(bound!.descriptionSource)).toBe('gebundene Evidenz');
  expect(dispatchEvidenceLabel(legacy!.descriptionSource)).toBe('aus Chatverlauf rekonstruiert');
  expect(boundExecutionLine(bound!)).toBe(
    'Agent qa-critic · Tool read-file · Runtime claude-code · Phase executing · WorkItem work-parser-42 · Attempt attempt-parser-7'
  );
  expect(boundExecutionLine(legacy!)).toBeUndefined();
});

test('missing identity stays visibly unbound instead of inheriting confidence', () => {
  const conversation = {
    turns: [],
    open_dispatches: [dispatch('unknown-ref', 99)]
  };

  const pulse = projectDispatches(conversation, PROJECT);
  expect(pulse.total).toBe(1);
  expect(pulse.unresolved).toBe(0);
  expect(pulse.items[0]).toMatchObject({
    ref: 'unknown-ref',
    descriptionSource: 'none'
  });
  expect(dispatchEvidenceLabel(pulse.items[0].descriptionSource)).toBe('Identität nicht gebunden');
  expect(boundExecutionLine(pulse.items[0])).toBeUndefined();
});

test('project-bound incompatible, incomplete, or non-canonical identity is unresolved without leaking foreign work', () => {
  const conversation = {
    turns: [],
    open_dispatches: [
      dispatch('future-schema', 1, {
        schema: 'conversation.dispatch.identity.v2',
        project: PROJECT,
        objective: 'Neue Schema-Version',
        lane: 'local_only'
      }),
      dispatch('missing-objective', 2, {
        schema: 'conversation.dispatch.identity.v1',
        project: PROJECT,
        lane: 'local_only'
      }),
      dispatch('missing-lane', 3, {
        schema: 'conversation.dispatch.identity.v1',
        project: PROJECT,
        objective: 'Ohne Lane keine vollständige gebundene Arbeitsidentität'
      }),
      dispatch('schema-with-padding', 4, {
        schema: ' conversation.dispatch.identity.v1 ',
        project: PROJECT,
        objective: 'Schema darf beim Lesen nicht normalisiert werden',
        lane: 'local_only'
      }),
      dispatch('objective-with-padding', 5, {
        schema: 'conversation.dispatch.identity.v1',
        project: PROJECT,
        objective: ' Parser härten ',
        lane: 'local_only'
      }),
      dispatch('lane-with-padding', 6, {
        schema: 'conversation.dispatch.identity.v1',
        project: PROJECT,
        objective: 'Parser härten',
        lane: ' local_only '
      }),
      dispatch('project-with-padding', 7, {
        schema: 'conversation.dispatch.identity.v1',
        project: ` ${PROJECT} `,
        objective: 'Nicht exakt diesem Projekt zurechenbar',
        lane: 'local_only'
      }),
      dispatch('foreign-future-schema', 8, {
        schema: 'conversation.dispatch.identity.v9',
        project: 'other-project',
        objective: 'Darf nicht sichtbar werden',
        lane: 'local_only'
      }),
      dispatch('unattributed-future-schema', 9, {
        schema: 'conversation.dispatch.identity.v9',
        objective: 'Ohne Projekt nicht zurechenbar',
        lane: 'local_only'
      })
    ]
  };

  const pulse = projectDispatches(conversation, PROJECT);
  expect(pulse.total).toBe(0);
  expect(pulse.items).toEqual([]);
  expect(pulse.unresolved).toBe(6);
});

test('optional bound execution attribution is omitted rather than normalized into a different identity', () => {
  const conversation = {
    turns: [],
    open_dispatches: [
      dispatch('bound-with-noncanonical-optional-evidence', 1, {
        schema: 'conversation.dispatch.identity.v1',
        project: PROJECT,
        objective: 'Parser härten',
        lane: 'local_only',
        work_item_id: ' work-parser-42 ',
        attempt_id: 'attempt-parser-7 ',
        agent: ' qa-critic',
        tool: 'read-file ',
        runtime_id: ' claude-code ',
        phase: ' executing'
      })
    ]
  };

  const pulse = projectDispatches(conversation, PROJECT);
  expect(pulse.total).toBe(1);
  expect(pulse.unresolved).toBe(0);
  expect(pulse.items[0]).toMatchObject({
    ref: 'bound-with-noncanonical-optional-evidence',
    description: 'Parser härten',
    descriptionSource: 'bound',
    lane: 'local_only'
  });
  expect(pulse.items[0].workItemId).toBeUndefined();
  expect(pulse.items[0].attemptId).toBeUndefined();
  expect(pulse.items[0].agent).toBeUndefined();
  expect(pulse.items[0].tool).toBeUndefined();
  expect(pulse.items[0].runtimeId).toBeUndefined();
  expect(pulse.items[0].phase).toBeUndefined();
  expect(boundExecutionLine(pulse.items[0])).toBeUndefined();
});

test('identity-shaped detail without a valid schema cannot fall back to causal chat reconstruction', () => {
  const causalTurn = {
    id: 42,
    project: PROJECT,
    user_message: 'Dieser Text darf kaputte Dispatch-Evidenz nicht retten',
    proposed_action: {
      kind: 'queue_task',
      args: {
        project: PROJECT,
        objective: 'Legacy-Fallback darf hier nicht erscheinen',
        lane: 'claude'
      }
    }
  };
  const conversation = {
    turns: [causalTurn],
    open_dispatches: [
      dispatch('missing-schema', 42, {
        project: PROJECT,
        objective: 'Producer hat Identitätsfelder, aber kein Schema geschrieben',
        lane: 'local_only'
      }),
      dispatch('non-string-schema', 42, {
        schema: 1,
        project: PROJECT,
        objective: 'Kaputtes Schema',
        lane: 'local_only'
      }),
      dispatch('foreign-missing-schema', 42, {
        project: 'other-project',
        objective: 'Fremde kaputte Evidenz darf weder sichtbar noch gezählt werden',
        lane: 'local_only'
      })
    ]
  };

  const pulse = projectDispatches(conversation, PROJECT);
  expect(pulse.total).toBe(0);
  expect(pulse.items).toEqual([]);
  expect(pulse.unresolved).toBe(2);
});
