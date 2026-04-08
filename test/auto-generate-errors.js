'use strict'

const fs = require('node:fs')
const path = require('node:path')
const { SafeParser } = require('../components/search-panel')

function scanErrorFiles (dir = path.join(__dirname, 'data', 'errors')) {
  const files = fs.readdirSync(dir, { withFileTypes: true })
    .filter((entry) => entry.isFile())
    .map((entry) => path.join(dir, entry.name))

  const report = {
    total: files.length,
    passed: 0,
    failed: [],
    low_confidence: []
  }

  for (const file of files) {
    try {
      const content = fs.readFileSync(file, 'utf8')
      const result = new SafeParser().parseSearchInput(content)

      if (result.status === 'ERROR') {
        report.failed.push({ file, error: result.errors[0] })
      } else if (result.confidence < 2) {
        report.low_confidence.push({ file, confidence: result.confidence, status: result.status })
      } else {
        report.passed += 1
      }
    } catch (e) {
      report.failed.push({ file, error: e.message })
    }
  }

  const output = path.join(__dirname, 'parser-error-report.json')
  fs.writeFileSync(output, JSON.stringify(report, null, 2) + '\n')
  console.log(`Processed ${report.total} files, passed ${report.passed}`)
}

scanErrorFiles()
