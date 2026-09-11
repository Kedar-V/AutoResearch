import type { Edge } from '@xyflow/react'
import { describe, expect, it } from 'vitest'

import { NODE_CATALOG, PALETTE_CATALOG, RECIPE_PANEL_TYPES } from './nodeCatalog'
import { compileRecipe, isLegalConnection } from './recipe'
import {
  buildStarterEdges,
  buildStarterNodes,
  createCanvasNode,
  currentExecutingNodeId,
  nodeLiveStatuses,
  toWorkflowDefinition,
  trialViewsFromRuns,
} from './workflow'
import { deriveRunProgress } from './components/LiveRunStatus'
import { buildProgressPoints, runningChampion } from './components/ProgressStaircase'
import type { HypothesisRecord, NodeRunRead, RunRead, TrialRecord } from './types'

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

  it('defaults every node to composer-2.5', () => {
    for (const item of NODE_CATALOG) {
      expect(item.defaultConfig.model).toBe('composer-2.5')
    }
  })

  it('locks the palette and builds the closed-loop starter graph', () => {
    expect(PALETTE_CATALOG).toEqual([])
    expect(RECIPE_PANEL_TYPES).toEqual([
      'hypothesis',
      'execution',
      'eval_script',
      'evaluation',
      'metric_gate',
      'git_decision',
    ])

    const nodes = buildStarterNodes()
    const edges = buildStarterEdges()

    expect(nodes.map((node) => node.data.nodeType)).toEqual([
      'hypothesis',
      'execution',
      'eval_script',
      'evaluation',
      'metric_gate',
      'git_decision',
      'database',
    ])
    expect(edges.map(({ source, target }) => [source, target])).toEqual([
      ['hypothesis', 'execution'],
      ['execution', 'eval_script'],
      ['execution', 'evaluation'],
      ['eval_script', 'evaluation'],
      ['evaluation', 'metric_gate'],
      ['metric_gate', 'git_decision'],
      ['execution', 'hypothesis'],
      ['git_decision', 'hypothesis'],
    ])
    expect(edges.every((edge) => edge.markerEnd)).toBe(true)
  })

  it('compiles the starter graph into a valid research recipe', () => {
    const definition = toWorkflowDefinition(
      'default-research-loop',
      'default-research-loop',
      buildStarterNodes(),
      buildStarterEdges(),
    )
    const result = compileRecipe(definition)
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.recipe.postTrial.map((node) => node.type)).toEqual([
      'eval_script',
      'evaluation',
      'metric_gate',
      'git_decision',
    ])
  })

  it('rejects a disconnected metric gate', () => {
    const nodes = buildStarterNodes()
    const edges = buildStarterEdges().filter(
      (edge) => !(edge.source === 'evaluation' && edge.target === 'metric_gate'),
    )
    const definition = toWorkflowDefinition('broken', 'broken', nodes, edges)
    const result = compileRecipe(definition)
    expect(result.ok).toBe(false)
    if (result.ok) return
    expect(result.error).toMatch(/evaluation → metric_gate/)
  })

  it('only allows legal recipe connections', () => {
    expect(isLegalConnection('hypothesis', 'execution')).toBe(true)
    expect(isLegalConnection('hypothesis', 'metric_gate')).toBe(false)
    expect(isLegalConnection('evaluation', 'eval_script')).toBe(false)
  })

  it('serializes React Flow nodes and edges into the backend workflow contract', () => {
    const nodes = [
      createCanvasNode('execution', { x: 12, y: 34 }, 'execution-1'),
      createCanvasNode('evaluation', { x: 56, y: 78 }, 'evaluation-1'),
    ]
    const edges: Edge[] = [{
      id: 'edge-execution-evaluation',
      source: 'execution-1',
      target: 'evaluation-1',
      sourceHandle: 'right',
      targetHandle: 'left',
    }]

    expect(toWorkflowDefinition('workflow-1', 'Research loop', nodes, edges)).toEqual({
      schema_version: '1',
      id: 'workflow-1',
      name: 'Research loop',
      description: 'Created in the AutoResearch canvas',
      nodes: [
        {
          id: 'execution-1',
          type: 'execution',
          name: 'Execution',
          position: { x: 12, y: 34 },
          config: nodes[0].data.config,
        },
        {
          id: 'evaluation-1',
          type: 'evaluation',
          name: 'Evaluation agent',
          position: { x: 56, y: 78 },
          config: nodes[1].data.config,
        },
      ],
      edges: [{
        id: 'edge-execution-evaluation',
        source: 'execution-1',
        target: 'evaluation-1',
        source_port: 'right',
        target_port: 'left',
      }],
    })
  })

  it('derives live current/total trial progress from a run', () => {
    const run: RunRead = {
      id: 'run-1',
      workflow_id: 'tinylm-bench-loop',
      status: 'running',
      hypothesis_id: 'H0002',
      trial_id: 'H0002/T001',
      branch: 'trial/H0002/T001',
      error: null,
      context: {},
      created_at: '2026-09-10T00:00:00Z',
      started_at: '2026-09-10T00:00:01Z',
      finished_at: null,
      node_runs: [
        {
          id: 'nr-h1',
          node_id: 'hypothesis',
          node_type: 'hypothesis',
          status: 'succeeded',
          output: { hypothesis_id: 'H0001' },
          stdout: '',
          stderr: '',
          started_at: '2026-09-10T00:00:01Z',
          finished_at: '2026-09-10T00:00:02Z',
        },
        {
          id: 'nr-t1',
          node_id: 'trial-T001',
          node_type: 'trial',
          status: 'succeeded',
          output: { trial_id: 'H0001/T001', number: 1 },
          stdout: '',
          stderr: '',
          started_at: '2026-09-10T00:00:02Z',
          finished_at: '2026-09-10T00:00:03Z',
        },
        {
          id: 'nr-h2',
          node_id: 'hypothesis',
          node_type: 'hypothesis',
          status: 'succeeded',
          output: { hypothesis_id: 'H0002' },
          stdout: '',
          stderr: '',
          started_at: '2026-09-10T00:00:04Z',
          finished_at: '2026-09-10T00:00:05Z',
        },
        {
          id: 'nr-t2',
          node_id: 'trial-T001',
          node_type: 'trial',
          status: 'running',
          output: { trial_id: 'H0002/T001', number: 1 },
          stdout: '',
          stderr: '',
          started_at: '2026-09-10T00:00:05Z',
          finished_at: null,
        },
      ],
    }

    expect(deriveRunProgress(run, { maxHypotheses: 20, maxRetries: 2 })).toMatchObject({
      status: 'running',
      hypothesisCurrent: 2,
      hypothesisTotal: 20,
      attemptCurrent: 1,
      attemptTotal: 2,
      overallCurrent: 2,
      overallTotal: 40,
      hypothesisId: 'H0002',
      trialId: 'H0002/T001',
      currentNode: 'trial-T001',
    })
  })

  it('builds trial views from run history', () => {
    const trialRuns: NodeRunRead[] = [{
      id: 'run-trial-1',
      node_id: 'trial-T001',
      node_type: 'trial',
      status: 'succeeded',
      output: { trial_id: 'H0001/T001', outcome: 'ran' },
      stdout: '',
      stderr: '',
      started_at: '2026-09-10T00:00:00Z',
      finished_at: '2026-09-10T00:00:01Z',
    }]

    expect(trialViewsFromRuns(trialRuns)).toEqual([{
      id: 'run-trial-1',
      name: 'H0001/T001',
      status: 'succeeded',
      outcome: 'ran',
      config: { trial_id: 'H0001/T001', outcome: 'ran' },
    }])
  })

  it('uses generic port mappings when React Flow handles are absent', () => {
    const workflow = toWorkflowDefinition(
      'workflow-1',
      'Research loop',
      [createCanvasNode('hypothesis', { x: 0, y: 0 }, 'hypothesis-1')],
      [{ id: 'edge-1', source: 'hypothesis-1', target: 'hypothesis-1' }],
    )

    expect(workflow.edges[0]).toMatchObject({ source_port: 'right', target_port: 'left' })
  })

  it('independently clones nested default configurations', () => {
    const first = createCanvasNode('execution', { x: 0, y: 0 }, 'execution-1')
    const second = createCanvasNode('execution', { x: 0, y: 0 }, 'execution-2')
    const firstCommand = first.data.config.command as string[]

    firstCommand.push('--fast')

    expect(second.data.config.command).toEqual(['python', 'train.py'])
    expect(NODE_CATALOG.find((item) => item.type === 'execution')?.defaultConfig.command).toEqual([
      'python', 'train.py',
    ])
  })

  it('builds a karpathy-style staircase from baseline and kept trials', () => {
    const hypotheses: HypothesisRecord[] = [
      {
        id: 'H0001',
        title: 'a',
        description: '',
        branch: 'hypothesis/H0001',
        base_commit: 'a',
        status: 'accepted',
        what_worked: '',
        what_did_not: '',
        metrics: { score: 4 },
        created_at: '2026-01-01T00:00:00Z',
      },
      {
        id: 'H0002',
        title: 'b',
        description: '',
        branch: 'hypothesis/H0002',
        base_commit: 'b',
        status: 'rejected',
        what_worked: '',
        what_did_not: '',
        metrics: { score: 4.5 },
        created_at: '2026-01-01T00:01:00Z',
      },
    ]
    const trials: TrialRecord[] = [
      {
        id: 'H0001/T001',
        hypothesis_id: 'H0001',
        branch: 'trial/H0001/T001',
        candidate_commit: 'c1',
        outcome: 'accepted',
        error: '',
        next_step: '',
        what_changed: '',
        metrics: { score: 4 },
        created_at: '2026-01-01T00:00:30Z',
      },
      {
        id: 'H0002/T001',
        hypothesis_id: 'H0002',
        branch: 'trial/H0002/T001',
        candidate_commit: 'c2',
        outcome: 'rejected',
        error: '',
        next_step: '',
        what_changed: '',
        metrics: { score: 4.5 },
        created_at: '2026-01-01T00:01:30Z',
      },
    ]
    const points = buildProgressPoints(hypotheses, trials, { metric: 'score', baseline: 5 })
    expect(points.map((point) => [point.status, point.metric])).toEqual([
      ['baseline', 5],
      ['accepted', 4],
      ['rejected', 4.5],
    ])
    expect(runningChampion(points, 'minimize')).toEqual([
      { index: 0, metric: 5 },
      { index: 1, metric: 4 },
    ])
  })

  it('tracks the currently executing canvas node from live node_runs', () => {
    const run: RunRead = {
      id: 'run-live',
      workflow_id: 'tinylm-bench-loop',
      status: 'running',
      hypothesis_id: 'H0001',
      trial_id: 'H0001/T001',
      branch: 'trial/H0001/T001',
      error: null,
      context: {},
      created_at: '2026-09-10T00:00:00Z',
      started_at: '2026-09-10T00:00:01Z',
      finished_at: null,
      node_runs: [
        {
          id: 'nr-1',
          node_id: 'hypothesis',
          node_type: 'hypothesis',
          status: 'succeeded',
          output: {},
          stdout: '',
          stderr: '',
          started_at: '2026-09-10T00:00:01Z',
          finished_at: '2026-09-10T00:00:02Z',
        },
        {
          id: 'nr-2',
          node_id: 'execution',
          node_type: 'execution',
          status: 'running',
          output: {},
          stdout: '',
          stderr: '',
          started_at: '2026-09-10T00:00:02Z',
          finished_at: null,
        },
      ],
    }
    expect(currentExecutingNodeId(run)).toBe('execution')
    expect(nodeLiveStatuses(run).get('hypothesis')).toBe('succeeded')
    expect(nodeLiveStatuses(run).get('execution')).toBe('running')
    expect(currentExecutingNodeId({ ...run, status: 'succeeded' })).toBeNull()
  })
})
