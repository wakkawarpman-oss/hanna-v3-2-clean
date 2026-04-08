'use strict'

const { parentPort } = require('node:worker_threads')
const { CachedParser } = require('./search-panel-opt')

const parser = new CachedParser({ maxCache: 2000 })

parentPort.on('message', (message) => {
  const { id, text } = message

  try {
    const result = parser.parseSearchInput(text)
    parentPort.postMessage({ id, result })
  } catch (err) {
    parentPort.postMessage({ id, error: err.message || 'Worker parse error' })
  }
})
