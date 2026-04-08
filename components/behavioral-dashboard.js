'use strict'

class BehavioralDashboard {
  constructor (tableWidget, metrics) {
    this.tableWidget = tableWidget
    this.metrics = metrics
  }

  displayMetrics () {
    const m = this.metrics.session
    const engagement = this.metrics.calculateEngagement()

    this.tableWidget.setData({
      headers: ['Метрика', 'Значення', 'Статус'],
      data: [
        ['Engagement Score', `${engagement}/100`, engagement > 70 ? 'OK' : 'WARN'],
        ['Dwell Time', `${Math.round((Date.now() - m.startTime) / 1000)}s`, 'OK'],
        ['Search Queries', String(m.searchQueries), m.searchQueries > 2 ? 'OK' : 'WARN'],
        ['Result Clicks', String(m.resultClicks), m.resultClicks > 3 ? 'OK' : 'LOW'],
        ['Scroll Depth', `${Math.min(100, m.scrolls * 20)}%`, m.scrolls > 3 ? 'OK' : 'WARN'],
        ['Bounce Risk', m.bounce ? 'HIGH' : 'LOW', m.bounce ? 'HIGH' : 'LOW']
      ]
    })
  }
}

module.exports = {
  BehavioralDashboard
}
