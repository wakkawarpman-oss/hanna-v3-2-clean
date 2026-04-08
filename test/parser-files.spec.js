'use strict'

const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { describe, it, before } = require('node:test')

const { SearchPanel } = require('../components/search-panel')

const rawData = fs.readFileSync(path.join(__dirname, 'data', 'real-examples.json'), 'utf8')
const testCases = JSON.parse(rawData)

describe('File-based parser tests', () => {
  let parser

  before(() => {
    const panel = new SearchPanel()
    parser = panel.parseSearchInput.bind(panel)
  })

  for (const { id, input, expected } of testCases) {
    it(`case ${id}`, () => {
      const result = parser(input)

      for (const [key, value] of Object.entries(expected)) {
        if (key === 'confidence') {
          assert.ok(Math.abs(result.confidence - value) <= 1, `confidence mismatch for case ${id}`)
          continue
        }

        const actual = result.parsed[key]
        assert.ok(actual, `${key} should be present for case ${id}`)
        assert.ok(
          actual.toLowerCase().includes(String(value).toLowerCase()),
          `${key} mismatch for case ${id}: expected part "${value}", got "${actual}"`
        )
      }
    })
  }

  it('collects aggregate confidence statistics', () => {
    const results = testCases.map((item) => parser(item.input))
    const avgConfidence = results.reduce((sum, r) => sum + r.confidence, 0) / results.length

    assert.ok(avgConfidence >= 3, 'Average confidence should stay >= 3')
  })
})
