'use strict'

const assert = require('node:assert/strict')
const { describe, it } = require('node:test')
const { BehavioralMetrics } = require('../components/behavioral-metrics')

describe('BEHAVIORAL METRICS', () => {
  it('active session reaches high engagement', () => {
    const metrics = new BehavioralMetrics()

    metrics.session.startTime = Date.now() - 45000
    for (let i = 0; i < 8; i++) metrics.trackAction('search')
    for (let i = 0; i < 5; i++) metrics.trackAction('result_click')
    for (let i = 0; i < 4; i++) metrics.trackAction('scroll')

    assert.ok(metrics.calculateEngagement() > 85)
  })

  it('bounce session gets low score', () => {
    const metrics = new BehavioralMetrics()
    metrics.session.startTime = Date.now() - 3000
    metrics.trackAction('bounce')
    assert.ok(metrics.calculateEngagement() < 30)
  })
})
