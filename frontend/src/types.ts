export type ResearchNodeType =
  | 'hypothesis'
  | 'trial'
  | 'script'
  | 'execution'
  | 'eval_script'
  | 'evaluation'
  | 'metric_gate'
  | 'git_decision'
  | 'database'

export interface Position { x: number; y: number }

export interface WorkflowNode {
  id: string
  type: ResearchNodeType
  name: string
  position: Position
  config: Record<string, unknown>
}

export interface WorkflowEdge {
  id: string
  source: string
  target: string
  source_port: string
  target_port: string
}

export interface WorkflowDefinition {
  schema_version: '1'
  id: string
  name: string
  description: string
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
}

export interface NodeRunRead {
  id: string
  node_id: string
  node_type: string
  status: string
  output: Record<string, unknown>
  stdout: string
  stderr: string
  started_at: string
  finished_at: string | null
}

export interface RunRead {
  id: string
  workflow_id: string
  status: string
  hypothesis_id: string | null
  trial_id: string | null
  branch: string | null
  error: string | null
  context: Record<string, unknown>
  created_at: string
  started_at: string | null
  finished_at: string | null
  node_runs: NodeRunRead[]
  project_id?: string | null
}

export interface HypothesisRecord {
  id: string
  title: string
  description: string
  branch: string
  base_commit: string
  status: string
  what_worked: string
  what_did_not: string
  metrics: Record<string, number>
  created_at: string
}

export interface TrialRecord {
  id: string
  hypothesis_id: string
  branch: string
  candidate_commit: string | null
  outcome: string
  error: string
  next_step: string
  what_changed: string
  metrics: Record<string, number>
  created_at: string
}

export interface ProjectRead {
  id: string
  name: string
  github_url: string | null
  local_path: string
  pg_schema: string
  status: string
  created_at: string
}

export interface EvaluationRecord {
  schema_version: '2'
  evaluation_id: string
  trial_id: string
  hypothesis_id: string
  run_id: string
  status: 'passed' | 'failed' | 'invalid'
  metrics: Record<string, number>
  champion_metrics: Record<string, number>
  deltas: Record<string, number>
  primary_metric: string
  direction: 'minimize' | 'maximize'
  summary: string
  signals: {
    improved: string[]
    regressed: string[]
    unchanged: string[]
  }
  recommendation: 'accept' | 'reject' | 'retry'
  rationale: string
  risks: string
  evidence: {
    candidate_commit: string
    evaluator_commit: string
    duration_seconds?: number | null
    stdout_excerpt?: string | null
  }
  model: string
  system_prompt_hash: string
  agent_trace_id?: string
  prompt_version?: string
  observability_backend?: string
  explainability?: Record<string, unknown>
  explainability_schema_hash?: string
  created_at: string
}

export interface HandoffRead {
  project: ProjectRead
  summary: string
  champion_metrics: Record<string, number>
  hypotheses: HypothesisRecord[]
  trials: TrialRecord[]
}
