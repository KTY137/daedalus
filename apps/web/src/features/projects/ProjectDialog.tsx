import { useEffect, useRef, useState } from 'react';
import { createProject } from '@/shared/api';

function nativeFolderPickerAvailable(): boolean {
  if (typeof window === 'undefined' || typeof navigator === 'undefined') return false;
  if (!('__TAURI_INTERNALS__' in window)) return false;
  // The Tauri capability is intentionally granted only on Windows/macOS.
  // This is UI affordance detection, not an authority boundary; Tauri still
  // enforces the capability when the dialog command is invoked.
  return /^(win|mac)/i.test(navigator.platform || '');
}

export function ProjectDialog({
  open,
  onClose,
  onRegistered
}: {
  open: boolean;
  onClose: () => void;
  onRegistered: (name: string, repoRoot: string) => Promise<void> | void;
}) {
  const [repoRoot, setRepoRoot] = useState('');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [choosing, setChoosing] = useState(false);
  const [error, setError] = useState('');
  const rootInput = useRef<HTMLInputElement>(null);
  const hasNativeFolderPicker = nativeFolderPickerAvailable();

  useEffect(() => {
    if (!open) {
      setError('');
      return;
    }
    window.setTimeout(() => rootInput.current?.focus(), 0);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [busy, onClose, open]);

  if (!open) return null;

  const chooseFolder = async () => {
    setChoosing(true);
    setError('');
    try {
      const { open: openNativeDialog } = await import('@tauri-apps/plugin-dialog');
      const selected = await openNativeDialog({
        directory: true,
        multiple: false,
        title: 'Projektordner öffnen'
      });
      if (typeof selected === 'string') setRepoRoot(selected);
    } catch {
      setError('Der native Ordnerdialog konnte nicht geöffnet werden. Du kannst den Pfad hier weiterhin direkt eintragen.');
      rootInput.current?.focus();
    } finally {
      setChoosing(false);
    }
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const root = repoRoot.trim();
    if (!root) {
      setError('Gib den lokalen Pfad zum Projektordner an.');
      rootInput.current?.focus();
      return;
    }
    setBusy(true);
    setError('');
    try {
      const payload = await createProject({ repo_root: root, ...(name.trim() ? { name: name.trim() } : {}) });
      const registeredName = payload.registered_project?.name || payload.project || name.trim();
      await onRegistered(registeredName, payload.registered_project?.repo_root || root);
      setRepoRoot('');
      setName('');
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Das Projekt konnte nicht hinzugefügt werden.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="project-dialog-scrim" onMouseDown={(event) => event.target === event.currentTarget && !busy && onClose()}>
      <section className="project-dialog" role="dialog" aria-modal="true" aria-labelledby="project-dialog-title">
        <div className="project-dialog-head">
          <div>
            <span>Bestehender Checkout</span>
            <h2 id="project-dialog-title">Projekt hinzufügen</h2>
          </div>
          <button type="button" aria-label="Dialog schließen" onClick={onClose} disabled={busy}>×</button>
        </div>
        <form onSubmit={(event) => void submit(event)}>
          <label>
            <span>Projektordner</span>
            <div className="project-folder-row">
              <input
                ref={rootInput}
                value={repoRoot}
                onChange={(event) => setRepoRoot(event.target.value)}
                placeholder="C:\\Pfad\\zum\\Repository"
                autoComplete="off"
                required
              />
              {hasNativeFolderPicker && (
                <button type="button" className="folder-picker" onClick={() => void chooseFolder()} disabled={busy || choosing}>
                  {choosing ? 'Öffnet …' : 'Durchsuchen …'}
                </button>
              )}
            </div>
          </label>
          <p className="project-dialog-hint">
            {hasNativeFolderPicker
              ? 'Der Ordner bleibt an seinem Platz. Es wird keine Upload-Kopie angelegt.'
              : 'Trag den vollständigen lokalen Pfad direkt ein. Auf dieser Oberfläche steht kein nativer Ordnerdialog zur Verfügung; der Ordner bleibt an seinem Platz.'}
          </p>
          <label>
            <span>Name <small>(optional)</small></span>
            <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Wird sonst aus dem Ordnernamen abgeleitet" autoComplete="off" />
          </label>
          {error && <p className="project-dialog-error" role="alert">{error}</p>}
          <div className="project-dialog-actions">
            <button type="button" className="quiet" onClick={onClose} disabled={busy}>Abbrechen</button>
            <button type="submit" disabled={busy || !repoRoot.trim()}>{busy ? 'Fügt hinzu …' : 'Ordner öffnen'}</button>
          </div>
        </form>
      </section>
    </div>
  );
}
