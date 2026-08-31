import { ThemeProvider } from '@/shared/ui/theme/ThemeProvider';
import { Cockpit } from './Cockpit';
import { resolveSurface } from './surface';

export function SurfaceRoot({ search }: { search: string }) {
  const surface = resolveSurface(search);

  return (
    <ThemeProvider key={surface}>
      <Cockpit />
    </ThemeProvider>
  );
}
