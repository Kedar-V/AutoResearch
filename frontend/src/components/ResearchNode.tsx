import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'
import type { CSSProperties } from 'react'

import { catalogItem, type AutoResearchNodeData } from '../nodeCatalog'

const HANDLE_SIDES: { id: string; position: Position }[] = [
  { id: 'top', position: Position.Top },
  { id: 'right', position: Position.Right },
  { id: 'bottom', position: Position.Bottom },
  { id: 'left', position: Position.Left },
]

export function ResearchNode({ data, selected }: NodeProps<Node<AutoResearchNodeData>>) {
  const item = catalogItem(data.nodeType)
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
      {HANDLE_SIDES.map(({ id, position }) => (
        <Handle
          key={`target-${id}`}
          id={id}
          type="target"
          position={position}
          className={`handle-${id}`}
        />
      ))}
      {HANDLE_SIDES.map(({ id, position }) => (
        <Handle
          key={`source-${id}`}
          id={id}
          type="source"
          position={position}
          className={`handle-${id}`}
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
