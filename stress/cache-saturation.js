#!/usr/bin/env node
'use strict'

const { CachedParser } = require('../components/search-panel-opt')

const parser = new CachedParser({ maxCache: 10000 })
const count = Number(process.argv[2] || 15000)

for (let i = 0; i < count; i++) {
  parser.parseSearchInput(`User${i} Name${i} ${1970 + (i % 50)} Харків 095${String(i).padStart(7, '0')}`)
}

const stats = parser.getStats()
console.log(JSON.stringify(stats, null, 2))
