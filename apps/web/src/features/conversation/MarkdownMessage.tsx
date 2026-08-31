import { useMemo, useState, type ReactNode } from 'react';

interface MarkdownMessageProps {
  text: string;
  streaming?: boolean;
}

function safeHref(value: string): string | undefined {
  try {
    const url = new URL(value);
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.toString() : undefined;
  } catch {
    return undefined;
  }
}

/** Small, dependency-free Markdown renderer for model output.
 *
 * It intentionally supports the conversational subset Ikarus emits: headings,
 * paragraphs, ordered/unordered lists, quotes, fenced code, inline code,
 * emphasis and http(s) links. React owns escaping, so model text never becomes
 * HTML and a Markdown feature cannot turn into an XSS surface.
 */
function inline(text: string): ReactNode[] {
  const token = /(https?:\/\/[^\s<]+)|`([^`\n]+)`|\*\*([^*\n]+)\*\*|__([^_\n]+)__|\*([^*\n]+)\*/g;
  const out: ReactNode[] = [];
  let at = 0;
  let match: RegExpExecArray | null;
  let key = 0;
  while ((match = token.exec(text)) !== null) {
    if (match.index > at) out.push(text.slice(at, match.index));
    if (match[1]) {
      const href = safeHref(match[1]);
      out.push(href ? <a key={key++} href={href} target="_blank" rel="noreferrer">{match[1]}</a> : match[1]);
    } else if (match[2]) {
      out.push(<code key={key++}>{match[2]}</code>);
    } else if (match[3] || match[4]) {
      out.push(<strong key={key++}>{inline(match[3] || match[4])}</strong>);
    } else if (match[5]) {
      out.push(<em key={key++}>{inline(match[5])}</em>);
    }
    at = match.index + match[0].length;
  }
  if (at < text.length) out.push(text.slice(at));
  return out;
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
  return (
    <div className="md-codeblock">
      <div className="md-codebar">
        <span>{language || 'code'}</span>
        <button type="button" onClick={() => void copy()} aria-label="Code kopieren">{copied ? 'Kopiert' : 'Kopieren'}</button>
      </div>
      <pre><code className={language ? `language-${language}` : undefined}>{code}</code></pre>
    </div>
  );
}

type Block =
  | { kind: 'code'; language: string; value: string }
  | { kind: 'text'; value: string };

function splitFences(text: string): Block[] {
  const lines = text.split('\n');
  const blocks: Block[] = [];
  let plain: string[] = [];
  let code: string[] = [];
  let language = '';
  let fenced = false;
  const flushPlain = () => {
    if (plain.length) blocks.push({ kind: 'text', value: plain.join('\n') });
    plain = [];
  };
  const flushCode = () => {
    blocks.push({ kind: 'code', language, value: code.join('\n') });
    code = [];
    language = '';
  };
  for (const line of lines) {
    const fence = /^```\s*([\w.+-]*)\s*$/.exec(line);
    if (fence) {
      if (fenced) {
        flushCode();
        fenced = false;
      } else {
        flushPlain();
        language = fence[1] || '';
        fenced = true;
      }
      continue;
    }
    (fenced ? code : plain).push(line);
  }
  if (fenced) flushCode();
  flushPlain();
  return blocks;
}

function TextBlocks({ text }: { text: string }) {
  const lines = text.split('\n');
  const nodes: ReactNode[] = [];
  let i = 0;
  let key = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i += 1; continue; }
    const heading = /^(#{1,4})\s+(.+)$/.exec(line);
    if (heading) {
      const level = Math.min(4, heading[1].length + 1);
      const body = inline(heading[2]);
      if (level === 2) nodes.push(<h2 key={key++}>{body}</h2>);
      else if (level === 3) nodes.push(<h3 key={key++}>{body}</h3>);
      else nodes.push(<h4 key={key++}>{body}</h4>);
      i += 1; continue;
    }
    if (/^>\s?/.test(line)) {
      const quoted: string[] = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) quoted.push(lines[i++].replace(/^>\s?/, ''));
      nodes.push(<blockquote key={key++}>{quoted.map((q, n) => <p key={n}>{inline(q)}</p>)}</blockquote>);
      continue;
    }
    const unordered = /^\s*[-*+]\s+(.+)$/.exec(line);
    if (unordered) {
      const items: string[] = [];
      while (i < lines.length) {
        const m = /^\s*[-*+]\s+(.+)$/.exec(lines[i]);
        if (!m) break;
        items.push(m[1]); i += 1;
      }
      nodes.push(<ul key={key++}>{items.map((item, n) => <li key={n}>{inline(item)}</li>)}</ul>);
      continue;
    }
    const ordered = /^\s*\d+[.)]\s+(.+)$/.exec(line);
    if (ordered) {
      const items: string[] = [];
      while (i < lines.length) {
        const m = /^\s*\d+[.)]\s+(.+)$/.exec(lines[i]);
        if (!m) break;
        items.push(m[1]); i += 1;
      }
      nodes.push(<ol key={key++}>{items.map((item, n) => <li key={n}>{inline(item)}</li>)}</ol>);
      continue;
    }
    const paragraph: string[] = [line];
    i += 1;
    while (i < lines.length && lines[i].trim() && !/^(#{1,4})\s+|^>\s?|^\s*[-*+]\s+|^\s*\d+[.)]\s+/.test(lines[i])) {
      paragraph.push(lines[i++]);
    }
    nodes.push(<p key={key++}>{inline(paragraph.join('\n'))}</p>);
  }
  return <>{nodes}</>;
}

export function MarkdownMessage({ text, streaming = false }: MarkdownMessageProps) {
  const blocks = useMemo(() => splitFences(text), [text]);
  if (!text && streaming) {
    return <div className="turn-text markdown thinking" role="status"><span>Ikarus denkt</span><i /><i /><i /></div>;
  }
  return (
    <div className="turn-text markdown">
      {blocks.map((block, i) => block.kind === 'code'
        ? <CodeBlock key={i} language={block.language} code={block.value} />
        : <TextBlocks key={i} text={block.value} />)}
      {streaming && <span className="caret" aria-hidden="true" />}
    </div>
  );
}
