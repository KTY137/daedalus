import { Cockpit } from '../cockpit/Cockpit';
import { ThemeProvider } from '../theme/ThemeProvider';
import { resolveSurface } from './surface';

export function SurfaceRoot({ search }: { search: string }) {
  const surface = resolveSurface(search);

  return (
    <ThemeProvider key={surface}>
      <Cockpit />
    </ThemeProvider>
  );
}
