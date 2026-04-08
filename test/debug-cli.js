#!/usr/bin/env node
'use strict'

const readline = require('node:readline')
const { DebugParser } = require('../components/search-panel')

console.log('INTERACTIVE PARSER DEBUGGER')
console.log('Type text to parse, use "dump" to save logs, Ctrl+C to exit')

const parser = new DebugParser(true)
const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout
})

rl.on('line', async (input) => {
  if (input.trim() === 'dump') {
    const filename = parser.dumpDebug()
    console.log(`Debug dump: ${filename}`)
    return
  }

  if (!input.trim()) return

  const result = parser.parseSearchInput(input)
  const tools = await parser.routeToTools(result)

  console.log('RESULT:', {
    confidence: result.confidence,
    status: result.status,
    parsed: result.parsed,
    errors: result.errors || []
  })

  const trace = parser.getDebugReport('DBG-').slice(-4)
  console.log('TRACE:', JSON.stringify(trace, null, 2))
  console.log('TOOLS:', tools.map((t) => t.name).join(', ') || '-')
})
