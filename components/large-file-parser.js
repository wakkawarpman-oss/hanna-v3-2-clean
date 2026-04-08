'use strict'

const fs = require('node:fs')
const { Transform } = require('node:stream')
const { pipeline } = require('node:stream/promises')
const { SafeParser } = require('./search-panel')

class LargeFileParser {
  constructor (options = {}) {
    this.chunkSize = options.chunkSize || 64 * 1024
    this.maxLineLength = options.maxLineLength || 10 * 1024
    this.parser = options.parser || new SafeParser()
    this.stats = { processed: 0, matched: 0, skipped: 0 }
  }

  async parseFile (filePath) {
    const results = []
    let pending = ''

    const parseTransform = new Transform({
      readableObjectMode: false,
      transform: (chunk, _enc, callback) => {
        try {
          const text = pending + chunk.toString('utf8')
          const lines = text.split('\n')
          pending = lines.pop() || ''

          for (const line of lines) {
            const trimmed = line.trim()
            if (!trimmed) continue

            if (trimmed.length > this.maxLineLength) {
              this.stats.skipped += 1
              continue
            }

            this.stats.processed += 1
            const parsed = this.parser.parseSearchInput(trimmed)
            if (parsed.confidence >= 2) {
              results.push(parsed)
              this.stats.matched += 1
            }
          }

          callback()
        } catch (err) {
          callback(err)
        }
      },
      flush: (callback) => {
        try {
          const tail = pending.trim()
          if (tail) {
            this.stats.processed += 1
            const parsed = this.parser.parseSearchInput(tail)
            if (parsed.confidence >= 2) {
              results.push(parsed)
              this.stats.matched += 1
            }
          }
          callback()
        } catch (err) {
          callback(err)
        }
      }
    })

    const readStream = fs.createReadStream(filePath, {
      encoding: 'utf8',
      highWaterMark: this.chunkSize
    })

    await pipeline(readStream, parseTransform)
    return { results, stats: this.stats }
  }
}

module.exports = {
  LargeFileParser
}
