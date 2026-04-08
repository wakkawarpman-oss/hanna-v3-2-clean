#!/usr/bin/env node
'use strict'

const { spawnSync } = require('node:child_process')
const path = require('node:path')

const scenario = path.resolve('stress/api-flood.yml')
const report = path.resolve('stress/stress-report.json')

function run (cmd, args) {
  return spawnSync(cmd, args, { stdio: 'inherit' })
}

const local = run('npx', ['artillery', 'run', scenario, '--output', report])
if (local.status === 0) process.exit(0)

console.error('Artillery run failed. Ensure artillery is installed or reachable via npx.')
process.exit(local.status || 1)
