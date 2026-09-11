import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Background,
  ConnectionMode,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  addEdge,
  reconnectEdge,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
  type NodeMouseHandler,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Activity, ChevronDown, Database, ExternalLink, FolderPlus, GitBranch, Pause, Play, RotateCcw, Save, Square, Workflow } from 'lucide-react'

import {
  activateProject,
  cancelRun,
  createProject,
  createRun,
  getActiveProject,
  getRun,
  getWorkflow,
  listEvaluations,
  listHypotheses,
  listProjects,
  listRuns,
  listTrials,
  pauseRun,
  restartProject,
  resumeRun,
  saveWorkflow,
} from './api'
import { AgentSlideOver } from './components/AgentSlideOver'
import { DbSlideOver } from './components/DbSlideOver'
import { EvaluationSlideOver } from './components/EvaluationSlideOver'
import { LiveRunStatus, deriveRunProgress } from './components/LiveRunStatus'
import {
  ProgressStaircase,
  buildProgressPoints,
} from './components/ProgressStaircase'
import { ResearchNode } from './components/ResearchNode'
import {
  DEFAULT_MODEL,
  RECIPE_PANEL_TYPES,
  catalogItem,
  type AutoResearchNodeData,
} from './nodeCatalog'
import { compileRecipe, isLegalConnection, isRequiredType } from './recipe'
import type {
  EvaluationRecord,
  HypothesisRecord,
  NodeRunRead,
  ProjectRead,
  RunRead,
  TrialRecord,
  WorkflowDefinition,
} from './types'
import {
  buildStarterEdges,
  buildStarterNodes,
  currentExecutingNodeId,
  defaultDirectedEdgeOptions,
  fromWorkflowDefinition,
  isRecipeNode,
  nodeLiveStatuses,
  toWorkflowDefinition,
} from './workflow'
import './App.css'

const nodeTypes = { research: ResearchNode }
const defaultWorkflowId = 'default-research-loop'
const starterNodes = buildStarterNodes()

function CanvasApp() {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<AutoResearchNodeData>>(starterNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(buildStarterEdges())
  const [workflowId, setWorkflowId] = useState(defaultWorkflowId)
  const [selectedId, setSelectedId] = useState<string | null>(nodes[0]?.id ?? null)
  const [configDraft, setConfigDraft] = useState(() =>
    JSON.stringify(starterNodes[0]?.data.config ?? {}, null, 2),
  )
  const [configError, setConfigError] = useState('')
  const [notice, setNotice] = useState('Ready')
  const [activeRun, setActiveRun] = useState<RunRead | null>(null)
  const [project, setProject] = useState<ProjectRead | null>(null)
  const [projects, setProjects] = useState<ProjectRead[]>([])
  const [hypotheses, setHypotheses] = useState<HypothesisRecord[]>([])
  const [trials, setTrials] = useState<TrialRecord[]>([])
  const [evaluations, setEvaluations] = useState<EvaluationRecord[]>([])
  const [agentOpen, setAgentOpen] = useState(false)
  const [evalOpen, setEvalOpen] = useState(false)
  const [focusHypothesisId, setFocusHypothesisId] = useState<string | null>(null)
  const [dbOpen, setDbOpen] = useState(false)
  const [projectName, setProjectName] = useState('')
  const [projectDialog, setProjectDialog] = useState(false)
  const [restarting, setRestarting] = useState(false)

  const selected = nodes.find((node) => node.id === selectedId) ?? null
  const running =
    activeRun?.status === 'queued' ||
    activeRun?.status === 'running' ||
    activeRun?.status === 'paused'
  const canPause = activeRun?.status === 'running'
  const canResume = activeRun?.status === 'paused'
  const canCancel =
    activeRun?.status === 'queued' ||
    activeRun?.status === 'running' ||
    activeRun?.status === 'paused'
  const hypothesisNode = nodes.find((node) => node.data.nodeType === 'hypothesis')
  const evaluationNode = nodes.find((node) => node.data.nodeType === 'evaluation')
  const maxHypotheses = Math.max(1, Number(hypothesisNode?.data.config.max_hypotheses) || 5)
  const maxRetries = Math.max(1, Number(hypothesisNode?.data.config.max_retries) || 3)
  const runProgress = useMemo(
    () => deriveRunProgress(activeRun, { maxHypotheses, maxRetries }),
    [activeRun, maxHypotheses, maxRetries],
  )

  const displayNodes = useMemo(() => {
    const live = nodeLiveStatuses(activeRun)
    const executingId = currentExecutingNodeId(activeRun)
    return nodes.map((node) => {
      const liveStatus = live.get(node.id)
      const executing = executingId === node.id
      let badge = node.data.badge
      if (node.data.nodeType === 'hypothesis') badge = hypotheses.length || undefined
      if (node.data.nodeType === 'evaluation') badge = evaluations.length || undefined
      return {
        ...node,
        data: {
          ...node.data,
          badge,
          liveStatus,
          executing,
        },
        className: executing ? 'executing-node' : undefined,
      }
    })
  }, [activeRun, evaluations.length, hypotheses.length, nodes])

  const displayEdges = useMemo(() => {
    const executingId = currentExecutingNodeId(activeRun)
    return edges.map((edge) => {
      const intoActive = Boolean(executingId && edge.target === executingId)
      const fromActive = Boolean(executingId && edge.source === executingId)
      if (!intoActive && !fromActive) return edge
      return {
        ...edge,
        animated: true,
        style: {
          ...edge.style,
          stroke: intoActive ? '#fbbf24' : edge.style?.stroke,
          strokeWidth: intoActive ? 3 : 2,
        },
        markerEnd:
          typeof edge.markerEnd === 'object' && edge.markerEnd
            ? {
                ...edge.markerEnd,
                color: intoActive
                  ? '#fbbf24'
                  : 'color' in edge.markerEnd
                    ? edge.markerEnd.color
                    : '#36d399',
              }
            : edge.markerEnd,
      }
    })
  }, [activeRun, edges])

  const gateNode = nodes.find((node) => node.data.nodeType === 'metric_gate')
  const metricName = String(gateNode?.data.config.metric ?? 'score')
  const metricDirection =
    gateNode?.data.config.direction === 'maximize' ? 'maximize' : 'minimize'
  const baselineValue = Number(gateNode?.data.config.baseline)
  const progressPoints = useMemo(
    () =>
      buildProgressPoints(hypotheses, trials, {
        metric: metricName,
        baseline: Number.isFinite(baselineValue) ? baselineValue : undefined,
      }),
    [baselineValue, hypotheses, metricName, trials],
  )

  const inboundContext = useMemo(() => {
    if (!hypothesisNode) return []
    return edges
      .filter((edge) => edge.target === hypothesisNode.id)
      .map((edge) => nodes.find((node) => node.id === edge.source)?.data.name ?? edge.source)
  }, [edges, hypothesisNode, nodes])

  const evaluationInboundContext = useMemo(() => {
    if (!evaluationNode) return []
    return edges
      .filter((edge) => edge.target === evaluationNode.id)
      .map((edge) => nodes.find((node) => node.id === edge.source)?.data.name ?? edge.source)
  }, [edges, evaluationNode, nodes])

  const loadProjectWorkflow = useCallback(
    async (active: ProjectRead | null) => {
      if (!active) return defaultWorkflowId
      const preferredId = active.name.endsWith('-bench')
        ? `${active.name}-loop`
        : defaultWorkflowId
      try {
        const definition = await getWorkflow(preferredId)
        const next = fromWorkflowDefinition(definition)
        setWorkflowId(definition.id)
        setNodes(next.nodes)
        setEdges(next.edges)
        setSelectedId(next.nodes[0]?.id ?? null)
        setConfigDraft(JSON.stringify(next.nodes[0]?.data.config ?? {}, null, 2))
        return definition.id
      } catch {
        // Keep the current canvas if the preferred workflow is missing.
        return preferredId
      }
    },
    [setEdges, setNodes],
  )

  const syncActiveRun = useCallback(async (nextWorkflowId: string, projectId: string | null) => {
    try {
      const runs = await listRuns()
      const latest =
        runs.find(
          (run) =>
            run.workflow_id === nextWorkflowId &&
            (projectId == null || run.project_id == null || run.project_id === projectId),
        ) ?? null
      setActiveRun(latest)
    } catch {
      setActiveRun(null)
    }
  }, [])

  const refreshProject = useCallback(async () => {
    let listed: ProjectRead[] = []
    try {
      listed = await listProjects()
      setProjects(listed)
    } catch (error) {
      setProjects([])
      setNotice(error instanceof Error ? error.message : 'Could not list projects')
      return
    }

    let active: ProjectRead | null = null
    try {
      active = await getActiveProject()
    } catch {
      active = listed[0] ?? null
    }
    setProject(active)

    if (active) {
      try {
        const [hypos, trialRows, evalRows] = await Promise.all([
          listHypotheses(active.id),
          listTrials(active.id),
          listEvaluations(active.id),
        ])
        setHypotheses(hypos)
        setTrials(trialRows)
        setEvaluations(evalRows)
        const nextWorkflowId = await loadProjectWorkflow(active)
        await syncActiveRun(nextWorkflowId, active.id)
      } catch (error) {
        setNotice(error instanceof Error ? error.message : 'Could not load project data')
      }
    } else {
      setHypotheses([])
      setTrials([])
      setEvaluations([])
      setActiveRun(null)
    }
  }, [loadProjectWorkflow, syncActiveRun])

  const handleSelectProject = async (projectId: string) => {
    if (!projectId) return
    try {
      const activated = await activateProject(projectId)
      setProject(activated)
      setActiveRun(null)
      const [hypos, trialRows, evalRows, listed] = await Promise.all([
        listHypotheses(activated.id),
        listTrials(activated.id),
        listEvaluations(activated.id),
        listProjects(),
      ])
      setHypotheses(hypos)
      setTrials(trialRows)
      setEvaluations(evalRows)
      setProjects(listed)
      const nextWorkflowId = await loadProjectWorkflow(activated)
      await syncActiveRun(nextWorkflowId, activated.id)
      setNotice(`Switched to ${activated.name}`)
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Could not switch project')
    }
  }

  useEffect(() => {
    refreshProject().catch(() => undefined)
  }, [refreshProject])

  useEffect(() => {
    if (!activeRun || !running) return
    const timer = window.setInterval(async () => {
      try {
        const next = await getRun(activeRun.id)
        setActiveRun(next)
        if (project) {
          const [hypos, trialRows] = await Promise.all([
            listHypotheses(project.id),
            listTrials(project.id),
          ])
          setHypotheses(hypos)
          setTrials(trialRows)
        }
        if (next.status === 'succeeded') {
          setNotice('Run completed')
          refreshProject().catch(() => undefined)
        }
        if (next.status === 'failed') setNotice('Run failed')
        if (next.status === 'cancelled') setNotice('Run cancelled')
        if (next.status === 'paused') setNotice('Run paused')
      } catch (error) {
        setNotice(error instanceof Error ? error.message : 'Could not refresh run')
      }
    }, 1000)
    return () => window.clearInterval(timer)
  }, [activeRun, project, refreshProject, running])

  const onNodesChangeFiltered = useCallback(
    (changes: Parameters<typeof onNodesChange>[0]) => {
      const filtered = changes.filter((change) => {
        if (change.type !== 'remove') return true
        const node = nodes.find((candidate) => candidate.id === change.id)
        if (!node) return true
        return !isRequiredType(node.data.nodeType)
      })
      if (filtered.length) onNodesChange(filtered)
    },
    [nodes, onNodesChange],
  )

  const onConnect = useCallback(
    (connection: Connection) => {
      const source = nodes.find((node) => node.id === connection.source)
      const target = nodes.find((node) => node.id === connection.target)
      if (!source || !target || !isRecipeNode(source) || !isRecipeNode(target)) return
      if (!isLegalConnection(source.data.nodeType, target.data.nodeType)) {
        setNotice(
          `Illegal edge ${source.data.nodeType} → ${target.data.nodeType} (not in research recipe grammar)`,
        )
        return
      }
      setEdges((current) =>
        addEdge(
          {
            ...connection,
            ...defaultDirectedEdgeOptions,
            style: { stroke: '#36d399', strokeWidth: 2 },
          },
          current,
        ),
      )
    },
    [nodes, setEdges],
  )

  const onReconnect = useCallback(
    (oldEdge: Edge, newConnection: Connection) => {
      const source = nodes.find((node) => node.id === newConnection.source)
      const target = nodes.find((node) => node.id === newConnection.target)
      if (!source || !target || !isRecipeNode(source) || !isRecipeNode(target)) return
      if (!isLegalConnection(source.data.nodeType, target.data.nodeType)) {
        setNotice(
          `Illegal edge ${source.data.nodeType} → ${target.data.nodeType} (not in research recipe grammar)`,
        )
        return
      }
      setEdges((current) =>
        reconnectEdge(oldEdge, newConnection, current).map((edge) =>
          edge.id === oldEdge.id
            ? { ...edge, reconnectable: true, type: edge.type ?? 'smoothstep' }
            : edge,
        ),
      )
    },
    [nodes, setEdges],
  )

  const onNodeClick: NodeMouseHandler<Node<AutoResearchNodeData>> = useCallback((_, node) => {
    setSelectedId(node.id)
    setConfigDraft(JSON.stringify(node.data.config, null, 2))
    setConfigError('')
    if (node.data.nodeType === 'hypothesis') setAgentOpen(true)
    if (node.data.nodeType === 'evaluation') setEvalOpen(true)
    if (node.data.nodeType === 'database') setDbOpen(true)
  }, [])

  const resetRecipeLayout = () => {
    const nextNodes = buildStarterNodes()
    const nextEdges = buildStarterEdges()
    setNodes(nextNodes)
    setEdges(nextEdges)
    setSelectedId(nextNodes[0]?.id ?? null)
    setConfigDraft(JSON.stringify(nextNodes[0]?.data.config ?? {}, null, 2))
    setConfigError('')
    setNotice('Recipe layout reset')
  }

  const updateName = (name: string) => {
    if (!selectedId) return
    setNodes((current) =>
      current.map((node) =>
        node.id === selectedId ? { ...node, data: { ...node.data, name } } : node,
      ),
    )
  }

  const updateHypothesisConfig = (patch: Record<string, unknown>) => {
    if (!hypothesisNode) return
    setNodes((current) =>
      current.map((node) =>
        node.id === hypothesisNode.id
          ? { ...node, data: { ...node.data, config: { ...node.data.config, ...patch } } }
          : node,
      ),
    )
  }

  const updateEvaluationConfig = (patch: Record<string, unknown>) => {
    if (!evaluationNode) return
    setNodes((current) =>
      current.map((node) =>
        node.id === evaluationNode.id
          ? { ...node, data: { ...node.data, config: { ...node.data.config, ...patch } } }
          : node,
      ),
    )
  }

  const applyConfig = () => {
    if (!selectedId) return
    try {
      const config: unknown = JSON.parse(configDraft)
      if (!config || Array.isArray(config) || typeof config !== 'object') {
        throw new Error('Configuration must be a JSON object')
      }
      setNodes((current) =>
        current.map((node) =>
          node.id === selectedId
            ? { ...node, data: { ...node.data, config: config as Record<string, unknown> } }
            : node,
        ),
      )
      setConfigError('')
      setNotice('Node configuration applied')
    } catch (error) {
      setConfigError(error instanceof Error ? error.message : 'Invalid JSON')
    }
  }

  const definition = useMemo<WorkflowDefinition>(
    () => toWorkflowDefinition(workflowId, workflowId, nodes, edges),
    [nodes, edges, workflowId],
  )

  const recipeCompile = useMemo(() => compileRecipe(definition), [definition])
  const graphValid = recipeCompile.ok
  const recipeError = recipeCompile.ok ? '' : recipeCompile.error

  const handleSave = async () => {
    if (!graphValid) {
      setNotice(recipeError || 'Fix the research recipe before saving')
      return
    }
    try {
      await saveWorkflow(definition)
      setNotice('Workflow saved')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Save failed')
    }
  }

  const handleRun = async () => {
    if (!graphValid || restarting) {
      if (!graphValid) {
        setNotice(recipeError || 'Fix the research recipe before running')
      }
      return
    }
    try {
      await saveWorkflow(definition)
      const run = await createRun(definition.id)
      setActiveRun(run)
      setNotice('Run started')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Run failed to start')
    }
  }

  const handleCancel = async () => {
    if (!activeRun || restarting) return
    try {
      const next = await cancelRun(activeRun.id)
      setActiveRun(next)
      setNotice('Cancelling run…')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Could not cancel run')
    }
  }

  const handleRestart = async () => {
    if (!project || restarting) return
    const confirmed = window.confirm(
      `Restart ${project.name}?\n\nThis wipes experiment history (hypotheses, trials, runs, Git experiment refs) and starts a fresh run. Champion code on master is kept.`,
    )
    if (!confirmed) return
    setRestarting(true)
    setNotice('Restarting project…')
    try {
      const result = await restartProject(project.id)
      setProject(result.project)
      setHypotheses([])
      setTrials([])
      setEvaluations([])
      setActiveRun(result.run)
      await loadProjectWorkflow(result.project)
      setProjects(await listProjects())
      setNotice('Restarted — fresh run started')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Could not restart project')
    } finally {
      setRestarting(false)
    }
  }

  const handlePause = async () => {
    if (!activeRun || restarting) return
    try {
      await pauseRun(activeRun.id)
      setNotice('Pause requested — finishing current node…')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Could not pause run')
    }
  }

  const handleResume = async () => {
    if (!activeRun || restarting) return
    try {
      await resumeRun(activeRun.id)
      setNotice('Resuming…')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Could not resume run')
    }
  }

  const handleCreateProject = async () => {
    try {
      const created = await createProject(projectName.trim())
      setProject(created)
      setProjects(await listProjects())
      setProjectDialog(false)
      setProjectName('')
      setHypotheses([])
      setTrials([])
      setActiveRun(null)
      await loadProjectWorkflow(created)
      setNotice(`Created private project ${created.name}`)
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Could not create project')
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark"><Workflow size={19} /></div>
          <div className="brand-copy">
            <span className="brand-eyebrow">AutoResearch</span>
            {project?.github_url ? (
              <a
                className="project-title"
                href={githubBrowserUrl(project.github_url)}
                target="_blank"
                rel="noreferrer"
                title="Open GitHub repository"
              >
                {project.name}
                <ExternalLink size={14} />
              </a>
            ) : (
              <strong className="project-title static">
                {project?.name ?? 'No active project'}
              </strong>
            )}
            <label className="project-picker">
              <span className="sr-only">Switch project</span>
              <select
                value={project?.id ?? ''}
                onChange={(event) => handleSelectProject(event.target.value)}
                disabled={projects.length === 0}
              >
                {projects.length === 0 ? (
                  <option value="">No projects yet</option>
                ) : (
                  projects.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))
                )}
              </select>
              <ChevronDown size={12} aria-hidden />
            </label>
          </div>
        </div>
        <div className="topbar-actions">
          <span className="notice">
            <span className={`status-dot ${running ? 'pulse' : ''}`} />
            {running
              ? `${runProgress.overallCurrent}/${runProgress.overallTotal} trials · ${notice}`
              : notice}
          </span>
          <button className="button secondary" onClick={() => setProjectDialog(true)}>
            <FolderPlus size={16} />New project
          </button>
          <button className="button secondary" onClick={handleSave}><Save size={16} />Save</button>
          {canPause && (
            <button className="button secondary" onClick={handlePause} type="button" disabled={restarting}>
              <Pause size={16} fill="currentColor" />Pause
            </button>
          )}
          {canResume && (
            <button className="button primary" onClick={handleResume} type="button" disabled={restarting}>
              <Play size={16} fill="currentColor" />Resume
            </button>
          )}
          {canCancel && (
            <button className="button danger" onClick={handleCancel} type="button" disabled={restarting}>
              <Square size={14} fill="currentColor" />Cancel
            </button>
          )}
          <button
            className="button secondary"
            onClick={handleRestart}
            type="button"
            disabled={!project || restarting}
            title="Wipe experiment history, keep champion, start a fresh run"
          >
            <RotateCcw size={16} />
            {restarting ? 'Restarting…' : 'Restart'}
          </button>
          <button
            className="button secondary"
            onClick={() => setDbOpen(true)}
            type="button"
            disabled={!project}
            title="Browse project database"
          >
            <Database size={16} />
            DB
          </button>
          <button
            className="button primary"
            onClick={handleRun}
            disabled={running || restarting || !graphValid}
            title={graphValid ? 'Run research loop' : recipeError}
          >
            <Play size={16} fill="currentColor" />
            {activeRun?.status === 'paused'
              ? 'Paused'
              : running
                ? 'Running…'
                : 'Run workflow'}
          </button>
        </div>
      </header>

      <section className="workspace-grid">
        <aside className="palette panel">
          <div className="panel-heading">
            <span>Research recipe</span>
            <small>Locked grammar</small>
          </div>
          <div className="palette-list">
            {RECIPE_PANEL_TYPES.map((type) => {
              const item = catalogItem(type)
              return (
                <div className="palette-item recipe-role" key={type}>
                  <span className="palette-icon" style={{ color: item.color }}>{item.icon}</span>
                  <span><strong>{item.label}</strong><small>{item.description}</small></span>
                </div>
              )
            })}
          </div>
          <button className="button secondary full" type="button" onClick={resetRecipeLayout}>
            Reset recipe layout
          </button>
          <div className="legend">
            <GitBranch size={15} />
            <span>
              Edges must follow the recipe grammar. Required nodes cannot be deleted.
              Self-heal and feedback close the loop.
            </span>
          </div>
          {recipeError && <p className="form-error">{recipeError}</p>}
        </aside>

        <div className="canvas-wrap">
          <ReactFlow
            nodes={displayNodes}
            edges={displayEdges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChangeFiltered}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onReconnect={onReconnect}
            edgesReconnectable
            reconnectRadius={28}
            connectionMode={ConnectionMode.Loose}
            defaultEdgeOptions={defaultDirectedEdgeOptions}
            onNodeClick={onNodeClick}
            onPaneClick={() => {
              setSelectedId(null)
              setConfigDraft('')
              setConfigError('')
            }}
            fitView
            minZoom={0.35}
            maxZoom={1.8}
          >
            <Background color="#243044" gap={22} size={1} />
            <MiniMap pannable zoomable nodeColor="#1f2937" maskColor="rgba(6, 10, 18, .74)" />
            <Controls />
          </ReactFlow>
          <LiveRunStatus progress={runProgress} />
        </div>

        <aside className="inspector panel">
          <div className="panel-heading">
            <span>Inspector</span>
            <small>{selected?.data.nodeType ?? 'No selection'}</small>
          </div>
          {selected ? (
            <div className="inspector-form">
              <label>
                Node name
                <input value={selected.data.name} onChange={(event) => updateName(event.target.value)} />
              </label>
              <label>
                Configuration
                <textarea
                  rows={16}
                  value={configDraft}
                  onChange={(event) => setConfigDraft(event.target.value)}
                  spellCheck={false}
                />
              </label>
              {configError && <p className="form-error">{configError}</p>}
              <button className="button secondary full" onClick={applyConfig}>Apply configuration</button>
            </div>
          ) : (
            <div className="empty-state">Select a node to edit its name and runtime configuration.</div>
          )}

          <div className="run-panel">
            <div className="panel-heading compact"><span>Progress</span><Activity size={15} /></div>
            <ProgressStaircase
              points={progressPoints}
              direction={metricDirection}
              metricName={metricName}
              onSelectHypothesis={(hypothesisId) => {
                setFocusHypothesisId(hypothesisId)
                setAgentOpen(true)
              }}
            />
          </div>

          <div className="run-panel">
            <div className="panel-heading compact"><span>Latest run</span><Activity size={15} /></div>
            {!activeRun ? (
              <div className="empty-state small">No run started in this session.</div>
            ) : (
              <>
                <div className={`run-status ${activeRun.status}`}>{activeRun.status}</div>
                <dl className="run-meta">
                  <div>
                    <dt>Trials</dt>
                    <dd>
                      {runProgress.overallCurrent}/{runProgress.overallTotal}
                    </dd>
                  </div>
                  <div>
                    <dt>Hypothesis</dt>
                    <dd>
                      {runProgress.hypothesisCurrent}/{runProgress.hypothesisTotal}
                    </dd>
                  </div>
                  <div><dt>Current hypo</dt><dd>{activeRun.hypothesis_id ?? '—'}</dd></div>
                  <div><dt>Current trial</dt><dd>{activeRun.trial_id ?? '—'}</dd></div>
                </dl>
                <div className="node-results">
                  {activeRun.node_runs.map((nodeRun) => {
                    const detail = nodeRunDetail(nodeRun)
                    return (
                      <div className="node-result" key={nodeRun.id}>
                        <span className={`result-dot ${detail.tone}`} />
                        <span>{nodeRun.node_id}</span>
                        <small className={detail.tone}>{detail.label}</small>
                      </div>
                    )
                  })}
                </div>
                {activeRun.error && <p className="form-error">{activeRun.error}</p>}
              </>
            )}
          </div>
        </aside>
      </section>

      <AgentSlideOver
        open={agentOpen}
        onClose={() => {
          setAgentOpen(false)
          setFocusHypothesisId(null)
        }}
        project={project}
        systemPrompt={String(hypothesisNode?.data.config.system_prompt ?? '')}
        model={String(hypothesisNode?.data.config.model ?? DEFAULT_MODEL)}
        onSystemPromptChange={(value) => updateHypothesisConfig({ system_prompt: value })}
        onModelChange={(value) => updateHypothesisConfig({ model: value })}
        inboundContext={inboundContext}
        focusHypothesisId={focusHypothesisId}
        onFocusHandled={() => setFocusHypothesisId(null)}
      />

      <EvaluationSlideOver
        open={evalOpen}
        onClose={() => setEvalOpen(false)}
        project={project}
        systemPrompt={String(evaluationNode?.data.config.system_prompt ?? '')}
        model={String(evaluationNode?.data.config.model ?? DEFAULT_MODEL)}
        explainabilitySchema={evaluationNode?.data.config.explainability_schema ?? null}
        onSystemPromptChange={(value) => updateEvaluationConfig({ system_prompt: value })}
        onModelChange={(value) => updateEvaluationConfig({ model: value })}
        onExplainabilitySchemaChange={(value) =>
          updateEvaluationConfig({ explainability_schema: value })
        }
        inboundContext={evaluationInboundContext}
        onOpenHypothesis={(hypothesisId) => {
          setEvalOpen(false)
          setFocusHypothesisId(hypothesisId)
          setAgentOpen(true)
        }}
      />

      <DbSlideOver
        open={dbOpen}
        onClose={() => setDbOpen(false)}
        project={project}
        onOpenHypothesis={() => {
          setDbOpen(false)
          setAgentOpen(true)
        }}
        onOpenTrial={() => {
          setDbOpen(false)
          setAgentOpen(true)
        }}
      />

      {projectDialog && (
        <div className="slide-root">
          <button className="slide-backdrop" aria-label="Close" onClick={() => setProjectDialog(false)} />
          <div className="dialog">
            <h2>New project</h2>
            <p className="muted">Creates a private GitHub repo and a dedicated Postgres schema.</p>
            <label>
              Repository name
              <input
                value={projectName}
                onChange={(event) => setProjectName(event.target.value)}
                placeholder="score-descent"
              />
            </label>
            <button
              className="button primary full"
              disabled={!/^[A-Za-z0-9._-]+$/.test(projectName.trim())}
              onClick={handleCreateProject}
            >
              Create private repo
            </button>
          </div>
        </div>
      )}
    </main>
  )
}

export default function App() {
  return (
    <ReactFlowProvider>
      <CanvasApp />
    </ReactFlowProvider>
  )
}

function githubBrowserUrl(raw: string): string {
  const trimmed = raw.trim()
  const ssh = trimmed.match(/^git@([^:]+):(.+?)(?:\.git)?$/i)
  if (ssh) return `https://${ssh[1]}/${ssh[2]}`
  return trimmed.replace(/\.git$/i, '')
}

function nodeRunDetail(nodeRun: NodeRunRead): { label: string; tone: string } {
  const output = nodeRun.output ?? {}
  if (nodeRun.node_type === 'metric_gate' && typeof output.accepted === 'boolean') {
    return output.accepted
      ? { label: 'accepted', tone: 'accepted' }
      : { label: 'rejected', tone: 'rejected' }
  }
  if (nodeRun.node_type === 'git_decision' && typeof output.outcome === 'string') {
    const outcome = output.outcome
    return {
      label: outcome,
      tone: outcome === 'accepted' ? 'accepted' : outcome === 'rejected' ? 'rejected' : nodeRun.status,
    }
  }
  if (nodeRun.node_type === 'trial' && typeof output.outcome === 'string') {
    return {
      label: output.outcome,
      tone: output.outcome === 'ran' ? 'succeeded' : output.outcome === 'failed' ? 'failed' : nodeRun.status,
    }
  }
  if (nodeRun.node_type === 'evaluation') {
    const recommendation =
      typeof output.recommendation === 'string' ? output.recommendation : null
    const primary =
      typeof output.primary_metric === 'string' &&
      output.metrics &&
      typeof output.metrics === 'object' &&
      typeof (output.metrics as Record<string, unknown>)[output.primary_metric] === 'number'
        ? Number((output.metrics as Record<string, number>)[output.primary_metric])
        : null
    const summary = typeof output.summary === 'string' ? output.summary : ''
    const labelBits = [
      recommendation,
      primary != null && typeof output.primary_metric === 'string'
        ? `${output.primary_metric}=${primary.toFixed(4)}`
        : null,
      summary ? summary.slice(0, 48) : null,
    ].filter(Boolean)
    return {
      label: labelBits.join(' · ') || nodeRun.status,
      tone: recommendation === 'accept' ? 'accepted' : recommendation === 'reject' ? 'rejected' : nodeRun.status,
    }
  }
  return { label: nodeRun.status, tone: nodeRun.status }
}
