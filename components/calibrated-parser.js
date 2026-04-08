'use strict'

const fs = require('node:fs')
const path = require('node:path')
const { SafeParser } = require('./search-panel')
const { SmartSearch } = require('./smart-search')

const DEFAULT_CONFIG = {
  parser: { sensitivity: 0.5, fuzziness: 0.75 },
  search: { boostFio: 3.0, boostYear: 2.5 },
  tui: { fpsTarget: 60, compactMode: false },
  behavioral: { noiseLevel: 0.1 }
}

class CalibratedParser {
  constructor (configPath = path.resolve('config.calibrated.json')) {
    this.configPath = configPath
    this.config = this.loadCalibration()
    this.parser = new SafeParser()
    this.smart = new SmartSearch()

    this.smart.fuzzyThreshold = this.config.parser.fuzziness
    this.smart.boostFactors.fio = this.config.search.boostFio
    this.smart.boostFactors.birthYear = this.config.search.boostYear
  }

  loadCalibration () {
    try {
      const raw = fs.readFileSync(this.configPath, 'utf8')
      const parsed = JSON.parse(raw)
      return {
        parser: { ...DEFAULT_CONFIG.parser, ...(parsed.parser || {}) },
        search: { ...DEFAULT_CONFIG.search, ...(parsed.search || {}) },
        tui: { ...DEFAULT_CONFIG.tui, ...(parsed.tui || {}) },
        behavioral: { ...DEFAULT_CONFIG.behavioral, ...(parsed.behavioral || {}) }
      }
    } catch {
      return DEFAULT_CONFIG
    }
  }

  parseSearchInput (text) {
    const baseResult = this.parser.parseSearchInput(text)
    const sensitivity = Number(this.config.parser.sensitivity) || DEFAULT_CONFIG.parser.sensitivity

    const calibratedConfidence = Math.max(
      0,
      Math.min(6, Number((baseResult.confidence * sensitivity).toFixed(2)))
    )

    const relevance = this.smart.scoreResult(baseResult.parsed, text)

    return {
      ...baseResult,
      confidence: calibratedConfidence,
      relevance,
      calibrated: true
    }
  }

  async routeToTools (parsedData) {
    return this.parser.routeToTools(parsedData)
  }
}

module.exports = {
  CalibratedParser,
  DEFAULT_CONFIG
}
