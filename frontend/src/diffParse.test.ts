import { describe, expect, it } from 'vitest'

import { languageFromPath, parseUnifiedDiff } from './diffParse'

const SAMPLE = `diff --git a/train.py b/train.py
index 1111111..2222222 100644
--- a/train.py
+++ b/train.py
@@ -14,7 +14,7 @@ from torch.nn import functional as F
 seed = 1337
 device_preference = "auto"
-block_size = 128
+block_size = 256
 batch_size = 32
`

describe('parseUnifiedDiff', () => {
  it('detects python language and add/del line numbers', () => {
    const files = parseUnifiedDiff(SAMPLE)
    expect(files).toHaveLength(1)
    expect(files[0].path).toBe('train.py')
    expect(files[0].language).toBe('python')

    const deleted = files[0].lines.find((line) => line.kind === 'del')
    const added = files[0].lines.find((line) => line.kind === 'add')
    expect(deleted?.text).toBe('-block_size = 128')
    expect(added?.text).toBe('+block_size = 256')
    expect(deleted?.oldNo).toBe(16)
    expect(added?.newNo).toBe(16)
  })

  it('maps common extensions to highlight languages', () => {
    expect(languageFromPath('src/App.tsx')).toBe('typescript')
    expect(languageFromPath('notes.md')).toBe('markdown')
    expect(languageFromPath('config.toml')).toBe('ini')
  })
})
