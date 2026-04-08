'use strict'

class BehavioralMetrics {
  constructor () {
    this.session = {
      startTime: Date.now(),
      interactions: 0,
      dwellTime: 0,
      scrolls: 0,
      searchQueries: 0,
      resultClicks: 0,
      navigation: 0,
      bounce: false
    }

    this.engagementScore = 0
    this.onUpdate = null
    this.metricsPanel = null
  }

  attachPanel (panel) {
    this.metricsPanel = panel
    this.updateLiveMetrics()
  }

  calculateEngagement () {
    const sessionDuration = (Date.now() - this.session.startTime) / 1000
    this.session.dwellTime = sessionDuration

    const dwellScore = Math.min(sessionDuration / 30, 1) * 25
    const interactionScore = Math.min(this.session.interactions / 10, 1) * 25
    const scrollScore = Math.min(this.session.scrolls / 5, 1) * 20
    const queryScore = Math.min(this.session.searchQueries / 3, 1) * 20
    const clickScore = Math.min(this.session.resultClicks / 5, 1) * 10

    this.engagementScore = Math.round(dwellScore + interactionScore + scrollScore + queryScore + clickScore)

    if (this.session.bounce) {
      this.engagementScore = Math.round(this.engagementScore * 0.3)
    }

    return this.engagementScore
  }

  trackAction (action, metadata = {}) {
    this.session.interactions += 1

    switch (action) {
      case 'search':
        this.session.searchQueries += 1
        break
      case 'result_click':
        this.session.resultClicks += 1
        break
      case 'scroll':
        this.session.scrolls += 1
        break
      case 'navigate':
        this.session.navigation += 1
        break
      case 'bounce':
        this.session.bounce = true
        break
      default:
        break
    }

    void metadata
    this.updateLiveMetrics()
  }

  updateLiveMetrics () {
    const score = this.calculateEngagement()
    const status = score > 80 ? 'EXCELLENT' : score > 60 ? 'GOOD' : score > 40 ? 'OK' : 'POOR'

    if (this.metricsPanel) {
      this.metricsPanel.setContent([
        `Engagement: ${score}/100 ${status}`,
        `Dwell: ${Math.round(this.session.dwellTime)}s`,
        `Queries: ${this.session.searchQueries}`,
        `Clicks: ${this.session.resultClicks}`,
        `Scrolls: ${this.session.scrolls}`
      ].join('\n'))
    }

    if (typeof this.onUpdate === 'function') {
      this.onUpdate({ score, session: this.session })
    }
  }
}

module.exports = {
  BehavioralMetrics
}
