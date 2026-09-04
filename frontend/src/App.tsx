import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  addEdge,
  useEdgesState,
  useNodesState,
  type Connection,
  type Node,
  type NodeMouseHandler,
  type ReactFlowInstance,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Activity, GitBranch, Play, Save, Workflow } from 'lucide-react'

import { createRun, getRun, saveWorkflow } from './api'
import { ResearchNode } from './components/ResearchNode'
import { NODE_CATALOG, type AutoResearchNodeData } from './nodeCatalog'
import type { RunRead, WorkflowDefinition } from './types'
import {
  buildStarterEdges,
  buildStarterNodes,
  createCanvasNode,
  toWorkflowDefinition,
} from './workflow'
import './App.css'

const nodeTypes = { research: ResearchNode }
const workflowId = 'default-research-loop'
const starterNodes = buildStarterNodes()

function CanvasApp() {
  const [instance, setInstance] = useState<ReactFlowInstance<Node<AutoResearchNodeData>>>()
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<AutoResearchNodeData>>(
    starterNodes,
  )
  const [edges, setEdges, onEdgesChange] = useEdgesState(buildStarterEdges())
  const [selectedId, setSelectedId] = useState<string | null>(nodes[0]?.id ?? null)
  const [configDraft, setConfigDraft] = useState(() =>
    JSON.stringify(starterNodes[0]?.data.config ?? {}, null, 2),
  )
  const [configError, setConfigError] = useState('')
  const [notice, setNotice] = useState('Ready')
  const [activeRun, setActiveRun] = useState<RunRead | null>(null)

  const selected = nodes.find((node) => node.id === selectedId) ?? null
  const running = activeRun?.status === 'queued' || activeRun?.status === 'running'

  useEffect(() => {
    if (!activeRun || !running) return
    const timer = window.setInterval(async () => {
      try {
        const next = await getRun(activeRun.id)
        setActiveRun(next)
        if (next.status === 'succeeded') setNotice('Run completed')
        if (next.status === 'failed') setNotice('Run failed')
      } catch (error) {
        setNotice(error instanceof Error ? error.message : 'Could not refresh run')
      }
    }, 1000)
    return () => window.clearInterval(timer)
  }, [activeRun, running])

  const onConnect = useCallback(
    (connection: Connection) =>
      setEdges((current) =>
        addEdge({ ...connection, animated: true, style: { stroke: '#36d399' } }, current),
      ),
    [setEdges],
  )

  const onNodeClick: NodeMouseHandler<Node<AutoResearchNodeData>> = useCallback((_, node) => {
    setSelectedId(node.id)
    setConfigDraft(JSON.stringify(node.data.config, null, 2))
    setConfigError('')
  }, [])

  const onDragStart = (event: React.DragEvent, type: AutoResearchNodeData['nodeType']) => {
    event.dataTransfer.setData('application/autoresearch-node', type)
    event.dataTransfer.effectAllowed = 'move'
  }

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault()
      const nodeType = event.dataTransfer.getData(
        'application/autoresearch-node',
      ) as AutoResearchNodeData['nodeType']
      if (!nodeType || !instance) return
      const position = instance.screenToFlowPosition({ x: event.clientX, y: event.clientY })
      const node = createCanvasNode(nodeType, position)
      setNodes((current) => [...current, node])
      setSelectedId(node.id)
      setConfigDraft(JSON.stringify(node.data.config, null, 2))
      setConfigError('')
    },
    [instance, setNodes],
  )

  const updateName = (name: string) => {
    if (!selectedId) return
    setNodes((current) =>
      current.map((node) =>
        node.id === selectedId ? { ...node, data: { ...node.data, name } } : node,
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
    () => toWorkflowDefinition(workflowId, 'Default research loop', nodes, edges),
    [nodes, edges],
  )

  const handleSave = async () => {
    try {
      await saveWorkflow(definition)
      setNotice('Workflow saved')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Save failed')
    }
  }

  const handleRun = async () => {
    try {
      await saveWorkflow(definition)
      const run = await createRun(definition.id)
      setActiveRun(run)
      setNotice('Run started')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Run failed to start')
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark"><Workflow size={19} /></div>
          <div><strong>AutoResearch</strong><span>Git-native experiment canvas</span></div>
        </div>
        <div className="topbar-actions">
          <span className="notice"><span className="status-dot" />{notice}</span>
          <button className="button secondary" onClick={handleSave}><Save size={16} />Save</button>
          <button className="button primary" onClick={handleRun} disabled={running}>
            <Play size={16} fill="currentColor" />{running ? 'Running…' : 'Run workflow'}
          </button>
        </div>
      </header>

      <section className="workspace-grid">
        <aside className="palette panel">
          <div className="panel-heading"><span>Node library</span><small>Drag to canvas</small></div>
          <div className="palette-list">
            {NODE_CATALOG.map((item) => (
              <button
                className="palette-item"
                draggable
                key={item.type}
                onDragStart={(event) => onDragStart(event, item.type)}
              >
                <span className="palette-icon" style={{ color: item.color }}>{item.icon}</span>
                <span><strong>{item.label}</strong><small>{item.description}</small></span>
              </button>
            ))}
          </div>
          <div className="legend">
            <GitBranch size={15} /><span>Every run creates auditable Git branches and notes.</span>
          </div>
        </aside>

        <div
          className="canvas-wrap"
          onDrop={onDrop}
          onDragOver={(event) => {
            event.preventDefault()
            event.dataTransfer.dropEffect = 'move'
          }}
        >
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onInit={setInstance}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
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
        </div>

        <aside className="inspector panel">
          <div className="panel-heading"><span>Inspector</span><small>{selected?.data.nodeType ?? 'No selection'}</small></div>
          {selected ? (
            <div className="inspector-form">
              <label>Node name<input value={selected.data.name} onChange={(event) => updateName(event.target.value)} /></label>
              <label>Configuration<textarea rows={16} value={configDraft} onChange={(event) => setConfigDraft(event.target.value)} spellCheck={false} /></label>
              {configError && <p className="form-error">{configError}</p>}
              <button className="button secondary full" onClick={applyConfig}>Apply configuration</button>
            </div>
          ) : <div className="empty-state">Select a node to edit its name and runtime configuration.</div>}

          <div className="run-panel">
            <div className="panel-heading compact"><span>Latest run</span><Activity size={15} /></div>
            {!activeRun ? <div className="empty-state small">No run started in this session.</div> : (
              <>
                <div className={`run-status ${activeRun.status}`}>{activeRun.status}</div>
                <dl className="run-meta">
                  <div><dt>Hypothesis</dt><dd>{activeRun.hypothesis_id ?? '—'}</dd></div>
                  <div><dt>Trial</dt><dd>{activeRun.trial_id ?? '—'}</dd></div>
                </dl>
                <div className="node-results">
                  {activeRun.node_runs.map((nodeRun) => (
                    <div className="node-result" key={nodeRun.id}>
                      <span className={`result-dot ${nodeRun.status}`} />
                      <span>{nodeRun.node_id}</span><small>{nodeRun.status}</small>
                    </div>
                  ))}
                </div>
                {activeRun.error && <p className="form-error">{activeRun.error}</p>}
              </>
            )}
          </div>
        </aside>
      </section>
    </main>
  )
}

export default function App() {
  return <ReactFlowProvider><CanvasApp /></ReactFlowProvider>
}
