'use strict'

const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { describe, it } = require('node:test')
const { SafeParser } = require('../components/search-panel')

describe('Golden dataset verification', () => {
  it('all golden fixtures match expected parser fields', () => {
    const parser = new SafeParser()
    const samples = JSON.parse(fs.readFileSync(path.resolve('test/golden.json'), 'utf8'))

    const mismatches = []
    for (const sample of samples) {
      const result = parser.parseSearchInput(sample.input)
      for (const [field, expected] of Object.entries(sample.expected)) {
        if (field === 'confidenceMin') {
          if (result.confidence < expected) mismatches.push(`${sample.name}:confidence`)
          continue
        }

        const actual = result.parsed[field]
        if (expected === null) {
          if (actual !== '') mismatches.push(`${sample.name}:${field}`)
          continue
        }

        if (String(actual) !== String(expected)) mismatches.push(`${sample.name}:${field}`)
      }
    }

    assert.equal(mismatches.length, 0)
  })
})
