'use strict'

const assert = require('node:assert/strict')
const { describe, it, beforeEach } = require('node:test')
const { DebugParser } = require('../components/search-panel')

const DEBUG = process.env.DEBUG === '1'

describe('Parser debug mode', () => {
  let parser

  beforeEach(() => {
    parser = new DebugParser(DEBUG)
  })

  it('captures debug trace for rich sample', (t) => {
    if (!DEBUG) {
      t.skip('DEBUG disabled')
      return
    }

    const input = 'Пелешенко Дмитро Валерійович 1972 г. р. Был прописан Харьков Ул. Гв. Широнинцев 49 ФОП.'
    const result = parser.parseSearchInput(input)

    const debugReport = parser.getDebugReport('DBG-')
    assert.ok(debugReport.length >= 2)
    assert.equal(debugReport[0].stage, 'START')
    assert.equal(debugReport[1].stage, 'PARSED')
    assert.equal(result.confidence >= 4, true)
  })

  it('supports step-like debug run', async (t) => {
    if (!DEBUG) {
      t.skip('DEBUG disabled')
      return
    }

    const input = '0958042036 Пелешенко 1972'
    const steps = [
      (text) => text.normalize('NFD').replace(/[\x00-\x1F\x7F]/g, ''),
      (text) => text.match(/([А-ЯІЇЄҐ][а-яіїєґ]+\s+){2,3}[А-ЯІЇЄҐ][а-яіїєґ]+/iu)?.[0] || '',
      (text) => text.match(/(0\d{9}|\+\d{10,12})/)?.[0] || ''
    ]

    for (const step of steps) {
      step(input)
      await new Promise((resolve) => setTimeout(resolve, 50))
    }

    const result = parser.parseSearchInput(input)
    assert.ok(result.confidence >= 2)
  })
})
