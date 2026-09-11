import type { GenesisRun } from '@/shared/api';
import { isGenesisRun } from './model';

export interface GenesisSourceDownload {
  url: string;
  candidateSha256: string;
  filename: string;
}

/** The download is a projection of the same complete terminal identity as the
 * result view. Backend-provided URLs and filenames never control navigation. */
export function genesisSourceDownload(run: GenesisRun): GenesisSourceDownload | undefined {
  if (!isGenesisRun(run) || !['preview-ready', 'succeeded'].includes(run.status)) return undefined;
  const candidateSha256 = (run.candidate as { sha256: string }).sha256;
  return {
    url: `/api/genesis/${run.run_id}/source.zip?candidate_sha256=${candidateSha256}`,
    candidateSha256,
    filename: `${run.run_id}-${candidateSha256.slice(0, 12)}-source.zip`
  };
}

export async function fetchGenesisSourceArchive(run: GenesisRun, signal?: AbortSignal): Promise<{
  blob: Blob;
  filename: string;
}> {
  const download = genesisSourceDownload(run);
  if (!download) throw new Error('Für diesen Lauf liegt kein vollständig bestätigter Quellkandidat vor.');

  const response = await fetch(download.url, {
    method: 'GET',
    mode: 'same-origin',
    credentials: 'same-origin',
    redirect: 'error',
    cache: 'no-store',
    headers: { Accept: 'application/zip' },
    signal
  });
  if (response.status !== 200) {
    throw new Error(`Quellcode konnte nicht heruntergeladen werden (HTTP ${response.status}). Bitte erneut versuchen.`);
  }
  if (response.headers.get('X-Daedalus-Candidate-Sha256') !== download.candidateSha256) {
    throw new Error('Der Download bestätigt einen anderen oder keinen Kandidaten. Es wurde keine Datei gespeichert.');
  }
  if (response.headers.get('Content-Type')?.split(';', 1)[0].trim().toLowerCase() !== 'application/zip'
    || !/^attachment(?:\s*;|\s*$)/i.test(response.headers.get('Content-Disposition') || '')) {
    throw new Error('Das Backend hat kein ZIP-Quellarchiv als Download geliefert.');
  }
  const blob = await response.blob();
  if (!blob.size) throw new Error('Das gelieferte Quellarchiv ist leer. Bitte erneut versuchen.');
  return { blob, filename: download.filename };
}

/** Keep the URL alive long enough for the browser to begin its download, then
 * release it even when clicking the temporary anchor throws. */
export function saveGenesisSourceArchive(blob: Blob, filename: string): void {
  const anchor = document.createElement('a');
  const url = URL.createObjectURL(blob);
  try {
    anchor.href = url;
    anchor.download = filename;
    anchor.hidden = true;
    document.body.append(anchor);
    anchor.click();
  } finally {
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1_000);
  }
}
