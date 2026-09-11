import type { NodeRunRead, RunRead } from '../types'

export interface RunProgress {
  status: string
  hypothesisCurrent: number
  hypothesisTotal: number
  trialCurrent: number
  trialTotal: number
  attemptCurrent: number
  attemptTotal: number
  overallCurrent: number
  overallTotal: number
  hypothesisId: string | null
  trialId: string | null
  currentNode: string | null
  fraction: number
}

export function parseHypothesisIndex(hypothesisId: string | null | undefined): number {
  if (!hypothesisId) return 0
  const match = /H(\d+)/i.exec(hypothesisId)
  return match ? Number(match[1]) : 0
}

export function parseTrialAttempt(trialId: string | null | undefined): number {
  if (!trialId) return 0
  const match = /T(\d+)/i.exec(trialId)
  return match ? Number(match[1]) : 0
}

export function deriveRunProgress(
  run: RunRead | null,
  options: { maxHypotheses: number; maxRetries: number },
): RunProgress {
  const hypothesisTotal = Math.max(1, options.maxHypotheses)
  const attemptTotal = Math.max(1, options.maxRetries)
  const overallTotal = hypothesisTotal * attemptTotal

  if (!run) {
    return {
      status: 'idle',
      hypothesisCurrent: 0,
      hypothesisTotal,
      trialCurrent: 0,
      trialTotal: overallTotal,
      attemptCurrent: 0,
      attemptTotal,
      overallCurrent: 0,
      overallTotal,
      hypothesisId: null,
      trialId: null,
      currentNode: null,
      fraction: 0,
    }
  }

  const trialRuns = run.node_runs.filter((nodeRun) => nodeRun.node_type === 'trial')
  const overallCurrent = trialRuns.length
  const hypothesisCurrent = Math.max(
    parseHypothesisIndex(run.hypothesis_id),
    run.node_runs.filter((nodeRun) => nodeRun.node_type === 'hypothesis').length,
  )
  const attemptCurrent = Math.max(
    parseTrialAttempt(run.trial_id),
    latestAttempt(trialRuns),
  )

  const currentNode =
    [...run.node_runs].reverse().find((nodeRun) => nodeRun.status === 'running')?.node_id ??
    run.node_runs.at(-1)?.node_id ??
    null

  const fraction = Math.min(1, overallCurrent / Math.max(overallTotal, 1))

  return {
    status: run.status,
    hypothesisCurrent,
    hypothesisTotal,
    trialCurrent: overallCurrent,
    trialTotal: overallTotal,
    attemptCurrent,
    attemptTotal,
    overallCurrent,
    overallTotal,
    hypothesisId: run.hypothesis_id,
    trialId: run.trial_id,
    currentNode,
    fraction,
  }
}

function latestAttempt(trialRuns: NodeRunRead[]): number {
  let max = 0
  for (const nodeRun of trialRuns) {
    const fromOutput = Number(nodeRun.output.number)
    if (Number.isFinite(fromOutput) && fromOutput > max) max = fromOutput
    const fromId = parseTrialAttempt(String(nodeRun.output.trial_id ?? nodeRun.node_id))
    if (fromId > max) max = fromId
  }
  return max
}

export function LiveRunStatus({ progress }: { progress: RunProgress }) {
  const live =
    progress.status === 'queued' ||
    progress.status === 'running' ||
    progress.status === 'paused'
  const label =
    progress.status === 'idle'
      ? 'Idle'
      : progress.status === 'queued'
        ? 'Queued'
        : progress.status === 'running'
          ? 'Running'
          : progress.status === 'paused'
            ? 'Paused'
            : progress.status === 'succeeded'
              ? 'Complete'
              : progress.status === 'failed'
                ? 'Failed'
                : progress.status === 'cancelled'
                  ? 'Cancelled'
                  : progress.status

  return (
    <div className={`live-run-status ${progress.status}`} aria-live="polite">
      <div className="live-run-status-header">
        <span className={`live-run-dot ${live && progress.status !== 'paused' ? 'pulse' : ''}`} />
        <strong>{label}</strong>
        <small>
          {progress.overallCurrent}/{progress.overallTotal} trials
        </small>
      </div>

      <div className="live-run-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress.fraction * 100)}>
        <span style={{ width: `${Math.round(progress.fraction * 100)}%` }} />
      </div>

      <dl className="live-run-metrics">
        <div>
          <dt>Hypothesis</dt>
          <dd>
            {progress.hypothesisCurrent}/{progress.hypothesisTotal}
          </dd>
        </div>
        <div>
          <dt>Retry</dt>
          <dd>
            {progress.attemptCurrent}/{progress.attemptTotal}
          </dd>
        </div>
      </dl>

      <div className="live-run-current">
        <span>{progress.hypothesisId ?? '—'}</span>
        <span aria-hidden>·</span>
        <span>{progress.trialId ?? '—'}</span>
        {progress.currentNode && (
          <>
            <span aria-hidden>·</span>
            <span className="live-run-node">{progress.currentNode}</span>
          </>
        )}
      </div>
    </div>
  )
}
