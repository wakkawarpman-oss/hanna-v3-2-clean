'use strict'

const assert = require('node:assert/strict')
const { describe, it } = require('node:test')
const { CachedParser } = require('../components/search-panel-opt')

describe('SMOKE TESTS', () => {
  it('Critical path parse -> cache', () => {
    const parser = new CachedParser({ maxCache: 100 })
    const result = parser.parseSearchInput('Петренко Іван 1991 Київ вул. Хрещатик 1')

    assert.equal(result.status === 'HIGH' || result.status === 'LOW', true)

    parser.parseSearchInput('Петренко Іван 1991 Київ вул. Хрещатик 1')
    const stats = parser.getStats()
    assert.ok(stats.size > 0)
    assert.ok(stats.hits >= 1)
  })
})
