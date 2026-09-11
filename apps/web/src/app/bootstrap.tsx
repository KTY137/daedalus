import React from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { SurfaceRoot } from './SurfaceRoot';

/** The sole browser root and application-provider composition authority. */
export function bootstrapApp(container: HTMLElement, search: string): Root {
  const root = createRoot(container);
  root.render(
    <React.StrictMode>
      <SurfaceRoot search={search} />
    </React.StrictMode>
  );
  return root;
}
