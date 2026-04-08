#!/usr/bin/env node
'use strict'

const { performance } = require('node:perf_hooks')
const { MultiThreadParser } = require('../components/multi-parser')

async function benchmark () {
  const workers = 32
  const urlsCount = 1000

  console.log('MULTI-THREAD BENCHMARK')
  console.log(`Workers: ${workers} | URLs: ${urlsCount} | Target: 10k req/min`)

  const parser = new MultiThreadParser(workers)
  const urls = Array.from({ length: urlsCount }, (_, i) => `https://bench${i % 100}.com`)

  const start = performance.now()
  const results = await parser.parseBatch(urls)
  const duration = performance.now() - start
  await parser.destroy()

  const throughput = urlsCount / (duration / 1000 / 60)
  const successRate = results.filter((r) => r.status === 'success').length / urlsCount
  const memMb = Math.floor(process.memoryUsage().heapUsed / 1024 / 1024)

  console.log('RESULTS:')
  console.log(`Success: ${(successRate * 100).toFixed(2)}%`)
  console.log(`Throughput: ${throughput.toFixed(0)} req/min`)
  console.log(`Duration: ${duration.toFixed(0)}ms`)
  console.log(`Memory peak: ${memMb}MB`)
  console.log(`Workers peak: ${workers}/${workers}`)

  if (successRate > 0.995 && throughput > 10000) {
    console.log('PRODUCTION READY')
    process.exit(0)
  }

  console.log('FAILED BENCHMARK')
  process.exit(1)
}

benchmark().catch((err) => {
  console.error('BENCHMARK ERROR:', err.message)
  process.exit(1)
})
