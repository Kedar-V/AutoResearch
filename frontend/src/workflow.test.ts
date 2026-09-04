import type { Edge } from '@xyflow/react'
import { describe, expect, it } from 'vitest'

import { NODE_CATALOG } from './nodeCatalog'
import {
  buildStarterEdges,
  buildStarterNodes,
  createCanvasNode,
  toWorkflowDefinition,
} from './workflow'

describe('workflow canvas helpers', () => {
  it('creates every catalog node type with its default configuration', () => {
    for (const item of NODE_CATALOG) {
      const node = createCanvasNode(item.type, { x: 10, y: 20 }, `${item.type}-node`)

      expect(node).toMatchObject({
        id: `${item.type}-node`,
        type: 'research',
        position: { x: 10, y: 20 },
        data: { nodeType: item.type, name: item.label, config: item.defaultConfig },
      })
    }
  })

  it('builds the starter graph in executable node and edge order', () => {
    const nodes = buildStarterNodes()
    const edges = buildStarterEdges()

    expect(nodes.map((node) => node.data.nodeType)).toEqual([
      'hypothesis', 'trial', 'script', 'evaluation', 'metric_gate', 'git_decision',
    ])
    expect(nodes.map((node) => node.position)).toEqual([
      { x: 0, y: 100 }, { x: 250, y: 210 }, { x: 500, y: 100 },
      { x: 750, y: 210 }, { x: 1000, y: 100 }, { x: 1250, y: 210 },
    ])
    expect(edges.map(({ source, target }) => [source, target])).toEqual([
      ['hypothesis', 'trial'], ['trial', 'script'], ['script', 'evaluation'],
      ['evaluation', 'metric_gate'], ['metric_gate', 'git_decision'],
    ])
  })

  it('serializes React Flow nodes and edges into the backend workflow contract', () => {
    const nodes = [
      createCanvasNode('script', { x: 12, y: 34 }, 'script-1'),
      createCanvasNode('evaluation', { x: 56, y: 78 }, 'evaluation-1'),
    ]
    const edges: Edge[] = [{
      id: 'edge-script-evaluation',
      source: 'script-1',
      target: 'evaluation-1',
      sourceHandle: 'artifacts',
      targetHandle: 'candidate',
    }]

    expect(toWorkflowDefinition('workflow-1', 'Research loop', nodes, edges)).toEqual({
      schema_version: '1',
      id: 'workflow-1',
      name: 'Research loop',
      description: 'Created in the AutoResearch canvas',
      nodes: [
        { id: 'script-1', type: 'script', name: 'Script', position: { x: 12, y: 34 }, config: nodes[0].data.config },
        { id: 'evaluation-1', type: 'evaluation', name: 'Evaluation', position: { x: 56, y: 78 }, config: nodes[1].data.config },
      ],
      edges: [{
        id: 'edge-script-evaluation',
        source: 'script-1',
        target: 'evaluation-1',
        source_port: 'artifacts',
        target_port: 'candidate',
      }],
    })
  })

  it('uses generic port mappings when React Flow handles are absent', () => {
    const workflow = toWorkflowDefinition(
      'workflow-1',
      'Research loop',
      [createCanvasNode('hypothesis', { x: 0, y: 0 }, 'hypothesis-1')],
      [{ id: 'edge-1', source: 'hypothesis-1', target: 'hypothesis-1' }],
    )

    expect(workflow.edges[0]).toMatchObject({ source_port: 'output', target_port: 'input' })
  })

  it('independently clones nested default configurations', () => {
    const first = createCanvasNode('script', { x: 0, y: 0 }, 'script-1')
    const second = createCanvasNode('script', { x: 0, y: 0 }, 'script-2')
    const firstCommand = first.data.config.command as string[]

    firstCommand.push('--fast')

    expect(second.data.config.command).toEqual(['python', 'train.py'])
    expect(NODE_CATALOG.find((item) => item.type === 'script')?.defaultConfig.command).toEqual([
      'python', 'train.py',
    ])
  })
})