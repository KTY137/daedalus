/** The server's 200 response when no frontend bundle exists. */
export const NOT_BUILT = /Run npm install/i;

export interface Signals {
  pageErrors: string[];
  consoleErrors: string[];
  api: { path: string; status: number }[];
}

/** Attach before navigation so an evaluation-time white screen cannot hide. */
export function collect(page: import('@playwright/test').Page): Signals {
  const signals: Signals = { pageErrors: [], consoleErrors: [], api: [] };
  page.on('pageerror', (error) => signals.pageErrors.push(String(error?.message || error)));
  page.on('console', (message) => {
    if (message.type() === 'error') signals.consoleErrors.push(message.text());
  });
  page.on('response', (response) => {
    try {
      const url = new URL(response.url());
      if (url.pathname.startsWith('/api/')) signals.api.push({ path: url.pathname, status: response.status() });
    } catch {
      /* opaque URL */
    }
  });
  return signals;
}
