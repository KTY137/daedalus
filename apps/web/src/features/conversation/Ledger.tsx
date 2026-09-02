import { useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { revealVariants, useReducedMotionPref } from '@/shared/ui/motion';
import type { LedgerRow, RowTone } from './model';

/**
 * THE PROTOKOLL — the one bold move on this page.
 *
 * A hairline spine down the left of an answer, one row per receipt the
 * kernel wrote about that turn, in the order it wrote them. Each row is one
 * line: a glyph in the tone of the fact, the role word, the datum. A row
 * with nothing measured does not exist.
 *
 * The glyphs are drawn, not typed. Filled means a fact about a run that
 * happened (measured, failed, unclear); hollow means a claim or a
 * description (a model's answer, a selection); the live glyph breathes on
 * the theme's own ambient duration and holds still under reduced motion.
 *
 * ONE disclosure per ledger, not one per row: every pointer target on this
 * surface is 44px, and nine 44px rows would turn a receipt into a form. The
 * rows stay one text line tall; the foot opens all their detail at once.
 */

function Glyph({ tone }: { tone: RowTone }) {
  const filled = tone === 'ok' || tone === 'bad' || tone === 'warn';
  return (
    <svg className={`ledger-glyph ${tone}`} viewBox="0 0 12 12" width="12" height="12" aria-hidden="true" focusable="false">
      <circle cx="6" cy="6" r="4" fill={filled ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="1.5" />
      {tone === 'live' && <circle className="ledger-glyph-pulse" cx="6" cy="6" r="2" fill="currentColor" />}
    </svg>
  );
}

function toneWord(tone: RowTone): string {
  switch (tone) {
    case 'ok': return 'belegt';
    case 'bad': return 'abgelehnt oder fehlgeschlagen';
    case 'warn': return 'unklar';
    case 'live': return 'läuft';
    default: return '';
  }
}

export function Ledger({ rows }: { rows: LedgerRow[] }) {
  const [open, setOpen] = useState(false);
  const reduced = useReducedMotionPref();
  const reveal = useMemo(() => revealVariants(reduced), [reduced]);
  if (rows.length === 0) return null;
  const detailed = rows.filter((r) => r.detail && r.detail.length > 0).length;
  return (
    <div className={open ? 'ledger open' : 'ledger'}>
      <ol className="ledger-rows" aria-label="Protokoll dieser Antwort">
        {rows.map((row) => {
          const word = toneWord(row.tone);
          const hasDetail = Boolean(row.detail && row.detail.length > 0);
          return (
            <motion.li
              key={row.key}
              className={`ledger-row ${row.tone}`}
              data-motion="ledger-row"
              data-key={row.key}
              variants={reveal}
              initial="hidden"
              animate="visible"
            >
              <Glyph tone={row.tone} />
              {word && <span className="visually-hidden">{word}: </span>}
              <span className="ledger-label">{row.label}</span>
              <span className={row.stamp ? 'ledger-datum stamp' : 'ledger-datum'}>{row.datum}</span>
              {hasDetail && open && (
                <ul className="ledger-detail">
                  {row.detail!.map((line, i) => (
                    <li key={i}>{line}</li>
                  ))}
                </ul>
              )}
            </motion.li>
          );
        })}
      </ol>
      {detailed > 0 && (
        <button
          type="button"
          className="ledger-toggle"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          {open ? 'Protokoll einklappen' : `Protokoll aufklappen · ${detailed} ${detailed === 1 ? 'Eintrag' : 'Einträge'} mit Details`}
        </button>
      )}
    </div>
  );
}
