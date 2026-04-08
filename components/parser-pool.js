'use strict'

const os = require('node:os')
const path = require('node:path')
const { Worker } = require('node:worker_threads')

class ParserPool {
  constructor (size = Math.max(2, Math.min(4, os.cpus().length)), workerFile = path.join(__dirname, 'parser-worker.js')) {
    this.size = size
    this.workers = []
    this.queue = []
    this.nextId = 1

    for (let i = 0; i < size; i++) {
      this.workers.push(this.createWorker(workerFile))
    }
  }

  createWorker (workerFile) {
    const worker = new Worker(workerFile)
    worker.busy = false
    worker.callbacks = new Map()

    worker.on('message', (message) => {
      const { id, result, error } = message
      const cb = worker.callbacks.get(id)
      if (!cb) return

      worker.callbacks.delete(id)
      worker.busy = false

      if (error) cb.reject(new Error(error))
      else cb.resolve(result)

      this.pumpQueue()
    })

    worker.on('error', (err) => {
      worker.busy = false
      for (const [, cb] of worker.callbacks) cb.reject(err)
      worker.callbacks.clear()
      this.pumpQueue()
    })

    return worker
  }

  parse (text) {
    return new Promise((resolve, reject) => {
      this.queue.push({ text, resolve, reject })
      this.pumpQueue()
    })
  }

  pumpQueue () {
    const freeWorker = this.workers.find((w) => !w.busy)
    if (!freeWorker) return

    const task = this.queue.shift()
    if (!task) return

    const id = this.nextId++
    freeWorker.busy = true
    freeWorker.callbacks.set(id, { resolve: task.resolve, reject: task.reject })
    freeWorker.postMessage({ id, text: task.text })
  }

  async destroy () {
    await Promise.all(this.workers.map((w) => w.terminate()))
  }
}

module.exports = {
  ParserPool
}
