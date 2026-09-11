import { Target } from 'lucide-react'

import type { FrontierPoint, FrontierRead } from '../types'

interface FrontierPanelProps {
  frontier: FrontierRead | null
  onSelect: (commit: string) => void
  selecting?: boolean
}

export function FrontierPanel({ frontier, onSelect, selecting }: FrontierPanelProps) {
  const points = frontier?.points ?? []
  const preferred = frontier?.preferred_base_commit

  return (
    <div className="run-panel">
      <div className="panel-heading compact">
        <span>Pareto frontier</span>
        <Target size={15} />
      </div>
      {points.length === 0 ? (
        <div className="empty-state small">No non-dominated points yet.</div>
      ) : (
        <ul className="frontier-list">
          {points.map((point: FrontierPoint) => {
            const short = point.commit.slice(0, 8)
            const isPreferred = preferred === point.commit
            const metrics = Object.entries(point.metrics)
              .map(([name, value]) => `${name}=${formatMetric(value)}`)
              .join(' · ')
            return (
              <li key={point.commit} className={isPreferred ? 'preferred' : undefined}>
                <div className="frontier-meta">
                  <strong>{point.trial_id}</strong>
                  <code>{short}</code>
                  {isPreferred && <span className="frontier-badge">next base</span>}
                </div>
                <div className="frontier-metrics">{metrics}</div>
                <button
                  className="button secondary small"
                  disabled={selecting || isPreferred}
                  onClick={() => onSelect(point.commit)}
                >
                  Seed next hypothesis
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

function formatMetric(value: number): string {
  if (!Number.isFinite(value)) return String(value)
  if (Math.abs(value) >= 100) return value.toFixed(1)
  return value.toPrecision(4)
}
