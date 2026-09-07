import { expect, test } from '@playwright/test';
import { dispatchPulseFromConversation } from '../src/cockpit/dispatchPulse';
import { dispatchEvidenceLabel } from '../src/cockpit/WorkPulse';

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
          args: { project: PROJECT, objective: 'Legacy-Auftrag', lane: 'local_only' }
        }
      }
    ],
    open_dispatches: [
      dispatch('bound-ref', 7, {
        schema: 'conversation.dispatch.identity.v1',
        project: PROJECT,
        objective: 'Parser härten',
        lane: 'claude'
      }),
      dispatch('legacy-ref', 42)
    ]
  };

  const pulse = dispatchPulseFromConversation(conversation, PROJECT);
  expect(pulse.total).toBe(2);

  const bound = pulse.items.find((item) => item.ref === 'bound-ref');
  const legacy = pulse.items.find((item) => item.ref === 'legacy-ref');
  expect(bound).toMatchObject({
    description: 'Parser härten',
    descriptionSource: 'bound',
    lane: 'claude'
  });
  expect(legacy).toMatchObject({
    description: 'Legacy-Auftrag',
    descriptionSource: 'action',
    lane: 'local_only'
  });

  expect(dispatchEvidenceLabel(bound!.descriptionSource)).toBe('gebundene Evidenz');
  expect(dispatchEvidenceLabel(legacy!.descriptionSource)).toBe('aus Chatverlauf rekonstruiert');
});

test('missing identity stays visibly unbound instead of inheriting confidence', () => {
  const conversation = {
    turns: [],
    open_dispatches: [dispatch('unknown-ref', 99)]
  };

  const pulse = dispatchPulseFromConversation(conversation, PROJECT);
  expect(pulse.total).toBe(1);
  expect(pulse.items[0]).toMatchObject({
    ref: 'unknown-ref',
    descriptionSource: 'none'
  });
  expect(dispatchEvidenceLabel(pulse.items[0].descriptionSource)).toBe('Identität nicht gebunden');
});