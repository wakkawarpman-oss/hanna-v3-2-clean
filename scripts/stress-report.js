#!/usr/bin/env node
'use strict'

const fs = require('node:fs')
const path = require('node:path')

const reportPath = path.resolve('stress/stress-report.json')
if (!fs.existsSync(reportPath)) {
  console.error('stress/stress-report.json not found')
  process.exit(1)
}

const payload = JSON.parse(fs.readFileSync(reportPath, 'utf8'))
const summary = payload.aggregate || payload.summary || payload

console.log(JSON.stringify(summary, null, 2))
