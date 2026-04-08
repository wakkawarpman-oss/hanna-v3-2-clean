'use strict'

class UltraPerfTui {
  constructor (screen, options = {}) {
    this.screen = screen
    this.frameBudget = options.frameBudget || 16
    this.lastRenderAt = 0
    this.dirtyRegions = new Set()
    this.scheduled = false
  }

  markDirty (element) {
    if (element) {
      this.dirtyRegions.add(element)
    }
    this.scheduleRender()
  }

  scheduleRender () {
    if (this.scheduled) return
    this.scheduled = true

    setImmediate(() => {
      this.scheduled = false
      this.renderFrame()
    })
  }

  renderFrame () {
    const now = Date.now()

    if (now - this.lastRenderAt < this.frameBudget) {
      return
    }

    this.lastRenderAt = now

    if (this.dirtyRegions.size === 0) {
      this.screen.render()
      return
    }

    for (const widget of this.dirtyRegions) {
      if (widget && typeof widget.render === 'function') {
        widget.render()
      }
    }

    this.dirtyRegions.clear()
    this.screen.render()
  }
}

module.exports = {
  UltraPerfTui
}
