import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'
import type { CSSProperties } from 'react'

import { catalogItem, type AutoResearchNodeData } from '../nodeCatalog'

export function ResearchNode({ data, selected }: NodeProps<Node<AutoResearchNodeData>>) {
  const item = catalogItem(data.nodeType)
  return (
    <div className={`research-node ${selected ? 'selected' : ''}`} style={{ '--node-color': item.color } as CSSProperties}>
      <Handle type="target" position={Position.Left} />
      <div className="node-header"><span className="node-icon">{item.icon}</span><span>{item.label}</span></div>
      <strong>{data.name}</strong>
      <small>{item.description}</small>
      <div className="port-label input">in</div><div className="port-label output">out</div>
      <Handle type="source" position={Position.Right} />
    </div>
  )
}
