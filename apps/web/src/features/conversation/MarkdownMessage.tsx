import { useState, type ReactNode } from 'react';
import Markdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface MarkdownMessageProps {
  text: string;
  streaming?: boolean;
  /** seconds since the turn went out; drawn while the stream is still empty */
  elapsed?: number;
}

/**
 * Model output is Markdown, and this page typesets it — through
 * react-markdown, which builds React nodes and never HTML, so a model answer
 * cannot become an XSS surface. Three deliberate limits on top of that:
 *
 * - raw HTML in the answer is skipped, not rendered (`skipHtml`);
 * - links open only for http(s) targets; anything else is plain text;
 * - images are never fetched. An `<img src="https://…">` in a model answer
 *   would make THIS browser reach an external host, which is egress the
 *   effect boundary never approved. The alt text is printed instead.
 *
 * Headings are clamped to h3…h5 so an answer cannot outrank the page.
 */

function safeHref(value?: string): string | undefined {
  if (!value) return undefined;
  try {
    const url = new URL(value);
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.toString() : undefined;
  } catch {
    return undefined;
  }
}

function CodeBlock({ language, code }: { language: string; code: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
    }
  };
  const lines = code ? code.split('\n').length : 0;
  return (
    <div className="md-codeblock">
      <div className="md-codebar">
        <span className="md-codelang">{language || 'code'}</span>
        <span className="md-codelines">{lines} {lines === 1 ? 'Zeile' : 'Zeilen'}</span>
        <button type="button" onClick={() => void copy()} aria-label="Code kopieren">{copied ? 'Kopiert' : 'Kopieren'}</button>
      </div>
      <pre><code className={language ? `language-${language}` : undefined}>{code}</code></pre>
    </div>
  );
}

/** The raw text and language of a fenced block, read off the hast node so a
 *  custom `pre` needs no knowledge of how `code` rendered its children. */
function fenced(node: unknown): { language: string; code: string } {
  const pre = node as { children?: Array<{ properties?: { className?: unknown }; children?: Array<{ value?: unknown }> }> } | undefined;
  const codeNode = pre?.children?.[0];
  const classes = codeNode?.properties?.className;
  const classList = Array.isArray(classes) ? classes.map(String) : typeof classes === 'string' ? [classes] : [];
  const language = classList.map((c) => /^language-(.+)$/.exec(c)?.[1]).find(Boolean) || '';
  const code = (codeNode?.children || []).map((c) => (typeof c.value === 'string' ? c.value : '')).join('').replace(/\n$/, '');
  return { language, code };
}

const components: Components = {
  a: ({ href, children }) => {
    const safe = safeHref(href);
    return safe ? <a href={safe} target="_blank" rel="noreferrer">{children}</a> : <span>{children}</span>;
  },
  img: ({ alt }) => <span className="md-img" title="Bilder werden nicht geladen">{alt ? `Bild: ${alt}` : 'Bild'}</span>,
  h1: ({ children }) => <h3>{children}</h3>,
  h2: ({ children }) => <h3>{children}</h3>,
  h3: ({ children }) => <h4>{children}</h4>,
  h4: ({ children }) => <h5>{children}</h5>,
  h5: ({ children }) => <h5>{children}</h5>,
  h6: ({ children }) => <h5>{children}</h5>,
  pre: ({ node }) => {
    const { language, code } = fenced(node);
    return <CodeBlock language={language} code={code} />;
  },
  table: ({ children }) => (
    <div className="md-table">
      <table>{children}</table>
    </div>
  ),
  // GFM task items render a real checkbox; a disabled form control is a
  // picture of a control, so it becomes a glyph the text describes.
  input: ({ checked }) => <span className={checked ? 'md-task on' : 'md-task'} aria-hidden="true" />
};

export function MarkdownMessage({ text, streaming = false, elapsed }: MarkdownMessageProps) {
  if (!text && streaming) {
    return (
      <div className="turn-text markdown thinking" role="status">
        <span>Ikarus denkt{elapsed !== undefined && elapsed >= 2 ? ` · ${elapsed} s` : ''}</span>
        <i /><i /><i />
      </div>
    );
  }
  return (
    <div className="turn-text markdown">
      <Markdown remarkPlugins={[remarkGfm]} components={components} skipHtml>
        {text}
      </Markdown>
      {streaming && <span className="caret" aria-hidden="true" />}
    </div>
  );
}

/** A local note the surface wrote itself — help, a command hint. */
export function NoteMessage({ children }: { children: ReactNode }) {
  return <div className="turn-text markdown note">{children}</div>;
}
