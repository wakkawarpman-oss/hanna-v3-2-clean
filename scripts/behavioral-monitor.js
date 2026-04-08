#!/usr/bin/env node
'use strict'

const { BehavioralMetrics } = require('../components/behavioral-metrics')

const metrics = new BehavioralMetrics()
metrics.session.startTime = Date.now() - 20000

setInterval(() => {
  metrics.trackAction('search')
  metrics.trackAction('scroll')
  metrics.trackAction('result_click')

  const score = metrics.calculateEngagement()
  console.clear()
  console.table({
    engagement: score,
    dwellSec: Math.round(metrics.session.dwellTime),
    interactions: metrics.session.interactions,
    searchQueries: metrics.session.searchQueries,
    resultClicks: metrics.session.resultClicks,
    scrolls: metrics.session.scrolls
  })
}, 2000)
