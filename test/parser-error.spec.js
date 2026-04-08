'use strict'

const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { describe, it } = require('node:test')

const { SafeParser } = require('../components/search-panel')

const parser = new SafeParser()

describe('Parser error handling', () => {
  it('handles invalid input type', () => {
    const result = parser.parseSearchInput(null)
    assert.equal(result.status, 'ERROR')
    assert.match(result.errors[0], /INVALID_INPUT/)
  })

  it('handles empty file', () => {
    const emptyFile = fs.readFileSync(path.join(__dirname, 'data', 'errors', 'empty.txt'), 'utf8')
    const result = parser.parseSearchInput(emptyFile)
    assert.equal(result.confidence, 0)
    assert.deepEqual(result.errors, ['EMPTY_INPUT'])
  })

  it('handles binary file gracefully', () => {
    const corrupted = fs.readFileSync(path.join(__dirname, 'data', 'errors', 'corrupted-files.bin'))
    const result = parser.parseSearchInput(corrupted)
    assert.equal(result.status, 'EMPTY')
    assert.ok(result.errors.length >= 1)
  })

  it('handles utf BOM input', () => {
    const utf16Like = '\uFEFFПелешенко Дмитро Валерійович 1972'
    const result = parser.parseSearchInput(utf16Like)
    assert.match(result.parsed.fio, /Пелешенко/u)
    assert.ok(!result.errors.includes('ENCODING_ERROR'))
  })

  it('filters control characters', () => {
    const dirty = 'Пелешенко\x00\r\n\t\u0007Дмитро Валерійович 1972'
    const result = parser.parseSearchInput(dirty)
    assert.ok(result.confidence >= 1)
    assert.ok(result.parsed.fio.length > 0)
    assert.ok(!result.raw.includes('\x00'))
  })

  it('partially parses damaged input', () => {
    const broken = 'Пелешен%ko Дми@тро 1972 \x07ул. Широнинцев'
    const result = parser.parseSearchInput(broken)

    assert.ok(result.confidence >= 2)
    assert.ok(!result.errors.includes('FATAL'))
  })
})
