#!/usr/bin/env node
'use strict'

const fs = require('node:fs')
const path = require('node:path')
const { LargeFileParser } = require('../components/large-file-parser')

async function main () {
  const dirArg = process.argv[2] || 'test/data'
  const dir = path.resolve(dirArg)

  const files = fs.readdirSync(dir)
    .filter((name) => name.endsWith('.txt'))
    .map((name) => path.join(dir, name))

  const parser = new LargeFileParser()
  const summary = []

  for (const file of files) {
    const started = Date.now()
    const { stats } = await parser.parseFile(file)
    summary.push({ file, elapsedMs: Date.now() - started, stats })
  }

  console.log(JSON.stringify(summary, null, 2))
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
