// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-License-Identifier: Apache-2.0

import React, { Suspense } from 'react';
import { createRoot } from 'react-dom/client';
import { Cockpit } from './cockpit/Cockpit';
import { ThemeProvider } from './theme/ThemeProvider';

/**
 * Two surfaces, one build.
 *
 * The cockpit is what opens. The previous surface — the dock, the three
 * spaces, Mission Control — is still here at `?surface=classic`, because it
 * carries wiring the cockpit has not absorbed yet (runtimes, the control
 * plane, the inbox tray) and because its acceptance suite is still the thing
 * pinning those contracts. Deleting it before the cockpit reaches it would
 * trade a working surface for a screenshot.
 *
 * The classic surface is loaded LAZILY, and that is load-bearing rather than a
 * bundle-size nicety. It imports `styles.css`, whose element selectors date
 * from the dock era — `nav { flex-direction: column }`, `.composer {
 * flex-direction: column }` — and a static import would apply them to the
 * cockpit's own chrome even while the classic surface never rendered. A
 * stylesheet one surface wants must load when that surface does.
 */
const surface = new URLSearchParams(location.search).get('surface');
const classic = surface === 'classic' || surface === 'legacy';

const Classic = React.lazy(() => import('./App'));

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    {classic ? (
      <Suspense fallback={null}>
        <Classic />
      </Suspense>
    ) : (
      <ThemeProvider>
        <Cockpit />
      </ThemeProvider>
    )}
  </React.StrictMode>
);
