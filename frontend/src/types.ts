export type ResearchNodeType =
  | 'hypothesis'
  | 'trial'
  | 'script'
  | 'evaluation'
  | 'metric_gate'
  | 'git_decision'

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
}
