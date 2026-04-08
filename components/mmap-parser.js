'use strict'

const fs = require('node:fs')
const { SafeParser } = require('./search-panel')

class MmapParser {
  constructor (options = {}) {
    this.parser = options.parser || new SafeParser()
  }

  async parseLargeFile (filePath) {
    // Node stable runtime does not provide portable mmap bindings.
    // This fallback keeps the same API and processes the file in-memory.
    const text = fs.readFileSync(filePath, 'utf8')
    const lines = text.split('\n')
    const results = []

    for (const line of lines) {
      const trimmed = line.trim()
      if (!trimmed) continue
      const parsed = this.parser.parseSearchInput(trimmed)
      if (parsed.confidence >= 2) {
        results.push(parsed)
      }
    }

    return results
  }
}

module.exports = {
  MmapParser
}
