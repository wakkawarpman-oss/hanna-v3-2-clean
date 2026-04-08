#!/usr/bin/env node
'use strict'

const fs = require('node:fs')
const path = require('node:path')
const { CalibratedParser } = require('../components/calibrated-parser')

const configPath = path.resolve('config.calibrated.json')
if (!fs.existsSync(configPath)) {
  console.error('config.calibrated.json not found. Run: npm run calibrate')
  process.exit(1)
}

const config = JSON.parse(fs.readFileSync(configPath, 'utf8'))
const parser = new CalibratedParser(configPath)

const testCases = [
  'Пелешенко Дмитро Валерійович 1972',
  '0958042036 Харків Широнинцев',
  'ФОП Коваленко вул Сумська'
]

console.log('CALIBRATION VALIDATION\n')
for (const [i, input] of testCases.entries()) {
  const result = parser.parseSearchInput(input)
  const score = result.relevance?.score ?? 0
  console.log(`${i + 1}. "${input}" -> confidence=${result.confidence.toFixed(2)} score=${score.toFixed(2)} rank=${result.relevance?.rank || 'D'}`)
}

console.log('\nConfig:')
console.log(JSON.stringify(config, null, 2))
