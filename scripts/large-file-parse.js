#!/usr/bin/env node
'use strict'

const path = require('node:path')
const { LargeFileParser } = require('../components/large-file-parser')

async function main () {
  const fileArg = process.argv[2]
  if (!fileArg) {
    console.error('Usage: npm run parse:large -- <path-to-file>')
    process.exit(1)
  }

  const target = path.resolve(fileArg)
  const parser = new LargeFileParser()
  const startedAt = Date.now()

  const { results, stats } = await parser.parseFile(target)
  const elapsedMs = Date.now() - startedAt

  console.log(JSON.stringify({
    file: target,
    elapsedMs,
    stats,
    resultCount: results.length
  }, null, 2))
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
