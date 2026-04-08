'use strict'

const blessed = require('blessed')

class EngagementHooks {
  constructor (tui) {
    this.tui = tui
    this.quickActions = null
    this.relatedPanel = null
    this.progressBar = null
  }

  initQuickActions () {
    const { screen, metrics } = this.tui
    this.quickActions = blessed.list({
      parent: screen,
      top: 0,
      left: 0,
      width: '30%',
      height: 6,
      label: ' QUICK ACTIONS ',
      border: { type: 'line', fg: 'cyan' },
      items: ['Save', 'Copy', 'Share', 'Rate', 'New Search'],
      style: { selected: { bg: 'blue' } },
      keys: true,
      mouse: true,
      hidden: true
    })

    this.quickActions.on('select', (item) => {
      metrics.trackAction('result_click', { action: item.getText() })
      if (typeof this.tui.onLog === 'function') {
        this.tui.onLog(`Quick action: ${item.getText()}`)
      }
    })
  }

  initProgressiveDisclosure () {
    const { screen, metrics } = this.tui
    this.relatedPanel = blessed.box({
      parent: screen,
      top: 6,
      left: 0,
      width: '30%',
      height: 6,
      label: ' RELATED ',
      border: { type: 'line', fg: 'cyan' },
      content: 'No related results yet',
      hidden: true
    })

    metrics.onUpdate = () => {
      if (metrics.session.searchQueries >= 2) {
        this.relatedPanel.setContent('Related:\nПелешенко -> Коваленко\nХарків -> Київ')
      }
    }
  }

  initGamification () {
    const { screen, metrics } = this.tui
    this.progressBar = blessed.progressbar({
      parent: screen,
      top: 12,
      left: 0,
      width: '30%',
      height: 3,
      label: ' PROGRESS ',
      border: { type: 'line', fg: 'cyan' },
      filled: 0
    })

    const previous = metrics.onUpdate
    metrics.onUpdate = (payload) => {
      if (typeof previous === 'function') previous(payload)
      this.progressBar.setProgress(payload.score)
    }
  }

  show () {
    this.quickActions?.show()
    this.relatedPanel?.show()
    this.progressBar?.show()
  }

  hide () {
    this.quickActions?.hide()
    this.relatedPanel?.hide()
    this.progressBar?.hide()
  }
}

module.exports = {
  EngagementHooks
}
