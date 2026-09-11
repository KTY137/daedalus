import { expect, test, type Page } from '@playwright/test';
import { controlledConversation, openLiveWork, stubLiveProject } from './_live-fixtures';

/** Drive the built WorkRail through the existing project EventSource consumer. */
async function report(page: Page, value: Record<string, unknown>) {
  await page.evaluate((row) => {
    type Source = { url: string; closed: boolean; emit(name: string, data: unknown): void };
    const sources = (window as unknown as { __conversationSources: Source[] }).__conversationSources;
    const source = sources.find((s) => !s.closed && s.url.includes('/api/events'));
    if (!source) throw new Error('project event observer is not connected');
    source.emit('report', row);
  }, value);
}

test('work reports require project attribution and retain execution identity', async ({ page }) => {
  await stubLiveProject(page, 'atlas');
  await controlledConversation(page);
  await openLiveWork(page);
  const rail = page.locator('.work');
  await expect.poll(() => page.evaluate(() => {
    type Source = { url: string; closed: boolean };
    const sources = (window as unknown as { __conversationSources?: Source[] }).__conversationSources;
    return sources?.some((s) => !s.closed && s.url.includes('/api/events')) || false;
  })).toBe(true);

  await report(page, { name: 'foreign-report', project: 'other', status: 'done' });
  await report(page, { name: 'unscoped-report', status: 'done' });
  await expect(rail).not.toContainText('foreign-report');
  await expect(rail).not.toContainText('unscoped-report');

  const row = {
    id: 'binding-1', name: 'bound-report', project: 'atlas', status: 'done',
    provider: 'claude_cli', execution_executed: true, replay: false,
    runtime_id: 'claude_code_cli', work_item_id: 'work-1', attempt_id: 'attempt-1',
    phase: 'terminal', terminal_receipt_sha256: 'a'.repeat(64),
  };
  await report(page, row);
  const evidence = rail.getByLabel('Beobachtete Ausführungsevidenz');
  await expect(evidence).toContainText('Runtime claude_code_cli');
  await expect(evidence).toContainText('WorkItem work-1');
  await expect(evidence).toContainText('Attempt attempt-1');
  await expect(evidence).toContainText('keine Inhaltsprüfung');
  await expect(evidence).toContainText('a'.repeat(64));

  // A receipt-only update must not disappear under report-name deduplication.
  await report(page, { ...row, terminal_receipt_sha256: 'b'.repeat(64) });
  await expect(evidence).toContainText('b'.repeat(64));
  await expect(evidence).not.toContainText('a'.repeat(64));
  await expect(rail.locator('.work-section.past .work-list > li')).toHaveCount(1);

  await report(page, { ...row, replay: true, execution_executed: false,
    phase: undefined, terminal_receipt_sha256: undefined });
  await expect(evidence).toContainText('Replay · kein neuer Provider-Lauf');
  await expect(evidence).toContainText('Identitätsfelder: unvollständig');
  await expect(evidence).not.toContainText('Phase terminal');
});
