'use strict'

const assert = require('node:assert/strict')
const { describe, it } = require('node:test')
const { CachedParser } = require('../components/search-panel-opt')

describe('STRESS TESTS', () => {
  it('1000 concurrent parse tasks keep >=99% successful status envelopes', async () => {
    const parser = new CachedParser({ maxCache: 1500 })
    const tasks = Array.from({ length: 1000 }, (_, i) => Promise.resolve().then(() => {
      return parser.parseSearchInput(`load-${i} Харків вул. Тестова ${i % 50} 19${70 + (i % 20)}`)
    }))

    const settled = await Promise.allSettled(tasks)
    const success = settled.filter((r) => r.status === 'fulfilled' && r.value.status !== 'ERROR').length

    assert.ok(success / 1000 >= 0.99)
  })

  it('Memory pressure remains within bounded envelope', async () => {
    const parser = new CachedParser({ maxCache: 600 })
    const start = process.memoryUsage().heapUsed

    await Promise.all(
      Array.from({ length: 500 }, (_, i) => Promise.resolve().then(() => {
        return parser.parseSearchInput(`stress-${i} Київ вул. Польова ${i % 100} 200${i % 10}`)
      }))
    )

    const end = process.memoryUsage().heapUsed
    assert.ok(end - start < 100 * 1024 * 1024)
    assert.ok(parser.getStats().size <= 600)
  })
})
