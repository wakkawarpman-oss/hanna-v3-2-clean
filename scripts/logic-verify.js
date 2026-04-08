#!/usr/bin/env node
'use strict'

const { execSync } = require('node:child_process')
const { Calibration } = require('../components/calibration')
const { buildOptimizedApp } = require('../app-opt')

function runStep (label, command) {
  process.stdout.write(`${label}... `)
  execSync(command, { stdio: 'inherit' })
}

async function verifyHealthViaInject () {
  const app = await buildOptimizedApp({ logger: false, jwtSecret: 'LOGIC_VERIFY_SECRET' })
  try {
    const res = await app.inject({ method: 'GET', url: '/health' })
    if (res.statusCode !== 200) {
      throw new Error(`/health returned ${res.statusCode}`)
    }
    const body = res.json()
    if (body.status !== 'healthy') {
      throw new Error(`health status is ${body.status}`)
    }
  } finally {
    await app.close()
  }
}

async function maxLogicCheck () {
  console.log('MAX LOGIC VERIFICATION v3.3.1')

  runStep('1) UNIT COVERAGE', 'npm run test:coverage')
  runStep('2) INTEGRATION', 'npm run test:integration')
  runStep('3) STRESS', 'npm run test:stress')

  process.stdout.write('4) CALIBRATION... ')
  const cal = await Calibration.fullCheck()
  if (!cal.allGreen) {
    throw new Error(`Calibration failed: ${JSON.stringify(cal.scores)}`)
  }
  console.log('OK', cal.scores)

  runStep('5) GOLDEN DATASET', 'npm run test:golden')

  process.stdout.write('6) HEALTH ENDPOINT... ')
  await verifyHealthViaInject()
  console.log('OK')

  console.log('ALL LOGIC VERIFIED')
  console.log('Coverage + Integration + Stress + Calibration + Golden + Health = GREEN')
}

maxLogicCheck().catch((err) => {
  console.error('LOGIC FAILED:', err.message)
  process.exit(1)
})
