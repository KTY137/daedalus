import { useCallback, useEffect, useMemo, useState } from 'react';
import { getDesktopStatus, startDesktopIde } from '../api';
import type { DesktopIdeService, DesktopStatusPayload, ProjectRow } from '../types';

function serviceFrom(payload: DesktopStatusPayload): DesktopIdeService | undefined {
  return payload.desktop?.services?.ide as DesktopIdeService | undefined || payload.service;
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
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const payload = await getDesktopStatus();
      setService(serviceFrom(payload));
    } catch (reason) {
      setService(undefined);
      setError(reason instanceof Error ? reason.message : 'Der Desktop-Status der IDE konnte nicht gelesen werden.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const start = useCallback(async () => {
    setStarting(true);
    setError('');
    try {
      const started = await startDesktopIde(project?.repo_root || '');
      const immediate = serviceFrom(started);
      if (immediate) setService(immediate);
      const measured = await getDesktopStatus();
      setService(serviceFrom(measured) || immediate);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'OpenVSCode Server konnte nicht gestartet werden.');
    } finally {
      setStarting(false);
      setLoading(false);
    }
  }, [project?.repo_root]);

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

  const endpointInvalid = reachable && Boolean(service?.endpoint) && !frameUrl;
  const title = loading
    ? 'IDE-Status wird geprüft'
    : missingInstallation
      ? 'OpenVSCode Server ist nicht installiert'
      : endpointInvalid
        ? 'Der gemeldete IDE-Endpunkt ist nicht lokal'
        : 'OpenVSCode Server ist nicht erreichbar';
  const detail = reportedDetail
    || (loading
      ? 'Der Desktop-Dienst wird abgefragt.'
      : missingInstallation
        ? 'Die IDE wurde auf diesem Desktop nicht gefunden. Der Startversuch meldet den genauen Installationsfehler.'
        : endpointInvalid
          ? 'Aus Sicherheitsgründen bettet Daedalus nur saubere numerische Loopback-Endpunkte ein.'
          : service?.configured_executable === '' && service?.runtime_downloads === false
            ? 'Der Dienst ist offline. Es ist keine ausführbare Datei konfiguriert; beim Start wird eine vorhandene openvscode-server-Installation auf PATH geprüft. Automatische Downloads sind deaktiviert.'
            : 'Der Dienst läuft nicht oder hat noch keinen erreichbaren Loopback-Endpunkt gemeldet.');

  return (
    <main className="cockpit-body ide" aria-label={`IDE für ${project.name}`}>
      <IdeNotice title={title} live>
        <p>{detail}</p>
        <p className="ide-project-path"><span>Ordner</span><code>{project.repo_root}</code></p>
        {!loading && (
          <div className="ide-actions">
            <button type="button" onClick={() => void start()} disabled={starting}>
              {starting ? 'IDE startet …' : 'IDE starten'}
            </button>
            <button type="button" className="quiet" onClick={() => void refresh()} disabled={starting}>
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
