import { useCallback, useEffect, useState } from 'react';
import { ApiError, getCatalogue, type CataloguePayload } from '@/shared/api';
import {
  catalogueSummary,
  readEntries,
  rejectionNote
} from './catalogue';
import './catalogue.css';

/**
 * BAUTEILE — what this interface may be built from, and what it may not copy.
 *
 * `/api/catalogue` had no caller in the cockpit. It is a pure read by
 * construction: `read.py` keeps the latent half out of it precisely so a GET
 * carries no undeclared effect, and it ships the refusals beside the
 * admissions because "a reader must see what was REFUSED and why".
 *
 * The catalogue exists to catch licence traps, and it documents three by name:
 * a licence whose string starts with "MIT" and is not MIT, one recorded as
 * NOASSERTION as "the worked example of the honest third state", and a split
 * licence recorded at its stricter half "so a human is forced to look".
 *
 * Nothing rendered any of it. This section does, without re-deriving
 * permission: `use_mode` and `vendorable` are code-derived on the backend and
 * are the authority here.
 */

export interface CatalogueSectionProps {
  enabled: boolean;
  /** Injected so the loading and failure paths have a seam. */
  read?: typeof getCatalogue;
}

export function CatalogueSection({ enabled, read = getCatalogue }: CatalogueSectionProps) {
  const [payload, setPayload] = useState<CataloguePayload | undefined>();
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      setPayload(await read());
      setError('');
    } catch (err) {
      setError(err instanceof ApiError ? `${err.kind}: ${err.message}` : String(err));
    }
  }, [read]);

  useEffect(() => {
    if (enabled) void load();
  }, [enabled, load]);

  const block = payload?.catalogue;
  const entries = readEntries(block);
  // Refusals first: they are what a builder must know before reaching for
  // something, and a long list of permissive entries would bury them.
  const ordered = [...entries].sort((a, b) => Number(a.vendorable) - Number(b.vendorable));

  return (
    <section className="settings-section" aria-labelledby="catalogue-title">
      <div className="settings-title" id="catalogue-title">Bauteile</div>
      <p className="settings-hint">{catalogueSummary(block)}</p>

      {error && (
        <p className="settings-hint bad" role="alert">
          Der Bauteil-Katalog konnte nicht gelesen werden: {error}. Das ist nicht dasselbe wie
          „keine Einschränkungen“.
        </p>
      )}
      {!error && !block && <p className="settings-hint" role="status">Katalog wird gelesen …</p>}

      {block && (
        <>
          <ul className="cat-list">
            {ordered.map((e) => (
              <li key={e.name} className={`cat-row ${e.tone}`}>
                <span className="cat-head">
                  <span className={`dot ${e.tone}`} aria-hidden="true" />
                  <span className="cat-name">{e.name}</span>
                  {/* VERBATIM. Shortening "MIT-with-Commons-Clause" at the
                      first token produces "MIT", which is the exact error
                      this catalogue was built to prevent. */}
                  {e.licenceUrl ? (
                    <a className="cat-licence" href={e.licenceUrl} target="_blank" rel="noreferrer noopener">
                      {e.licence}
                    </a>
                  ) : (
                    <span className="cat-licence">{e.licence}</span>
                  )}
                </span>
                <span className={`cat-use ${e.tone}`}>{e.use}</span>
                {/* The registry's own caution, when the licence needs a
                    second look beyond its use_mode. */}
                {e.caution && <span className="cat-caution">{e.caution}</span>}
              </li>
            ))}
          </ul>
          {/* Zero refusals is reported as zero: an empty list is a fact about
              the load, and omitting it would leave a reader unable to tell
              "nothing was refused" from "refusals were not reported". */}
          <p className="settings-hint">{rejectionNote(block)}</p>
        </>
      )}
    </section>
  );
}
