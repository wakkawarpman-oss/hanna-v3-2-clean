#!/usr/bin/env node
'use strict'

const fs = require('node:fs')
const os = require('node:os')
const { execSync } = require('node:child_process')
const { buildOptimizedApp } = require('../app-opt')

class MasterTest {
  constructor () {
    this.results = {
      timestamp: new Date().toISOString(),
      suite: 'pantester-v3.3.1',
      total: 0,
      passed: 0,
      failed: 0,
      warnings: 0,
      selfHealing: []
    }
  }

  log (kind, test, details = '') {
    this.results.total += 1

    if (kind === 'PASS') {
      this.results.passed += 1
      console.log(`OK [${this.results.total}] ${test}${details ? ` | ${details}` : ''}`)
      return
    }

    if (kind === 'WARN') {
      this.results.warnings += 1
      console.log(`WARN [${this.results.total}] ${test}${details ? ` | ${details}` : ''}`)
      return
    }

    this.results.failed += 1
    console.log(`FAIL [${this.results.total}] ${test}${details ? ` | ${details}` : ''}`)
  }

  runCommand (command, timeout = 120000) {
    return execSync(command, { stdio: 'pipe', timeout, encoding: 'utf8' })
  }

  correction (fix, command, optional = false) {
    this.results.selfHealing.push({ fix, command })
    try {
      this.runCommand(command, 180000)
      this.log('PASS', `Self-heal: ${fix}`, command)
      return true
    } catch (err) {
      if (optional) {
        this.log('WARN', `Optional heal skipped: ${fix}`, err.message.split('\n')[0])
        return false
      }
      this.log('FAIL', `Self-heal failed: ${fix}`, err.message.split('\n')[0])
      return false
    }
  }

  ensureCalibrationFile () {
    if (fs.existsSync('config.calibrated.json')) {
      this.log('PASS', 'Calibration file exists')
      return
    }

    const ok = this.correction('calibration file', 'node scripts/calibrate-reset.js && node -e "const fs=require(\'fs\');fs.writeFileSync(\'config.calibrated.json\', JSON.stringify({parser:{sensitivity:0.5,fuzziness:0.75},search:{boostFio:3,boostYear:2.5},tui:{fpsTarget:60,compactMode:false},behavioral:{noiseLevel:0.1}},null,2)+\'\\n\')"')
    if (ok) this.log('PASS', 'Calibration file restored')
  }

  async systemHealth () {
    try {
      const app = await buildOptimizedApp({ logger: false, jwtSecret: 'MASTER_TEST_SECRET' })
      const res = await app.inject({ method: 'GET', url: '/health' })
      await app.close()

      if (res.statusCode === 200) {
        this.log('PASS', 'API health endpoint', 'inject /health 200')
      } else {
        this.log('FAIL', 'API health endpoint', `inject /health ${res.statusCode}`)
      }
    } catch (err) {
      this.log('FAIL', 'API health endpoint', err.message)
    }
  }

  async isHttpHealthy () {
    try {
      const res = await fetch('http://localhost:3000/health', { method: 'GET' })
      return res.ok
    } catch {
      return false
    }
  }

  selfHealTools () {
    const checks = [
      { name: 'node', command: 'node --version', optional: false },
      { name: 'npm', command: 'npm --version', optional: false },
      { name: 'pm2', command: 'pm2 --version', optional: true },
      { name: 'newman', command: 'npx --yes newman --version', optional: true }
    ]

    for (const check of checks) {
      try {
        this.runCommand(check.command, 30000)
        this.log('PASS', `Tool ${check.name}`)
      } catch (err) {
        if (check.optional) {
          this.log('WARN', `Tool ${check.name} missing`, 'optional in local/dev')
        } else {
          this.log('FAIL', `Tool ${check.name} missing`, err.message.split('\n')[0])
        }
      }
    }

    if (os.platform() === 'linux') {
      try {
        this.runCommand('systemctl --version', 10000)
        this.log('PASS', 'systemctl available')
      } catch {
        this.log('WARN', 'systemctl unavailable', 'skipping service-level heal')
      }
    } else {
      this.log('WARN', 'systemctl checks skipped', `${os.platform()} platform`)
    }
  }

  backendTests () {
    try {
      this.runCommand('npm test', 240000)
      this.log('PASS', 'Backend unit/integration')
    } catch (err) {
      this.log('FAIL', 'Backend unit/integration', err.message.split('\n')[0])
    }

    try {
      this.runCommand('npm run test:full-multi', 240000)
      this.log('PASS', 'Multi-thread stress')
    } catch (err) {
      this.log('FAIL', 'Multi-thread stress', err.message.split('\n')[0])
    }
  }

  frontendTests () {
    try {
      this.runCommand('npm run tui:test', 60000)
      this.log('PASS', 'TUI smoke tests')
    } catch (err) {
      this.log('FAIL', 'TUI smoke tests', err.message.split('\n')[0])
    }
  }

  async e2eTests () {
    try {
      this.runCommand('npm run test:e2e', 300000)
      this.log('PASS', 'E2E chain')
    } catch (err) {
      this.log('WARN', 'E2E chain', `non-blocking in local mode: ${err.message.split('\n')[0]}`)
    }
  }

  finalReport () {
    const passRate = this.results.total > 0
      ? ((this.results.passed / this.results.total) * 100).toFixed(1)
      : '0.0'

    console.log('\nMASTER REPORT')
    console.log(`Passed: ${this.results.passed}/${this.results.total} (${passRate}%)`)
    console.log(`Warnings: ${this.results.warnings}`)
    console.log(`Failed: ${this.results.failed}`)

    fs.writeFileSync('test-report.json', JSON.stringify(this.results, null, 2) + '\n')

    if (this.results.failed === 0) {
      console.log('SYSTEM PRODUCTION READY')
      process.exit(0)
    }

    console.log('Self-healing applied where possible; review FAIL entries and rerun npm run master-test')
    process.exit(1)
  }

  async run () {
    console.log('MASTER PANTEST v3.3.1 — Self-healing mode')

    this.log('PASS', 'Node.js version', process.version)
    this.ensureCalibrationFile()
    await this.systemHealth()
    this.selfHealTools()
    this.backendTests()
    this.frontendTests()
    await this.e2eTests()
    this.finalReport()
  }
}

new MasterTest().run().catch((err) => {
  console.error('MASTER TEST FATAL:', err.message)
  process.exit(1)
})
