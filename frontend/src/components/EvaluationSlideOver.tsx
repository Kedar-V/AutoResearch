import { useEffect, useState } from 'react'
import { ArrowLeft, X } from 'lucide-react'

import { listEvaluations } from '../api'
import type { EvaluationRecord, ProjectRead } from '../types'

type View = { kind: 'agent' } | { kind: 'evaluation'; id: string }

const EMPTY_SCHEMA_HINT = `{
  "type": "object",
  "additionalProperties": false,
  "required": ["confidence", "attribution"],
  "properties": {
    "confidence": { "type": "number", "minimum": 0, "maximum": 1 },
    "attribution": { "type": "string" },
    "failure_modes": { "type": "array", "items": { "type": "string" } }
  }
}`

interface Props {
  open: boolean
  onClose: () => void
  project: ProjectRead | null
  systemPrompt: string
  model: string
  explainabilitySchema: unknown
  onSystemPromptChange: (value: string) => void
  onModelChange: (value: string) => void
  onExplainabilitySchemaChange: (value: unknown) => void
  inboundContext: string[]
  onOpenHypothesis?: (hypothesisId: string) => void
}

function schemaToEditorText(schema: unknown): string {
  if (schema == null || schema === false) return ''
  if (typeof schema === 'string') return schema
  try {
    return JSON.stringify(schema, null, 2)
  } catch {
    return ''
  }
}

export function EvaluationSlideOver({
  open,
  onClose,
  project,
  systemPrompt,
  model,
  explainabilitySchema,
  onSystemPromptChange,
  onModelChange,
  onExplainabilitySchemaChange,
  inboundContext,
  onOpenHypothesis,
}: Props) {
  const [view, setView] = useState<View>({ kind: 'agent' })
  const [evaluations, setEvaluations] = useState<EvaluationRecord[]>([])
  const [error, setError] = useState('')
  const [schemaText, setSchemaText] = useState(() => schemaToEditorText(explainabilitySchema))
  const [schemaError, setSchemaError] = useState('')

  useEffect(() => {
    if (!open || !project) return
    listEvaluations(project.id)
      .then((rows) => {
        setEvaluations(rows)
        setError('')
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load evaluations'))
  }, [open, project])

  useEffect(() => {
    if (!open) setView({ kind: 'agent' })
  }, [open])

  useEffect(() => {
    if (open) {
      setSchemaText(schemaToEditorText(explainabilitySchema))
      setSchemaError('')
    }
  }, [open, explainabilitySchema])

  if (!open) return null

  const active =
    view.kind === 'evaluation'
      ? evaluations.find((item) => item.evaluation_id === view.id) ?? null
      : null

  const crumb =
    view.kind === 'agent' ? 'Evaluation agent' : `Evaluation agent / ${view.id}`

  const commitSchemaText = (text: string) => {
    const trimmed = text.trim()
    if (!trimmed) {
      setSchemaError('')
      onExplainabilitySchemaChange(null)
      return
    }
    try {
      const parsed = JSON.parse(trimmed) as unknown
      if (parsed !== null && typeof parsed !== 'object') {
        setSchemaError('explainability_schema must be a JSON object')
        return
      }
      setSchemaError('')
      onExplainabilitySchemaChange(parsed)
    } catch (err) {
      setSchemaError(err instanceof Error ? err.message : 'Invalid JSON')
    }
  }

  const explainabilityEntries =
    active?.explainability && typeof active.explainability === 'object'
      ? Object.entries(active.explainability)
      : []

  return (
    <div className="slide-root">
      <button className="slide-backdrop" aria-label="Close" onClick={onClose} />
      <aside className="slide-over">
        <header className="slide-header">
          <div>
            <small>{crumb}</small>
            <strong>Evaluation agent</strong>
          </div>
          <div className="slide-actions">
            {view.kind !== 'agent' && (
              <button className="button secondary" onClick={() => setView({ kind: 'agent' })}>
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
            <label>
              Explainability schema (JSON)
              <small className="muted" style={{ display: 'block', marginBottom: 6 }}>
                Optional. Custom fields the evaluation agent must fill under{' '}
                <code>explainability</code>. Clear to disable. Does not affect the metric gate.
              </small>
              <textarea
                rows={12}
                value={schemaText}
                placeholder={EMPTY_SCHEMA_HINT}
                spellCheck={false}
                onChange={(event) => {
                  setSchemaText(event.target.value)
                  setSchemaError('')
                }}
                onBlur={() => commitSchemaText(schemaText)}
              />
            </label>
            {schemaError && <p className="form-error">{schemaError}</p>}
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
              <h3>Previous evaluations</h3>
              {evaluations.length === 0 ? (
                <p className="muted">No evaluations yet. Run the workflow to populate history.</p>
              ) : (
                <div className="card-list">
                  {evaluations.map((item) => {
                    const primary = item.metrics[item.primary_metric]
                    const delta = item.deltas[item.primary_metric]
                    return (
                      <button
                        key={item.evaluation_id}
                        className="info-card"
                        onClick={() => setView({ kind: 'evaluation', id: item.evaluation_id })}
                      >
                        <span className={`status-chip ${item.recommendation}`}>
                          {item.recommendation}
                        </span>
                        <strong>{item.trial_id}</strong>
                        <small>
                          {item.primary_metric}
                          {typeof primary === 'number' ? `=${primary.toFixed(4)}` : ''}
                          {typeof delta === 'number'
                            ? ` (Δ ${delta >= 0 ? '+' : ''}${delta.toFixed(4)})`
                            : ''}
                        </small>
                        <small>{item.summary}</small>
                        <small>{new Date(item.created_at).toLocaleString()}</small>
                      </button>
                    )
                  })}
                </div>
              )}
            </section>
          </div>
        )}

        {view.kind === 'evaluation' && active && (
          <div className="slide-body">
            <span className={`status-chip ${active.recommendation}`}>{active.recommendation}</span>
            <h2>{active.trial_id}</h2>
            <p>{active.summary}</p>
            <dl className="detail-grid">
              <div>
                <dt>Hypothesis</dt>
                <dd>
                  {onOpenHypothesis ? (
                    <button
                      className="linkish"
                      onClick={() => onOpenHypothesis(active.hypothesis_id)}
                    >
                      {active.hypothesis_id}
                    </button>
                  ) : (
                    active.hypothesis_id
                  )}
                </dd>
              </div>
              <div>
                <dt>Status</dt>
                <dd>{active.status}</dd>
              </div>
              <div>
                <dt>Primary</dt>
                <dd>
                  {active.primary_metric} ({active.direction})
                </dd>
              </div>
              <div>
                <dt>Evaluation id</dt>
                <dd>{active.evaluation_id}</dd>
              </div>
            </dl>
            <section>
              <h3>Rationale</h3>
              <p>{active.rationale || '—'}</p>
            </section>
            <section>
              <h3>Risks</h3>
              <p>{active.risks || '—'}</p>
            </section>
            {explainabilityEntries.length > 0 && (
              <section>
                <h3>Explainability</h3>
                {active.explainability_schema_hash ? (
                  <small className="muted">
                    schema {active.explainability_schema_hash}
                  </small>
                ) : null}
                <dl className="detail-grid">
                  {explainabilityEntries.map(([key, value]) => (
                    <div key={key}>
                      <dt>{key}</dt>
                      <dd>
                        {typeof value === 'string' || typeof value === 'number'
                          ? String(value)
                          : JSON.stringify(value)}
                      </dd>
                    </div>
                  ))}
                </dl>
              </section>
            )}
            <section>
              <h3>Signals</h3>
              <dl className="detail-grid">
                <div>
                  <dt>Improved</dt>
                  <dd>{active.signals.improved.join(', ') || '—'}</dd>
                </div>
                <div>
                  <dt>Regressed</dt>
                  <dd>{active.signals.regressed.join(', ') || '—'}</dd>
                </div>
                <div>
                  <dt>Unchanged</dt>
                  <dd>{active.signals.unchanged.join(', ') || '—'}</dd>
                </div>
              </dl>
            </section>
            <section>
              <h3>Metrics vs champion</h3>
              <pre className="code-block">
                {JSON.stringify(
                  {
                    metrics: active.metrics,
                    champion_metrics: active.champion_metrics,
                    deltas: active.deltas,
                  },
                  null,
                  2,
                )}
              </pre>
            </section>
            <section>
              <h3>Evidence</h3>
              <dl className="detail-grid">
                <div>
                  <dt>Candidate</dt>
                  <dd>{active.evidence.candidate_commit.slice(0, 10) || '—'}</dd>
                </div>
                <div>
                  <dt>Evaluator</dt>
                  <dd>{active.evidence.evaluator_commit.slice(0, 10) || '—'}</dd>
                </div>
                <div>
                  <dt>Duration</dt>
                  <dd>
                    {typeof active.evidence.duration_seconds === 'number'
                      ? `${active.evidence.duration_seconds.toFixed(2)}s`
                      : '—'}
                  </dd>
                </div>
                <div>
                  <dt>Model / prompt</dt>
                  <dd>
                    {active.model || '—'}
                    {active.system_prompt_hash ? ` · ${active.system_prompt_hash}` : ''}
                  </dd>
                </div>
              </dl>
              {active.evidence.stdout_excerpt ? (
                <pre className="code-block">{active.evidence.stdout_excerpt}</pre>
              ) : null}
            </section>
          </div>
        )}
      </aside>
    </div>
  )
}
