import {
  Beaker,
  Braces,
  Database,
  GitBranch,
  GitMerge,
  Play,
  Scale,
  TestTubeDiagonal,
} from 'lucide-react'
import type { ReactNode } from 'react'

import type { ResearchNodeType } from './types'

/** Default model for every canvas node config. */
export const DEFAULT_MODEL = 'composer-2.5'

export interface AutoResearchNodeData extends Record<string, unknown> {
  nodeType: ResearchNodeType
  name: string
  config: Record<string, unknown>
  badge?: string | number
  readOnly?: boolean
  /** Live run status for this canvas node (`running` highlighted). */
  liveStatus?: string
  executing?: boolean
}

export interface CatalogItem {
  type: ResearchNodeType
  label: string
  description: string
  color: string
  icon: ReactNode
  defaultConfig: Record<string, unknown>
  executable?: boolean
}

export const NODE_CATALOG: CatalogItem[] = [
  {
    type: 'hypothesis',
    label: 'Hypothesis',
    description: 'Propose the next idea from inbound context',
    color: '#a78bfa',
    icon: <Beaker size={17} />,
    defaultConfig: {
      title: 'New hypothesis',
      description: '',
      system_prompt: `You are the research agent for this repository.

Produce a concrete next experiment — not a vague goal like "improve the metric".

Your hypothesis must specify:
1. Objective — which metric moves, in which direction, and why this attempt should beat the champion.
2. Exact edits — files you will change (only allowed paths), functions/hyperparameters/logic touched, and the intended behavioral effect of each edit.
3. Rationale — how this differs from the last N hypotheses; explicitly reuse what worked and avoid what failed.
4. Risks — what could break training/eval, and how you will detect failure quickly.
5. Success check — the numeric gate condition that counts as acceptance.

Never restate the research brief alone. Never propose "try something" without naming the change.
Prefer one focused change over many simultaneous edits unless history shows a compound change is required.`,
      model: DEFAULT_MODEL,
      max_retries: 3,
      max_hypotheses: 5,
      history_window: 10,
      use_planner: false,
    },
  },
  {
    type: 'trial',
    label: 'Trial',
    description: 'Retry created by a hypothesis',
    color: '#60a5fa',
    icon: <GitBranch size={17} />,
    defaultConfig: { model: DEFAULT_MODEL },
    executable: false,
  },
  {
    type: 'script',
    label: 'Script',
    description: 'Optional allow-list of editable paths',
    color: '#f59e0b',
    icon: <Braces size={17} />,
    defaultConfig: { allowed_paths: ['score.txt', 'train.py'], model: DEFAULT_MODEL },
  },
  {
    type: 'execution',
    label: 'Execution',
    description: 'Apply edits and run training in a trial worktree',
    color: '#38bdf8',
    icon: <Play size={17} />,
    defaultConfig: {
      command: ['python', 'train.py'],
      timeout_seconds: 300,
      commit_message: 'trial: apply candidate',
      use_agent: false,
      model: DEFAULT_MODEL,
    },
  },
  {
    type: 'eval_script',
    label: 'Eval script',
    description: 'Trusted evaluator that reads training metrics JSON',
    color: '#22d3ee',
    icon: <TestTubeDiagonal size={17} />,
    defaultConfig: {
      command: ['python', 'eval.py'],
      timeout_seconds: 300,
      protected_paths: ['eval.py', 'tests', '.research'],
      model: DEFAULT_MODEL,
    },
  },
  {
    type: 'evaluation',
    label: 'Evaluation agent',
    description: 'Interpret metrics from eval script + execution',
    color: '#67e8f9',
    icon: <TestTubeDiagonal size={17} />,
    defaultConfig: {
      system_prompt:
        'Judge whether the candidate truly improved the champion metric. ' +
        'Explain the result, recommend accept/reject/retry, and call out risks or noise.',
      model: DEFAULT_MODEL,
      use_agent: true,
      explainability_schema: {
        type: 'object',
        additionalProperties: false,
        required: ['confidence', 'attribution'],
        properties: {
          confidence: { type: 'number', minimum: 0, maximum: 1 },
          attribution: { type: 'string' },
          failure_modes: { type: 'array', items: { type: 'string' } },
        },
      },
    },
  },
  {
    type: 'metric_gate',
    label: 'Metric gate',
    description: 'Compare with champion',
    color: '#36d399',
    icon: <Scale size={17} />,
    defaultConfig: {
      metric: 'score',
      direction: 'minimize',
      baseline: 5,
      min_delta: 0.01,
      model: DEFAULT_MODEL,
    },
  },
  {
    type: 'git_decision',
    label: 'Git decision',
    description: 'Accept, reject, or merge',
    color: '#fb7185',
    icon: <GitMerge size={17} />,
    defaultConfig: { model: DEFAULT_MODEL },
  },
  {
    type: 'database',
    label: 'DB',
    description: 'Browse project Postgres tables',
    color: '#94a3b8',
    icon: <Database size={17} />,
    defaultConfig: { model: DEFAULT_MODEL },
    executable: false,
  },
]

export const PALETTE_CATALOG = NODE_CATALOG.filter((item) => item.type !== 'trial')

export function catalogItem(type: ResearchNodeType): CatalogItem {
  const item = NODE_CATALOG.find((candidate) => candidate.type === type)
  if (!item) throw new Error(`Unknown node type: ${type}`)
  return item
}

export function isExecutableType(type: ResearchNodeType): boolean {
  return type !== 'trial' && type !== 'database'
}
