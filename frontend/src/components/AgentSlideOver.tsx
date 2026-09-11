import { useEffect, useState } from 'react'
import { ArrowLeft, X } from 'lucide-react'

import { getTrialDiff, listHypotheses, listTrials } from '../api'
import type { HypothesisRecord, ProjectRead, TrialRecord } from '../types'
import { CodeDiffView } from './CodeDiffView'
import { ProgressStaircase, buildProgressPoints } from './ProgressStaircase'

type View =
  | { kind: 'agent' }
  | { kind: 'hypothesis'; id: string }
  | { kind: 'trial'; hypothesisId: string; trialId: string }

interface Props {
  open: boolean
  onClose: () => void
  project: ProjectRead | null
  systemPrompt: string
  model: string
  onSystemPromptChange: (value: string) => void
  onModelChange: (value: string) => void
  inboundContext: string[]
  focusHypothesisId?: string | null
  onFocusHandled?: () => void
}

export function AgentSlideOver({
  open,
  onClose,
  project,
  systemPrompt,
  model,
  onSystemPromptChange,
  onModelChange,
  inboundContext,
  focusHypothesisId = null,
  onFocusHandled,
}: Props) {
  const [view, setView] = useState<View>({ kind: 'agent' })
  const [hypotheses, setHypotheses] = useState<HypothesisRecord[]>([])
  const [trials, setTrials] = useState<TrialRecord[]>([])
  const [diff, setDiff] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open || !project) return
    Promise.all([listHypotheses(project.id), listTrials(project.id)])
      .then(([nextHypos, nextTrials]) => {
        setHypotheses(nextHypos)
        setTrials(nextTrials)
        setError('')
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load ledger'))
  }, [open, project])

  useEffect(() => {
    if (!open) {
      setView({ kind: 'agent' })
      return
    }
    if (!focusHypothesisId) return
    setView({ kind: 'hypothesis', id: focusHypothesisId })
    onFocusHandled?.()
  }, [open, focusHypothesisId, onFocusHandled])

  useEffect(() => {
    if (!open || !project || view.kind !== 'trial') {
      setDiff('')
      return
    }
    getTrialDiff(project.id, view.trialId)
      .then((payload) =>
        setDiff(
          payload.diff?.trim()
            ? payload.diff
            : 'No file changes. The execution step did not modify allow-listed files.',
        ),
      )
      .catch((err) =>
        setDiff(err instanceof Error ? `Diff unavailable: ${err.message}` : 'Diff unavailable.'),
      )
  }, [open, project, view])

  if (!open) return null

  const activeHypothesis =
    view.kind === 'hypothesis' || view.kind === 'trial'
      ? hypotheses.find((item) => item.id === (view.kind === 'hypothesis' ? view.id : view.hypothesisId))
      : null
  const activeTrial =
    view.kind === 'trial' ? trials.find((item) => item.id === view.trialId) : null
  const hypoTrials = activeHypothesis
    ? trials.filter((item) => item.hypothesis_id === activeHypothesis.id)
    : []

  const crumb =
    view.kind === 'agent'
      ? 'Agent'
      : view.kind === 'hypothesis'
        ? `Agent / ${view.id}`
        : `Agent / ${view.hypothesisId} / ${view.trialId}`

  return (
    <div className="slide-root">
      <button className="slide-backdrop" aria-label="Close" onClick={onClose} />
      <aside className="slide-over">
        <header className="slide-header">
          <div>
            <small>{crumb}</small>
            <strong>Hypothesis agent</strong>
          </div>
          <div className="slide-actions">
            {view.kind !== 'agent' && (
              <button
                className="button secondary"
                onClick={() =>
                  setView(
                    view.kind === 'trial'
                      ? { kind: 'hypothesis', id: view.hypothesisId }
                      : { kind: 'agent' },
                  )
                }
              >
                <ArrowLeft size={14} /> Back
              </button>
            )}
            <button className="icon-button" onClick={onClose} aria-label="Close panel">
              <X size={16} />
            </button>
          </div>
        </header>

        {error && <p className="form-error slide-pad">{error}</p>}

        {view.kind === 'agent' && (
          <div className="slide-body">
            <label>
              System prompt
              <textarea
                rows={8}
                value={systemPrompt}
                onChange={(event) => onSystemPromptChange(event.target.value)}
              />
            </label>
            <label>
              Model
              <input value={model} onChange={(event) => onModelChange(event.target.value)} />
            </label>
            <section>
              <h3>Inbound context</h3>
              {inboundContext.length === 0 ? (
                <p className="muted">No upstream nodes connected.</p>
              ) : (
                <ul className="chip-list">
                  {inboundContext.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              )}
            </section>
            <section>
              <h3>Progress</h3>
              <ProgressStaircase
                points={buildProgressPoints(hypotheses, trials, { metric: 'score' })}
                direction="minimize"
                metricName="score"
                onSelectHypothesis={(hypothesisId) =>
                  setView({ kind: 'hypothesis', id: hypothesisId })
                }
              />
            </section>
            <section>
              <h3>Hypotheses</h3>
              {hypotheses.length === 0 ? (
                <p className="muted">No hypotheses yet. Run the workflow to populate the ledger.</p>
              ) : (
                <div className="card-list">
                  {hypotheses.map((hypo) => (
                    <button
                      key={hypo.id}
                      className="info-card"
                      onClick={() => setView({ kind: 'hypothesis', id: hypo.id })}
                    >
                      <span className={`status-chip ${hypo.status}`}>{hypo.status}</span>
                      <strong>{hypo.id}</strong>
                      <small>{hypo.title}</small>
                      <small>{hypo.branch}</small>
                    </button>
                  ))}
                </div>
              )}
            </section>
          </div>
        )}

        {view.kind === 'hypothesis' && activeHypothesis && (
          <div className="slide-body">
            <span className={`status-chip ${activeHypothesis.status}`}>{activeHypothesis.status}</span>
            <h2>{activeHypothesis.id}</h2>
            <p>{activeHypothesis.title}</p>
            <section>
              <h3>Detailed brief</h3>
              <pre className="code-block hypothesis-brief">{activeHypothesis.description}</pre>
            </section>
            <dl className="detail-grid">
              <div><dt>Branch</dt><dd>{activeHypothesis.branch}</dd></div>
              <div><dt>Base</dt><dd>{activeHypothesis.base_commit.slice(0, 10)}</dd></div>
            </dl>
            <section>
              <h3>What worked</h3>
              <p>{activeHypothesis.what_worked || '—'}</p>
            </section>
            <section>
              <h3>What didn’t</h3>
              <p>{activeHypothesis.what_did_not || '—'}</p>
            </section>
            <section>
              <h3>Metrics</h3>
              <pre className="code-block">{JSON.stringify(activeHypothesis.metrics || {}, null, 2)}</pre>
            </section>
            <section>
              <h3>Trials</h3>
              <div className="card-list">
                {hypoTrials.map((trial) => (
                  <button
                    key={trial.id}
                    className="info-card"
                    onClick={() =>
                      setView({
                        kind: 'trial',
                        hypothesisId: activeHypothesis.id,
                        trialId: trial.id,
                      })
                    }
                  >
                    <span className={`status-chip ${trial.outcome}`}>{trial.outcome}</span>
                    <strong>{trial.id}</strong>
                    <small>{trial.branch}</small>
                  </button>
                ))}
              </div>
            </section>
          </div>
        )}

        {view.kind === 'trial' && activeTrial && (
          <div className="slide-body">
            <span className={`status-chip ${activeTrial.outcome}`}>{activeTrial.outcome}</span>
            <h2>{activeTrial.id}</h2>
            <dl className="detail-grid">
              <div><dt>Branch</dt><dd>{activeTrial.branch}</dd></div>
              <div>
                <dt>Commit</dt>
                <dd>{activeTrial.candidate_commit?.slice(0, 10) || '—'}</dd>
              </div>
            </dl>
            {activeTrial.outcome === 'failed' || activeTrial.outcome === 'rejected' ? (
              <>
                <section>
                  <h3>What failed</h3>
                  <p>{activeTrial.error || activeTrial.what_changed || '—'}</p>
                </section>
                <section>
                  <h3>Next step</h3>
                  <p>{activeTrial.next_step || '—'}</p>
                </section>
              </>
            ) : (
              <section>
                <h3>What changed</h3>
                <p>{activeTrial.what_changed || '—'}</p>
              </section>
            )}
            <section>
              <h3>Metrics</h3>
              <pre className="code-block">{JSON.stringify(activeTrial.metrics || {}, null, 2)}</pre>
            </section>
            <section>
              <h3>Code diff</h3>
              {diff ? (
                <CodeDiffView diff={diff} emptyLabel="No file changes." />
              ) : (
                <p className="muted">Loading…</p>
              )}
            </section>
          </div>
        )}
      </aside>
    </div>
  )
}
