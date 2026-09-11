import type { CapabilityEntry } from '@/shared/contracts';

export type { CapabilityEntry };

/**
 * WHAT AN AGENT IS ALLOWED TO DO, AND WHETHER ANYONE CLASSIFIED IT.
 *
 * Two vocabularies meet here and they do not line up.
 *
 * `hierarchy.capabilities` is a REGISTRY: five entries, each with a `risk`
 * class and a `requires_secret` flag. It was typed in the contract as
 * `Array<Record<string, unknown>>` -- opaque, which is the same defect as an
 * undeclared field: present and unreachable. Nothing had ever rendered it.
 * It is `CapabilityEntry[]` now.
 *
 * `AgentProfile.capabilities` is a `string[]` of GRANTS, and the profile card
 * prints them as a flat comma list in which every entry looks alike.
 *
 * Measured on this machine, 2026-09-03, across 24 profiles:
 *
 *   registry declares  claude_escalate, deepseek_advisory, github_read,
 *                      ollama_write, web_search
 *   profiles grant     bash, claude_escalate, codex_delegate, external_api,
 *                      file_write, ollama_write, read_files
 *
 *   classified (both)  claude_escalate, ollama_write            -- 2
 *   UNCLASSIFIED       bash, codex_delegate, external_api,
 *                      file_write, read_files                   -- 5
 *   declared, unused   deepseek_advisory, github_read, web_search
 *
 * So FIVE OF SEVEN granted capabilities carry no declared risk class at all,
 * and they include `bash` and `file_write` -- the two that most obviously
 * need one. That is the finding, and it is only visible once the two lists
 * are put beside each other.
 *
 * THIS MODULE INVENTS NO RISK CLASS. It would be easy to guess that `bash` is
 * dangerous and colour it accordingly; that would be this interface asserting
 * a classification nobody made, which is the exact failure the rest of this
 * cockpit spends its length refusing. An unclassified grant is drawn as
 * unassessed -- not as safe, and not as dangerous.
 */

/** The risk classes the registry actually uses, measured 2026-09-03. */
export const RISK_WORD: Record<string, string> = {
  external_read: 'liest extern',
  local_write: 'schreibt lokal',
  external_advisory: 'fragt extern um Rat',
  trusted_frontier: 'vertrauenswürdiges Frontier-Modell'
};

/**
 * How a risk class is drawn.
 *
 * Anything leaving the machine is flagged; a local write is flagged because it
 * changes the tree. A class this interface does not recognise is flagged too:
 * a new risk word is not evidence of safety.
 */
export function riskTone(risk: string | undefined): string {
  if (!risk) return 'warn';
  if (risk === 'external_read' || risk === 'external_advisory') return 'warn';
  if (risk === 'local_write') return 'warn';
  if (risk === 'trusted_frontier') return '';
  return 'warn';
}

export interface CapabilityReading {
  id: string;
  /** the registry's word, or the raw class, or the unclassified sentence */
  text: string;
  tone: string;
  /** false when the registry has no entry for this grant at all */
  classified: boolean;
  requiresSecret: boolean;
  /** the registry's own description, when it has one */
  description: string;
}

/**
 * Read one grant against the registry.
 *
 * The registry is passed in rather than fetched: `hierarchy.capabilities` is
 * byte-identical to `/api/capabilities` (verified against both endpoints on
 * 2026-09-03) and the card already holds the hierarchy.
 */
export function readCapability(
  id: string,
  registry: CapabilityEntry[] | undefined
): CapabilityReading {
  const entry = (registry || []).find((c) => c && c.id === id);
  if (!entry) {
    return {
      id,
      text: 'ohne eingestufte Risikoklasse',
      tone: 'warn',
      classified: false,
      requiresSecret: false,
      description: ''
    };
  }
  const risk = typeof entry.risk === 'string' ? entry.risk : '';
  return {
    id,
    text: RISK_WORD[risk] || risk || 'Risikoklasse nicht gemeldet',
    tone: riskTone(risk || undefined),
    classified: true,
    requiresSecret: entry.requires_secret === true,
    description: typeof entry.description === 'string' ? entry.description : ''
  };
}

export function readCapabilities(
  ids: string[] | undefined,
  registry: CapabilityEntry[] | undefined
): CapabilityReading[] {
  return (ids || []).filter(Boolean).map((id) => readCapability(id, registry));
}

/**
 * The one-line summary for a profile: how many of its grants nobody has
 * classified.
 *
 * Returns null when every grant is classified, so the line appears only when
 * it has something to say.
 */
export function unclassifiedNote(readings: CapabilityReading[]): string | null {
  const open = readings.filter((r) => !r.classified);
  if (open.length === 0) return null;
  const names = open.map((r) => r.id).join(', ');
  return open.length === 1
    ? `1 Berechtigung ohne eingestufte Risikoklasse: ${names}`
    : `${open.length} Berechtigungen ohne eingestufte Risikoklasse: ${names}`;
}
