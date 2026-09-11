export type DiffLineKind = 'meta' | 'hunk' | 'add' | 'del' | 'ctx' | 'plain'

export interface DiffLine {
  kind: DiffLineKind
  text: string
  oldNo?: number
  newNo?: number
}

export interface DiffFile {
  path: string
  language: string
  lines: DiffLine[]
}

const EXT_LANG: Record<string, string> = {
  py: 'python',
  pyi: 'python',
  js: 'javascript',
  jsx: 'javascript',
  mjs: 'javascript',
  cjs: 'javascript',
  ts: 'typescript',
  tsx: 'typescript',
  json: 'json',
  md: 'markdown',
  markdown: 'markdown',
  toml: 'ini',
  ini: 'ini',
  cfg: 'ini',
  yml: 'yaml',
  yaml: 'yaml',
  sh: 'bash',
  bash: 'bash',
  zsh: 'bash',
  css: 'css',
  html: 'xml',
  xml: 'xml',
  rs: 'rust',
  go: 'go',
  java: 'java',
  kt: 'kotlin',
  c: 'c',
  h: 'c',
  cpp: 'cpp',
  cc: 'cpp',
  hpp: 'cpp',
  rb: 'ruby',
  php: 'php',
  sql: 'sql',
  txt: 'plaintext',
}

export function languageFromPath(path: string): string {
  const base = path.split('/').pop() ?? path
  if (base === 'Dockerfile' || base.startsWith('Dockerfile.')) return 'dockerfile'
  if (base === 'Makefile' || base === 'makefile') return 'makefile'
  const ext = base.includes('.') ? base.split('.').pop()!.toLowerCase() : ''
  return EXT_LANG[ext] ?? 'plaintext'
}

function pathFromDiffHeader(line: string): string | null {
  const match = line.match(/^diff --git a\/(.+?) b\/(.+)$/)
  if (match) return match[2]
  return null
}

/** Parse a unified diff into per-file sections with line kinds and numbers. */
export function parseUnifiedDiff(raw: string): DiffFile[] {
  const text = raw.replace(/\r\n/g, '\n')
  if (!text.trim()) return []

  const files: DiffFile[] = []
  let current: DiffFile | null = null
  let oldNo = 0
  let newNo = 0

  const pushMeta = (line: string) => {
    if (!current) {
      current = { path: 'changes', language: 'plaintext', lines: [] }
      files.push(current)
    }
    current.lines.push({ kind: 'meta', text: line })
  }

  for (const line of text.split('\n')) {
    const fromHeader = pathFromDiffHeader(line)
    if (fromHeader) {
      current = {
        path: fromHeader,
        language: languageFromPath(fromHeader),
        lines: [{ kind: 'meta', text: line }],
      }
      files.push(current)
      oldNo = 0
      newNo = 0
      continue
    }

    if (line.startsWith('+++ ') || line.startsWith('--- ') || line.startsWith('index ') || line.startsWith('new file') || line.startsWith('deleted file') || line.startsWith('similarity ') || line.startsWith('rename ')) {
      if (line.startsWith('+++ b/')) {
        const path = line.slice(6)
        if (current) {
          current.path = path
          current.language = languageFromPath(path)
        }
      }
      pushMeta(line)
      continue
    }

    if (line.startsWith('@@')) {
      const hunk = line.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/)
      if (hunk) {
        oldNo = Number(hunk[1])
        newNo = Number(hunk[2])
      }
      if (!current) {
        current = { path: 'changes', language: 'plaintext', lines: [] }
        files.push(current)
      }
      current.lines.push({ kind: 'hunk', text: line })
      continue
    }

    if (!current) {
      current = { path: 'changes', language: 'plaintext', lines: [] }
      files.push(current)
    }

    if (line.startsWith('+')) {
      current.lines.push({ kind: 'add', text: line, newNo })
      newNo += 1
      continue
    }
    if (line.startsWith('-')) {
      current.lines.push({ kind: 'del', text: line, oldNo })
      oldNo += 1
      continue
    }
    if (line.startsWith('\\')) {
      current.lines.push({ kind: 'meta', text: line })
      continue
    }
    // context (leading space) or plain
    const kind: DiffLineKind = line.startsWith(' ') || line === '' ? 'ctx' : 'plain'
    if (kind === 'ctx') {
      current.lines.push({ kind, text: line || ' ', oldNo, newNo })
      oldNo += 1
      newNo += 1
    } else {
      current.lines.push({ kind, text: line })
    }
  }

  return files
}
