'use strict'

const assert = require('node:assert/strict')
const { performance } = require('node:perf_hooks')
const { describe, it } = require('node:test')
const { MultiThreadParser } = require('../components/multi-parser')

describe('MULTI-THREAD STRESS', () => {
  it('100 concurrent urls with 32 workers keep >=99.5% success', async () => {
    const parser = new MultiThreadParser(32)
    const urls = Array.from({ length: 100 }, (_, i) => `https://stress${i}.com`)

    try {
      const start = performance.now()
      const results = await parser.parseBatch(urls)
      const duration = performance.now() - start

      const successRate = results.filter((r) => r.status === 'success').length / 100

      assert.ok(successRate >= 0.995)
      assert.ok(duration < 15000)
    } finally {
      await parser.destroy()
    }
  })

  it('Backpressure handling keeps queue stable with small pool', async () => {
    const parser = new MultiThreadParser(4)
    const urls = Array.from({ length: 50 }, () => 'https://backpressure.com')

    try {
      const start = Date.now()
      const results = await parser.parseBatch(urls)
      const elapsed = Date.now() - start

      assert.equal(results.length, 50)
      assert.ok(elapsed < 15000)
    } finally {
      await parser.destroy()
    }
  })
})
