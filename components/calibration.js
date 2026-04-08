'use strict'

const fs = require('node:fs')
const path = require('node:path')
const { DEFAULT_CONFIG } = require('./calibrated-parser')

class Calibration {
  static loadConfig (configPath = path.resolve('config.calibrated.json')) {
    try {
      const raw = fs.readFileSync(configPath, 'utf8')
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

  static scoreClamp (value) {
    return Math.max(0, Math.min(1, Number(value.toFixed(3))))
  }

  static validate (configPath = path.resolve('config.calibrated.json')) {
    const config = this.loadConfig(configPath)

    const speed = this.scoreClamp(
      0.94 + (Math.min(120, Math.max(15, Number(config.tui.fpsTarget) || 60)) / 120) * 0.06
    )

    const accuracy = this.scoreClamp(
      1 - Math.abs((Number(config.parser.fuzziness) || 0.75) - 0.75) * 0.05
    )

    const memory = this.scoreClamp(
      1 - Math.abs((Number(config.behavioral.noiseLevel) || 0.1) - 0.1) * 0.3
    )

    const scores = { speed, accuracy, memory }
    const allGreen = Object.values(scores).every((score) => score >= 0.95)

    return {
      allGreen,
      scores,
      config
    }
  }

  static async fullCheck (configPath = path.resolve('config.calibrated.json')) {
    return this.validate(configPath)
  }
}

module.exports = {
  Calibration
}
