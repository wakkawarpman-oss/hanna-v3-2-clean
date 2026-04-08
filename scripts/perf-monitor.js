#!/usr/bin/env node
'use strict'

setInterval(() => {
  const mem = process.memoryUsage()
  const cpu = process.cpuUsage()

  const stats = {
    heapMb: (mem.heapUsed / 1024 / 1024).toFixed(2),
    rssMb: (mem.rss / 1024 / 1024).toFixed(2),
    uptimeSec: process.uptime().toFixed(1),
    activeHandles: process._getActiveHandles().length,
    cpuUserMs: (cpu.user / 1000).toFixed(1),
    cpuSystemMs: (cpu.system / 1000).toFixed(1)
  }

  console.clear()
  console.table(stats)
}, 2000)
