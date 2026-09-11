import { expect, type Page } from '@playwright/test';

/** Controlled read contracts keep these browser tests independent of host work. */
export async function stubLiveProject(page: Page, project = 'atlas') {
  await page.route('**/api/**', (route) => route.fulfill({ status: 404, json: { ok: false, error: 'fixture: unavailable read' } }));
  await page.route('**/api/projects', (route) => route.fulfill({ json: {
    ok: true, projects: [{ name: project, repo_root: `/fixtures/${project}`, team: {}, reachable: true }]
  } }));
  await page.route('**/api/structure**', (route) => route.fulfill({ json: {
    ok: true, project, structure: { repo_root: `/fixtures/${project}`, n_files: 0, graph: { nodes: [], edges: [] } }
  } }));
  await page.route('**/api/drafts**', (route) => route.fulfill({ json: { ok: true, drafts: [], scope: project } }));
  await page.route('**/api/runtimes/status**', (route) => route.fulfill({ json: { ok: true, runtimes: [] } }));
  await page.route('**/api/conversations?**', (route) => route.fulfill({ json: { ok: true, conversations: [] } }));
}

export async function openLiveWork(page: Page) {
  await page.goto('/?view=chat', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.cockpit')).toBeVisible();
  await page.getByRole('button', { name: /^Arbeit/ }).click();
  await expect(page.locator('.work')).toBeVisible();
}

export async function controlledConversation(page: Page) {
  await page.addInitScript(() => {
    const sources: ControlledSource[] = [];
    class ControlledSource {
      url: string;
      closed = false;
      onerror: ((event: Event) => void) | null = null;
      listeners = new Map<string, EventListenerOrEventListenerObject[]>();
      constructor(url: string | URL) { this.url = String(url); sources.push(this); }
      addEventListener(name: string, listener: EventListenerOrEventListenerObject) {
        this.listeners.set(name, [...(this.listeners.get(name) || []), listener]);
      }
      removeEventListener() {}
      close() { this.closed = true; }
      emit(name: string, value: unknown) {
        const event = new MessageEvent(name, { data: JSON.stringify(value) });
        for (const listener of this.listeners.get(name) || []) {
          if (typeof listener === 'function') listener(event); else listener.handleEvent(event);
        }
      }
    }
    Object.defineProperty(window, 'EventSource', { configurable: true, value: ControlledSource });
    Object.assign(window, {
      __conversationSources: sources,
      __emitConversation: (id: number, name: string, value: unknown) => {
        const source = sources.find((item) => item.url.endsWith(`/turns/${id}/events`));
        if (!source) throw new Error('request observer has not opened');
        source.emit(name, value);
      }
    });
  });
}

export async function emitConversation(page: Page, name: string, value: unknown, id = 51) {
  await page.evaluate(({ id, name, value }) => {
    (window as unknown as { __emitConversation: (id: number, name: string, value: unknown) => void }).__emitConversation(id, name, value);
  }, { id, name, value });
}
