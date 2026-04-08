'use strict'

const assert = require('node:assert/strict')
const { describe, it } = require('node:test')
const { MultiThreadParser } = require('../components/multi-parser')

describe('MULTI-THREAD PARSER TESTS', () => {
  it('001. Single worker returns correct result', async () => {
    const parser = new MultiThreadParser(1)
    try {
      const result = await parser.parseBatch(['https://test1.com'])

      assert.equal(result.length, 1)
      assert.equal(result[0].status, 'success')
    } finally {
      await parser.destroy()
    }
  })

  it('002. 20 urls with 4 workers complete under threshold', async () => {
    const parser = new MultiThreadParser(4)
    const urls = Array.from({ length: 20 }, (_, i) => `https://test${i}.com`)
    const start = Date.now()

    try {
      const results = await parser.parseBatch(urls)
      const duration = Date.now() - start

      assert.equal(results.length, 20)
      assert.ok(duration < 7000)
    } finally {
      await parser.destroy()
    }
  })

  it('003. Mixed success/error returns partial results safely', async () => {
    const parser = new MultiThreadParser(8)
    const urls = [
      'https://valid.com',
      'http://invalid-url',
      'https://error.com'
    ]
    try {
      const results = await parser.parseBatch(urls)
      const successes = results.filter((r) => r.status === 'success')
      const errors = results.filter((r) => r.status === 'error')

      assert.equal(successes.length, 1)
      assert.equal(errors.length, 2)
    } finally {
      await parser.destroy()
    }
  })

  it('004. Duplicate URLs keep deterministic repeated outputs', async () => {
    const parser = new MultiThreadParser(8)
    try {
      const results = await parser.parseBatch([
        'https://same.com',
        'https://same.com',
        'https://same.com'
      ])

      assert.equal(results.length, 3)
      assert.ok(results.every((r) => r.url === 'https://same.com'))
    } finally {
      await parser.destroy()
    }
  })

  it('005. 100 tasks memory growth stays bounded', async () => {
    const startMemory = process.memoryUsage().heapUsed
    const parser = new MultiThreadParser(16)
    const urls = Array.from({ length: 100 }, (_, i) => `https://load${i}.com`)

    try {
      await parser.parseBatch(urls)

      const endMemory = process.memoryUsage().heapUsed
      assert.ok(endMemory - startMemory < 80 * 1024 * 1024)
    } finally {
      await parser.destroy()
    }
  })
})
