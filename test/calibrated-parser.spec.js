'use strict'

const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { describe, it } = require('node:test')
const { CalibratedParser, DEFAULT_CONFIG } = require('../components/calibrated-parser')

describe('CalibratedParser', () => {
  it('falls back to defaults when config missing', () => {
    const parser = new CalibratedParser(path.join(os.tmpdir(), `missing-${Date.now()}.json`))
    const result = parser.parseSearchInput('Пелешенко Дмитро 1972 Харків')

    assert.equal(parser.config.parser.sensitivity, DEFAULT_CONFIG.parser.sensitivity)
    assert.equal(parser.config.search.boostFio, DEFAULT_CONFIG.search.boostFio)
    assert.equal(result.calibrated, true)
    assert.ok(result.relevance)
  })

  it('applies configured sensitivity and boosts', () => {
    const tmpConfig = path.join(os.tmpdir(), `calib-${Date.now()}.json`)
    fs.writeFileSync(tmpConfig, JSON.stringify({
      parser: { sensitivity: 0.4, fuzziness: 0.8 },
      search: { boostFio: 4.0, boostYear: 3.0 },
      tui: { fpsTarget: 45, compactMode: true },
      behavioral: { noiseLevel: 0.2 }
    }))

    const parser = new CalibratedParser(tmpConfig)
    const result = parser.parseSearchInput('Пелешенко Дмитро Валерійович 1972 Харків')

    assert.equal(parser.smart.fuzzyThreshold, 0.8)
    assert.equal(parser.smart.boostFactors.fio, 4.0)
    assert.equal(parser.smart.boostFactors.birthYear, 3.0)
    assert.ok(result.confidence <= 6)
    assert.ok(result.relevance.score >= 0)

    fs.unlinkSync(tmpConfig)
  })
})
