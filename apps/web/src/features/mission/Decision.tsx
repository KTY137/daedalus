import { useCallback, useEffect, useRef, useState } from 'react';
import { applyDraft, dismissDraft, getDraft, getDrafts, type DraftDetail, type DraftRow } from '@/shared/api';

/**
 * The one thing waiting for a person.
 *
 * The draft store is shared, but this card is project-bound. A list response
 * is actionable only in the exact Cockpit project generation that requested
 * it. Models may propose; only the explicit controls below hand off or dismiss.
 */

export interface DecisionBinding {
  project: string;
  generation: number;
}

function sameBinding(left: DecisionBinding, right: DecisionBinding): boolean {
  return left.project === right.project && left.generation === right.generation;
}

interface DecisionSnapshot extends DecisionBinding {
  pending: DraftRow[];
  scope: string | null;
  scopeWarning: string;
  error: string;
  loaded: boolean;
}

interface DecisionDetailState extends DecisionBinding {
  draftId: string;
  open: boolean;
  value?: DraftDetail;
}

interface DecisionBusyState extends DecisionBinding {
  draftId: string;
  kind: 'handoff' | 'dismiss';
  claim: symbol;
}

export interface DecisionProps {
  /** Which repository's drafts this card may show as its own. */
  project: string;
  /** Synchronous project epoch owned by Cockpit. */
  generation: number;
  /** Bumped by the caller when something may have created a draft. */
  signal?: number;
  onChanged?: (binding: DecisionBinding) => void;
  onCount?: (binding: DecisionBinding, count: number) => void;
  /** The whole pending queue, plus whether it is honestly this project's. */
  onPending?: (binding: DecisionBinding, rows: DraftRow[], scoped: boolean) => void;
}

export function Decision({ project, generation, signal = 0, onChanged, onCount, onPending }: DecisionProps) {
  const bindingRef = useRef<DecisionBinding>({ project, generation });
  bindingRef.current = { project, generation };
  const aliveRef = useRef(true);
  const [snapshot, setSnapshot] = useState<DecisionSnapshot>({
    project,
    generation,
    pending: [],
    scope: null,
    scopeWarning: '',
    error: '',
    loaded: false
  });
  const [detailState, setDetailState] = useState<DecisionDetailState>();
  const [busyState, setBusyState] = useState<DecisionBusyState>();
  const [interactionError, setInteractionError] = useState<(DecisionBinding & { message: string })>();
  const loadId = useRef(0);
  const detailClaim = useRef<(DecisionBinding & { draftId: string; claim: symbol }) | undefined>(undefined);
  const actionClaim = useRef<(DecisionBinding & { draftId: string; claim: symbol }) | undefined>(undefined);

  const isCurrentBinding = useCallback(
    (binding: DecisionBinding) => aliveRef.current && sameBinding(bindingRef.current, binding),
    []
  );

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
      loadId.current += 1;
      detailClaim.current = undefined;
      actionClaim.current = undefined;
    };
  }, []);

  const load = useCallback(async (binding: DecisionBinding) => {
    if (!isCurrentBinding(binding)) return;
    const requestId = ++loadId.current;

    // Clear the prior epoch before the GET can settle. Parent projections get
    // the same binding and independently reject stale callbacks.
    setSnapshot({ ...binding, pending: [], scope: null, scopeWarning: '', error: '', loaded: false });
    setDetailState(undefined);
    setInteractionError(undefined);
    onCount?.(binding, 0);
    onPending?.(binding, [], false);

    try {
      const payload = await getDrafts(binding.project);
      if (!isCurrentBinding(binding) || loadId.current !== requestId) return;
      const rows = (payload.drafts || []).filter((draft) => draft.status === 'pending');
      setSnapshot({
        ...binding,
        pending: rows,
        scope: payload.scope,
        scopeWarning: payload.warnings?.[0] || '',
        error: '',
        loaded: true
      });
      onCount?.(binding, payload.scope !== null ? rows.length : 0);
      onPending?.(binding, rows, payload.scope !== null);
    } catch (reason) {
      if (!isCurrentBinding(binding) || loadId.current !== requestId) return;
      setSnapshot({
        ...binding,
        pending: [],
        scope: null,
        scopeWarning: '',
        error: reason instanceof Error ? reason.message : 'Entwürfe konnten nicht gelesen werden.',
        loaded: true
      });
      onCount?.(binding, 0);
      onPending?.(binding, [], false);
    }
  }, [isCurrentBinding, onCount, onPending]);

  useEffect(() => {
    void load({ project, generation });
  }, [generation, load, project, signal]);

  // A prior project's snapshot becomes inert during render, before effects run
  // and before a stale promise callback can repaint or expose its controls.
  const ownsSnapshot = sameBinding(snapshot, bindingRef.current);
  const pending = ownsSnapshot ? snapshot.pending : [];
  const scope = ownsSnapshot ? snapshot.scope : null;
  const scopeWarning = ownsSnapshot ? snapshot.scopeWarning : '';
  const loaded = ownsSnapshot && snapshot.loaded;
  const current = scope !== null ? pending[0] : undefined;
  const ownsDetail = Boolean(
    current
    && detailState
    && sameBinding(detailState, bindingRef.current)
    && detailState.draftId === current.id
  );
  const detail = ownsDetail ? detailState?.value : undefined;
  const open = ownsDetail ? Boolean(detailState?.open) : false;
  const busy = current && busyState
    && sameBinding(busyState, bindingRef.current)
    && busyState.draftId === current.id
      ? busyState.kind
      : '';
  const error = (ownsSnapshot ? snapshot.error : '') || (
    interactionError && sameBinding(interactionError, bindingRef.current) ? interactionError.message : ''
  );

  const why = useCallback(async () => {
    if (!current) return;
    const binding = { project, generation };
    if (!isCurrentBinding(binding)) return;
    const draftId = current.id;
    const opening = !open;
    setDetailState((previous) => ({
      ...binding,
      draftId,
      open: opening,
      value: previous && sameBinding(previous, binding) && previous.draftId === draftId
        ? previous.value
        : undefined
    }));
    if (!opening || detail || !draftId) return;
    if (detailClaim.current
      && sameBinding(detailClaim.current, binding)
      && detailClaim.current.draftId === draftId) return;

    const claim = Symbol('decision-detail');
    detailClaim.current = { ...binding, draftId, claim };
    try {
      const payload = await getDraft(draftId);
      if (detailClaim.current?.claim !== claim || !isCurrentBinding(binding)) return;
      setDetailState((previous) => (
        previous && sameBinding(previous, binding) && previous.draftId === draftId
          ? { ...previous, value: payload.draft }
          : previous
      ));
    } catch (reason) {
      if (detailClaim.current?.claim !== claim || !isCurrentBinding(binding)) return;
      setInteractionError({
        ...binding,
        message: reason instanceof Error ? reason.message : 'Der Entwurf konnte nicht gelesen werden.'
      });
    } finally {
      if (detailClaim.current?.claim === claim) detailClaim.current = undefined;
    }
  }, [current, detail, generation, isCurrentBinding, open, project]);

  const act = useCallback(async (kind: 'handoff' | 'dismiss') => {
    if (!current) return;
    const binding = { project, generation };
    if (!isCurrentBinding(binding)) return;
    const draftId = current.id;
    if (actionClaim.current && sameBinding(actionClaim.current, binding)) return;

    const claim = Symbol('decision-action');
    actionClaim.current = { ...binding, draftId, claim };
    setBusyState({ ...binding, draftId, kind, claim });
    setInteractionError(undefined);
    try {
      // The historical API calls handoff "apply". It is not evidence of a
      // repository write, successful evaluation, or promotion.
      if (kind === 'handoff') await applyDraft(draftId);
      else await dismissDraft(draftId);
      if (actionClaim.current?.claim !== claim || !isCurrentBinding(binding)) return;

      // Hide the acted-on snapshot before releasing the synchronous claim.
      // The parent signal starts exactly one fresh, project-bound list read.
      setSnapshot({ ...binding, pending: [], scope, scopeWarning: '', error: '', loaded: false });
      setDetailState(undefined);
      onCount?.(binding, 0);
      onPending?.(binding, [], scope !== null);
      onChanged?.(binding);
    } catch (reason) {
      if (actionClaim.current?.claim !== claim || !isCurrentBinding(binding)) return;
      setInteractionError({
        ...binding,
        message: reason instanceof Error ? reason.message : 'Die Aktion ist fehlgeschlagen.'
      });
    } finally {
      if (actionClaim.current?.claim === claim) actionClaim.current = undefined;
      if (isCurrentBinding(binding)) {
        setBusyState((previous) => (previous?.claim === claim ? undefined : previous));
      }
    }
  }, [current, generation, isCurrentBinding, onChanged, onCount, onPending, project, scope]);

  if (!loaded) {
    return (
      <div className="decision quiet" role="status" aria-busy="true" aria-label="Entscheidung">
        <span className="dot pending" aria-hidden="true" />
        <p className="decision-none">Entwürfe werden gelesen …</p>
      </div>
    );
  }

  if (!current) {
    const unresolved = scope === null && scopeWarning;
    const unscoped = scope === null && !scopeWarning;
    const tone = error || unresolved ? 'bad' : unscoped ? 'pending' : 'muted';
    return (
      <div className="decision quiet" role={error || unresolved ? 'alert' : 'status'} aria-label="Entscheidung">
        <span className={`dot ${tone}`} aria-hidden="true" />
        <p className={error || unresolved ? 'decision-error' : 'decision-none'}>
          {error
            ? error
            : unresolved
              ? `Projekt nicht gefunden — ${scopeWarning}`
              : unscoped
                ? 'Projekt wird ermittelt …'
                : (
                  <>
                    Nichts wartet auf dich. Entwürfe erscheinen hier, sobald ein Lauf einen erzeugt hat. Entwürfe ohne
                    Projekt zeigt dir <code>daedalus drafts list</code>.
                  </>
                )}
        </p>
      </div>
    );
  }

  return (
    <div className="decision" role="region" aria-label="Offene Entscheidung">
      <div className="decision-head">
        <span className="decision-eyebrow">
          <span className="dot warn" aria-hidden="true" />
          Entscheidung
        </span>
        {pending.length > 1 && <span className="decision-count">{pending.length} offen</span>}
      </div>
      <h2 className="decision-title">{current.objective || current.id}</h2>
      <p className="decision-sub">
        Von <b>{current.agent || 'unbekannt'}</b>
        {current.paths?.length ? ` · ${current.paths.length} Pfad(e)` : ''} · angelegt {current.created}. Eine explizite
        Bestätigung übergibt den Entwurf an den bestehenden Daedalus-Pfad; sie belegt keine Repository-Änderung,
        Auswertung oder Promotion. Ablehnen legt den Entwurf zur Seite.
      </p>

      <div className="decision-acts">
        <button type="button" className="primary" onClick={() => void act('handoff')} disabled={busy !== ''}>
          {busy === 'handoff' ? 'Übergabe wird bestätigt …' : 'Übergabe bestätigen'}
        </button>
        <button type="button" onClick={() => void act('dismiss')} disabled={busy !== ''}>
          {busy === 'dismiss' ? 'Wird abgelegt …' : 'Ablehnen'}
        </button>
        <button type="button" className="quiet" onClick={() => void why()} aria-expanded={open}>
          Warum
        </button>
      </div>

      {error && (
        <p className="decision-error" role="alert">
          <span className="dot bad" aria-hidden="true" />
          {error}
        </p>
      )}

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
                    {detail.report.files_changed.slice(0, 8).map((file) => (
                      <li key={file}><code>{file}</code></li>
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
                    {detail.report.risks.map((risk) => <li key={risk}>{risk}</li>)}
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
