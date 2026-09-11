import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'
import type { CSSProperties } from 'react'

import { catalogItem, type AutoResearchNodeData } from '../nodeCatalog'
import type { ResearchNodeType } from '../types'

interface PortSpec {
  id: string
  type: 'source' | 'target'
  position: Position
}

/** Named ports per recipe role — not generic 8-way sockets. */
const PORTS_BY_TYPE: Partial<Record<ResearchNodeType, PortSpec[]>> = {
  hypothesis: [
    { id: 'left', type: 'target', position: Position.Left },
    { id: 'top', type: 'target', position: Position.Top },
    { id: 'bottom', type: 'target', position: Position.Bottom },
    { id: 'right', type: 'source', position: Position.Right },
  ],
  execution: [
    { id: 'left', type: 'target', position: Position.Left },
    { id: 'right', type: 'source', position: Position.Right },
    { id: 'bottom', type: 'source', position: Position.Bottom },
  ],
  eval_script: [
    { id: 'left', type: 'target', position: Position.Left },
    { id: 'top', type: 'source', position: Position.Top },
    { id: 'right', type: 'source', position: Position.Right },
  ],
  evaluation: [
    { id: 'left', type: 'target', position: Position.Left },
    { id: 'bottom', type: 'target', position: Position.Bottom },
    { id: 'right', type: 'source', position: Position.Right },
  ],
  metric_gate: [
    { id: 'left', type: 'target', position: Position.Left },
    { id: 'right', type: 'source', position: Position.Right },
  ],
  git_decision: [
    { id: 'left', type: 'target', position: Position.Left },
    { id: 'bottom', type: 'source', position: Position.Bottom },
  ],
  database: [],
  script: [
    { id: 'left', type: 'target', position: Position.Left },
    { id: 'right', type: 'source', position: Position.Right },
  ],
  trial: [],
}

export function ResearchNode({ data, selected }: NodeProps<Node<AutoResearchNodeData>>) {
  const item = catalogItem(data.nodeType)
  const ports = PORTS_BY_TYPE[data.nodeType] ?? []
  const className = [
    'research-node',
    selected ? 'selected' : '',
    data.executing ? 'executing' : '',
    data.liveStatus && data.liveStatus !== 'running' ? `live-${data.liveStatus}` : '',
    data.nodeType === 'database' ? 'db-node' : '',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div className={className} style={{ '--node-color': item.color } as CSSProperties}>
      {ports.map((port) => (
        <Handle
          key={`${port.type}-${port.id}`}
          id={port.id}
          type={port.type}
          position={port.position}
          className={`handle-${port.id}`}
        />
      ))}
      <div className="node-header">
        <span className="node-icon">{item.icon}</span>
        <span>{item.label}</span>
        {data.executing && <span className="live-exec-pill">Running</span>}
        {data.badge != null && data.badge !== '' && (
          <span className="trial-badge">{data.badge}</span>
        )}
      </div>
      <strong>{data.name}</strong>
      <small>{item.description}</small>
    </div>
  )
}
