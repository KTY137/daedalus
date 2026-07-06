import { useCallback, useEffect, useMemo, useState } from 'react';
import { ReactFlow, Background, Controls, MiniMap, Node, Edge, Position, useEdgesState, useNodesState } from '@xyflow/react';
import {
  Bot,
  BrainCircuit,
  Check,
  ChevronRight,
  Cpu,
  FileText,
  GitBranch,
  KeyRound,
  MessageSquare,
  Network,
  Play,
  RefreshCw,
  Send,
  ShieldCheck,
  Sparkles,
  Terminal,
  Users
} from 'lucide-react';
import {
  chatIkarus,
  getControlPlane,
  getDashboard,
  getClaudeBootstrap,
  getHierarchy,
  getProjects,
  getRuntimeStatus,
  queueTask,
  testRuntime,
  updateAutonomy
} from './api';
import type { AgentProfile, BootstrapPayload, ControlPlanePayload, DashboardPayload, HierarchyNode, HierarchyPayload, IkarusChatPayload, NodeKind, ProjectRow, RuntimeRow, RuntimeTestPayload } from './types';

const kindRank: Record<NodeKind, number> = {
  project: 0,
  squad: 1,
  category: 1,
  agent: 2,
  model: 3,
  capability: 3,
  path: 3
};

const kindIcon: Record<NodeKind, string> = {
  project: 'Project',
  squad: 'Squad',
  category: 'Category',
  agent: 'Agent',
  model: 'Model',
  capability: 'Capability',
  path: 'Path'
};

function asText(value: unknown, fallback = '') {
  return value == null || value === '' ? fallback : String(value);
}

function cx(...parts: Array<string | false | undefined>) {
  return parts.filter(Boolean).join(' ');
}

function StudioNode({ data }: { data: any }) {
  return (
    <div className={cx('studio-node', `node-${data.kind}`, data.active === false && 'muted-node')}>
      <div className="node-meta">
        <span>{kindIcon[data.kind as NodeKind] || data.kind}</span>
        {data.sync && <b className={`sync sync-${data.sync}`}>{data.sync}</b>}
      </div>
      <strong>{data.label}</strong>
      {data.subtitle && <small>{data.subtitle}</small>}
    </div>
  );
}

const nodeTypes = { studio: StudioNode };

function graphNodes(nodes: HierarchyNode[], profiles: AgentProfile[]): Node[] {
  const profileByName = new Map(profiles.map((p) => [p.name, p]));
  const groups = new Map<number, HierarchyNode[]>();
  nodes
    .filter((n) => n.type !== 'path')
    .forEach((n) => {
      const rank = kindRank[n.type] ?? 2;
      groups.set(rank, [...(groups.get(rank) || []), n]);
    });
  const result: Node[] = [];
  [...groups.entries()].forEach(([rank, group]) => {
    const spacing = rank === 2 ? 138 : 170;
    const startY = -((group.length - 1) * spacing) / 2;
    group.forEach((n, index) => {
      const d = n.data || {};
      const agentName = n.id.startsWith('agent:') ? n.id.slice('agent:'.length) : '';
      const profile = profileByName.get(agentName);
      result.push({
        id: n.id,
        type: 'studio',
        position: { x: rank * 260, y: startY + index * spacing },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        data: {
          ...d,
          kind: n.type,
          label: n.label,
          sync: profile?.sync_status,
          active: profile ? profile.active : d.active,
          subtitle: n.type === 'agent'
            ? `${profile?.category_label || asText(d.category, 'uncategorized')} | ${profile?.capabilities.length || 0} caps`
            : n.type === 'category'
              ? `${asText(d.lane)} | ${asText(d.count, '0')} agents`
              : n.type === 'capability'
                ? asText(d.risk)
                : asText(d.repo_root || d.model || d.count)
        }
      });
    });
  });
  return result;
}

function graphEdges(edges: HierarchyPayload['edges']): Edge[] {
  return edges
    .filter((e) => !e.target.startsWith('path:'))
    .map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      type: 'smoothstep',
      animated: e.type === 'can_use' || e.type === 'uses_model',
      className: `edge-${e.type}`
    }));
}

function RuntimeCard({ runtime }: { runtime: Record<string, unknown> }) {
  return (
    <div className="runtime-card">
      <div>
        <strong>{asText(runtime.label)}</strong>
        <span>{asText(runtime.role)}</span>
      </div>
      <b className={`status-pill status-${asText(runtime.status)}`}>{asText(runtime.status)}</b>
    </div>
  );
}

function ProfileRow({ profile, selected, onSelect }: { profile: AgentProfile; selected: boolean; onSelect: () => void }) {
  return (
    <button className={cx('profile-row', selected && 'selected')} onClick={onSelect}>
      <span className={`sync-dot sync-${profile.sync_status}`} />
      <div>
        <strong>{profile.display_name}</strong>
        <small>{profile.name} | {profile.category_label || 'uncategorized'} | {profile.squads.join(', ') || 'no squad'}</small>
      </div>
      <b>{profile.sync_status.replace('_', ' ')}</b>
    </button>
  );
}

function Inspector({ profile, control, onAutonomy }: { profile?: AgentProfile; control?: ControlPlanePayload; onAutonomy: (mode: string) => void }) {
  if (!profile) {
    return (
      <section className="panel inspector empty-panel">
        <Network size={22} />
        <h2>Pick an agent profile</h2>
        <p>Unified profiles merge Daedalus roles with Claude Code subagents and Codex handoff rules.</p>
      </section>
    );
  }
  const autonomyModes = ['manual', 'semi_auto', 'autonomous'];
  return (
    <section className="panel inspector">
      <div className="panel-head">
        <span className={`sync-dot sync-${profile.sync_status}`} />
        <div>
          <h2>{profile.display_name}</h2>
          <p>{profile.name} | {profile.sync_status.replace('_', ' ')}</p>
        </div>
      </div>
      <div className="field-grid">
        <div><label>Category</label><strong>{profile.category_label || 'none'}</strong></div>
        <div><label>Squads</label><strong>{profile.squads.join(', ') || 'none'}</strong></div>
        <div><label>Active</label><strong>{profile.active ? 'yes' : 'no'}</strong></div>
        <div><label>Ownership</label><strong>{profile.ownership.join(', ') || 'none'}</strong></div>
      </div>
      <div className="section-title">Agent autonomy</div>
      <div className="segmented">
        {autonomyModes.map((mode) => (
          <button key={mode} onClick={() => onAutonomy(mode)} className={profile.autonomy.read_files?.project_default === mode ? 'active' : ''}>{mode}</button>
        ))}
      </div>
      <div className="section-title">Capabilities</div>
      <div className="cap-list">
        {profile.capabilities.map((cap) => {
          const policy = profile.autonomy[cap] || {};
          const gate = (control?.capability_gates || []).find((g) => g.id === cap);
          return (
            <div key={cap} className="cap-row">
              <span>{asText(gate?.label, cap)}</span>
              <b className={asText(policy.requires_confirmation) === 'true' ? 'needs-confirm' : ''}>{asText(policy.mode, 'manual')}</b>
            </div>
          );
        })}
      </div>
      <div className="section-title">Claude Code</div>
      <pre>{profile.claude ? JSON.stringify(profile.claude, null, 2) : 'No Claude subagent profile yet.'}</pre>
    </section>
  );
}

function IkarusPanel({ project, onApplied }: { project: string; onApplied: () => void }) {
  const [message, setMessage] = useState('Build a clean app-project agent network with Claude, Codex, Ikarus, QA, UI, API and memory roles.');
  const [reply, setReply] = useState<IkarusChatPayload | null>(null);
  const [busy, setBusy] = useState(false);

  async function send(apply = false) {
    if (!message.trim()) return;
    setBusy(true);
    try {
      const result = await chatIkarus(project, message, apply);
      setReply(result);
      if (apply) onApplied();
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel ikarus-panel">
      <div className="panel-head">
        <Sparkles size={18} />
        <div>
          <h2>Ikarus Architect</h2>
          <p>Drafts agent networks. Apply only after confirmation.</p>
        </div>
      </div>
      <textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={5} />
      <div className="action-row">
        <button onClick={() => send(false)} disabled={busy}><Send size={14} /> Draft</button>
        <button className="primary" onClick={() => send(true)} disabled={busy || !reply?.draft}><Check size={14} /> Apply draft</button>
      </div>
      {reply && (
        <div className="draft-box">
          <strong>{reply.assistant}</strong>
          <div className="draft-stats">
            <span>{reply.draft?.roles.length || 0} Daedalus roles</span>
            <span>{reply.draft?.subagents.length || 0} Claude subagents</span>
          </div>
          {reply.draft && <pre>{JSON.stringify(reply.draft, null, 2)}</pre>}
        </div>
      )}
    </section>
  );
}

function RuntimeCenter({ runtimes }: { runtimes: RuntimeRow[] }) {
  const [tests, setTests] = useState<Record<string, RuntimeTestPayload['test']>>({});
  const [busy, setBusy] = useState('');

  async function runTest(id: string) {
    setBusy(id);
    try {
      const result = await testRuntime(id);
      setTests((prev) => ({ ...prev, [id]: result.test }));
    } finally {
      setBusy('');
    }
  }

  return (
    <section className="panel feature-panel">
      <div className="panel-head">
        <KeyRound size={18} />
        <div><h2>Provider Runtime Registry</h2><p>CLI-first today, API-ready later. The app never talks to random subprocesses directly.</p></div>
      </div>
      <div className="runtime-table">
        {runtimes.map((runtime) => (
          <div className="runtime-row" key={runtime.id}>
            <div>
              <strong>{runtime.label}</strong>
              <small>{runtime.id} | {runtime.mode} | {runtime.auth_status}</small>
              <p>{runtime.notes}</p>
            </div>
            <div className="runtime-detail">
              <span className={runtime.available ? 'ok' : 'warn'}>{runtime.available ? 'available' : 'unavailable'}</span>
              <code>{runtime.command_path || runtime.endpoint || 'no path'}</code>
              <small>{runtime.version || runtime.last_error || runtime.selected_model}</small>
            </div>
            <button onClick={() => runTest(runtime.id)} disabled={busy === runtime.id}>{busy === runtime.id ? 'Testing...' : 'Test'}</button>
            {tests[runtime.id] && (
              <div className={`test-result ${tests[runtime.id].ok ? 'ok' : 'warn'}`}>
                {tests[runtime.id].ok ? 'OK' : 'Check failed'}: {tests[runtime.id].detail}
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

export default function App() {
  const queryProject = new URLSearchParams(location.search).get('project') || '';
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [project, setProject] = useState(queryProject);
  const [dashboard, setDashboard] = useState<DashboardPayload | undefined>();
  const [hierarchy, setHierarchy] = useState<HierarchyPayload | undefined>();
  const [control, setControl] = useState<ControlPlanePayload | undefined>();
  const [runtimes, setRuntimes] = useState<RuntimeRow[]>([]);
  const [bootstrap, setBootstrap] = useState<BootstrapPayload | undefined>();
  const [selectedName, setSelectedName] = useState('');
  const [view, setView] = useState<'network' | 'claude' | 'codex' | 'providers' | 'queue'>('network');
  const [objective, setObjective] = useState('');
  const [lane, setLane] = useState('local_only');
  const [error, setError] = useState('');
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  const selectedProfile = useMemo(
    () => (control?.profiles || []).find((p) => p.name === selectedName) || control?.profiles?.[0],
    [control, selectedName]
  );

  const refresh = useCallback(async (nextProject = project) => {
    setError('');
    try {
      const projectPayload = await getProjects();
      setProjects(projectPayload.projects);
      const chosen = nextProject || queryProject || projectPayload.projects[0]?.name || '';
      if (!chosen) return;
      setProject(chosen);
      const [dash, graph, plane, runtimePayload, bootstrapPayload] = await Promise.all([
        getDashboard(chosen),
        getHierarchy(chosen),
        getControlPlane(chosen),
        getRuntimeStatus(),
        getClaudeBootstrap(chosen)
      ]);
      setDashboard(dash);
      setHierarchy(graph);
      setControl(plane);
      setRuntimes(runtimePayload.runtimes);
      setBootstrap(bootstrapPayload);
      setNodes(graphNodes(graph.nodes, plane.profiles));
      setEdges(graphEdges(graph.edges));
      if (!selectedName && plane.profiles[0]) setSelectedName(plane.profiles[0].name);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [project, queryProject, selectedName, setEdges, setNodes]);

  useEffect(() => { refresh(); }, []);

  const selectedProject = projects.find((p) => p.name === project);

  async function submitTask() {
    if (!objective.trim()) return;
    await queueTask(project, objective.trim(), lane);
    setObjective('');
    refresh(project);
  }

  async function setAgentAutonomy(mode: string) {
    if (!selectedProfile || !control) return;
    const agents = { ...((control.autonomy.agents as Record<string, string>) || {}), [selectedProfile.name]: mode };
    const updated = await updateAutonomy(project, { agents });
    setControl(updated);
  }

  const queue = dashboard?.queue as any;

  return (
    <main className="studio-shell">
      <aside className="sidebar">
        <div className="brand"><Bot size={20} /><strong>Daedalus</strong><span>Agent Network Studio</span></div>
        <label>Project</label>
        <select value={project} onChange={(e) => refresh(e.target.value)}>
          {projects.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
        </select>
        <nav>
          <button className={view === 'network' ? 'active' : ''} onClick={() => setView('network')}><Network size={15} /> Agent Network</button>
          <button className={view === 'claude' ? 'active' : ''} onClick={() => setView('claude')}><BrainCircuit size={15} /> Claude Code</button>
          <button className={view === 'codex' ? 'active' : ''} onClick={() => setView('codex')}><Terminal size={15} /> Codex</button>
          <button className={view === 'providers' ? 'active' : ''} onClick={() => setView('providers')}><KeyRound size={15} /> Providers</button>
          <button className={view === 'queue' ? 'active' : ''} onClick={() => setView('queue')}><GitBranch size={15} /> Mission Feed</button>
        </nav>
        <div className="runtime-list">
          {(control?.runtimes || []).map((runtime) => <RuntimeCard key={String(runtime.id)} runtime={runtime} />)}
        </div>
      </aside>

      <section className="main-stage">
        <header className="studio-header">
          <div>
            <h1>{view === 'network' ? 'Agent Network' : view === 'claude' ? 'Claude Code Control' : view === 'codex' ? 'Codex Runtime' : view === 'providers' ? 'Provider Center' : 'Mission Feed'}</h1>
            <p>{selectedProject?.repo_root || 'No project selected'}</p>
          </div>
          <button onClick={() => refresh(project)}><RefreshCw size={15} /> Refresh</button>
        </header>

        {error && <div className="error-banner">{error}</div>}

        {view === 'network' && (
          <div className="network-layout">
            <section className="panel profiles-panel">
              <div className="panel-head">
                <Users size={18} />
                <div><h2>Unified Agent Profiles</h2><p>Daedalus roles + Claude subagents + Codex handoff</p></div>
              </div>
              <div className="profile-list">
                {(control?.profiles || []).map((profile) => (
                  <ProfileRow key={profile.name} profile={profile} selected={selectedProfile?.name === profile.name} onSelect={() => setSelectedName(profile.name)} />
                ))}
              </div>
            </section>
            <section className="panel map-panel">
              <div className="panel-head compact">
                <Network size={18} />
                <div><h2>Network Map</h2><p>Useful map, not the whole product.</p></div>
              </div>
              <div className="flow-wrap">
                <ReactFlow
                  nodes={nodes}
                  edges={edges}
                  nodeTypes={nodeTypes}
                  onNodesChange={onNodesChange}
                  onEdgesChange={onEdgesChange}
                  onNodeClick={(_, node) => node.id.startsWith('agent:') && setSelectedName(node.id.slice('agent:'.length))}
                  fitView
                  minZoom={0.35}
                  maxZoom={1.4}
                >
                  <Background gap={24} size={1} />
                  <MiniMap pannable zoomable />
                  <Controls />
                </ReactFlow>
              </div>
            </section>
          </div>
        )}

        {view === 'claude' && (
          <section className="panel feature-panel">
            <div className="panel-head"><BrainCircuit size={18} /><div><h2>Claude Code Surface</h2><p>Subagents, permissions, MCP, hooks and runtime features.</p></div></div>
            <div className="feature-grid">
              <Info title="Subagents" value={`${asText(control?.claude?.subagent_count, '0')} detected`} icon={<Users size={18} />} />
              <Info title="Permission mode" value={asText((control?.claude?.settings as any)?.defaultMode, 'not set')} icon={<ShieldCheck size={18} />} />
              <Info title="MCP servers" value={`${(((control?.claude?.mcp as any)?.servers || []) as unknown[]).length} configured`} icon={<Cpu size={18} />} />
              <Info title="Hooks" value={`${Object.keys(((control?.claude?.settings as any)?.hooks || {}) as Record<string, unknown>).length} groups`} icon={<GitBranch size={18} />} />
            </div>
            <pre>{JSON.stringify(control?.claude || {}, null, 2)}</pre>
            <div className="bootstrap-box">
              <div className="panel-head compact"><MessageSquare size={16} /><div><h2>Claude Session Bootstrap</h2><p>Paste this at the start of a Claude Code session so it uses Daedalus/Ikarus/Ollama correctly.</p></div></div>
              <pre>{bootstrap?.prompt || 'Loading bootstrap prompt...'}</pre>
            </div>
          </section>
        )}

        {view === 'codex' && (
          <section className="panel feature-panel">
            <div className="panel-head"><Terminal size={18} /><div><h2>Codex Runtime</h2><p>Codex participates through AGENTS.md and the Daedalus file bus.</p></div></div>
            <div className="feature-grid">
              <Info title="AGENTS.md" value={(control?.codex?.agents_md as any)?.exists ? 'present' : 'missing'} icon={<FileText size={18} />} />
              <Info title="Managed block" value={(control?.codex?.agents_md as any)?.managed ? 'enforced' : 'not enforced'} icon={<Check size={18} />} />
              <Info title="Communication" value={asText((control?.codex?.runtime as any)?.communication, 'file_bus')} icon={<MessageSquare size={18} />} />
              <Info title="Queue source" value={asText((control?.codex?.runtime as any)?.queue_source, 'codex')} icon={<GitBranch size={18} />} />
            </div>
            <pre>{JSON.stringify(control?.codex || {}, null, 2)}</pre>
          </section>
        )}

        {view === 'providers' && <RuntimeCenter runtimes={runtimes} />}

        {view === 'queue' && (
          <section className="panel feature-panel">
            <div className="panel-head"><GitBranch size={18} /><div><h2>Mission Feed</h2><p>All runtimes communicate through queue, reports and memory.</p></div></div>
            <form className="queue-form" onSubmit={(e) => { e.preventDefault(); submitTask(); }}>
              <select value={lane} onChange={(e) => setLane(e.target.value)}>
                <option value="local_only">local_only</option>
                <option value="local">local</option>
                <option value="auto">auto</option>
                <option value="claude">claude</option>
              </select>
              <input value={objective} onChange={(e) => setObjective(e.target.value)} placeholder="Describe work for the app project..." />
              <button className="primary" type="submit"><Play size={14} /> Queue</button>
            </form>
            <div className="feed-list">
              {([...(queue?.pending || []), ...(queue?.reports || [])] as any[]).slice(0, 20).map((item) => (
                <div className="feed-row" key={`${item.kind}-${item.name}`}>
                  <b>{item.kind}</b>
                  <span>{item.name}</span>
                  <small>{item.lane || 'n/a'} | {item.status || 'queued'}</small>
                </div>
              ))}
            </div>
          </section>
        )}
      </section>

      <aside className="right-rail">
        <Inspector profile={selectedProfile} control={control} onAutonomy={setAgentAutonomy} />
        <IkarusPanel project={project} onApplied={() => refresh(project)} />
      </aside>
    </main>
  );
}

function Info({ title, value, icon }: { title: string; value: string; icon: React.ReactNode }) {
  return (
    <div className="info-card">
      {icon}
      <span>{title}</span>
      <strong>{value}</strong>
      <ChevronRight size={14} />
    </div>
  );
}
