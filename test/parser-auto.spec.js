'use strict'

const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { describe, it } = require('node:test')
const { SearchPanel } = require('../components/search-panel')

function loadRealFiles (dir = path.join(__dirname, 'data', 'real')) {
  const panel = new SearchPanel()
  const parser = panel.parseSearchInput.bind(panel)

  if (!fs.existsSync(dir)) {
    return []
  }

  const files = fs
    .readdirSync(dir)
    .filter((f) => f.endsWith('.txt'))
    .map((f) => ({
      id: path.basename(f, '.txt'),
      input: fs.readFileSync(path.join(dir, f), 'utf8')
    }))

  return files.map((file) => {
    const parsed = parser(file.input)
    return {
      ...file,
      parsed: parsed.parsed,
      confidence: parsed.confidence,
      status: parsed.confidence >= 3 ? 'PASS' : 'LOW_CONFIDENCE'
    }
  })
}

describe('Auto parser file scan', () => {
  const realFiles = loadRealFiles()

  it('has at least one auto-case', () => {
    assert.ok(realFiles.length >= 1)
  })

  realFiles.forEach(({ id, input, status }) => {
    it(`${status} ${id}`, () => {
      const panel = new SearchPanel()
      const result = panel.parseSearchInput(input)
      assert.ok(result.confidence >= 2, `Low confidence in ${id}`)
    })
  })
})
