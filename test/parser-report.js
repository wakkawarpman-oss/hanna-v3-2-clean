#!/usr/bin/env node
'use strict'

const fs = require('node:fs')
const path = require('node:path')
const { SearchPanel } = require('../components/search-panel')

const inputFile = path.join(__dirname, 'data', 'real-examples.json')
const outputFile = path.join(__dirname, 'parser-report.json')

if (!fs.existsSync(inputFile)) {
  console.error('Input file not found:', inputFile)
  process.exit(1)
}

const panel = new SearchPanel()
const testCases = JSON.parse(fs.readFileSync(inputFile, 'utf8'))

const report = {
  generatedAt: new Date().toISOString(),
  totalCases: testCases.length,
  cases: testCases.map(({ id, input }) => {
    const result = panel.parseSearchInput(input)
    return {
      id,
      confidence: result.confidence,
      parsed: result.parsed,
      status: result.confidence >= 4 ? 'HIGH' : result.confidence >= 2 ? 'MEDIUM' : 'LOW'
    }
  })
}

const avg = report.cases.reduce((sum, c) => sum + c.confidence, 0) / report.totalCases
report.averageConfidence = Number(avg.toFixed(2))

fs.writeFileSync(outputFile, JSON.stringify(report, null, 2) + '\n')
console.log(`Parser report generated: ${outputFile}`)
