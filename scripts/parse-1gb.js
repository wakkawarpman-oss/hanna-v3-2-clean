#!/usr/bin/env node
'use strict'

const path = require('node:path')
const { LargeFileParser } = require('../components/large-file-parser')

async function main () {
  const fileArg = process.argv[2]
  if (!fileArg) {
    console.error('Usage: npm run parse:1gb -- <path-to-file>')
    process.exit(1)
  }

  const target = path.resolve(fileArg)
  const parser = new LargeFileParser({ chunkSize: 256 * 1024 })
  const started = process.hrtime.bigint()
  const { stats } = await parser.parseFile(target)
  const ended = process.hrtime.bigint()
  const ms = Number(ended - started) / 1e6

  console.log(JSON.stringify({ file: target, elapsedMs: ms.toFixed(2), stats }, null, 2))
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
