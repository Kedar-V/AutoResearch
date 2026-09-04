import type { Edge, Node, XYPosition } from '@xyflow/react'

import { catalogItem, type AutoResearchNodeData } from './nodeCatalog'
import type { ResearchNodeType, WorkflowDefinition } from './types'

let sequence = 0

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

const STARTER_TYPES: ResearchNodeType[] = [
  'hypothesis', 'trial', 'script', 'evaluation', 'metric_gate', 'git_decision',
]

export function buildStarterNodes(): Node<AutoResearchNodeData>[] {
  return STARTER_TYPES.map((type, index) =>
    createCanvasNode(type, { x: index * 250, y: index % 2 === 0 ? 100 : 210 }, type),
  )
}

export function buildStarterEdges(): Edge[] {
  return STARTER_TYPES.slice(0, -1).map((source, index) => ({
    id: `edge-${source}-${STARTER_TYPES[index + 1]}`,
    source,
    target: STARTER_TYPES[index + 1],
    animated: true,
    style: { stroke: '#36d399' },
  }))
}

export function toWorkflowDefinition(
  id: string,
  name: string,
  nodes: Node<AutoResearchNodeData>[],
  edges: Edge[],
): WorkflowDefinition {
  return {
    schema_version: '1',
    id,
    name,
    description: 'Created in the AutoResearch canvas',
    nodes: nodes.map((node) => ({
      id: node.id,
      type: node.data.nodeType,
      name: node.data.name,
      position: node.position,
      config: node.data.config,
    })),
    edges: edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      source_port: edge.sourceHandle ?? 'output',
      target_port: edge.targetHandle ?? 'input',
    })),
  }
}
