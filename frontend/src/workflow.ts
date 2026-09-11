import type { Edge, Node, XYPosition } from '@xyflow/react'
import { MarkerType } from '@xyflow/react'

import { catalogItem, isExecutableType, type AutoResearchNodeData } from './nodeCatalog'
import type { NodeRunRead, ResearchNodeType, RunRead, WorkflowDefinition } from './types'

let sequence = 0

const FORWARD_MARKER = {
  type: MarkerType.ArrowClosed,
  width: 18,
  height: 18,
  color: '#36d399',
} as const

const SELF_HEAL_MARKER = {
  type: MarkerType.ArrowClosed,
  width: 18,
  height: 18,
  color: '#fb7185',
} as const

const FEEDBACK_MARKER = {
  type: MarkerType.ArrowClosed,
  width: 18,
  height: 18,
  color: '#a78bfa',
} as const

export const defaultDirectedEdgeOptions = {
  type: 'smoothstep' as const,
  animated: true,
  reconnectable: true,
  style: { stroke: '#36d399', strokeWidth: 2 },
  markerEnd: { ...FORWARD_MARKER },
}

export function createCanvasNode(
  nodeType: ResearchNodeType,
  position: XYPosition,
  id = `${nodeType}-${Date.now()}-${sequence++}`,
): Node<AutoResearchNodeData> {
  const item = catalogItem(nodeType)
  return {
    id,
    type: 'research',
    position,
    data: {
      nodeType,
      name: item.label,
      config: structuredClone(item.defaultConfig),
    },
  }
}

export function buildStarterNodes(): Node<AutoResearchNodeData>[] {
  return [
    createCanvasNode('hypothesis', { x: 40, y: 140 }, 'hypothesis'),
    createCanvasNode('execution', { x: 320, y: 140 }, 'execution'),
    createCanvasNode('eval_script', { x: 320, y: 320 }, 'eval_script'),
    createCanvasNode('evaluation', { x: 600, y: 140 }, 'evaluation'),
    createCanvasNode('metric_gate', { x: 880, y: 140 }, 'metric_gate'),
    createCanvasNode('git_decision', { x: 1160, y: 140 }, 'git_decision'),
    createCanvasNode('database', { x: 600, y: 360 }, 'database'),
  ]
}

export function buildStarterEdges(): Edge[] {
  return [
    edge('hypothesis', 'execution', 'hypothesis-execution', 'right', 'left'),
    edge('execution', 'evaluation', 'execution-evaluation', 'right', 'left'),
    edge('eval_script', 'evaluation', 'eval-script-evaluation', 'top', 'bottom'),
    edge('evaluation', 'metric_gate', 'evaluation-gate', 'right', 'left'),
    edge('metric_gate', 'git_decision', 'gate-decision', 'right', 'left'),
    {
      ...edge('execution', 'hypothesis', 'self-heal', 'bottom', 'bottom'),
      animated: true,
      style: { stroke: '#fb7185', strokeDasharray: '6 4', strokeWidth: 2 },
      markerEnd: { ...SELF_HEAL_MARKER },
      label: 'self-heal',
    },
    {
      ...edge('git_decision', 'hypothesis', 'feedback', 'bottom', 'top'),
      animated: true,
      style: { stroke: '#a78bfa', strokeDasharray: '6 4', strokeWidth: 2 },
      markerEnd: { ...FEEDBACK_MARKER },
      label: 'feedback',
    },
  ]
}

function edge(
  source: string,
  target: string,
  id = `${source}-${target}`,
  sourceHandle = 'right',
  targetHandle = 'left',
): Edge {
  return {
    id: `edge-${id}`,
    source,
    target,
    sourceHandle,
    targetHandle,
    ...defaultDirectedEdgeOptions,
  }
}

export function isRecipeNode(node: Node<AutoResearchNodeData>): boolean {
  return isExecutableType(node.data.nodeType) || node.data.nodeType === 'database'
}

/** Latest status per canvas node_id from the active run. */
export function nodeLiveStatuses(run: RunRead | null | undefined): Map<string, string> {
  const statuses = new Map<string, string>()
  if (!run) return statuses
  for (const nodeRun of run.node_runs) {
    statuses.set(nodeRun.node_id, nodeRun.status)
  }
  return statuses
}

/** Canvas node currently executing (status=running), if any. */
export function currentExecutingNodeId(run: RunRead | null | undefined): string | null {
  if (!run || (run.status !== 'running' && run.status !== 'queued')) return null
  const active = [...run.node_runs].reverse().find((nodeRun) => nodeRun.status === 'running')
  return active?.node_id ?? null
}

export interface TrialView {
  id: string
  name: string
  status: string
  outcome?: string
  config: Record<string, unknown>
}

export function trialViewsFromRuns(trialRuns: NodeRunRead[]): TrialView[] {
  return trialRuns.map((trialRun) => {
    const outcome =
      typeof trialRun.output.outcome === 'string' ? trialRun.output.outcome : undefined
    return {
      id: trialRun.id,
      name: String(trialRun.output.trial_id ?? trialRun.node_id),
      status: trialRun.status,
      outcome,
      config: trialRun.output,
    }
  })
}

export function toWorkflowDefinition(
  id: string,
  name: string,
  nodes: Node<AutoResearchNodeData>[],
  edges: Edge[],
): WorkflowDefinition {
  const recipeNodes = nodes.filter(isRecipeNode)
  const recipeIds = new Set(recipeNodes.map((node) => node.id))
  return {
    schema_version: '1',
    id,
    name,
    description: 'Created in the AutoResearch canvas',
    nodes: recipeNodes.map((node) => ({
      id: node.id,
      type: node.data.nodeType,
      name: node.data.name,
      position: node.position,
      config: node.data.config,
    })),
    edges: edges
      .filter((edge) => recipeIds.has(edge.source) && recipeIds.has(edge.target))
      .map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        source_port: edge.sourceHandle ?? 'right',
        target_port: edge.targetHandle ?? 'left',
      })),
  }
}

export function fromWorkflowDefinition(definition: WorkflowDefinition): {
  nodes: Node<AutoResearchNodeData>[]
  edges: Edge[]
} {
  const nodes = definition.nodes.map((node) => ({
    id: node.id,
    type: 'research' as const,
    position: node.position,
    data: {
      nodeType: node.type,
      name: node.name,
      config: structuredClone(node.config),
    },
  }))
  const edges = definition.edges.map((edge) => {
    const base = {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      sourceHandle: edge.source_port,
      targetHandle: edge.target_port,
      ...defaultDirectedEdgeOptions,
    }
    if (edge.source_port === 'bottom' && edge.target_port === 'bottom') {
      return {
        ...base,
        style: { stroke: '#fb7185', strokeDasharray: '6 4', strokeWidth: 2 },
        markerEnd: { ...SELF_HEAL_MARKER },
        label: 'self-heal',
      }
    }
    if (edge.source_port === 'bottom' && edge.target_port === 'top') {
      return {
        ...base,
        style: { stroke: '#a78bfa', strokeDasharray: '6 4', strokeWidth: 2 },
        markerEnd: { ...FEEDBACK_MARKER },
        label: 'feedback',
      }
    }
    return base
  })
  return { nodes, edges }
}
