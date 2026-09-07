import { expect, test } from '@playwright/test';
import { watcherGuidance } from '../src/cockpit/WorkPulse';

test.describe('watcher action guidance', () => {
  test('turns fresh stopped watcher evidence into an exact restart action', () => {
    expect(watcherGuidance('none', 'project_tct', true)).toEqual({
      message: 'Aktion empfohlen: Bridge-Wächter starten',
      command: 'python -m daedalus.file_bridge watch --project project_tct'
    });
    expect(watcherGuidance('stopped', 'project_tct', true)).toEqual({
      message: 'Aktion empfohlen: Bridge-Wächter starten',
      command: 'python -m daedalus.file_bridge watch --project project_tct'
    });
    expect(watcherGuidance('stale', 'project_tct', true)).toEqual({
      message: 'Aktion empfohlen: Bridge-Wächter neu starten',
      command: 'python -m daedalus.file_bridge watch --project project_tct'
    });
  });

  test('never recommends blind redispatch for a wedged watcher', () => {
    expect(watcherGuidance('wedged', 'project_tct', true)).toEqual({
      message: 'Aktion empfohlen: laufenden Auftrag und Provider prüfen; nicht erneut dispatchen'
    });
  });

  test('does not create operational advice from stale or healthy evidence', () => {
    expect(watcherGuidance('stale', 'project_tct', false)).toBeUndefined();
    expect(watcherGuidance('none', 'project_tct', false)).toBeUndefined();
    expect(watcherGuidance('busy', 'project_tct', true)).toBeUndefined();
    expect(watcherGuidance('alive', 'project_tct', true)).toBeUndefined();
  });
});
