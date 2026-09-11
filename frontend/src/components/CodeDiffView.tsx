import { useMemo } from 'react'
import hljs from 'highlight.js/lib/core'
import bash from 'highlight.js/lib/languages/bash'
import c from 'highlight.js/lib/languages/c'
import cpp from 'highlight.js/lib/languages/cpp'
import css from 'highlight.js/lib/languages/css'
import dockerfile from 'highlight.js/lib/languages/dockerfile'
import go from 'highlight.js/lib/languages/go'
import ini from 'highlight.js/lib/languages/ini'
import java from 'highlight.js/lib/languages/java'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import markdown from 'highlight.js/lib/languages/markdown'
import python from 'highlight.js/lib/languages/python'
import ruby from 'highlight.js/lib/languages/ruby'
import rust from 'highlight.js/lib/languages/rust'
import sql from 'highlight.js/lib/languages/sql'
import typescript from 'highlight.js/lib/languages/typescript'
import xml from 'highlight.js/lib/languages/xml'
import yaml from 'highlight.js/lib/languages/yaml'

import { parseUnifiedDiff, type DiffFile, type DiffLine } from '../diffParse'

hljs.registerLanguage('python', python)
hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('typescript', typescript)
hljs.registerLanguage('json', json)
hljs.registerLanguage('markdown', markdown)
hljs.registerLanguage('yaml', yaml)
hljs.registerLanguage('bash', bash)
hljs.registerLanguage('ini', ini)
hljs.registerLanguage('css', css)
hljs.registerLanguage('xml', xml)
hljs.registerLanguage('rust', rust)
hljs.registerLanguage('go', go)
hljs.registerLanguage('java', java)
hljs.registerLanguage('c', c)
hljs.registerLanguage('cpp', cpp)
hljs.registerLanguage('ruby', ruby)
hljs.registerLanguage('sql', sql)
hljs.registerLanguage('dockerfile', dockerfile)

interface Props {
  diff: string
  emptyLabel?: string
}

function highlightCode(code: string, language: string): string {
  if (!code || language === 'plaintext') {
    return escapeHtml(code)
  }
  try {
    if (hljs.getLanguage(language)) {
      return hljs.highlight(code, { language, ignoreIllegals: true }).value
    }
  } catch {
    // fall through
  }
  return escapeHtml(code)
}

function escapeHtml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
}

function renderLine(line: DiffLine, language: string) {
  if (line.kind === 'meta' || line.kind === 'hunk') {
    return <code>{line.text}</code>
  }

  const prefix = line.text.slice(0, 1)
  const body = line.text.startsWith('+') || line.text.startsWith('-') || line.text.startsWith(' ')
    ? line.text.slice(1)
    : line.text
  const html = highlightCode(body, language)

  return (
    <>
      <span className="diff-prefix" aria-hidden>
        {line.kind === 'add' || line.kind === 'del' || line.kind === 'ctx' ? prefix : ' '}
      </span>
      <code dangerouslySetInnerHTML={{ __html: html || '&nbsp;' }} />
    </>
  )
}

function FileDiff({ file }: { file: DiffFile }) {
  return (
    <article className="diff-file">
      <header className="diff-file-header">
        <strong>{file.path}</strong>
        <span className="diff-lang">{file.language}</span>
      </header>
      <div className="diff-lines" role="table" aria-label={`Diff for ${file.path}`}>
        {file.lines.map((line, index) => (
          <div
            key={`${file.path}-${index}`}
            className={`diff-line diff-${line.kind}`}
            role="row"
          >
            <span className="diff-gutter old" role="cell">
              {line.oldNo ?? ''}
            </span>
            <span className="diff-gutter new" role="cell">
              {line.newNo ?? ''}
            </span>
            <span className="diff-code" role="cell">
              {renderLine(line, file.language)}
            </span>
          </div>
        ))}
      </div>
    </article>
  )
}

export function CodeDiffView({ diff, emptyLabel = 'No file changes.' }: Props) {
  const files = useMemo(() => parseUnifiedDiff(diff), [diff])

  if (!diff.trim()) {
    return <p className="muted">{emptyLabel}</p>
  }
  if (diff.startsWith('No file changes') || diff.startsWith('Diff unavailable')) {
    return <p className="muted">{diff}</p>
  }
  if (files.length === 0) {
    return <pre className="code-block diff">{diff}</pre>
  }

  return (
    <div className="code-diff-view">
      {files.map((file) => (
        <FileDiff key={file.path} file={file} />
      ))}
    </div>
  )
}
