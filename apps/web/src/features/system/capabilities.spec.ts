import type { CapabilityEntry } from '@/shared/contracts';
import {
  RISK_WORD,
  readCapabilities,
  readCapability,
  riskTone,
  unclassifiedNote
} from './capabilities';

/**
 * Grants against the registry, pinned.
 *
 * The registry below is verbatim from `/api/capabilities` on 2026-09-03, and
 * the grant list is the union across the 24 live agent profiles. Their
 * misalignment is the finding, not a fixture convenience.
 */

interface Result {
  name: string;
  ok: boolean;
  detail?: string;
}

/** The live registry: five entries. */
const REGISTRY: CapabilityEntry[] = [
  { id: 'web_search', name: 'Web Search', description: 'Research public information through an approved search connector.', requires_secret: false, risk: 'external_read' },
  { id: 'github_read', name: 'GitHub Read', description: '', requires_secret: false, risk: 'external_read' },
  { id: 'ollama_write', name: 'Ollama Write', description: '', requires_secret: false, risk: 'local_write' },
  { id: 'deepseek_advisory', name: 'DeepSeek Advisory', description: '', requires_secret: true, risk: 'external_advisory' },
  { id: 'claude_escalate', name: 'Claude Escalate', description: '', requires_secret: false, risk: 'trusted_frontier' }
];

/** Every capability granted across the 24 live profiles. */
const GRANTED = ['bash', 'claude_escalate', 'codex_delegate', 'external_api', 'file_write', 'ollama_write', 'read_files'];

export function runCapabilitySpec(): Result[] {
  const results: Result[] = [];
  const check = (name: string, ok: boolean, detail = '') => results.push({ name, ok, detail });

  // ---- 1. the misalignment, which is the whole point ---------------------
  const readings = readCapabilities(GRANTED, REGISTRY);
  const classified = readings.filter((r) => r.classified).map((r) => r.id);
  const open = readings.filter((r) => !r.classified).map((r) => r.id);

  check('only the two grants the registry declares are classified',
    classified.join(',') === 'claude_escalate,ollama_write', classified.join(','));
  check('the other five are reported as unclassified',
    open.join(',') === 'bash,codex_delegate,external_api,file_write,read_files', open.join(','));
  // The two that most obviously want a class are among them.
  check('bash and file_write are among the unclassified',
    open.includes('bash') && open.includes('file_write'));

  // ---- 2. an unclassified grant is unassessed, not safe ------------------
  const bash = readCapability('bash', REGISTRY);
  check('an unknown grant says no class was assigned',
    bash.text.includes('ohne eingestufte Risikoklasse'), bash.text);
  check('and is not drawn as unremarkable', bash.tone === 'warn', bash.tone);
  // AND NOT AS DANGEROUS EITHER. Guessing that `bash` is risky would be this
  // interface asserting a classification nobody made.
  check('and is not drawn as dangerous', bash.tone !== 'bad', bash.tone);
  check('an unclassified grant claims no secret requirement', bash.requiresSecret === false);
  check('nor a description it does not have', bash.description === '');

  // ---- 3. the summary names what is open ---------------------------------
  const note = unclassifiedNote(readings);
  check('the summary counts the unclassified grants', String(note).includes('5'), String(note));
  check('and names them, so the reader can act', String(note).includes('bash'), String(note));
  // Nothing to say when everything is classified.
  check('a fully classified profile gets no note',
    unclassifiedNote(readCapabilities(['ollama_write', 'claude_escalate'], REGISTRY)) === null);
  check('a profile with one open grant is counted in the singular',
    String(unclassifiedNote(readCapabilities(['bash'], REGISTRY))).startsWith('1 Berechtigung'));

  // ---- 4. the registry's own words are used, never paraphrased -----------
  const ollama = readCapability('ollama_write', REGISTRY);
  check('a declared class is translated, not invented',
    ollama.text === RISK_WORD.local_write && ollama.classified);
  const claude = readCapability('claude_escalate', REGISTRY);
  check('a trusted frontier grant is not flagged', claude.tone === '', claude.tone);
  const search = readCapability('web_search', REGISTRY);
  check('an external read is flagged', search.tone === 'warn');
  check('and carries the registry description',
    search.description.includes('approved search connector'), search.description);

  // ---- 5. a secret requirement is surfaced -------------------------------
  const deepseek = readCapability('deepseek_advisory', REGISTRY);
  check('a grant needing a secret says so', deepseek.requiresSecret === true);
  check('and one that does not, does not', ollama.requiresSecret === false);

  // ---- 6. an unrecognised class is reported, not swallowed ---------------
  // `risk` is a plain string in the contract on purpose: a NEW class must
  // reach the surface as an unrecognised word, not become a type error.
  const future = readCapability('x', [{ id: 'x', risk: 'quantum_egress' }]);
  check('an unrecognised risk class is shown raw', future.text === 'quantum_egress', future.text);
  check('and is not treated as safe', future.tone === 'warn');
  check('a registry entry with no risk at all says so',
    readCapability('y', [{ id: 'y' }]).text === 'Risikoklasse nicht gemeldet');
  check('an entry with no risk is still classified as present',
    readCapability('y', [{ id: 'y' }]).classified === true);

  // ---- 7. degenerate inputs ----------------------------------------------
  check('no registry means nothing is classified',
    readCapabilities(GRANTED, undefined).every((r) => !r.classified));
  check('no grants means no readings', readCapabilities(undefined, REGISTRY).length === 0);
  check('an empty grant name is dropped rather than rendered',
    readCapabilities(['', 'bash'], REGISTRY).length === 1);
  check('an unknown risk word is flagged', riskTone('something_new') === 'warn');
  check('a missing risk word is flagged', riskTone(undefined) === 'warn');

  return results;
}
