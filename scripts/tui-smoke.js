#!/usr/bin/env node
'use strict'

const { execSync } = require('node:child_process')

const checks = [
  'node --check hanna-tui.js',
  'node --check components/search-panel.js',
  'node --check components/debug-tui.js',
  'node --check components/smart-results-tui.js'
]

for (const command of checks) {
  execSync(command, { stdio: 'inherit' })
  console.log(`TUI check passed: ${command}`)
}

console.log('TUI smoke checks complete')
