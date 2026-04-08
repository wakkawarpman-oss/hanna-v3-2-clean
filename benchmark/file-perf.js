#!/usr/bin/env node
'use strict'

const fs = require('node:fs')
const path = require('node:path')
const { LargeFileParser } = require('../components/large-file-parser')
const { MmapParser } = require('../components/mmap-parser')

async function runOne (name, filePath, parser) {
  const start = process.hrtime.bigint()
  let count = 0

  if (parser instanceof MmapParser) {
    const results = await parser.parseLargeFile(filePath)
    count = results.length
  } else {
    const out = await parser.parseFile(filePath)
    count = out.results.length
  }

  const end = process.hrtime.bigint()
  const durationMs = Number(end - start) / 1e6
  const sizeMb = fs.statSync(filePath).size / 1024 / 1024
  const speed = sizeMb / (durationMs / 1000)

  return { name, durationMs: Number(durationMs.toFixed(2)), count, speedMbSec: Number(speed.toFixed(2)) }
}

async function main () {
  const files = ['10mb.txt', '100mb.txt']
    .map((name) => ({ name, path: path.resolve('test/data', name) }))
    .filter((item) => fs.existsSync(item.path))

  if (files.length === 0) {
    console.error('No benchmark files found. Run: node scripts/gen-test-files.js')
    process.exit(1)
  }

  const table = []
  for (const file of files) {
    table.push(await runOne(`stream-${file.name}`, file.path, new LargeFileParser()))
    table.push(await runOne(`mmap-fallback-${file.name}`, file.path, new MmapParser()))
  }

  console.table(table)
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
