#!/usr/bin/env node
'use strict'

const path = require('node:path')
const { LargeFileParser } = require('../components/large-file-parser')

async function main () {
  const fileArg = process.argv[2] || 'test/data/100mb.txt'
  const count = Number(process.argv[3] || 10)
  const file = path.resolve(fileArg)

  const parserTasks = Array.from({ length: count }, () => new LargeFileParser().parseFile(file))
  const start = Date.now()
  const results = await Promise.all(parserTasks)
  const elapsedMs = Date.now() - start

  const totalProcessed = results.reduce((sum, r) => sum + (r.stats?.processed || 0), 0)
  console.log(JSON.stringify({
    file,
    runs: count,
    elapsedMs,
    elapsedSec: Number((elapsedMs / 1000).toFixed(2)),
    totalProcessed
  }, null, 2))
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
