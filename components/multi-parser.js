'use strict'

const { Worker, isMainThread, parentPort, threadId } = require('node:worker_threads')

function parseUrlTask (url, options = {}) {
  return new Promise((resolve) => {
    const delayMs = Math.max(0, Number(options.delayMs) || 0)

    setTimeout(() => {
      try {
        if (typeof url !== 'string' || url.trim() === '') {
          resolve({ url, status: 'error', error: 'INVALID_URL_EMPTY' })
          return
        }

        const parsed = new URL(url)

        if (parsed.protocol !== 'https:') {
          resolve({ url, status: 'error', error: 'INVALID_URL_PROTOCOL' })
          return
        }

        if (parsed.hostname.includes('error')) {
          resolve({ url, status: 'error', error: 'SIMULATED_UPSTREAM_ERROR' })
          return
        }

        resolve({
          url,
          status: 'success',
          cacheHit: false,
          workerThreadId: threadId,
          data: {
            host: parsed.hostname,
            path: parsed.pathname || '/',
            ts: Date.now()
          }
        })
      } catch (err) {
        resolve({ url, status: 'error', error: err.message || 'INVALID_URL_FORMAT' })
      }
    }, delayMs)
  })
}

class MultiThreadParser {
  constructor (maxWorkers = 8) {
    this.maxWorkers = Math.max(1, Number(maxWorkers) || 1)
    this.activeWorkers = 0
    this.queue = []
    this.results = new Map()
    this.pool = []
    this.nextTaskId = 1
    this.taskMeta = new Map()

    for (let i = 0; i < this.maxWorkers; i++) {
      this.pool.push(this.createWorker())
    }
  }

  createWorker () {
    const worker = new Worker(__filename)
    worker.busy = false
    worker.currentTaskId = null

    worker.on('message', ({ taskId, batchId, result }) => {
      const batch = this.results.get(batchId)
      if (batch) {
        batch.data.push(result)
        batch.completed += 1

        if (batch.completed === batch.total) {
          this.results.delete(batchId)
          batch.resolve(batch.data)
        }
      }

      this.taskMeta.delete(taskId)
      if (worker.busy) {
        worker.busy = false
        worker.currentTaskId = null
        this.activeWorkers = Math.max(0, this.activeWorkers - 1)
      }
      this.processQueue()
    })

    worker.on('error', (err) => {
      const task = worker.currentTaskId ? this.taskMeta.get(worker.currentTaskId) : null
      if (task) {
        const batch = this.results.get(task.batchId)
        if (batch) {
          batch.data.push({ url: task.url, status: 'error', error: err.message || 'WORKER_ERROR' })
          batch.completed += 1

          if (batch.completed === batch.total) {
            this.results.delete(task.batchId)
            batch.resolve(batch.data)
          }
        }
        this.taskMeta.delete(worker.currentTaskId)
      }

      if (worker.busy) {
        worker.busy = false
        worker.currentTaskId = null
        this.activeWorkers = Math.max(0, this.activeWorkers - 1)
      }
      this.processQueue()
    })

    return worker
  }

  async parseBatch (urls, options = {}) {
    const normalizedUrls = Array.isArray(urls) ? urls : []
    if (normalizedUrls.length === 0) {
      return []
    }

    return new Promise((resolve) => {
      const batchId = Date.now() + Math.floor(Math.random() * 10000)
      this.results.set(batchId, {
        completed: 0,
        total: normalizedUrls.length,
        data: [],
        resolve
      })

      for (const url of normalizedUrls) {
        this.queue.push({ url, batchId, options })
      }

      this.processQueue()
    })
  }

  processQueue () {
    while (this.queue.length > 0) {
      const freeWorker = this.pool.find((w) => !w.busy)
      if (!freeWorker) return

      const task = this.queue.shift()
      const taskId = this.nextTaskId++

      freeWorker.busy = true
      freeWorker.currentTaskId = taskId
      this.activeWorkers += 1
      this.taskMeta.set(taskId, task)

      freeWorker.postMessage({ taskId, batchId: task.batchId, url: task.url, options: task.options })
    }
  }

  async destroy () {
    await Promise.all(this.pool.map((worker) => worker.terminate()))
    this.pool = []
  }
}

if (!isMainThread) {
  parentPort.on('message', ({ taskId, batchId, url, options }) => {
    parseUrlTask(url, options)
      .then((result) => {
        parentPort.postMessage({ taskId, batchId, result })
      })
      .catch((err) => {
        parentPort.postMessage({
          taskId,
          batchId,
          result: {
            url,
            status: 'error',
            error: err.message || 'WORKER_FAILURE'
          }
        })
      })
  })
}

module.exports = {
  MultiThreadParser
}
