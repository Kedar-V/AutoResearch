import type {
  EvaluationRecord,
  GitHubStatus,
  HandoffRead,
  HypothesisRecord,
  ProjectCreatePayload,
  ProjectRead,
  ProjectRestartRead,
  RunRead,
  TrialRecord,
  WorkflowDefinition,
} from './types'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    })
  } catch {
    throw new Error(`Could not reach API at ${API_URL}. Is the backend running?`)
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    const detail = payload?.detail ?? `${response.status} ${response.statusText}`
    throw new Error(`API error: ${detail}`)
  }
  return response.json() as Promise<T>
}

export function getWorkflow(workflowId: string) {
  return request<WorkflowDefinition>(`/api/workflows/${workflowId}`)
}

export function saveWorkflow(definition: WorkflowDefinition) {
  return request<WorkflowDefinition>(`/api/workflows/${definition.id}`, {
    method: 'PUT',
    body: JSON.stringify(definition),
  })
}

export function listRuns() {
  return request<RunRead[]>('/api/runs')
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

export function cancelRun(runId: string) {
  return request<RunRead>(`/api/runs/${runId}/cancel`, { method: 'POST' })
}

export function pauseRun(runId: string) {
  return request<RunRead>(`/api/runs/${runId}/pause`, { method: 'POST' })
}

export function resumeRun(runId: string) {
  return request<RunRead>(`/api/runs/${runId}/resume`, { method: 'POST' })
}

export function listProjects() {
  return request<ProjectRead[]>('/api/projects')
}

export function getActiveProject() {
  return request<ProjectRead | null>('/api/projects/active')
}

export function createProject(payload: ProjectCreatePayload) {
  return request<ProjectRead>('/api/projects', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function getGitHubStatus() {
  return request<GitHubStatus>('/api/github/status')
}

export function activateProject(projectId: string) {
  return request<ProjectRead>(`/api/projects/${projectId}/activate`, {
    method: 'POST',
  })
}

export function restartProject(projectId: string) {
  return request<ProjectRestartRead>(`/api/projects/${projectId}/restart`, {
    method: 'POST',
  })
}

export function getHandoff(projectId: string) {
  return request<HandoffRead>(`/api/projects/${projectId}/handoff`)
}

export function listHypotheses(projectId: string) {
  return request<HypothesisRecord[]>(`/api/projects/${projectId}/hypotheses`)
}

export function listTrials(projectId: string) {
  return request<TrialRecord[]>(`/api/projects/${projectId}/trials`)
}

export function listEvaluations(projectId: string) {
  return request<EvaluationRecord[]>(`/api/projects/${projectId}/evaluations`)
}

export function getTable(projectId: string, tableName: string) {
  return request<{ table: string; rows: Record<string, unknown>[] }>(
    `/api/projects/${projectId}/tables/${tableName}`,
  )
}

export function getTrialDiff(projectId: string, trialId: string) {
  // trial ids contain slashes (H0001/T001); FastAPI route uses {trial_id:path}
  return request<{ trial_id: string; base_commit: string; candidate_commit: string; diff: string }>(
    `/api/projects/${projectId}/trials/${trialId}/diff`,
  )
}
