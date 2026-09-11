import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { EvaluationSlideOver } from './EvaluationSlideOver'
import type { EvaluationRecord, ProjectRead } from '../types'

vi.mock('../api', () => ({
  listEvaluations: vi.fn(async () => [
    {
      schema_version: '2',
      evaluation_id: 'H0001/T001@aaaaaaaa',
      trial_id: 'H0001/T001',
      hypothesis_id: 'H0001',
      run_id: 'run-1',
      status: 'passed',
      metrics: { score: 0.5 },
      champion_metrics: { score: 1.0 },
      deltas: { score: -0.5 },
      primary_metric: 'score',
      direction: 'minimize',
      summary: 'score improved vs champion; advisory recommendation: accept.',
      signals: { improved: ['score'], regressed: [], unchanged: [] },
      recommendation: 'accept',
      rationale: 'beat baseline',
      risks: 'noise',
      evidence: {
        candidate_commit: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
        evaluator_commit: 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
        duration_seconds: 1.5,
        stdout_excerpt: '{"metrics":{"score":0.5}}',
      },
      model: 'composer-2.5',
      system_prompt_hash: 'deadbeef',
      explainability: {
        confidence: 0.82,
        attribution: 'weight tying',
      },
      explainability_schema_hash: 'abc123',
      created_at: '2026-09-11T00:00:00+00:00',
    } satisfies EvaluationRecord,
  ]),
}))

const project: ProjectRead = {
  id: 'proj-1',
  name: 'tinylm-bench',
  github_url: null,
  local_path: '/tmp/tinylm',
  pg_schema: 'proj_tinylm',
  status: 'active',
  created_at: '2026-09-11T00:00:00+00:00',
}

afterEach(() => {
  cleanup()
})

describe('EvaluationSlideOver', () => {
  it('lists previous evaluations and opens detail', async () => {
    render(
      <EvaluationSlideOver
        open
        onClose={() => undefined}
        project={project}
        systemPrompt="interpret metrics"
        model="composer-2.5"
        explainabilitySchema={null}
        onSystemPromptChange={() => undefined}
        onModelChange={() => undefined}
        onExplainabilitySchemaChange={() => undefined}
        inboundContext={['Eval script', 'Execution']}
      />,
    )

    expect(await screen.findByText('Previous evaluations')).toBeTruthy()
    expect(screen.getByText('H0001/T001')).toBeTruthy()
    expect(screen.getByText(/Explainability schema/i)).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: /H0001\/T001/i }))
    await waitFor(() => {
      expect(screen.getByText('Rationale')).toBeTruthy()
      expect(screen.getByText('beat baseline')).toBeTruthy()
      expect(screen.getByText('Risks')).toBeTruthy()
      expect(screen.getByText('Explainability')).toBeTruthy()
      expect(screen.getByText('weight tying')).toBeTruthy()
    })
  })
})
