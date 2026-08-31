import { useCallback, useState } from 'react';
import { getContextPlan } from '@/shared/api';
import type { ContextPlanPayload } from '@/shared/contracts';
import { shortLabel } from '@/features/twin/graph';

/**
 * What would be read, before anything reads it.
 *
 * This is the distillation claim made inspectable. Press it with a question in
 * the box and the backend ranks the repository against that question — the
 * seeds it would feed a model, the terms it actually derived from your
 * sentence, whether the latent route was consulted, and the digests that make
 * the answer reproducible.
 *
 * Three things it deliberately shows rather than hides:
 *
 *  - the SCORE next to every seed, because a ranked list with the ranking
 *    removed is a list of opinions;
 *  - the latent route's status when it is off, in its own words, instead of a
 *    silently lexical-only result presented as the whole method;
 *  - the receipt digest, so a seed list on screen can be tied to the run that
 *    produced it.
 */

export interface ContextPlanProps {
  project: string;
  /** the question in the composer right now; empty disables the control */
  objective: string;
  onFocusModule: (module: string) => void;
  /** used to check a seed is a module the stage can actually open */
  resolveModule: (needle: string) => string | undefined;
}

const TOP = 8;

export function ContextPlan({ project, objective, onFocusModule, resolveModule }: ContextPlanProps) {
  const [plan, setPlan] = useState<ContextPlanPayload['context_plan'] | undefined>();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const question = objective.trim();

  const load = useCallback(async () => {
    if (!question || !project) return;
    if (open) {
      setOpen(false);
      return;
    }
    setBusy(true);
    setError('');
    try {
      const payload = await getContextPlan(project, question);
      setPlan(payload.context_plan);
      setOpen(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Der Kontextplan konnte nicht gelesen werden.');
      setOpen(true);
    } finally {
      setBusy(false);
    }
  }, [open, project, question]);

  const seeds = plan ? Object.entries(plan.seeds?.scores || {}).sort((a, b) => b[1] - a[1]) : [];
  const terms = plan?.seeds?.lexical?.query_terms || [];
  const latent = plan?.seeds?.latent;

  return (
    <div className="ctxplan">
      <button
        type="button"
        className="ctxplan-toggle"
        onClick={() => void load()}
        disabled={!question || busy || !project}
        aria-expanded={open}
        title={question ? 'Zeigen, was für diese Frage gelesen würde' : 'Erst eine Frage tippen'}
      >
        {busy ? 'Wird geplant …' : open ? 'Kontext verbergen' : 'Was würde gelesen?'}
      </button>

      {open && (
        <div className="ctxplan-body">
          {error && <p className="ctxplan-error" role="alert">{error}</p>}
          {plan && (
            <>
              <p className="ctxplan-line">
                {seeds.length} Kandidaten gerankt · gezeigt {Math.min(TOP, seeds.length)}
                {terms.length ? (
                  <>
                    {' '}· Suchbegriffe{' '}
                    {terms.map((t) => (
                      <code key={t}>{t}</code>
                    ))}
                  </>
                ) : null}
              </p>

              <ol className="ctxplan-seeds">
                {seeds.slice(0, TOP).map(([module, score]) => {
                  const target = resolveModule(module);
                  return (
                    <li key={module}>
                      {target ? (
                        <button type="button" onClick={() => onFocusModule(target)} title={module}>
                          <span className="ctxplan-name">{shortLabel(module)}</span>
                          <span className="ctxplan-score">{score.toFixed(2)}</span>
                        </button>
                      ) : (
                        <span className="ctxplan-off" title={`${module} — nicht in der gezeichneten Karte`}>
                          <span className="ctxplan-name">{shortLabel(module)}</span>
                          <span className="ctxplan-score">{score.toFixed(2)}</span>
                        </span>
                      )}
                    </li>
                  );
                })}
              </ol>

              <p className="ctxplan-line muted">
                Lexikalisch ×{plan.seeds?.lexical_weight ?? 1}
                {' · '}
                {plan.seeds?.latent_applied
                  ? `latent ×${plan.seeds.effective_latent_weight}`
                  : `latent nicht angewandt${latent?.status ? ` (${latent.status})` : ''}`}
              </p>
              {!plan.seeds?.latent_applied && latent?.message && (
                <p className="ctxplan-line muted">{latent.message}</p>
              )}
              <p className="ctxplan-line muted">
                Quittung <code>{(plan.receipt?.receipt_sha256 || '').slice(0, 12)}</code> · Frage{' '}
                <code>{(plan.receipt?.objective_sha256 || '').slice(0, 12)}</code>
              </p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
