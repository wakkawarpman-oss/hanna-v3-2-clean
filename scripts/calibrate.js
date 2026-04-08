#!/usr/bin/env node
'use strict'

const fs = require('node:fs')
const path = require('node:path')
const readline = require('node:readline')
const { SafeParser } = require('../components/search-panel')
const { SmartSearch } = require('../components/smart-search')
const { DEFAULT_CONFIG } = require('../components/calibrated-parser')

class CalibrationWizard {
  constructor (configFile = path.resolve('config.calibrated.json')) {
    this.configFile = configFile
    this.config = this.loadConfig()

    this.rl = readline.createInterface({
      input: process.stdin,
      output: process.stdout
    })
  }

  loadConfig () {
    try {
      return JSON.parse(fs.readFileSync(this.configFile, 'utf8'))
    } catch {
      return JSON.parse(JSON.stringify(DEFAULT_CONFIG))
    }
  }

  async prompt (question, fallback) {
    return new Promise((resolve) => {
      this.rl.question(question, (answer) => {
        const normalized = answer.trim()
        resolve(normalized === '' ? String(fallback) : normalized)
      })
    })
  }

  async promptFloat (question, fallback, min, max) {
    const raw = await this.prompt(question, fallback)
    const value = Number.parseFloat(raw)
    if (Number.isNaN(value)) return fallback
    return Math.min(max, Math.max(min, value))
  }

  async promptInt (question, fallback, min, max) {
    const raw = await this.prompt(question, fallback)
    const value = Number.parseInt(raw, 10)
    if (Number.isNaN(value)) return fallback
    return Math.min(max, Math.max(min, value))
  }

  async promptYesNo (question, fallback) {
    const raw = await this.prompt(question, fallback ? 'y' : 'n')
    return raw.toLowerCase().startsWith('y')
  }

  printParserPreview () {
    const parser = new SafeParser()
    const testCases = [
      'Пелешенко Дмитро Валерійович 1972',
      '0958042036 ул. Широнинцев 49',
      'Коваленко Петро ФОП Київ Сумська'
    ]

    console.log('\nParser preview:')
    for (const [index, sample] of testCases.entries()) {
      const out = parser.parseSearchInput(sample)
      console.log(`${index + 1}. ${sample.slice(0, 40)} -> ${out.confidence}/6`) 
    }
  }

  async calibrateParser () {
    console.log('\n1) PARSER SENSITIVITY')
    this.printParserPreview()

    this.config.parser.sensitivity = await this.promptFloat(
      'Sensitivity (0.1-1.0, default 0.5): ',
      this.config.parser.sensitivity ?? 0.5,
      0.1,
      1.0
    )

    this.config.parser.fuzziness = await this.promptFloat(
      'Fuzziness (0.5-0.95, default 0.75): ',
      this.config.parser.fuzziness ?? 0.75,
      0.5,
      0.95
    )
  }

  async calibrateSearch () {
    console.log('\n2) SEARCH RELEVANCE WEIGHTS')

    this.config.search.boostFio = await this.promptFloat(
      'FIO boost (1.0-5.0, default 3.0): ',
      this.config.search.boostFio ?? 3.0,
      1.0,
      5.0
    )

    this.config.search.boostYear = await this.promptFloat(
      'Birth year boost (1.0-5.0, default 2.5): ',
      this.config.search.boostYear ?? 2.5,
      1.0,
      5.0
    )

    const smart = new SmartSearch()
    smart.boostFactors.fio = this.config.search.boostFio
    smart.boostFactors.birthYear = this.config.search.boostYear
    smart.fuzzyThreshold = this.config.parser.fuzziness

    const sample = {
      fio: 'Пелешенко Дмитро Валерійович',
      birthYear: '1972',
      city: 'Харків'
    }
    const score = smart.scoreResult(sample, 'Пелешенко Дмитро Харків 1972')
    console.log(`Sample smart score: ${score.score} (${score.rank})`)
  }

  async calibrateTui () {
    console.log('\n3) TUI PERFORMANCE')

    this.config.tui.fpsTarget = await this.promptInt(
      'FPS target (15-120, default 60): ',
      this.config.tui.fpsTarget ?? 60,
      15,
      120
    )

    this.config.tui.compactMode = await this.promptYesNo(
      'Compact mode? (y/n): ',
      this.config.tui.compactMode ?? false
    )
  }

  async calibrateBehavioral () {
    console.log('\n4) BEHAVIORAL NOISE')

    this.config.behavioral.noiseLevel = await this.promptFloat(
      'Organic noise (0.05-0.25, default 0.1): ',
      this.config.behavioral.noiseLevel ?? 0.1,
      0.05,
      0.25
    )
  }

  saveConfig () {
    fs.writeFileSync(this.configFile, JSON.stringify(this.config, null, 2) + '\n')
    console.log(`\nSaved calibration: ${this.configFile}`)
  }

  async run () {
    console.clear()
    console.log('HANNA v3.3.1 CALIBRATION WIZARD')

    await this.calibrateParser()
    await this.calibrateSearch()
    await this.calibrateTui()
    await this.calibrateBehavioral()

    this.saveConfig()
    this.rl.close()

    console.log('\nCalibration complete.')
    console.log('Run: npm run tui:calibrated')
  }
}

new CalibrationWizard().run().catch((err) => {
  console.error(err)
  process.exit(1)
})
