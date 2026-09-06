import { useCallback, useEffect, useMemo, useState } from 'react';
import { ApiError, getDesktopStatus } from '@/shared/api';
import type { DesktopIdeService, DesktopStatusPayload, ProjectRow } from '@/shared/contracts';

function serviceFrom(payload: DesktopStatusPayload): DesktopIdeService | undefined {
  return payload.desktop?.services?.ide as DesktopIdeService | undefined || payload.service;
}

function useMobileViewport(): boolean {
  const [mobile, setMobile] = useState(false);

  useEffect(() => {
    const query = window.matchMedia('(max-width: 640px)');
    const update = () => setMobile(query.matches);
    update();
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);

  return mobile;
}

/** OpenVSCode is a local desktop surface. Refuse to embed an endpoint which a
 * malformed/stale status response points at somewhere else. */
export function ideUrlFor(endpoint: string | undefined, repoRoot: string): string | undefined {
  if (!endpoint || !repoRoot) return undefined;
  try {
    const url = new URL(endpoint);
    const numericLoopback = url.hostname === '127.0.0.1' || url.hostname === '[::1]';
    const cleanOrigin = !url.username && !url.password && Boolean(url.port)
      && url.pathname === '/' && !url.search && !url.hash;
    if (!numericLoopback || url.protocol !== 'http:' || !cleanOrigin) return undefined;
    url.searchParams.set('folder', repoRoot);
    return url.toString();
  } catch {
    return undefined;
  }
}

/** Prefer the desktop service's measured workspace URL. Docker deliberately
 * exposes the selected Windows checkout as /home/workspace, whereas the
 * backwards-compatible native mode still opens the host path directly. */
export function ideServiceUrlFor(
  service: DesktopIdeService | undefined,
  repoRoot: string
): string | undefined {
  if (!service || !repoRoot) return undefined;
  const expectedFolder = service.mode === 'docker' ? '/home/workspace' : repoRoot;
  const fallback = ideUrlFor(service.endpoint, expectedFolder);
  if (!service.ui_url) return fallback;
  try {
    const url = new URL(service.ui_url);
    const numericLoopback = url.hostname === '127.0.0.1' || url.hostname === '[::1]';
    const folderValues = url.searchParams.getAll('folder');
    const cleanUrl = numericLoopback && url.protocol === 'http:'
      && !url.username && !url.password && Boolean(url.port)
      && url.pathname === '/' && !url.hash
      && [...url.searchParams.keys()].length === 1
      && folderValues.length === 1 && folderValues[0] === expectedFolder;
    if (!cleanUrl) return fallback;
    if (fallback && new URL(fallback).origin !== url.origin) return fallback;
    return url.toString();
  } catch {
    return fallback;
  }
}

export function IdeWorkspace({ project }: { project?: ProjectRow }) {
  const [service, setService] = useState<DesktopIdeService>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [desktopApi, setDesktopApi] = useState<'loading' | 'available' | 'unavailable' | 'error'>('loading');
  const mobile = useMobileViewport();

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const payload = await getDesktopStatus();
      setService(serviceFrom(payload));
      setDesktopApi('available');
    } catch (reason) {
      setService(undefined);
      if (reason instanceof ApiError && reason.kind === 'notfound') {
        setDesktopApi('unavailable');
        setError('');
      } else {
        setDesktopApi('error');
        setError(reason instanceof Error ? reason.message : 'Der Desktop-Status der IDE konnte nicht gelesen werden.');
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const installed = service?.installed ?? service?.available;
  const reachable = service?.reachable ?? (service?.running === true && Boolean(service?.endpoint));
  const reportedDetail = error || service?.last_error || service?.detail || '';
  const missingInstallation = installed === false || /not on PATH|does not exist|nicht installiert/i.test(reportedDetail);
  const frameUrl = useMemo(
    () => ideServiceUrlFor(service, project?.repo_root || ''),
    [project?.repo_root, service]
  );

  if (!project) {
    return (
      <main className="cockpit-body ide" aria-label="IDE">
        <IdeNotice title="Kein Projekt geöffnet">
          Füge im Projektmenü einen bestehenden Ordner hinzu. Daedalus arbeitet direkt in diesem Checkout und lädt keine Kopie hoch.
        </IdeNotice>
      </main>
    );
  }

  if (reachable && frameUrl) {
    if (mobile) {
      return (
        <main className="cockpit-body ide" aria-label={`IDE für ${project.name}`}>
          <IdeNotice title="IDE auf einem Desktop fortsetzen">
            <p>Der integrierte Editor braucht mehr Platz als diese Ansicht bietet. Öffne das bereits ausgewählte Projekt auf einem Desktop.</p>
            <a className="ide-handoff-link" href={frameUrl} target="_blank" rel="noreferrer">Auf Desktop öffnen</a>
          </IdeNotice>
        </main>
      );
    }
    return (
      <main className="cockpit-body ide" aria-label={`IDE für ${project.name}`}>
        <div className="ide-toolbar">
          <span title={project.repo_root}>{project.name}</span>
          <a href={frameUrl} target="_blank" rel="noreferrer">Extern öffnen</a>
        </div>
        <iframe className="ide-frame" src={frameUrl} title={`OpenVSCode – ${project.name}`} allow="clipboard-read; clipboard-write" />
      </main>
    );
  }

  const endpointInvalid = desktopApi === 'available' && reachable && Boolean(service?.endpoint) && !frameUrl;
  const managedStartUnavailable = service?.managed_start_available === false;
  const title = loading
    ? 'IDE-Status wird geprüft'
    : desktopApi === 'unavailable' || (desktopApi === 'available' && !service)
      ? 'IDE-Integration nicht verfügbar'
      : endpointInvalid
        ? 'Der gemeldete IDE-Endpunkt ist nicht lokal'
      : managedStartUnavailable
        ? 'IDE-Start nicht verfügbar'
        : missingInstallation
          ? 'OpenVSCode Server ist nicht installiert'
          : 'OpenVSCode Server ist nicht erreichbar';
  const detail = loading
    ? 'Der Desktop-Dienst wird abgefragt.'
    : desktopApi === 'unavailable' || (desktopApi === 'available' && !service)
      ? 'Dieses Backend stellt keinen gemessenen Desktop-IDE-Status bereit. Ein extern gestarteter Editor kann erst mit einem kompatiblen Loopback-Status geöffnet werden.'
    : endpointInvalid
      ? 'Aus Sicherheitsgründen bettet Daedalus nur saubere numerische Loopback-Endpunkte ein.'
    : managedStartUnavailable
      ? 'Daedalus startet in v0.1.6 keinen IDE-Prozess. Ein bereits laufender, gemessener Loopback-Endpunkt bleibt sichtbar und kann extern geöffnet werden.'
    : reportedDetail
      || (missingInstallation
        ? 'Der Desktop-Status meldet auf diesem Rechner keine vorhandene OpenVSCode-Installation.'
        : service?.configured_executable === '' && service?.runtime_downloads === false
          ? 'Es ist keine ausführbare Datei konfiguriert. Ein extern gestarteter, erreichbarer Loopback-Dienst kann hier angezeigt werden; automatische Downloads sind deaktiviert.'
          : 'Der Dienst hat noch keinen erreichbaren Loopback-Endpunkt gemeldet.');

  return (
    <main className="cockpit-body ide" aria-label={`IDE für ${project.name}`}>
      <IdeNotice title={title} live>
        <p>{detail}</p>
        <p className="ide-project-path"><span>Ordner</span><code>{project.repo_root}</code></p>
        {!loading && desktopApi === 'available' && (
          <div className="ide-actions">
            <button type="button" className="quiet" onClick={() => void refresh()} disabled={loading}>
              Status neu prüfen
            </button>
          </div>
        )}
      </IdeNotice>
    </main>
  );
}

function IdeNotice({ title, children, live = false }: { title: string; children: React.ReactNode; live?: boolean }) {
  return (
    <section className="ide-notice" aria-live={live ? 'polite' : undefined}>
      <span className="ide-mark" aria-hidden="true">&lt;/&gt;</span>
      <h2>{title}</h2>
      <div className="ide-notice-copy">{children}</div>
    </section>
  );
}
