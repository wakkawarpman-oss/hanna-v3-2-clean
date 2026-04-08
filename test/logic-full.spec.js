'use strict'

const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { describe, it } = require('node:test')
const { SafeParser } = require('../components/search-panel')
const { CachedParser } = require('../components/search-panel-opt')
const { CalibratedParser } = require('../components/calibrated-parser')
const { Calibration } = require('../components/calibration')

describe('MAX LOGIC VERIFICATION', () => {
  it('001. Base parse critical path is successful', () => {
    const parser = new SafeParser()
    const result = parser.parseSearchInput('Пелешенко Дмитро Валерійович 1972 Харків вул. Широнинцев 49 0958042036')

    assert.equal(result.status, 'HIGH')
    assert.ok(result.confidence >= 4)
    assert.equal(typeof result.raw, 'string')
  })

  it('002. Empty response is gracefully handled', () => {
    const parser = new SafeParser()
    const result = parser.parseSearchInput('')

    assert.equal(result.status, 'EMPTY')
    assert.ok(result.errors.includes('EMPTY_INPUT'))
  })

  it('003. Invalid input type returns parser error envelope', () => {
    const parser = new SafeParser()
    const result = parser.parseSearchInput(null)

    assert.equal(result.status, 'ERROR')
    assert.ok(result.errors.some((e) => e.includes('INVALID_INPUT')))
  })

  it('004. Calibration matrix is green', () => {
    const cal = Calibration.validate()

    assert.equal(cal.allGreen, true)
    assert.deepEqual(Object.keys(cal.scores).sort(), ['accuracy', 'memory', 'speed'])
    for (const score of Object.values(cal.scores)) {
      assert.ok(score >= 0.95)
    }
  })

  it('005. Cache deduplication prevents duplicate cache keys', () => {
    const parser = new CachedParser({ maxCache: 8 })

    parser.parseSearchInput('https://test.com')
    parser.parseSearchInput('https://test.com')

    const stats = parser.getStats()
    assert.equal(stats.size, 1)
    assert.ok(stats.hits >= 1)
  })

  it('006. Iterative parse stays memory-stable and cache-bounded', () => {
    const parser = new CachedParser({ maxCache: 200 })
    const startHeap = process.memoryUsage().heapUsed

    for (let i = 0; i < 1000; i++) {
      parser.parseSearchInput(`target-${i} Харків 19${70 + (i % 20)}`)
    }

    const endHeap = process.memoryUsage().heapUsed
    const growth = endHeap - startHeap
    const stats = parser.getStats()

    assert.ok(stats.size <= 200)
    assert.ok(growth < 160 * 1024 * 1024)
  })

  it('007. Golden dataset matches expected parser fields', () => {
    const parser = new SafeParser()
    const goldenPath = path.resolve('test/golden.json')
    const goldens = JSON.parse(fs.readFileSync(goldenPath, 'utf8'))

    const failures = []
    for (const sample of goldens) {
      const result = parser.parseSearchInput(sample.input)
      for (const [field, expected] of Object.entries(sample.expected)) {
        if (field === 'confidenceMin') {
          if (result.confidence < expected) failures.push(`${sample.name}:confidence`) 
          continue
        }

        const actual = result.parsed[field]
        if (expected === null) {
          if (actual !== '') failures.push(`${sample.name}:${field}`)
          continue
        }

        if (String(actual) !== String(expected)) {
          failures.push(`${sample.name}:${field}`)
        }
      }
    }

    assert.equal(failures.length, 0)
  })

  it('008. Fault injection strings recover without crash', () => {
    const parser = new CalibratedParser()
    const payloads = [
      'Пелешенко\u0000\u0001 Дмитро 1972',
      '%%%%%%% Харків вул. Сумська 10 ####',
      '\uFEFF0951234567 ФОП'
    ]

    const results = payloads.map((p) => parser.parseSearchInput(p))
    assert.ok(results.every((r) => r.status !== 'ERROR'))
  })
})
