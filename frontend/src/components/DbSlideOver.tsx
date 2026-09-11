import { useEffect, useState } from 'react'
import { X } from 'lucide-react'

import { getTable } from '../api'
import type { ProjectRead } from '../types'

const TABLES = [
  'hypotheses',
  'trials',
  'evaluations',
  'metrics',
  'runs',
  'node_runs',
  'chat_summaries',
  'chat_messages',
] as const

interface Props {
  open: boolean
  onClose: () => void
  project: ProjectRead | null
  onOpenHypothesis?: (id: string) => void
  onOpenTrial?: (hypothesisId: string, trialId: string) => void
}

export function DbSlideOver({ open, onClose, project, onOpenHypothesis, onOpenTrial }: Props) {
  const [table, setTable] = useState<(typeof TABLES)[number]>('hypotheses')
  const [rows, setRows] = useState<Record<string, unknown>[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open || !project) return
    getTable(project.id, table)
      .then((payload) => {
        setRows(payload.rows)
        setError('')
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load table'))
  }, [open, project, table])

  if (!open) return null

  return (
    <div className="slide-root">
      <button className="slide-backdrop" aria-label="Close" onClick={onClose} />
      <aside className="slide-over wide">
        <header className="slide-header">
          <div>
            <small>{project?.pg_schema ?? 'no project'}</small>
            <strong>Database explorer</strong>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Close panel">
            <X size={16} />
          </button>
        </header>
        <div className="db-layout">
          <nav className="db-rail">
            {TABLES.map((name) => (
              <button
                key={name}
                className={table === name ? 'active' : ''}
                onClick={() => setTable(name)}
              >
                {name}
              </button>
            ))}
          </nav>
          <div className="db-main">
            {error && <p className="form-error">{error}</p>}
            {!project && <p className="muted">Create or activate a project to browse tables.</p>}
            {project && rows.length === 0 && !error && (
              <p className="muted">No rows in {table} yet.</p>
            )}
            <div className="card-list">
              {rows.map((row, index) => {
                const id = String(row.id ?? index)
                const status = String(row.status ?? row.outcome ?? '')
                return (
                  <button
                    key={id}
                    className="info-card"
                    onClick={() => {
                      if (table === 'hypotheses' && onOpenHypothesis) onOpenHypothesis(id)
                      if (table === 'trials' && onOpenTrial && typeof row.hypothesis_id === 'string') {
                        onOpenTrial(row.hypothesis_id, id)
                      }
                    }}
                  >
                    {status && <span className={`status-chip ${status}`}>{status}</span>}
                    <strong>{id}</strong>
                    <small>{JSON.stringify(row).slice(0, 160)}</small>
                  </button>
                )
              })}
            </div>
          </div>
        </div>
      </aside>
    </div>
  )
}
