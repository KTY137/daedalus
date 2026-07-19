import { useState } from 'react';
import {
  AlertTriangle,
  Boxes,
  ChevronDown,
  Copy,
  Flame,
  Layers,
  RefreshCw,
  Scissors
} from 'lucide-react';
import { GlassButton, GlassCard, cx } from './glass';
import { distill } from '../api';
import type { DistillPayload, StructurePayload } from '../types';

interface StructureSheetProps {
  project: string;
  data?: StructurePayload;
  loading: boolean;
  error: string;
  onRefresh: () => void;
}

/** Round to at most one decimal, dropping a trailing `.0`. */
function pct(value: number): string {
  if (!Number.isFinite(value)) return '0';
  return String(Math.round(value * 10) / 10);
}

function num(value: number): string {
  return Number.isFinite(value) ? value.toLocaleString() : '0';
}

const ROLE_ORDER = ['focus', 'dependency', 'caller'];
const ROLE_LABEL: Record<string, string> = {
  focus: 'Focus',
  dependency: 'Dependency',
  caller: 'Caller'
};

/**
 * The Structure sheet: makes the multi-language structural core visible —
 * language coverage + backend badge, ranked hotspots (each distillable),
 * duplication clusters (unit + window clones, safety-fenced), and an
 * on-demand distillation result. Mirrors the other feature-panel sheets.
 */
export function StructureSheet({ project, data, loading, error, onRefresh }: StructureSheetProps) {
  const [distilling, setDistilling] = useState('');
  const [distillResult, setDistillResult] = useState<DistillPayload | undefined>();
  const [distillError, setDistillError] = useState('');
  const [distillTarget, setDistillTarget] = useState('');
  const [showSlice, setShowSlice] = useState(false);

  async function runDistill(target: string) {
    if (!target || distilling) return;
    setDistilling(target);
    setDistillTarget(target);
    setDistillError('');
    setShowSlice(false);
    try {
      const res = await distill(project, target);
      setDistillResult(res);
    } catch (err) {
      setDistillResult(undefined);
      setDistillError(err instanceof Error ? err.message : String(err));
    } finally {
      setDistilling('');
    }
  }

  return (
    <section className="panel feature-panel structure-panel">
      <div className="panel-head">
        <Boxes size={18} />
        <div>
          <h2>Structure</h2>
          <p>Multi-language code-health: hotspots, duplication and token-cheap distillation.</p>
        </div>
        <button
          type="button"
          className="iconbtn struct-refresh"
          onClick={onRefresh}
          disabled={loading}
          title="Re-index repository"
          aria-label="Re-index repository"
        >
          <RefreshCw size={15} className={loading ? 'spin' : undefined} />
        </button>
      </div>

      {loading && (
        <div className="struct-state">
          <RefreshCw size={22} className="spin" />
          <strong>Indexing {project || 'repository'}…</strong>
          <span>The first scan of a big repo can take up to a minute. Hang tight.</span>
        </div>
      )}

      {!loading && error && (
        <div className="struct-state struct-state-error">
          <AlertTriangle size={22} />
          <strong>Couldn't load structure</strong>
          <span>{error}</span>
          <GlassButton onClick={onRefresh}><RefreshCw size={14} /> Retry</GlassButton>
        </div>
      )}

      {!loading && !error && data && data.ok === false && (
        <div className="struct-state">
          <Boxes size={22} />
          <strong>Structure unavailable</strong>
          <span>The backend returned no structural data for this project.</span>
        </div>
      )}

      {!loading && !error && data && data.ok !== false && data.structure && (
        <StructureBody
          data={data}
          project={project}
          distilling={distilling}
          onDistill={runDistill}
          distillResult={distillResult}
          distillError={distillError}
          distillTarget={distillTarget}
          showSlice={showSlice}
          onToggleSlice={() => setShowSlice((v) => !v)}
        />
      )}

      {!loading && !error && !data && (
        <div className="struct-state">
          <Boxes size={22} />
          <strong>No structure yet</strong>
          <span>Open this sheet to index the project's structural core.</span>
        </div>
      )}
    </section>
  );
}

function StructureBody({
  data,
  distilling,
  onDistill,
  distillResult,
  distillError,
  distillTarget,
  showSlice,
  onToggleSlice
}: {
  data: StructurePayload;
  project: string;
  distilling: string;
  onDistill: (target: string) => void;
  distillResult?: DistillPayload;
  distillError: string;
  distillTarget: string;
  showSlice: boolean;
  onToggleSlice: () => void;
}) {
  const s = data.structure;
  const langs = Object.entries(s.languages || {}).sort((a, b) => b[1].files - a[1].files);
  const backend = s.backend || { tree_sitter: false, lizard: false };
  const totals = s.totals || { unit_clusters: 0, window_clusters: 0, safety_fenced: 0 };
  const hotspots = s.hotspots || [];
  const clones = s.clones || [];
  const windowClones = s.window_clones || [];

  return (
    <>
      {/* ---- header line: languages + backend badge + totals ---- */}
      <div className="struct-header">
        <div className="struct-chips">
          {langs.length === 0 && <span className="struct-chip muted">no languages detected</span>}
          {langs.map(([name, info]) => (
            <span className="struct-chip" key={name}>
              <b>{name}</b> {num(info.files)}f
            </span>
          ))}
        </div>
        <div className="struct-badges">
          <span
            className="struct-chip"
            style={{ color: backend.tree_sitter ? 'var(--good)' : 'var(--muted)' }}
          >
            tree-sitter {backend.tree_sitter ? 'on' : 'off'}
          </span>
          <span
            className="struct-chip"
            style={{ color: backend.lizard ? 'var(--good)' : 'var(--muted)' }}
          >
            lizard {backend.lizard ? 'on' : 'off'}
          </span>
          <span className="struct-chip">
            {num(totals.unit_clusters)} clone clusters · {num(totals.safety_fenced)} safety-fenced
          </span>
        </div>
      </div>

      {/* ---- hotspots ---- */}
      <div className="struct-section">
        <div className="section-title struct-section-title"><Flame size={14} /> Hotspots</div>
        {hotspots.length === 0 && <div className="struct-empty">No hotspots ranked for this repo.</div>}
        <div className="struct-list">
          {hotspots.map((h) => (
            <GlassCard className="hotspot-row" key={h.module}>
              <div className="hotspot-main">
                <strong title={h.module}>{h.module}</strong>
                <div className="hotspot-metrics">
                  <span className="hm-score">score {num(h.score)}</span>
                  <span>{num(h.loc)} loc</span>
                  {h.cc_max != null && <span>cc {num(h.cc_max)}</span>}
                  <span>{num(h.long_functions)} long-fn</span>
                  {h.guard_count > 0 && <span>{num(h.guard_count)} guards</span>}
                </div>
              </div>
              <GlassButton
                className="distill-btn"
                onClick={() => onDistill(h.module)}
                disabled={distilling === h.module}
              >
                <Scissors size={13} /> {distilling === h.module ? 'Distilling…' : 'Distill'}
              </GlassButton>
            </GlassCard>
          ))}
        </div>
      </div>

      {/* ---- distill result ---- */}
      {(distilling || distillResult || distillError) && (
        <DistillResult
          distilling={distilling}
          result={distillResult}
          error={distillError}
          target={distillTarget}
          showSlice={showSlice}
          onToggleSlice={onToggleSlice}
        />
      )}

      {/* ---- duplication ---- */}
      <div className="struct-section">
        <div className="section-title struct-section-title"><Copy size={14} /> Duplication</div>
        {clones.length === 0 && <div className="struct-empty">No unit clone clusters detected.</div>}
        <div className="struct-list">
          {clones.map((c, i) => (
            <GlassCard className="clone-card" key={`${c.name}-${i}`}>
              <div className="clone-head">
                <strong>
                  <span className="clone-count">×{num(c.count)}</span> {c.name}{' '}
                  <span className="clone-loc">(~{num(c.loc)} loc)</span>
                </strong>
                <span className="clone-lang">{c.language}</span>
                {c.safety != null && (
                  <span className="safety-pill" title={c.safety}>
                    <AlertTriangle size={11} /> SAFETY-FENCED
                  </span>
                )}
              </div>
              <div className="clone-sites">
                {(c.sites || []).slice(0, 4).map((site, j) => (
                  <span className="clone-site" key={`${site.module}-${site.line}-${j}`}>
                    {site.module}:{site.line}
                  </span>
                ))}
                {(c.sites || []).length > 4 && (
                  <span className="clone-site more">+{(c.sites || []).length - 4} more</span>
                )}
              </div>
            </GlassCard>
          ))}
        </div>

        {windowClones.length > 0 && (
          <>
            <div className="section-title struct-section-title struct-sub-title">
              <Layers size={14} /> Window clones
            </div>
            <div className="struct-list">
              {windowClones.slice(0, 6).map((w, i) => (
                <GlassCard className="window-clone" key={`win-${i}`}>
                  <div className="window-files">
                    {(w.files || []).map((f, j) => (
                      <span className="clone-site" key={`${f}-${j}`}>{f}</span>
                    ))}
                  </div>
                  <div className="window-meta">
                    <span className="pill">{num(w.shared_runs)} shared runs</span>
                    {w.safety != null && (
                      <span className="safety-pill" title={w.safety}>
                        <AlertTriangle size={11} /> SAFETY-FENCED
                      </span>
                    )}
                  </div>
                </GlassCard>
              ))}
            </div>
          </>
        )}
      </div>
    </>
  );
}

/**
 * Renders a `/api/distill` result: the reduction headline, the included files
 * grouped by role, and the collapsible slice text. Exported so the code map
 * (Movement II) surfaces distillation through the *same* display path instead
 * of growing a parallel one — one distill look, two entry points.
 */
export function DistillResult({
  distilling,
  result,
  error,
  target,
  showSlice,
  onToggleSlice
}: {
  distilling: string;
  result?: DistillPayload;
  error: string;
  target: string;
  showSlice: boolean;
  onToggleSlice: () => void;
}) {
  if (distilling) {
    return (
      <div className="distill-panel">
        <div className="distill-loading">
          <RefreshCw size={16} className="spin" /> Distilling <code>{distilling}</code>…
        </div>
      </div>
    );
  }
  if (error) {
    return (
      <div className="distill-panel">
        <div className="distill-loading distill-err">
          <AlertTriangle size={16} /> Distill failed: {error}
        </div>
      </div>
    );
  }
  if (!result || !result.distill) return null;

  const d = result.distill;
  const grouped = ROLE_ORDER
    .map((role) => ({ role, items: d.included.filter((it) => it.role === role) }))
    .filter((g) => g.items.length > 0);
  const otherRoles = d.included.filter((it) => !ROLE_ORDER.includes(it.role));
  if (otherRoles.length > 0) grouped.push({ role: 'other', items: otherRoles });

  return (
    <div className="distill-panel">
      <div className="distill-top">
        <div className="distill-headline">
          <span className="dh-num">{pct(d.reduction_pct)}%</span>
          <span className="dh-label">smaller</span>
        </div>
        <div className="distill-facts">
          <strong title={target || d.target}>{d.focus_symbol || d.focus_file || d.target}</strong>
          <span>
            {num(d.slice_tokens)} slice tokens · {num(d.whole_repo_tokens)} whole-repo tokens
          </span>
        </div>
      </div>

      <div className="distill-roles">
        {grouped.map((g) => (
          <div className="role-group" key={g.role}>
            <div className="role-head">{ROLE_LABEL[g.role] || g.role} · {g.items.length}</div>
            {g.items.map((it, i) => (
              <div className="role-file" key={`${it.file}-${i}`}>
                <span className="rf-name" title={it.file}>{it.file}</span>
                <span className="rf-meta">{it.mode} · {num(it.tokens)}t</span>
              </div>
            ))}
          </div>
        ))}
      </div>

      {d.slice_text && (
        <div className="slice-wrap">
          <button type="button" className="slice-toggle" onClick={onToggleSlice}>
            <ChevronDown size={14} className={cx('slice-caret', showSlice && 'open')} />
            {showSlice ? 'Hide' : 'Show'} distilled slice ({num(d.slice_text.length)} chars)
          </button>
          {showSlice && <pre className="slice-pre">{d.slice_text}</pre>}
        </div>
      )}
    </div>
  );
}
