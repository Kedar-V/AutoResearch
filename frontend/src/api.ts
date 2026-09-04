import type { RunRead, WorkflowDefinition } from './types'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    const detail = payload?.detail ?? `${response.status} ${response.statusText}`
    throw new Error(`API error: ${detail}`)
  }
  return response.json() as Promise<T>
}

export function saveWorkflow(definition: WorkflowDefinition) {
  return request<WorkflowDefinition>(`/api/workflows/${definition.id}`, {
    method: 'PUT',
    body: JSON.stringify(definition),
  })
}

export function createRun(workflowId: string) {
  return request<RunRead>('/api/runs', {
    method: 'POST',
    body: JSON.stringify({ workflow_id: workflowId }),
  })
}

export function getRun(runId: string) {
  return request<RunRead>(`/api/runs/${runId}`)
}
