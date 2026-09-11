import type { GovernancePayload, GovernanceState } from '@/shared/contracts';

/**
 * HOW THE PROMOTION CHIP READS — pure, because the colour was wrong and a
 * wrong colour is not something you notice by looking at it once.
 *
 * `/api/governance` answers TWO different questions and the interface was
 * reading only one of them:
 *
 *   `promotion_allowed`  is derived from the DISCRIMINATION GATE ALONE. That
 *                        is deliberate — `daedalus/core.py` says the other
 *                        gates "inform the operator; they do not get a vote".
 *   `state`              is the worst-of-five aggregate across every gate. It
 *                        is the field the five-state vocabulary exists for,
 *                        and `shared/contracts` says in so many words that
 *                        nothing may collapse those five into a boolean.
 *
 * The chip coloured itself from the boolean. So a payload with
 * `discrimination: working` and `write_confinement: absent` — headline "the
 * local write lane is UNCONFINED" — rendered a GREEN chip reading "Promotion
 * offen", with the blocker count suppressed because the count was only on the
 * blocked branch of the ternary. A screen-reader user heard exactly
 * "Promotion öffnen: Promotion offen" while the write lane was unconfined.
 *
 * So: the WORD still answers the promotion question, because that is the
 * question the word asks. The COLOUR comes from the aggregate, the blocker
 * count is shown on both branches, and when the two answers disagree the chip
 * says so rather than letting the reassuring one win.
 */

/** Worst-of-five, same direction as everywhere else: only `working` is green. */
export function stateTone(state: GovernanceState | undefined): string {
  if (state === 'degraded' || state === 'absent') return 'bad';
  if (state === 'working') return 'ok';
  return 'warn';
}

export const STATE_WORD: Record<GovernanceState, string> = {
  working: 'hält',
  present: 'vorhanden, ungeprüft',
  degraded: 'beeinträchtigt',
  absent: 'fehlt',
  unknown: 'unbekannt'
};

export interface PromotionChip {
  text: string;
  tone: string;
  /** true when `promotion_allowed` is friendlier than the aggregate state */
  contested: boolean;
}

export function promotionChip(governance: GovernancePayload | undefined): PromotionChip {
  if (!governance) return { text: 'Promotion unbekannt', tone: 'pending', contested: false };

  const blockers = governance.blockers?.length || 0;
  const tone = stateTone(governance.state);
  // "Allowed, but a gate is absent" is the case the boolean hid.
  const contested = governance.promotion_allowed && tone !== 'ok';

  const parts: string[] = [governance.promotion_allowed ? 'Promotion offen' : 'Promotion gesperrt'];
  // The aggregate is named whenever it is not simply holding — including on
  // the allowed branch, which is the whole point.
  if (governance.state && governance.state !== 'working') {
    parts.push(`Gates ${STATE_WORD[governance.state] || governance.state}`);
  }
  // The count is no longer exclusive to the blocked branch.
  if (blockers > 0) parts.push(`${blockers} ${blockers === 1 ? 'Blocker' : 'Blocker'}`);

  return {
    text: parts.join(' · '),
    // A green word never gets a green chip while a gate is down.
    tone: governance.promotion_allowed ? tone : tone === 'ok' ? 'warn' : tone,
    contested
  };
}
