'use strict'

const { SafeParser } = require('./search-panel')

class CachedParser extends SafeParser {
  constructor (options = {}) {
    super()
    this.cache = new Map()
    this.maxCache = options.maxCache || 10000
    this.cacheHits = 0
    this.cacheMisses = 0
  }

  hash (text) {
    let hash = 5381
    for (let i = 0; i < text.length; i++) {
      hash = ((hash << 5) + hash) + text.charCodeAt(i)
    }
    return (hash >>> 0).toString(16)
  }

  parseSearchInput (input) {
    const keySource = Buffer.isBuffer(input) ? input.toString('utf8') : String(input ?? '')
    const key = this.hash(keySource)

    if (this.cache.has(key)) {
      const value = this.cache.get(key)
      this.cache.delete(key)
      this.cache.set(key, value)
      this.cacheHits += 1
      return value
    }

    const result = super.parseSearchInput(input)
    this.cache.set(key, result)
    this.cacheMisses += 1

    if (this.cache.size > this.maxCache) {
      const firstKey = this.cache.keys().next().value
      this.cache.delete(firstKey)
    }

    return result
  }

  getStats () {
    return {
      size: this.cache.size,
      maxCache: this.maxCache,
      hits: this.cacheHits,
      misses: this.cacheMisses
    }
  }
}

module.exports = {
  CachedParser
}
