'use strict'

const assert = require('node:assert/strict')
const { describe, it } = require('node:test')
const { SearchPanel } = require('../components/search-panel')

describe('OSINT Search Parser', () => {
  const panel = new SearchPanel()
  const parser = panel.parseSearchInput.bind(panel)

  it('parses complete Peleshenko sample', () => {
    const input = `Пелешенко Дмитро Валерійович 1972 г. р.
Был прописан Харьков
Ул. Гв. Широнинцев 49 (49А, 49Б)
Вероятно раньше был ФОП.`

    const result = parser(input)

    assert.match(result.parsed.fio, /Пелешенко Дмитро Валерійович/u)
    assert.equal(result.parsed.birthYear, '1972')
    assert.match(result.parsed.city, /Харк|Харьк/u)
    assert.match(result.parsed.address, /Широнинцев/u)
    assert.equal(result.parsed.fop, 'ФОП')
    assert.equal(result.confidence, 5)
  })

  it('parses date/address and phone sample', () => {
    const input = `22.07.1973
г. Харьков, ул. Бучмы, 32Б, корп. Б, кв. 5.
0958042036`

    const result = parser(input)

    assert.equal(result.parsed.birthYear, '1973')
    assert.match(result.parsed.city, /Харк|Харьк/u)
    assert.match(result.parsed.address, /Бучм/u)
    assert.equal(result.parsed.phone, '0958042036')
    assert.equal(result.confidence, 4)
  })

  it('parses only full name', () => {
    const result = parser('Іванов Іван Іванович')

    assert.match(result.parsed.fio, /Іванов Іван Іванович/u)
    assert.equal(result.confidence, 1)
  })

  it('parses multi-phone and FOP case', () => {
    const input = `Коваленко Петро 1985
Харків вул. Сумська 25
ФОП з 2010
+380501234567 0671234567`

    const result = parser(input)

    assert.equal(result.parsed.birthYear, '1985')
    assert.match(result.parsed.city, /Харків/u)
    assert.equal(result.parsed.fop, 'ФОП')
    assert.match(result.parsed.phone, /^(\+380501234567|0671234567)$/)
    assert.equal(result.confidence, 6)
  })

  it('parses address without city', () => {
    const result = parser('вул. Гвардійців Широнинців 49А')

    assert.match(result.parsed.address, /Гвардійців Широнинців/u)
    assert.equal(result.parsed.fio, '')
    assert.equal(result.confidence, 1)
  })

  it('normalizes spaced local phone', () => {
    const result = parser('095 123 45 67')

    assert.equal(result.parsed.phone, '0951234567')
    assert.equal(result.confidence, 1)
  })

  it('routes expected tools for rich sample', async () => {
    const input = `Пелешенко Дмитро Валерійович 1972 г. р.
Был прописан Харьков
Ул. Гв. Широнинцев 49`

    const parsed = parser(input)
    const tools = await panel.routeToTools(parsed)

    assert.ok(tools.length >= 3)
    assert.ok(tools.some((t) => t.name.includes('ФІО')))
    assert.ok(tools.some((t) => t.name.includes('Адресний')))
    assert.ok(tools.some((t) => t.name.includes('ДР/РІК')))
  })

  const testCases = [
    {
      input: 'Пелешенко Дмитро Валерійович',
      expected: { fio: 'Пелешенко Дмитро Валерійович', confidence: 1 }
    },
    {
      input: '0958042036',
      expected: { phone: '0958042036', confidence: 1 }
    },
    {
      input: 'Харків вул. Гв. Широнинцев 49',
      expected: {
        city: 'Харків',
        address: 'вул. Гв. Широнинцев 49',
        confidence: 2
      }
    }
  ]

  testCases.forEach(({ input, expected }, idx) => {
    it(`regex case ${idx + 1}`, () => {
      const result = parser(input)
      Object.entries(expected).forEach(([key, value]) => {
        if (key === 'confidence') {
          assert.equal(result.confidence, value)
          return
        }
        assert.equal(result.parsed[key], value)
      })
    })
  })
})
