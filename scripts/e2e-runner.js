#!/usr/bin/env node
'use strict'

const { spawn } = require('node:child_process')
const { buildOptimizedApp } = require('../app-opt')

function runNewman () {
  return new Promise((resolve, reject) => {
    const child = spawn('npx', [
      '--yes',
      'newman',
      'run',
      'collections/e2e.json',
      '--env-var',
      'baseUrl=http://127.0.0.1:3000',
      '--timeout-request',
      '8000',
      '--timeout',
      '20000'
    ], {
      stdio: 'inherit'
    })

    const timer = setTimeout(() => {
      child.kill('SIGKILL')
      reject(new Error('newman run timed out'))
    }, 300000)

    child.on('error', (err) => {
      clearTimeout(timer)
      reject(err)
    })

    child.on('close', (code) => {
      clearTimeout(timer)
      if (code === 0) resolve()
      else reject(new Error(`newman exited with code ${code}`))
    })
  })
}

async function run () {
  const app = await buildOptimizedApp({ logger: false, jwtSecret: 'E2E_RUNNER_SECRET' })

  try {
    await app.listen({ host: '127.0.0.1', port: 3000 })
    await runNewman()
  } finally {
    await app.close()
  }
}

run().catch((err) => {
  console.error('E2E runner failed:', err.message)
  process.exit(1)
})
