import { expect, test } from '@playwright/test';
import { watcherGuidance } from '../src/cockpit/WorkPulse';

test.describe('watcher action guidance', () => {
  test('only turns an explicitly stopped watcher into a start command', () => {
    expect(watcherGuidance('none', 'project_tct', true)).toEqual({
      message: 'Aktion empfohlen: Bridge-Wächter starten',
      command: 'python -m daedalus.file_bridge watch --project project_tct'
    });
    expect(watcherGuidance('stopped', 'project_tct', true)).toEqual({
      message: 'Aktion empfohlen: Bridge-Wächter starten',
      command: 'python -m daedalus.file_bridge watch --project project_tct'
    });
  });

  test('never turns an unsafe project label into executable-looking shell guidance', () => {
    const unsafe = watcherGuidance('none', 'project_tct; rm -rf .', true);
    expect(unsafe).toEqual({
      message: 'Aktion empfohlen: Bridge-Wächter starten'
    });
    expect(unsafe?.command).toBeUndefined();

    expect(watcherGuidance('stopped', '-other-option', true)?.command).toBeUndefined();
    expect(watcherGuidance('none', 'project with spaces', true)?.command).toBeUndefined();
  });

  test('never starts a second watcher from stale heartbeat evidence alone', () => {
    expect(watcherGuidance('stale', 'project_tct', true)).toEqual({
      message: 'Aktion empfohlen: Wächterprozess prüfen; erst nach bestätigtem Stillstand neu starten'
    });
    expect(watcherGuidance('stale', 'project_tct', true)?.command).toBeUndefined();
  });

  test('never recommends blind redispatch for a wedged watcher', () => {
    expect(watcherGuidance('wedged', 'project_tct', true)).toEqual({
      message: 'Aktion empfohlen: laufenden Auftrag und Provider prüfen; nicht erneut dispatchen'
    });
  });

  test('does not create operational advice from disconnected or healthy evidence', () => {
    expect(watcherGuidance('stale', 'project_tct', false)).toBeUndefined();
    expect(watcherGuidance('none', 'project_tct', false)).toBeUndefined();
    expect(watcherGuidance('busy', 'project_tct', true)).toBeUndefined();
    expect(watcherGuidance('alive', 'project_tct', true)).toBeUndefined();
  });
});