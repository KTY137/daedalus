// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-License-Identifier: Apache-2.0

import { useEffect } from 'react';
import '@xyflow/react/dist/style.css';
import {
  Background,
  Controls,
  MiniMap,
  Position,
  ReactFlow,
  useEdgesState,
  useNodesState
} from '@xyflow/react';
import type { Edge, Node } from '@xyflow/react';
import { Network, RefreshCw, Users } from 'lucide-react';
import { cx } from './glass';
import type { AgentProfile, HierarchyNode, HierarchyPayload, NodeKind } from '../types';

interface NetworkSheetProps {
  hierarchy?: HierarchyPayload;
  profiles: AgentProfile[];
  selectedName: string;
  loading: boolean;
  error: string;
  onSelect: (name: string) => void;
  onRefresh: () => void;
}

const kindRank: Record<NodeKind, number> = {
  project: 0,
  squad: 1,
  category: 1,
  agent: 2,
  model: 3,
  capability: 3,
  path: 3
};

const kindLabel: Record<NodeKind, string> = {
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

function StudioNode({ data }: { data: any }) {
  return (
    <div className={cx('studio-node', `node-${data.kind}`, data.active === false && 'muted-node')}>
      <div className="node-meta">
        <span>{kindLabel[data.kind as NodeKind] || data.kind}</span>
        {data.sync && <b className={`sync sync-${data.sync}`}>{data.sync}</b>}
      </div>
      <strong>{data.label}</strong>
      {data.subtitle && <small>{data.subtitle}</small>}
    </div>
  );
}

const nodeTypes = { studio: StudioNode };

function graphNodes(items: HierarchyNode[], profiles: AgentProfile[]): Node[] {
  const profileByName = new Map(profiles.map((profile) => [profile.name, profile]));
  const groups = new Map<number, HierarchyNode[]>();
  items
    .filter((item) => item.type !== 'path')
    .forEach((item) => {
      const rank = kindRank[item.type] ?? 2;
      groups.set(rank, [...(groups.get(rank) || []), item]);
    });

  const result: Node[] = [];
  [...groups.entries()].forEach(([rank, group]) => {
    const spacing = rank === 2 ? 138 : 170;
    const startY = -((group.length - 1) * spacing) / 2;
    group.forEach((item, index) => {
      const data = item.data || {};
      const agentName = item.id.startsWith('agent:') ? item.id.slice('agent:'.length) : '';
      const profile = profileByName.get(agentName);
      result.push({
        id: item.id,
        type: 'studio',
        position: { x: rank * 260, y: startY + index * spacing },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        data: {
          ...data,
          kind: item.type,
          label: item.label,
          sync: profile?.sync_status,
          active: profile ? profile.active : data.active,
          subtitle: item.type === 'agent'
            ? `${profile?.category_label || asText(data.category, 'uncategorized')} | ${profile?.capabilities.length || 0} caps`
            : item.type === 'category'
              ? `${asText(data.lane)} | ${asText(data.count, '0')} agents`
              : item.type === 'capability'
                ? asText(data.risk)
                : asText(data.repo_root || data.model || data.count)
        }
      });
    });
  });
  return result;
}

function graphEdges(items: HierarchyPayload['edges']): Edge[] {
  return items
    .filter((item) => !item.target.startsWith('path:'))
    .map((item) => ({
      id: item.id,
      source: item.source,
      target: item.target,
      type: 'smoothstep',
      animated: item.type === 'can_use' || item.type === 'uses_model',
      className: `edge-${item.type}`
    }));
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

export function NetworkSheet({ hierarchy, profiles, selectedName, loading, error, onSelect, onRefresh }: NetworkSheetProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  useEffect(() => {
    setNodes(graphNodes(hierarchy?.nodes || [], profiles));
    setEdges(graphEdges(hierarchy?.edges || []));
  }, [hierarchy, profiles, setEdges, setNodes]);

  return (
    <div className="network-layout">
      <section className="panel profiles-panel">
        <div className="panel-head">
          <Users size={18} />
          <div><h2>Unified Agent Profiles</h2><p>Daedalus roles + Claude subagents + Codex handoff</p></div>
        </div>
        <div className="profile-list">
          {profiles.map((profile) => (
            <ProfileRow key={profile.name} profile={profile} selected={selectedName === profile.name} onSelect={() => onSelect(profile.name)} />
          ))}
        </div>
      </section>

      <section className="panel map-panel">
        <div className="panel-head compact">
          <Network size={18} />
          <div><h2>Network Map</h2><p>Loaded on demand to keep chat startup light.</p></div>
          <button type="button" className="iconbtn struct-refresh" onClick={onRefresh} disabled={loading} title="Refresh network" aria-label="Refresh network">
            <RefreshCw size={15} className={loading ? 'spin' : undefined} />
          </button>
        </div>
        <div className="flow-wrap">
          {loading && nodes.length === 0 ? (
            <div className="struct-state" role="status"><RefreshCw size={20} className="spin" /><strong>Loading network</strong></div>
          ) : error && nodes.length === 0 ? (
            <div className="struct-state struct-state-error" role="alert"><Network size={20} /><strong>Network unavailable</strong><span>{error}</span></div>
          ) : (
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onNodeClick={(_, node) => node.id.startsWith('agent:') && onSelect(node.id.slice('agent:'.length))}
              fitView
              minZoom={0.35}
              maxZoom={1.4}
            >
              <Background gap={24} size={1} />
              <MiniMap pannable zoomable />
              <Controls />
            </ReactFlow>
          )}
        </div>
      </section>
    </div>
  );
}
