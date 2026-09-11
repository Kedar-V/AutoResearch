import { useEffect, useId, useState, type MouseEvent } from 'react'
import { Maximize2, X } from 'lucide-react'

import type { HypothesisRecord, TrialRecord } from '../types'

export type ProgressPoint = {
  index: number
  metric: number
  status: 'accepted' | 'rejected' | 'failed' | 'baseline'
  label: string
}

export function buildProgressPoints(
  hypotheses: HypothesisRecord[],
  trials: TrialRecord[],
  options: { metric?: string; baseline?: number } = {},
): ProgressPoint[] {
  const metric = options.metric ?? 'score'
  const baseline = options.baseline
  const points: ProgressPoint[] = []
  if (typeof baseline === 'number' && Number.isFinite(baseline)) {
    points.push({
      index: 0,
      metric: baseline,
      status: 'baseline',
      label: 'baseline',
    })
  }
  const orderedTrials = [...trials].sort(
    (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
  )
  const hypoById = new Map(hypotheses.map((hypo) => [hypo.id, hypo]))
  for (const trial of orderedTrials) {
    const value = trial.metrics?.[metric] ?? hypoById.get(trial.hypothesis_id)?.metrics?.[metric]
    if (typeof value !== 'number' || !Number.isFinite(value)) continue
    const status =
      trial.outcome === 'accepted'
        ? 'accepted'
        : trial.outcome === 'rejected'
          ? 'rejected'
          : trial.outcome === 'failed'
            ? 'failed'
            : trial.outcome === 'ran'
              ? 'rejected'
              : 'failed'
    points.push({
      index: points.length,
      metric: value,
      status,
      label: trial.hypothesis_id || trial.id,
    })
  }
  return points
}

export function runningChampion(
  points: ProgressPoint[],
  direction: 'minimize' | 'maximize',
): Array<{ index: number; metric: number }> {
  const kept = points.filter((point) => point.status === 'accepted' || point.status === 'baseline')
  const series: Array<{ index: number; metric: number }> = []
  let best: number | null = null
  for (const point of kept) {
    if (best === null) {
      best = point.metric
    } else {
      best = direction === 'minimize' ? Math.min(best, point.metric) : Math.max(best, point.metric)
    }
    series.push({ index: point.index, metric: best })
  }
  return series
}

type Props = {
  points: ProgressPoint[]
  direction?: 'minimize' | 'maximize'
  metricName?: string
  onSelectHypothesis?: (hypothesisId: string) => void
}

export function ProgressStaircase({
  points,
  direction = 'minimize',
  metricName = 'score',
  onSelectHypothesis,
}: Props) {
  const [expanded, setExpanded] = useState(false)
  const titleId = useId()

  useEffect(() => {
    if (!expanded) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setExpanded(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [expanded])

  if (points.length === 0) {
    return <div className="empty-state small">No scored experiments yet.</div>
  }

  const keptCount = points.filter((point) => point.status === 'accepted').length
  const trialCount = points.filter((point) => point.status !== 'baseline').length

  return (
    <>
      <div className="progress-staircase">
        <div className="progress-meta">
          <span>
            {trialCount} trials · {keptCount} kept
          </span>
          <span>{metricName} · {direction}</span>
        </div>
        <div
          className="progress-frame"
          role="button"
          tabIndex={0}
          onClick={() => setExpanded(true)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault()
              setExpanded(true)
            }
          }}
          aria-label="Expand progress staircase"
        >
          <Chart
            points={points}
            direction={direction}
            metricName={metricName}
            size="compact"
            onSelectHypothesis={onSelectHypothesis}
          />
          <span className="progress-expand-hint">
            <Maximize2 size={12} /> Expand
          </span>
        </div>
        <div className="progress-legend">
          <span><i className="swatch kept" />Kept</span>
          <span><i className="swatch discarded" />Discarded</span>
          <span><i className="swatch step" />Running best</span>
        </div>
      </div>

      {expanded && (
        <div className="progress-lightbox">
          <button
            type="button"
            className="slide-backdrop"
            aria-label="Close expanded progress"
            onClick={() => setExpanded(false)}
          />
          <div className="progress-lightbox-panel" role="dialog" aria-modal="true" aria-labelledby={titleId}>
            <header className="progress-lightbox-header">
              <div>
                <small id={titleId}>Progress staircase</small>
                <strong>
                  {points.length} experiments · {keptCount} kept · {metricName}
                </strong>
              </div>
              <button
                type="button"
                className="icon-button"
                aria-label="Close"
                onClick={() => setExpanded(false)}
              >
                <X size={16} />
              </button>
            </header>
            <div className="progress-lightbox-body">
              <Chart
                points={points}
                direction={direction}
                metricName={metricName}
                size="expanded"
                onSelectHypothesis={(hypothesisId) => {
                  onSelectHypothesis?.(hypothesisId)
                  setExpanded(false)
                }}
              />
              <div className="progress-legend">
                <span><i className="swatch kept" />Kept — click to open</span>
                <span><i className="swatch discarded" />Discarded — click to open</span>
                <span><i className="swatch step" />Running best</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

type ChartProps = {
  points: ProgressPoint[]
  direction: 'minimize' | 'maximize'
  metricName: string
  size: 'compact' | 'expanded'
  onSelectHypothesis?: (hypothesisId: string) => void
}

function Chart({ points, direction, metricName, size, onSelectHypothesis }: ChartProps) {
  const width = size === 'expanded' ? 920 : 280
  const height = size === 'expanded' ? 480 : 168
  const pad =
    size === 'expanded'
      ? { top: 28, right: 36, bottom: 40, left: 52 }
      : { top: 18, right: 14, bottom: 28, left: 36 }
  const plotW = width - pad.left - pad.right
  const plotH = height - pad.top - pad.bottom
  const metrics = points.map((point) => point.metric)
  const minY = Math.min(...metrics)
  const maxY = Math.max(...metrics)
  const spanY = Math.max(maxY - minY, 1e-6)
  const margin = spanY * 0.18
  const yMin = minY - margin
  const yMax = maxY + margin
  const maxX = Math.max(points[points.length - 1]?.index ?? 1, 1)
  const xScale = (index: number) => pad.left + (index / maxX) * plotW
  const yScale = (value: number) => pad.top + ((yMax - value) / (yMax - yMin)) * plotH

  const champion = runningChampion(points, direction)
  let stepPath = ''
  if (champion.length > 0) {
    stepPath = `M ${xScale(champion[0].index)} ${yScale(champion[0].metric)}`
    for (let i = 1; i < champion.length; i += 1) {
      stepPath += ` H ${xScale(champion[i].index)} V ${yScale(champion[i].metric)}`
    }
    stepPath += ` H ${xScale(maxX)}`
  }

  const kept = points.filter((point) => point.status === 'accepted')
  const discarded = points.filter(
    (point) => point.status === 'rejected' || point.status === 'failed',
  )
  const dotR = size === 'expanded' ? 7 : 4.5
  const discardR = size === 'expanded' ? 5.5 : 3.2

  const selectPoint = (event: MouseEvent, point: ProgressPoint) => {
    event.stopPropagation()
    event.preventDefault()
    if (point.status === 'baseline') return
    onSelectHypothesis?.(point.label)
  }

  return (
    <svg
      className={`progress-svg ${size}`}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`Progress staircase for ${metricName}`}
    >
      <line
        className="progress-axis"
        x1={pad.left}
        y1={pad.top}
        x2={pad.left}
        y2={height - pad.bottom}
      />
      <line
        className="progress-axis"
        x1={pad.left}
        y1={height - pad.bottom}
        x2={width - pad.right}
        y2={height - pad.bottom}
      />
      <text className="progress-tick" x={pad.left - 6} y={yScale(yMax) + 3} textAnchor="end">
        {formatTick(yMax)}
      </text>
      <text className="progress-tick" x={pad.left - 6} y={yScale(yMin) + 3} textAnchor="end">
        {formatTick(yMin)}
      </text>
      <text className="progress-tick" x={pad.left} y={height - 10} textAnchor="start">
        0
      </text>
      <text className="progress-tick" x={width - pad.right} y={height - 10} textAnchor="end">
        {maxX}
      </text>
      {stepPath && <path className="progress-step" d={stepPath} fill="none" />}
      {discarded.map((point) => (
        <circle
          key={`d-${point.index}-${point.label}`}
          className="progress-dot discarded clickable"
          cx={xScale(point.index)}
          cy={yScale(point.metric)}
          r={discardR}
          onClick={(event) => selectPoint(event, point)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault()
              selectPoint(event as unknown as MouseEvent, point)
            }
          }}
          tabIndex={0}
          role="button"
          aria-label={`Open hypothesis ${point.label}`}
        >
          <title>{`${point.label}: ${point.metric} (discarded)`}</title>
        </circle>
      ))}
      {kept.map((point) => (
        <g key={`k-${point.index}-${point.label}`}>
          <circle
            className="progress-dot kept clickable"
            cx={xScale(point.index)}
            cy={yScale(point.metric)}
            r={dotR}
            onClick={(event) => selectPoint(event, point)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                selectPoint(event as unknown as MouseEvent, point)
              }
            }}
            tabIndex={0}
            role="button"
            aria-label={`Open hypothesis ${point.label}`}
          >
            <title>{`${point.label}: ${point.metric} (kept)`}</title>
          </circle>
          <text
            className="progress-label"
            x={xScale(point.index) + (size === 'expanded' ? 8 : 5)}
            y={yScale(point.metric) - (size === 'expanded' ? 10 : 6)}
            onClick={(event) => selectPoint(event, point)}
          >
            {point.label}
          </text>
        </g>
      ))}
    </svg>
  )
}

function formatTick(value: number): string {
  if (Math.abs(value) >= 100) return value.toFixed(0)
  if (Math.abs(value) >= 10) return value.toFixed(1)
  return value.toFixed(2)
}
