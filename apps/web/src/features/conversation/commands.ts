import type { EffortLevel } from '@/shared/contracts';

/**
 * `/` commands for the composer.
 *
 * A command is a shortcut to something the surface can already do — never a
 * new capability, and never a hidden effect. Two of them send a fixed word
 * down the deterministic route the backend classifies by itself
 * (`ikarus_os.classify`: `status`, `distill`); the rest are in-page actions
 * that touch no server. A command the surface does not know is sent verbatim:
 * Ikarus may know it, and the surface does not pretend it did.
 *
 * Pure. The composer decides what to do with the parsed action; this module
 * only says what was typed.
 */

export interface CommandSpec {
  name: string;
  /** the argument's name, when the command takes one */
  arg?: string;
  /** the argument is optional; the command still runs without it */
  argOptional?: boolean;
  /** one line, in the interface's voice */
  summary: string;
}

export const COMMANDS: readonly CommandSpec[] = [
  { name: 'status', summary: 'Projektzustand aus dem lokalen Index, ohne Modell' },
  { name: 'distill', summary: 'Struktur destillieren, ohne Modell' },
  { name: 'plan', arg: 'Frage', summary: 'Zeigt, was für diese Frage gelesen würde. Sendet nichts.' },
  { name: 'karte', arg: 'Modul', summary: 'Rückt das Modul auf der Karte in die Mitte' },
  { name: 'neu', summary: 'Neuer Verlauf' },
  { name: 'modell', summary: 'Wer antwortet' },
  { name: 'aufwand', arg: 'gering | mittel | hoch', summary: 'Wie viel das Modell beim nächsten Turn nachdenken darf' },
  { name: 'abbrechen', summary: 'Fordert den Abbruch des laufenden Turns an' },
  { name: 'hilfe', summary: 'Diese Liste, als Hinweis im Verlauf' }
];

export type CommandAction =
  | { kind: 'send'; message: string }
  | { kind: 'plan'; text: string }
  | { kind: 'map'; module: string }
  | { kind: 'new' }
  | { kind: 'model' }
  | { kind: 'effort'; level: EffortLevel }
  | { kind: 'cancel' }
  | { kind: 'help' }
  /** a known command that needs an argument and did not get one */
  | { kind: 'incomplete'; command: CommandSpec; hint: string }
  /** a `/word` the surface does not know — sent verbatim */
  | { kind: 'unknown'; message: string };

export const EFFORT_WORDS: Readonly<Record<string, EffortLevel>> = {
  gering: 'low',
  niedrig: 'low',
  low: 'low',
  mittel: 'medium',
  medium: 'medium',
  hoch: 'high',
  high: 'high'
};

export const EFFORT_LABEL: Readonly<Record<EffortLevel, string>> = {
  low: 'gering',
  medium: 'mittel',
  high: 'hoch'
};

/** True when the draft is a command and not a sentence that happens to start with `/`. */
export function looksLikeCommand(draft: string): boolean {
  return /^\/[a-zäöü]*$/i.test(draft.trim()) || /^\/[a-zäöü]+\s/i.test(draft.trimStart());
}

/** The commands whose name begins with what was typed after the slash. */
export function matchCommands(draft: string): CommandSpec[] {
  const m = /^\/([a-zäöü]*)/i.exec(draft.trimStart());
  if (!m) return [];
  const prefix = m[1].toLowerCase();
  return COMMANDS.filter((c) => c.name.startsWith(prefix));
}

/**
 * Parse a draft. `null` when it is not a command at all, so the composer
 * sends it as typed.
 */
export function parseCommand(draft: string): CommandAction | null {
  const text = draft.trim();
  const m = /^\/([a-zäöü]+)(?:\s+([\s\S]*))?$/i.exec(text);
  if (!m) return null;
  const name = m[1].toLowerCase();
  const arg = (m[2] || '').trim();
  const spec = COMMANDS.find((c) => c.name === name);
  if (!spec) return { kind: 'unknown', message: text };
  switch (spec.name) {
    case 'status':
      return { kind: 'send', message: 'status' };
    case 'distill':
      return { kind: 'send', message: 'distill' };
    case 'plan':
      return arg ? { kind: 'plan', text: arg } : { kind: 'incomplete', command: spec, hint: 'Wozu? /plan gefolgt von der Frage.' };
    case 'karte':
      return arg ? { kind: 'map', module: arg } : { kind: 'incomplete', command: spec, hint: 'Welches Modul? /karte gefolgt vom Dateinamen.' };
    case 'neu':
      return { kind: 'new' };
    case 'modell':
      return { kind: 'model' };
    case 'aufwand': {
      const level = EFFORT_WORDS[arg.toLowerCase()];
      return level
        ? { kind: 'effort', level }
        : { kind: 'incomplete', command: spec, hint: 'Wie viel? /aufwand gering, mittel oder hoch.' };
    }
    case 'abbrechen':
      return { kind: 'cancel' };
    case 'hilfe':
      return { kind: 'help' };
    default:
      return { kind: 'unknown', message: text };
  }
}

/** The help note, as Markdown the transcript renders. Never sent. */
export function helpText(): string {
  const rows = COMMANDS.map((c) => `| \`/${c.name}${c.arg ? ` ${c.arg}` : ''}\` | ${c.summary} |`);
  return [
    'Befehle beginnen mit `/`. Zwei davon senden ein Wort an den lokalen Index; alle anderen bleiben auf dieser Seite.',
    '',
    '| Befehl | Wirkung |',
    '| --- | --- |',
    ...rows,
    '',
    'Enter sendet, Shift+Enter bricht die Zeile, ↑ holt die letzte Nachricht zurück.'
  ].join('\n');
}
