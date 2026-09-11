import type { ResearchNodeType } from './types'
import type { WorkflowDefinition, WorkflowEdge, WorkflowNode } from './types'

export const REQUIRED_TYPES = [
  'hypothesis',
  'execution',
  'eval_script',
  'evaluation',
  'metric_gate',
  'git_decision',
] as const

export type RequiredNodeType = (typeof REQUIRED_TYPES)[number]

/** Allowed directed edges by (source_type, target_type). */
export const LEGAL_EDGE_PAIRS: ReadonlyArray<readonly [ResearchNodeType, ResearchNodeType]> = [
  ['hypothesis', 'execution'],
  ['execution', 'eval_script'],
  ['execution', 'evaluation'],
  ['eval_script', 'evaluation'],
  ['evaluation', 'metric_gate'],
  ['metric_gate', 'git_decision'],
  ['execution', 'hypothesis'],
  ['git_decision', 'hypothesis'],
]

const LEGAL_SET = new Set(LEGAL_EDGE_PAIRS.map(([a, b]) => `${a}>${b}`))

export interface CompiledLoop {
  hypothesis: WorkflowNode
  execution: WorkflowNode
  eval_script: WorkflowNode
  evaluation: WorkflowNode
  metric_gate: WorkflowNode
  git_decision: WorkflowNode
  postTrial: WorkflowNode[]
  allowedPaths: string[] | null
  maxHypotheses: number
  maxRetries: number
  hasSelfHeal: boolean
  hasFeedback: boolean
}

export type CompileResult =
  | { ok: true; recipe: CompiledLoop }
  | { ok: false; error: string }

export function isLegalConnection(
  sourceType: ResearchNodeType,
  targetType: ResearchNodeType,
): boolean {
  return LEGAL_SET.has(`${sourceType}>${targetType}`)
}

export function isRequiredType(type: ResearchNodeType): boolean {
  return (REQUIRED_TYPES as readonly string[]).includes(type)
}

function normalizeType(node: WorkflowNode): ResearchNodeType {
  if (node.type === 'script' && Array.isArray(node.config.command)) return 'execution'
  if (node.type === 'evaluation' && Array.isArray(node.config.command)) return 'eval_script'
  return node.type
}

function intConfig(node: WorkflowNode, key: string, fallback: number): number {
  const raw = Number(node.config[key])
  return Number.isFinite(raw) && raw > 0 ? Math.floor(raw) : fallback
}

function allowedPathsFromWorkflow(definition: WorkflowDefinition): string[] | null {
  for (const node of definition.nodes) {
    if (normalizeType(node) !== 'execution') continue
    const paths = node.config.allowed_paths
    if (Array.isArray(paths) && paths.every((path) => typeof path === 'string')) {
      return paths
    }
  }
  for (const node of definition.nodes) {
    if (node.type !== 'script') continue
    if (Array.isArray(node.config.command)) continue
    const paths = node.config.allowed_paths
    if (Array.isArray(paths) && paths.every((path) => typeof path === 'string')) {
      return paths
    }
  }
  return null
}

function groupByType(definition: WorkflowDefinition): Map<ResearchNodeType, WorkflowNode[]> {
  const grouped = new Map<ResearchNodeType, WorkflowNode[]>()
  for (const node of definition.nodes) {
    const type = normalizeType(node)
    const list = grouped.get(type) ?? []
    list.push({ ...node, type })
    grouped.set(type, list)
  }
  return grouped
}

/** Compile a workflow into a validated research recipe (mirrors backend). */
export function compileRecipe(definition: WorkflowDefinition): CompileResult {
  const byType = groupByType(definition)
  const nodesById = new Map(
    definition.nodes.map((node) => [node.id, { ...node, type: normalizeType(node) }]),
  )

  for (const nodeType of REQUIRED_TYPES) {
    const matches = byType.get(nodeType) ?? []
    if (matches.length === 0) {
      return { ok: false, error: `recipe requires exactly one ${nodeType} node` }
    }
    if (matches.length > 1) {
      return {
        ok: false,
        error: `recipe allows only one ${nodeType} node; found ${matches.length}`,
      }
    }
  }

  for (const node of definition.nodes) {
    const type = normalizeType(node)
    if (isRequiredType(type)) continue
    if (type === 'database' || type === 'trial') continue
    if (type === 'script') {
      if (Array.isArray(node.config.command)) {
        return {
          ok: false,
          error: 'script nodes with a command must be typed as execution',
        }
      }
      continue
    }
    return { ok: false, error: `unsupported node type '${type}' on the research recipe` }
  }

  const edgesByPair = new Map<string, WorkflowEdge[]>()
  for (const edge of definition.edges) {
    const source = nodesById.get(edge.source)
    const target = nodesById.get(edge.target)
    if (!source || !target) {
      return { ok: false, error: `edge ${edge.id} references an unknown node` }
    }
    const key = `${source.type}>${target.type}`
    if (!LEGAL_SET.has(key)) {
      return {
        ok: false,
        error: `illegal edge ${source.type} → ${target.type} (edge ${edge.id}); not part of the research recipe grammar`,
      }
    }
    const list = edgesByPair.get(key) ?? []
    list.push(edge)
    edgesByPair.set(key, list)
  }

  const requireEdge = (sourceType: string, targetType: string): string | null => {
    if ((edgesByPair.get(`${sourceType}>${targetType}`) ?? []).length === 0) {
      return `missing required edge ${sourceType} → ${targetType}`
    }
    return null
  }

  for (const [sourceType, targetType] of [
    ['hypothesis', 'execution'],
    ['eval_script', 'evaluation'],
    ['evaluation', 'metric_gate'],
    ['metric_gate', 'git_decision'],
  ] as const) {
    const missing = requireEdge(sourceType, targetType)
    if (missing) return { ok: false, error: missing }
  }

  const hasExecToEval = (edgesByPair.get('execution>evaluation') ?? []).length > 0
  const hasExecToEvalScript = (edgesByPair.get('execution>eval_script') ?? []).length > 0
  if (!hasExecToEval && !hasExecToEvalScript) {
    return {
      ok: false,
      error:
        'execution must connect to eval_script or evaluation (metrics path after a successful trial)',
    }
  }

  const hypothesis = byType.get('hypothesis')![0]
  const execution = byType.get('execution')![0]
  const evalScript = byType.get('eval_script')![0]
  const evaluation = byType.get('evaluation')![0]
  const metricGate = byType.get('metric_gate')![0]
  const gitDecision = byType.get('git_decision')![0]

  const postNodes = new Map([
    [evalScript.id, evalScript],
    [evaluation.id, evaluation],
    [metricGate.id, metricGate],
    [gitDecision.id, gitDecision],
  ])
  const indegree = new Map([...postNodes.keys()].map((id) => [id, 0]))
  const outgoing = new Map<string, string[]>()
  for (const edge of definition.edges) {
    if (!postNodes.has(edge.source) || !postNodes.has(edge.target)) continue
    outgoing.set(edge.source, [...(outgoing.get(edge.source) ?? []), edge.target])
    indegree.set(edge.target, (indegree.get(edge.target) ?? 0) + 1)
  }

  let ready = [...indegree.entries()]
    .filter(([, degree]) => degree === 0)
    .map(([id]) => id)
    .sort()
  const orderedIds: string[] = []
  while (ready.length) {
    const nodeId = ready.shift()!
    orderedIds.push(nodeId)
    for (const target of outgoing.get(nodeId) ?? []) {
      const next = (indegree.get(target) ?? 0) - 1
      indegree.set(target, next)
      if (next === 0) ready = [...ready, target].sort()
    }
  }

  if (orderedIds.length !== postNodes.size) {
    return {
      ok: false,
      error:
        'eval_script → evaluation → metric_gate → git_decision path has a cycle or is disconnected',
    }
  }

  const expected = [evalScript.id, evaluation.id, metricGate.id, gitDecision.id]
  if (orderedIds.join() !== expected.join()) {
    return {
      ok: false,
      error: `post-trial spine must be eval_script → evaluation → metric_gate → git_decision; compiled order was ${orderedIds
        .map((id) => postNodes.get(id)!.type)
        .join(' → ')}`,
    }
  }

  return {
    ok: true,
    recipe: {
      hypothesis,
      execution,
      eval_script: evalScript,
      evaluation,
      metric_gate: metricGate,
      git_decision: gitDecision,
      postTrial: orderedIds.map((id) => postNodes.get(id)!),
      allowedPaths: allowedPathsFromWorkflow(definition),
      maxHypotheses: intConfig(hypothesis, 'max_hypotheses', 5),
      maxRetries: intConfig(hypothesis, 'max_retries', 3),
      hasSelfHeal: (edgesByPair.get('execution>hypothesis') ?? []).length > 0,
      hasFeedback: (edgesByPair.get('git_decision>hypothesis') ?? []).length > 0,
    },
  }
}
