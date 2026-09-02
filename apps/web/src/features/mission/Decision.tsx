import { useCallback, useEffect, useRef, useState } from 'react';
import { applyDraft, dismissDraft, getDraft, getDrafts, type DraftDetail, type DraftRow } from '@/shared/api';

/**
 * The one thing waiting for a person.
 *
 * This card exists only when a draft is actually pending. There is no
 * placeholder decision, no demo attempt, and no disabled Übergabe-Schalter
 * standing in for one — five review rounds died on affordances that were
 * pictures of affordances. When nothing is pending the card says so in one
 * line and offers nothing to press.
 *
 * "Warum" is not a tooltip. It fetches the draft's own report — what it
 * changed, what it ran, what it flagged as a risk — because a handoff without
 * a readable proposal is just an opaque state transition.
 *
 * THE DRAFT STORE IS SHARED, THE CARD IS NOT.
 *
 * `/api/drafts` used to be one pile for every project on the machine, and
 * this card showed its `pending[0]` as if it were `project`'s own — on this
 * machine that meant a card reading "427 offen" for a project that owned
 * zero of them [MEASURED 2026-08-26]. The backend now scopes by `repo_root`
 * and answers with `scope`: a path when the listing is really this
 * project's, `null` when it could not honestly narrow it (no project known
 * yet, or a project name it could not resolve — the second comes with a
 * `warnings` entry). `current` below is only ever read from `scope !== null`
 * — an unscoped batch is real data, but it is never presented as this
 * project's decision. Drafts written before the store recorded a
 * `repo_root` (a real, sizeable slice of the store on this machine) belong
 * to no project and are therefore invisible here on purpose; the empty
 * state below points at `daedalus drafts list` rather than pretending they
 * do not exist.
 */

export interface DecisionProps {
  /** which repository's drafts this card may show as its own */
  project: string;
  /** bumped by the caller when something happened that may have created a draft */
  signal?: number;
  onChanged?: () => void;
  /** how many drafts are pending, so the navigation can say so */
  onCount?: (n: number) => void;
  /**
   * The whole pending queue, and whether it is honestly this project's.
   *
   * The card reads every pending draft and draws exactly one — the rest were
   * fetched and dropped. The work rail lists them instead of issuing a second
   * GET against an endpoint measured at 12.5s on this machine.
   */
  onPending?: (rows: DraftRow[], scoped: boolean) => void;
}

export function Decision({ project, signal = 0, onChanged, onCount, onPending }: DecisionProps) {
  const [pending, setPending] = useState<DraftRow[]>([]);
  /** `null` until proven otherwise — see the file doc comment. Only a
   *  resolved path makes `pending` this project's to show or act on. */
  const [scope, setScope] = useState<string | null>(null);
  const [scopeWarning, setScopeWarning] = useState('');
  const [detail, setDetail] = useState<DraftDetail | undefined>();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [loaded, setLoaded] = useState(false);

  /**
   * Which `load()` call is still the one that matters.
   *
   * `project` starts as `''` on first mount — Cockpit resolves it from the
   * project list a beat later — so this fires once unscoped, then again a
   * moment later correctly scoped. Both are in flight at once, the backend
   * is slow enough right now [MEASURED 2026-08-26: 17–31s per call under
   * this session's load] that either can resolve last, and a stale unscoped
   * timeout landing AFTER the real answer would overwrite a correct,
   * honestly-scoped result with a wrong error. Only the most recently
   * STARTED call is allowed to write state, independent of which one
   * finishes first. The local `alive` guard below follows the same rule.
   */
  const loadId = useRef(0);

  const load = useCallback(async () => {
    const id = ++loadId.current;
    try {
      const payload = await getDrafts(project);
      if (loadId.current !== id) return;
      const rows = (payload.drafts || []).filter((d) => d.status === 'pending');
      setPending(rows);
      setScope(payload.scope);
      setScopeWarning(payload.warnings?.[0] || '');
      // Never hand the nav badge an unscoped count under this project's name.
      onCount?.(payload.scope !== null ? rows.length : 0);
      onPending?.(rows, payload.scope !== null);
      setError('');
    } catch (e) {
      if (loadId.current !== id) return;
      setError(e instanceof Error ? e.message : 'Entwürfe konnten nicht gelesen werden.');
      onPending?.([], false);
    } finally {
      if (loadId.current === id) setLoaded(true);
    }
  }, [onCount, onPending, project]);

  useEffect(() => {
    void load();
    // `load` already changes identity when `project` changes, but that is an
    // implementation detail of useCallback's memoisation, not a contract —
    // list the real trigger explicitly so a refactor cannot drop it.
  }, [load, signal, project]);

  const current = scope !== null ? pending[0] : undefined;

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
    async (kind: 'handoff' | 'dismiss') => {
      if (!current) return;
      setBusy(kind);
      setError('');
      try {
        // The existing API calls this historical state "apply". In this
        // cockpit it means only that the reviewed draft was handed to the
        // canonical Daedalus path; it is not evidence of a repository write,
        // successful evaluation, or promotion.
        if (kind === 'handoff') await applyDraft(current.id);
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
      <div className="decision quiet" role="status" aria-busy="true" aria-label="Entscheidung">
        <span className="dot pending" aria-hidden="true" />
        <p className="decision-none">Entwürfe werden gelesen …</p>
      </div>
    );
  }

  if (!current) {
    // `scope === null` splits two different situations, and they read
    // differently on purpose: a project name the backend could not resolve
    // is a real problem (it comes with a `warnings` entry); a project not
    // known yet is just early, the same "unknown" this line uses everywhere
    // else — never "keine Entwürfe", which would claim a measured zero.
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
