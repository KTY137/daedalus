import { useCallback, useEffect, useState } from 'react';
import { applyDraft, dismissDraft, getDraft, getDrafts, type DraftDetail, type DraftRow } from '../api';

/**
 * The one thing waiting for a person.
 *
 * This card exists only when a draft is actually pending. There is no
 * placeholder decision, no demo attempt, and no disabled Annehmen button
 * standing in for one — five review rounds died on affordances that were
 * pictures of affordances. When nothing is pending the card says so in one
 * line and offers nothing to press.
 *
 * "Warum" is not a tooltip. It fetches the draft's own report — what it
 * changed, what it ran, what it flagged as a risk — because "accept" without a
 * readable proposal is just a button that writes to your repository.
 */

export interface DecisionProps {
  /** bumped by the caller when something happened that may have created a draft */
  signal?: number;
  onChanged?: () => void;
  /** how many drafts are pending, so the navigation can say so */
  onCount?: (n: number) => void;
}

export function Decision({ signal = 0, onChanged, onCount }: DecisionProps) {
  const [pending, setPending] = useState<DraftRow[]>([]);
  const [detail, setDetail] = useState<DraftDetail | undefined>();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    try {
      const payload = await getDrafts();
      const rows = (payload.drafts || []).filter((d) => d.status === 'pending');
      setPending(rows);
      onCount?.(rows.length);
      setError('');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Entwürfe konnten nicht gelesen werden.');
    } finally {
      setLoaded(true);
    }
  }, [onCount]);

  useEffect(() => {
    void load();
  }, [load, signal]);

  const current = pending[0];

  useEffect(() => {
    setOpen(false);
    setDetail(undefined);
  }, [current?.id]);

  const why = useCallback(async () => {
    if (!current) return;
    setOpen((v) => !v);
    if (detail || !current.id) return;
    try {
      const payload = await getDraft(current.id);
      setDetail(payload.draft);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Der Entwurf konnte nicht gelesen werden.');
    }
  }, [current, detail]);

  const act = useCallback(
    async (kind: 'apply' | 'dismiss') => {
      if (!current) return;
      setBusy(kind);
      setError('');
      try {
        if (kind === 'apply') await applyDraft(current.id);
        else await dismissDraft(current.id);
        await load();
        onChanged?.();
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Die Aktion ist fehlgeschlagen.');
      } finally {
        setBusy('');
      }
    },
    [current, load, onChanged]
  );

  /**
   * "Still reading" is not "nothing pending".
   *
   * This returned null until the first fetch landed, and on this machine that
   * fetch takes 12.5s [MEASURED 2026-08-25 — /api/drafts lists all 428 drafts
   * and has no limit]. For twelve seconds the page therefore showed an empty
   * space where a decision would be, which reads as "nothing waits for you" —
   * the exact collapse of "could not look" into "nothing to see" that this
   * repository treats as a defect everywhere else.
   */
  if (!loaded) {
    return (
      <div className="decision quiet" aria-busy="true">
        <span className="decision-eyebrow">Entscheidung</span>
        <p className="decision-none">Entwürfe werden gelesen …</p>
      </div>
    );
  }

  if (!current) {
    return (
      <div className="decision quiet">
        <span className="decision-eyebrow">Entscheidung</span>
        <p className="decision-none">
          {error ? error : 'Nichts wartet auf dich. Entwürfe erscheinen hier, sobald ein Lauf einen erzeugt hat.'}
        </p>
      </div>
    );
  }

  return (
    <div className="decision" role="region" aria-label="Offene Entscheidung">
      <span className="decision-eyebrow">
        Entscheidung{pending.length > 1 ? ` · ${pending.length} offen` : ''}
      </span>
      <h2 className="decision-title">{current.objective || current.id}</h2>
      <p className="decision-sub">
        Von <b>{current.agent || 'unbekannt'}</b>
        {current.paths?.length ? ` · ${current.paths.length} Pfad(e)` : ''} · angelegt {current.created}. Annehmen
        schreibt in dein Repository; Ablehnen legt den Entwurf zur Seite.
      </p>

      <div className="decision-acts">
        <button type="button" className="primary" onClick={() => void act('apply')} disabled={busy !== ''}>
          {busy === 'apply' ? 'Wird angewandt …' : 'Annehmen'}
        </button>
        <button type="button" onClick={() => void act('dismiss')} disabled={busy !== ''}>
          {busy === 'dismiss' ? 'Wird abgelegt …' : 'Ablehnen'}
        </button>
        <button type="button" className="quiet" onClick={() => void why()} aria-expanded={open}>
          Warum
        </button>
      </div>

      {error && <p className="decision-error" role="alert">{error}</p>}

      {open && (
        <div className="decision-why">
          {!detail && <p className="muted">Wird gelesen …</p>}
          {detail && (
            <>
              <p className="decision-summary">{detail.report?.summary || 'Kein Bericht hinterlegt.'}</p>
              {detail.report?.files_changed?.length > 0 && (
                <div className="decision-list">
                  <span>Geändert</span>
                  <ul>
                    {detail.report.files_changed.slice(0, 8).map((f) => (
                      <li key={f}><code>{f}</code></li>
                    ))}
                  </ul>
                  {detail.report.files_changed.length > 8 && (
                    <p className="muted">und {detail.report.files_changed.length - 8} weitere.</p>
                  )}
                </div>
              )}
              {detail.report?.risks?.length > 0 && (
                <div className="decision-list risk">
                  <span>Risiken</span>
                  <ul>
                    {detail.report.risks.map((r) => (
                      <li key={r}>{r}</li>
                    ))}
                  </ul>
                </div>
              )}
              <p className="muted">
                Tests gelaufen: {detail.report?.tests_run?.length ? detail.report.tests_run.join(', ') : 'keine gemeldet'} ·
                Zustand: {detail.report?.status || 'unbekannt'} · Provider: {detail.provider || 'unbekannt'}
              </p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
