'use strict'

const assert = require('node:assert/strict')
const { describe, it } = require('node:test')
const { SmartSearch, SearchResults } = require('../components/smart-search')

describe('SMART SEARCH RANKING', () => {
  const smart = new SmartSearch()

  it('exactly matching fields gets high score', () => {
    const parsed = {
      fio: 'Пелешенко Дмитро Валерійович',
      birthYear: '1972',
      city: 'Харків',
      address: 'вул. Широнинцев 49',
      phone: '0958042036'
    }

    const score = smart.scoreResult(parsed, 'Пелешенко Дмитро Валерійович 1972 Харків').score
    assert.ok(score > 4.0)
  })

  it('fuzzy match still gives useful score', () => {
    const parsed = { fio: 'Пелешенко Дмитро Валерійович' }
    const score = smart.scoreResult(parsed, 'Пелешенк Дмитро').score
    assert.ok(score >= 1.0)
  })

  it('duplicate-like entries group into one cluster', () => {
    const results = [
      { parsed: { fio: 'Пелешенко Дмитро', birthYear: '1972', city: 'Харків' }, score: 4.2 },
      { parsed: { fio: 'Пелешенко Дмитро', birthYear: '1972', city: 'Харків' }, score: 3.8 }
    ]

    const clusters = new SearchResults().groupResults(results)
    assert.equal(clusters[0].count, 2)
    assert.equal(clusters.length, 1)
  })
})
