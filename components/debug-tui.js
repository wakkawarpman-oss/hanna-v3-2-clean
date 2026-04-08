'use strict'

const blessed = require('blessed')
const contrib = require('blessed-contrib')
const { SmartSearch, SearchResults } = require('./smart-search')

class DebugTui {
  constructor (screen, parser, onLog) {
    this.screen = screen
    this.parser = parser
    this.onLog = typeof onLog === 'function' ? onLog : () => {}
    this.visible = false
    this.smartSearch = new SmartSearch()
    this.searchResults = new SearchResults()

    this.debugInput = blessed.textbox({
      parent: screen,
      top: 1,
      left: 2,
      width: '68%',
      height: 5,
      label: ' DEBUG INPUT ',
      border: { type: 'line', fg: 'yellow' },
      style: { fg: 'white', bg: 'black', border: { fg: 'yellow' } },
      inputOnFocus: true,
      keys: true,
      tags: true,
      hidden: true,
      value: ''
    })

    this.toolRoutes = blessed.list({
      parent: screen,
      top: 1,
      left: '71%',
      width: '27%',
      height: 12,
      label: ' TOOL ROUTING ',
      border: { type: 'line', fg: 'yellow' },
      style: { fg: 'white', selected: { bg: 'blue' } },
      keys: true,
      mouse: true,
      tags: true,
      hidden: true,
      items: []
    })

    this.parseResult = contrib.table({
      parent: screen,
      top: 6,
      left: 2,
      width: '68%',
      height: '38%',
      label: ' PARSED RESULT ',
      columnSpacing: 2,
      columnWidth: [12, 32, 10],
      border: { type: 'line', fg: 'yellow' },
      fg: 'white',
      hidden: true
    })

    this.debugTrace = blessed.log({
      parent: screen,
      top: 6,
      left: '71%',
      width: '27%',
      height: '38%',
      label: ' DEBUG TRACE ',
      border: { type: 'line', fg: 'yellow' },
      style: { fg: 'green' },
      keys: true,
      mouse: true,
      vi: true,
      scrollable: true,
      alwaysScroll: true,
      hidden: true
    })

    this.debugInput.key(['enter'], async () => {
      await this.parseCurrentInput()
    })

    this.debugInput.key(['f1'], () => {
      this.loadTestCase()
    })

    this.debugInput.key(['f2'], () => {
      this.clear()
    })

    this.debugInput.key(['C-d'], () => {
      const file = this.parser.dumpDebug('tui-debug-dump.json')
      this.debugTrace.log(`dump saved: ${file}`)
      this.screen.render()
    })

    this.debugInput.key(['escape'], () => {
      this.close()
    })

    this.resetViews()
  }

  resetViews () {
    this.parseResult.setData({
      headers: ['Field', 'Value', 'Status'],
      data: [['-', 'No data', '-']]
    })
    this.toolRoutes.setItems([])
  }

  open () {
    this.visible = true
    this.debugInput.show()
    this.toolRoutes.show()
    this.parseResult.show()
    this.debugTrace.show()
    this.debugInput.focus()
    this.debugTrace.log('debug panel opened')
    this.screen.render()
  }

  close () {
    this.visible = false
    this.debugInput.hide()
    this.toolRoutes.hide()
    this.parseResult.hide()
    this.debugTrace.hide()
    this.screen.render()
  }

  clear () {
    this.debugInput.clearValue()
    this.resetViews()
    this.debugTrace.log('debug cleared')
    this.screen.render()
  }

  loadTestCase () {
    this.debugInput.setValue('Пелешенко Дмитро Валерійович 1972 Харків Гв. Широнинцев 49 ФОП 0958042036')
    this.debugTrace.log('test case loaded')
    this.screen.render()
  }

  async parseCurrentInput () {
    const input = this.debugInput.getValue().trim()
    if (!input) return

    const result = this.parser.parseSearchInput(input)
    const tools = await this.parser.routeToTools(result)
    const scored = tools.map((tool) => {
      const scoring = this.smartSearch.scoreResult(result.parsed, input)
      return {
        parsed: result.parsed,
        tool: tool.name,
        score: scoring.score,
        rank: scoring.rank
      }
    })
    const clusters = this.searchResults.groupResults(scored)

    const rows = [
      ...Object.entries(result.parsed).map(([k, v]) => [k.toUpperCase(), v || '—', v ? 'OK' : 'MISS']),
      ['CONFIDENCE', `${result.confidence}/6`, result.confidence >= 3 ? 'HIGH' : 'LOW'],
      ['STATUS', result.status || 'N/A', '-']
    ]

    if (result.errors && result.errors.length) {
      rows.push(['ERRORS', result.errors.join(', '), 'WARN'])
    }

    if (clusters.length > 0) {
      rows.push(['SMART_TOP', `${clusters[0].score.toFixed(2)} (${clusters[0].bestMatch.rank})`, 'OK'])
      rows.push(['SMART_CLUSTERS', String(clusters.length), 'OK'])
    }

    this.parseResult.setData({
      headers: ['Field', 'Value', 'Status'],
      data: rows
    })

    this.toolRoutes.setItems(
      clusters.length
        ? clusters.map((c, idx) => `${idx + 1}. ${c.score.toFixed(2)} ${c.bestMatch.tool}`)
        : tools.map((t) => `${t.status} ${t.name}`)
    )
    this.debugTrace.log(`parsed: confidence=${result.confidence}, status=${result.status}`)
    this.onLog(`Debug parse: ${result.confidence}/6 (${tools.length} tools)`)
    this.screen.render()
  }
}

module.exports = {
  DebugTui
}
