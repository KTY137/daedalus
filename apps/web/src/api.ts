import type { ApiEnvelope, BootstrapPayload, ControlPlanePayload, DashboardPayload, HierarchyPayload, IkarusChatPayload, ProjectRow, RuntimeStatusPayload, RuntimeTestPayload } from './types';

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init
  });
  const data = await res.json();
  if (!res.ok || data.ok === false) {
    throw new Error(data.error || `Request failed: ${res.status}`);
  }
  return data;
}

export function getProjects() {
  return request<ApiEnvelope & { projects: ProjectRow[] }>('/api/projects');
}

export function getDashboard(project: string) {
  return request<DashboardPayload>(`/api/dashboard?project=${encodeURIComponent(project)}`);
}

export function getHierarchy(project: string) {
  return request<HierarchyPayload>(`/api/projects/${encodeURIComponent(project)}/hierarchy`);
}

export function getControlPlane(project: string) {
  return request<ControlPlanePayload>(`/api/projects/${encodeURIComponent(project)}/control-plane`);
}

export function getEnvStatus() {
  return request<ApiEnvelope & { env: Record<string, unknown> }>('/api/env/status');
}

export function getProviderStatus() {
  return request<ApiEnvelope & { providers: Array<Record<string, unknown>> }>('/api/providers/status');
}

export function updateAgent(project: string, agent: string, patch: Record<string, unknown>) {
  return request(`/api/projects/${encodeURIComponent(project)}/agents/${encodeURIComponent(agent)}`, {
    method: 'PUT',
    body: JSON.stringify(patch)
  });
}

export function updateCategory(project: string, category: string, patch: Record<string, unknown>) {
  return request(`/api/projects/${encodeURIComponent(project)}/categories/${encodeURIComponent(category)}`, {
    method: 'PUT',
    body: JSON.stringify(patch)
  });
}

export function queueTask(project: string, objective: string, lane: string) {
  return request('/api/queue', {
    method: 'POST',
    body: JSON.stringify({ project, objective, lane, source: 'agent-os', strategy: 'single' })
  });
}

export function chatIkarus(project: string, message: string, apply = false) {
  return request<IkarusChatPayload>('/api/ikarus/chat', {
    method: 'POST',
    body: JSON.stringify({ project, message, apply })
  });
}

export function updateAutonomy(project: string, patch: Record<string, unknown>) {
  return request<ControlPlanePayload>(`/api/projects/${encodeURIComponent(project)}/autonomy`, {
    method: 'PUT',
    body: JSON.stringify(patch)
  });
}

export function getRuntimeStatus() {
  return request<RuntimeStatusPayload>('/api/runtimes/status');
}

export function testRuntime(runtimeId: string) {
  return request<RuntimeTestPayload>(`/api/runtimes/${encodeURIComponent(runtimeId)}/test`, {
    method: 'POST',
    body: JSON.stringify({})
  });
}

export function getClaudeBootstrap(project: string) {
  return request<BootstrapPayload>(`/api/projects/${encodeURIComponent(project)}/bootstrap/claude`);
}
