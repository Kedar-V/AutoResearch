import { Beaker, Braces, GitBranch, GitMerge, Scale, TestTubeDiagonal } from 'lucide-react'
import type { ReactNode } from 'react'

import type { ResearchNodeType } from './types'

export interface AutoResearchNodeData extends Record<string, unknown> {
  nodeType: ResearchNodeType
  name: string
  config: Record<string, unknown>
}

export interface CatalogItem {
  type: ResearchNodeType
  label: string
  description: string
  color: string
  icon: ReactNode
  defaultConfig: Record<string, unknown>
}

export const NODE_CATALOG: CatalogItem[] = [
  { type: 'hypothesis', label: 'Hypothesis', description: 'Create an idea branch', color: '#a78bfa', icon: <Beaker size={17} />, defaultConfig: { title: 'New hypothesis', description: '' } },
  { type: 'trial', label: 'Trial', description: 'Create branch + worktree', color: '#60a5fa', icon: <GitBranch size={17} />, defaultConfig: { number: 1 } },
  { type: 'script', label: 'Script', description: 'Run trusted local code', color: '#f59e0b', icon: <Braces size={17} />, defaultConfig: { command: ['python', 'train.py'], timeout_seconds: 300, commit_message: 'trial: apply candidate' } },
  { type: 'evaluation', label: 'Evaluation', description: 'Emit structured metrics', color: '#22d3ee', icon: <TestTubeDiagonal size={17} />, defaultConfig: { command: ['python', 'eval.py'], timeout_seconds: 300, protected_paths: ['eval.py', 'tests', '.research'] } },
  { type: 'metric_gate', label: 'Metric gate', description: 'Compare with champion', color: '#36d399', icon: <Scale size={17} />, defaultConfig: { metric: 'score', direction: 'maximize', baseline: 0, min_delta: 0 } },
  { type: 'git_decision', label: 'Git decision', description: 'Accept, reject, or merge', color: '#fb7185', icon: <GitMerge size={17} />, defaultConfig: {} },
]

export function catalogItem(type: ResearchNodeType): CatalogItem {
  const item = NODE_CATALOG.find((candidate) => candidate.type === type)
  if (!item) throw new Error(`Unknown node type: ${type}`)
  return item
}
